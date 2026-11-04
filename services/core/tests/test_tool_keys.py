"""Workspace → Settings → Keys: a key for the workspace's own tools goes into its
Hermes root (`.env` by Hermes's writer, the name into terminal.env_passthrough),
under a name decided from Hermes's data; AGOS never answers, logs or stores the key.

Hermes's runtime part (engine/tool_keys.py SCRIPT) is stood in for here by
`FakeHermes`, which uses Hermes's real catalog (config_defaults.py, pure data);
`test_the_real_script_*` runs the script in the installed Hermes."""

from __future__ import annotations

import json
import logging
import runpy
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from test_agent_profiles import add_agent
from test_library import env, ws  # noqa: F401 - fixture

from agos_core.engine import config_file
from agos_core.engine import tool_keys as tk

HERMES = Path.home() / ".hermes" / "hermes-agent"
SECRET = "pk-TEST-9f3c1e7a5b2d4c6e8a0b"  # noqa: S105 - a made-up key: it must never come back
SECRET2 = "pk-TEST-other-77aa55bb33cc11dd"


def _catalog() -> dict[str, dict[str, Any]]:
    path = HERMES / "hermes_cli" / "config_defaults.py"
    if not path.is_file():
        pytest.skip("no Hermes checkout to read its catalog from")
    found: dict[str, dict[str, Any]] = runpy.run_path(str(path))["OPTIONAL_ENV_VARS"]
    return found


class FakeHermes:
    """HermesEngine.tool_keys as far as the files go (the real one runs
    engine/tool_keys.py SCRIPT in Hermes's runtime)."""

    def __init__(self) -> None:
        self.catalog = _catalog()
        self.secrets: list[str] = []
        self.status: int | None = 200

    def own(self, name: str) -> bool:
        # Hermes's blocklist: providers, tool and messaging credentials, AUXILIARY_*.
        meta = self.catalog.get(name) or {}
        return meta.get("category") in ("provider", "messaging", "setting", "tool") or (
            name.startswith("AUXILIARY_")
        )

    def __call__(self, home: Path, job: dict[str, Any], secret: str = "") -> dict[str, Any]:
        if secret:
            self.secrets.append(secret)
        envf = home / ".env"
        lines = envf.read_text().splitlines() if envf.exists() else []
        if job["do"] == "facts":
            stem = job["slug"]
            rows = [
                {
                    "name": n,
                    "category": str(m.get("category") or ""),
                    "url": str(m.get("url") or ""),
                    "secret": bool(m.get("password")),
                    "own": self.own(n),
                }
                for n, m in self.catalog.items()
                if n.startswith(stem + "_")
            ]
            names: set[str] = {str(n) for n in job["names"]} | {str(r["name"]) for r in rows}
            names |= {"TOOLS_" + n for n in list(names) if not n.startswith("TOOLS_")}
            return {"catalog": rows, "own": {n: self.own(n) for n in names}}
        if job["do"] == "share":
            values = json.loads(secret or "{}")
            env_now = dict(ln.split("=", 1) for ln in lines if "=" in ln)
            for n, v in values.items():
                if not self.own(n):
                    env_now[n] = v
            dropped = [n for n in job.get("drop") or [] if env_now.pop(n, None) is not None]
            envf.write_text("".join(f"{n}={v}\n" for n, v in env_now.items()))
            return {"put": [n for n in values if not self.own(n)], "dropped": dropped}
        name = job["name"]
        if job["do"] == "save":
            if self.own(name):
                return {"refused": "own"}
            kept = [ln for ln in lines if not ln.startswith(f"{name}=")]
            envf.write_text("\n".join([*kept, f"{name}={secret}"]) + "\n")
            return {"saved": True}
        if job["do"] == "remove":
            kept = [ln for ln in lines if not ln.startswith(f"{name}=")]
            envf.write_text("".join(f"{ln}\n" for ln in kept))
            return {"removed": True}
        present = any(ln.startswith(f"{name}=") and ln.split("=", 1)[1] for ln in lines)
        listed = name in tk.passthrough(config_file.read(home))
        out: dict[str, Any] = {
            "present": present,
            "listed": listed,
            "passed": present and listed and not self.own(name),
            "own": self.own(name),
        }
        if job.get("probe") and present:
            out["status"] = self.status
        return out


