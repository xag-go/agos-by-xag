"""Ownership of the operations keys (backups, flags, the ops watch): part of the
registry's KEYS (db/ownership/keys.py). Same rules as db/ownership/__init__.py.

Must not: hold any other key (keys.py) or a table entry.
"""

from __future__ import annotations

from agos_core.db.ownership.base import Owned, agos

__all__ = [
    "OPS_KEYS",
]

OPS_KEYS: dict[str, Owned] = {
    "backup_password": agos(
        "the backup password, sealed",
        "H: hermes_cli/backup.py (no encryption or password anywhere in it)",
    ),
    "backup_schedule": agos(
        "when AGOS's whole backup runs and how many sealed files to keep. It covers "
        "agos.db (AGOS's own), every workspace root and the shared home, sealed with "
        "AGOS's key. Hermes's cron runs a home's jobs in its gateway or once per "
        "`hermes cron tick`, which still needs an outside timer, and a job belongs to "
        "one home (a workspace's root would stop it with that workspace)",
        "H: gateway/run.py:5623 (cron ticks in the gateway), hermes_cli/subcommands/"
        "cron.py:202 (`cron tick`: run due jobs once and exit), hermes_cli/subcommands/"
        "backup.py:32 -k (prunes its own hermes-backup-*.zip only)",
    ),
    "backup_last": agos("the last backup's result"),
    "backup_rehearsal": agos("the last restore rehearsal's result"),
    "server_rehearsal": agos("the last server-move rehearsal's result"),
    "ops.flags": agos(
        "the owner's Labs switches (actions/flags.py)",
        "H: hermes_cli/config_defaults.py has no feature-flag registry",
    ),
    "ops.watch": agos(
        "the ops watch's marks (actions/ops_watch.py): when the owner was last told "
        "about backups, the last monthly restore test and weekly database check",
        "H: hermes_cli/backup.py has no restore test or schedule",
    ),
}
