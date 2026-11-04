"""The Co-Founder service: its mode, action cards and the actions it runs from chat, split
out of actions/cofounder_actions.py and actions/cofounder_more.py, and its tools on a
Hermes turn (agent_tools, out of actions/hermes_channel.py).

Each module imports only the modules before it in the service's dependency order (no
cycles); the package itself imports nothing, so loading one part stays cheap.

Must not: import its own modules here (loading one part stays cheap) or hold code.
"""

__all__: list[str] = []
