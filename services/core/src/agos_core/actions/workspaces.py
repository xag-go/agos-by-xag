"""Creating, configuring, archiving and deleting workspaces; their folders."""

import contextlib
import shutil
import threading
from collections.abc import Callable
from types import ModuleType
from typing import Any, Literal

from agos_core import events
from agos_core.actions import access, idle, memory_plugin, tool_services
from agos_core.actions import engine as engine_actions
from agos_core.actions.engine import (
    check_grant,
    delete_engine_data,
    move_description,
    move_name,
    park_workspace,
    sync_workspace,
    write_identity,
)
from agos_core.actions.errors import ActionError, NotFoundError
from agos_core.context import Core
from agos_core.db import chats as chats_repo
from agos_core.db import sagas as sagas_repo
from agos_core.db import workspaces as repo
from agos_core.db.activity import add_activity
from agos_core.db.connection import transaction
from agos_core.db.records import Workspace
from agos_core.domain.models import ModelSelection
from agos_core.domain.workspace import is_workspace_id, workspace_id_from_name
from agos_core.engine.hermes import EngineError
from agos_core.engine.rules import Grant
from agos_core.saga import Saga
from agos_core.storage.folders import FolderNotAllowedError, check_added_folder, share_name
from agos_core.storage.layout import (
    create_workspace_folders,
    move_workspace_to_trash,
    restore_workspace_from_trash,
    workspace_paths,
)
from agos_core.storage.paths import is_inside
from agos_core.uow import UnitOfWork


def _automations() -> ModuleType:
    """Imported late: automations need require_workspace from here."""
    from agos_core.actions import automations

    return automations


def require_workspace(core: Core, workspace_id: str) -> Workspace:
    workspace = repo.get_workspace(core.db, workspace_id)
    if workspace is None:
        raise NotFoundError("This workspace")
    return workspace


def listed(core: Core, *, include_archived: bool = False) -> list[Workspace]:
    """The workspaces not in the trash, in the owner's sidebar order."""
    return repo.list_workspaces(core.db, include_archived=include_archived)


def archived_list(core: Core) -> list[Workspace]:
    return [w for w in repo.list_workspaces(core.db, include_archived=True) if w.archived]


def trashed(core: Core) -> list[dict[str, str]]:
    """The workspaces in the trash (until they are purged)."""
    return repo.list_trashed(core.db)


def _checked_name(name: str) -> str:
    """The name Hermes can hold as the Co-Founder's display name."""
    clean = name.strip()
    if not clean:
        raise ActionError("Give the workspace a name.")
    if len(clean) > repo.NAME_MAX:
        raise ActionError(f"Keep the name to {repo.NAME_MAX} characters (Hermes's limit).")
    return clean


CREATE_SAGA = "workspace.create"
DELETE_SAGA = "workspace.delete"


def _free_id(core: Core, name: str) -> str:
    base = workspace_id_from_name(name)
    if not is_workspace_id(base):
        raise ActionError("Use at least one letter or digit in the name.")
    workspace_id, n = base, 2
    while (
        repo.workspace_id_taken(core.db, workspace_id)
        or workspace_paths(core.layout, workspace_id).root.exists()
        # A leftover Hermes profile (memory, sessions) must never be inherited.
        or (core.engine is not None and core.engine.profile_home(workspace_id).exists())
    ):
        workspace_id, n = f"{base[:58]}-{n}", n + 1
    return workspace_id


def _insert_rows(core: Core, workspace_id: str, name: str, description: str) -> None:
    with UnitOfWork(core, name="create workspace", workspace_id=workspace_id):
        repo.insert_workspace(
            core.db,
            workspace_id=workspace_id,
            name=name,
            description=description,
        )
        add_activity(core.db, workspace_id, kind="workspace.created", text="Workspace created")
        # Every workspace starts with its General chat (departments add their own).
        chats_repo.insert_chat(
            core.db,
            workspace_id=workspace_id,
            title="General",
            channel="web",
        )


def _drop_new_rows(core: Core, workspace_id: str) -> None:
    """A create undone: its rows (and every row tied to it) go, as a purge would."""
    with UnitOfWork(core, name="undo create workspace", workspace_id=workspace_id):
        repo.mark_deleted(core.db, workspace_id, "")
        repo.purge_deleted(core.db, workspace_id)


