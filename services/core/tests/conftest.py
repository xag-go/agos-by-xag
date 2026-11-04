"""Shared test setup."""

import contextlib
import os
import re
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from autouse_fixtures import _hermes_circuits_closed, _hermes_never_on_the_loop  # noqa: F401

# Hermes never starts on the core's event loop (engine/loop_guard.py): in the whole
# suite a route or loop task that starts it fails instead of being only logged.
os.environ["AGOS_STRICT_LOOP"] = "1"

# Test files that read the installed Hermes Agent's own source (~/.hermes/hermes-agent)
# or run the real `hermes`, and do not skip themselves without it. Every test in them
# gets the `hermes` marker: GitHub CI runs `-m "not hermes"` in parallel, the nightly
# self-hosted job (.github/workflows/nightly-hermes.yml) runs the whole suite serially.
# A new file that needs a real Hermes goes here, or skips itself when Hermes is missing.
HERMES_FILES = frozenset(
    {
        "test_cofounder_hermes.py",
        "test_cofounder_more.py",
        "test_helper_models.py",
        "test_hermes_all_settings.py",
        "test_hermes_managed.py",
        "test_hermes_roots.py",
        "test_hermes_time_limits.py",
        "test_hermes_voice.py",
        "test_install_defaults.py",
        "test_key_pools.py",
        "test_move_day_kit.py",
        "test_settings_read_ahead.py",
        "test_workspace_logins.py",
    }
)


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    for item in items:
        if item.path.name in HERMES_FILES:
            item.add_marker(pytest.mark.hermes)


def _on_hermes(what: str, fake: Callable[..., Any]) -> Callable[..., Any]:
    """A test's stand-in for a Hermes run keeps the real one's rule: never on the
    core's event loop (the real one starts Hermes whenever its cache is cold)."""
    from agos_core.engine.loop_guard import off_loop

    def run(*args: Any, **kwargs: Any) -> Any:
        off_loop(what)
        return fake(*args, **kwargs)

    return run


# The made-up MCP hosts tests add (they resolve nowhere; a real unknown name is refused).
_TEST_MCP_HOST = re.compile(r"x|([a-z0-9-]+\.)*(example\.com|invalid)")


@pytest.fixture(autouse=True)
def _test_mcp_hosts_are_public(monkeypatch: pytest.MonkeyPatch) -> None:
    """engine/library.py refuses an MCP URL whose name doesn't resolve; the tests'
    made-up names stand for public servers."""
    from agos_core.engine import library

    real = library._private

    def private(host: str) -> bool | None:
        found = real(host)
        return False if found is None and _TEST_MCP_HOST.fullmatch(host) else found

    monkeypatch.setattr(library, "_private", private)


@pytest.fixture(autouse=True)
def _team_profiles_made_at_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """Live, the members' profiles are made in the background; tests check them."""
    from agos_core.actions import agent_profiles

    monkeypatch.setattr(agent_profiles, "IN_BACKGROUND", False)


@pytest.fixture(autouse=True)
def _folder_restarts_at_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """Live, a folder click's gateway restart runs after the answer; tests check it
    when the click returns (the C2 tests run it in the background themselves)."""
    from agos_core.actions import engine as engine_actions

    monkeypatch.setattr(engine_actions, "RESTART_IN_BACKGROUND", False)
    monkeypatch.setattr(engine_actions, "RESTART_SETTLE_S", 0.0)


