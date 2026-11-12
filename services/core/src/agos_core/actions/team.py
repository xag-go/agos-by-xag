"""The team: who is on it, and who each member is, is its Hermes profiles.

A member is a named profile in the workspace's root (`<root>/profiles/a-<name>`,
ADR 0020). Everything about it is that profile's own Hermes data, read from there
each time and written there only:
- on the team: the profile exists (Hermes's profile list); off the team: Hermes's
  `gateway.parked` marker (the root's gateway stops serving it, its memory stays);
- job title: profile.yaml `display_name` (Hermes's presentation name, the one the
  owner renames);
- what it's for: profile.yaml `description` (`hermes profile describe`; Hermes's
  Kanban decomposer routes cards by it);
- role text and the owner's notes for it: its SOUL.md (agent_profiles writes it);
- model: its config's `model.*` and `agent.reasoning_effort` (`hermes config set`);
- skills: its config's `skills.auto_load` (Hermes loads them in every session);
- what Hermes has no key for: profile.yaml `ui_meta.agos` (the rule files it reads,
  and whether its model is its own or follows the workspace's).

AGOS keeps only an id per member (a bare `library_items` row: the web's links and
the Connectors list use it), made and dropped to follow the profiles.
"""

from __future__ import annotations

import contextlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agos_core.actions.errors import ActionError, NotFoundError
from agos_core.context import Core
from agos_core.db import chats as chats_repo
from agos_core.db import library as library_repo
from agos_core.db.rows import dump_json
from agos_core.engine import config_file, profile_meta
from agos_core.engine import library as lib
from agos_core.engine.hermes import EngineError
from agos_core.hermes_gateway import cli as hermes_cli

log = logging.getLogger("agos.team")

PREFIX = "a-"  # a member's Hermes profile name: a-<name>
NOT_SET_UP = "This workspace's agent isn't set up yet."


@dataclass(frozen=True)
class Agent:
    """One member, as its Hermes profile says."""

    id: int
    workspace_id: str
    name: str
    title: str
    summary: str
    instructions: str
    local: str
    model: dict[str, Any] | None
    skills: list[str] = field(default_factory=list)
    reads: list[dict[str, str]] = field(default_factory=list)
    on: bool = True
    reports_to: str = ""  # "" = the Co-Founder; else the member it reports to

    @property
    def definition(self) -> dict[str, Any]:
        return {
            "instructions": self.instructions,
            "model": self.model,
            "skills": list(self.skills),
            "reads": [dict(r) for r in self.reads],
            "reports_to": self.reports_to,
        }

    def row(self) -> dict[str, Any]:
        """The member shaped like a library item row (for code that lists items)."""
        return {
            "id": self.id,
            "kind": "agent",
            "name": self.name,
            "title": self.title,
            "summary": self.summary,
            "definition": dump_json(self.definition),
            "source": "hermes",
            "workspace_id": self.workspace_id,
        }


# ---- reading ----------------------------------------------------------------------


def key(workspace_id: str, name: str) -> str:
    return f"{workspace_id}--{PREFIX}{name}"


def home(core: Core, workspace_id: str, name: str) -> Path | None:
    if core.engine is None:
        return None
    return core.engine.profile_home(key(workspace_id, name))


# What makes a folder under profiles/ a profile for Hermes (hermes_constants.py
# `named_profile_has_identity`); a deleted one has a tombstone in profiles/.deleted.
IDENTITY = ("config.yaml", ".env", "SOUL.md", "profile.yaml", "auth.json", "state.db")


def _profile_names(core: Core, workspace_id: str) -> list[str]:
    """The members' names: the root's `a-…` profiles, as Hermes lists them."""
    engine = core.engine
    if engine is None:
        return []
    folder = engine.root(workspace_id) / "profiles"
    if not folder.is_dir():
        return []
    names = []
    for entry in sorted(folder.iterdir()):
        name = entry.name[len(PREFIX) :]
        if (
            entry.is_dir()
            and entry.name.startswith(PREFIX)
            and lib.NAME.fullmatch(name)
            and any((entry / marker).is_file() for marker in IDENTITY)
            and not (folder / ".deleted" / entry.name).exists()
        ):
            names.append(name)
    return names


