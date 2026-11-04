"""The Co-Founder's team actions: hire, its own profile, members' files and fields.
Must not: hold the team logic (actions/team.py does).

Split out of agos_core.actions.cofounder_actions (which re-exports it); behaviour unchanged.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agos_core.actions.errors import ActionError
from agos_core.actions.services.cofounder.chat_mode import _edited
from agos_core.actions.workspaces import require_workspace
from agos_core.context import Core
from agos_core.db.activity import add_activity

__all__ = [
    "FILE_TYPES",
]


def _agent_field(value: Any) -> str | None:
    name = str(value or "").strip().lstrip("@")
    return (
        None if name.lower() in ("", "cofounder", "manager", "none") else name
    )  # "manager": the name before step 44, still in old rows and cards


def _default_model(core: Core, workspace_id: str) -> dict[str, Any]:
    return require_workspace(core, workspace_id).default_model.model_dump()


FILE_TYPES = (
    ".py",
    ".sh",
    ".js",
    ".mjs",
    ".ts",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".md",
    ".txt",
    ".csv",
)


def _team_file(core: Core, workspace_id: str, path: str) -> Path:
    """A text file of the workspace outside playbooks/ (scripts, validators, gates)."""
    from agos_core.storage.layout import workspace_paths

    clean = path.strip().removeprefix("/workspace/").strip("/")
    parts = clean.split("/")
    if not clean or ".." in parts or any(x.startswith(".") for x in parts) or "\\" in clean:
        raise ActionError("Use a path like tools/check.py (no hidden folders, no ..).")
    if parts[0] == "playbooks":
        raise ActionError(
            "Files in playbooks/ change with update_doc / update_skill / update_agent "
            "— send that action yourself; never tell the owner they are locked."
        )
    if not clean.endswith(FILE_TYPES):
        raise ActionError("Only text files (scripts, data, notes) can be changed this way.")
    base = workspace_paths(core.layout, workspace_id).files.resolve()
    target = (base / clean).resolve()
    if base not in target.parents:
        raise ActionError("The file stays in this workspace.")
    if target.is_file() and target.stat().st_size > 2_000_000:
        raise ActionError("That file is too big to change with a card.")
    return target


def _file(core: Core, workspace_id: str, p: dict[str, Any]) -> dict[str, Any]:
    """Writes a team file outside playbooks (a version kept for Undo, a CHANGES.md line)."""
    from agos_core.actions import docs
    from agos_core.engine import docs as doc_rules

    target = _team_file(core, workspace_id, str(p["path"]))
    rel = str(p["path"]).strip().removeprefix("/workspace/").strip("/")
    before = target.read_text() if target.is_file() else None
    if p.get("text"):
        text = str(p["text"])
    else:
        text = _edited(
            before or "", {"replace": p.get("replace"), "add_instructions": p.get("add")}
        )
    if text == before:
        return {"path": rel, "before": before}
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)
    log_file = docs.folder(core, workspace_id) / doc_rules.LOG
    if log_file.parent.is_dir():
        current = log_file.read_text() if log_file.is_file() else ""
        log_file.write_text(
            doc_rules.add_to_log(
                current, doc_rules.log_entry(rel, "Co-Founder", str(p["why"]), ["whole file"])
            )
        )
    add_activity(
        core.db,
        workspace_id,
        kind="docs.changed",
        text=f"File {rel} changed by Co-Founder ({str(p['why']).strip()[:120]})",
    )
    return {"path": rel, "before": before}


def _hire(core: Core, workspace_id: str, p: dict[str, Any], *, old: bool = False) -> dict[str, Any]:
    """A hire asked from a chat, a card's worker, an automation's run or a subagent:
    ALWAYS a proposal card for the owner's Approve / Revise / Reject in his Inbox
    (actions/proposals.py), in every autonomy mode, Direct included. Nothing is
    created before his Approve; a hire missing any part of its kit or model is
    refused with what is missing (the agent sends it again). `old`: sent as
    create_agent, which makes no agent any more."""
    from agos_core.actions import proposals

    words = str(p.get("why") or "").strip()
    try:
        return proposals.propose(core, workspace_id, "hire", dict(p), words)
    except ActionError as error:
        if not old:
            raise
        raise ActionError(
            "create_agent makes no agent any more: every new agent is a hire the owner "
            "approves in his Inbox. Send hire_agent with the full hire (title, role, why, "
            "goal_id, skills, kit, model, model_why). " + error.message,
            error.status,
        ) from error


def _founder(core: Core, workspace_id: str, action: str, p: dict[str, Any]) -> dict[str, Any]:
    """A task for the Founder (the owner himself) on Hermes's board, or his Done
    when he said so in the chat (actions/founder.py, the same code as his pages)."""
    from agos_core.actions import founder, kanban_board

    def ids(value: Any) -> list[str]:
        items = value if isinstance(value, list) else str(value or "").replace(",", " ").split()
        return [str(i).strip() for i in items if str(i).strip()]

    if action == "founder_done":
        card = str(p["card"]).strip()
        was = founder.done(core, workspace_id, card, str(p.get("note") or ""), by="cofounder")
        return {"card": card, "said": "Done on the board." if was else "It was done already."}
    card = founder.assign(
        core,
        workspace_id,
        str(p["title"]),
        str(p.get("what") or p.get("body") or ""),
        due=str(p.get("due") or ""),
        unblocks=ids(p.get("unblocks")),
        parents=ids(p.get("parents")),
        by=kanban_board.COFOUNDER,
    )
    return {"card": card, "said": f"On the board for him: {card}."}
