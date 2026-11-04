"""Settings → Export / Import (Step 56, F90): a workspace as a readable bundle.

Export reads each piece where it lives (the members' Hermes profiles, the
workspace's skill folder, Hermes's cron jobs through AGOS's automations, AGOS's
Vision rows and review defaults) and writes engine/bundle.py's tree. No secret
leaves: only named fields are read (never a .env, auth.json or config secret: the
files Hermes's own `hermes profile export` drops, hermes_cli/profiles.py
_EXPORT_CREDENTIAL_FILES), every key value AGOS can see in the workspace's Hermes
homes becomes `${NAME}` in any text that holds it, and Hermes's own masking
(agent/redact.py redact_sensitive_text, engine/hermes_redact.py) runs over every
file. The keys the workspace uses become `env_requires` inputs (Hermes's profile
distribution shape); a Telegram bot token is never one.

Import goes through the normal AGOS paths, so Hermes gets everything the way it
always does: skills = the workspace's skill create/save (Hermes's skill_manage),
members = the team's save (`hermes profile create`, SOUL.md, profile.yaml, config),
automations = the automations' save (Hermes cron / webhook routes), the Vision =
the Vision page's writers, keys = Workspace → Keys (Hermes's save_env_value).
Into a new workspace or an existing one, with a collision strategy per kind
(skip / rename / replace), the inputs the owner fills (a required one he didn't
fill and didn't put off stops the import before anything is written), and a
fidelity report: what came in, as what, and what still needs the owner.

This module is a compatibility facade: the code lives in actions/services/portability/ and
is re-exported here so every import path and patch target keeps working.
"""

from __future__ import annotations

# isort: off
from agos_core.actions.services.portability.export import (
    log as log,
    TELEGRAM as TELEGRAM,
    SHORTEST_SECRET as SHORTEST_SECRET,
    _skills as _skills,
    scrub as scrub,
    export_files as export_files,
    _extra as _extra,
    export_zip as export_zip,
)
from agos_core.actions.services.portability.preview import (
    KINDS as KINDS,
    DEFAULTS as DEFAULTS,
    SCRIPTS as SCRIPTS,
    read_zip as read_zip,
    parsed as parsed,
    trust as trust,
    preview as preview,
)
from agos_core.actions.services.portability.importing import (
    apply as apply,
)
from agos_core.actions.services.portability.import_report import (
    Report as Report,
    Plan as Plan,
    check_inputs as check_inputs,
    _said as _said,
)
from agos_core.actions.services.portability.import_steps import import_keys as import_keys
# isort: on
