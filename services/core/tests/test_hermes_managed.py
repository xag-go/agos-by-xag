"""The settings that are one value for every workspace live in Hermes's managed
scope (actions/hermes_managed.py): every Hermes process AGOS runs gets the folder,
on the systemd path (the gateway unit's drop-in) as on the test-only spawn path;
no AGOS writer keeps a per-profile copy; the old copies move in once."""

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from test_agent_profiles import add_agent
from test_library import env, ws  # noqa: F401 - fixture

from agos_core.actions import hermes_managed
from agos_core.config import EngineConfig
from agos_core.engine import config_file, root_unit
from agos_core.engine.hermes import HermesEngine


def _engine(tmp_path: Path, supervisor: str, runner: Any) -> HermesEngine:
    return HermesEngine(
        EngineConfig(
            hermes_bin="/bin/hermes",
            docker_bin="/bin/docker",
            hermes_home=tmp_path / ".hermes",
            profile_prefix="agos-",
            sandbox_image="img:1",
            host_home=tmp_path,
            roots_dir=tmp_path / "data" / "hermes",
            runtime_dir=tmp_path / ".hermes" / "tools",
            gateway_supervisor=supervisor,
        ),
        runner=runner,
    )


class _Runner:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], dict[str, str]]] = []
        self.spawned: list[dict[str, str]] = []

    def run(self, args: Any, *, timeout: float, env: Any = None) -> str:  # noqa: F811
        self.calls.append((list(args), dict(env or {})))
        return ""

    def spawn(self, args: Any, *, log_file: Path, env: Any = None) -> None:  # noqa: F811
        self.spawned.append(dict(env or {}))


def test_the_systemd_gateway_reads_the_managed_scope(tmp_path: Path) -> None:
    """Live path: Hermes's own service. Its unit gets HERMES_MANAGED_DIR through
    AGOS's drop-in (with the runtime), and a unit installed before gets it at
    AGOS's next start (refresh_dropin), for its next start."""
    runner = _Runner()
    engine = _engine(tmp_path, "systemd", runner)
    root = engine.root("alpha")
    root.mkdir(parents=True)
    root_unit.remember(root, "hermes-gateway-abc.service")
    unit = engine.service_unit("alpha")
    unit.parent.mkdir(parents=True)
    unit.write_text("[Service]\n")
    managed = tmp_path / "data" / "hermes-managed"
    assert managed.is_dir()  # made at start: Hermes reads no scope from a missing folder
    engine.refresh_dropin("alpha")
    body = (unit.with_name(unit.name + ".d") / "agos-runtime.conf").read_text()
    assert f'Environment="HERMES_MANAGED_DIR={managed}"' in body
    assert f'Environment="HERMES_RUNTIME_DIR={tmp_path / ".hermes" / "tools"}"' in body
    assert any(a[:2] == ["systemctl", "--user"] for a, _e in runner.calls)  # daemon-reload
    before = len(runner.calls)
    engine.refresh_dropin("alpha")  # unchanged: no reload
    assert len(runner.calls) == before
    # Every Hermes CLI call AGOS runs carries it too.
    engine._hermes("alpha", "config", "get", "timezone")
    assert runner.calls[-1][1]["HERMES_MANAGED_DIR"] == str(managed)
    # ...except the writer of a profile's own copy (Hermes refuses pinned keys there).
    engine.unmanaged_hermes("alpha", "config", "unset", "timezone")
    assert runner.calls[-1][1]["HERMES_MANAGED_DIR"] == str(managed / ".off")
    assert not (managed / ".off").exists()


def test_the_systemd_gateway_keeps_two_malloc_arenas_from_its_next_start(
    tmp_path: Path,
) -> None:
    """glibc gives a Python gateway one malloc arena per thread (live: 71 arenas,
    214 MB in a 78-thread gateway): the drop-in caps them at 2. A changed drop-in
    only reloads systemd: the running gateway is never restarted for it, it takes
    the cap at its next start (S7)."""
    runner = _Runner()
    engine = _engine(tmp_path, "systemd", runner)
    root = engine.root("alpha")
    root.mkdir(parents=True)
    root_unit.remember(root, "hermes-gateway-abc.service")
    unit = engine.service_unit("alpha")
    unit.parent.mkdir(parents=True)
    unit.write_text("[Service]\n")
    dropin = unit.with_name(unit.name + ".d") / "agos-runtime.conf"
    dropin.parent.mkdir(parents=True)
    dropin.write_text("[Service]\n")  # one an older AGOS wrote, without the cap
    engine.refresh_dropin("alpha")
    assert 'Environment="MALLOC_ARENA_MAX=2"' in dropin.read_text()
    assert [a for a, _e in runner.calls] == [["systemctl", "--user", "daemon-reload"]]