@pytest.fixture
def keys(env: Any, monkeypatch: pytest.MonkeyPatch) -> Any:  # noqa: F811
    client, core, runner, _home = env
    fake = FakeHermes()
    core.engine.tool_keys = fake
    restarts: list[str] = []
    from agos_core.actions import hermes_channel

    monkeypatch.setattr(
        hermes_channel,
        "restart_gateway",
        lambda core, workspace_id, wait=False: restarts.append(workspace_id),
    )
    return client, core, runner, fake, restarts


def _root(core: Any, w: str) -> Path:
    return Path(core.engine.profile_home(w))


def _no_secret_anywhere(core: Any, runner: Any, texts: list[str], caplog: Any) -> None:
    for s in (SECRET, SECRET2):
        for text in texts:
            assert s not in text
        assert s not in caplog.text
        assert all(s not in " ".join(c) for c in runner.calls)  # never on a command line
        for row in core.db.execute("SELECT key, value FROM app_settings"):
            assert s not in str(row["value"]) and s[-8:] not in str(row["value"])


# ---- the name, from Hermes's data ---------------------------------------------------


def _facts(app: str) -> dict[str, Any]:
    fake = FakeHermes()
    return fake(
        Path("/nonexistent"), {"do": "facts", "slug": tk.slug(app), "names": tk.candidates(app)}
    )


def test_the_name_comes_from_the_apps_name_and_hermess_catalog() -> None:
    assert tk.pick("Pixabay", _facts("Pixabay")).name == "PIXABAY_API_KEY"
    assert tk.pick("  my  cool-app ", _facts("my cool-app")).name == "MY_COOL_APP_API_KEY"
    # Hermes's own provider key: a tools copy under its own name, with Hermes's link.
    picked = tk.pick("OpenRouter", _facts("OpenRouter"))
    assert picked.name == "TOOLS_OPENROUTER_API_KEY" and picked.hermes_own
    assert picked.url.startswith("https://openrouter.ai")
    # A tool credential Hermes blocks from sandboxes (its catalog's FIRECRAWL_API_KEY).
    assert tk.pick("Firecrawl", _facts("Firecrawl")).name == "TOOLS_FIRECRAWL_API_KEY"
    # Hermes didn't say whether a name is its own: never written.
    with pytest.raises(tk.NameProblem):
        tk.pick("Pixabay", {"catalog": [], "own": {}})
    for bad in ("", "   ", "123", "!!!", "x" * 61):
        with pytest.raises(tk.NameProblem):
            tk.clean_app(bad)


def test_only_a_long_values_last_four_are_shown() -> None:
    assert tk.shown_end(SECRET) == SECRET[-4:]
    assert tk.shown_end("short") == ""


# ---- save, list, replace, delete ----------------------------------------------------