def _ids(core: Core, workspace_id: str, names: list[str], *, every: bool) -> dict[str, int]:
    """AGOS's id of each member (made for a new profile). With `every` (the whole
    team was read), a bare id whose profile is gone is dropped too."""
    rows = library_repo.agent_ids(core.db, workspace_id)
    out: dict[str, int] = {}
    for name in names:
        found = rows.get(name)
        if found is None:
            out[name] = library_repo.insert_item(
                core.db,
                kind="agent",
                name=name,
                title="",
                summary="",
                definition={},
                source="hermes",
                workspace_id=workspace_id,
            )
        else:
            out[name] = found
    for name, item_id in rows.items() if every else ():
        # A bare id whose profile is gone goes too.
        if name not in out:
            library_repo.delete_item(core.db, item_id)
    return out


def _model(cfg: dict[str, Any]) -> dict[str, Any] | None:
    from agos_core.engine.models import selection_from_hermes

    effort = config_file.get(cfg, "agent.reasoning_effort")
    selection = selection_from_hermes(
        str(config_file.get(cfg, "model.provider") or ""),
        str(config_file.get(cfg, "model.default") or ""),
        str(effort) if effort else None,
    )
    return selection.model_dump() if selection is not None else None


def _reads(raw: Any) -> list[dict[str, str]]:
    return list(lib.check_agent({"instructions": "-", "reads": raw or []})["reads"])


def _read(core: Core, workspace_id: str, name: str, item_id: int) -> Agent:
    where = home(core, workspace_id, name)
    assert where is not None
    meta = profile_meta.read(where)
    facts = profile_meta.agos(meta)
    title = profile_meta.display_name(meta) or lib.readable_title(name)
    about = profile_meta.description(meta)
    try:
        soul = (where / "SOUL.md").read_text(encoding="utf-8")
    except OSError:
        soul = ""
    instructions, local = lib.soul_role(soul)
    cfg = config_file.read(where)
    skills = config_file.string_list(config_file.get(cfg, "skills.auto_load")) or []
    return Agent(
        id=item_id,
        workspace_id=workspace_id,
        name=name,
        title=title,
        summary="" if about == title else about,
        instructions=instructions or "",
        local=local,
        model=_model(cfg) if facts.get("own_model") else None,
        skills=list(skills),
        reads=_reads(facts.get("reads")),
        on=not profile_meta.parked(where),
        reports_to=lib.reports_to(facts.get("reports_to")),
    )


def members(core: Core, workspace_id: str, *, on_only: bool = False) -> list[Agent]:
    """The workspace's team, by job title (off ones too unless `on_only`)."""
    names = _profile_names(core, workspace_id)
    ids = _ids(core, workspace_id, names, every=True)
    out = [_read(core, workspace_id, n, ids[n]) for n in names]
    return sorted((a for a in out if a.on or not on_only), key=lambda a: (a.title.lower(), a.name))


def get(core: Core, workspace_id: str, name: str) -> Agent | None:
    if not name or not lib.NAME.fullmatch(name) or name not in _profile_names(core, workspace_id):
        return None
    return _read(core, workspace_id, name, _ids(core, workspace_id, [name], every=False)[name])


def names(core: Core, workspace_id: str) -> list[str]:
    """The members on the team now (read only the profiles' folders: cheap)."""
    out = []
    for name in _profile_names(core, workspace_id):
        where = home(core, workspace_id, name)
        if where is not None and not profile_meta.parked(where):
            out.append(name)
    return out


def by_id(core: Core, item_id: int) -> Agent | None:
    row = library_repo.get_item(core.db, item_id)
    if row is None or row["kind"] != "agent" or not row["workspace_id"]:
        return None
    return get(core, str(row["workspace_id"]), str(row["name"]))


def title_of(core: Core, workspace_id: str, name: str) -> str:
    """The job title the owner gave the member (its name made readable without one)."""
    where = home(core, workspace_id, name) if lib.NAME.fullmatch(name or "") else None
    found = profile_meta.display_name(profile_meta.read(where)) if where is not None else ""
    return found or lib.readable_title(name)


