"""The Co-Founder's actions for keys, apps and Telegram, imports and exports, templates and artifacts.
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
from agos_core.db import artifact_reviews, channel_connections
from agos_core.db import chats as chats_repo

__all__ = [
    "do_add_address",
    "do_approve_person",
    "do_disconnect",
    "do_export",
    "do_import",
    "do_install_template",
    "do_promote",
    "do_reactions",
    "do_remove_address",
    "do_remove_key",
    "do_remove_person",
    "do_review_artifact",
    "do_team_group",
    "do_test_key",
    "undo_add_address",
    "undo_reactions",
    "undo_review_artifact",
    "undo_team_group",
]

# ---- workspace: keys, apps, channels ----------------------------------------------------


def do_remove_key(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import tool_keys

    tool_keys.remove(core, ws, text_arg(p, "name"))
    return {}


def do_test_key(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import tool_keys

    found = tool_keys.test(core, ws, text_arg(p, "name"))
    # The answer says whether the key works, never the key itself.
    return {"report": json.dumps(found, ensure_ascii=False)[:2000]}


def do_disconnect(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import apps

    apps.disconnect(core, ws, text_arg(p, "app"))
    return {}


def do_team_group(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import hermes_channel

    before = str(hermes_channel.team_groups(core, ws).get("teamGroup") or "")
    hermes_channel.set_team_group(core, ws, text_arg(p, "group"))
    return {"before": before}


def undo_team_group(core: Core, ws: str, r: Result) -> None:
    from agos_core.actions import hermes_channel

    hermes_channel.set_team_group(core, ws, str(r["before"]))


def _bot(core: Core, ws: str) -> Any:
    row = next(
        (r for r in channel_connections.of_workspace(core.db, ws) if r["kind"] == "telegram"),
        None,
    )
    if row is None:
        raise ActionError("This workspace has no Telegram bot yet (the owner adds it).", 404)
    return row


def do_reactions(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import channels, hermes_channel

    row = _bot(core, ws)
    before = hermes_channel.reactions_on(core, ws)
    enabled = hermes_channel.bot_on(core, ws)
    channels.update_connection(
        core,
        int(row["id"]),
        name=str(row["name"]),
        enabled=enabled,
        secret=None,
        reactions=flag_arg(p.get("on")),
    )
    return {"before": before}


def undo_reactions(core: Core, ws: str, r: Result) -> None:
    do_reactions(core, ws, {"on": bool(r["before"])})


def _chat_here(core: Core, ws: str, value: Any) -> int:
    chat = int_arg(value, "the chat")
    found = chats_repo.in_workspace(core.db, ws, chat)
    if found is None:
        raise NotFoundError("This chat")
    return chat


def do_add_address(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import channels

    chat = _chat_here(core, ws, p["chat"])
    made = channels.add_address(
        core,
        ws,
        chat,
        connection_id=int(_bot(core, ws)["id"]),
        address=text_arg(p, "address") or None,
        create_topic=text_arg(p, "create_topic") or None,
        notify=flag_arg(p.get("notify")),
    )
    return {"chat": chat, "address": made}


def undo_add_address(core: Core, ws: str, r: Result) -> None:
    from agos_core.actions import channels

    channels.remove_address(core, ws, int(r["chat"]), int(r["address"]))


def do_remove_address(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import channels

    channels.remove_address(
        core, ws, _chat_here(core, ws, p["chat"]), int_arg(p["address"], "the address")
    )
    return {}


def do_approve_person(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import channels

    channels.approve_person(core, int(_bot(core, ws)["id"]), text_arg(p, "request")[:64])
    return {}


def do_remove_person(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import channels

    channels.remove_person(core, int(_bot(core, ws)["id"]), text_arg(p, "user")[:100])
    return {}


# ---- workspace: templates, artifacts ----------------------------------------------------


def do_import(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import portability
    from agos_core.actions.cofounder_actions import _team_file

    path = text_arg(p, "path")
    if not path.endswith(".zip"):
        raise ActionError("Give the bundle's .zip file in the workspace.")
    target = _team_file(core, ws, path.removesuffix(".zip") + ".txt").with_suffix(".zip")
    if not target.is_file():
        raise NotFoundError("This file")
    report, _found = portability.apply(
        core,
        portability.read_zip(target.read_bytes()),
        workspace_id=ws,
        strategies=dict(p.get("strategies") or {}),
        inputs={str(k): str(v) for k, v in (p.get("inputs") or {}).items()},
        later=[str(x) for x in p.get("later") or []],
        who="cofounder",
    )
    return {"report": json.dumps(report.view(), ensure_ascii=False, default=str)[:4000]}


def do_export(core: Core, ws: str, p: Fields) -> Result:
    """The page's Export (GET /workspaces/<id>/export: the same zip, no secrets), put
    in the workspace's files where the owner and import_bundle find it."""
    from agos_core.actions import portability
    from agos_core.actions.cofounder_actions import _team_file

    name, data = portability.export_zip(core, ws)
    path = text_arg(p, "path") or f"exports/{name}"
    if not path.endswith(".zip"):
        raise ActionError("The bundle is a .zip: give a path ending in .zip.")
    target = _team_file(core, ws, path.removesuffix(".zip") + ".txt").with_suffix(".zip")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    shown = "/workspace/" + path.removeprefix("/workspace/").strip("/")
    return {"report": f"Exported to {shown} ({len(data) // 1024 + 1} KB)."}


def do_install_template(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import teams_catalog

    found = teams_catalog.install(
        core,
        text_arg(p, "slug"),
        workspace_id=ws,
        under=member_arg(p.get("under")),
        inputs={str(k): str(v) for k, v in (p.get("inputs") or {}).items()},
        later=[str(x) for x in p.get("later") or []],
    )
    return {"report": json.dumps(found, ensure_ascii=False, default=str)[:4000]}


def _artifact_state(core: Core, ws: str, artifact: str) -> dict[str, str]:
    row = artifact_reviews.get(core.db, ws, artifact)
    return (
        {"state": str(row["state"]), "note": str(row["note"])} if row else {"state": "", "note": ""}
    )


def do_review_artifact(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import artifacts

    artifact = text_arg(p, "artifact")
    before = _artifact_state(core, ws, artifact)
    artifacts.review(core, ws, artifact, text_arg(p, "state"), text_arg(p, "note"))
    return {"artifact": artifact, "before": before}


def undo_review_artifact(core: Core, ws: str, r: Result) -> None:
    from agos_core.actions import artifacts

    b = r["before"]
    artifacts.review(core, ws, str(r["artifact"]), str(b["state"]), str(b["note"]))


def do_promote(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import artifacts

    found = artifacts.promote(
        core,
        ws,
        text_arg(p, "card"),
        int_arg(p["attachment"], "the attachment"),
        text_arg(p, "key"),
    )
    return {"report": json.dumps(found, ensure_ascii=False, default=str)[:1000]}
