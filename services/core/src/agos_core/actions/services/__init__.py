"""Service modules (one package per service), split out of the big action files.

Each package holds one service's code; the old modules (actions/library.py, ...)
re-export it, so every import path and patch target keeps working.

Must not: import its own modules here (loading one part stays cheap) or hold code.
"""

__all__: list[str] = []
