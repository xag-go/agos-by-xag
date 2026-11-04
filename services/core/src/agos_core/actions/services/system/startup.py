"""What the core does once at start and at shutdown, around the web app.

Moved out of api/app.py (it keeps only the HTTP wiring). Owns: the one-time moves of
old AGOS data into Hermes, the sync of every sandbox and the hand-over of each
workspace's gateway to Hermes's own service, the read-ahead of what the first pages
need from Hermes, the background loops, and stopping the reads at shutdown.

Each step that fails is logged and the start goes on (a failed sandbox sync keeps
that workspace stopped: fail closed). Order matters and is kept as it was.

Must not: answer HTTP, or hold the start on a slow Hermes call (the background
start runs them after the app is up).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from pathlib import Path
from types import ModuleType
from typing import Any

from agos_core.actions import (
    account_pause,
    chat,
    chat_store,
    cofounder_move,
    digest,
    hermes_channel,
    hermes_errors,
    hermes_fallback,
    hermes_managed,
    kanban_board,
    key_pools,
    member_profiles_gone,
    member_topics,
    memory_plugin,
    ops_watch,
    outbox_push,
    skill_requests,
    skills_move,
    staging,
    team_design,
    tool_search,
    tool_services,
)
from agos_core.actions import automations as automations_loop
from agos_core.actions import backups as backups_loop
from agos_core.actions import channels as channels_loop
from agos_core.actions import cofounder_actions as cofounder_actions_once
from agos_core.actions import engine as engine_actions
from agos_core.actions import hooks as hooks_actions
from agos_core.actions import idle as idle_loop
from agos_core.actions import library as library_actions
from agos_core.actions import rooms as rooms_actions
from agos_core.actions import team as team_actions
from agos_core.actions import workspaces as workspaces_actions
from agos_core.actions.engine import resync_all, write_all_identities
from agos_core.background import schedule as background_jobs
from agos_core.context import stop_reading_hermes
from agos_core.db import orphan_keys, ownership
from agos_core.engine import library as library_engine
from agos_core.engine import read_ahead
from agos_core.engine.skill_frontmatter import HermesFrontmatter
from agos_core.jobs import runner as jobs_loop
from agos_core.outbox import delivery as outbox_loop
from agos_core.storage.layout import remove_unused_folders

__all__ = [
    "loop_ended",
    "loops",
    "once_at_start",
    "serve_then_read_ahead",
    "stop_reads",
    "sync_then_serve",
]

log = logging.getLogger("agos")

# (the module, its function that runs with the core, the log line if it fails). The
# function is looked up when it runs: a test's patch on the module is seen.
Step = tuple[ModuleType, str, str]

# The one-time moves of what AGOS kept itself into Hermes's own places, in order.
_MOVES: tuple[Step, ...] = (
    (hermes_fallback, "move_old_setting", "old fallback setting not moved into Hermes"),
    (tool_services, "move_old_setting", "old tool services setting not moved into Hermes"),
    # A chat's model AGOS kept (chats.model, the whole /model told): into Hermes's own
    # /model for the conversation, once; only the effort stays.
    (hermes_channel, "move_old_models", "old chat models not moved into Hermes"),
    # Groups' names AGOS kept while their Hermes room existed: the room's.
    (rooms_actions, "move_old_names", "old group names not moved into their Hermes rooms"),
    # Turns still open from before everything ran on Hermes: closed, once.
    (chat, "close_pre_hermes", "old open turns not closed"),
    # Chats AGOS hid itself: Hermes's own per-session archive, once.
    (chat_store, "move_hidden", "hidden chats not moved into Hermes"),
)
_RENAMES: tuple[Step, ...] = (
    # Workspace names AGOS kept: the Co-Founders' Hermes display names, once.
    (engine_actions, "move_names", "workspace names not moved into Hermes"),
    # DM names AGOS copied from its members: the members' Hermes names, once.
    (team_actions, "move_dm_titles", "DM names not moved into Hermes"),
    # Old Co-Founder cards' copies of Hermes data (skills, roles, cron jobs), once.
    (cofounder_actions_once, "move_snapshots", "old Co-Founder cards' copies not moved"),
    (hooks_actions, "move_names", "webhook automations' names not left to their Hermes routes"),
    (kanban_board, "move_card_chat_titles", "card chat names not moved to their Hermes cards"),
    # The pre-Step-33 account pause (an emptied dispatch list, jobs held with
    # PAUSE_REASON) put back once: Hermes's own pause runs it now.
    (account_pause, "move_old_pause", "legacy account pause not moved to Hermes's own pause"),
    # Old group-name notes into each root's channel_aliases.json, at start (it used
    # to wait for the Channels page to be opened).
    (hermes_channel, "move_group_names", "old group names not moved into their Hermes roots"),
)
_OLD_DATA: tuple[Step, ...] = (
    # The old shared skill library: each workspace's own skills now, once.
    (skills_move, "move_old_shared_skills", "old shared skills not moved into their workspaces"),
    # The Manager is the Co-Founder (step 44): the roots' files, once.
    (cofounder_move, "move_old_manager_name", "the Manager's name not renamed in the roots' files"),
    # hooks.output_spill.max_chars AGOS used to force: Hermes's default, once.
    (library_actions, "move_spill_cap", "hooks.output_spill.max_chars not given back to Hermes"),
    # A bot AGOS had turned off itself: Hermes's own switch, once.
    (hermes_channel, "move_old_switches", "old bot switches not moved into Hermes"),
    # The profiles of the people workspaces were once shared with: gone, once.
    (member_profiles_gone, "remove_all", "old member profiles not deleted"),
)
# After the gateways were handed to Hermes's service, in order.
_AFTER_HAND_OVER: tuple[Step, ...] = (
    # Gateways (re)started just now read Hermes's managed scope: their profiles' old
    # copies of its keys go (actions/hermes_managed.py).
    (hermes_managed, "settle", "Hermes's managed settings' copies not settled"),
    # Extra provider keys AGOS once added to every home: into the managed .env, then
    # out of the homes whose gateway reads it (actions/key_pools.py).
    (key_pools, "move_once", "old extra provider keys not moved into Hermes's managed .env"),
)
# Last, once member topics are routed: skills every workspace gets once.
_SKILLS: tuple[Step, ...] = (
    # The Co-Founder's team-design skill, once per workspace (actions/team_design.py).
    (team_design, "ensure_all", "team-design skill not installed"),
    # Every agent's find-skills skill, once per workspace (actions/skill_requests.py).
    (skill_requests, "ensure_all", "find-skills skill not installed"),
)


async def _run(core: Any, steps: tuple[Step, ...]) -> None:
    for module, name, failed in steps:
        try:
            await asyncio.to_thread(getattr(module, name), core)
        except Exception:
            log.exception(failed)


def loop_ended(task: asyncio.Task[None]) -> None:
    """A background loop that stopped by itself (not at shutdown) is an error."""
    if task.cancelled():
        return
    code = getattr(task.get_coro(), "cr_code", None)
    name = f"{Path(code.co_filename).stem}.{code.co_name}" if code else task.get_name()
    error = task.exception()
    if error is not None:
        log.error("background loop %s stopped", name, exc_info=error)
    else:
        log.error("background loop %s stopped", name)


async def _before_hand_over(core: Any) -> None:
    """Settings keys no code registers are told; Hermes's managed scope settled (the
    hook guard's one move first, live too); a staging copy's cron jobs paused before
    any gateway (and its ticker) runs."""
    stray = ownership.unregistered(core.db)
    if stray:
        log.warning("app_settings keys no code registers (db/ownership.py KEYS): %s", stray)
    await _run(
        core,
        (
            (hermes_managed, "move_hook_guard", "plugins.hook_callback_timeout not moved"),
            (hermes_managed, "move_once", "Hermes's managed settings not checked"),
            (staging, "quiet", "staging: cron jobs not paused"),
        ),
    )


async def sync_then_serve(core: Any) -> None:
    """Every sandbox in line with AGOS's rules, then one pass that makes each
    workspace's gateway Hermes's own service (it keeps them up from there).
    First the one-time move into Hermes's managed scope (settled after the hand-over)."""
    await _before_hand_over(core)
    # A create whose setup Hermes refused then (its saga needs attention) is finished.
    await resync_all(core, finish=workspaces_actions.finish_setup)
    try:
        started = await asyncio.to_thread(idle_loop.ensure_all, core)
    except Exception:
        log.exception("gateways not handed to Hermes's service")
        return
    if started:
        log.info("gateways started as Hermes's service: %s", ", ".join(started))
    await _run(core, _AFTER_HAND_OVER)
    # Member topics are Hermes's routed conversations (the live move from AGOS's
    # relay; safe to repeat): the root's routes, then each topic's earlier talk.
    try:
        changed = await asyncio.to_thread(member_topics.sync_all, core)
    except Exception:
        log.exception("member topics not routed by Hermes")
        return
    if changed:
        log.info("member topics routed by Hermes: %d workspace(s)", changed)
    await _run(core, _SKILLS)


