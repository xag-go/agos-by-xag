# ruff: noqa: S105, S310, S603, SIM105 - a test harness on throwaway local services
"""Real end-to-end run: AGOS core + real Hermes gateways on throwaway roots (ADR 0020).

    python tests/e2e/rooms_e2e.py up|setup|run|down

Everything lives under $AGOS_E2E (default ~/agos-roots-test/e2e):
a fake "shared" Hermes home (General Settings' .env), AGOS's data, the workspaces'
roots, logs. Hermes runs with HERMES_RUNTIME_DIR = the install's own runtime (never
a runtime of its own), the model is fake_llm.py (no account), Telegram is
fake_bot_api.py. Docker is not used (AGOS_DOCKER_BIN=/bin/true; the agents' terminal
runs locally in these throwaway roots).
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

# Run from a Hermes delegate_task child, the shell carries Hermes's child marker. The
# test gateways would inherit it and refuse every Kanban change (Hermes's
# agent/delegation_context.py is_delegated_child_process_context). A real gateway
# (systemd) never has it.
os.environ.pop("HERMES_DELEGATED_CHILD_CONTEXT", None)

E = Path(os.environ.get("AGOS_E2E") or Path.home() / "agos-roots-test" / "e2e")
CORE_DIR = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
RUNTIME = os.environ.get("AGOS_E2E_RUNTIME") or str(Path.home() / ".hermes" / "tools")
# AGOS_E2E_HERMES runs the whole check on another Hermes (a newer checkout with its own
# venv, docs/hermes-upgrade.md); AGOS_E2E_RUNTIME is then that install's runtime.
HERMES = (
    os.environ.get("AGOS_E2E_HERMES")
    or shutil.which("hermes")
    or str(Path.home() / ".local" / "bin" / "hermes")
)
# Another worktree's run may hold the default ports: AGOS_E2E_PORTS="core,llm,telegram".
CORE_PORT, LLM_PORT, TG_PORT = (
    int(p) for p in (os.environ.get("AGOS_E2E_PORTS") or "18766,18991,18993").split(",")
)
TOKEN = "123456789:AAE2E-fake-token-for-tests-only-000"
STATE = E / "state.json"
GROUP_CHAT = "-1000009"


def say(*a: Any) -> None:
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def state() -> dict[str, Any]:
    return json.loads(STATE.read_text()) if STATE.is_file() else {}


def save(**kv: Any) -> None:
    STATE.write_text(json.dumps({**state(), **kv}, indent=1))


def api(method: str, path: str, body: Any = None, timeout: float = 600) -> Any:
    token = (E / "data" / "system" / "internal.token").read_text().strip()
    req = urllib.request.Request(
        f"http://127.0.0.1:{CORE_PORT}{path}",
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"content-type": "application/json", "x-agos-internal": token},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"{method} {path}: {error.code} {error.read()[:500]!r}") from None


def tg(path: str, body: Any = None) -> Any:
    req = urllib.request.Request(
        f"http://127.0.0.1:{TG_PORT}{path}",
        method="POST" if body is not None else "GET",
        data=json.dumps(body).encode() if body is not None else None,
        headers={"content-type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def hermes_env(home: Path) -> dict[str, str]:
    return {
        **os.environ,
        "HERMES_HOME": str(home),
        "HERMES_RUNTIME_DIR": RUNTIME,
        # Hermes's managed scope, as AGOS gives it (beside the roots).
        "HERMES_MANAGED_DIR": str(E / "hermes-managed"),
        "HOME": str(E / "home"),
    }


def hset(home: Path, key: str, value: str) -> None:
    """Hermes's `config set` under the same per-home lock AGOS takes (two writers on
    one config.yaml would otherwise lose a write: engine/hermes.py home_write_lock)."""
    import fcntl

    with (home / ".agos-config.lock").open("a") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        subprocess.run(
            [HERMES, "config", "set", key, value],
            env=hermes_env(home),
            check=True,
            capture_output=True,
            timeout=120,
        )


def gone(pid: int | str) -> bool:
    """The process ended (a zombie counts: in these runs a gateway is agos-core's
    child, reaped whenever agos-core next starts a process)."""
    try:
        return "\nState:\tZ" in Path(f"/proc/{pid}/status").read_text()
    except OSError:
        return True


def service_restart(home: Path) -> None:
    """What Hermes's own systemd service does when its gateway dies (Restart=always).
    These throwaway roots run without systemd (supervisor "spawn"), and AGOS no
    longer restarts gateways itself, so the rig plays the service's part."""
    tmp = E / "home" / ".agos-tmp" / f"svc-{home.name[-12:]}"
    tmp.mkdir(parents=True, exist_ok=True)
    spawn(
        f"gateway-{home.name}",
        [HERMES, "gateway", "run", "--replace"],
        {**hermes_env(home), "TMPDIR": str(tmp)},
    )