def test_the_spawn_gateway_reads_the_managed_scope(tmp_path: Path) -> None:
    """Test-only path (e2e): the gateway AGOS spawns gets it in its environment."""
    runner = _Runner()
    engine = _engine(tmp_path, "spawn", runner)
    engine.is_running = lambda _ws: bool(runner.spawned)  # type: ignore[method-assign,assignment]
    engine.start("alpha")
    assert runner.spawned[0]["HERMES_MANAGED_DIR"] == str(tmp_path / "data" / "hermes-managed")
    engine.refresh_dropin("alpha")  # no service, nothing to write
    assert not list(tmp_path.rglob("agos-runtime.conf"))


def test_a_running_gateway_says_whether_it_reads_the_scope(tmp_path: Path) -> None:
    engine = _engine(tmp_path, "systemd", _Runner())
    home = engine.root("alpha")
    home.mkdir(parents=True)
    assert engine.gateway_managed("alpha") is None  # not running

    def gateway(env_extra: dict[str, str]) -> subprocess.Popen[bytes]:
        proc = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)", "gateway"],
            env={"PATH": "/usr/bin:/bin", **env_extra},
        )
        # Right after the fork /proc still shows the parent's command line: wait
        # until the child has really become the "gateway" (it raced on a busy box).
        cmdline = Path(f"/proc/{proc.pid}/cmdline")
        for _ in range(200):
            if b"gateway" in cmdline.read_bytes():
                break
            time.sleep(0.05)
        (home / "gateway_state.json").write_text(
            json.dumps({"pid": proc.pid, "gateway_state": "running"})
        )
        return proc

    old = gateway({})
    try:
        assert engine.gateway_managed("alpha") is False  # started before AGOS gave it
    finally:
        old.kill()
        old.wait()
    new = gateway({"HERMES_MANAGED_DIR": str(engine.settings.managed_home)})
    try:
        assert engine.gateway_managed("alpha") is True
    finally:
        new.kill()
        new.wait()


def test_no_agos_writer_keeps_a_per_profile_copy() -> None:
    from agos_core.actions import hermes_fallback, hermes_limits
    from agos_core.engine import rules

    pinned = set(hermes_managed.by_card())
    assert not pinned & set(rules.profile_config(image="i:1", mounts=[]))
    assert not pinned & set(rules.seeded_config())
    assert not hasattr(hermes_limits, "give_new_workspace")
    assert not hasattr(hermes_fallback, "give_new_profile")
    # Every managed config key is on its card (read-only on the Hermes settings
    # page, which shows config.yaml; the .env one is on the Time limits card).
    from agos_core.actions.hermes_all_settings import card_keys

    assert {k for k in pinned if not k.isupper()} <= set(card_keys())


def test_old_copies_move_in_once_with_the_most_common_value(env: Any) -> None:  # noqa: F811
    client, core, _runner, _home = env
    a, b, c = ws(client, "Alpha"), ws(client, "Beta"), ws(client, "Cedar")
    add_agent(client, a, "writer")
    # The scope already holds the owner's start values (the core's start); an old
    # AGOS had written the run budget into every profile instead.
    core.engine.managed_write([], ["agent.run_budget_seconds", "kanban.max_in_progress"])
    for key in (a, f"{a}--a-writer", b):
        core.engine.unmanaged_hermes(key, "config", "set", "agent.run_budget_seconds", "600")
    core.engine.unmanaged_hermes(c, "config", "set", "agent.run_budget_seconds", "60")
    moved = hermes_managed.move_once(core)
    assert moved == ["agent.run_budget_seconds"]  # no profile had kanban's cap: Hermes's
    assert hermes_managed.value(core, "agent.run_budget_seconds") == 600
    hermes_managed.settle(core)
    for key in (a, f"{a}--a-writer", b, c):
        own = config_file.read(core.engine.profile_home(key))
        assert hermes_managed.lookup(own, "agent.run_budget_seconds") is hermes_managed._MISSING
    assert hermes_managed.move_once(core) == []  # once
    # The time limits start on the owner's values (no profile held them).
    assert hermes_managed.value(core, "terminal.timeout") == 86400
    # The Hermes settings page shows the scope's value, on its card, for everyone.
    from agos_core.actions import hermes_all_settings

    core.engine.config_schema = lambda: []
    rows = {r["key"]: r for r in hermes_all_settings.read(core)["settings"]}
    row = rows["agent.run_budget_seconds"]
    assert not row["editable"] and "one value for every workspace" in json.dumps(row).lower()
    assert "600" in json.dumps(row)


