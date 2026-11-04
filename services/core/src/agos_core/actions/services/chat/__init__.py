"""The Chat service (a workspace chat and a group chat's Hermes room: every answer is
Hermes's), split out of actions/chat.py and actions/rooms.py, with the chat's read model
(view, out of db/chats.py) and a Hermes gateway turn's lifecycle (gateway_turns, out of
actions/hermes_channel.py).

Each module imports only the modules before it in the service's dependency order (no
cycles); the package itself imports nothing, so loading one part stays cheap.

Must not: import its own modules here (loading one part stays cheap) or hold code.
"""

__all__: list[str] = []
