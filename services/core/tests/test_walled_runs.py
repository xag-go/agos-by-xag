"""Hermes processes AGOS starts for a root run behind that root's wall when they
run code its walled gateway can write (area3 B3): a plugin CLI command (Hermes
imports `<root>/plugins/*` to find it: H: hermes_cli/main.py:3320-3345), `hermes
cron run` and an automation's script (the root's `scripts/`). Unwalled, a planted
plugin or script ran with AGOS's own access to every workspace.

Hermes's unit's ExecStop/ExecStopPost run only the install's code (`hermes
--run-module gateway.systemd_stop_mark` / `gateway.cgroup_cleanup`, H:
hermes_cli/gateway.py:3343-3346; ExecReload is /bin/kill): proven below with a
planted `gateway/` package in the working folder, which Hermes's launcher never
imports."""

import contextlib
import json
import re
import subprocess
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

import pytest
from split_parts import SRC, whole_text
from test_wall import LAUNCHER, _engine, _Runner, real

from agos_core.engine import wall
from agos_core.engine.cron import CronBridge


def test_a_plugin_cli_command_runs_walled(tmp_path: Path) -> None:
    runner = _Runner()
    engine = _engine(tmp_path, "systemd", runner)
    engine.root("alpha").mkdir(parents=True)
    engine.walled_cli("alpha", "agos-estimate", "t1")
    argv = runner.calls[-1]
    assert argv[1:3] == ["-I", str(Path(wall.__file__).resolve())]
    assert argv[argv.index("--") :] == ["--", "/bin/hermes", "agos-estimate", "t1"]
    assert f"{engine.root('alpha')}" in argv


def test_the_boards_estimate_uses_the_walled_cli() -> None:
    text = whole_text("actions/kanban_board.py")
    # The estimate is a plugin command of the board's port, and the port runs those walled.
    assert re.search(r'kanban_cli\.plugin\(\s*core,\s*workspace_id,\s*"agos-estimate"', text)
    port = (SRC / "actions" / "services" / "board" / "kanban_cli.py").read_text()
    assert re.search(r"def plugin\(.*?hermes_cli\.walled_cli\(", port, re.S)
    assert not re.search(r'(_hermes|hermes_cli\.cli)\([^)]*"agos-estimate"', text)


def test_run_now_and_its_script_run_walled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    engine = _engine(tmp_path, "systemd", _Runner())
    home = engine.root("alpha") / "profiles" / "a-writer"
    (home / "scripts").mkdir(parents=True)
    (home / "scripts" / "fire.py").write_text("print('hi')\n")
    seen: list[list[str]] = []

    def run(argv: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        seen.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, "Ran now: succeeded.\n", "")

    monkeypatch.setattr(subprocess, "run", run)
    bridge = CronBridge(engine.settings, "/usr/bin/python3", wall=engine.walled_for_home)
    bridge.run_script(home, "fire.py", ["manual"])
    with contextlib.suppress(Exception):  # its output file isn't there; only argv matters
        bridge.run_inline(home, "job1")
    for argv in seen:
        assert argv[1:3] == ["-I", str(Path(wall.__file__).resolve())]
        cut = argv.index("--")
        assert f"{engine.root('alpha')}" in argv[:cut]  # the root's wall, a member's too
    assert seen[0][seen[0].index("--") + 1 :] == [
        "/usr/bin/python3",
        str(home / "scripts" / "fire.py"),
        "manual",
    ]
    assert seen[1][seen[1].index("--") + 1 :] == ["/bin/hermes", "cron", "run", "job1"]


def test_automations_give_cron_the_roots_wall() -> None:
    src = Path(__file__).resolve().parents[1] / "src/agos_core/actions/services/automation/cron.py"
    assert "wall=engine.walled_for_home" in src.read_text()


@pytest.fixture
def layout() -> Iterator[Path]:
    """At one fixed place: Hermes's per-root environments survive between tests."""
    from conftest import kept_layout

    with kept_layout("agos-walled-run") as folder:
        yield folder


