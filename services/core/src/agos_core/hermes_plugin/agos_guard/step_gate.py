"""A team automation step's "Only if" lines, checked the moment the step starts.

Hermes's dispatcher starts a step's card once its parents are done (its parents =
the steps it waits on) and spawns the step agent's worker. Before that worker's
first model call (Hermes's `pre_llm_call`), this module reads the step's lines
and the run's values that the run script wrote beside the board
(engine/automation_run.py keep_run: `<root>/agos-automations/<automation>.runs/
<run>.only-if.json`), and when a line doesn't hold:
- completes the card with Hermes's own `complete_task`, under the worker's own run
  id, result and summary `agos-skipped: <plain reason>` (the cards waiting on it
  are released by Hermes as for any done card);
- vetoes the turn (`{"action": "block"}`): Hermes then makes no model request, no
  compaction, no title, no memory prefetch (agent/turn_context.py).

Lines (engine/step_conditions.py): match lines on the run's values (`payload.<path>`
of a webhook delivery, or a variable), and check lines (a /workspace script run in
this worker's own sandbox through Hermes's terminal; its last line says YES/AH or
NO/LA). When in doubt the step runs: no file, an unreadable file, a check that
fails, times out or gives no answer, a card Hermes won't complete.

Owns: deciding a step's lines and closing its card as skipped.
Must not: decide anything for a card that isn't an automation step with lines.
Runs inside Hermes: imports no agos_core package, standard library + Hermes only.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import shlex
import time
from os import _exit as end_process  # the stdlib's immediate exit (no Hermes name)
from pathlib import Path
from typing import Any

__all__ = [
    "CHECK_WAIT_S",
    "MARK",
    "answer_of",
    "card_parts",
    "match_reason",
    "pre_llm_call",
    "verdict",
]

log = logging.getLogger("agos_guard")

MARK = "agos-skipped:"  # the contract with Runs (lane auto-c): result text "agos-skipped: <why>"
AUTOMATION_KEY = "agos-automation:"
# Hermes bounds pre_llm_call (plugins.hook_callback_timeout, 30 s by default) and
# drops a callback that runs longer: a check gets less, and nothing is closed late.
CHECK_WAIT_S = 18
CLOSE_BEFORE_S = 25
_YES, _NO = frozenset({"YES", "AH"}), frozenset({"NO", "LA"})
_WORD = re.compile(r"[A-Za-z]+")
_checked: set[str] = set()  # cards this worker already decided (one check per card)


# ---- pure: the lines ------------------------------------------------------------------


def card_parts(key: str) -> tuple[str, str, str] | None:
    """(automation, run, step) of a run card's idempotency key."""
    if not key.startswith(AUTOMATION_KEY):
        return None
    parts = key[len(AUTOMATION_KEY) :].split(":")
    if len(parts) != 4 or not all(parts):
        return None
    automation, run, _source, step = parts
    return (automation, run, step) if automation.isdigit() else None


def _at(data: Any, path: str) -> Any:
    found = data
    for part in path.split("."):
        if isinstance(found, dict):
            found = found.get(part)
        elif isinstance(found, list) and part.isdigit() and int(part) < len(found):
            found = found[int(part)]
        else:
            return None
    return found


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _holds(line: dict[str, Any], value: str) -> bool:
    got = value.strip().casefold()
    wanted = [str(v).strip().casefold() for v in line.get("values") or []]
    op = str(line.get("op") or "is")
    if op == "is":
        return got in wanted
    if op == "is_not":
        return got not in wanted
    found = any(w and w in got for w in wanted)
    return found if op == "contains" else not found


def _shown(field: str) -> str:
    return field[len("payload.") :] if field.startswith("payload.") else field


_OP_WORDS = {
    "is": "is one of",
    "is_not": "is not one of",
    "contains": "contains",
    "not_contains": "doesn't contain",
}


def match_reason(
    lines: list[dict[str, Any]], values: dict[str, Any], payloads: list[Any]
) -> str | None:
    """Why the step must not start (its first match line that fails), or None when
    they all hold. A webhook run with several deliveries starts the step when ANY of
    them makes every line hold; a run with no delivery can't judge payload lines
    (they hold)."""
    matches = [line for line in lines if "field" in line]
    if not matches:
        return None
    failed: tuple[dict[str, Any], str] | None = None
    for payload in payloads or [None]:
        failed = None
        for line in matches:
            field = str(line["field"])
            if field.startswith("payload."):
                if payload is None or (isinstance(payload, dict) and payload.get("agos_too_big")):
                    continue
                value = _text(_at(payload, field[len("payload.") :]))
            else:
                value = _text(values.get(field))
            if not _holds(line, value):
                failed = (line, value)
                break
        if failed is None:
            return None
    assert failed is not None
    line, value = failed
    wanted = ", ".join(str(v) for v in line.get("values") or [])
    op = _OP_WORDS.get(str(line.get("op") or "is"), "is one of")
    return f"Only if {_shown(str(line['field']))} {op} {wanted} (this run: {value or 'empty'})"


def answer_of(output: str) -> bool | None:
    """A check's answer, from its last non-empty line: YES/AH = True, NO/LA = False,
    anything else None (unsure)."""
    lines = [line for line in str(output or "").splitlines() if line.strip()]
    if not lines:
        return None
    words = {w.upper() for w in _WORD.findall(lines[-1])}
    yes, no = bool(words & _YES), bool(words & _NO)
    return None if yes == no else yes


