"""The Settings service: every Hermes setting of each workspace, split out of actions/hermes_all_settings.py.

Each module imports only the modules before it in the service's dependency order (no
cycles); the package itself imports nothing, so loading one part stays cheap.

Must not: import its own modules here (loading one part stays cheap) or hold code.
"""

__all__: list[str] = []