async def serve_then_read_ahead(core: Any) -> None:
    """What the owner's first pages after a restart need from Hermes is asked at
    once, beside the start's sync (engine/read_ahead.py AT_START); the sync and
    gateway hand-over, then everything else pages need from Hermes, asked once in
    the background (WARMERS), so the first page after a restart doesn't wait for
    Hermes to start."""
    first = asyncio.create_task(asyncio.to_thread(read_ahead.run, core, read_ahead.AT_START))
    try:
        await sync_then_serve(core)
        await first
    except asyncio.CancelledError:
        first.cancel()
        raise
    await asyncio.to_thread(read_ahead.run, core)


async def _hermes_first(core: Any) -> None:
    """What every page reads the way Hermes does, before anything else."""
    # A SKILL.md is read the way Hermes reads it (its own parse_frontmatter).
    library_engine.use_hermes_reader(HermesFrontmatter(core.engine.settings))
    # MCP servers a workspace added itself: in Settings' shared list too.
    try:
        await asyncio.to_thread(library_actions.share_servers, core)
    except Exception:
        log.exception("workspace MCP servers not shared")
    # Hermes's tools: its own list (anything new appears and is on).
    with contextlib.suppress(Exception):
        await asyncio.to_thread(library_actions.refresh_tools, core)
    # Existing workspaces get (or refresh) their SOUL.md from AGOS's data.
    written = await asyncio.to_thread(write_all_identities, core)
    log.info("identities checked: %d workspace(s)", written)
    await _run(
        core,
        (
            # The chats' Hermes sessions are pinned: one pass for what happened while
            # AGOS was down (after that, Hermes's on_session_end says when).
            (chat_store, "tick", "chat sessions not kept"),
            # The Daily digest's clock: a Hermes cron job in each root that needs one.
            (digest, "keep_all", "digest jobs not checked"),
            # Hermes's Tool Search for the Co-Founder's tools (the owner's one switch;
            # nothing to do while it is Hermes's own behaviour).
            (tool_search, "keep_all", "tool search setting not checked"),
        ),
    )


