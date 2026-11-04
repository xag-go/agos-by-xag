"""Read vs act, inside Hermes: which sessions read untrusted content.

`pre_tool_call` sees every tool call. A call that reads from outside AGOS
(taint_sources.py: the web, an app's answer, an earlier conversation, a fetching
command, a file from /shared) marks its SESSION (or the top parent of a subagent: what
a child read reaches its parent through delegate_task). AGOS's own marks come in too:
turn-start answers `untrusted` (a Telegram message from someone else), a run asks AGOS
(a card a webhook made or a tainted session made, a job a tainted session scheduled),
and a card's result woken into a chat brings that card's mark with it.

The mark lasts until the chat SESSION ends (owner, 2026-11-03), not the turn: Hermes's
own on_session_finalize / on_session_reset end it (/new, an expired session). When
Hermes compresses a long conversation into a new session, the mark goes with it (the
same chat and sender). Until then:

- AGOS's tools (agos_action / agos_capability / agos_skill_request) first tell AGOS
  the session is marked (bridge `/taint`, before every call, so a core restart
  forgets nothing); AGOS asks the owner first for every power action with a one-time
  question (gate.py). If AGOS can't be told, the call is refused (fail closed).
- Hermes's own `cronjob` create / update / resume is a power too: asked once in a
  chat, refused in a run (nobody is there). A job made in a marked session is marked
  for good, so its runs start marked; a card it makes (kanban_create) too.
- Hermes's memory and skill writes are held for the owner's review with Hermes's
  own write-approval store (tools/write_approval.py stage_write: the same pending
  records AGOS shows as Inbox cards, applied with Hermes's own /memory, /skills).
"""

from __future__ import annotations

import importlib
import json
import re
import secrets
import sys
import threading
from collections.abc import Callable
from typing import Any

_PROCESS = "agos_guard_process_state"
_MAX = 20000
_lock = threading.Lock()
_MEMORY_WRITES = {"add", "replace", "remove", "patch", "batch"}
_CRON_POWERS = {"create", "update", "resume"}
_WAKE = re.compile(r"\[kanban\][^\n]{0,40}?\b(t_[A-Za-z0-9_-]{1,60})")
Post = Callable[[str, dict[str, Any], float], dict[str, Any] | None]
Report = Callable[[str, BaseException | str | None], None]


def _state(name: str) -> dict[str, Any]:
    """Shared by every profile's copy of the plugin (one dict per process)."""
    holder = sys.modules.get(_PROCESS)
    state = getattr(holder, "state", None) if holder is not None else None
    if not isinstance(state, dict):
        return _LOCAL.setdefault(name, {})
    found: dict[str, Any] = state.setdefault(name, {})
    return found


_LOCAL: dict[str, dict[str, Any]] = {}


def _marks() -> dict[str, str]:
    """session -> what it read."""
    return _state("tainted")


def _chats() -> dict[str, str]:
    """ "<chat>|<sender>" -> what its session read (carried to a compressed session)."""
    return _state("tainted_chats")


def _where() -> dict[str, str]:
    """session -> "<chat>|<sender>"; "evicted" -> "1" once marks were dropped."""
    return _state("tainted_where")


def _sibling(stem: str) -> Any:
    if __package__:
        return importlib.import_module(f"{__package__}.{stem}")
    return sys.modules.get(f"agos_guard_{stem}")


def _trusted() -> list[str]:
    """The apps the owner trusts in this profile (its policy file); none = all outside."""
    try:
        rules = _sibling("policy")  # the owner's policy file (policy.py)
        found = rules._policy().get("trustedApps") if rules is not None else None
    except Exception:  # noqa: BLE001 — unread: every app counts as outside
        return []
    return [str(t) for t in found] if isinstance(found, list) else []


def source_of(tool: str, args: dict[str, Any]) -> str:
    """What untrusted content this call reads ("" = nothing from outside)."""
    return str(_sibling("taint_sources").source_of(tool, args, _trusted()))


