"""The Co-Founder's actions for the board: labels, views, cards, holds, reviews, card docs, status cards.
Must not: hold the logic itself; each calls the page's own action.

Split out of agos_core.actions.cofounder_more (which re-exports it); behaviour unchanged.
"""

from __future__ import annotations

import json
from typing import Any

from agos_core.actions.errors import ActionError, NotFoundError
from agos_core.actions.services.cofounder.action_args import (
    Fields,
    Result,
    flag_arg,
    int_arg,
    member_arg,
    text_arg,
)
from agos_core.context import Core

__all__ = [
    "do_assign",
    "do_bulk",
    "do_card_action",
    "do_card_doc",
    "do_card_goal",
    "do_card_review",
    "do_create_label",
    "do_create_status",
    "do_delete_label",
    "do_delete_status",
    "do_delete_view",
    "do_doc_comment",
    "do_estimate",
    "do_hold",
    "do_refresh_status",
    "do_rename_folder",
    "do_resume_hold",
    "do_review_settings",
    "do_save_view",
    "do_update_label",
    "do_update_status",
    "do_watch_card",
    "undo_assign",
    "undo_card_doc",
    "undo_card_goal",
    "undo_card_review",
    "undo_create_label",
    "undo_create_status",
    "undo_delete_status",
    "undo_delete_view",
    "undo_doc_comment",
    "undo_hold",
    "undo_rename_folder",
    "undo_review_settings",
    "undo_save_view",
    "undo_update_label",
    "undo_update_status",
    "undo_watch_card",
]

# ---- board ------------------------------------------------------------------------------


def _label(core: Core, ws: str, ref: Any) -> dict[str, Any]:
    from agos_core.actions import labels

    wanted = str(ref or "").strip().lower().lstrip("#")
    for label in labels.listing(core, ws):
        if str(label["id"]) == wanted or str(label["name"]).lower() == wanted:
            return label
    raise ActionError(f"There is no label “{ref}” in this workspace.", 404)


