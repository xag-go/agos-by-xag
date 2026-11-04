"""The Automation service (a workspace's automations: AGOS's row plus its job in Hermes cron),
moved here from the old actions/automations package (actions/automations.py re-exports its names).

Each module imports only the modules before it (instructions, cron, jobs, run_history,
owner, sync_loop); the package itself imports nothing, so loading one part stays cheap.

Must not: import its own modules here (loading one part stays cheap) or hold code.
"""

__all__: list[str] = []
