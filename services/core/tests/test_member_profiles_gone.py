"""The member profiles left from before AGOS became single-user are deleted at core
start with Hermes's own `hermes profile delete`; the team's agent profiles stay."""

import sqlite3
from collections.abc import Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from agos_core.actions import member_profiles_gone
from agos_core.config import EngineConfig
from agos_core.engine.hermes import HermesEngine


class Runner:
    """Stands in for `hermes` and `docker`: `profile delete` removes the folder in
    the root it runs in, like Hermes."""

    def __init__(self) -> None:
        self.calls: list[tuple[list[str], str]] = []

    def run(self, args: Sequence[str], *, timeout: float, env: dict[str, str] | None = None) -> str:
        argv = list(args)
        home = (env or {}).get("HERMES_HOME", "")
        self.calls.append((argv, home))
        if Path(argv[0]).name == "hermes" and argv[1:3] == ["profile", "delete"]:
            import shutil

            shutil.rmtree(Path(home) / "profiles" / argv[3])
        return ""

    def spawn(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("nothing is started")


def _core(tmp_path: Path, workspaces: list[str]) -> tuple[Any, Runner]:
    home = tmp_path / ".hermes"
    home.mkdir()
    runner = Runner()
    engine = HermesEngine(
        EngineConfig(
            hermes_bin="/bin/hermes",
            docker_bin="/bin/docker",
            hermes_home=home,
            profile_prefix="agos-",
            sandbox_image="img:1",
            host_home=tmp_path,
            roots_dir=tmp_path / "roots",
        ),
        runner,
    )
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute("CREATE TABLE workspaces (id TEXT PRIMARY KEY)")
    db.executemany("INSERT INTO workspaces (id) VALUES (?)", [(w,) for w in workspaces])
    return SimpleNamespace(engine=engine, db=db), runner


def _profile(tmp_path: Path, workspace: str, name: str) -> Path:
    home = tmp_path / "roots" / f"agos-{workspace}" / "profiles" / name
    home.mkdir(parents=True)
    (home / "config.yaml").write_text("{}\n")
    return home


def test_only_member_profiles_go_through_hermess_profile_delete(tmp_path: Path) -> None:
    core, runner = _core(tmp_path, ["argan", "shop"])
    member = _profile(tmp_path, "argan", "m3")
    other = _profile(tmp_path, "shop", "m12")
    agents = [
        _profile(tmp_path, "argan", "a-writer"),
        _profile(tmp_path, "argan", "a-m3"),  # an agent named "m3": still an agent
        _profile(tmp_path, "shop", "a-m12x"),
    ]
    not_members = [_profile(tmp_path, "shop", name) for name in ("m", "mx1", "m1-a", "m1a")]

    assert member_profiles_gone.leftovers(core) == ["argan--m3", "shop--m12"]
    assert member_profiles_gone.remove_all(core) == ["argan--m3", "shop--m12"]

    assert not member.exists() and not other.exists()
    assert all(p.is_dir() for p in [*agents, *not_members])
    deletes = [
        (argv[1:], home) for argv, home in runner.calls if argv[1:3] == ["profile", "delete"]
    ]
    assert deletes == [
        (["profile", "delete", "m3", "-y"], str(tmp_path / "roots" / "agos-argan")),
        (["profile", "delete", "m12", "-y"], str(tmp_path / "roots" / "agos-shop")),
    ]
    # A second start finds nothing and runs nothing.
    runner.calls.clear()
    assert member_profiles_gone.remove_all(core) == []
    assert runner.calls == []


def test_no_engine_or_no_root_does_nothing(tmp_path: Path) -> None:
    core, runner = _core(tmp_path, ["argan"])
    assert member_profiles_gone.remove_all(core) == []  # no root on disk yet
    no_engine: Any = SimpleNamespace(engine=None, db=core.db)
    assert member_profiles_gone.remove_all(no_engine) == []
    assert runner.calls == []
