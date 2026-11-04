"""Gateways and the library on Hermes's own paths (step 15).

- An MCP change reaches the running gateway through Hermes's own /reload-mcp (in
  AGOS's control conversation of each profile); the gateway is never stopped, so
  Kanban workers, cron runs and rooms keep going.
- Testing an MCP server is `hermes mcp test` in the workspace's root.
- Skills from the web are installed by Hermes's hub straight into the workspace's
  skill folder (`hermes skills install --category agos-library` in its root, whose
  hub lock keeps it), checked with `hermes skills check`, updated with `hermes
  skills update`; a delete is Hermes's curator archive.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from test_library import SKILL, env, mcp, ws  # noqa: F401

from agos_core.engine import sources


def _inbox(core: Any, workspace_id: str) -> list[tuple[str, str]]:
    return [
        (str(r["chat_ref"]), str(r["text"]))
        for r in core.db.execute(
            "SELECT chat_ref, text FROM hermes_inbox WHERE workspace_id = ? AND kind = 'command'"
            " ORDER BY id",
            (workspace_id,),
        )
    ]


def test_an_mcp_change_is_hermess_reload_never_a_stop(env: Any) -> None:  # noqa: F811
    """Added, turned off or on, removed: Hermes's own MCP reconcile takes it (no
    command from AGOS). Edited (url, headers, tools, key): Hermes's /reload-mcp,
    with no /approve (every profile has approvals.mcp_reload_confirm: false)."""
    client, core, _runner, _home = env
    a = ws(client, "Alpha")
    stops: list[str] = []
    core.engine.stop = lambda workspace_id, **_: stops.append(workspace_id)
    core.engine.is_running = lambda workspace_id: True
    assert _inbox(core, a) == []
    mid = mcp(client, a, "wiki", {"url": "https://wiki.example.com/mcp"})
    assert _inbox(core, a) == []  # added: Hermes's reconcile connects it
    assert client.put(f"/workspaces/{a}/connectors/{mid}", json={"on": False}).status_code == 204
    assert client.put(f"/workspaces/{a}/connectors/{mid}", json={"on": True}).status_code == 204
    assert _inbox(core, a) == []  # off / on: Hermes's reconcile too
    edited = client.put(
        f"/workspaces/{a}/connectors/{mid}", json={"on": True, "allowedTools": ["search"]}
    )
    assert edited.status_code == 204, edited.text  # its tool filter: an edit
    assert _inbox(core, a) == [("agos:0", "/reload-mcp")]
    assert stops == []
    # The same setup again: nothing to reload.
    from agos_core.actions.library import apply_workspace

    (core.engine.profile_home(a) / ".agos-connectors").unlink()
    apply_workspace(core, a)
    assert len(_inbox(core, a)) == 1 and stops == []


def test_every_profile_skips_hermess_reload_confirm(env: Any) -> None:  # noqa: F811
    from agos_core.actions.library import profile_settings

    assert profile_settings([])["approvals.mcp_reload_confirm"] == "false"


def test_no_reload_while_the_gateway_is_down(env: Any) -> None:  # noqa: F811
    """A gateway that isn't running reads its config when Hermes's service starts it."""
    client, core, _runner, _home = env
    a = ws(client, "Alpha")
    core.engine.is_running = lambda workspace_id: False
    mcp(client, a, "wiki", {"url": "https://wiki.example.com/mcp"})
    assert _inbox(core, a) == []


def test_the_control_conversation_is_no_chat(env: Any) -> None:  # noqa: F811
    """Hermes's answer to /reload-mcp lands in no AGOS chat."""
    client, core, _runner, _home = env
    from agos_core.actions import hermes_channel

    a = ws(client, "Alpha")
    assert hermes_channel.chat_at(core, a, "agos:0") is None
    assert hermes_channel.owner_member(core, a, "agos:0") is None  # the Co-Founder's own
    assert not hermes_channel.platform_said(core, a, "agos:0", "🔄 MCP servers reloaded")


def test_testing_an_mcp_server_is_hermes_mcp_test(env: Any) -> None:  # noqa: F811
    client, core, _runner, _home = env
    a = ws(client, "Alpha")
    mid = mcp(client, a, "wiki", {"url": "https://wiki.example.com/mcp"})
    asked: list[tuple[str, ...]] = []

    def hermes(workspace_id: str, *args: str, timeout: float = 60) -> str:
        asked.append(args)
        return (
            "  Testing 'wiki'...\n  ✓ Connected (12ms)\n  ✓ Tools discovered: 1\n\n"
            "    search                                Find a page\n"
        )

    # Walled: a stdio server's command comes from the root's config.yaml, which the
    # walled gateway can write (area3 B3).
    core.engine.walled_cli = hermes
    core.engine._hermes = lambda *a, **k: (_ for _ in ()).throw(AssertionError("unwalled"))
    got = client.post(f"/workspaces/{a}/mcp/{mid}/test").json()
    assert asked == [("mcp", "test", "wiki")]
    assert got["ok"] is True and [t["name"] for t in got["tools"]] == ["search"]