def restart_gateway(home: Path) -> None:
    """End a home's gateway and wait until it runs again, as Hermes's service brings
    it back (Hermes reads a tool's backend and the model only when it starts)."""
    state_file = home / "gateway_state.json"

    def current() -> dict[str, Any]:
        try:
            return dict(json.loads(state_file.read_text()))
        except (OSError, ValueError):
            return {}

    pid = current().get("pid")
    if pid and Path(f"/proc/{pid}").exists():
        os.kill(int(pid), 15)
        wait("gateway gone", lambda: gone(pid), 60)
    service_restart(home)
    wait(
        "gateway back",
        lambda: (
            current().get("pid") not in (None, pid)
            and current().get("gateway_state") == "running"
            and not gone(current().get("pid") or 0)
        ),
        240,
        3,
    )


def spawn(name: str, argv: list[str], env: dict[str, str] | None = None) -> int:
    log = (E / "logs" / f"{name}.log").open("ab")
    p = subprocess.Popen(
        argv,
        stdout=log,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        env=env or os.environ.copy(),
        start_new_session=True,
    )
    pids = state().get("pids", {})
    pids[name] = p.pid
    save(pids=pids)
    return p.pid


def wait(what: str, check: Any, timeout: float = 120, every: float = 1.0) -> Any:
    deadline = time.monotonic() + timeout
    last: Any = None
    while time.monotonic() < deadline:
        try:
            last = check()
        except Exception as error:  # noqa: BLE001 - polled again
            last = error
        if last and not isinstance(last, Exception):
            return last
        time.sleep(every)
    raise SystemExit(f"TIMEOUT waiting for {what} (last: {last!r})")


# ---- up: fakes + AGOS core ------------------------------------------------------------


def core_env() -> dict[str, str]:
    """The test core's environment. AGOS_CORE_URL is always this run's port: the
    default (8766) is where a real AGOS may listen on the same machine."""
    env = {
        **os.environ,
        "AGOS_ENGINE": "hermes",
        "AGOS_DATA_DIR": str(E / "data"),
        "AGOS_HERMES_BIN": HERMES,
        "AGOS_DOCKER_BIN": "/bin/true",
        "AGOS_HERMES_USER_HOME": str(E / "home"),
        "AGOS_HERMES_ROOTS": str(E / "roots"),
        "AGOS_HERMES_RUNTIME_DIR": RUNTIME,
        "AGOS_HERMES_GATEWAY_SUPERVISOR": "spawn",
        "AGOS_CORE_URL": f"http://127.0.0.1:{CORE_PORT}",
        # Webhook ports after this run's own (another run's gateways take 8650 up).
        "AGOS_WEBHOOK_FIRST_PORT": str(max(CORE_PORT, LLM_PORT, TG_PORT) + 1),
    }
    env.pop("PYTHONPATH", None)
    return env


def warm_shared_home() -> None:
    """The throwaway HOME's Hermes home sets itself up once (its dependency env),
    before AGOS runs several Hermes commands at once."""
    home = E / "home" / ".hermes"
    home.mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith(("HERMES_HOME", "AGOS_"))}
    env |= {"HOME": str(E / "home"), "HERMES_RUNTIME_DIR": RUNTIME}
    subprocess.run(
        [HERMES, "config", "set", "display.compact", "false"],
        env=env,
        check=True,
        capture_output=True,
        timeout=900,
        cwd=str(home),
    )


