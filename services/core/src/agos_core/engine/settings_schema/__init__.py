"""Hermes's own list of its settings, read from Hermes, split out of engine/hermes_schema.py.

Each module imports only the modules before it in the dependency order (no cycles);
the package itself imports nothing, so loading one part stays cheap.
"""