class _Hub:
    """Hermes's skills hub, as `hermes skills …` answers in a workspace's root."""

    def __init__(self) -> None:
        self.calls: list[tuple[list[str], Path | None]] = []
        self.lock: dict[str, str] = {}
        self.status = "up_to_date"

    def __call__(self, args: list[str], *, home: Path | None = None, timeout: float = 180) -> str:
        self.calls.append((args, home))
        if args[:2] == ["skills", "inspect"]:
            return "╭── Skill: invoice-check ──╮\n│ Name: invoice-check │\n╰──╯\n"
        assert home is not None
        if args[:2] == ["skills", "install"]:
            name = args[args.index("--name") + 1]
            category = args[args.index("--category") + 1] if "--category" in args else ""
            folder = home / "skills" / category / name
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "SKILL.md").write_text(SKILL)
            self.lock[name] = args[2]
            return "Decision: ALLOWED — Allowed (trusted source)\nInstalled: invoice-check\n"
        if args[:2] == ["skills", "check"]:
            rows = "".join(f"│ {n} │ github │ {self.status} │\n" for n in self.lock)
            return "┃ Name ┃ Source ┃ Status ┃\n" + rows
        if args[:2] == ["skills", "update"]:
            folder = home / "skills" / "agos-library" / args[2]
            (folder / "SKILL.md").write_text(SKILL.replace("mistakes", "errors"))
            return "Updating: invoice-check\nUpdated 1 skill(s).\n"
        raise AssertionError(args)


def _use_hub(monkeypatch: Any, core: Any, hub: _Hub) -> list[dict[str, str]]:
    """Every Sources AGOS makes answers through `hub`; returns the extra env each got."""
    from agos_core.actions import library
    from agos_core.actions.services.library import sources as library_sources

    made: list[dict[str, str]] = []

    def fake(_core: Any, home: Path | None = None, **kw: Any) -> sources.Sources:
        src = sources.Sources(core.engine.settings, "/x/venv/bin/python", Path("/x"), home, **kw)
        made.append(dict(src.extra_env))
        monkeypatch.setattr(src, "_hermes", lambda args, **k: hub(args, **{"home": home, **k}))
        return src

    for mod in (library, library_sources):  # the facade and its home
        monkeypatch.setattr(mod, "_sources", fake)
    return made


def _updates(core: Any, workspace_id: str) -> list[Any]:
    """The skills' updates once Hermes's check is in (Step 41: with nothing kept,
    the check runs behind the page and the page answers without the hub's skills)."""
    from agos_core.actions import workspace_skills
    from agos_core.engine.read_cache import ReadCache

    workspace_skills.check_updates(core, workspace_id)
    assert ReadCache.settle(10)
    return list(workspace_skills.check_updates(core, workspace_id))


def test_web_skills_land_in_their_workspace_through_hermess_hub(env: Any, monkeypatch: Any) -> None:  # noqa: F811
    client, core, runner, _home = env
    from agos_core.actions import library, workspace_skills

    hub = _Hub()
    made = _use_hub(monkeypatch, core, hub)
    (library.library_home(core) / ".env").parent.mkdir(parents=True, exist_ok=True)
    (library.library_home(core) / ".env").write_text("GITHUB_TOKEN=ghp_hub\n")
    a, b = ws(client, "Alpha"), ws(client, "Beta")
    got = workspace_skills.install_web(core, a, "openai/skills/invoice-check")
    # Hermes's hub installed it straight into the workspace's folder, in its root.
    install = next(c for c in hub.calls if c[0][:2] == ["skills", "install"])
    root = core.engine.profile_home(a)
    assert install[1] == root and "--force" not in install[0]
    assert install[0][install[0].index("--category") + 1] == "agos-library"
    assert {"GITHUB_TOKEN": "ghp_hub"} in made  # for Hermes's process only
    root_env = (root / ".env").read_text() if (root / ".env").exists() else ""
    assert "ghp_hub" not in root_env  # never written into the workspace's root
    folder = root / "skills" / "agos-library" / "invoice-check"
    assert (folder / "SKILL.md").read_text() == SKILL
    assert "Decision: ALLOWED" in got.scan
    # On in that workspace at once; nothing of it in another.
    import json

    assert "invoice-check" not in json.loads(runner.config[f"agos-{a}"]["skills.disabled"])
    assert client.get(f"/workspaces/{b}/skills").json() == []
    # A second one with the same name is refused before Hermes installs anything.
    before = len(hub.calls)
    r = client.post(
        f"/workspaces/{a}/skills/web/install", json={"identifier": "other/invoice-check"}
    )
    assert r.status_code == 409, r.text
    assert not [c for c in hub.calls[before:] if c[0][:2] == ["skills", "install"]]
    # Hermes says if there is a newer one; Update is Hermes's own update.
    assert [u.has_update for u in _updates(core, a)] == [False]
    hub.status = "update_available"
    workspace_skills._HUB.drop()  # hours later: Hermes's kept check is asked again
    [update] = _updates(core, a)
    assert update.has_update and update.item_id == got.id
    workspace_skills.apply_update(core, a, got.id)
    assert ["skills", "update", "invoice-check", "--force"] in [c[0] for c in hub.calls]
    rows = {r["name"]: r for r in client.get(f"/workspaces/{a}/skills").json()}
    assert rows["invoice-check"]["summary"] == "Check invoices for errors."
    # Deleting it is Hermes's curator archive (recoverable).
    assert client.delete(f"/workspaces/{a}/skills/{got.id}").status_code == 204
    assert not folder.exists()
    assert (root / "skills" / ".archive" / "invoice-check" / "SKILL.md").is_file()