@real
def test_a_planted_plugin_command_cant_read_another_workspace(layout: Path) -> None:
    """Real wall, real Hermes: a plugin written into root A by its gateway, run as
    a CLI command the way AGOS runs agos-estimate, can't read workspace B."""
    runner_calls: list[Any] = []

    class Real:
        def run(
            self, args: Sequence[str], *, timeout: float, env: dict[str, str] | None = None
        ) -> str:
            runner_calls.append(args)
            done = subprocess.run(  # noqa: S603 - the launcher, a fixed command
                args, capture_output=True, text=True, timeout=timeout, env=env, check=False
            )
            return done.stdout + done.stderr

        def spawn(
            self, args: Sequence[str], *, log_file: Path, env: dict[str, str] | None = None
        ) -> None:
            raise AssertionError("nothing is spawned here")

    from agos_core.config import EngineConfig
    from agos_core.engine.hermes import HermesEngine

    tools = Path.home() / ".hermes" / "tools"
    engine = HermesEngine(
        EngineConfig(
            hermes_bin=str(LAUNCHER),
            docker_bin="docker",
            hermes_home=layout / "shared",
            profile_prefix="agos-",
            sandbox_image="x",
            host_home=Path.home(),
            roots_dir=layout / "data" / "hermes",
            runtime_dir=tools if tools.is_dir() else None,
        ),
        runner=Real(),
    )
    root_a, root_b = engine.root("alpha"), engine.root("beta")
    from conftest import hermes_warm

    for root in (root_a, root_b):
        root.mkdir(parents=True, exist_ok=True)
    hermes_warm(root_a)  # first run of the kept layout: Hermes syncs its environment once
    (root_b / ".env").write_text("OPENROUTER_API_KEY=beta-secret\n")
    plugin = root_a / "plugins" / "agos-planted"
    plugin.mkdir(parents=True)
    (plugin / "plugin.yaml").write_text("name: agos-planted\nversion: '1'\n")
    (plugin / "__init__.py").write_text(
        f"""
def _setup(parser):
    pass

def _handle(args):
    try:
        open({str(root_b / ".env")!r}).read()
        print("PLANTED-READ open")
    except PermissionError:
        print("PLANTED-READ denied")
    return 0

def register(ctx):
    ctx.register_cli_command("agos-planted", "probe", _setup, _handle)
"""
    )
    env = engine.hermes_env("alpha")
    subprocess.run(  # noqa: S603 - unwalled: enabling it, as AGOS does for its own
        [str(LAUNCHER), "plugins", "enable", "agos-planted"],
        env=env, capture_output=True, timeout=180, check=False,
    )  # fmt: skip
    unwalled = subprocess.run(  # noqa: S603 - how it ran before: open
        [str(LAUNCHER), "agos-planted"], env=env, capture_output=True, text=True,
        timeout=180, check=False,
    )  # fmt: skip
    if "PLANTED-READ" not in unwalled.stdout:
        pytest.skip(f"this Hermes didn't load the probe plugin: {unwalled.stderr[-300:]}")
    assert "PLANTED-READ open" in unwalled.stdout
    out = engine.walled_cli("alpha", "agos-planted", timeout=180)
    assert "PLANTED-READ denied" in out, out[-800:]


@real
def test_execstop_runs_only_the_installs_code(layout: Path) -> None:
    from conftest import hermes_warm

    hermes_warm(layout)  # first run of the kept layout: Hermes syncs its environment once
    (layout / "gateway").mkdir()
    (layout / "gateway" / "__init__.py").write_text("print('PLANTED')\n")
    (layout / "gateway" / "systemd_stop_mark.py").write_text("print('PLANTED')\n")
    done = subprocess.run(  # noqa: S603 - Hermes's own ExecStop command
        [str(LAUNCHER), "--run-module", "gateway.systemd_stop_mark"],
        cwd=layout,
        env={"HOME": str(Path.home()), "HERMES_HOME": str(layout), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert "PLANTED" not in done.stdout + done.stderr
    assert json.dumps(done.returncode) == "0"


@real
def test_run_now_starts_a_script_behind_the_real_wall(layout: Path) -> None:
    """Real wall, real Hermes: Run now of a webhook-only automation runs its script
    on Hermes's own runtime command behind the root's wall (it starts, imports
    Hermes, gets its argument), and the script still can't read another root.
    Before, it ran AGOS's launcher file in ~/.cache, which the wall doesn't open:
    exec failed with EACCES and Run now said "Couldn't start it"."""
    from agos_core.config import EngineConfig
    from agos_core.engine.hermes import HermesEngine
    from agos_core.engine.models import hermes_python, hermes_runtime_argv

    tools = Path.home() / ".hermes" / "tools"
    engine = HermesEngine(
        EngineConfig(
            hermes_bin=str(LAUNCHER),
            docker_bin="docker",
            hermes_home=layout / "shared",
            profile_prefix="agos-",
            sandbox_image="x",
            host_home=Path.home(),
            roots_dir=layout / "data" / "hermes",
            runtime_dir=tools if tools.is_dir() else None,
        ),
        runner=_Runner(),
    )
    root_a, root_b = engine.root("alpha"), engine.root("beta")
    from conftest import hermes_warm

    for root in (root_a, root_b):
        root.mkdir(parents=True, exist_ok=True)
    hermes_warm(root_a)  # first run of the kept layout: Hermes syncs its environment once
    (root_b / ".env").write_text("OPENROUTER_API_KEY=beta-secret\n")
    (root_a / "scripts").mkdir()
    (root_a / "scripts" / "fire.py").write_text(
        "import sys, hermes_constants\n"
        f"try:\n    open({str(root_b / '.env')!r}).read(); other = 'open'\n"
        "except PermissionError:\n    other = 'denied'\n"
        "print('FIRED', sys.argv[1:], other)\n"
    )
    bridge = CronBridge(
        engine.settings,
        hermes_python(engine.settings),
        wall=engine.walled_for_home,
        script_python=hermes_runtime_argv(engine.settings),
    )
    code, said = bridge.run_script(root_a, "fire.py", ["manual"])
    assert code == 0, said
    assert "FIRED ['manual'] denied" in said, said
