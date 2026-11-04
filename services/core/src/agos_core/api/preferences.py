"""Settings' routes (account-wide preferences and every workspace's Hermes settings),
one router per Settings area, wired here in the order they are served:

- settings_account.py      General and Notifications: AGOS's own account preferences
- settings_hermes_limits.py Limits: Hermes's loop detector, time limit and timeouts
- settings_hermes_models.py Models: helper models, fallback chain, voice
- settings_hermes_all.py   Hermes: every Hermes setting, the Co-Founder's Tool Search
- settings_health.py       Health: Hermes's status/doctor, the secrets check
- settings_facts.py        the core's own limits the web reads

This module is a compatibility facade: `router` is what api/app.py includes, and
the names below are re-exported so every import path keeps working.

Must not: hold a route or a rule (each lives in its area's router or action).
"""

from fastapi import APIRouter

# isort: off
from agos_core.api import (
    settings_account,
    settings_hermes_limits,
    settings_hermes_models,
    settings_hermes_all,
    settings_health,
    settings_facts,
)
from agos_core.actions.services.settings.account_prefs import TABS as TABS
from agos_core.actions.services.settings.account_prefs import tabs_order as tabs_order
from agos_core.actions.services.settings.model_routes import fallback_chain as fallback_chain
from agos_core.api.settings_account import UsagePrefs as UsagePrefs
from agos_core.api.settings_account import usage_prefs as usage_prefs
# isort: on

router = APIRouter(tags=["preferences"])
for _part in (
    settings_account,
    settings_hermes_limits,
    settings_hermes_models,
    settings_hermes_all,
    settings_health,
    settings_facts,
):
    router.include_router(_part.router)
