"""Hermes's .env variables as settings: its registry of them, the platforms AGOS uses, the ones it doesn't list.
Must not: cache anything (the read cache does).

Split out of agos_core.engine.hermes_schema (which re-exports it); behaviour unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agos_core.engine.settings_schema.groups import ENV, NOT_USED

__all__ = [
    "EnvVar",
    "env_vars",
    "unlisted_env",
]

# --- the .env settings (Hermes's own registry) ----------------------------------

# The chat platforms AGOS runs Hermes's gateway with (its Telegram bot, its own
# "agos" platform, the API server AGOS talks to, the webhook platform): a messaging
# variable of any other platform (Hermes's category "messaging") is "Not used".
_USED_PLATFORMS = ("TELEGRAM_", "GATEWAY_", "API_SERVER_", "WEBHOOK_", "AGOS_PLATFORM_")


@dataclass(frozen=True)
class EnvVar:
    """One .env setting as Hermes's registry describes it (hermes_cli/config_defaults.py
    OPTIONAL_ENV_VARS, config.py _EXTRA_ENV_KEYS, the provider catalog's key names)."""

    name: str
    description: str
    category: str  # provider / tool / messaging / skill / setting / "" (Hermes's own)
    secret: bool
    listed: bool = True  # False: set in a profile's .env but in no Hermes registry

    @property
    def group(self) -> str:
        if self.category == "messaging" and not self.name.startswith(_USED_PLATFORMS):
            return NOT_USED
        return ENV


def env_vars(found: Any) -> list[EnvVar]:
    out: list[EnvVar] = []
    if not isinstance(found, dict):
        return out
    for name, info in found.items():
        if not isinstance(info, dict) or not str(name).isupper():
            continue
        # Hermes's two rules: the registry's password flag, and its credential
        # key names (_is_secret_config_key, read in its runtime with the list).
        out.append(
            EnvVar(
                name=str(name),
                description=str(info.get("description") or ""),
                category=str(info.get("category") or ""),
                secret=bool(info.get("password")) or bool(info.get("secret")),
            )
        )
    return out


def unlisted_env(name: str) -> EnvVar:
    """A .env line no Hermes registry lists: Hermes's own dashboard treats such a
    key as a secret (web_routers/config_env.py: custom keys are is_password)."""
    return EnvVar(
        name=name,
        description="Not in Hermes's list of .env settings: set in this Hermes by hand, by a "
        "plugin, or by AGOS.",
        category="custom",
        secret=True,
        listed=False,
    )
