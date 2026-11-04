"""Subscription logins started from Settings → Models (fake Hermes, no network)."""

import stat
import time
from pathlib import Path

import pytest

from agos_core.config import EngineConfig
from agos_core.engine import provider_login
from agos_core.engine.models import to_connections
from agos_core.engine.provider_login import ProviderLogins, parse_output

CODEX_OUT = """Signing in to OpenAI Codex...
To continue, follow these steps:

  1. Open this URL in your browser:
     https://auth.openai.com/codex/device

  2. Enter this code:
     GAU9-67ID9

Waiting for sign-in... (press Ctrl+C to cancel)
"""

CLAUDE_OUT = """Authorize Hermes with your Claude Pro/Max subscription.
╭─ Claude Pro/Max Authorization ──╮
│  Open this link in your browser: │
╰──────────────────────────────────╯

  https://claude.ai/oauth/authorize?code=true&client_id=abc&state=xyz

After authorizing, you'll see a code. Paste it below.

Authorization code: """


def test_parse_device_code() -> None:
    assert parse_output(CODEX_OUT) == ("https://auth.openai.com/codex/device", "GAU9-67ID9", False)


def test_parse_pasted_code() -> None:
    url, code, needs = parse_output(CLAUDE_OUT)
    assert url == "https://claude.ai/oauth/authorize?code=true&client_id=abc&state=xyz"
    assert code is None
    assert needs is True


def test_login_labels_read_as_accounts() -> None:
    payload = {"providers": [{"slug": "openai-codex", "authenticated": True}]}
    pool = [provider_login_cred("openai-codex", "openai-codex-oauth-1")]
    rows = {r["id"]: r for r in to_connections(payload, pool)}
    assert rows["openai"]["cli"]["account"] == "your ChatGPT account"


def provider_login_cred(slug: str, label: str):  # type: ignore[no-untyped-def]
    from agos_core.engine.models import Credential

    return Credential(slug, label, "oauth")


def _fake_hermes(tmp_path: Path, body: str) -> EngineConfig:
    script = tmp_path / "hermes"
    script.write_text("#!/bin/sh\n" + body)
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return EngineConfig(
        hermes_bin=str(script),
        docker_bin="docker",
        hermes_home=tmp_path,
        profile_prefix="agos-",
        sandbox_image="x",
        host_home=tmp_path,
        roots_dir=tmp_path / "roots",
    )


def _wait(logins: ProviderLogins, provider: str, status: str) -> dict[str, object]:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        view = logins.get(provider)
        if view["status"] == status:
            return view
        time.sleep(0.1)
    raise AssertionError(f"never reached {status}: {logins.get(provider)}")


def test_device_login_reaches_connected(tmp_path: Path) -> None:
    engine = _fake_hermes(
        tmp_path,
        'echo "Open this URL in your browser:"\n'
        'echo "   https://auth.openai.com/codex/device"\n'
        'echo "Enter this code:"\necho "   AB12-CD34"\nsleep 1\necho "Login successful"\n',
    )
    logins = ProviderLogins(engine, lambda p, w: p == "openai")
    view = logins.start("openai")
    assert view["status"] == "waiting"
    assert view["url"] == "https://auth.openai.com/codex/device"
    assert view["userCode"] == "AB12-CD34"
    assert _wait(logins, "openai", "done")["message"] == "Connected."


def test_pasted_code_goes_to_hermes(tmp_path: Path) -> None:
    out = tmp_path / "got"
    engine = _fake_hermes(
        tmp_path,
        'echo "  https://claude.ai/oauth/authorize?x=1"\n'
        'echo "After authorizing, you\'ll see a code. Paste it below."\n'
        'printf "Authorization code: "\nread code\n'
        f'echo "$code" > {out}\n',
    )
    logins = ProviderLogins(engine, lambda p, w: True)
    view = logins.start("claude")
    assert view["status"] == "waiting" and view["needsCode"] is True
    logins.send_code("claude", "  abc#def  ")
    _wait(logins, "claude", "done")
    assert out.read_text().strip() == "abc#def"


def test_failed_login_says_why_and_cancel_stops(tmp_path: Path) -> None:
    engine = _fake_hermes(
        tmp_path,
        'echo "https://auth.openai.com/codex/device"\necho "Enter this code: ZZ99"\nexit 1\n',
    )
    logins = ProviderLogins(engine, lambda p, w: False)
    logins.start("openai")
    assert "ZZ99" in str(_wait(logins, "openai", "failed")["message"])

    slow = _fake_hermes(
        tmp_path, 'echo "https://x.example/d"\necho "Enter this code: QQ11"\nsleep 60\n'
    )
    logins = ProviderLogins(slow, lambda p, w: False)
    assert logins.start("openai")["status"] == "waiting"
    assert logins.cancel("openai")["status"] == "cancelled"
    assert logins.get("openai")["status"] == "idle"


def test_code_refused_without_waiting_login(tmp_path: Path) -> None:
    logins = ProviderLogins(_fake_hermes(tmp_path, "exit 0\n"), lambda p, w: False)
    with pytest.raises(ValueError):
        logins.send_code("claude", "x")
    with pytest.raises(ValueError):
        logins.start("gemini")
    assert provider_login.SLUGS["openai"] == "openai-codex"