def hermes_ready_home(home: Any) -> None:
    """Give a throwaway HERMES_HOME the Python environment Hermes keeps per data root,
    taken from one prepared copy instead of built again (minutes each, past the tests'
    timeouts). Hermes (hermes_cli/venv_sync.py _prepare_borrowed_launch, #123238) syncs an
    environment of its own into ``<home>/installs`` for any home that borrows the
    checkout; one is prepared once per Hermes checkout under ~/.cache/agos-tests and
    linked in (Hermes records the environment's own path, so a copy elsewhere is refused;
    a walled home can't read through the link: test_wall keeps a root of its own)."""
    import fcntl
    import os
    import shutil
    import subprocess
    from pathlib import Path

    home = Path(home)
    launcher = shutil.which("hermes")
    agent = Path.home() / ".hermes" / "hermes-agent"
    if launcher is None or not agent.is_dir() or (home / "installs").exists():
        return
    git = shutil.which("git") or "git"
    head = subprocess.run(  # noqa: S603 - fixed argv
        [git, "-C", str(agent), "rev-parse", "--short=12", "HEAD"],
        capture_output=True, text=True, check=False,
    ).stdout.strip() or "unknown"  # fmt: skip
    cache = Path.home() / ".cache" / "agos-tests" / f"hermes-installs-{head}"
    cache.parent.mkdir(parents=True, exist_ok=True)
    with (cache.parent / f".{cache.name}.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not (cache / "installs").is_dir():
            shutil.rmtree(cache, ignore_errors=True)
            cache.mkdir()
            (cache / "config.yaml").write_text("{}\n")
            env = {
                **{k: v for k, v in os.environ.items() if not k.startswith(("HERMES", "_HERMES"))},
                "HERMES_HOME": str(cache),
                "HERMES_RUNTIME_DIR": str(Path.home() / ".hermes" / "tools"),
            }
            subprocess.run(  # noqa: S603 - fixed argv
                [launcher, "config", "get", "model.provider"],
                env=env, capture_output=True, timeout=900, check=True,
            )  # fmt: skip
        home.mkdir(parents=True, exist_ok=True)
        (home / "installs").symlink_to(cache / "installs", target_is_directory=True)


# Every throwaway Hermes home a test launches Hermes in shares ONE prepared Python
# environment instead of syncing its own (minutes per home: the cause of every "piece hung
# 30 min" / 180 s timeout in the chain). Hermes keeps that environment per data root in
# ``<root>/installs`` (hermes_cli/venv_sync.py _prepare_borrowed_launch); a link to one
# borrower's environment prepared once per Hermes checkout (hermes_ready_home's cache) is
# read as that environment. Never a link to ~/.hermes/installs itself: the home would then
# count as the owner and run its update tail under the machine's own install locks.
# Walled tests (kept_layout) keep their own: a Landlock wall can't follow a link out.
_WALLED_LAYOUTS = ("agos-wall-test", "agos-walled-run")


def _share_hermes_env(env: Any) -> None:
    if not env:
        return
    raw = env.get("HERMES_HOME") if hasattr(env, "get") else None
    if not raw:
        return
    home = Path(str(raw))
    root = home.parent.parent if home.parent.name == "profiles" else home
    real_home = Path.home().resolve()
    own = Path(str(env.get("HOME") or real_home)).resolve() == real_home
    try:
        if root.resolve() == (Path.home() / ".hermes").resolve():
            return  # the machine's own Hermes
        if own and root.resolve().is_relative_to((Path.home() / ".hermes").resolve()):
            # Inside ~/.hermes with the real HOME: Hermes uses the machine's environment.
            # A scratch HOME (test homes under TMPDIR) makes the root a new data root.
            return
        if root.resolve().is_relative_to((Path.home() / ".cache" / "agos-tests").resolve()) and (
            root.name.startswith("hermes-installs-")
        ):
            return  # the shared environment's own home
        if any(part in _WALLED_LAYOUTS for part in root.parts):
            return
        hermes_ready_home(root)
        if not own:
            # A scratch HOME's own ~/.hermes is prepared by the launcher too.
            hermes_ready_home(Path(str(env.get("HOME"))) / ".hermes")
    except OSError:
        return


@pytest.fixture(autouse=True, scope="session")
def _hermes_homes_share_the_env() -> Iterator[None]:
    import subprocess

    original = subprocess.Popen.__init__

    def init(self: Any, *args: Any, **kwargs: Any) -> None:
        env = kwargs.get("env")
        _share_hermes_env(os.environ if env is None else env)
        original(self, *args, **kwargs)

    subprocess.Popen.__init__ = init  # type: ignore[method-assign]
    try:
        yield
    finally:
        subprocess.Popen.__init__ = original  # type: ignore[method-assign]


def kept_layout(name: str) -> Any:
    """A test folder at one fixed place (~/.cache/<name>) for tests whose throwaway Hermes
    homes must sit outside ~/.hermes (a Landlock wall): Hermes syncs a Python environment
    per data root into ``<home>/installs`` (minutes; hermes_cli/venv_sync.py
    _prepare_borrowed_launch) and records its path, so those ``installs`` folders are kept
    in place between tests and everything else is wiped. One test at a time (a lock)."""
    import contextlib
    import fcntl
    from pathlib import Path

    @contextlib.contextmanager
    def _layout() -> Any:
        base = Path.home() / ".cache"
        base.mkdir(exist_ok=True)
        folder = base / name
        with (base / f".{name}.lock").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            _wipe_but_installs(folder)
            folder.mkdir(exist_ok=True)
            try:
                yield folder
            finally:
                _wipe_but_installs(folder)

    return _layout()


def _wipe_but_installs(folder: Any) -> None:
    import os
    import shutil
    from pathlib import Path

    folder = Path(folder)
    if not folder.is_dir():
        return
    aside = folder.parent / f".{folder.name}.kept"
    shutil.rmtree(aside, ignore_errors=True)
    kept: list[Path] = []
    for here, dirs, _files in os.walk(folder):
        rel = Path(here).relative_to(folder)
        if "installs" in dirs:
            target = aside / rel / "installs"
            target.parent.mkdir(parents=True, exist_ok=True)
            (Path(here) / "installs").rename(target)
            kept.append(rel / "installs")
            dirs.remove("installs")
        if len(rel.parts) >= 5:
            dirs.clear()
    shutil.rmtree(folder, ignore_errors=True)
    for rel in kept:
        (folder / rel).parent.mkdir(parents=True, exist_ok=True)
        (aside / rel).rename(folder / rel)
    shutil.rmtree(aside, ignore_errors=True)


def hermes_warm(home: Any) -> None:
    """Let Hermes sync a kept home's environment once (up to 15 min), before a test's own
    180 s calls: the first run of a fixed layout otherwise times out there."""
    import os
    import shutil
    import subprocess
    from pathlib import Path

    home = Path(home)
    launcher = shutil.which("hermes")
    if launcher is None or (home / "installs").is_dir():
        return
    home.mkdir(parents=True, exist_ok=True)
    env = {
        **{k: v for k, v in os.environ.items() if not k.startswith(("HERMES", "_HERMES"))},
        "HERMES_HOME": str(home),
        "HERMES_RUNTIME_DIR": str(Path.home() / ".hermes" / "tools"),
    }
    subprocess.run(  # noqa: S603 - the launcher and a fixed command
        [launcher, "config", "get", "model.provider"],
        env=env, capture_output=True, timeout=900, check=False,
    )  # fmt: skip


def hermes_write_profile_meta(home: Any, title: str) -> None:
    """Hermes's write_profile_meta(display_name=...) (hermes_cli/profiles.py): only
    that key changes, every other key is kept. The real one runs in Hermes's
    runtime (test_hermes_writes_live.py checks it with the installed Hermes)."""
    import yaml

    path = home / "profile.yaml"
    data = (yaml.safe_load(path.read_text()) if path.is_file() else {}) or {}
    if title.strip():
        data["display_name"] = title.strip()
    else:
        data.pop("display_name", None)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))


