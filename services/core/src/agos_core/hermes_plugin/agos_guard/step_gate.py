"""A team automation step's "Only if" lines, checked the moment the step starts.

Hermes's dispatcher starts a step's card once its parents are done (its parents =
the steps it waits on) and spawns the step agent's worker. Before that worker's
first model call (Hermes's `pre_llm_call`), this module reads, beside the board in
the workspace's root (never under the files folder the sandboxes see as /workspace):
- the step's lines from the automation as AGOS saved it
  (`<root>/agos-automations/<automation>.lines.json`, engine/step_conditions.py
  keep_saved), each line checked again by the save rules (`valid_lines`);
- only the run's values and deliveries from the run's file (engine/automation_run.py
  keep_run: `<root>/agos-automations/<automation>.runs/<run>.only-if.json`), found
  from a card key whose parts are exactly what the run script makes (`card_parts`),
  never through a link or outside that folder;
and decides once per card: a later attempt of the same card (a retry, an unblock,
a review's rework) never checks again, it runs. When a line doesn't hold:
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
import posixpath
import re
import shlex
import time
from collections.abc import Iterator
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
    "valid_lines",
    "verdict",
]

log = logging.getLogger("agos_guard")

MARK = "agos-skipped:"  # the contract with Runs (lane auto-c): result text "agos-skipped: <why>"
AUTOMATION_KEY = "agos-automation:"
# Hermes bounds pre_llm_call (plugins.hook_callback_timeout, 30 s by default, the
# owner's "A stuck plugin step") and drops a callback that runs longer: a check gets
# less, and a card is closed only within that wait (_close_budget).
CHECK_WAIT_S = 18
CLOSE_BEFORE_S = 25
_YES, _NO = frozenset({"YES", "AH"}), frozenset({"NO", "LA"})
_WORD = re.compile(r"[A-Za-z]+")
_checked: set[str] = set()  # cards this worker already decided (one check per card)
# The parts of a run card's key, exactly as engine/automation_run.py start() makes
# them: run = datetime.strftime("%Y%m%dT%H%M%S%fZ"), source, step key (team_steps).
_RUN_ID = re.compile(r"\d{8}T\d{12}Z")
_SOURCES = frozenset({"manual", "schedule", "webhook"})
_STEP_KEY = re.compile(r"[a-z0-9][a-z0-9_-]{0,30}")
# The save rules of engine/step_conditions.py (the plugin can't import agos_core;
# tests/test_step_only_if_safety.py keeps the two in step).
_FIELD = re.compile(r"payload(\.[A-Za-z0-9_-]{1,60}){1,12}|[a-z][a-z0-9_]{0,39}")
_SHELL = re.compile(r"[;&|$`<>(){}\\\n\r*?!~'\"]")
_OPS = ("is", "is_not", "contains", "not_contains")
_MAX_LINES = 20


# ---- pure: the lines ------------------------------------------------------------------


def card_parts(key: str) -> tuple[str, str, str] | None:
    """(automation, run, step) of a run card's idempotency key."""
    if not key.startswith(AUTOMATION_KEY):
        return None
    parts = key[len(AUTOMATION_KEY) :].split(":")
    if len(parts) != 4 or not all(parts):
        return None
    automation, run, source, step = parts
    if not (
        automation.isdigit()
        and _RUN_ID.fullmatch(run)
        and source in _SOURCES
        and _STEP_KEY.fullmatch(step)
    ):
        return None
    return automation, run, step


def _valid_check(text: Any) -> dict[str, str] | None:
    if not isinstance(text, str) or not text.strip() or len(text.strip()) > 300:
        return None
    text = text.strip()
    if _SHELL.search(text):
        return None
    try:
        words = shlex.split(text)
    except ValueError:
        return None
    if not words:
        return None
    path = posixpath.normpath(words[0])
    if not path.startswith("/workspace/") or ".." in words[0].split("/"):
        return None
    return {"check": shlex.join([path, *words[1:]])}