def _setup_steps(
    core: Core, workspace_id: str, model: ModelSelection
) -> dict[str, Callable[[], object]]:
    """The Hermes setup of a new workspace that may be finished later: the step
    name -> what it does (create_workspace runs them, finish_setup again)."""
    from agos_core.actions import autonomy, docs  # both import this module

    return {
        # Every Hermes tool AGOS can give safely is on from the start (he turns off what
        # he doesn't want): a root AGOS never set up has them all on (hermes_config).
        "sync": lambda: sync_workspace(core, workspace_id),
        # The owner's General config: Full access (he switches it in Settings), and its
        # starting Autonomy table, both written into its own Hermes.
        "access": lambda: access.set_workspace(core, workspace_id, True),
        "autonomy": lambda: autonomy.seed_new_workspace(core, workspace_id),
        # Its model: written into its Hermes, the one place it lives.
        "model": lambda: engine_actions.set_model(core, workspace_id, model),
        "docs": lambda: docs.ensure(core, workspace_id),  # README, team, flow
    }


# What each setup step may fail with and be finished later (anything else undoes
# the whole create).
_LATER: dict[str, tuple[type[BaseException], ...]] = {
    "sync": (ActionError,),
    "access": (EngineError, OSError),
    "autonomy": (OSError,),
    "model": (EngineError, OSError),
    "docs": (ActionError, OSError),
}


def create_workspace(
    core: Core,
    *,
    name: str,
    description: str,
    default_model: ModelSelection,
) -> str:
    """A saga (CREATE_SAGA): folders, rows, then its Hermes setup. A step that
    fails for good undoes the ones before it (no half-made workspace); a setup
    step Hermes refused now (Docker down...) is journaled for finish_setup, and the
    workspace exists meanwhile with its agent stopped (fail closed)."""
    name = _checked_name(name)
    workspace_id = _free_id(core, name)
    data = {"default_model": default_model.model_dump(mode="json", by_alias=True)}
    # Holographic's install holds the root's config lock while it downloads: it
    # starts once the setup below is done (actions/memory_plugin.py).
    with memory_plugin.after_setup(core), Saga(core, CREATE_SAGA, data=data) as saga:
        saga.step(
            "folders",
            lambda: create_workspace_folders(core.layout, workspace_id),
            undo=lambda made: shutil.rmtree(made.root, ignore_errors=True),
        )
        saga.step(
            "rows",
            lambda: _insert_rows(core, workspace_id, name, description),
            undo=lambda _: _drop_new_rows(core, workspace_id),
        )
        saga.attach(workspace_id)
        # Whatever the steps below write into its Hermes goes with its root.
        saga.step("hermes", lambda: None, undo=lambda _: delete_engine_data(core, workspace_id))
        setup = _setup_steps(core, workspace_id, default_model)
        saga.step("sync", setup.pop("sync"), tolerate=_LATER["sync"])
        # The tools' services already set up in Settings (pictures, voice…).
        saga.step("tool_services", lambda: tool_services.apply_to(core, workspace_id))
        for step, do in setup.items():
            saga.step(step, do, tolerate=_LATER[step])
        # Its gateway is installed and started as Hermes's own service now (Hermes's
        # Restart=always keeps it up from there; a message never starts one). The
        # test-only "spawn" supervisor starts it when work arrives (idle.spawned_up).
        if core.engine is not None and core.engine.settings.gateway_supervisor != "spawn":
            saga.step("serve", lambda: _serve(core, workspace_id))
    events.publish(core, events.Event(events.WORKSPACE_CREATED, workspace_id, {"name": name}))
    return workspace_id


def finish_setup(core: Core, workspace_id: str) -> list[str]:
    """Runs again the setup steps a create left to finish; returns those still left."""
    left: list[str] = []
    for row in sagas_repo.open_sagas(core.db, CREATE_SAGA, workspace_id):
        model = ModelSelection.model_validate(
            sagas_repo.data_of(core.db, int(row["id"])).get("default_model")
        )
        left += Saga.resume(core, int(row["id"]), _setup_steps(core, workspace_id, model))
    return left