def hermes_write_description(home: Any, text: str) -> None:
    """Hermes's write_profile_meta(description=..., description_auto=False)."""
    import yaml

    path = home / "profile.yaml"
    data = (yaml.safe_load(path.read_text()) if path.is_file() else {}) or {}
    data["description"] = text.strip()
    data["description_auto"] = False
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))


@pytest.fixture(autouse=True)
def _hermes_writes_profile_meta(monkeypatch: pytest.MonkeyPatch) -> None:
    from agos_core.engine.hermes import HermesEngine

    monkeypatch.setattr(
        HermesEngine,
        "set_display_name",
        _on_hermes(
            "hermes profile meta",
            lambda self, home, title: hermes_write_profile_meta(home, title),
        ),
    )
    monkeypatch.setattr(
        HermesEngine,
        "set_description",
        _on_hermes(
            "hermes profile meta",
            lambda self, home, text: hermes_write_description(home, text),
        ),
    )
    monkeypatch.setattr(
        HermesEngine,
        "archive_sessions",
        _on_hermes(
            "hermes sessions archive",
            lambda self, home, ids, archived: hermes_archive(home, ids, archived),
        ),
    )
    monkeypatch.setattr(
        HermesEngine,
        "pairing_approved",
        _on_hermes(
            "Hermes runtime script AGOS-PAIRED",
            lambda self, home, platform, user: hermes_paired(home, platform, user),
        ),
    )
    # Hermes's skill tool and skill ledger (the real ones: test_skill_writes_live.py).
    import hermes_skills

    monkeypatch.setattr(
        HermesEngine,
        "skill_manage",
        _on_hermes(
            "Hermes runtime script AGOS-SKILL",
            lambda self, home, name, ops=None, *, delete=False, actor="user": (
                hermes_skills.skill_manage(home, name, ops, delete=delete, actor=actor)
            ),
        ),
    )
    monkeypatch.setattr(
        HermesEngine,
        "skill_rollback",
        _on_hermes(
            "Hermes runtime script AGOS-ROLLED",
            lambda self, home, skills, entries: hermes_skills.rollback(home, skills, entries),
        ),
    )
    monkeypatch.setattr(
        HermesEngine,
        "skill_check",
        lambda self, home, name, text, files=None: hermes_skills.check_new(home, name, text, files),
    )
    monkeypatch.setattr(
        HermesEngine,
        "skill_changes",
        _on_hermes(
            "Hermes runtime script AGOS-LEDGER",
            lambda self, home, limit=200: hermes_skills.changes(home, limit),
        ),
    )
    monkeypatch.setattr(
        HermesEngine,
        "skill_history",
        _on_hermes(
            "Hermes runtime script AGOS-HISTORY",
            lambda self, home, folder, skill, known: hermes_skills.history(
                home, folder, skill, known
            ),
        ),
    )
    monkeypatch.setattr(
        HermesEngine,
        "gateway_status",
        _on_hermes(
            "Hermes runtime script AGOS-GW",
            lambda self, home, fresh=False, kept=False: hermes_gateway_status(home),
        ),
    )


