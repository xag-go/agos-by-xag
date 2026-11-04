"""Claude's limits are read as the percents Anthropic sends (1 = 1%, not 100%)."""

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from agos_core.engine import limits

# The shape of api.anthropic.com/api/oauth/usage (numbers from a real answer).
PAYLOAD: dict[str, Any] = {
    "five_hour": {"utilization": 1.0, "resets_at": "2026-09-27T19:59:59+00:00"},
    "seven_day": {"utilization": 3.0, "resets_at": "2026-10-04T02:59:59+00:00"},
    "limits": [
        {
            "kind": "session",
            "group": "session",
            "percent": 1,
            "resets_at": "2026-09-27T20:00:00+00:00",
            "scope": None,
        },
        {
            "kind": "weekly_all",
            "group": "weekly",
            "percent": 3,
            "resets_at": "2026-10-04T03:00:00+00:00",
            "scope": None,
        },
        {
            "kind": "weekly_scoped",
            "group": "weekly",
            "percent": 0,
            "resets_at": "2026-10-04T03:00:00+00:00",
            "scope": {"model": {"id": None, "display_name": "Fable"}, "surface": None},
        },
    ],
}


def _run(tmp_path: Path, payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Runs the real script against stand-ins for Hermes's modules."""
    agent = tmp_path / "agent"
    agent.mkdir(exist_ok=True)
    (agent / "__init__.py").write_text("")
    (agent / "anthropic_credentials.py").write_text(
        "def resolve_anthropic_token():\n    return 'oauth'\n"
        "def _is_oauth_token(t):\n    return True\n"
    )
    fail = payload is None
    (agent / "account_usage.py").write_text(
        f"import json\nPAYLOAD = json.loads({json.dumps(json.dumps(payload or {}))})\n"
        "def _get_json(url, headers, *, timeout):\n"
        + ("    raise RuntimeError('429 rate limited')\n" if fail else "    return PAYLOAD\n")
        + "def fetch_account_usage(provider):\n    return None\n"
    )
    done = subprocess.run(  # noqa: S603 - fixed argv, test only
        [sys.executable, "-c", limits._SCRIPT, json.dumps(["anthropic"])],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        check=True,
    )
    line = [ln for ln in done.stdout.splitlines() if ln.startswith("AGOS-JSON ")][-1]
    rows: list[dict[str, Any]] = json.loads(line[len("AGOS-JSON ") :])
    return rows


def test_claude_percents_are_not_multiplied(tmp_path: Path) -> None:
    rows = _run(tmp_path, PAYLOAD)
    windows = {w["label"]: w["used"] for w in rows[0]["windows"]}
    assert windows == {"Current session": 1.0, "This week": 3.0, "Fable this week": 0.0}
    accounts = limits._remember("t1", rows)
    assert not accounts[0].warning


def _future(payload: dict[str, Any]) -> dict[str, Any]:
    text = (
        json.dumps(payload).replace("2026-09-27", "2999-09-27").replace("2026-10-04", "2999-10-04")
    )
    out: dict[str, Any] = json.loads(text)
    return out


def test_a_rate_limited_read_keeps_the_last_numbers(tmp_path: Path) -> None:
    good = _run(tmp_path, _future(PAYLOAD))
    limits._remember("t2", good)
    (tmp_path / "agent" / "account_usage.py").unlink()
    later = _run(tmp_path, None)
    assert later == [{"provider": "anthropic", "unavailable": True}]
    kept = limits._remember("t2", later)
    assert [w.used_percent for w in kept[0].windows] == [1.0, 3.0, 0.0]


def test_kept_numbers_of_a_window_that_has_reset_are_not_shown(tmp_path: Path) -> None:
    """The page showed yesterday's 88% "resets 00:30" all day: once a window's reset
    time passed, its old number is wrong, so it shows nothing until a fresh read."""
    good = _run(tmp_path, PAYLOAD)  # resets in 2026-09/10: already passed
    limits._remember("t3", good)
    kept = limits._remember("t3", [{"provider": "anthropic", "unavailable": True}])
    assert [w.used_percent for w in kept[0].windows] == [None, None, None]
    assert not kept[0].warning


def test_an_expired_login_is_renewed_through_hermes_then_read(tmp_path: Path) -> None:
    """Nobody used Claude for hours: the saved token expired and the read-only
    lookup got 401. The script asks Hermes's credential pool for a fresh one
    (it renews it under its own lock) and reads again."""
    agent = tmp_path / "agent"
    agent.mkdir()
    (agent / "__init__.py").write_text("")
    (agent / "anthropic_credentials.py").write_text(
        "def resolve_anthropic_token():\n    return 'old'\n"
        "def _is_oauth_token(t):\n    return True\n"
    )
    (agent / "credential_pool.py").write_text(
        "class E:\n    access_token = 'new'\n"
        "class P:\n    def select(self):\n        return E()\n"
        "def load_pool(provider):\n    assert provider == 'anthropic'\n    return P()\n"
    )
    (agent / "account_usage.py").write_text(
        f"import json\nPAYLOAD = json.loads({json.dumps(json.dumps(PAYLOAD))})\n"
        "def _get_json(url, headers, *, timeout):\n"
        "    if headers['Authorization'] != 'Bearer new':\n"
        "        raise RuntimeError(\"Client error '401 Unauthorized'\")\n"
        "    return PAYLOAD\n"
        "def fetch_account_usage(provider):\n    return None\n"
    )
    done = subprocess.run(  # noqa: S603 - fixed argv, test only
        [sys.executable, "-c", limits._SCRIPT, json.dumps(["anthropic"])],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        check=True,
    )
    line = [ln for ln in done.stdout.splitlines() if ln.startswith("AGOS-JSON ")][-1]
    rows = json.loads(line[len("AGOS-JSON ") :])
    assert [w["used"] for w in rows[0]["windows"]] == [1.0, 3.0, 0.0]


def _fake_hermes(tmp_path: Path, answers: dict[str, Any]) -> str:
    """A stand-in `hermes` launcher: `usage --provider <p> --json` as Hermes prints it."""
    script = tmp_path / "hermes"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        f"ANSWERS = json.loads({json.dumps(json.dumps(answers))})\n"
        "args = sys.argv[1:]\n"
        "assert args[0] == 'usage' and args[-1] == '--json', args\n"
        "doc = ANSWERS.get(args[args.index('--provider') + 1])\n"
        "if doc is None:\n"
        "    print('No account usage available', file=sys.stderr); sys.exit(1)\n"
        "print(json.dumps(doc, indent=2))\n"
    )
    script.chmod(0o755)
    return str(script)