def save_settings(
    core: Core,
    workspace_id: str,
    *,
    name: str,
    description: str,
    default_model: ModelSelection,
    chat_access: str = "ask",
) -> None:
    current = require_workspace(core, workspace_id)
    chat_access = chat_access if chat_access in ("ask", "full") else "ask"
    name = _checked_name(name)
    with transaction(core.db):
        if name != current.name:
            repo.update_workspace(core.db, workspace_id, name=name)
        if description != current.description:
            repo.set_pending_description(core.db, workspace_id, description)
    if name != current.name:
        move_name(core, workspace_id)
    if description != current.description:
        move_description(core, workspace_id)
    if (name, description) != (current.name, current.description):
        write_identity(core, workspace_id)
    if chat_access != current.chat_access:
        # Full access / Ask me is Hermes's own approvals setting on its profiles.
        try:
            access.set_workspace(core, workspace_id, chat_access == "full")
        except (EngineError, OSError) as error:
            raise ActionError(
                "Saved, but Hermes didn't take the new access. Try again.", 503
            ) from error
    if default_model != current.default_model:
        # Straight into the workspace's Hermes (its default model; AGOS keeps no copy).

        try:
            engine_actions.set_model(core, workspace_id, default_model)
        except (EngineError, OSError) as error:
            raise ActionError("Hermes didn't take the new model. Try again.", 503) from error


def _change_folders(
    core: Core, workspace_id: str, grants: list[Any], done: Any, kind: str, text: str
) -> None:
    """The owner's folder change goes into the workspace's Hermes (its
    terminal.docker_volumes, the one list). The click answers once Hermes's list
    holds it; the gateway restart the mounts need (ADR 0010) follows in the
    background (engine_actions.restart_later; the page shows it running and how it
    ended). `done(found)` says whether Hermes's list now has the change; when the
    write failed before Hermes took it, he is told it wasn't saved (the list he sees
    is still Hermes's)."""

    if core.engine is None:
        raise ActionError("The engine is off: folders live in the workspace's Hermes.", 409)
    try:
        engine_actions.save_folders(core, workspace_id, grants)
    except ActionError as error:
        if not done(engine_actions.folders(core, workspace_id)):
            raise ActionError(
                "Not saved: the workspace's Hermes didn't take it, and the agent is stopped. "
                "Check that Docker is running, then try again.",
                503,
            ) from error
        add_activity(core.db, workspace_id, kind=kind, text=text)
        raise
    add_activity(core.db, workspace_id, kind=kind, text=text)
    engine_actions.restart_later(core, workspace_id)


def add_folder(core: Core, workspace_id: str, *, path: str, access: str) -> str:

    require_workspace(core, workspace_id)
    try:
        real = check_added_folder(core.layout, path)
    except FolderNotAllowedError as error:
        raise ActionError(f"Can't add it: {error}.") from error
    if is_inside(workspace_paths(core.layout, workspace_id).root.resolve(), real):
        raise ActionError("This folder is already part of this workspace.")
    existing = engine_actions.folders(core, workspace_id)
    if any(f.host_path == str(real) for f in existing):
        raise ActionError("This folder is already added.")
    name = share_name(real, [f.name for f in existing])
    check_grant(core, workspace_id, real, name)
    # Read only unless he asks for read and write.
    access_value: Literal["read", "read-write"] = "read-write" if access == "read-write" else "read"
    grants = [Grant(name=f.name, host_path=f.host_path, access=f.access) for f in existing]
    grants.append(Grant(name=name, host_path=str(real), access=access_value))
    _change_folders(
        core,
        workspace_id,
        grants,
        lambda found: any(f.name == name for f in found),
        "folder.added",
        f"Folder added: /shared/{name} ({'read only' if access_value == 'read' else 'read and write'})",
    )
    return name


def set_folder_access(core: Core, workspace_id: str, name: str, access: str) -> None:

    access_value: Literal["read", "read-write"] = "read-write" if access == "read-write" else "read"
    existing = engine_actions.folders(core, workspace_id)
    if not any(f.name == name and f.access != access_value for f in existing):
        return
    grants = [
        Grant(
            name=f.name, host_path=f.host_path, access=access_value if f.name == name else f.access
        )
        for f in existing
    ]
    _change_folders(
        core,
        workspace_id,
        grants,
        lambda found: any(f.name == name and f.access == access_value for f in found),
        "folder.access",
        f"Folder /shared/{name} is now {'read only' if access_value == 'read' else 'read and write'}",
    )


