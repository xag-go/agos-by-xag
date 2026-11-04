"""Writing a workspace's skills: create, save, delete, the shipped skills kept up to date, telling Hermes.
Must not: copy or install skills from elsewhere.

Split out of agos_core.actions.workspace_skills (which re-exports it); behaviour unchanged.
"""

from __future__ import annotations

import contextlib
import logging
import threading
from typing import Any

from agos_core.actions.errors import ActionError, NotFoundError
from agos_core.actions.services.library.skill_folders import (
    FOLDER,
    _home,
    _row,
    existing_dir,
    never_written,
    stored,
)
from agos_core.actions.workspaces import require_workspace
from agos_core.context import Core
from agos_core.db import library as repo
from agos_core.db.connection import transaction
from agos_core.engine import library as lib
from agos_core.engine.library import LibraryError
from agos_core.hermes_gateway import cli as hermes_cli

__all__ = [
    "applied",
    "create",
    "curator_archive",
    "delete",
    "ensure_shipped",
    "rewrite_shipped",
    "save",
]

log = logging.getLogger("agos.workspace_skills")  # the old module's logger (one name)

# ---- writing: Hermes's skill_manage in the workspace's root ----------------------------


def _write(
    core: Core,
    workspace_id: str,
    name: str,
    text: str,
    files: dict[str, str] | None = None,
    *,
    create: bool = False,
    actor: str = "user",
    author: str = "",
    summary: str = "",
) -> list[str]:
    """SKILL.md and the files named (a file given as "" goes), by Hermes's own
    skill_manage in the workspace's root, so each change is in its skill ledger.
    Every other file of the skill stays as it is (actions/skill_writes.py)."""
    from agos_core.actions import skill_versions, skill_writes

    current = existing_dir(core, workspace_id, name)
    create = create or current is None
    entries = skill_writes.write(
        core,
        _home(core, workspace_id),
        name,
        None if create else current,
        text,
        files,
        create=create,
        category=FOLDER if create else None,
        actor=actor,
    )
    skill_versions.record(
        core,
        workspace_id,
        name,
        entries,
        author=author or ("owner" if actor == "user" else "cofounder"),
        action="create" if create else "edit",
        summary=summary or ("created in AGOS" if create else "edited in AGOS"),
    )
    return entries


def _checked(name: str, given: dict[str, Any]) -> dict[str, Any]:
    from agos_core.actions.library import _checked as checked

    try:
        lib.check_name(name)
        clean, _summary = checked("skill", name, "", given)
    except LibraryError as error:
        raise ActionError(str(error)) from error
    return clean


def _title(name: str, title: str) -> str:
    title = title.strip()
    return "" if not title or title == name else title  # its SKILL.md name is the one copy


def applied(core: Core, workspace_id: str) -> None:
    """This workspace only: its playbooks and Co-Founder view show the change; its
    profiles' switches are written again (nothing of another workspace moves)."""
    from agos_core.actions import library

    problem = library.apply_workspace(core, workspace_id)
    if problem and problem != "This workspace's agent isn't set up yet.":
        log.warning("skills of %s not applied: %s", workspace_id, problem)


# One new skill at a time: an unfinished one is never taken for an empty card.
_new_skills = threading.Lock()


def create(
    core: Core,
    workspace_id: str,
    name: str,
    *,
    title: str,
    given: dict[str, Any],
    source: str = "created",
    extra: dict[str, Any] | None = None,
) -> int:
    """A new skill of this workspace, on in it at once. Hermes's own checks of a new
    skill come first, so its refusal (e.g. a description longer than the skill
    index's budget) changes nothing and comes back with Hermes's reason. When
    Hermes doesn't write it, its row goes too: no empty skill is left behind. No
    other workspace is touched."""
    from agos_core.actions import skill_writes

    require_workspace(core, workspace_id)
    clean = _checked(name, given)
    text, files = str(clean["text"]), clean.get("files")
    home = _home(core, workspace_id)
    with _new_skills:
        found = repo.find_item(core.db, "skill", name, workspace_id)
        if found is not None and never_written(core, found):
            # An empty card left by an earlier create Hermes refused: it goes, and
            # this one is made under the same name.
            repo.delete_item(core.db, int(found["id"]))
            found = None
        if found is not None or existing_dir(core, workspace_id, name) is not None:
            raise ActionError(f"This workspace already has a skill named {name}.", 409)
        skill_writes.check_new(core, home, name, text, files)
        with transaction(core.db):
            new_id = repo.insert_item(
                core.db,
                kind="skill",
                name=name,
                title=_title(name, title),
                summary="",
                definition={**stored(clean), **(extra or {})},
                source=source,
                workspace_id=workspace_id,
            )
        try:
            _write(core, workspace_id, name, text, files, create=True)
        except Exception:
            if existing_dir(core, workspace_id, name) is None:
                with contextlib.suppress(Exception), transaction(core.db):
                    repo.delete_item(core.db, new_id)
            raise
    applied(core, workspace_id)
    return new_id