def hermes_gateway_status(home: Any) -> dict[str, Any]:
    """Hermes's gateway verdict (gateway/status.py get_running_pid,
    runtime_status_pid_is_live, runtime_status_is_stale) for a test's
    gateway_state.json: its pid live (not a zombie) and, with an updated_at, not
    older than 120 s. The real one runs in Hermes's runtime
    (test_gateway_liveness.py checks it with the installed Hermes)."""
    import json
    from datetime import UTC, datetime
    from pathlib import Path

    try:
        record = json.loads((home / "gateway_state.json").read_text())
    except (OSError, ValueError):
        record = None
    if not isinstance(record, dict):
        return {"pid": None, "record": None, "live": False, "stale": True}
    pid = int(record.get("pid") or 0)
    try:
        live = pid > 0 and "\nState:\tZ" not in Path(f"/proc/{pid}/status").read_text()
    except OSError:
        live = False
    stale = False
    stamp = str(record.get("updated_at") or "")
    if stamp:
        try:
            when = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
            when = when if when.tzinfo else when.replace(tzinfo=UTC)
            stale = (datetime.now(UTC) - when).total_seconds() > 120
        except ValueError:
            stale = True
    return {"pid": pid if live else None, "record": record, "live": live, "stale": stale}


def hermes_paired(home: Any, platform: str, user: str) -> bool:
    """Hermes's PairingStore.is_approved (gateway/pairing.py): the user is in the
    home's approved file (the real one runs in Hermes's runtime:
    test_hermes_writes_live)."""
    import json

    for folder in (home / "pairing", home / "platforms" / "pairing"):
        try:
            if str(user) in json.loads((folder / f"{platform}-approved.json").read_text()):
                return True
        except (OSError, ValueError, TypeError):
            continue
    return False


def hermes_archive(home: Any, ids: list[str], archived: bool) -> list[str]:
    """Hermes's SessionDB.set_session_archived (hermes_state_sessions.py): the flag on
    each session (the real one runs in Hermes's runtime: test_hermes_writes_live)."""
    import sqlite3

    path = home / "state.db"
    if not path.is_file():
        return []
    with contextlib.closing(sqlite3.connect(path)) as db:
        done = [
            i
            for i in ids
            if db.execute(
                "UPDATE sessions SET archived = ?, auto_archived = 0 WHERE id = ?",
                (int(archived), i),
            ).rowcount
        ]
        db.commit()
    return done