def remove_folder(core: Core, workspace_id: str, name: str) -> None:

    existing = engine_actions.folders(core, workspace_id)
    if not any(f.name == name for f in existing):
        return
    grants = [
        Grant(name=f.name, host_path=f.host_path, access=f.access)
        for f in existing
        if f.name != name
    ]
    _change_folders(
        core,
        workspace_id,
        grants,
        lambda found: not any(f.name == name for f in found),
        "folder.removed",
        f"Folder removed: /shared/{name}",
    )


def archive(core: Core, workspace_id: str, archived: bool) -> None:
    if archived:
        require_workspace(core, workspace_id)
    if archived:
        _automations().park(core, workspace_id)
        park_workspace(core, workspace_id)
    repo.set_archived(core.db, workspace_id, archived)
    if not archived:
        finish_setup(core, workspace_id)  # what its create left, Hermes may take now
        _automations().resync_workspace(core, workspace_id)
        _serve(core, workspace_id)
    if archived:
        add_activity(core.db, workspace_id, kind="workspace.archived", text="Workspace archived")


def delete_to_trash(core: Core, workspace_id: str, confirm: str) -> None:
    """A saga (DELETE_SAGA): nothing runs for it any more (automations, then its
    agent), then the folder moves to the trash, then the row is marked. A step
    that fails starts again what the earlier ones stopped."""
    workspace = require_workspace(core, workspace_id)
    if confirm != workspace.id:
        raise ActionError(f"Type {workspace.id} to confirm.")
    with Saga(core, DELETE_SAGA, workspace_id=workspace.id) as saga:
        saga.step(
            "automations",
            lambda: _automations().park(core, workspace.id),
            undo=lambda _: _automations().resync_workspace(core, workspace.id),
        )
        saga.step(
            "agent",
            lambda: park_workspace(core, workspace.id),
            undo=lambda _: _serve(core, workspace.id),
        )
        trash_name = saga.step(
            "folder",
            lambda: move_workspace_to_trash(core.layout, workspace.id),
            undo=lambda name: restore_workspace_from_trash(core.layout, name),
        )
        assert trash_name is not None
        saga.step("row", lambda: repo.mark_deleted(core.db, workspace.id, trash_name))
    events.publish(core, events.Event(events.WORKSPACE_TRASHED, workspace.id))


def restore(core: Core, workspace_id: str) -> None:
    entry = next((t for t in repo.list_trashed(core.db) if t["id"] == workspace_id), None)
    if entry is None:
        raise NotFoundError("This trash entry")
    restore_workspace_from_trash(core.layout, entry["trashName"])
    repo.restore_deleted(core.db, workspace_id)
    with contextlib.suppress(ActionError):
        sync_workspace(core, workspace_id)
    finish_setup(core, workspace_id)  # what its create left, Hermes may take now
    _automations().resync_workspace(core, workspace_id)  # its profile (and model) stayed
    _serve(core, workspace_id)


def _serve(core: Core, workspace_id: str) -> None:
    """Back from the archive or the trash: its gateway runs again as Hermes's own
    service (in the background; Hermes keeps it up from there)."""
    threading.Thread(
        target=idle.ensure, args=(core, workspace_id), name=f"serve-{workspace_id}", daemon=True
    ).start()


def purge(core: Core, workspace_id: str) -> None:
    entry = next((t for t in repo.list_trashed(core.db) if t["id"] == workspace_id), None)
    if entry is None:
        return
    folder = core.layout.trash / entry["trashName"]
    if is_inside(core.layout.trash.resolve(), folder.resolve()):
        shutil.rmtree(folder, ignore_errors=True)
    from agos_core.actions.apps import forget_workspace  # apps imports this module

    forget_workspace(core, workspace_id)  # its own app logins (Google revoked)
    repo.purge_deleted(core.db, workspace_id)
    delete_engine_data(core, workspace_id)
