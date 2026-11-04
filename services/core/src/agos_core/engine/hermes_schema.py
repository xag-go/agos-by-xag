"""Hermes's own list of its settings (Settings → Hermes settings), read from Hermes.

AGOS keeps no copy of the list. Hermes's dashboard builds its Config page from
`DEFAULT_CONFIG` (hermes_cli/config_defaults.py) through
`hermes_cli/web_server_config.py _schema_with_dynamic_provider_options` (the code
behind `GET /api/config/schema`; `GET /api/config/defaults` returns `DEFAULT_CONFIG`
itself). AGOS runs those same functions in Hermes's runtime (`_SCHEMA`, one small
process, kept in memory while Hermes's file is unchanged) and takes:

- every field of the schema: its key, type, select options, and description;
- the defaults (`DEFAULT_CONFIG`), including the sections whose default is an empty
  mapping (`providers`, `credential_pool_strategies`, ...), which the dashboard's
  walk skips but which are settings too;
- the comments above each key in `config_defaults.py` ("Comments are the
  user-facing docs of config.yaml", that file's own docstring): Hermes's plain
  description of the key, used where the schema has only the key's name.

A key added by a Hermes upgrade shows on the page with no change in AGOS: the
groups are chosen by the key's section (`GROUP_BY_PREFIX`, longest prefix wins),
and a key in a section AGOS doesn't know falls in "Runtime".

This module is a compatibility facade: the code lives in engine/settings_schema/ and is
re-exported here so every import path and patch target keeps working.
"""

from __future__ import annotations

# isort: off
from agos_core.engine.settings_schema.groups import (
    SAFETY as SAFETY,
    COST as COST,
    MEMORY as MEMORY,
    KANBAN as KANBAN,
    CHATS as CHATS,
    RUNTIME as RUNTIME,
    ENV as ENV,
    NOT_USED as NOT_USED,
    GROUPS as GROUPS,
    GROUP_BY_PREFIX as GROUP_BY_PREFIX,
    NOT_USED_WHY as NOT_USED_WHY,
    group_of as group_of,
)
from agos_core.engine.settings_schema.fields import (
    Field as Field,
    leaves as leaves,
    _title as _title,
    comments as comments,
    build as build,
    unlisted as unlisted,
)
from agos_core.engine.settings_schema.env import (
    EnvVar as EnvVar,
    env_vars as env_vars,
    unlisted_env as unlisted_env,
)
from agos_core.engine.settings_schema.extras import (
    EXTRA_PLATFORM as EXTRA_PLATFORM,
    EXTRA_PREFIX as EXTRA_PREFIX,
    ExtraKey as ExtraKey,
    platform_extras as platform_extras,
    extra_fields as extra_fields,
    hermes_root as hermes_root,
)
from agos_core.engine.settings_schema.secrets import (
    MASK as MASK,
    Path_ as Path_,
    secret_paths as secret_paths,
    masked as masked,
    holds_secret as holds_secret,
)
from agos_core.engine.settings_schema.read_cache import (
    env_registry as env_registry,
    keep_env as keep_env,
    source_path as source_path,
    SCRIPT as SCRIPT,
    _cache as _cache,
    _lock as _lock,
    parse as parse,
    cached as cached,
    keep as keep,
    kanban_workflow as kanban_workflow,
    kanban_auto_cap as kanban_auto_cap,
    image_modes as image_modes,
    forget as forget,
)
# isort: on