def hermes_save_credentials(home: Any, values: dict[str, str], drop: list[str]) -> None:
    """Hermes's credential_lifecycle save/remove, as far as `.env` goes. The real one
    runs in Hermes's runtime (test_hermes_writes_live.py checks it, with the pool in
    auth.json)."""
    from agos_core.engine import envfile

    names = set(values) | set(drop)
    envfile.rewrite(
        home / ".env",
        tuple(f"{n}=" for n in sorted(names)),
        [f"{k}={v}" for k, v in values.items()],
    )


@pytest.fixture(autouse=True)
def _hermes_saves_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    from agos_core.engine.hermes import HermesEngine

    monkeypatch.setattr(
        HermesEngine,
        "save_credentials",
        _on_hermes(
            "hermes credentials",
            lambda self, home, values, drop: hermes_save_credentials(home, values, drop),
        ),
    )


def _no_runtime(self: Any, home: Any, script: str, **kw: Any) -> str:
    from agos_core.engine.hermes import EngineError

    raise EngineError("no Hermes runtime in tests")


@pytest.fixture(autouse=True)
def _config_writes_one_by_one(monkeypatch: pytest.MonkeyPatch) -> None:
    """engine.config_writes runs Hermes's writer in its runtime (the real one:
    test_config_writes_live.py); a test's fake runner has none, so its writes go
    one CLI each, as when the runtime can't run. hermes_config_batch is the
    stand-in for tests that count Hermes starts."""
    from agos_core.engine.hermes import HermesEngine

    monkeypatch.setattr(HermesEngine, "_config_batch", _on_hermes("AGOS-SETS", _no_runtime))