def do_create_label(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import labels

    made = labels.create(
        core, ws, text_arg(p, "name"), text_arg(p, "color") or "gray", text_arg(p, "folder")
    )
    return {"label": int(made["id"])}


def undo_create_label(core: Core, ws: str, r: Result) -> None:
    from agos_core.actions import labels

    labels.remove(core, ws, int(r["label"]))


def do_update_label(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import labels

    before = _label(core, ws, p["label"])
    labels.update(
        core,
        ws,
        int(before["id"]),
        name=text_arg(p, "name") or None,
        color=text_arg(p, "color") or None,
        folder=text_arg(p, "folder") if "folder" in p else None,
    )
    return {"label": int(before["id"]), "before": before}


def undo_update_label(core: Core, ws: str, r: Result) -> None:
    from agos_core.actions import labels

    b = r["before"]
    labels.update(core, ws, int(r["label"]), name=b["name"], color=b["color"], folder=b["folder"])


def do_delete_label(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import labels

    found = _label(core, ws, p["label"])
    labels.remove(core, ws, int(found["id"]))
    return {"label": found}


def do_rename_folder(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import labels

    labels.rename_folder(core, ws, text_arg(p, "folder"), text_arg(p, "new"))
    return {"folder": text_arg(p, "folder"), "new": text_arg(p, "new")}


def undo_rename_folder(core: Core, ws: str, r: Result) -> None:
    from agos_core.actions import labels

    labels.rename_folder(core, ws, str(r["new"]), str(r["folder"]))


def _view_named(core: Core, ws: str, name: Any) -> dict[str, Any] | None:
    from agos_core.actions import board_views

    wanted = str(name or "").strip().lower()
    return next(
        (v for v in board_views.listing(core, ws) if str(v.get("name", "")).lower() == wanted),
        None,
    )


_VIEW = ("filters", "groupBy", "sort", "layout", "columns")


def do_save_view(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import board_views

    before = _view_named(core, ws, p["name"])
    view = dict(before or {"name": text_arg(p, "name")})
    for key in _VIEW:
        sent = p.get(key) if key in p else p.get(key.lower())
        if sent is not None:
            view[key] = sent
    saved = board_views.save(core, ws, view)
    return {"view": int(saved["id"]), "before": before}


def undo_save_view(core: Core, ws: str, r: Result) -> None:
    from agos_core.actions import board_views

    if r.get("before") is None:
        board_views.remove(core, ws, int(r["view"]))
    else:
        board_views.save(core, ws, dict(r["before"]))


def do_delete_view(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import board_views

    found = _view_named(core, ws, p["view"])
    if found is None:
        raise ActionError(f"There is no board view “{p['view']}”.", 404)
    board_views.remove(core, ws, int(found["id"]))
    return {"before": {k: v for k, v in found.items() if k != "id"}}


def undo_delete_view(core: Core, ws: str, r: Result) -> None:
    from agos_core.actions import board_views

    board_views.save(core, ws, dict(r["before"]))


def _card_body(core: Core, ws: str, card: str) -> dict[str, Any]:
    from agos_core.actions import kanban_board

    raw, _extra = kanban_board._shown(core, ws, card)
    task = raw.get("task") if isinstance(raw, dict) else None
    if not isinstance(task, dict):
        raise NotFoundError("This card")
    return task


def do_card_goal(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import goals
    from agos_core.engine.goals import card_goal

    card = text_arg(p, "card")
    before = card_goal(str(_card_body(core, ws, card).get("body") or ""))
    goal = int_arg(p["goal"], "the goal") if text_arg(p, "goal") else None
    goals.set_card_goal(core, ws, card, goal)
    return {"card": card, "before": before}


def undo_card_goal(core: Core, ws: str, r: Result) -> None:
    from agos_core.actions import goals

    goals.set_card_goal(core, ws, str(r["card"]), r["before"])


def do_assign(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import kanban_board

    card = text_arg(p, "card")
    before = str(_card_body(core, ws, card).get("assignee") or "")
    kanban_board.assign(core, ws, card, member_arg(p["member"]))
    return {"card": card, "before": before}


def undo_assign(core: Core, ws: str, r: Result) -> None:
    from agos_core.actions import kanban_board

    if not r.get("before"):
        raise ActionError("The card had nobody before: give it to someone instead.")
    kanban_board._cli(core, ws, "assign", str(r["card"]), str(r["before"]))


def do_card_action(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import kanban_board

    kanban_board.act(core, ws, text_arg(p, "card"), text_arg(p, "action"), text_arg(p, "summary"))
    return {}


def do_hold(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import holds

    action = text_arg(p, "action").lower()
    if action not in ("pause", "cancel"):
        raise ActionError("action is pause or cancel.")
    run = holds.pause if action == "pause" else holds.cancel
    made = run(core, ws, text_arg(p, "card"))
    return {"hold": int(made["id"]), "action": action}


def undo_hold(core: Core, ws: str, r: Result) -> None:
    from agos_core.actions import holds

    if r.get("action") != "pause":
        raise ActionError("A cancel archived the cards: it can't be undone from here.")
    holds.resume(core, ws, int(r["hold"]))


def do_resume_hold(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import holds

    holds.resume(core, ws, int_arg(p["hold"], "the hold"))
    return {}


def do_bulk(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import board_views

    def ids(key: str) -> list[int]:
        return [int_arg(v, "a label") for v in p.get(key) or []]

    found = board_views.bulk(
        core,
        ws,
        [str(c) for c in p.get("cards") or []],
        text_arg(p, "action"),
        member=member_arg(p.get("member")),
        add=ids("add"),
        remove=ids("remove"),
        summary=text_arg(p, "summary"),
    )
    return {"report": json.dumps(found, ensure_ascii=False)[:2000]}


def do_watch_card(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import threads

    card, member = text_arg(p, "card"), member_arg(p["member"])
    was = any(
        str(w.get("member") or w.get("name") or "") == member
        for w in threads.watchers(core, ws, card)
    )
    on = flag_arg(p.get("on"))
    (threads.watch if on else threads.unwatch)(core, ws, card, member)
    return {"card": card, "member": member, "before": was}


def undo_watch_card(core: Core, ws: str, r: Result) -> None:
    from agos_core.actions import threads

    (threads.watch if r["before"] else threads.unwatch)(core, ws, str(r["card"]), str(r["member"]))


def do_estimate(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import kanban_board

    found = kanban_board.estimate(core, ws, text_arg(p, "card"))
    return {"report": json.dumps(found, ensure_ascii=False, default=str)[:2000]}


def do_card_review(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import reviews
    from agos_core.engine import reviews as review_rules

    card = text_arg(p, "card")
    before = review_rules.card_block(str(_card_body(core, ws, card).get("body") or ""))
    data: dict[str, Any] = {}
    if not flag_arg(p.get("reset"), default=False):
        data = dict(before)
        if isinstance(p.get("stages"), list):
            data["stages"] = [member_arg(s) for s in p["stages"]]
        if "cap" in p:
            data["cap"] = int_arg(p["cap"], "the rounds")
        if "plan" in p:
            data["plan"] = flag_arg(p["plan"])
        if p.get("plan_reviewer"):
            data["planReviewer"] = member_arg(p["plan_reviewer"])
    reviews.set_card(core, ws, card, data)
    return {"card": card, "before": before}


def undo_card_review(core: Core, ws: str, r: Result) -> None:
    from agos_core.actions import reviews

    reviews.set_card(core, ws, str(r["card"]), dict(r["before"] or {}))


def do_review_settings(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import reviews

    before = dict(reviews.defaults(core, ws))
    data = dict(before)
    if isinstance(p.get("stages"), list):
        data["stages"] = [member_arg(s) for s in p["stages"]]
    if "cap" in p:
        data["cap"] = int_arg(p["cap"], "the rounds")
    if "plan_first" in p:
        data["planFirst"] = flag_arg(p["plan_first"])
    if "plan_reviewer" in p:
        data["planReviewer"] = member_arg(p["plan_reviewer"])
    reviews.save_defaults(core, ws, data)
    return {"before": before}


def undo_review_settings(core: Core, ws: str, r: Result) -> None:
    from agos_core.actions import reviews

    reviews.save_defaults(core, ws, dict(r["before"]))


def do_card_doc(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import card_docs

    card, key = text_arg(p, "card"), text_arg(p, "key")
    before = int(card_docs.get_doc(core, ws, card, key)["revision"])
    card_docs.restore(core, ws, card, key, int_arg(p["revision"], "the revision"), who="Co-Founder")
    return {"card": card, "key": key, "before": before}


def undo_card_doc(core: Core, ws: str, r: Result) -> None:
    from agos_core.actions import card_docs

    card_docs.restore(core, ws, str(r["card"]), str(r["key"]), int(r["before"]), who="Co-Founder")


def do_doc_comment(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import card_docs

    comment = int_arg(p["comment"], "the comment")
    resolved = flag_arg(p.get("resolved"))
    card_docs.resolve(core, ws, comment, resolved)
    return {"comment": comment, "resolved": resolved}


def undo_doc_comment(core: Core, ws: str, r: Result) -> None:
    from agos_core.actions import card_docs

    card_docs.resolve(core, ws, int(r["comment"]), not bool(r["resolved"]))


_STATUS = ("title", "scope", "scope_ref", "policy", "time", "day")


def _status_fields(shown: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": shown["title"],
        "scope": shown["scope"],
        "scope_ref": shown.get("scopeRef") or "",
        "policy": shown["policy"],
        "time": shown["time"],
        "day": shown.get("day"),
    }


def _status_args(p: Fields, base: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key in _STATUS:
        if key in p:
            out[key] = (
                (int_arg(p[key], "the day") if text_arg(p, key) else None)
                if key == "day"
                else text_arg(p, key)
            )
    # The page's "some words" scope is status_cards' "query".
    if str(out.get("scope") or "").lower() in ("search", "words", "text", "keywords"):
        out["scope"] = "query"
    return out


def do_create_status(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import status_cards

    args = _status_args(
        p, {"scope_ref": "", "policy": "daily", "time": status_cards.DEFAULT_TIME, "day": None}
    )
    made = status_cards.create(core, ws, **args)
    return {"card": int(made["id"])}


def undo_create_status(core: Core, ws: str, r: Result) -> None:
    from agos_core.actions import status_cards

    status_cards.delete(core, ws, int(r["card"]))


def do_update_status(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import status_cards

    card = int_arg(p["card"], "the status card")
    before = _status_fields(status_cards.one(core, ws, card))
    status_cards.update(core, ws, card, **_status_args(p, before))
    return {"card": card, "before": before}


def undo_update_status(core: Core, ws: str, r: Result) -> None:
    from agos_core.actions import status_cards

    status_cards.update(core, ws, int(r["card"]), **dict(r["before"]))


def do_delete_status(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import status_cards

    card = int_arg(p["card"], "the status card")
    before = _status_fields(status_cards.one(core, ws, card))
    status_cards.delete(core, ws, card)
    return {"before": before}


def undo_delete_status(core: Core, ws: str, r: Result) -> None:
    from agos_core.actions import status_cards

    status_cards.create(core, ws, **dict(r["before"]))


def do_refresh_status(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import status_cards

    status_cards.refresh(core, ws, int_arg(p["card"], "the status card"))
    return {}
