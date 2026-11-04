"""Holographic memory is a Hermes catalog plugin (v0.22): every profile that names
it gets it with Hermes's own `hermes plugins install holographic`."""

from pathlib import Path
from typing import Any

import pytest
from test_engine_sync import profile_dir
from test_library import env, ws  # noqa: F401 - fixture

from agos_core.actions import memory_plugin


def test_every_root_and_member_gets_holographic_from_hermess_catalog(env: Any) -> None:  # noqa: F811
    client, core, runner, home = env
    a = ws(client, "Alpha")
    r = client.post(
        f"/workspaces/{a}/agents",
        json={"name": "editor", "title": "Editor", "definition": {"instructions": "Edit."}},
    )
    assert r.status_code == 201, r.text
    root, member = profile_dir(home, f"agos-{a}"), profile_dir(home, f"agos-{a}--a-editor")
    for h in (root, member):  # AGOS's rules name it (engine/rules.py)
        core.engine._hermes(
            a if h == root else f"{a}--a-editor",
            "config",
            "set",
            "memory.provider",
            "holographic",
        )
    import shutil
    import time

    # Made just now: AGOS's one install ran in the background.
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and not memory_plugin.installed(root):
        time.sleep(0.05)
    assert memory_plugin.installed(root)
    shutil.rmtree(root / "plugins" / "holographic")
    runner.plugins_down = True
    assert memory_plugin.ensure(core, a) is False  # no catalog: one try, Hermes retries
    runner.plugins_down = False
    assert memory_plugin.ensure(core, a) is True
    assert memory_plugin.ensure(core, f"{a}--a-editor") is True
    assert all((h / "plugins" / "holographic" / "plugin.yaml").is_file() for h in (root, member))
    calls = {c[1:] for c in runner.plugin_installs}
    assert calls == {("holographic", "--enable", "--yes-deps")}
    before = len(runner.plugin_installs)
    assert memory_plugin.ensure(core, a) is True  # there: Hermes isn't asked again
    assert len(runner.plugin_installs) == before


def test_a_failed_install_is_tried_again_when_agos_starts(env: Any) -> None:  # noqa: F811
    """Under the gateway's Landlock wall Hermes's own install at agent start
    (memory_provider_migration.recover_at_startup) can't finish: the catalog
    install writes outside the root. So AGOS, unwalled, tries again at its own
    start for every profile that names Holographic and lacks it (area3 B6)."""
    client, core, runner, home = env
    a = ws(client, "Alpha")
    root = profile_dir(home, f"agos-{a}")
    core.engine._hermes(a, "config", "set", "memory.provider", "holographic")
    import shutil
    import time

    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and not memory_plugin.installed(root):
        time.sleep(0.05)
    shutil.rmtree(root / "plugins" / "holographic", ignore_errors=True)
    before = len(runner.plugin_installs)
    started = memory_plugin.recover(core)
    assert started == [a]
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and not memory_plugin.installed(root):
        time.sleep(0.05)
    assert memory_plugin.installed(root)
    assert len(runner.plugin_installs) == before + 1
    assert memory_plugin.recover(core) == []  # there now: nothing to do


def test_agos_never_copies_the_plugin_itself() -> None:
    """Installed by Hermes's CLI only: no copy of plugins/holographic by AGOS."""
    src = Path(__file__).resolve().parents[1] / "src" / "agos_core"
    for path in src.rglob("*.py"):
        text = path.read_text()
        if '"holographic"' in text or "'holographic'" in text:
            rel = path.relative_to(src).as_posix()
            assert rel in {"actions/memory_plugin.py", "engine/rules.py"}, rel
    rules = (src / "engine" / "rules.py").read_text()
    assert '"memory.provider": "holographic"' in rules
    start = (src / "actions" / "services" / "system" / "startup.py").read_text()
    assert '(memory_plugin, "recover", ' in start  # a failed install, tried again at start
    for made in ("actions/engine.py", "actions/agent_profiles.py"):
        assert "memory_plugin.install_new(core, " in (src / made).read_text()
    text = (src / "actions" / "memory_plugin.py").read_text()
    assert '"plugins", "install", PLUGIN, "--enable", "--yes-deps"' in text
    assert "copytree" not in text and "git" not in text.replace("plugin", "")


def test_a_new_profiles_install_is_tried_again_after_a_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Hermes's installer can fail when two installs run at once in a new workspace;
    the new profile's one install is tried a few times (Hermes's own retry waits an
    hour), and stops as soon as it is there."""
    import threading
    from types import SimpleNamespace

    calls: list[str] = []
    done = threading.Event()

    def ensure(core: object, key: str) -> bool:
        calls.append(key)
        ok = len(calls) >= 2
        if ok:
            done.set()
        return ok

    monkeypatch.setattr(memory_plugin, "ensure", ensure)
    monkeypatch.setattr(memory_plugin, "PAUSE_S", 0.01)
    memory_plugin.install_new(SimpleNamespace(engine=object()), "alpha")  # type: ignore[arg-type]
    assert done.wait(5)
    assert calls == ["alpha", "alpha"]


def test_a_new_workspaces_install_starts_once_its_create_is_done(
    env: Any,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Hermes's catalog install writes the root's config, so it holds the root's
    config lock for as long as it downloads (minutes on a slow network): started in
    the middle of a create, every later setup step of that create waited for it and
    the owner's "Create" hung. The install starts when the create is done."""
    import threading

    from agos_core.actions import docs

    client, _core, _runner, _home = env
    order: list[str] = []
    installed_now = threading.Event()
    real_docs = docs.ensure

    def docs_ensure(core: Any, workspace_id: str) -> None:
        order.append("docs")
        real_docs(core, workspace_id)

    def ensure(core: Any, key: str) -> bool:
        order.append(f"install {key}")
        installed_now.set()
        return True

    monkeypatch.setattr(docs, "ensure", docs_ensure)
    monkeypatch.setattr(memory_plugin, "ensure", ensure)
    a = ws(client, "Alpha")
    assert installed_now.wait(5)
    assert order.index("docs") < order.index(f"install {a}"), order


def test_installs_asked_for_during_a_setup_start_when_it_ends(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    started: list[str] = []
    monkeypatch.setattr(memory_plugin, "_start", lambda core, key: started.append(key))
    core = SimpleNamespace(engine=object())
    with memory_plugin.after_setup(core):  # type: ignore[arg-type]
        memory_plugin.install_new(core, "alpha")  # type: ignore[arg-type]
        memory_plugin.install_new(core, "alpha--a-editor")  # type: ignore[arg-type]
        assert started == []
    assert started == ["alpha", "alpha--a-editor"]
    memory_plugin.install_new(core, "bravo")  # type: ignore[arg-type]
    assert started == ["alpha", "alpha--a-editor", "bravo"]
    try:
        with memory_plugin.after_setup(core):  # type: ignore[arg-type]
            memory_plugin.install_new(core, "charlie")  # type: ignore[arg-type]
            raise RuntimeError("the create failed")
    except RuntimeError:
        pass
    assert started[-1] == "charlie"  # a profile was made: its install still runs
