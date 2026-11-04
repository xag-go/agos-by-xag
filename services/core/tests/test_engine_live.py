"""Live isolation tests: real Hermes profiles, real Docker sandboxes, driven
through AGOS's own API. Slow; run with AGOS_TEST_HERMES=1 (needs `hermes` and a
running Docker). Every profile it creates uses a throwaway prefix and is
removed at the end.

What the brief requires (§4, checklist) and how it is checked here:
- workspace A can't reach B's files                  → commands inside A's sandbox
- added folders are read-only by default             → write attempt fails
- removal is immediate                               → folder gone from a new sandbox
- no secret in the sandbox                           → env has no key/token
- no Docker socket, no host home                     → paths absent in the sandbox
- AGOS's API keys differ per workspace, loopback only → .env + a wrong-key call
"""

import json
import os
import secrets
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agos_core.api.app import create_app
from agos_core.config import DEFAULT_SANDBOX_IMAGE, EngineConfig, Settings
from agos_core.engine.hermes import child_env

pytestmark = pytest.mark.skipif(
    os.environ.get("AGOS_TEST_HERMES") != "1",
    reason="live Hermes + Docker test (AGOS_TEST_HERMES=1)",
)

MODEL = {"provider": "claude", "mode": "cli", "model": "claude-sonnet-5", "effort": "medium"}
HERMES = shutil.which("hermes") or ""
DOCKER = shutil.which("docker") or ""
HERMES_HOME = Path.home() / ".hermes"


def sandbox_exec(profile_home: Path, command: str) -> dict[str, object]:
    """Runs one command through Hermes's own terminal tool, in the profile's sandbox —
    the exact path an agent's command takes. No model involved."""
    code = (
        "import json,sys\n"
        "from tools.terminal_tool import terminal_tool\n"
        "print('AGOSJSON'+terminal_tool(command=sys.argv[1], task_id='agos-live-test'))\n"
    )
    python = Path(HERMES).resolve().parent / "python"
    if not python.exists():
        python = HERMES_HOME / "hermes-agent" / "venv" / "bin" / "python"
    env = child_env({"HERMES_HOME": str(profile_home), "HERMES_STATE_DB_GUARD_BYPASS": "1"})
    out = subprocess.run(  # noqa: S603 — fixed argv
        [str(python), "-c", code, command],
        capture_output=True,
        text=True,
        timeout=300,
        env=env,
        cwd=str(HERMES_HOME / "hermes-agent"),
        check=True,
    ).stdout
    line = next(x for x in out.splitlines() if x.startswith("AGOSJSON"))
    result: dict[str, object] = json.loads(line[len("AGOSJSON") :])
    return result


@pytest.fixture(scope="module")
def live(tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[TestClient, str, Path]]:
    assert HERMES and DOCKER, "hermes and docker must be installed"
    # Hermes refuses its real state from any process under pytest; this test
    # deliberately uses real (throwaway, prefixed) profiles, so allow it here only.
    os.environ["HERMES_STATE_DB_GUARD_BYPASS"] = "1"
    tmp = tmp_path_factory.mktemp("live")
    prefix = f"agost{secrets.token_hex(2)}-"
    settings = Settings(
        data_dir=tmp / "data",
        internal_token_file=tmp / "data" / "system" / "internal.token",
        documents_url=None,
        engine=EngineConfig(
            hermes_bin=HERMES,
            docker_bin=DOCKER,
            hermes_home=HERMES_HOME,
            profile_prefix=prefix,
            sandbox_image=os.environ.get("AGOS_SANDBOX_IMAGE") or DEFAULT_SANDBOX_IMAGE,
            host_home=Path.home(),
            roots_dir=tmp / "roots",
        ),
    )
    app = create_app(settings, background=False)
    with TestClient(app) as client:
        client.headers["x-agos-internal"] = settings.internal_token_file.read_text()
        try:
            yield client, prefix, tmp
        finally:
            for ws in [w["id"] for w in client.get("/workspaces").json()]:
                client.post(f"/workspaces/{ws}/delete", json={"confirm": ws})
                client.delete(f"/trash/{ws}")
            os.environ.pop("HERMES_STATE_DB_GUARD_BYPASS", None)
            leftovers = list((tmp / "roots").glob(f"{prefix}*"))
            assert not leftovers, f"profiles left behind: {leftovers}"


