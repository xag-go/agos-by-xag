"""The Co-Founder's board kinds: labels, views, cards, reviews, status cards.

Part of the Co-Founder's KINDS (merged in DOMAINS order by
cofounder_parity/catalog.py).

Must not: run a kind (actions/cofounder_more.py) or merge the catalogue (catalog.py).
"""

from __future__ import annotations

from agos_core.engine.cofounder_kind import BOARD, Kind

__all__ = [
    "BOARD_KINDS",
]

BOARD_KINDS: dict[str, Kind] = {
    # ---- board ------------------------------------------------------------------------
    "create_label": Kind(
        BOARD, ("name",), "Label “{name}”", "name, color (gray, red, green...), folder"
    ),
    "update_label": Kind(
        BOARD,
        ("label",),
        "Change label “{label}”",
        "label (its name or number), name, color, folder",
    ),
    "delete_label": Kind(
        BOARD, ("label",), "Delete label “{label}” (off every card)", "label", "owner"
    ),
    "rename_label_folder": Kind(
        BOARD, ("folder", "new"), "Label folder “{folder}” → “{new}”", "folder, new"
    ),
    "save_board_view": Kind(
        BOARD,
        ("name",),
        "Kanban view “{name}”",
        "name (an existing view of that name changes), filters (object), groupBy, sort, "
        "layout, columns",
        structured=("filters", "columns"),
    ),
    "delete_board_view": Kind(BOARD, ("view",), "Delete Kanban view “{view}”", "view (its name)"),
    "set_card_goal": Kind(
        BOARD,
        ("card",),
        "Card {card} serves goal {goal}",
        "card, goal (a goal's or project's number; \"\" = none)",
    ),
    "assign_card": Kind(BOARD, ("card", "member"), "Give card {card} to @{member}", "card, member"),
    "card_action": Kind(
        BOARD,
        ("card", "action"),
        "Card {card}: {action}",
        "card, action (unblock | done | block | archive), summary (for done)",
        "once",
    ),
    "hold_cards": Kind(
        BOARD,
        ("card", "action"),
        "{action} card {card} and everything under it",
        "card, action (pause | cancel)",
    ),
    "resume_hold": Kind(BOARD, ("hold",), "Resume held cards (hold {hold})", "hold", "once"),
    "bulk_cards": Kind(
        BOARD,
        ("cards", "action"),
        "{action} on several cards",
        "cards (ids), action (the board toolbar's: archive, assign, labels, done...), member, "
        "add / remove (label numbers), summary",
        "owner",
        structured=("cards", "add", "remove"),
    ),
    "watch_card": Kind(
        BOARD,
        ("card", "member"),
        "@{member} watches card {card}: {on}",
        "card, member (or cofounder), on (true/false)",
    ),
    "estimate_card": Kind(BOARD, ("card",), "Estimate card {card}", "card", "once"),
    "set_card_review": Kind(
        BOARD,
        ("card",),
        "Review rules of card {card}",
        "card, stages (reviewer names in order), cap (rounds), plan (true = plan first), "
        "plan_reviewer, reset (true = the workspace's defaults)",
        structured=("stages",),
    ),
    "save_review_settings": Kind(
        BOARD,
        (),
        "Review settings of the workspace",
        "stages, cap, plan_first (true/false), plan_reviewer",
        structured=("stages",),
    ),
    "restore_card_doc": Kind(
        BOARD,
        ("card", "key", "revision"),
        "Card {card}'s document {key} back to r{revision}",
        "card, key, revision",
    ),
    "resolve_doc_comment": Kind(
        BOARD,
        ("comment",),
        "Comment {comment}: resolved {resolved}",
        "card, key, comment (its number), resolved (true/false)",
    ),
    "create_status_card": Kind(
        BOARD,
        ("title", "scope"),
        "Status card “{title}”",
        "title, scope (workspace | goal | project | member | query = some words), scope_ref "
        "(the goal/project number, the member, or the words), policy (daily | weekly | "
        "manual), time (HH:MM), day",
    ),
    "update_status_card": Kind(
        BOARD, ("card",), "Change status card {card}", "card (its number) and the create fields"
    ),
    "delete_status_card": Kind(BOARD, ("card",), "Delete status card {card}", "card", "owner"),
    "refresh_status_card": Kind(BOARD, ("card",), "Refresh status card {card}", "card", "once"),
}