def test_no_zone_in_the_shared_home_never_writes_a_marker_as_the_zone(env: Any) -> None:  # noqa: F811
    """With no `timezone` in the shared home (a fresh machine), the move never writes
    the internal "missing" marker as the zone: Hermes once read
    '<object object at 0x…>' as its timezone (and its own config writes failed)."""
    client, core, _runner, _home = env
    ws(client, "Alpha")
    core.engine.managed_write([], ["timezone"])
    shared = core.engine.settings.hermes_home / "config.yaml"
    if shared.is_file():
        shared.write_text(
            "".join(
                line
                for line in shared.read_text().splitlines(True)
                if not line.startswith("timezone:")
            )
        )
    hermes_managed.move_once(core)
    zone = hermes_managed.value(core, "timezone")
    assert zone is None or (isinstance(zone, str) and "object" not in zone)
    text = (core.engine.settings.managed_home / "config.yaml").read_text()
    assert "<object object" not in text


def test_the_managed_folders_first_write_waits_for_hermess_home_upkeep(tmp_path: Path) -> None:
    """The managed folder's first Hermes command runs Hermes's one-time home upkeep
    there (minutes on a busy machine: live's first move timed out at 60 s), so the
    first write may take long; later ones keep a short limit."""
    from agos_core.engine import hermes as engine_module

    timeouts: list[float] = []

    class Timed(_Runner):
        def run(self, args: Any, *, timeout: float, env: Any = None) -> str:  # noqa: F811
            timeouts.append(timeout)
            if args[1:3] == ["config", "set"]:
                folder = Path(env["HERMES_HOME"])
                (folder / "config.yaml").write_text("x: 1\n")
            return ""

    engine = _engine(tmp_path, "systemd", Timed())
    engine.managed_write([("a.b", "1"), ("c.d", "2")], [])
    assert timeouts[0] == engine_module.MANAGED_FIRST_TIMEOUT_S >= 900
    assert timeouts[1] <= 120
    engine.managed_write([("e.f", "3")], ["a.b"])
    assert all(t <= 120 for t in timeouts[2:])


def test_a_marker_zone_already_written_is_repaired_once_at_start(env: Any) -> None:  # noqa: F811
    """An install that ran the old move holds '<object object at 0x…>' (or another
    zone Hermes rejects) as its managed `timezone`. The core's start repairs it once:
    the shared home's zone, else unset. Settings never shows it."""
    from agos_core.actions import owner_time

    client, core, _runner, _home = env
    ws(client, "Alpha")
    shared = core.engine.settings.hermes_home / "config.yaml"
    marker = "<object object at 0x7f3a2c1b4e60>"

    def seed(own: str | None) -> None:
        core.engine.managed_write([("timezone", marker)], [])
        kept = shared.read_text().splitlines(True) if shared.is_file() else []
        kept = [line for line in kept if not line.startswith("timezone:")]
        shared.write_text("".join(kept) + (f"timezone: {own}\n" if own else ""))
        assert hermes_managed.value(core, "timezone") == marker

    seed("Europe/Paris")
    assert owner_time.owner_zone(core) == ""  # never shown, even before the repair
    hermes_managed.at_start(core)
    assert hermes_managed.value(core, "timezone") == "Europe/Paris"
    assert owner_time.owner_zone(core) == "Europe/Paris"
    assert hermes_managed.move_once(core) == []  # once: a valid zone is left alone

    seed(None)
    hermes_managed.at_start(core)
    assert hermes_managed.value(core, "timezone") is None
    assert "<object object" not in (core.engine.settings.managed_home / "config.yaml").read_text()
    assert owner_time.owner_zone(core) == ""

    core.engine.managed_write([("timezone", "Mars/Olympus")], [])  # not an IANA zone
    hermes_managed.at_start(core)
    assert hermes_managed.value(core, "timezone") is None