def test_isolation_end_to_end(live: tuple[TestClient, str, Path]) -> None:
    client, _prefix, tmp = live
    a = client.post("/workspaces", json={"name": "Alpha", "defaultModel": MODEL}).json()["id"]
    b = client.post("/workspaces", json={"name": "Beta", "defaultModel": MODEL}).json()["id"]
    files = tmp / "data" / "workspaces"
    (files / a / "files" / "a-secret.txt").write_text("alpha only")
    (files / b / "files" / "b-secret.txt").write_text("beta only")
    shared = tmp / "Shared Reports"
    shared.mkdir()
    (shared / "report.txt").write_text("q3")
    engine = client.app.state.core.engine  # type: ignore[attr-defined]
    home_a, home_b = engine.profile_home(a), engine.profile_home(b)  # each its own root

    # Each workspace has its own loopback API with its own key.
    env_a, env_b = (h.joinpath(".env").read_text() for h in (home_a, home_b))

    def key(text: str) -> str:
        return next(x for x in text.splitlines() if x.startswith("API_SERVER_KEY="))

    assert key(env_a) != key(env_b) and "API_SERVER_HOST=127.0.0.1" in env_a

    # A sees only its own folder.
    listing = str(
        sandbox_exec(home_a, "ls -a /workspace; find / -xdev -name '*-secret.txt' 2>/dev/null")[
            "output"
        ]
    )
    assert "a-secret.txt" in listing and "b-secret.txt" not in listing
    probes = str(
        sandbox_exec(
            home_a,
            "cat /workspace/../*/b-secret.txt 2>/dev/null; ls /shared /Users "
            "/var/run/docker.sock /run/docker.sock 2>&1",
        )["output"]
    )
    assert "beta only" not in probes and "report.txt" not in probes
    for gone in ("/shared", "/Users", "/var/run/docker.sock", "/run/docker.sock"):
        assert f"cannot access '{gone}': No such file" in probes, gone

    # No secret in A's sandbox environment.
    env_out = str(sandbox_exec(home_a, "env")["output"])
    for word in ("API_SERVER_KEY", "ANTHROPIC", "OPENAI", "_TOKEN=", "HERMES_HOME="):
        assert word not in env_out, word

    # Added folder: visible, read-only by default.
    r = client.post(f"/workspaces/{a}/folders", json={"path": str(shared)})
    assert r.status_code == 201, r.text
    name = r.json()["id"]
    out = str(
        sandbox_exec(home_a, f"cat /shared/{name}/report.txt; touch /shared/{name}/x 2>&1")[
            "output"
        ]
    )
    assert "q3" in out and "Read-only file system" in out
    assert not (shared / "x").exists()
    # B still can't see it.
    assert "report.txt" not in str(sandbox_exec(home_b, "ls -R /shared 2>&1")["output"])

    # Removal is immediate: the very next command no longer sees it.
    assert client.delete(f"/workspaces/{a}/folders/{name}").status_code == 200
    out = str(sandbox_exec(home_a, f"ls /shared/{name} 2>&1; ls /workspace")["output"])
    assert "No such file" in out and "a-secret.txt" in out

    # Private places are refused by AGOS before anything reaches Hermes.
    for private in (Path.home(), HERMES_HOME, tmp / "data"):
        assert (
            client.post(f"/workspaces/{a}/folders", json={"path": str(private)}).status_code == 400
        )


def test_wrong_key_is_refused(live: tuple[TestClient, str, Path]) -> None:
    client, _, _ = live
    ws = client.post("/workspaces", json={"name": "Gamma", "defaultModel": MODEL}).json()["id"]
    engine = client.app.state.core.engine  # type: ignore[attr-defined]
    engine.start(ws)
    try:
        base, key = engine.api(ws)
        url = f"{base}/v1/capabilities"
        assert url.startswith("http://127.0.0.1:")
        ok = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}"})  # noqa: S310
        with urllib.request.urlopen(ok, timeout=10) as response:  # noqa: S310
            assert response.status == 200
        bad = urllib.request.Request(url, headers={"Authorization": "Bearer nope"})  # noqa: S310
        with pytest.raises(urllib.error.HTTPError) as refused:
            urllib.request.urlopen(bad, timeout=10)  # noqa: S310
        assert refused.value.code == 401
    finally:
        engine.stop(ws)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and engine.is_running(ws):
        time.sleep(0.5)
    assert not engine.is_running(ws)