# ---- Hermes: the card, the sandbox -----------------------------------------------------


def _run_check(check: str, task_id: str) -> tuple[bool | None, str]:
    """A check line in this worker's own sandbox (Hermes's terminal, its configured
    backend: the member's container), with /workspace as its folder."""
    from tools.terminal_tool import terminal_tool  # type: ignore[import-not-found]

    words = shlex.split(check)
    argv = ["python3", *words] if words and words[0].endswith(".py") else words
    raw = terminal_tool(
        command=shlex.join(argv),
        timeout=CHECK_WAIT_S,
        task_id=task_id or None,
        workdir="/workspace",
    )
    try:
        done = json.loads(raw)
    except (TypeError, ValueError):
        return None, "no answer"
    if not isinstance(done, dict) or int(done.get("exit_code") or 0) != 0 or done.get("error"):
        return None, "it failed"
    output = str(done.get("output") or "")
    last = next((x.strip() for x in reversed(output.splitlines()) if x.strip()), "")
    return answer_of(output), last[:120]


def _lines_of(kb: Any, conn: Any, card: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    task = kb.get_task(conn, card)
    parts = card_parts(str(getattr(task, "idempotency_key", "") or ""))
    if parts is None:
        return [], {}
    automation, run, step = parts
    path = (
        Path(kb.kanban_home()) / "agos-automations" / f"{automation}.runs" / f"{run}.only-if.json"
    )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [], {}  # no lines in this run (or not readable: the step runs)
    if not isinstance(data, dict):
        return [], {}
    lines = (data.get("only_if") or {}).get(step) or []
    return [line for line in lines if isinstance(line, dict)], data


def verdict(card: str, task_id: str = "") -> str | None:
    """`agos-skipped: <why>` when this card's step must not start, else None."""
    from hermes_cli import kanban_db as kb  # type: ignore[import-not-found]
    from hermes_cli import kanban_db_connect as kbc

    conn = kbc.connect()
    try:
        lines, data = _lines_of(kb, conn, card)
        if not lines:
            return None
        raw_values, raw_payloads = data.get("values"), data.get("payloads")
        values: dict[str, Any] = raw_values if isinstance(raw_values, dict) else {}
        payloads: list[Any] = raw_payloads if isinstance(raw_payloads, list) else []
        why = match_reason(lines, values, payloads)
        if why is None:
            for line in (x for x in lines if "check" in x):
                said, last = _run_check(str(line["check"]), task_id)
                if said is False:
                    why = f"{str(line['check']).split(' ')[0]} said {last or 'no'}"
                    break
        return None if why is None else f"{MARK} {why}"
    finally:
        conn.close()


def _close(card: str, reason: str) -> bool:
    """The card done as skipped, under this worker's own run (Hermes's fence)."""
    from hermes_cli import kanban_db as kb
    from hermes_cli import kanban_db_connect as kbc

    raw = os.environ.get("HERMES_KANBAN_RUN_ID", "")
    run = int(raw) if raw.isdigit() else None
    conn = kbc.connect()
    try:
        return bool(
            kb.complete_task(conn, card, result=reason, summary=reason, expected_run_id=run)
        )
    finally:
        conn.close()


def _veto_supported() -> bool:
    """This Hermes stops a turn on a pre_llm_call `{"action": "block"}` before any
    model request (H: agent/turn_context.py PRE_LLM_BLOCK_EXIT_REASON, #57364). An
    older Hermes ignores the answer and would call the model anyway."""
    try:
        from agent import turn_context  # type: ignore[import-not-found]
    except ImportError:
        return False
    return hasattr(turn_context, "PRE_LLM_BLOCK_EXIT_REASON")


def _end_worker(task_id: str, checked: bool) -> None:
    """An older Hermes (no veto): the card is already done, so this card's own worker
    process ends here, before its first model call (Hermes's dispatcher reads a done
    card's worker exit as clean). Its sandbox, when a check started one, goes first."""
    if checked:
        try:
            from tools.terminal_tool_lifecycle import cleanup_vm  # type: ignore[import-not-found]

            cleanup_vm(task_id)
        except Exception:
            log.debug("AGOS: sandbox of %s left to Hermes's cleanup", task_id, exc_info=True)
    for handler in logging.getLogger().handlers:
        with contextlib.suppress(Exception):
            handler.flush()
    end_process(0)


def pre_llm_call(
    task_id: str = "", is_first_turn: bool = True, parent_session_id: str = "", **_: Any
) -> dict[str, str] | None:
    """Hermes's pre_llm_call: a step that must not start ends here, before any model
    call. Only the worker's own first turn (never a subagent's, never a later turn).
    Any error = the step runs (as before Only if existed)."""
    card = os.environ.get("HERMES_KANBAN_TASK", "")
    if not card or card in _checked or not is_first_turn or parent_session_id:
        return None
    _checked.add(card)
    started = time.monotonic()
    try:
        reason = verdict(card, str(task_id or ""))
        if reason is None or time.monotonic() - started > CLOSE_BEFORE_S:
            return None
        if not _close(card, reason):
            return None
    except Exception:
        log.warning("AGOS: Only if of card %s not checked; the step runs", card, exc_info=True)
        return None
    log.info("AGOS: card %s skipped before any model call: %s", card, reason)
    if not _veto_supported():
        _end_worker(str(task_id or ""), checked=reason.startswith(f"{MARK} /workspace/"))
    return {"action": "block", "message": reason}
