"""The fake Hermes skills hub test_skill_growth.py installs from (`hermes skills …`
answers as engine/sources.py runs them), kept beside the tests that use it."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest

from agos_core.actions.services.library import sources as library_sources
from agos_core.engine import models, sources

__all__ = ["HUB", "HUB_SKILL", "FakeHub", "_hub"]

HUB = "skills-sh/acme/skills/invoice-pro"
HUB_SKILL = "---\nname: invoice-pro\ndescription: Check invoice totals.\n---\n\n1. Add it up.\n"


class FakeHub:
    """Hermes's skills hub as `hermes skills …` answers (engine/sources.py runs it)."""

    def __init__(self, *, verdict: str = "SAFE", scripts: bool = False, block: str = "") -> None:
        self.verdict, self.scripts, self.block = verdict, scripts, block
        self.calls: list[list[str]] = []

    def __call__(self, src: Any, args: list[str], **_: Any) -> str:
        self.calls.append(list(args))
        home = Path(src.library_home or "/nonexistent")
        folder = home / "skills" / "agos-library" / "invoice-pro"
        if args[:2] == ["skills", "inspect"]:
            return "Name: invoice-pro\nDescription: Check invoice totals.\n"
        if args[:2] == ["skills", "search"]:
            return json.dumps(
                [
                    {
                        "name": "invoice-pro",
                        "description": "Check invoice totals.",
                        "identifier": HUB,
                        "trust_level": "community",
                    }
                ]
            )
        if args[:2] == ["skills", "install"]:
            if self.block and "--force" not in args:
                raise sources.SourceError(self.block)
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "SKILL.md").write_text(HUB_SKILL)
            if self.scripts:
                (folder / "scripts").mkdir(exist_ok=True)
                (folder / "scripts" / "total.py").write_text("print(1)\n")
            return (
                f"Scan: invoice-pro (skills-sh/community)  Verdict: {self.verdict}\n"
                "Decision: ALLOWED — Allowed (community source, safe verdict)\n"
                "Scan provenance: fresh; scanner 3.1; hash ab12\n"
            )
        if args[:2] == ["skills", "uninstall"]:
            shutil.rmtree(folder, ignore_errors=True)
            return "Uninstalled.\n"
        if args[:2] == ["skills", "check"]:
            return ""
        raise AssertionError(args)


def _hub(monkeypatch: pytest.MonkeyPatch, **kw: Any) -> FakeHub:
    hub = FakeHub(**kw)
    monkeypatch.setattr(sources.Sources, "_hermes", lambda src, args, **k: hub(src, args, **k))
    # No Hermes install in tests: its python and checkout are this one's.
    monkeypatch.setattr(library_sources, "hermes_python", lambda settings: sys.executable)
    monkeypatch.setattr(models, "hermes_repo", lambda settings: Path(sys.prefix))
    return hub