def start_core() -> None:
    """agos-core with its own INFO log (what AGOS does is visible in logs/core.log)."""
    code = (
        "import logging, uvicorn\n"
        "logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)s %(levelname)s %(message)s')\n"
        f"uvicorn.run('agos_core.api.app:create_app', factory=True, host='127.0.0.1', port={CORE_PORT})\n"
    )
    if not (E / "home" / ".hermes" / "config.yaml").is_file():
        warm_shared_home()
    spawn("core", [sys.executable, "-c", code], core_env())


def bridges_point_here() -> list[str]:
    """Every agos-bridge.json of this run names this run's core (never another AGOS)."""
    want = f"http://127.0.0.1:{CORE_PORT}"
    return [
        str(f)
        for f in E.rglob("agos-bridge.json")
        if "installs" not in f.parts and json.loads(f.read_text()).get("core") != want
    ]


def up() -> None:
    if STATE.exists():
        raise SystemExit(f"{STATE} exists: run `down` first")
    import socket

    for port in (CORE_PORT, LLM_PORT, TG_PORT):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                raise SystemExit(f"port {port} is in use: a previous run is still up")
    for d in ("home/.hermes", "data", "roots", "logs"):
        (E / d).mkdir(parents=True, exist_ok=True)
    # General Settings' keys, as the shared home keeps them (AGOS's General Settings
    # writes there): every root must get them.
    (E / "home" / ".hermes" / ".env").write_text("GEMINI_API_KEY=e2e-general-gemini-1\n")
    py = sys.executable
    spawn("llm", [py, str(HERE / "fake_llm.py"), str(LLM_PORT), str(E / "logs" / "llm.jsonl")])
    spawn(
        "telegram", [py, str(HERE / "fake_bot_api.py"), str(TG_PORT), str(E / "logs" / "tg.jsonl")]
    )
    # The shared install's launcher as it is now: the run must leave it so (rooms_e2e_run 12).
    launcher = Path.home() / ".hermes" / "hermes-agent" / ".hermes" / "bin"
    save(
        launcher={
            str(launcher / name): subprocess.run(
                ["md5sum", str(launcher / name)],  # noqa: S607 - the system's md5sum
                capture_output=True,
                text=True,
            ).stdout[:12]
            for name in ("hermes", "hermes-acp")
        }
    )
    start_core()
    wait("AGOS core", lambda: api("GET", "/workspaces") is not None, 60)
    say("up: core, fake LLM, fake Telegram")


# ---- setup: 2 workspaces, each a Co-Founder + 2 members, a group, Telegram ---------------

MODEL = {"provider": "claude", "mode": "cli", "model": "claude-sonnet-5", "effort": "medium"}


def root_of(ws: str) -> Path:
    return E / "roots" / f"agos-{ws}"


def fake_model(home: Path) -> None:
    """The fake model (a named provider Hermes resolves, which AGOS's own model
    mirroring keeps) and a local terminal (no docker here) for one home."""
    for k, v in (
        ("providers.fakellm.base_url", f"http://127.0.0.1:{LLM_PORT}/v1"),
        ("providers.fakellm.api_key", "fake"),
        ("providers.fakellm.api_mode", "chat_completions"),
        ("model.provider", "fakellm"),
        ("model.default", "fake-model"),
        ("terminal.backend", "local"),
        ("terminal.cwd", str(E / "data")),
        ("platforms.telegram.extra.base_url", f"http://127.0.0.1:{TG_PORT}/bot"),
        ("platforms.telegram.extra.base_file_url", f"http://127.0.0.1:{TG_PORT}/file/bot"),
    ):
        hset(home, k, v)
    # Read back: the fake provider's address is there and no other route is left.
    import yaml

    cfg = yaml.safe_load((home / "config.yaml").read_text()) or {}
    assert (cfg.get("providers") or {}).get("fakellm", {}).get("base_url"), cfg.get("providers")
    assert not (cfg.get("model") or {}).get("base_url"), cfg.get("model")