# ---- writing ----------------------------------------------------------------------


def _set(core: Core, profile_key: str, cfg: dict[str, Any], pairs: dict[str, str]) -> None:
    """`hermes config set` of each value the profile doesn't have yet."""
    assert core.engine is not None
    for name, value in pairs.items():
        have = config_file.get(cfg, name)
        try:
            same = have == json.loads(value)
        except ValueError:
            same = str(have if have is not None else "") == value
        if not same:
            hermes_cli.cli(core.engine, profile_key, "config", "set", name, value)


def _model_pairs(core: Core, workspace_id: str, model: dict[str, Any] | None) -> dict[str, str]:
    from agos_core.actions.engine import _default_model
    from agos_core.engine.models import hermes_slug
    from agos_core.engine.rules import model_pairs

    if model is not None:
        provider = hermes_slug(str(model["provider"]), str(model.get("mode") or "subscription"))
        # No effort picked: Hermes's own default (no agent.reasoning_effort written).
        return model_pairs(provider, str(model["model"]), str(model.get("effort") or ""))
    found = _default_model(core, workspace_id)  # the workspace's own (the Co-Founder's)
    return model_pairs(*found) if found is not None else {}


def _describe(core: Core, workspace_id: str, name: str, text: str) -> None:
    """Hermes's description of the profile (`hermes profile describe --text`)."""
    where = home(core, workspace_id, name)
    assert core.engine is not None and where is not None
    if profile_meta.description(profile_meta.read(where)) == text.strip():
        return
    hermes_cli.cli(
        core.engine, workspace_id, "profile", "describe", f"{PREFIX}{name}", "--text", text.strip()
    )


def write(
    core: Core,
    workspace_id: str,
    name: str,
    *,
    title: str,
    summary: str,
    definition: dict[str, Any],
    local: str,
    on: bool | None = None,
    reports_before: str | None = None,
) -> None:
    """Writes who the member is into its (existing) profile. Safe to repeat.

    `reports_before`: the lead the caller read with `definition`. When this write
    doesn't change it, the lead in the profile NOW stays (another writer may have
    moved the member meanwhile: a write must never put back a lead it never
    changed). Every profile.yaml change runs under the profile's lock and starts
    from the file as it is then (Hermes's `profile describe` too: it rewrites the
    whole file)."""
    from agos_core.actions import agent_profiles

    where = home(core, workspace_id, name)
    assert core.engine is not None and where is not None
    profile_key = key(workspace_id, name)
    model = definition.get("model") if isinstance(definition.get("model"), dict) else None
    title = title.strip()[: profile_meta.TITLE_MAX] or lib.readable_title(name)
    reads = _reads(definition.get("reads"))
    wanted = lib.reports_to(definition.get("reports_to"))
    keep_lead = reports_before is not None and wanted == lib.reports_to(reports_before)
    boss = "" if keep_lead else checked_reports_to(core, workspace_id, name, wanted)
    with profile_meta.locked(where):
        if profile_meta.display_name(profile_meta.read_fresh(where)) != title:
            core.engine.set_display_name(where, title)  # Hermes's write_profile_meta
        facts = profile_meta.agos(profile_meta.read_fresh(where))
        lead = lib.reports_to(facts.get("reports_to")) if keep_lead else boss
        facts["reads"] = reads
        if model:
            facts["own_model"] = True
        else:
            facts.pop("own_model", None)
        if lead:
            facts["reports_to"] = lead
        else:
            facts.pop("reports_to", None)
        profile_meta.write(where, agos_facts=facts)
        # Hermes's `profile describe` reads and rewrites the whole profile.yaml: under
        # the same lock, so no reports_to written meanwhile is lost.
        _describe(core, workspace_id, name, summary.strip() or title)
    cfg = config_file.read(where)
    pairs = _model_pairs(core, workspace_id, model)
    skills = [lib.check_name(str(s)) for s in definition.get("skills") or []]
    if skills or config_file.get(cfg, "skills.auto_load") is not None:
        pairs["skills.auto_load"] = json.dumps(skills)
    _set(core, profile_key, cfg, pairs)
    agent_profiles.write_soul(
        core,
        workspace_id,
        name,
        title=title,
        instructions=str(definition.get("instructions") or ""),
        local=local,
        reads=reads,
    )
    if on is not None:
        park(core, workspace_id, name, not on)


