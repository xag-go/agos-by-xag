"""The Workspace service's parts split out of actions/workspaces.py (which stays its
entry point: create, configure, archive, delete, the folders).

Must not: import its own modules here (loading one part stays cheap) or hold code.
"""

__all__: list[str] = []
