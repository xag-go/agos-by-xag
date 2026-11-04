"""History kept: Hermes's own `sessions.auto_prune` (hermes_cli/config_defaults.py
`sessions`, read by hermes_cli/cli_auto_maintenance.py and gateway/run.py).

Hermes's default (true) deletes ended sessions after `sessions.retention_days`
(90), and their `session_model_usage` rows go with them, so the usage dashboard
and the Log would lose anything older. A NEW profile starts with pruning off
(engine/rules.py `seeded_config`: set only while the profile doesn't have the
key); afterwards the value is Hermes's alone and a later change is never reset.
AGOS keeps no copy of it.
"""

AUTO_PRUNE = "sessions.auto_prune"


def seeded_defaults() -> dict[str, str]:
    """`hermes config set` pairs a new profile starts with: history is kept."""
    return {AUTO_PRUNE: "false"}