def hermes_config_batch(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """The one Hermes process of engine.config_writes on a test's fake runner: each
    command runs as the fake's own `config set/unset` (its refusals too), a value
    the home already holds is skipped, and the runner sees ONE start,
    `[hermes, "AGOS-SETS", home, *keys written]`. Returns the list of those starts."""
    import ast
    import json

    from agos_core.engine import config_file
    from agos_core.engine.hermes import EngineError, HermesEngine

    starts: list[list[str]] = []

    def held(home: Any, key: str, value: str) -> bool:
        if key.isupper():
            return config_file.read_env(home).get(key) == value
        try:
            want: Any = json.loads(value)
        except ValueError:
            want = value
        have = config_file.get(config_file.read(home), key)
        return have is not None and json.dumps(have) == json.dumps(want)

    def run(self: Any, home: Any, script: str, **kw: Any) -> str:
        line = next(ln for ln in script.splitlines() if ln.startswith("job = json.loads("))
        ops = json.loads(ast.literal_eval(line[len("job = json.loads(") : -1]))
        calls = getattr(self.runner, "calls", None)
        mark = len(calls) if calls is not None else 0
        done: list[list[Any]] = []
        failed = None
        for op in ops:
            if op[0] == "set" and held(home, op[1], op[2]):
                done.append([op[1], False])
                continue
            force = ["--force"] if op[0] == "set" and op[3] else []
            argv = (
                ["config", "set", *force, *op[1:3]]
                if op[0] == "set"
                else ["config", "unset", op[1]]
            )
            try:
                self.runner.run(
                    [self.settings.hermes_bin, *argv],
                    timeout=60,
                    env={**self._env(), **kw.get("extra", {}), "HERMES_HOME": str(home)},
                )
            except EngineError as error:
                failed = {"key": op[1], "code": 1, "said": str(error)}
                break
            done.append([op[1], True])
        if calls is not None:
            del calls[mark:]
            calls.append([self.settings.hermes_bin, "AGOS-SETS", str(home)])
        starts.append([str(home), *(k for k, wrote in done if wrote)])
        return json.dumps({"done": done, "failed": failed})

    monkeypatch.setattr(HermesEngine, "_config_batch", _on_hermes("AGOS-SETS", run))
    return starts


def hermes_as_read(managed_home: Any, homes: list[Any]) -> dict[str, dict[str, Any]]:
    """Hermes's apply_managed_overlay, as far as the tests' plain configs go (each
    home's config.yaml, the managed one on top leaf by leaf, None never replacing a
    mapping). The real one runs in Hermes's runtime (test_hermes_writes_live.py)."""
    from agos_core.engine import config_file

    def merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
        out = dict(base)
        for key, value in over.items():
            if isinstance(out.get(key), dict) and isinstance(value, dict):
                out[key] = merge(out[key], value)
            elif not (isinstance(out.get(key), dict) and value is None):
                out[key] = value
        return out

    managed = config_file.read(managed_home)
    return {str(home): merge(config_file.read(home), managed) for home in homes}


@pytest.fixture(autouse=True)
def _hermes_reads_with_its_managed_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    from agos_core.engine.hermes import HermesEngine

    monkeypatch.setattr(
        HermesEngine,
        "as_hermes_reads",
        _on_hermes(
            "Hermes runtime script AGOS-ASREAD",
            lambda self, homes: hermes_as_read(self.settings.managed_home, homes),
        ),
    )
    monkeypatch.setattr(
        HermesEngine,
        "hermes_secrets",
        _on_hermes(
            "Hermes runtime script AGOS-ASREAD",
            lambda self, homes: hermes_secret_paths(self.settings.managed_home, homes),
        ),
    )
    monkeypatch.setattr(
        HermesEngine,
        "hermes_logins",
        _on_hermes(
            "Hermes runtime script AGOS-LOGINS",
            lambda self, home, status=False: hermes_logins_read(home, status),
        ),
    )
    monkeypatch.setattr(
        HermesEngine,
        "hermes_lanes",
        _on_hermes(
            "Hermes runtime script AGOS-LANES",
            lambda self, root, homes: hermes_lanes_read(root, homes),
        ),
    )


def hermes_lanes_read(root: Any, homes: list[Any]) -> dict[str, list[dict[str, Any]]]:
    """engine.hermes_lanes, as far as the tests' plain files go: state.db's
    gateway_routing rows of the gateway store's scope, each entry's origin. The
    real one runs Hermes's own SessionDB / SessionEntry (test_hermes_writes_live.py)."""
    import json
    import sqlite3

    out: dict[str, list[dict[str, Any]]] = {}
    for home in homes:
        lanes: list[dict[str, Any]] = []
        state = home / "state.db"
        if state.is_file():
            scopes = {str((root / "sessions").resolve()), str((home / "sessions").resolve())}
            con = sqlite3.connect(f"file:{state}?mode=ro", uri=True)
            try:
                rows = con.execute("SELECT scope, session_key, entry_json FROM gateway_routing")
                for scope, key, raw in rows.fetchall():
                    if scope not in scopes:
                        continue
                    entry = json.loads(raw)
                    origin = entry.get("origin") or {}
                    lanes.append(
                        {
                            "key": key,
                            "yolo": entry.get("yolo") is True,
                            "updated_at": str(entry.get("updated_at") or ""),
                            "platform": str(origin.get("platform") or ""),
                            "chat_id": str(origin.get("chat_id") or ""),
                            "thread_id": str(origin.get("thread_id") or ""),
                        }
                    )
            except sqlite3.Error:
                pass
            finally:
                con.close()
        out[str(home)] = lanes
    return out


def _hermes_borrowed() -> Any:
    """Hermes's is_borrowed_credential_source, from the installed Hermes's source
    (agent/credential_persistence.py) by AST."""
    import ast

    found = getattr(_hermes_borrowed, "found", None)
    if found is not None:
        return found
    path = Path.home() / ".hermes/hermes-agent/agent/credential_persistence.py"
    names = {"_PERSISTABLE_PROVIDER_SOURCES", "is_borrowed_credential_source"}
    keep: list[ast.stmt] = []
    for node in ast.parse(path.read_text()).body:
        if (isinstance(node, ast.FunctionDef) and node.name in names) or (
            isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id in names for t in node.targets)
        ):
            keep.append(node)
    space: dict[str, Any] = {"Any": Any}
    module = ast.Module(body=keep, type_ignores=[])
    exec(compile(module, str(path), "exec"), space)  # noqa: S102 - Hermes's code
    _hermes_borrowed.found = space["is_borrowed_credential_source"]  # type: ignore[attr-defined]
    return space["is_borrowed_credential_source"]


# Hermes's registry auth type of the providers the tests use (PROVIDER_REGISTRY).
_AUTH_TYPES = {"openai-codex": "oauth_device_code", "xai-oauth": "oauth_device_code"}