def save(
    core: Core, workspace_id: str, item_id: int, *, name: str, title: str, given: dict[str, Any]
) -> int:
    """The owner's edit: the workspace's one copy changes (its whole team reads it)."""
    row = _row(core, workspace_id, item_id)
    if row["name"] != name:
        raise ActionError("The name can't change; duplicate it instead.")
    clean = _checked(name, given)
    repo.update_item(
        core.db,
        item_id,
        title=_title(name, title),
        summary="",
        definition={**repo.definition(row), **stored(clean)},
    )
    _write(core, workspace_id, name, str(clean["text"]), clean.get("files"))
    applied(core, workspace_id)
    return item_id


def rewrite_shipped(core: Core, workspace_id: str, name: str, text: str, *, summary: str) -> None:
    """A skill AGOS ships and owns (the Co-Founder's team-design) written back to
    AGOS's text when the workspace's copy differs (the caller checks): Hermes's
    skill_manage writes it, its version says AGOS did."""
    if existing_dir(core, workspace_id, name) is None:
        raise NotFoundError("This skill")
    _write(core, workspace_id, name, text, author="agos", summary=summary)
    applied(core, workspace_id)


def ensure_shipped(
    core: Core,
    workspace_id: str,
    name: str,
    title: str,
    text: str,
    *,
    done: set[str],
    lock: threading.Lock,
) -> bool:
    """One of AGOS's background skills (agos_owned: team-design, find-skills) in the
    workspace at its shipped text, once per core start (`done` holds who has it):
    made through Hermes's skill_manage when missing, written back when its copy
    differs (a recorded version labelled 'agos'), left alone when equal. True when
    it was made or rewritten now. Never raises."""
    done_key = f"{core.layout.root}\0{workspace_id}"
    if core.engine is None or done_key in done:
        return False
    with lock:
        if done_key in done:
            return False
        try:
            found = existing_dir(core, workspace_id, name)
            if found is not None:
                current = (found / "SKILL.md").read_text(encoding="utf-8")
                rewritten = current.strip() != text.strip()
                if rewritten:
                    rewrite_shipped(
                        core, workspace_id, name, text, summary="AGOS's shipped version"
                    )
                done.add(done_key)
                return rewritten
            if repo.find_item(core.db, "skill", name, workspace_id) is not None:
                done.add(done_key)
                return False
            if not (core.engine.profile_home(workspace_id) / "config.yaml").is_file():
                return False  # no root yet: next time
            create(core, workspace_id, name, title=title, given={"text": text}, source="agos")
        except (ActionError, OSError) as error:
            log.warning("%s skill not installed in %s: %s", name, workspace_id, error)
            return False
        except Exception:
            log.exception("%s skill not installed in %s", name, workspace_id)
            return False
        done.add(done_key)
        return True


def curator_archive(core: Core, workspace_id: str) -> Any:
    """Hermes's `hermes curator archive <skill>` in the workspace's root."""

    def archive(skill: str) -> None:
        assert core.engine is not None
        hermes_cli.cli(core.engine, workspace_id, "curator", "archive", skill)

    return archive


def delete(core: Core, workspace_id: str, item_id: int) -> None:
    """The skill goes from this workspace: Hermes's curator archives its folder
    (recoverable with `hermes curator restore`), then its row goes."""
    from agos_core.actions.library import workspace_lock

    row = _row(core, workspace_id, item_id)
    with workspace_lock(workspace_id):
        if existing_dir(core, workspace_id, str(row["name"])) is not None:
            try:
                lib.archive_skill(
                    _home(core, workspace_id),
                    str(row["name"]),
                    archive=curator_archive(core, workspace_id),
                )
            except LibraryError as error:
                raise ActionError(str(error), 409) from error
        with transaction(core.db):
            repo.delete_item(core.db, item_id)
    applied(core, workspace_id)
