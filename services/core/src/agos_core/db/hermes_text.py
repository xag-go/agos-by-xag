"""agos_text() / agos_text5(): SQL functions older migrations' `messages` views name.

Before, a message row linked to Hermes had no text of its own and the view read it
from the profile's state.db through these functions. Those copies are gone (a chat's
words are Hermes's, db/hermes_chats.py) and the view of migration 101 reads the
row's own text. Old migrations still create views that name these functions, so
every connection registers them as the row's own text: an upgrade from an old
database runs those migrations before the view is replaced.
"""

from __future__ import annotations

import sqlite3
from typing import Any


def plain(body: Any, *_rest: Any) -> Any:
    """The row's own text."""
    return body


def install(db: sqlite3.Connection) -> None:
    db.create_function("agos_text", 4, plain, deterministic=True)
    db.create_function("agos_text5", 5, plain, deterministic=True)