def test_a_key_goes_into_the_roots_env_and_passthrough_and_never_comes_back(
    keys: Any, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    client, core, runner, fake, restarts = keys
    a = ws(client, "Alpha")
    root = _root(core, a)
    answers: list[str] = []
    r = client.post(f"/workspaces/{a}/tool-keys/name", json={"app": "Pixabay"})
    assert r.status_code == 200, r.text
    assert r.json() == {"name": "PIXABAY_API_KEY", "url": "", "exists": False}
    r = client.post(f"/workspaces/{a}/tool-keys", json={"app": "Pixabay", "key": f" {SECRET} "})
    assert r.status_code == 200, r.text
    answers.append(r.text)
    body = r.json()
    assert body["savedName"] == "PIXABAY_API_KEY"
    (row,) = body["keys"]
    assert row["app"] == "Pixabay" and row["name"] == "PIXABAY_API_KEY"
    assert row["endsWith"] == SECRET[-4:] and row["saved"] and row["savedAt"]
    assert row["testable"] is True
    # In Hermes: the value in the root's .env, the name in its passthrough list.
    assert config_file.read_env(root)["PIXABAY_API_KEY"] == SECRET
    assert tk.passthrough(config_file.read(root)) == ["PIXABAY_API_KEY"]
    assert fake.secrets == [SECRET]  # handed to Hermes once, on stdin
    assert restarts == [a]  # the gateway reads both at start
    # Replace.
    r = client.put(f"/workspaces/{a}/tool-keys/PIXABAY_API_KEY", json={"key": SECRET2})
    assert r.status_code == 200, r.text
    answers.append(r.text)
    assert config_file.read_env(root)["PIXABAY_API_KEY"] == SECRET2
    assert r.json()["keys"][0]["endsWith"] == SECRET2[-4:]
    # Test (Pixabay takes it / refuses it).
    r = client.post(f"/workspaces/{a}/tool-keys/PIXABAY_API_KEY/test")
    answers.append(r.text)
    assert r.json() == {"ok": True, "message": "Works: Pixabay accepted the key."}
    fake.status = 400
    r = client.post(f"/workspaces/{a}/tool-keys/PIXABAY_API_KEY/test")
    assert r.json()["ok"] is False and "refused" in r.json()["message"]
    listed = client.get(f"/workspaces/{a}/tool-keys")
    answers.append(listed.text)
    assert listed.json()["keys"][0]["testOk"] is False and listed.json()["keys"][0]["testedAt"]
    # Delete: out of the .env and the list; AGOS's note goes too.
    r = client.delete(f"/workspaces/{a}/tool-keys/PIXABAY_API_KEY")
    assert r.status_code == 200, r.text
    answers.append(r.text)
    assert r.json()["keys"] == []
    assert "PIXABAY_API_KEY" not in config_file.read_env(root)
    assert tk.passthrough(config_file.read(root)) == []
    assert (
        core.db.execute("SELECT 1 FROM app_settings WHERE key = ?", (f"tool_keys.{a}",)).fetchone()
        is None
    )
    assert restarts == [a, a, a]
    _no_secret_anywhere(core, runner, answers, caplog)


def test_a_key_hermes_keeps_for_itself_gets_a_tools_copy(keys: Any) -> None:
    client, core, _runner, _fake, _restarts = keys
    a = ws(client, "Alpha")
    root = _root(core, a)
    # The root's own OpenRouter key (Hermes's provider login).
    (root / ".env").write_text((root / ".env").read_text() + "OPENROUTER_API_KEY=root-own-key\n")
    r = client.post(f"/workspaces/{a}/tool-keys", json={"app": "OpenRouter", "key": SECRET})
    assert r.status_code == 200, r.text
    assert r.json()["savedName"] == "TOOLS_OPENROUTER_API_KEY"
    env_now = config_file.read_env(root)
    assert env_now["OPENROUTER_API_KEY"] == "root-own-key"  # untouched
    assert env_now["TOOLS_OPENROUTER_API_KEY"] == SECRET
    assert tk.passthrough(config_file.read(root)) == ["TOOLS_OPENROUTER_API_KEY"]


@pytest.mark.parametrize(
    ("app", "name", "said"),
    [
        ("OpenRouter", "OPENROUTER_API_KEY", "Hermes keeps"),
        ("Hermes", "API_SERVER_KEY", ""),
        ("Telegram", "TELEGRAM_BOT_TOKEN", "Hermes keeps"),
        ("Webhook", "WEBHOOK_PORT", ""),
        ("Clock", "TERMINAL_TIMEOUT", "kept for Hermes and AGOS"),
        ("Apps", "AGOS_MCP_GITHUB_TOKEN", "kept for Hermes and AGOS"),
        ("Bad", "lower_case", "A-Z"),
    ],
)
def test_names_hermes_or_agos_own_are_refused(keys: Any, app: str, name: str, said: str) -> None:
    client, core, _runner, fake, _restarts = keys
    a = ws(client, "Alpha")
    before = (_root(core, a) / ".env").read_text()
    r = client.post(f"/workspaces/{a}/tool-keys", json={"app": app, "key": SECRET, "name": name})
    assert r.status_code == 400, r.text
    assert said in r.json()["detail"] and SECRET not in r.text
    assert (_root(core, a) / ".env").read_text() == before
    assert fake.secrets == []


def test_a_name_hermes_already_uses_for_something_else_is_refused(keys: Any) -> None:
    client, core, _runner, _fake, _restarts = keys
    a = ws(client, "Alpha")
    root = _root(core, a)
    (root / ".env").write_text((root / ".env").read_text() + "FOO_API_KEY=set-in-hermes\n")
    r = client.post(f"/workspaces/{a}/tool-keys", json={"app": "Foo", "key": SECRET})
    assert r.status_code == 400 and "already uses" in r.json()["detail"]
    assert config_file.read_env(root)["FOO_API_KEY"] == "set-in-hermes"
    for path in ("/workspaces/{a}/tool-keys/FOO_API_KEY",):
        assert client.delete(path.format(a=a)).status_code == 404  # not one of the list
        assert client.put(path.format(a=a), json={"key": SECRET}).status_code == 404
    r = client.post(f"/workspaces/{a}/tool-keys", json={"app": "Foo", "key": "has space"})
    assert r.status_code == 400 and "no spaces" in r.json()["detail"]


# ---- each workspace's own ----------------------------------------------------------


def test_one_workspace_cannot_see_or_change_anothers_keys(keys: Any) -> None:
    client, core, _runner, _fake, _restarts = keys
    a, b = ws(client, "Alpha"), ws(client, "Beta")
    add_agent(client, a, "writer")
    assert (
        client.post(
            f"/workspaces/{a}/tool-keys", json={"app": "Pixabay", "key": SECRET}
        ).status_code
        == 200
    )
    root_a = _root(core, a)
    assert client.get(f"/workspaces/{b}/tool-keys").json() == {"keys": [], "savedName": None}
    assert "PIXABAY_API_KEY" not in config_file.read_env(_root(core, b))
    calls: list[Callable[[], Any]] = [
        lambda: client.put(f"/workspaces/{b}/tool-keys/PIXABAY_API_KEY", json={"key": SECRET2}),
        lambda: client.delete(f"/workspaces/{b}/tool-keys/PIXABAY_API_KEY"),
        lambda: client.post(f"/workspaces/{b}/tool-keys/PIXABAY_API_KEY/test"),
        lambda: client.get(f"/workspaces/{a}--a-writer/tool-keys"),
        lambda: client.get("/workspaces/nope/tool-keys"),
    ]
    for call in calls:
        assert call().status_code == 404
    assert config_file.read_env(root_a)["PIXABAY_API_KEY"] == SECRET
    assert tk.passthrough(config_file.read(root_a)) == ["PIXABAY_API_KEY"]


# ---- the list is Hermes's, and stays --------------------------------------------------


def test_the_passthrough_list_survives_a_sync_and_keeps_names_set_in_hermes(
    keys: Any,
) -> None:
    from agos_core.actions.engine import sync_workspace

    client, core, _runner, _fake, _restarts = keys
    a = ws(client, "Alpha")
    root = _root(core, a)
    # A name the owner put into Hermes himself.
    core.engine._hermes(a, "config", "set", tk.PASSTHROUGH, json.dumps(["OWN_TOOL_TOKEN"]))
    client.post(f"/workspaces/{a}/tool-keys", json={"app": "Pixabay", "key": SECRET})
    assert tk.passthrough(config_file.read(root)) == ["OWN_TOOL_TOKEN", "PIXABAY_API_KEY"]
    sync_workspace(core, a)
    assert tk.passthrough(config_file.read(root)) == ["OWN_TOOL_TOKEN", "PIXABAY_API_KEY"]
    assert config_file.read_env(root)["PIXABAY_API_KEY"] == SECRET
    # Shown too (nothing Hermes-only he can't see), under its own name.
    shown = {k["name"]: k for k in client.get(f"/workspaces/{a}/tool-keys").json()["keys"]}
    assert (
        shown["OWN_TOOL_TOKEN"]["app"] == "OWN_TOOL_TOKEN" and not shown["OWN_TOOL_TOKEN"]["saved"]
    )
    client.delete(f"/workspaces/{a}/tool-keys/PIXABAY_API_KEY")
    assert tk.passthrough(config_file.read(root)) == ["OWN_TOOL_TOKEN"]


def test_the_cofounder_learns_the_names_only(keys: Any) -> None:
    client, core, _runner, _fake, _restarts = keys
    a = ws(client, "Alpha")
    client.post(f"/workspaces/{a}/tool-keys", json={"app": "Pixabay", "key": SECRET})
    soul = (_root(core, a) / "SOUL.md").read_text()
    assert "$PIXABAY_API_KEY (Pixabay)" in soul and "Settings → Keys" in soul
    assert SECRET not in soul and SECRET[-4:] not in soul
    client.delete(f"/workspaces/{a}/tool-keys/PIXABAY_API_KEY")
    assert "PIXABAY_API_KEY" not in (_root(core, a) / "SOUL.md").read_text()


def test_the_hermes_settings_page_points_the_keys_to_this_card(keys: Any) -> None:
    from agos_core.actions import hermes_all_settings as hall

    assert hall.card_keys()[tk.PASSTHROUGH] == "keys"
    assert "keys" in hall.CARD_LABELS


def test_a_generic_key_is_ready_when_hermes_hands_it_to_the_tools(keys: Any) -> None:
    client, _core, _runner, _fake, _restarts = keys
    a = ws(client, "Alpha")
    client.post(f"/workspaces/{a}/tool-keys", json={"app": "Tracker", "key": SECRET})
    r = client.post(f"/workspaces/{a}/tool-keys/TRACKER_API_KEY/test")
    assert r.json() == {
        "ok": True,
        "message": "Ready: tools and scripts can read it as $TRACKER_API_KEY.",
    }
    # A fixed name (moving old key files): kept as given when Hermes allows it.
    r = client.post(
        f"/workspaces/{a}/tool-keys",
        json={"app": "Tracker", "key": SECRET2, "name": "TRACKER_MCP_URL"},
    )
    assert r.status_code == 200 and r.json()["savedName"] == "TRACKER_MCP_URL"


# ---- every agent of the workspace gets them ------------------------------------------


def test_every_agent_of_the_workspace_gets_the_keys_and_loses_them_with_the_root(
    keys: Any, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    client, core, runner, _fake, _restarts = keys
    a, b = ws(client, "Alpha"), ws(client, "Beta")
    add_agent(client, a, "writer")
    add_agent(client, b, "other")
    writer = Path(core.engine.profile_home(f"{a}--a-writer"))
    other = Path(core.engine.profile_home(f"{b}--a-other"))
    # A name the member holds in Hermes himself: never touched.
    core.engine._hermes(f"{a}--a-writer", "config", "set", tk.PASSTHROUGH, '["OWN_TOOL_TOKEN"]')
    answers = [
        client.post(f"/workspaces/{a}/tool-keys", json={"app": "Pixabay", "key": SECRET}).text
    ]
    assert config_file.read_env(writer)["PIXABAY_API_KEY"] == SECRET
    assert tk.passthrough(config_file.read(writer)) == ["OWN_TOOL_TOKEN", "PIXABAY_API_KEY"]
    assert json.loads((writer / ".agos-tool-keys.json").read_text()) == {
        "names": ["PIXABAY_API_KEY"]
    }
    # Another workspace's agent: nothing.
    assert "PIXABAY_API_KEY" not in config_file.read_env(other)
    assert "PIXABAY_API_KEY" not in tk.passthrough(config_file.read(other))
    r = client.post(f"/workspaces/{a}/tool-keys/PIXABAY_API_KEY/test")
    assert r.json()["ok"] is True
    # Replace: the agent's copy follows.
    client.put(f"/workspaces/{a}/tool-keys/PIXABAY_API_KEY", json={"key": SECRET2})
    assert config_file.read_env(writer)["PIXABAY_API_KEY"] == SECRET2
    # The agent lost it (hand edit): the test says so, a sync gives it back.
    (writer / ".env").write_text(
        "".join(
            ln + "\n" for ln in (writer / ".env").read_text().splitlines() if "PIXABAY" not in ln
        )
    )
    r = client.post(f"/workspaces/{a}/tool-keys/PIXABAY_API_KEY/test")
    answers.append(r.text)
    assert r.json() == {
        "ok": False,
        "message": "Saved, but 1 agent of this workspace doesn't get it yet. Save it again.",
    }
    from agos_core.actions import tool_keys as actions

    assert actions.share(core, a) == 1
    assert config_file.read_env(writer)["PIXABAY_API_KEY"] == SECRET2
    assert actions.share(core, a) == 0  # nothing to do: no Hermes run
    # A new agent gets the workspace's keys when it is made.
    add_agent(client, a, "editor")
    editor = Path(core.engine.profile_home(f"{a}--a-editor"))
    assert config_file.read_env(editor)["PIXABAY_API_KEY"] == SECRET2
    assert tk.passthrough(config_file.read(editor)) == ["PIXABAY_API_KEY"]
    # Removed from the workspace: gone from every agent, the agent's own name stays.
    answers.append(client.delete(f"/workspaces/{a}/tool-keys/PIXABAY_API_KEY").text)
    for home in (writer, editor):
        assert "PIXABAY_API_KEY" not in config_file.read_env(home)
        assert "PIXABAY_API_KEY" not in tk.passthrough(config_file.read(home))
    assert tk.passthrough(config_file.read(writer)) == ["OWN_TOOL_TOKEN"]
    _no_secret_anywhere(core, runner, answers, caplog)


# ---- the real script, in the installed Hermes -------------------------------------------


def test_the_real_script_names_saves_tests_and_removes(tmp_path: Path) -> None:
    from agos_core.config import EngineConfig
    from agos_core.engine.hermes import HermesEngine

    hermes = shutil.which("hermes")
    if not hermes or not HERMES.is_dir():
        pytest.skip("no Hermes install on this machine")
    tools = Path.home() / ".hermes" / "tools"
    engine = HermesEngine(
        EngineConfig(
            hermes_bin=hermes,
            docker_bin="docker",
            hermes_home=tmp_path / "shared",
            profile_prefix="agos-",
            sandbox_image="x",
            host_home=Path.home(),
            roots_dir=tmp_path / "roots",
            runtime_dir=tools if tools.is_dir() else None,
        ),
        egress=False,
    )
    home = tmp_path / "root"
    home.mkdir()
    (home / "config.yaml").write_text(
        "terminal:\n  backend: local\n  env_passthrough: [PIXABAY_API_KEY, OPENROUTER_API_KEY]\n"
    )
    for app, want in (("Pixabay", "PIXABAY_API_KEY"), ("OpenRouter", "TOOLS_OPENROUTER_API_KEY")):
        facts = engine.tool_keys(
            home, {"do": "facts", "slug": tk.slug(app), "names": tk.candidates(app)}
        )
        assert tk.pick(app, facts).name == want
    assert engine.tool_keys(home, {"do": "save", "name": "OPENROUTER_API_KEY"}, SECRET) == {
        "refused": "own"
    }
    assert engine.tool_keys(home, {"do": "save", "name": "PIXABAY_API_KEY"}, SECRET) == {
        "saved": True
    }
    found = engine.tool_keys(home, {"do": "test", "name": "PIXABAY_API_KEY"})
    assert found == {"present": True, "listed": True, "passed": True, "own": False}
    assert SECRET not in json.dumps(found)
    assert engine.tool_keys(home, {"do": "remove", "name": "PIXABAY_API_KEY"}) == {"removed": True}
    assert "PIXABAY_API_KEY" not in config_file.read_env(home)
    # A member's copy: values on stdin, Hermes's own credential never written.
    shared = engine.tool_keys(
        home,
        {"do": "share", "drop": []},
        json.dumps({"PIXABAY_API_KEY": SECRET, "OPENROUTER_API_KEY": SECRET2}),
    )
    assert shared == {"put": ["PIXABAY_API_KEY"], "dropped": []}
    assert config_file.read_env(home)["PIXABAY_API_KEY"] == SECRET
    assert "OPENROUTER_API_KEY" not in config_file.read_env(home)
    shared = engine.tool_keys(home, {"do": "share", "drop": ["PIXABAY_API_KEY"]}, "{}")
    assert shared == {"put": [], "dropped": ["PIXABAY_API_KEY"]}
    assert "PIXABAY_API_KEY" not in config_file.read_env(home)