def hermes_logins_read(home: Any, status: bool = False) -> dict[str, Any]:
    """engine.hermes_logins, as far as the tests' plain files go: the model's
    provider, the persisted pool with Hermes's borrowed rule, Hermes's saved
    sign-ins and (status) whether the provider has a pool entry or its key. The
    real one runs Hermes's own functions (test_hermes_logins_live.py)."""
    import json

    from agos_core.engine import config_file

    borrowed = _hermes_borrowed()
    try:
        data = json.loads((home / "auth.json").read_text())
    except (OSError, ValueError):
        data = {}
    data = data if isinstance(data, dict) else {}
    model = config_file.read(home).get("model")
    provider = str((model.get("provider") if isinstance(model, dict) else "") or "")
    pool = []
    for slug, entries in sorted((data.get("credential_pool") or {}).items()):
        for e in entries if isinstance(entries, list) else []:
            if not isinstance(e, dict):
                continue
            source = str(e.get("source") or "")
            pool.append(
                {
                    "provider": slug,
                    "label": str(e.get("label") or ""),
                    "source": source,
                    "auth_type": str(e.get("auth_type") or ""),
                    "borrowed": borrowed(source, slug) and not source.startswith("env:"),
                    "last_status": e.get("last_status") or "",
                    "last_status_at": e.get("last_status_at") or "",
                    "last_error_message": str(e.get("last_error_message") or ""),
                    "last_error_reason": str(e.get("last_error_reason") or ""),
                }
            )
    states = sorted(k for k, v in (data.get("providers") or {}).items() if v)
    out: dict[str, Any] = {
        "provider": provider,
        "auth_type": _AUTH_TYPES.get(provider, "api_key" if provider else ""),
        "pool": pool,
        "signed_in_state": states,
    }
    if status and provider:
        env = config_file.read_env(home)
        key = provider.upper().replace("-", "_") + "_API_KEY"
        out["logged_in"] = bool(
            [e for e in pool if e["provider"] == provider] or env.get(key) or provider in states
        )
    return out


def _hermes_masker() -> Any:
    """Hermes's own redact_config_value and the key rules it uses, taken from the
    installed Hermes's source (hermes_cli/config.py) by AST: the tests mask with
    Hermes's code, not with an AGOS copy. The real run is in
    test_hermes_writes_live.py."""
    import ast
    import re

    found = getattr(_hermes_masker, "found", None)
    if found is not None:
        return found
    source = (Path.home() / ".hermes/hermes-agent/hermes_cli/config.py").read_text()
    names = {
        "_ENV_CONFIG_KEYS",
        "_SECRET_CONFIG_KEYS",
        "_SECRET_CONFIG_KEY_SUFFIXES",
        "_NON_SECRET_KEY_SUFFIXES",
        "_ENV_PLACEHOLDER_RE",
        "_is_env_config_key",
        "_is_secret_config_key",
        "redact_config_value",
    }
    keep: list[ast.stmt] = []
    for node in ast.parse(source).body:
        if isinstance(node, ast.FunctionDef) and node.name in names:
            # Its `from agent.redact import mask_secret`: given below instead.
            node.body = [
                n
                for n in node.body
                if not (isinstance(n, ast.ImportFrom) and n.module == "agent.redact")
            ]
            keep.append(node)
        elif isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id in names for t in node.targets
        ):
            keep.append(node)
    module = ast.Module(body=keep, type_ignores=[])
    space: dict[str, Any] = {
        "re": re,
        "Any": Any,
        # agent/redact.py mask_secret's shape (the masked text itself never matters:
        # AGOS shows its own MASK wherever Hermes changed the value).
        "mask_secret": lambda v, **_k: "***" if len(v) < 12 else f"{v[:4]}...{v[-4:]}",
    }
    exec(compile(module, "hermes_cli/config.py", "exec"), space)  # noqa: S102 - Hermes's code
    _hermes_masker.found = space["redact_config_value"]  # type: ignore[attr-defined]
    return space["redact_config_value"]


def hermes_secret_paths(managed_home: Any, homes: list[Any]) -> dict[str, list[list[Any]]]:
    """engine.hermes_secrets: where Hermes's redact_config_value changes a value."""
    from agos_core.engine import config_file

    redact = _hermes_masker()

    def hidden(given: Any, shown: Any, path: list[Any], found: list[list[Any]]) -> None:
        if isinstance(given, dict) and isinstance(shown, dict):
            for k, v in given.items():
                hidden(v, shown.get(k), [*path, str(k)], found)
        elif isinstance(given, list) and isinstance(shown, list):
            for i, v in enumerate(given):
                hidden(v, shown[i] if i < len(shown) else None, [*path, i], found)
        elif given != shown and path not in found:
            found.append(path)

    merged = hermes_as_read(managed_home, homes)
    out: dict[str, list[list[Any]]] = {}
    for home in homes:
        found: list[list[Any]] = []
        raw = config_file.read(home)
        hidden(raw, redact(raw), [], found)
        hidden(merged[str(home)], redact(merged[str(home)]), [], found)
        out[str(home)] = found
    return out


