"""The Co-Founder can do anything the owner does in AGOS (owner rule 2026-10-28):
the rest of the owner's pages as agos_action kinds (pure rules).

Each kind below is one more `do` of the Co-Founder's agos_action tool (no new tool
schema: every new kind rides on the tool and the Undo / approval cards it already
has). It runs the same AGOS action code as the owner's page
(actions/cofounder_more.py). Its fields are written in AGOS's hidden skill
`cofounder-actions` (`skill_text`), which the Co-Founder opens with skill_view when
it needs them; the always-on prompt only names each domain in one line (`DOMAINS`).

The kinds live by domain in cofounder_parity/<domain>.py, merged by catalog.py;
the web-action map is web_actions.py, the hidden skill skill.py. This module only
re-exports them (callers keep `from agos_core.engine import cofounder_parity`).

`DO`, `READS` and `OWNER_ONLY` (engine/cofounder_owner_only.py) map every server
action of the web app (apps/web/src/features/**/(actions|*-actions).ts) to the
Co-Founder's way of doing it, a read, or an owner-only exception with its reason;
tests/test_cofounder_parity.py fails on a web action these tables don't know.
"""

from __future__ import annotations

from agos_core.engine.cofounder_kind import AUTOMATIONS as AUTOMATIONS
from agos_core.engine.cofounder_kind import BOARD as BOARD
from agos_core.engine.cofounder_kind import SKILLS as SKILLS
from agos_core.engine.cofounder_kind import TEAM as TEAM
from agos_core.engine.cofounder_kind import WORKSPACE as WORKSPACE
from agos_core.engine.cofounder_kind import Gate as Gate
from agos_core.engine.cofounder_kind import Kind as Kind
from agos_core.engine.cofounder_owner_only import OWNER_ONLY as OWNER_ONLY
from agos_core.engine.cofounder_parity.actions_skill import skill_text as skill_text
from agos_core.engine.cofounder_parity.catalog import DOMAINS as DOMAINS
from agos_core.engine.cofounder_parity.catalog import KINDS as KINDS
from agos_core.engine.cofounder_parity.catalog import STRUCTURED as STRUCTURED
from agos_core.engine.cofounder_parity.catalog import owner_first as owner_first
from agos_core.engine.cofounder_parity.catalog import title as title
from agos_core.engine.cofounder_parity.web_actions import DO as DO
from agos_core.engine.cofounder_parity.web_actions import READS as READS
