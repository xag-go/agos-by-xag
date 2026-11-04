"""The Co-Founder's actions for the team: groups, member kits, readiness, the office look.
Must not: hold the logic itself; each calls the page's own action.

Split out of agos_core.actions.cofounder_more (which re-exports it); behaviour unchanged.
"""

from __future__ import annotations

from typing import Any

from agos_core.actions.errors import ActionError
from agos_core.actions.services.cofounder.action_args import Fields, Result, member_arg, text_arg
from agos_core.actions.services.team import office_looks
from agos_core.context import Core
from agos_core.db import chats as chats_repo

__all__ = [
    "do_create_group",
    "do_office_look",
    "do_readiness",
    "do_save_kit",
    "do_set_group",
    "do_suggest_kit",
    "undo_create_group",
    "undo_kit",
    "undo_office_look",
    "undo_readiness",
    "undo_set_group",
]

# ---- team -------------------------------------------------------------------------------


def _names(value: Any) -> list[str]:
    items = value if isinstance(value, list) else [value]
    return [member_arg(v) for v in items if member_arg(v)]


def _group(core: Core, ws: str, ref: Any) -> int:
    wanted = str(ref or "").strip().lower().lstrip("#")
    for row in chats_repo.groups_of(core.db, ws):
        if str(row["id"]) == wanted or str(row["title"] or "").strip().lower() == wanted:
            return int(row["id"])
    raise ActionError(f"There is no group “{ref}” in this workspace.", 404)


def _group_members(core: Core, ws: str, chat_id: int) -> list[str]:
    from agos_core.actions import workers

    found = next((g for g in workers.team(core, ws).groups if g.id == chat_id), None)
    return [str(m) for m in found.members] if found is not None else []


def do_create_group(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import workers

    return {"chat": workers.create_group(core, ws, text_arg(p, "title"), _names(p["members"]))}


def undo_create_group(core: Core, ws: str, r: Result) -> None:
    from agos_core.actions import chat

    chat.delete_chat(core, ws, int(r["chat"]))


def do_set_group(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import workers

    chat_id = _group(core, ws, p["group"])
    before = _group_members(core, ws, chat_id)
    workers.set_group_members(core, ws, chat_id, _names(p["members"]))
    return {"chat": chat_id, "before": before}


def undo_set_group(core: Core, ws: str, r: Result) -> None:
    from agos_core.actions import workers

    workers.set_group_members(core, ws, int(r["chat"]), [str(m) for m in r["before"]])


def do_save_kit(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import hire_kit

    member = member_arg(p["member"])
    if not isinstance(p.get("kit"), dict):
        raise ActionError("Give the kit as an object (tools, skills, docs, team, onboarding).")
    before = hire_kit.kit_of(core, ws, member)
    hire_kit.save_kit(core, ws, member, dict(p["kit"]))
    return {"member": member, "before": before}


def undo_kit(core: Core, ws: str, r: Result) -> None:
    from agos_core.actions import hire_kit

    if not isinstance(r.get("before"), dict):
        raise ActionError("This member had no kit before: change it on its Readiness instead.")
    hire_kit.save_kit(core, ws, str(r["member"]), dict(r["before"]))


def do_suggest_kit(core: Core, ws: str, p: Fields) -> Result:
    """The owner's "Suggest kit" (a card on you for one member, or "all": one per
    member without a whole kit), or, with a kit, your own 'Kit for @x' proposal:
    always a card he approves in his Inbox, never written on the spot."""
    from agos_core.actions import member_kits, proposals

    member = member_arg(p["member"]).lower()
    note = text_arg(p, "note")
    if member == "all":
        made = member_kits.ask_all(core, ws, note)
        asked = ", ".join(f"@{a['member']} (card {a['card']})" for a in made["asked"])
        return {
            "report": (f"Asked for kits: {asked}." if asked else "No member waits for a kit ask.")
            + (f" {made['left']} more on the next ask." if made["left"] else "")
        }
    if isinstance(p.get("kit"), dict):
        payload: dict[str, Any] = {
            k: p[k] for k in ("kit", "model", "model_why", "why", "source_card") if k in p
        }
        made = proposals.propose(core, ws, "kit", {**payload, "member": member}, text_arg(p, "why"))
        return {
            "proposed": True,
            "card": made["card"],
            "report": f"Proposed on card {made['card']}: the owner approves it in his Inbox.",
        }
    card, created = member_kits.ask(core, ws, member, note)
    return {
        "report": f"Card {card}: "
        + ("propose the kit there." if created else "already asked (still open or waiting).")
    }


def do_readiness(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import hire_kit

    member = member_arg(p["member"])
    choice = text_arg(p, "choice")
    item = text_arg(p, "item")
    hire_kit.choose(core, ws, member, item, choice, text_arg(p, "reason"))
    return {"member": member, "item": item, "choice": choice}


def undo_readiness(core: Core, ws: str, r: Result) -> None:
    from agos_core.actions import hire_kit

    hire_kit.choose(core, ws, str(r["member"]), str(r["item"]), "clear")


def do_office_look(core: Core, ws: str, p: Fields) -> Result:
    member = member_arg(p["member"])
    before = office_looks.look_of(core, ws, member)
    office_looks.save_look(core, ws, member, {**before, **dict(p["look"])})
    return {"member": member, "before": before}


def undo_office_look(core: Core, ws: str, r: Result) -> None:
    office_looks.save_look(core, ws, str(r["member"]), dict(r["before"]))
