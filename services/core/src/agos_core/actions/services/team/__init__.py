"""The Team service (a workspace's members: their Hermes profiles, what AGOS keeps
beside them, and how the Office shows them).

Each module imports only the modules before it; the package itself imports
nothing, so loading one part stays cheap.

Must not: import its own modules here (loading one part stays cheap) or hold code.
"""

__all__: list[str] = []
