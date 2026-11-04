"""Source of a module split by responsibility: the old module (now a facade) and every
module of its package it re-exports names from, for the tests that read code as text."""

from __future__ import annotations

import inspect
from types import ModuleType


def split_modules(facade: ModuleType) -> list[ModuleType]:
    """The facade, then each module of its package (siblings and subpackages) that owns
    one of its names (first seen first)."""
    package = facade.__name__.rpartition(".")[0]
    out = [facade]
    for value in vars(facade).values():
        owner = inspect.getmodule(value)
        if owner is None or owner in out:
            continue
        # A sibling, or a module of a service package below it (actions/services/<service>/).
        if owner.__name__.rpartition(".")[0] == package or owner.__name__.startswith(package + "."):
            out.append(owner)
    return out


def split_source(facade: ModuleType) -> str:
    """The code of the facade and of the modules it re-exports from, as one text."""
    return "\n".join(inspect.getsource(m) for m in split_modules(facade))
