"""The Channel service (each workspace's Telegram bot, run by its Hermes gateway), split out of
actions/channels.py and actions/hermes_channel.py (gateway_*, hermes_addresses,
telegram_menu), with the owner's needs on his phone (owner_needs).

Each module imports only the modules before it in the service's dependency order (no
cycles); the package itself imports nothing, so loading one part stays cheap.

Must not: import its own modules here (loading one part stays cheap) or hold code.
"""

__all__: list[str] = []
