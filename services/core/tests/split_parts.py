"""Source guards that read one module's text, after that module was split.

A big module split into service parts (actions/services/...) keeps its old file as a
facade that re-exports the parts; each part's docstring says "Split out of <module>".
Guards that look for (or forbid) a line in the old file read the whole: the facade
plus every part split out of it.
"""

from __future__ import annotations

from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "agos_core"


def _module(rel: str) -> str:
    return "agos_core." + rel.removesuffix(".py").replace("/", ".")


def is_part_of(text: str, rel: str) -> bool:
    """True when `text` is a part split out of the module at `rel` (agos_core-relative)."""
    return f"Split out of {_module(rel)} " in text


def parts_of(rel: str) -> list[Path]:
    """The files split out of `rel`, sorted."""
    return sorted(
        p
        for p in SRC.rglob("*.py")
        if "__pycache__" not in p.parts and is_part_of(p.read_text(), rel)
    )


def whole_text(rel: str, texts: dict[str, str] | None = None) -> str:
    """The facade's text plus every part split out of it."""
    if texts is None:
        return "\n".join(p.read_text() for p in [SRC / rel, *parts_of(rel)])
    return "\n".join([texts[rel], *(t for t in texts.values() if is_part_of(t, rel))])
