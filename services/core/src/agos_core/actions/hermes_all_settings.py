"""Settings → Hermes settings: every Hermes setting, in Hermes's own words, as each
workspace's Hermes has it, and changed with Hermes's own `hermes config set`.

AGOS keeps no copy of the settings and no list of them: the list is Hermes's
(engine/hermes_schema.py, the dashboard's schema and defaults read in Hermes's
runtime); the values are read back from the files Hermes wrote (each profile's
config.yaml, with Hermes's managed scope on top: actions/hermes_managed.py); a change is written with `hermes config set --force <key> <value>`
into every root and member (or one workspace's), only where it differs.

Each setting carries what AGOS does with it:

- `forced`: AGOS writes it on every sync of the workspace (engine/rules.py
  `profile_config`, actions/library.py `profile_settings`, actions/agent_profiles.py
  `kanban_pairs`, actions/access.py), so a change here would be undone. Shown
  read-only with the reason (`FORCED_WHY`).
- `card`: an AGOS card already shows and changes it (with its own rules: the
  members follow the Co-Founder, a fallback chain keeps its keys...). Shown read-only
  with a link to that card.
- `seeded`: a new profile starts on AGOS's value (engine/rules.py `seeded_config`);
  afterwards it is the owner's and can be changed here.
- a secret (an API key inside a setting) is never sent to the web.

Settings a workspace's Hermes has that Hermes's defaults don't list (set by hand,
or a newer key) are shown too, so nothing set in Hermes is invisible.

This module is a compatibility facade: the code lives in actions/services/settings/
(hermes_*.py) and is re-exported here so every import path and patch target keeps working.
"""

from __future__ import annotations

# isort: off
from agos_core.actions.services.settings.hermes_targets import (
    log as log,
    Target as Target,
    targets as targets,
    _uncovered as _uncovered,
    _norm as _norm,
)
from agos_core.actions.services.settings.hermes_policy import (
    FORCED_WHY as FORCED_WHY,
    LOCKED_WHY as LOCKED_WHY,
    locked_keys as locked_keys,
    FORCED_ENV_WHY as FORCED_ENV_WHY,
    forced_env as forced_env,
    locked_env as locked_env,
    CARD_LABELS as CARD_LABELS,
    card_keys as card_keys,
    forced_keys as forced_keys,
    choice_keys as choice_keys,
    recommended as recommended,
    _rule as _rule,
)
from agos_core.actions.services.settings.hermes_rows import (
    SHARED_WHY as SHARED_WHY,
    shared_rows as shared_rows,
    _env_rows as _env_rows,
    _row as _row,
)
from agos_core.actions.services.settings.hermes_reads import (
    read as read,
    _read_once as _read_once,
    warm_after_write as warm_after_write,
    _read as _read,
    read_ahead as read_ahead,
)
from agos_core.actions.services.settings.hermes_writes import (
    as_argument as as_argument,
    write as write,
    restore as restore,
    _parsed as _parsed,
    give_new_profile as give_new_profile,
)
# isort: on
