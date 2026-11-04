"""The proposals an agent puts to the owner (a hire, an instructions change, a plan), split out of actions/proposals.py.

Each module imports only the modules before it in the service's dependency order (no
cycles); the package itself imports nothing, so loading one part stays cheap.

Must not: import its own modules here (loading one part stays cheap) or hold code.
"""

__all__: list[str] = []