def _valid_match(line: dict[str, Any]) -> dict[str, Any] | None:
    if set(line) - {"field", "op", "values"}:
        return None
    field = str(line.get("field") or "").strip()
    if field.startswith("{") and field.endswith("}"):
        field = field[1:-1].strip()
    op = str(line.get("op") or "is").strip().lower()
    raw = line.get("values")
    values = raw if isinstance(raw, list) else [raw] if raw not in (None, "") else []
    kept = list(dict.fromkeys(str(v).strip()[:200] for v in values if str(v).strip()))
    if not _FIELD.fullmatch(field) or op not in _OPS or not kept or len(kept) > 100:
        return None
    return {"field": field, "op": op, "values": kept}


def valid_lines(raw: Any) -> list[dict[str, Any]] | None:
    """A step's lines read back by the save rules (as save keeps them), or None when
    any line breaks them: such lines are never run (the step runs)."""
    if not isinstance(raw, list) or len(raw) > _MAX_LINES:
        return None
    out: list[dict[str, Any]] = []
    for line in raw:
        if not isinstance(line, dict):
            return None
        line = {k: v for k, v in line.items() if v not in (None, "", [])}
        if "check" in line:
            one: dict[str, Any] | None = (
                _valid_check(line["check"]) if set(line) == {"check"} else None
            )
        else:
            one = _valid_match(line)
        if one is None:
            return None
        out.append(one)
    return out


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
                # None: a delivery too big to keep (or no delivery): it can't be judged.
                # {"agos_too_big": true} alone: how run files said it before.
                if payload is None or payload == {"agos_too_big": True}:
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


def _run_check(check: str, task_id: str) -> tuple[bool | None, str, Any]:
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
        return None, "no answer", None
    if not isinstance(done, dict):
        return None, "no answer", None
    code = done.get("exit_code")
    if int(code or 0) != 0 or done.get("error"):
        return None, "it failed", code
    output = str(done.get("output") or "")
    last = next((x.strip() for x in reversed(output.splitlines()) if x.strip()), "")
    return answer_of(output), last[:120], code