async def once_at_start(core: Any, *, background: bool) -> list[asyncio.Task[None]]:
    """The start's one-time work with an engine; the background start's task (the
    sandbox sync, the gateways' hand-over, the read-ahead) when `background`."""
    if core.engine is None:
        return []
    await _hermes_first(core)
    if not background:
        # The settings that are one value for every workspace: Hermes's managed scope
        # (moved in once from the profiles' copies, then the copies go).
        await _run(
            core,
            (
                (hermes_managed, "at_start", "Hermes's managed settings not checked"),
                (
                    key_pools,
                    "move_once",
                    "old extra provider keys not moved into Hermes's managed .env",
                ),
            ),
        )
    # With the loops on (live), the move runs in the background before the gateways
    # are handed over (sync_then_serve): its Hermes calls (one per key, the first
    # time) never hold AGOS's start, so the app is up at once.
    await _run(core, _MOVES)
    # The empty memory/ and connectors/ folders AGOS made and never used: once.
    try:
        gone = await asyncio.to_thread(remove_unused_folders, core.layout)
        if gone:
            log.info("unused empty folders removed: %d", len(gone))
    except Exception:
        log.exception("unused folders not removed")
    await _run(core, _RENAMES)
    # Settings keys of workspaces/chats that no longer exist: into the backups folder
    # (old purges left them; purge takes them along now).
    try:
        await asyncio.to_thread(orphan_keys.sweep, core.db, core.layout.root)
    except Exception:
        log.exception("settings keys of gone workspaces not moved out")
    await _run(core, _OLD_DATA)
    if not background:
        return []
    # A Holographic install whose tries all failed: again, unwalled (Hermes's own
    # recovery runs behind the gateway's wall and can't).
    await _run(core, ((memory_plugin, "recover", "Holographic memory not tried again"),))
    # Sandboxes match AGOS's rules (network isolation, folders) after an upgrade; a
    # workspace that can't be synced stays stopped (fail closed).
    return [asyncio.create_task(serve_then_read_ahead(core))]


def _every_copys_loops(core: Any) -> list[asyncio.Task[None]]:
    """The loops a staging copy runs too: the outbox (notifications after their
    change committed), the job queue (AGOS's own chores: idle round, trash,
    retention), backups, the ops watch, Hermes's errors."""
    outbox_push.register()
    background_jobs.register()
    every = (outbox_loop.run_forever, jobs_loop.run_forever)
    return [asyncio.create_task(loop(core)) for loop in every] + [
        asyncio.create_task(loop(core))
        for loop in (backups_loop.run_forever, ops_watch.run_forever, hermes_errors.run_forever)
    ]


def loops(core: Any, *, background: bool) -> list[asyncio.Task[None]]:
    """The background loops (none for a test app): each one that stops by itself is
    logged as an error."""
    if not background:
        return []
    tasks: list[asyncio.Task[None]] = []
    if core.engine is not None and not staging.on():  # no automation or channel loop
        tasks.append(asyncio.create_task(automations_loop.run_forever(core)))
        tasks.append(asyncio.create_task(channels_loop.run_forever(core)))
        tasks.append(asyncio.create_task(channels_loop.upkeep_forever(core)))
    tasks += _every_copys_loops(core)
    for task in tasks:
        task.add_done_callback(loop_ended)
    return tasks


def stop_reads() -> None:
    """At shutdown: no more reads of Hermes's stores, SKILL.md read AGOS's way again."""
    stop_reading_hermes()
    library_engine.use_hermes_reader(None)
