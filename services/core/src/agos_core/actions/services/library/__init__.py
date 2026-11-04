"""The Library service (skills, agents, MCP servers, tools, connectors), split out of
actions/library.py, actions/workspace_skills.py and actions/skill_growth.py.

Each module imports only the modules before it in the service's dependency order (no
cycles); the package itself imports nothing, so loading one part stays cheap.

Must not: import its own modules here (loading one part stays cheap) or hold code.
"""

__all__: list[str] = []