# ---- the org chart: who reports to whom (profile.yaml ui_meta.agos.reports_to) ------


def _bosses(core: Core, workspace_id: str) -> dict[str, str]:
    """Each member's lead ("" = the Co-Founder), read from the profiles' metadata
    only (no SOUL, no config): cheap enough for a cycle check on every save."""
    out = {}
    for member in _profile_names(core, workspace_id):
        where = home(core, workspace_id, member)
        assert where is not None
        out[member] = lib.reports_to(profile_meta.agos(profile_meta.read(where)).get("reports_to"))
    return out


def checked_reports_to(core: Core, workspace_id: str, name: str, value: Any) -> str:
    """The lead a member may report to: "" (the Co-Founder), or a member of THIS
    workspace that is not itself and not (through others) one of its own reports.
    Raises ActionError otherwise, so a cycle is never written."""
    boss = lib.reports_to(value)
    if not boss:
        return ""
    if boss == name:
        raise ActionError("An agent can't report to itself.")
    bosses = _bosses(core, workspace_id)
    if boss not in bosses:
        raise ActionError(f"There is no agent named {boss} in this workspace to report to.", 404)
    seen = {name}
    walk = boss
    while walk:
        if walk in seen:
            raise ActionError(
                f"{boss} already reports to {name} (through the team): that would be a loop."
            )
        seen.add(walk)
        walk = bosses.get(walk, "")
    return boss


def set_reports_to(core: Core, workspace_id: str, name: str, value: Any) -> None:
    """The owner moves a member under another lead (or back under the Co-Founder).
    Compared and written against the profile as it is under its lock (never a read
    kept from before): a move is never skipped nor undone by a stale read. Its
    chain of command is in its SOUL.md and its reports' (they move with it)."""
    if get(core, workspace_id, name) is None:
        raise NotFoundError("This agent")
    from agos_core.actions import agent_revisions

    boss = checked_reports_to(core, workspace_id, name, value)
    agent_revisions.catch_up(core, workspace_id, name)
    if _write_reports_to(core, workspace_id, name, boss):
        _chains_changed(core, workspace_id)
        agent_revisions.record(core, workspace_id, name)


def _write_reports_to(core: Core, workspace_id: str, name: str, boss: str) -> bool:
    """False when the profile already said so."""
    where = home(core, workspace_id, name)
    assert where is not None
    with profile_meta.locked(where):
        facts = profile_meta.agos(profile_meta.read_fresh(where))
        if lib.reports_to(facts.get("reports_to")) == boss:
            return False
        if boss:
            facts["reports_to"] = boss
        else:
            facts.pop("reports_to", None)
        return profile_meta.write(where, agos_facts=facts)


def _chains_changed(core: Core, workspace_id: str) -> None:
    """Who reports to whom moved: every member's SOUL.md says its chain again."""
    from agos_core.actions import agent_profiles

    try:
        agent_profiles.write_texts(core, workspace_id)
    except Exception:
        log.exception("chains of command of %s not written into the prompts", workspace_id)


def reparent_reports(core: Core, workspace_id: str, gone: str) -> list[str]:
    """A member leaves: whoever reported to it reports to the Co-Founder now, and
    the owner finds a note about it in his Inbox."""
    moved = []
    for member, boss in _bosses(core, workspace_id).items():
        if boss == gone and member != gone:
            _write_reports_to(core, workspace_id, member, "")
            moved.append(member)
    if moved:
        from agos_core.actions import inbox

        inbox.note(
            core,
            workspace_id,
            "lead_removed",
            f"@{gone} left the team: {len(moved)} report"
            f"{'s' if len(moved) != 1 else ''} now report to the Co-Founder",
            "Moved under the Co-Founder: "
            + ", ".join(f"@{m}" for m in moved)
            + ". Pick a new lead for them in Hierarchy if one fits.",
        )
    return moved