def test_a_web_skill_not_in_the_roots_hub_lock_is_installed_again_on_update(
    env: Any,  # noqa: F811
    monkeypatch: Any,
) -> None:
    """A web skill moved from the old shared library (or copied from another
    workspace) isn't in its root's hub lock: check says so and Update has Hermes's
    hub install it again there (then it keeps it)."""
    client, core, _runner, _home = env
    from agos_core.actions import workspace_skills
    from agos_core.db import library as repo

    a = ws(client, "Alpha")
    folder = core.engine.profile_home(a) / "skills" / "agos-library" / "invoice-check"
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text(SKILL)
    item_id = repo.insert_item(
        core.db,
        kind="skill",
        name="invoice-check",
        title="invoice-check",
        summary="",
        definition={"identifier": "openai/skills/invoice-check", "hash": "sha256:x"},
        source="web",
        workspace_id=a,
    )
    hub = _Hub()
    _use_hub(monkeypatch, core, hub)
    [update] = _updates(core, a)
    assert update.has_update and "Hermes's hub" in update.detail
    workspace_skills.apply_update(core, a, item_id)
    assert hub.lock == {"invoice-check": "openai/skills/invoice-check"}
    assert [u.has_update for u in workspace_skills.check_updates(core, a)] == [False]


def test_hermess_tables_are_read_back() -> None:
    text = (
        "        Skill Updates\n┏━━━━━━┳━━━━━━━━┳━━━━━━━━━━━━┓\n┃ Name ┃ Source ┃ Status     ┃\n"
        "┡━━━━━━╇━━━━━━━━╇━━━━━━━━━━━━┩\n│ pdf  │ github │ up_to_date │\n└──────┴────────┴────────────┘\n"
    )
    assert sources._table_rows(text) == [
        ["Name", "Source", "Status"],
        ["pdf", "github", "up_to_date"],
    ]


def test_an_edited_mcp_url_and_header_reach_hermes_and_reload(env: Any) -> None:  # noqa: F811
    """Editing a server's url (and its header) writes the new entry into Hermes's
    `mcp_servers` (through `hermes config set`) and asks Hermes's /reload-mcp."""
    import json

    client, core, runner, _home = env
    a = ws(client, "Alpha")
    core.engine.is_running = lambda workspace_id: True
    mid = mcp(client, a, "wiki", {"url": "https://wiki.example.com/mcp"})
    r = client.put(f"/workspaces/{a}/connectors/{mid}/secret", json={"value": "k-1234"})
    assert r.status_code == 204
    before = len(_inbox(core, a))
    edited = client.put(
        f"/workspaces/{a}/mcp/{mid}",
        json={
            "name": "wiki",
            "definition": {
                "url": "https://wiki2.example.com/mcp",
                "auth_header": "X-Api-Key",
                "auth_scheme": "",
            },
        },
    )
    assert edited.status_code == 204, edited.text
    entry = json.loads(runner.config[f"agos-{a}"]["mcp_servers"])["wiki"]
    assert entry["url"] == "https://wiki2.example.com/mcp"
    assert entry["headers"] == {"X-Api-Key": "${AGOS_MCP_WIKI}"}
    assert _inbox(core, a)[before:] == [("agos:0", "/reload-mcp")]
    listed = {m["name"]: m for m in client.get(f"/workspaces/{a}/mcp").json()}
    assert listed["wiki"]["definition"]["url"] == "https://wiki2.example.com/mcp"