def access(ws: str, name: str, chat_access: str) -> None:
    """The workspace's Settings switch: Full access / Ask me first. Settings also
    carries the model, which AGOS writes into the Co-Founder's Hermes: the fake model is
    put back after (the real one would need an account)."""
    api(
        "PUT",
        f"/workspaces/{ws}",
        {"name": name, "description": "", "defaultModel": MODEL, "chatAccess": chat_access},
    )
    if (root_of(ws) / "config.yaml").is_file() and state().get(f"group_{ws}"):
        fake_model(root_of(ws))


def setup() -> None:
    made: dict[str, str] = dict(state().get("ws") or {})
    for name in ("Alpha", "Bravo"):
        if name in made:
            continue
        ws = api("POST", "/workspaces", {"name": name, "defaultModel": MODEL})["id"]
        made[name] = ws
        say("workspace", ws)
        # Ask me first (the approval steps); a new workspace starts on Full access.
        access(ws, name, "ask")
        for agent, title in (("writer", "Writer"), ("editor", "Editor")):
            api(
                "POST",
                f"/workspaces/{ws}/agents",
                {
                    "name": agent,
                    "title": title,
                    "definition": {"instructions": f"You are {title}."},
                },
            )
        root = root_of(ws)
        wait(
            f"{ws} root + members",
            lambda r=root: all(
                (h / "agos-bridge.json").is_file()
                for h in (r, r / "profiles" / "a-writer", r / "profiles" / "a-editor")
            ),
            300,
            2,
        )
    save(ws=made)
    for ws in made.values():
        if state().get(f"group_{ws}"):
            continue
        root = root_of(ws)
        for home in (root, root / "profiles" / "a-writer", root / "profiles" / "a-editor"):
            fake_model(home)
        group = api(
            "POST",
            f"/workspaces/{ws}/workers/groups",
            {"title": "Launch", "members": ["writer", "editor"]},
        )["id"]
        save(**{f"group_{ws}": group})
    # Telegram on Alpha only (its group's topic mirrors the room).
    a = made["Alpha"]
    conn = api(
        "POST",
        "/channels",
        {
            "kind": "telegram",
            "name": "e2e bot",
            "secret": TOKEN,
            "allowed": ["4242"],
            "workspaceId": a,
        },
    )
    save(conn=conn.get("id") if isinstance(conn, dict) else conn)
    say("setup done", made)


def down() -> None:
    """Every throwaway process of this run (only those whose HERMES_HOME or argv is
    under $AGOS_E2E, or that the run started), then the folder."""
    pids = set(state().get("pids", {}).values())
    mine = {os.getpid()}
    parent = os.getppid()
    while parent > 1:  # never this command's own shell and its parents
        mine.add(parent)
        try:
            parent = int(
                (Path("/proc") / str(parent) / "stat").read_text().rsplit(")", 1)[1].split()[1]
            )
        except (OSError, ValueError, IndexError):
            break
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit() or int(proc.name) in mine:
            continue
        try:
            argv = (proc / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
            env = (proc / "environ").read_bytes().decode(errors="replace")
        except OSError:
            continue
        if f"HERMES_HOME={E}/" in env or f"HERMES_HOME={E}\0" in env or str(E) in argv:
            pids.add(int(proc.name))
    own_group = os.getpgid(0)
    for pid in pids - mine:
        try:
            group = os.getpgid(pid)
            if group != own_group:
                os.killpg(group, signal.SIGTERM)
            else:
                os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
    time.sleep(3)
    for pid in pids - mine:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if "--keep" not in sys.argv:
        shutil.rmtree(E, ignore_errors=True)
    say("down:", len(pids), "process(es) ended", "" if "--keep" in sys.argv else f"; {E} removed")


def main() -> None:
    step = sys.argv[1]
    if step == "setup-run":
        sys.path.insert(0, str(HERE))
        from rooms_e2e_run import run

        setup()
        run()
        return
    if step in ("run", "all"):
        sys.path.insert(0, str(HERE))
        from rooms_e2e_run import run

        if step == "all":
            up()
            setup()
        run()
        return
    {"up": up, "setup": setup, "down": down}[step]()


if __name__ == "__main__":
    main()