def park(core: Core, workspace_id: str, name: str, value: bool) -> None:
    """Off (True) or on the team: Hermes's `hermes -p <member> gateway stop|start`.
    It writes or removes `gateway.parked` and asks the root's running gateway to
    unserve or serve the member now (multi-profile-gateways.md "Stopping one profile
    without stopping the host"). With the root's gateway down Hermes leaves the
    marker as it is (hermes_cli/gateway_profile_lifecycle.py: no host, no park), so
    the marker is set by hand, as that doc allows for provisioning; the gateway
    reads it when it starts."""
    where = home(core, workspace_id, name)
    assert core.engine is not None and where is not None
    if profile_meta.parked(where) == value:
        return
    if core.engine.is_running(workspace_id):
        try:
            said = hermes_cli.cli(
                core.engine, key(workspace_id, name), "gateway", "stop" if value else "start"
            )
            log.info("%s of %s: %s", name, workspace_id, " ".join(str(said or "").split())[:300])
        except EngineError as error:
            log.warning("%s of %s: Hermes's gateway %s: %s", name, workspace_id, value, error)
    if profile_meta.parked(where) != value:
        profile_meta.set_parked(where, value)
    from agos_core.actions import heartbeat

    heartbeat.follow_parked(core, workspace_id, name, value)  # its heartbeat job follows


def move_dm_titles(core: Core) -> int:
    """Once: a DM's name AGOS kept (a copy of its member's job title) goes; the
    member's Hermes display name is the one name (db/chats.py dm_title). A name
    the profile lacks is written into it first (Hermes's write_profile_meta); a
    DM whose member profile is gone keeps its name. Safe to repeat."""
    rows = chats_repo.titled_dms(core.db)
    moved = 0
    for row in rows:
        workspace_id, agent, title = str(row["workspace_id"]), row["agent"], str(row["title"])
        if agent:
            where = home(core, workspace_id, str(agent)) if lib.NAME.fullmatch(agent) else None
            if where is None or not (where / "config.yaml").is_file():
                continue  # no profile to hold it: the DM keeps its name
            try:
                with profile_meta.locked(where):
                    if not profile_meta.display_name(profile_meta.read(where)):
                        assert core.engine is not None
                        core.engine.set_display_name(where, title[: profile_meta.TITLE_MAX])
            except (EngineError, OSError) as error:
                log.warning("DM name of %s in %s not moved: %s", agent, workspace_id, error)
                continue
        chats_repo.drop_title_copy(core.db, int(row["id"]), title)
        moved += 1
    return moved


def _gist(definition: dict[str, Any]) -> tuple[Any, ...]:
    """What makes two versions of an agent's definition the same."""
    model = definition.get("model") if isinstance(definition.get("model"), dict) else None
    return (
        str(definition.get("instructions") or "").strip(),
        *((model or {}).get(k) for k in ("provider", "model", "effort")),
        list(definition.get("skills") or []),
        _reads(definition.get("reads")),
        lib.reports_to(definition.get("reports_to")),
    )


def _root_or_raise(core: Core, workspace_id: str) -> None:
    from agos_core.actions import hermes_config as hc

    if core.engine is None:
        raise ActionError("The engine is off.", 409)
    if not hc.has_root(core, workspace_id):
        raise ActionError(NOT_SET_UP, 409)