def root(session: str, parents: dict[str, str]) -> str:
    """The top of a subagent chain (its first parent that has none)."""
    seen = {session}
    while (up := parents.get(session, "")) and up not in seen:
        seen.add(up)
        session = up
    return session


def mark(session: str, found: str) -> None:
    """This session read `found` (the first source stays the one named)."""
    if not session or not found:
        return
    marks, where = _marks(), _where()
    with _lock:
        if len(marks) >= _MAX and session not in marks:
            # Dropped marks must never read as clean: from now on an unmarked
            # session's memory write asks AGOS (which keeps its marks on disk).
            where["evicted"] = "1"
            for old in list(marks)[: _MAX // 2]:
                marks.pop(old, None)
        marks.setdefault(session, found[:200])
        chat = where.get(session)
        if chat:
            _chats().setdefault(chat, marks[session])


def read(tool: str, args: dict[str, Any], session: str, parents: dict[str, str]) -> None:
    """Marks the session when this call reads from outside."""
    found = source_of(tool, args)
    if found and session:
        mark(root(session, parents), found)


def source(session: str, parents: dict[str, str]) -> str:
    if not session:
        return ""
    with _lock:
        return _marks().get(root(session, parents), "")


def opened(
    session: str, chat: str, sender: str, answer: dict[str, Any] | None, said: Any, post: Post
) -> None:
    """A turn opens in a chat (bridge.py turn-start): what AGOS knows this session read
    (`untrusted`), what its chat's earlier (compressed) session read, and the mark of
    a card whose result this turn wakes the agent with."""
    if not session:
        return
    key = f"{chat}|{sender}"
    with _lock:
        _where()[session] = key
        carried = _chats().get(key, "")
    if carried:
        mark(session, carried)
    if answer and answer.get("untrusted"):
        mark(session, str(answer["untrusted"]))
    text = said if isinstance(said, str) else json.dumps(said, default=str)[:20000]
    for card in dict.fromkeys(_WAKE.findall(text[:20000])):
        got = post("taint-of", {"chat": f"kanban:{card}"}, 15)
        if got is None or got.get("untrusted"):
            what = (got or {}).get("untrusted") or "a card AGOS couldn't check"
            mark(session, f"the result of card {card}, after {what}"[:200])


def end(session: str) -> None:
    """Hermes ended the session (/new, expired): the chat's next session starts clean."""
    with _lock:
        _marks().pop(str(session), None)
        chat = _where().pop(str(session), "")
        if chat:
            _chats().pop(chat, None)


def told(session: str, parents: dict[str, str], address: str, post: Post) -> bool:
    """Before one of AGOS's tools: AGOS knows this session read untrusted content.
    True when there is nothing to tell or AGOS got it."""
    found = source(session, parents)
    if not found:
        return True
    if not address:
        return False
    body = {"chat": address, "source": found, "session": root(session, parents)}
    return post("taint", body, 15) is not None


def _is_run(session: str) -> bool:
    bridge = _sibling("bridge")
    return session.startswith("cron_") or bool(bridge is not None and bridge.run_card())


def _from_agos(session: str, parents: dict[str, str]) -> str | None:
    """What AGOS says this run (or an evicted session) read; None = no answer."""
    bridge = _sibling("bridge")
    if bridge is None:
        return None
    top = root(session, parents)
    address = bridge._address_of_session(top)
    if not address:
        return None
    got = bridge.post("taint-of", {"chat": address, "session": top}, 15)
    if got is None:
        return None
    found = str(got.get("untrusted") or "")
    if found:
        mark(top, found)
    return found


def _known(session: str, parents: dict[str, str]) -> str | None:
    """The session's mark; for a run (or after marks were dropped) AGOS's too.
    None: AGOS should know and didn't answer (the caller fails closed)."""
    found = source(session, parents)
    if found or not session:
        return found
    if _is_run(session) or _where().get("evicted"):
        return _from_agos(session, parents)
    return ""


def held_write(
    tool: str, args: dict[str, Any], session: str, parents: dict[str, str], report: Report
) -> dict[str, str] | None:
    """A memory or skill write in a marked session: held in Hermes's own pending store
    for the owner's review (None: not held, Hermes goes on as usual)."""
    if tool not in ("memory", "skill_manage"):
        return None
    action = str(args.get("action") or "")
    if tool == "memory" and action not in _MEMORY_WRITES and not args.get("operations"):
        return None
    if tool == "skill_manage" and action in ("view", "list", "read") and not args.get("operations"):
        return None
    known = _known(session, parents)
    if known == "":
        return None
    found = known or "something AGOS couldn't check (it didn't answer)"
    try:
        from tools import write_approval as wa  # type: ignore[import-not-found]
    except ImportError as error:
        report("tools.write_approval", error)
        return {"action": "block", "message": _refused(found)}
    subsystem = wa.MEMORY if tool == "memory" else wa.SKILLS
    try:
        if wa.write_approval_enabled(subsystem):
            return None  # Hermes holds it itself (his Ask me / write_approval is on)
        payload, summary = _payload(wa, tool, args)
        record = wa.stage_write(
            subsystem,
            payload,
            summary=f"After reading {found}: {summary}"[:300],
            origin=wa.current_origin(),
        )
    except Exception as error:  # noqa: BLE001 — fail closed: never written unseen
        report("tools.write_approval.stage_write", error)
        return {"action": "block", "message": _refused(found)}
    return {
        "action": "block",
        "message": f"Held for the owner's review (this came after reading {found}): it "
        f"is saved as pending {record.get('id', '')} and he approves or rejects it in "
        "AGOS. Don't write it again; go on with your task.",
    }


def held_power(
    tool: str, args: dict[str, Any], session: str, parents: dict[str, str]
) -> tuple[dict[str, Any], bool] | None:
    """Hermes's own cronjob create / update / resume in a marked session: a power.
    A chat asks him once (a rule key never seen before); a run is refused."""
    if tool != "cronjob" or str(args.get("action") or "") not in _CRON_POWERS:
        return None
    known = _known(session, parents)
    if known == "":
        return None
    found = known or "something AGOS couldn't check (it didn't answer)"
    what = (
        f"⏰ {args.get('action')} the scheduled job {args.get('name') or args.get('job_id') or ''}"
    )
    said = f"⚠️ This came after reading {found}. {what.strip()}"[:900]
    if _is_run(session):
        return {
            "action": "block",
            "message": f"Not done: a run that read {found} doesn't schedule or change jobs "
            "(nobody is here to say yes). Say in your result what you wanted to schedule.",
        }, False
    nonce = secrets.token_urlsafe(16)
    return {"action": "approve", "message": said, "rule_key": f"agos:once:{nonce}"}, True


def checked(
    tool: str,
    args: dict[str, Any],
    session: str,
    parents: dict[str, str],
    report: Report,
    verdict_of: Callable[[str, dict[str, Any], str], tuple[dict[str, Any] | None, bool]],
) -> tuple[dict[str, Any] | None, bool]:
    """pre_tool_call's answer with read vs act: the read is marked, the guard's own
    verdict comes first (a block stays a block), then a held power or memory / skill
    write."""
    read(tool, args, session, parents)
    verdict, asks = verdict_of(tool, args, session)
    if verdict and verdict.get("action") == "block":
        return verdict, asks
    power = held_power(tool, args, session, parents)
    if power is not None:
        return power
    held = held_write(tool, args, session, parents, report)
    return (held, False) if held else (verdict, asks)


def after_tool(
    tool: str, args: Any, result: Any, session: str, parents: dict[str, str], post: Post
) -> None:
    """A marked session made a scheduled job or a card: it is marked for good (its
    runs, its worker, its result woken into a chat all start marked)."""
    if tool not in ("cronjob", "kanban_create") or not isinstance(args, dict):
        return
    found = source(session, parents)
    if not found:
        return
    try:
        out = json.loads(result) if isinstance(result, str) else result
    except ValueError:
        return
    if not isinstance(out, dict):
        return
    if tool == "cronjob" and str(args.get("action") or "") in _CRON_POWERS:
        job = str(out.get("job_id") or (out.get("job") or {}).get("id") or args.get("job_id") or "")
        address = f"cron:{job}" if job else ""
    else:
        card = str(out.get("task_id") or "")
        address = f"kanban:{card}" if card else ""
    if address and re.match(r"^(cron|kanban):[A-Za-z0-9_-]{1,64}$", address):
        what = f"a job or card made after reading {found}"[:200]
        post("taint", {"chat": address, "source": what}, 15)


def register(ctx: Any, post: Post, report: Report, parents: Callable[[], dict[str, str]]) -> None:
    """Hermes's hooks: the session ends (its mark with it); a marked session's new job
    or card is marked."""

    def finalized(session_id: str = "", **_: Any) -> None:
        end(str(session_id or ""))

    def reset(old_session_id: str = "", session_id: str = "", **_: Any) -> None:
        end(str(old_session_id or ""))

    def done(tool_name: str = "", args: Any = None, result: Any = None, **kw: Any) -> None:
        session = str(kw.get("session_id") or kw.get("task_id") or "")
        try:
            after_tool(str(tool_name), args, result, session, parents(), post)
        except Exception as error:  # noqa: BLE001 — an observer never breaks a tool call
            report("agos_guard.taint.after_tool", error)

    ctx.register_hook("on_session_finalize", finalized)
    ctx.register_hook("on_session_reset", reset)
    ctx.register_hook("post_tool_call", done)


def _refused(found: str) -> str:
    return (
        f"Not saved: this came after reading {found}, and AGOS could not hold it for the "
        "owner's review. Don't try another way; say in your answer what you wanted to save."
    )


def _payload(wa: Any, tool: str, args: dict[str, Any]) -> tuple[dict[str, Any], str]:
    """What Hermes's own approval replays (memory_tool / skill_manager_tool shapes)."""
    if tool == "memory":
        target = str(args.get("target") or "memory")
        label = "user profile" if target == "user" else "memory"
        if args.get("operations") is not None:
            ops = list(args.get("operations") or [])
            return (
                {"action": "batch", "target": target, "operations": ops},
                f"apply {len(ops)} op(s) to {label}",
            )
        action = str(args.get("action") or "")
        content = args.get("content") if args.get("content") is not None else args.get("new_text")
        old = args.get("old_text")
        said = str(content or old or "")[:120]
        return (
            {"action": action, "target": target, "content": content, "old_text": old},
            f"{action} {label}: {said}",
        )
    keys = ("content", "category", "file_path", "file_content", "old_string", "new_string")
    action, name = str(args.get("action") or ""), str(args.get("name") or "")
    payload: dict[str, Any] = {"action": action, "name": name}
    for key in (*keys, "absorbed_into", "operations", "replace_all"):
        if args.get(key) is not None:
            payload[key] = args[key]
    ops = [o for o in args.get("operations") or [] if isinstance(o, dict)]
    if ops and not action:
        # The operations shape: each change named, so he never reviews it blind.
        named = "; ".join(f"{o.get('action') or '?'} {o.get('name') or '?'}" for o in ops[:8])
        return payload, f"{len(ops)} skill change(s): {named}"
    gist_of = getattr(wa, "skill_gist", None)
    gist = (
        gist_of(
            action,
            name,
            **{
                k: str(args.get(k) or "")
                for k in ("content", "file_path", "old_string", "new_string")
            },
        )
        if callable(gist_of)
        else f"{action} skill {name}"
    )
    return payload, str(gist) or f"{action} skill {name}"