def test_pool_is_hermess_structured_list_not_its_printed_table() -> None:
    """P7: the labels and kinds come from Hermes's own redacted pool list (no
    regex over `hermes auth list`'s padded columns)."""
    from agos_core.engine.models import pool_credentials

    found = {
        "pool": {
            "providers": [
                {
                    "provider": "openai-codex",
                    "entries": [{"label": "openai-codex-oauth-1", "auth_type": "oauth"}],
                },
                {
                    "provider": "copilot",
                    "entries": [{"label": "gh auth token", "auth_type": "api_key"}],
                },
            ]
        }
    }
    got = [(c.slug, c.label, c.kind) for c in pool_credentials(found)]
    assert got == [
        ("openai-codex", "openai-codex-oauth-1", "oauth"),
        ("copilot", "gh auth token", "api_key"),
    ]


def test_xai_grok_sign_in_is_read_from_hermess_own_device_login() -> None:
    """A tool service's sign-in (Hermes's post_setup "xai_grok"): Hermes's
    `auth add xai-oauth` prints its page and code; AGOS shows them."""
    from agos_core.engine.provider_login import SLUGS, TOOL_LOGINS, parse_output

    assert SLUGS[TOOL_LOGINS["xai_grok"]] == "xai-oauth"
    out = (
        "To continue:\n  1. Open: https://accounts.x.ai/oauth2/device?user_code=AB12-CD34\n"
        "  2. If prompted, enter code: AB12-CD34\nWaiting for approval (polling every 5s)...\n"
    )
    assert parse_output(out) == (
        "https://accounts.x.ai/oauth2/device?user_code=AB12-CD34",
        "AB12-CD34",
        False,
    )


def test_the_page_to_open_is_not_hermess_portal_line() -> None:
    from agos_core.engine.provider_login import parse_output

    out = (
        "Starting Hermes login via MiniMax (global) OAuth...\nPortal: https://api.minimax.io\n\n"
        "To continue:\n  1. Open: https://platform.minimax.io/oauth-authorize?user_code=X1\n"
        "  2. If prompted, enter code: AB12-CD34\n"
    )
    assert parse_output(out)[0] == "https://platform.minimax.io/oauth-authorize?user_code=X1"
    assert parse_output("Portal: https://api.minimax.io\n")[0] is None


def test_workspace_login_runs_in_that_workspace_root(tmp_path: Path) -> None:
    """A workspace signs in with Hermes's own `hermes auth add` in its own root."""
    seen = tmp_path / "home"
    engine = _fake_hermes(
        tmp_path,
        f'echo "$HERMES_HOME" > {seen}\n'
        'echo "https://auth.openai.com/codex/device"\necho "Enter this code: AB12"\nsleep 1\n',
    )
    roots = {"alpha": tmp_path / "roots" / "agos-alpha", "beta": tmp_path / "roots" / "agos-beta"}
    calls: list[tuple[str, str | None]] = []
    logins = ProviderLogins(
        engine,
        lambda p, w: w == "alpha",
        lambda p, w: calls.append((p, w)),
        home_of=lambda ws: roots[ws],
    )
    view = logins.start("openai", "alpha")
    assert view["status"] == "waiting" and view["workspace"] == "alpha"
    # One login per (workspace, provider): another workspace's is its own.
    assert logins.get("openai", "beta")["status"] == "idle"
    assert logins.get("openai")["status"] == "idle"
    deadline = time.monotonic() + 10
    while logins.get("openai", "alpha")["status"] != "done" and time.monotonic() < deadline:
        time.sleep(0.1)
    assert logins.get("openai", "alpha")["status"] == "done"
    assert seen.read_text().strip() == str(roots["alpha"])
    assert calls == [("openai", "alpha")]


def test_hermes_success_line_is_never_shown_as_the_failure(tmp_path: Path) -> None:
    engine = _fake_hermes(
        tmp_path,
        'echo "https://auth.openai.com/codex/device"\necho "Enter this code: AB12"\n'
        "echo 'Added openai-codex OAuth credential #1: \"x\"'\n",
    )
    logins = ProviderLogins(engine, lambda p, w: False)
    logins.start("openai")
    message = str(_wait(logins, "openai", "failed")["message"])
    assert not message.startswith("Added")


def test_subscriptions_are_shown_per_workspace() -> None:
    from agos_core.engine.models import Credential, own_logins, per_workspace

    payload = {
        "providers": [
            {"slug": "anthropic", "authenticated": True},
            {"slug": "copilot", "authenticated": True},
        ]
    }
    pool = [Credential("copilot", "COPILOT_GITHUB_TOKEN", "api_key")]
    spaces = [
        {"id": "a", "name": "Alpha", "logins": ["anthropic"]},
        {"id": "b", "name": "Beta", "logins": []},
    ]
    rows = {r["id"]: r for r in to_connections(payload, pool, spaces)}
    claude = rows["claude"]
    assert claude["perWorkspace"] is True
    assert claude["cli"]["account"] == "1 of 2 workspaces"
    assert [w["connected"] for w in claude["workspaces"]] == [True, False]
    assert rows["openai"]["cli"]["account"] is None  # no workspace signed in
    assert "perWorkspace" not in rows["copilot"]  # a token: General Settings' one login
    assert not per_workspace("nous", "oauth_device_code")
    # Claude Code's file borrowed by Hermes is not the workspace's own login.
    assert (
        own_logins(
            [Credential("anthropic", "claude_code", "oauth"), Credential("copilot", "gh", "oauth")]
        )
        == set()
    )
    assert own_logins([Credential("anthropic", "anthropic-oauth-1", "oauth")]) == {"anthropic"}
