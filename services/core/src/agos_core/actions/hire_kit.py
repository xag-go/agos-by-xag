"""A hire's kit, its Readiness and its onboarding test (Step 62).

Every member gets what it needs to do its work well. A hire proposal (the
Co-Founder's hire_agent / agos_propose kind hire) carries a kit (engine/hire_kit.py
says its shape); the owner edits it before Approve. On approve AGOS provisions
what it can through the normal paths, then shows a Readiness checklist until the
member is ready:

- the kit itself is the member's Hermes profile fact (profile.yaml `ui_meta.agos.kit`,
  Hermes's place for an app's facts about a profile, engine/profile_meta.py);
- library skills go into the member through the team's own code (its
  `skills.auto_load`), docs and examples are copied into its folder in the
  workspace's files (team/<member>/docs|examples), and its SOUL.md gets ONE marked
  'Your team' section (rewritten with every SOUL write) plus one memory entry;
- each item's state is DERIVED from real checks each time it is read: the model
  Hermes runs it on, its Telegram topic, its lead on the team, each skill in its
  profile and the library, each connector on in the workspace's Hermes, each key
  name in its root's Keys (and its .env line), each file in its folder. AGOS keeps
  only the owner's own choices ('Start anyway', 'Not needed', 'Skip test') and the
  onboarding grades (member_readiness rows);
- what is missing goes on ONE Hermes card for the Co-Founder ('Make @x ready',
  idempotency key agos-ready:<member>:<digest of what is missing>), which finds a
  route for each item; its routes are read back from that card's result;
- once every item is there, the member does its onboarding test (a Hermes card,
  key agos-onboard:<member>:<n>), graded by Skill Studio's grader (`hermes
  agos-grade`); a failure gets a fix card for the Co-Founder and a re-run (at most
  MAX_TRIES tries, then the owner decides in his Inbox);
- while it is not ready the member is held from work: Hermes's dispatcher doesn't
  start its cards (it is left out of the root's kanban.dispatch_profiles) and its
  heartbeat can't be turned on. Members without a kit are never held.

This module is a compatibility facade: the code lives in actions/services/hire/ and
is re-exported here so every import path and patch target keeps working.
"""

from __future__ import annotations

# isort: off
from agos_core.actions.services.hire.kit_store import (
    log as log,
    KIT_FACT as KIT_FACT,
    READY_KEY as READY_KEY,
    ONBOARD_KEY as ONBOARD_KEY,
    FIX_KEY as FIX_KEY,
    OWNER_CHOICES as OWNER_CHOICES,
    CHOICE_WORDS as CHOICE_WORDS,
    _pending as _pending,
    _home as _home,
    kit_of as kit_of,
    _store as _store,
    expect as expect,
    forget_pending as forget_pending,
    kit_members as kit_members,
)
from agos_core.actions.services.hire.kit_rules import (
    _catalog as _catalog,
    fill as fill,
    kit_problems as kit_problems,
    required_problems as required_problems,
    library_skills as library_skills,
    team_section as team_section,
)
from agos_core.actions.services.hire.kit_files import (
    _files as _files,
    copy_docs as copy_docs,
    MEMORY_MARK as MEMORY_MARK,
    _remember as _remember,
    sync_dispatch as sync_dispatch,
)
from agos_core.actions.services.hire.readiness import (
    kit_state as kit_state,
    _connected as _connected,
    _keys as _keys,
    _cards as _cards,
    readiness as readiness,
    state_of as state_of,
    held as held,
    held_names as held_names,
    busy_only_onboarding as busy_only_onboarding,
)
from agos_core.actions.services.hire.onboarding import (
    choose as choose,
    _lock as _lock,
    advance as advance,
    _grade as _grade,
    sweep as sweep,
)
from agos_core.actions.services.hire.kit_lifecycle import (
    provision as provision,
    save_kit as save_kit,
    drop_kit as drop_kit,
    inbox_items as inbox_items,
)
# isort: on