def test_codex_copilot_and_nous_are_hermes_usage_json(tmp_path: Path) -> None:
    """Hermes's own `hermes usage --json` (H: hermes_cli/subcommands/usage.py)."""
    from types import SimpleNamespace

    codex = {
        "provider": "openai-codex",
        "source": "usage_api",
        "title": "Account limits",
        "plan": "Plus",
        "fetched_at": "2026-10-16T19:54:05+00:00",
        "windows": [
            {
                "label": "5h",
                "used_percent": 42.0,
                "resets_at": "2999-01-01T00:00:00+00:00",
                "detail": None,
            }
        ],
        "details": ["Banked resets: 1"],
        "unavailable_reason": None,
    }
    nous = {**codex, "provider": "nous", "windows": [], "unavailable_reason": "no plan"}
    engine = SimpleNamespace(
        hermes_bin=_fake_hermes(tmp_path, {"openai-codex": codex, "nous": nous}),
        host_home=tmp_path,
        hermes_home=tmp_path / "h",
    )
    got = limits._hermes_usage(engine, "openai-codex")  # type: ignore[arg-type]
    assert got == {
        "provider": "openai-codex",
        "windows": [
            {"label": "5h", "used": 42.0, "reset": "2999-01-01T00:00:00+00:00", "detail": None}
        ],
        "details": ["Banked resets: 1"],
    }
    assert limits._hermes_usage(engine, "copilot") is None  # type: ignore[arg-type]
    assert limits._hermes_usage(engine, "nous") is None  # type: ignore[arg-type]
    accounts = limits._remember("t-cli", [got])
    assert accounts[0].label == "OpenAI (Codex)" and accounts[0].windows[0].used_percent == 42.0


def test_only_claude_is_read_past_hermes_cli() -> None:
    """Guard: the venv script is Claude's alone (Hermes misreads its percents);
    the other accounts never go back to Hermes's private module."""
    source = Path(limits.__file__).read_text()
    assert "fetch_account_usage" not in source
    assert limits.CLI_PROVIDERS == ("openai-codex", "copilot", "nous")
    assert '"usage", "--provider", provider, "--json"' in source


def test_the_claude_probe_tries_each_home_until_one_holds_the_login(
    tmp_path: Path,
) -> None:
    """The Claude sign-in lives in a workspace root's own credential pool; the
    shared home can have none, and only Hermes may read its stores. So the probe
    runs Hermes's script per home (the shared home first, then each root with a
    config): a home with no login answers empty and costs no Anthropic request;
    the first that answers wins."""
    from agos_core.config import EngineConfig

    calls = tmp_path / "homes.txt"
    stub = tmp_path / "bin" / "x" / "python"  # _claude's cwd rule: 3 parents up
    stub.parent.mkdir(parents=True)
    stub.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, pathlib\n"
        f"log = pathlib.Path({str(calls)!r})\n"
        "home = os.environ.get('HERMES_HOME', 'NONE')\n"
        "seen = log.read_text() if log.exists() else ''\n"
        "log.write_text(seen + home + '\\n')\n"
        "row = [] if home.endswith('.hermes') else [\n"
        "    {'provider': 'anthropic', 'windows': [\n"
        "        {'label': 'Current session', 'used': 2.0, 'reset': None, 'detail': None}\n"
        "    ], 'details': []}\n"
        "]\n"
        "print('AGOS-JSON ' + json.dumps(row))\n"
    )
    stub.chmod(0o755)
    home = tmp_path / "home" / ".hermes"
    home.mkdir(parents=True)
    roots = tmp_path / "data" / "hermes"
    (roots / "agos-b").mkdir(parents=True)
    (roots / "agos-b" / "config.yaml").write_text("{}\n")
    (roots / "agos-a").mkdir()  # no config.yaml: not a root yet, never probed
    engine = EngineConfig(
        hermes_bin="/bin/hermes",
        docker_bin="/bin/docker",
        hermes_home=home,
        profile_prefix="agos-",
        sandbox_image="img:1",
        host_home=tmp_path / "home",
        roots_dir=roots,
    )
    rows = limits._claude(engine, str(stub))
    assert [w["used"] for w in rows[0]["windows"]] == [2.0]
    # The shared home was asked first (empty: no login), then the root answered.
    assert calls.read_text().splitlines() == [str(home), str(roots / "agos-b")]
