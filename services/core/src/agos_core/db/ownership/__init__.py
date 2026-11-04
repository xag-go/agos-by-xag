"""Who owns what AGOS stores: the one list, checked by code on every test run.

The rule: AGOS only SHOWS and CONTROLS; Hermes is the engine and holds everything
it has a place for. AGOS keeps no copy of anything Hermes holds.

Every table, every column and every app_settings key (or key prefix, `name.*`)
AGOS has is in this registry (this package: the tables by area in chats.py, automations.py,
system.py, board.py, merged by tables.py; the app_settings keys in keys.py and
ops.py; the files in files.py; this module only re-exports), in one of two classes and nothing else:

- AGOS_ONLY: product or control data Hermes has no place for. `why` says what it
  is; `hermes` gives the evidence (a path in Hermes v0.22.2) wherever Hermes has
  something close, so the reason it still stays here can be checked again.
- MOVE_ONCE: a legacy value read only to move it into Hermes (or to drop it); the
  code that moves it deletes it after. `hermes` says where it lives now.

tests/test_ownership.py builds the schema from every migration and greps the code
for app_settings keys. A table, column or key that is not here, or that is here
but gone, fails the tests; so does an empty reason, or a MOVE_ONCE key nothing
deletes. A new table or key therefore needs a written reason before it can ship.
The rule and the guards in plain words: docs/hermes-ownership.md.

`writer` (a Table's): the one module that writes the table, its repository under db/
(tests/test_board_chat_repositories.py fails on any other writer); "" while a table
still has more than one.

`moving`: another branch (named) changes this entry; the mark holds only while the
number of migrations is the one it was set at, so a merge that adds migrations
fails until the entry is checked again and the mark removed.
"""

from __future__ import annotations

from agos_core.db.ownership.base import AGOS_ONLY as AGOS_ONLY
from agos_core.db.ownership.base import MOVE_ONCE as MOVE_ONCE
from agos_core.db.ownership.base import Owned as Owned
from agos_core.db.ownership.base import Table as Table
from agos_core.db.ownership.files import CODE as CODE
from agos_core.db.ownership.files import FILES as FILES
from agos_core.db.ownership.files import HERMES_FILES as HERMES_FILES
from agos_core.db.ownership.keys import KEYS as KEYS
from agos_core.db.ownership.keys import WILDCARD_IDS as WILDCARD_IDS
from agos_core.db.ownership.keys import unregistered as unregistered
from agos_core.db.ownership.tables import TABLES as TABLES
