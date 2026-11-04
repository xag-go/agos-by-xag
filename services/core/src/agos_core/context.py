"""Everything a request needs: database, data folders, keys."""

import os
import secrets
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from agos_core.config import Settings
from agos_core.db.connection import open_database
from agos_core.engine.hermes import HermesEngine
from agos_core.security.secrets import load_or_create_master_key
from agos_core.storage.layout import DataLayout, data_layout, ensure_data_layout


@dataclass(frozen=True)
class Core:
    db: sqlite3.Connection
    layout: DataLayout
    master_key: bytes
    internal_token: str
    settings: Settings
    engine: HermesEngine | None = None


def load_or_create_internal_token(file: Path) -> str:
    """Shared secret between the web app and the core, created once (0600).
    In Docker it lives on a small volume the web app mounts read-only."""
    try:
        token = file.read_text().strip()
    except FileNotFoundError:
        token = ""
    if len(token) >= 32:
        return token
    file.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    token = secrets.token_urlsafe(32)
    fd = os.open(file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o640)
    with os.fdopen(fd, "w") as handle:
        handle.write(token)
    return token


def open_core(settings: Settings) -> Core:
    layout = data_layout(settings.data_dir)
    ensure_data_layout(layout)
    core = Core(
        db=open_database(layout.database),
        layout=layout,
        master_key=load_or_create_master_key(layout.master_key),
        internal_token=load_or_create_internal_token(settings.internal_token_file),
        settings=settings,
        engine=HermesEngine(settings.engine) if settings.engine else None,
    )
    read_models_from_hermes(core)
    if core.engine is not None:
        engine = core.engine
        from agos_core.engine import hermes_redact

        redactor = hermes_redact.Redactor(
            engine.settings.hermes_bin, str(engine.settings.host_home)
        )
        hermes_redact.use(redactor)
        import threading

        threading.Thread(target=redactor.warm, name="hermes-redact-warm", daemon=True).start()
        # Keys he pastes in his own messages: masked by Hermes before AGOS keeps them.
        from agos_core.engine import owner_keys

        helper = owner_keys.KeysHelper(engine.settings.hermes_bin, str(engine.settings.host_home))
        owner_keys.use(helper)
        threading.Thread(target=helper.warm, name="owner-keys-warm", daemon=True).start()
        # A chat is its Hermes conversation, read from the workspace's own Hermes.
        from agos_core.db import hermes_chats
        from agos_core.hermes_gateway import chat_sessions

        hermes_chats.install(
            chat_sessions.Store(engine.home_of, engine.profile, engine.own_profiles)
        )
    return core


def stop_reading_hermes() -> None:
    """The core stops: the readers set at its start go with it."""
    from agos_core.db import chats as chats_repo
    from agos_core.db import workspaces as workspaces_repo

    workspaces_repo.model_reader = None
    workspaces_repo.access_reader = None
    workspaces_repo.description_reader = None
    workspaces_repo.name_reader = None
    workspaces_repo.icon_reader = None
    chats_repo.access_reader = None
    chats_repo.member_title_reader = None
    chats_repo.card_title_reader = None
    from agos_core.db import hermes_switches

    hermes_switches.bot_reader = None


def read_models_from_hermes(core: "Core") -> None:
    """A workspace's model is read from its Hermes profile (the one copy)."""
    from agos_core.actions import engine as engine_actions
    from agos_core.db import workspaces as workspaces_repo

    workspaces_repo.model_reader = lambda ws: engine_actions.workspace_model(core, ws)
    from agos_core.actions import access

    workspaces_repo.access_reader = lambda ws: access.workspace_full(core, ws)
    workspaces_repo.description_reader = lambda ws: engine_actions.workspace_description(core, ws)
    workspaces_repo.name_reader = lambda ws: engine_actions.workspace_name(core, ws)
    from agos_core.storage import workspace_icon

    workspace_icon.forget()

    workspaces_repo.icon_reader = lambda ws: workspace_icon.stamp(core.layout, ws)
    from agos_core.db import chats as chats_repo

    chats_repo.access_reader = lambda ws, chat: access.chat_full(core, ws, chat)
    from agos_core.actions import kanban_board, team

    chats_repo.member_title_reader = lambda ws, name: team.title_of(core, ws, name)
    chats_repo.card_title_reader = lambda ws, card: (
        kanban_board.facts(core, ws, [card]).get(card, {}).get("title") or None
    )
    from agos_core.actions import hermes_channel
    from agos_core.db import hermes_switches

    hermes_switches.bot_reader = lambda ws: hermes_channel.bot_on(core, ws)
