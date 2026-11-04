"""Every Hermes internal AGOS uses, in one list, and the check that a Hermes source
tree still has each of them as AGOS uses it.

Hermes is the engine; AGOS calls into it in three ways that a Hermes upgrade can
break without any test of ours noticing:

- the agos-guard plugin (hermes_plugin/agos_guard/*), which runs inside Hermes's
  processes and calls Hermes's modules, classes and private helpers;
- helper scripts AGOS runs in Hermes's own runtime (strings in engine/*.py,
  actions/*.py, migrate_root.py, and engine/connect_helper.py);
- names of Hermes's plugin hooks the plugin registers.

`CONTRACT` lists each one: the Hermes module, the name, what kind of thing AGOS
needs it to be, how AGOS calls it, and which AGOS feature breaks when it changes.
tests/test_hermes_contract.py fails when AGOS's code uses a Hermes name that is
not on the list.

`check(root)` reads a Hermes source tree with `ast` (nothing is imported or run)
and reports each entry that is gone or no longer fits:

- function / method / class (its constructor): a required parameter AGOS doesn't
  pass, or a keyword AGOS passes that Hermes no longer takes (unless Hermes takes
  **kwargs), or more positional arguments than Hermes takes;
- override (AGOS's subclass replaces or wraps Hermes's method, Hermes calls it):
  Hermes's parameters must be the ones AGOS's version takes;
- attr / constant / module / hook / text: it exists.

CLI: `python -m agos_core.engine.hermes_contract [/path/to/hermes-agent]` prints a
plain report and exits 1 when anything broke (2: not a Hermes source tree). The
first step of every Hermes upgrade (docs/hermes-upgrade.md).

At run time, `broken()` is how AGOS's core says one of these failed (logged as
ERROR "Hermes contract broken: <name>", which lands in the workspace Log, and told
to the owner once per name; the plugin has its own copy in agos_guard/contract.py).

The entries live in engine/contract/uses_*.py (assembled by contract/entries.py),
what an entry is in contract/base.py, the checker in contract/tree.py; this module
re-exports all of it and keeps the run-time part (its state is this module's).
"""

from __future__ import annotations

import logging
import re
import threading
from collections.abc import Callable
from typing import Any

from agos_core.engine.contract.base import HERMES_ROOTS as HERMES_ROOTS
from agos_core.engine.contract.base import KINDS as KINDS
from agos_core.engine.contract.base import Use as Use
from agos_core.engine.contract.base import _hooks as _hooks
from agos_core.engine.contract.base import _u as _u
from agos_core.engine.contract.entries import CONTRACT as CONTRACT
from agos_core.engine.contract.tree import Finding as Finding
from agos_core.engine.contract.tree import Found as Found
from agos_core.engine.contract.tree import Tree as Tree
from agos_core.engine.contract.tree import _dataclass_fields as _dataclass_fields
from agos_core.engine.contract.tree import check as check
from agos_core.engine.contract.tree import check_one as check_one
from agos_core.engine.contract.tree import default_root as default_root
from agos_core.engine.contract.tree import is_hermes as is_hermes
from agos_core.engine.contract.tree import main as main
from agos_core.engine.contract.tree import report as report
from agos_core.engine.hermes_contract_ast import Params as Params
from agos_core.engine.hermes_contract_ast import call_problems as call_problems
from agos_core.engine.hermes_contract_ast import params_of as params_of

# ---- at run time: a Hermes internal failed in AGOS's core ---------------------------------

log = logging.getLogger("agos.hermes_contract")
KEYS = frozenset(u.key for u in CONTRACT)
_told: set[str] = set()
_told_lock = threading.Lock()
notifiers: list[Callable[[str, str, str | None], None]] = []  # who else hears it (api/app.py)

# A helper script's own catch says so on a line of its own (see `SCRIPT_MARK`).
SCRIPT_MARK = "AGOS-CONTRACT-BROKEN "
_SCRIPT_LINE = re.compile(r"^AGOS-CONTRACT-BROKEN (\S+) ?(.*)$", re.M)
_IMPORT_ERROR = re.compile(r"ImportError: cannot import name '(\w+)' from '([\w.]+)'")
_ATTR_ERROR = re.compile(r"AttributeError: module '([\w.]+)' has no attribute '(\w+)'")
_NO_MODULE = re.compile(r"ModuleNotFoundError: No module named '([\w.]+)'")
_TYPE_ERROR = re.compile(
    r"TypeError: (\w+)\(\) (got an unexpected keyword argument|missing \d+ required)"
)


def broken(name: str, detail: str = "", workspace_id: str | None = None) -> bool:
    """A Hermes internal on the list failed (AGOS already fell back or refused, as
    before): ERROR in the Log, and the owner is told, once per name while this core
    runs. True when this was the first time."""
    with _told_lock:
        if name in _told:
            return False
        _told.add(name)
    where = f" (workspace {workspace_id})" if workspace_id else ""
    why = detail[:500] or "failed"  # its Log line is quiet: the notifiers below tell him
    log.error("Hermes contract broken: %s%s: %s", name, where, why, extra={"agos_quiet": True})
    for notify in list(notifiers):
        try:
            notify(name, detail, workspace_id)
        except Exception:
            log.warning("Hermes contract break not told to the owner", exc_info=True)
    return True


def reset() -> None:
    """Forget what was told (tests)."""
    with _told_lock:
        _told.clear()


def names_in_output(text: str) -> list[tuple[str, str]]:
    """The contract entries a helper script's output names as failed: its own
    `AGOS-CONTRACT-BROKEN <name> <error>` lines, and Python's own ImportError /
    AttributeError / TypeError lines that name an entry."""
    out: list[tuple[str, str]] = [(m[1], m[2].strip()) for m in _SCRIPT_LINE.finditer(text or "")]
    for m in _IMPORT_ERROR.finditer(text or ""):
        out.append((f"{m[2]}.{m[1]}", m[0]))
    for m in _ATTR_ERROR.finditer(text or ""):
        out.append((f"{m[1]}.{m[2]}", m[0]))
    for m in _NO_MODULE.finditer(text or ""):
        out.append((m[1], m[0]))
    for m in _TYPE_ERROR.finditer(text or ""):
        for key in sorted(KEYS):
            if key.rsplit(".", 1)[-1] == m[1]:
                out.append((key, m[0]))
                break
    return [(n, d) for n, d in out if n in KEYS or any(k.startswith(n + ".") for k in KEYS)]


def seen_in_output(text: str, workspace_id: str | None = None) -> list[str]:
    """Reports each contract entry a helper script's output says failed."""
    names = []
    for name, detail in names_in_output(text):
        broken(name, detail, workspace_id)
        names.append(name)
    return names


def ran(done: Any, workspace_id: str | None = None) -> list[str]:
    """After a helper script ran in Hermes's runtime (a subprocess.CompletedProcess):
    a failed run whose output names a contract entry (Python's own ImportError /
    AttributeError / TypeError, or the script's `AGOS-CONTRACT-BROKEN` line) is
    reported. The caller's own handling of the failure stays as it was."""
    try:
        parts = []
        for stream in (getattr(done, "stdout", None), getattr(done, "stderr", None)):
            if isinstance(stream, bytes):
                stream = stream.decode("utf-8", "replace")
            if isinstance(stream, str):
                parts.append(stream)
        text = "\n".join(parts)
        if getattr(done, "returncode", 0) == 0 and SCRIPT_MARK not in text:
            return []
        return seen_in_output(text, workspace_id)
    except Exception:
        log.warning("Hermes contract check of a helper's output failed", exc_info=True)
        return []


if __name__ == "__main__":
    raise SystemExit(main())