@contextlib.contextmanager
def _shared_lock(folder: Path) -> Iterator[None]:
    """Read while no delivery is being added (the run script's lock on the runs
    folder, engine/automation_run.py _locked); no lock file = nobody writes."""
    try:
        import fcntl
    except ImportError:  # no flock on this system: read as is
        yield
        return
    try:
        handle = (folder / ".lock").open("rb")
    except OSError:
        yield
        return
    with handle:
        deadline = time.monotonic() + 3
        while True:
            try:
                fcntl.flock(handle, fcntl.LOCK_SH | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() > deadline:
                    break  # read as is: the worst case is one delivery less to judge
                time.sleep(0.05)
        yield


def _json_in(folder: Path, name: str) -> Any:
    """A JSON file AGOS's side wrote in `folder` (None: missing, unreadable, a link,
    or not right inside that folder)."""
    path = folder / name
    try:
        if folder.is_symlink() or path.is_symlink():
            return None
        real, base = path.resolve(strict=True), folder.resolve(strict=True)
        if real.parent != base or not real.is_file():
            return None
        return json.loads(real.read_text(encoding="utf-8"))
    except (OSError, ValueError, RuntimeError):
        return None


def _lines_of(kb: Any, conn: Any, card: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """The step's saved lines (checked again) and its run's file; ([], {}) = it runs."""
    task = kb.get_task(conn, card)
    parts = card_parts(str(getattr(task, "idempotency_key", "") or ""))
    if parts is None:
        return [], {}
    automation, run, step = parts
    home = Path(kb.kanban_db_path()).parent / "agos-automations"
    saved = _json_in(home, f"{automation}.lines.json")
    raw = saved.get(step) if isinstance(saved, dict) else None
    if not raw:
        return [], {}  # no saved line for this step: it always runs
    lines = valid_lines(raw)
    if lines is None:
        log.warning("AGOS: Only if lines of card %s break the save rules; the step runs", card)
        return [], {}
    runs = home / f"{automation}.runs"
    with _shared_lock(runs):
        data = _json_in(runs, f"{run}.only-if.json")
    if not isinstance(data, dict):
        return [], {}  # no values for this run (not kept): the step runs
    return lines, data


def _worked_before(kb: Any, conn: Any, card: str, run: int | None) -> bool:
    """An earlier attempt of this card started its worker: the card was decided
    then (it ran), so this one runs too (Hermes's own run history of the card)."""
    listing = getattr(kb, "list_runs", None)
    if listing is None:
        return False
    started = [r for r in listing(conn, card) if getattr(r, "outcome", None) != "spawn_failed"]
    if run is None:
        return len(started) > 1
    return any(getattr(r, "id", None) != run for r in started)


def _checks(card: str, task_id: str, lines: list[dict[str, Any]]) -> str | None:
    """The check lines, in order: why the step must not start, or None."""
    for line in (x for x in lines if "check" in x):
        script = str(line["check"]).split(" ")[0]
        said, last, code = _run_check(str(line["check"]), task_id)
        answer = {True: "yes", False: "no", None: "unsure (runs)"}[said]
        log.info("AGOS: Only if check of card %s ran %s (exit %s): %s", card, script, code, answer)
        if said is False:
            return f"{script} said {last or 'no'}"
    return None


def verdict(card: str, task_id: str = "", run: int | None = None) -> str | None:
    """`agos-skipped: <why>` when this card's step must not start, else None."""
    from hermes_cli import kanban_db as kb  # type: ignore[import-not-found]
    from hermes_cli import kanban_db_connect as kbc

    conn = kbc.connect()
    try:
        lines, data = _lines_of(kb, conn, card)
        if not lines:
            return None
        if _worked_before(kb, conn, card, run):
            log.info("AGOS: card %s was decided at its first attempt; it runs", card)
            return None
        raw_values, raw_payloads = data.get("values"), data.get("payloads")
        values: dict[str, Any] = raw_values if isinstance(raw_values, dict) else {}
        payloads: list[Any] = raw_payloads if isinstance(raw_payloads, list) else []
        why = match_reason(lines, values, payloads) or _checks(card, task_id, lines)
        return None if why is None else f"{MARK} {why}"
    finally:
        conn.close()


def _close(card: str, run: int | None, reason: str) -> bool:
    """The card done as skipped, under this worker's own run (Hermes's fence)."""
    from hermes_cli import kanban_db as kb
    from hermes_cli import kanban_db_connect as kbc

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
    card: str = "",
    run: int | None = None,
    task_id: str = "",
    is_first_turn: bool = True,
    parent_session_id: str = "",
    **_: Any,
) -> dict[str, str] | None:
    """Hermes's pre_llm_call: a step that must not start ends here, before any model
    call. `card` / `run`: the Kanban card this worker runs and its run id (Hermes's
    dispatcher sets them; the guard passes them in). Only the worker's own first turn
    (never a subagent's, never a later turn). Any error = the step runs (as before
    Only if existed)."""
    if not card or card in _checked or not is_first_turn or parent_session_id:
        return None
    _checked.add(card)
    started = time.monotonic()
    try:
        reason = verdict(card, str(task_id or ""), run)
        if reason is None:
            return None
        budget = _close_budget()
        if time.monotonic() - started > budget:
            return None
        if not _close(card, run, reason):
            return None
        late = time.monotonic() - started > budget
    except Exception:
        log.warning("AGOS: Only if of card %s not checked; the step runs", card, exc_info=True)
        return None
    log.info("AGOS: card %s skipped before any model call: %s", card, reason)
    if late:
        # Hermes may have stopped waiting for this hook: the worker may be working
        # already, so it is never ended mid-work (Hermes refuses its done-card result).
        log.warning("AGOS: card %s closed late; its worker is left to finish", card)
    elif not _veto_supported():
        _end_worker(str(task_id or ""), checked=reason.startswith(f"{MARK} /workspace/"))
    return {"action": "block", "message": reason}


def _close_budget() -> float:
    """How long after the hook started a card may still be closed: a margin under
    Hermes's wait for a plugin hook (plugins.hook_callback_timeout, the owner's
    "A stuck plugin step"; <= 0 = no limit), never more than CLOSE_BEFORE_S."""
    try:
        from hermes_cli.config import load_config  # type: ignore[import-not-found]

        raw = (load_config().get("plugins") or {}).get("hook_callback_timeout")
        limit = 30.0 if raw is None else float(raw)
    except (ImportError, AttributeError, OSError, TypeError, ValueError):
        return float(CLOSE_BEFORE_S)
    if limit <= 0:
        return float(CLOSE_BEFORE_S)
    return max(0.0, min(float(CLOSE_BEFORE_S), limit - 5))