# The fake Telegram Bot API a stand-in gateway sends to (test_channels sets it).
FAKE_TELEGRAM: dict[str, Any] = {"url": None}


def _bot_call(core: Any, workspace_id: str, method: str, **params: Any) -> Any:
    import httpx

    from agos_core.actions import hermes_channel

    token = hermes_channel.bot_token(core, workspace_id)
    r = httpx.post(f"{FAKE_TELEGRAM['url']}/bot{token}/{method}", json=params, timeout=10)
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(str(data.get("description") or r.status_code))
    return data.get("result")


@pytest.fixture(autouse=True)
def _a_gateway_sends_to_the_fake_telegram(monkeypatch: pytest.MonkeyPatch) -> None:
    """Live, each workspace's Hermes gateway sends AGOS's outbox on its own bot (the
    agos-guard plugin reads `hermes_outbox`; that path has its own test). Here a
    stand-in gateway sends it through the fake Telegram the tests look at."""
    from agos_core.actions import channels
    from agos_core.actions.services.channel import bot_addresses

    real_round = channels.send_round

    def send_round(core):  # type: ignore[no-untyped-def]
        real_round(core)
        if not FAKE_TELEGRAM["url"]:
            return 0
        sent = 0
        for r in core.db.execute(
            "SELECT DISTINCT workspace_id FROM channel_connections WHERE agos_bot_on(workspace_id)"
        ).fetchall():
            ws = str(r["workspace_id"] or "")
            if not ws:
                continue
            got = channels.hermes_outbox(core, ws)
            for item in got["send"]:
                chat, _, topic = item["address"].partition(":")
                params: dict[str, Any] = {"chat_id": chat, "text": item["text"]}
                if topic and topic != "0":
                    params["message_thread_id"] = int(topic)
                if item["buttons"]:
                    params["reply_markup"] = {
                        "inline_keyboard": [
                            [
                                {"text": label, "callback_data": data[:64]}
                                for label, data in item["buttons"]
                            ]
                        ]
                    }
                try:
                    message_id = str(_bot_call(core, ws, "sendMessage", **params)["message_id"])
                    error = None
                except RuntimeError as failed:
                    message_id, error = "", str(failed)
                channels.hermes_outbox_done(core, ws, item["id"], "send", message_id, error)
                sent += 0 if error else 1
            for item in got["close"]:
                with contextlib.suppress(RuntimeError):
                    _bot_call(
                        core,
                        ws,
                        "editMessageText",
                        chat_id=item["address"].partition(":")[0],
                        message_id=int(item["messageId"]),
                        text=item["text"],
                        reply_markup={"inline_keyboard": []},
                    )
                channels.hermes_outbox_done(core, ws, item["id"], "close", None, None)
        return sent

    send_round.real = real_round  # type: ignore[attr-defined]
    monkeypatch.setattr(channels, "send_round", send_round)

    def make_topic(workspace_id: str, chat: str, name: str) -> str:
        # The workspace's Hermes gateway makes it with its bot (here: the fake one).
        core = core_of[0]
        assert core is not None
        topic = _bot_call(core, workspace_id, "createForumTopic", chat_id=chat, name=name[:128])
        return f"{chat}:{topic['message_thread_id']}"

    core_of: list[Any] = [None]
    real_add = channels.add_address

    def add_address(core: Any, workspace_id: str, chat_id: int, **kw: Any) -> int:
        core_of[0] = core
        return real_add(core, workspace_id, chat_id, **kw)

    make_topic.real = channels.make_topic  # type: ignore[attr-defined]
    # The facade (hermes_channel's callers) and where add_address/link_cofounder_chat
    # look them up (the channel service's bot_addresses module).
    for mod in (channels, bot_addresses):
        monkeypatch.setattr(mod, "make_topic", make_topic)
        monkeypatch.setattr(mod, "add_address", add_address)