def save(
    core: Core,
    workspace_id: str,
    name: str,
    *,
    title: str,
    summary: str,
    definition: dict[str, Any],
    new: bool,
    local: str | None = None,
    record_revision: bool = True,
) -> int:
    """Creates (`new`) or changes a member: its profile is the one place it lives.
    Returns its id. The change is a revision of the member (actions/agent_revisions)."""
    from agos_core.actions import docs

    try:
        lib.check_name(name)
        clean = lib.check_agent(definition)
    except lib.LibraryError as error:
        raise ActionError(str(error)) from error
    if len(title.strip()) > profile_meta.TITLE_MAX:
        raise ActionError(f"Keep the name to {profile_meta.TITLE_MAX} characters (the limit).")
    _root_or_raise(core, workspace_id)
    assert core.engine is not None
    current = get(core, workspace_id, name)
    if new and current is not None:
        raise ActionError(f"There is already a agent named {name} in this workspace.", 409)
    if not new and current is None:
        raise NotFoundError("This agent")
    if current is not None and record_revision:
        from agos_core.actions import agent_revisions

        agent_revisions.catch_up(core, workspace_id, name)
    if current is not None and (
        current.title != title.strip()
        or current.summary != summary.strip()
        or _gist(current.definition) != _gist(clean)
        or (local is not None and current.local != local.strip())
    ):
        docs.keep_agent_version(core, current, "changed")
    try:
        if current is None:
            core.engine.ensure_profile(key(workspace_id, name))  # `hermes profile create`
        write(
            core,
            workspace_id,
            name,
            title=title,
            summary=summary,
            definition=clean,
            local=current.local if local is None and current is not None else (local or ""),
            on=True if current is None else None,
            reports_before=current.reports_to if current is not None else None,
        )
    except (EngineError, OSError) as error:
        raise ActionError(f"Not saved: its profile wasn't written: {error}", 503) from error
    agent = get(core, workspace_id, name)
    if agent is None:
        raise ActionError("Not saved: its profile isn't there.", 503)
    if current is not None and current.skills != agent.skills:
        from agos_core.actions import automations

        try:  # its jobs load its skills now (keep_in_step tries again otherwise)
            automations.sync_agent_jobs(core, workspace_id, name)
        except Exception:
            log.exception("automations of %s in %s not given its skills", name, workspace_id)
    if record_revision:
        from agos_core.actions import agent_revisions

        agent_revisions.record(core, workspace_id, name)
    return agent.id


def set_on(core: Core, workspace_id: str, name: str, *, on: bool, local: str) -> None:
    """On or off the team (Hermes's parked marker) and the owner's notes for it."""
    from agos_core.actions import agent_revisions

    agent = get(core, workspace_id, name)
    if agent is None:
        raise NotFoundError("This agent")
    agent_revisions.catch_up(core, workspace_id, name)
    try:
        if local.strip() != agent.local:
            write(
                core,
                workspace_id,
                name,
                title=agent.title,
                summary=agent.summary,
                definition=agent.definition,
                local=local.strip(),
                reports_before=agent.reports_to,
            )
        park(core, workspace_id, name, not on)
    except (EngineError, OSError) as error:
        raise ActionError(f"Not saved: its profile wasn't written: {error}", 503) from error
    agent_revisions.record(core, workspace_id, name)


def delete(core: Core, workspace_id: str, name: str) -> None:
    """Gone from the team: its profile goes (Hermes's `profile delete`); AGOS keeps
    its last text in the agent's history."""
    from agos_core.actions import agent_profiles, automations, docs

    agent = get(core, workspace_id, name)
    if agent is None:
        raise NotFoundError("This agent")
    docs.keep_agent_version(core, agent, "deleted")
    try:
        reparent_reports(core, workspace_id, name)  # its reports go to the Co-Founder
    except (OSError, EngineError):
        log.exception("reports of %s in %s not moved to the Co-Founder", name, workspace_id)
    where = home(core, workspace_id, name)
    if where is not None:
        # Off the team first, so its automations' jobs leave its cron for the
        # Co-Founder's before its profile (and that cron) goes.
        with contextlib.suppress(OSError, EngineError):
            park(core, workspace_id, name, True)
        try:
            automations.hand_over(core, workspace_id, name)
        except Exception:
            log.exception("automations of %s in %s not handed over", name, workspace_id)
    agent_profiles.remove(core, workspace_id, name)
    if name in _profile_names(core, workspace_id):
        raise ActionError("Not deleted: the engine kept its profile.", 503)
    library_repo.delete_item(core.db, agent.id)
    from agos_core.actions import goals

    goals.member_left(core, workspace_id, name)  # its sub-goals have no owner now
    _chains_changed(core, workspace_id)
