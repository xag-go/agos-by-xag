"""Settings → Models as a service (actions/services/settings/model_keys and
model_logins), without a real Hermes: a key is tested before it is saved and copied
into every root, a refused or failed Hermes call becomes the page's error with its
status (never the key's text), a login runs in the shared home or a workspace's own
root, and the routes of api/models.py only hand the service's answers on.

Hermes's own key test, pools and login flows are faked here (the real ones:
test_key_pools.py, test_workspace_logins.py, nightly)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from test_library import env, ws  # noqa: F401 - fixture

from agos_core.actions import apps, general_sync, hermes_all_settings
from agos_core.actions.errors import ActionError
from agos_core.actions.services.settings import model_catalog, model_keys, model_logins
from agos_core.engine import key_status, limits
from agos_core.engine.provider_keys import KeyCheck, KeyProblem

KEY = "sk-test-0000000000001234"


class Keys:
    """Hermes's key steps as model_keys calls them; `fail` names the step that fails."""

    def __init__(self, settings: Any) -> None:
        self.saved = SAVED  # Hermes's .env: one for every ProviderKeys made
        self.fail: dict[str, Exception] = {}
        self.ok = True
        self.probed: KeyCheck | None = None
        KEYS.append(self)

    def _maybe(self, step: str) -> None:
        if step in self.fail:
            raise self.fail[step]

    def probe(self, name: str, key: str) -> KeyCheck | None:
        self._maybe("probe")
        return self.probed

    def check(self, name: str, key: str) -> KeyCheck:
        self._maybe("check")
        return KeyCheck(self.ok, "Key works." if self.ok else "Wrong key.")

    def save_env(self, name: str, key: str) -> None:
        self._maybe("save")
        self.saved[name] = key

    def remove_env(self, name: str) -> None:
        self._maybe("remove")
        self.saved.pop(name, None)

    def stored(self, name: str) -> str:
        return self.saved.get(name, "")


KEYS: list[Keys] = []
SAVED: dict[str, str] = {}

PROVIDERS: list[dict[str, Any]] = [
    {"id": "openai", "apiKey": True, "keyEnvs": ["OPENAI_API_KEY"], "api": {}},
    {"id": "claude", "apiKey": False, "keyEnv": None, "api": None},
    {"id": "groq", "more": True, "keyEnv": "GROQ_API_KEY", "api": None},
]


@pytest.fixture
def keys(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> SimpleNamespace:
    KEYS.clear()
    SAVED.clear()
    SAVED["OPENAI_API_KEY"] = KEY
    done: dict[str, list[Any]] = {"synced": [], "remembered": [], "refreshed": []}
    catalog: dict[str, Any] = {"catalog": [{"id": "openai"}]}

    def load(core: Any, refresh: bool) -> dict[str, Any]:
        if refresh:
            done["refreshed"].append(True)
        return {"providers": [dict(p) for p in PROVIDERS], **catalog}

    monkeypatch.setattr(model_keys, "ProviderKeys", Keys)
    monkeypatch.setattr(model_catalog, "load", load)
    monkeypatch.setattr(model_catalog, "roots", lambda core: [("w1", "W", tmp_path)])
    monkeypatch.setattr(general_sync, "general_values", lambda core: {"OPENAI_API_KEY": KEY})
    monkeypatch.setattr(general_sync, "pools", lambda core, homes: [[]])
    monkeypatch.setattr(general_sync, "remember_name", lambda core, n: done["remembered"].append(n))
    monkeypatch.setattr(general_sync, "sync", lambda core: done["synced"].append(1))
    monkeypatch.setattr(hermes_all_settings, "warm_after_write", lambda core: None)
    monkeypatch.setattr(
        key_status,
        "status",
        lambda pools, names: SimpleNamespace(status="ok", at="t", problem=""),
    )
    core = SimpleNamespace(engine=SimpleNamespace(settings=SimpleNamespace(hermes_home=tmp_path)))
    return SimpleNamespace(core=core, done=done, catalog=catalog)


def test_a_providers_row_shows_its_keys_end_and_hermess_state(keys: Any) -> None:
    rows = {r["id"]: r for r in model_keys.providers(keys.core)}
    assert rows["openai"]["api"] == {
        "last4": "1234",
        "status": "ok",
        "statusAt": "t",
        "problem": "",
    }
    assert rows["openai"]["keyEnv"] == "OPENAI_API_KEY" and "keyEnvs" not in rows["openai"]
    assert rows["claude"]["api"] is None


def test_a_key_is_tested_then_saved_into_every_root(keys: Any) -> None:
    assert model_keys.save_key(keys.core, "openai", KEY)["ok"]
    assert KEYS[-1].saved["OPENAI_API_KEY"] == KEY
    assert keys.done["remembered"] == ["OPENAI_API_KEY"] and keys.done["synced"]
    with pytest.raises(ActionError, match="takes no API key"):
        model_keys.save_key(keys.core, "claude", KEY)


@pytest.mark.parametrize(
    ("step", "error", "status", "words"),
    [
        ("check", KeyProblem("Bad key shape."), 422, "Bad key shape."),
        ("check", OSError("boom"), 503, "did not test"),
        ("save", RuntimeError(KEY), 503, "did not save"),
    ],
)
def test_a_failed_key_step_is_the_pages_error_never_the_key(
    keys: Any, monkeypatch: pytest.MonkeyPatch, step: str, error: Exception, status: int, words: str
) -> None:
    real = Keys

    def failing(settings: Any) -> Keys:
        made = real(settings)
        made.fail[step] = error
        return made

    monkeypatch.setattr(model_keys, "ProviderKeys", failing)
    with pytest.raises(ActionError) as caught:
        model_keys.save_key(keys.core, "openai", KEY)
    assert caught.value.status == status and words in str(caught.value)
    assert KEY not in str(caught.value)


def test_a_wrong_key_is_refused_before_it_is_saved(
    keys: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    def wrong(settings: Any) -> Keys:
        made = Keys(settings)
        made.ok = False
        made.saved.clear()
        return made

    monkeypatch.setattr(model_keys, "ProviderKeys", wrong)
    with pytest.raises(ActionError, match="Wrong key"):
        model_keys.save_key(keys.core, "openai", KEY)
    assert KEYS[-1].saved == {}


def test_another_hermes_provider_uses_hermess_probe_and_its_catalog(keys: Any) -> None:
    found = model_keys.save_key(keys.core, "groq", KEY)
    assert found["ok"] and "found no models" in found["message"]
    keys.catalog["catalog"] = [{"id": "groq"}]
    assert model_keys.save_key(keys.core, "groq", KEY)["message"].startswith("Key saved.")
    assert model_keys.test_key(keys.core, "groq") == {"ok": True, "message": "Key works."}


@pytest.mark.parametrize(("error", "status"), [(KeyProblem("Bad."), 422), (OSError("x"), 503)])
def test_another_providers_refused_save_is_the_pages_error(
    keys: Any, monkeypatch: pytest.MonkeyPatch, error: Exception, status: int
) -> None:
    def failing(settings: Any) -> Keys:
        made = Keys(settings)
        made.fail["save"] = error
        return made

    monkeypatch.setattr(model_keys, "ProviderKeys", failing)
    with pytest.raises(ActionError) as caught:
        model_keys.save_key(keys.core, "groq", KEY)
    assert caught.value.status == status


def test_hermess_probe_refusing_the_key_stops_the_save(
    keys: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refusing(settings: Any) -> Keys:
        made = Keys(settings)
        made.probed = KeyCheck(False, "Groq says no.")
        return made

    monkeypatch.setattr(model_keys, "ProviderKeys", refusing)
    with pytest.raises(ActionError, match="Groq says no"):
        model_keys.save_key(keys.core, "groq", KEY)
    assert "GROQ_API_KEY" not in KEYS[-1].saved


def test_the_saved_key_is_tested_again_and_removed_everywhere(
    keys: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert model_keys.test_key(keys.core, "openai") == {"ok": True, "message": "Key works."}
    model_keys.remove_key(keys.core, "openai")
    assert KEYS[-1].saved == {} and keys.done["refreshed"]
    with pytest.raises(ActionError) as caught:  # nothing saved any more
        model_keys.test_key(keys.core, "openai")
    assert caught.value.status == 404

    def failing(settings: Any) -> Keys:
        made = Keys(settings)
        made.fail.update(check=OSError("x"), remove=KeyProblem("Locked."))
        return made

    monkeypatch.setattr(model_keys, "ProviderKeys", failing)
    SAVED["OPENAI_API_KEY"] = KEY
    with pytest.raises(ActionError) as answered:
        model_keys.test_key(keys.core, "openai")
    assert answered.value.status == 503
    with pytest.raises(ActionError, match="Locked"):
        model_keys.remove_key(keys.core, "openai")


def test_no_engine_no_keys() -> None:
    with pytest.raises(ActionError) as caught:
        model_keys.test_key(SimpleNamespace(engine=None), "openai")  # type: ignore[arg-type]
    assert caught.value.status == 503


# ---- logins -------------------------------------------------------------------------


class Logins:
    """Hermes's login flows as model_logins calls them (engine/provider_login.py)."""

    def __init__(self, settings: Any, is_connected: Any, on_connected: Any, **kw: Any) -> None:
        self.is_connected, self.on_connected = is_connected, on_connected
        self.calls: list[tuple[Any, ...]] = []
        self.fail: Exception | None = None

    def _view(self, *args: Any) -> dict[str, Any]:
        self.calls.append(args)
        if self.fail is not None:
            raise self.fail
        return {"provider": args[1], "status": "waiting"}

    def start(self, *a: Any) -> dict[str, Any]:
        return self._view("start", *a)

    def get(self, *a: Any) -> dict[str, Any]:
        return self._view("get", *a)

    def send_code(self, *a: Any) -> dict[str, Any]:
        return self._view("code", *a)

    def cancel(self, *a: Any) -> dict[str, Any]:
        return self._view("cancel", *a)

    def logout(self, *a: Any) -> None:
        self._view("logout", *a)


@pytest.fixture
def logins(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> SimpleNamespace:
    seen: dict[str, list[Any]] = {"own": [], "forgot": [], "refreshed": []}
    rows = [
        {"id": "claude", "cli": {"account": "me@x", "installed": True}},
        {"id": "kimi", "more": True, "cli": {"account": None, "installed": True}},
    ]

    class Catalog:
        def root_logins(self, root: Path) -> set[str]:
            return {"anthropic"}

        def load(self, refresh: bool = False) -> dict[str, Any]:
            if refresh:
                seen["refreshed"].append(True)
            return {"providers": rows}

    monkeypatch.setattr(model_logins, "ProviderLogins", Logins)
    monkeypatch.setattr(model_catalog, "catalog_of", lambda core: Catalog())
    monkeypatch.setattr(model_catalog, "roots", lambda core: [("w1", "W", tmp_path)])
    monkeypatch.setattr(model_catalog, "load", lambda core, refresh: {})
    monkeypatch.setattr(apps, "nous_signed_in", lambda core: True)
    monkeypatch.setattr(
        general_sync,
        "hermes_logins",
        lambda engine, home: {"signed_in_state": ["xai-oauth"]},
    )
    monkeypatch.setattr(general_sync, "own_logins_only", lambda core, w: seen["own"].append(w))
    monkeypatch.setattr(limits, "forget", lambda: seen["forgot"].append(1))
    engine = SimpleNamespace(
        settings=SimpleNamespace(hermes_home=tmp_path), root=lambda w: tmp_path / w
    )
    return SimpleNamespace(core=SimpleNamespace(engine=engine), seen=seen)


def test_one_login_object_knows_where_each_provider_is_signed_in(logins: Any) -> None:
    found = cast(Logins, model_logins.logins(logins.core))
    assert cast(Logins, model_logins.logins(logins.core)) is found  # made once, kept
    assert found.is_connected("claude", "w1")  # the workspace's own root
    assert not found.is_connected("openai", "w1")
    assert found.is_connected("xai", None) and found.is_connected("nous", None)
    assert found.is_connected("claude", None) and not found.is_connected("kimi", None)
    found.on_connected("claude", "w1")
    found.on_connected("claude", None)
    assert logins.seen["own"] == ["w1"] and len(logins.seen["forgot"]) == 2


def test_only_a_provider_with_a_sign_in_has_a_login(logins: Any) -> None:
    assert model_logins.provider_of("claude") == "claude"
    assert model_logins.provider_of("kimi", logins.core) == "kimi"
    with pytest.raises(ActionError) as caught:
        model_logins.provider_of("groq", logins.core)
    assert caught.value.status == 404


def test_a_workspace_login_is_for_its_own_root_and_its_own_subscriptions(logins: Any) -> None:
    assert model_logins.workspace_of(logins.core, "w1", "claude") == "w1"
    for workspace, provider, status in (("w9", "claude", 404), ("w1", "nous", 409)):
        with pytest.raises(ActionError) as caught:
            model_logins.workspace_of(logins.core, workspace, provider)
        assert caught.value.status == status


def test_each_login_step_runs_in_the_shared_home_or_the_workspaces_root(logins: Any) -> None:
    core = logins.core
    for workspace in (None, "w1"):
        assert model_logins.start(core, "claude", workspace)["status"] == "waiting"
        model_logins.status(core, "claude", workspace)
        model_logins.send_code(core, "claude", "123", workspace)
        model_logins.cancel(core, "claude", workspace)
        model_logins.logout(core, "claude", workspace)
    calls = cast(Logins, model_logins.logins(core)).calls
    assert ("start", "claude") in calls and ("start", "claude", "w1") in calls
    assert ("code", "claude", "123", "w1") in calls and ("logout", "claude", "w1") in calls


@pytest.mark.parametrize("workspace", [None, "w1"])
def test_a_login_hermes_could_not_run_is_the_pages_error(logins: Any, workspace: Any) -> None:
    found = cast(Logins, model_logins.logins(logins.core))
    found.fail = RuntimeError("no browser")
    with pytest.raises(ActionError) as started:
        model_logins.start(logins.core, "claude", workspace)
    assert started.value.status == 503
    with pytest.raises(ActionError) as left:
        model_logins.logout(logins.core, "claude", workspace)
    assert left.value.status == 503
    found.fail = ValueError("No login is waiting for a code.")
    with pytest.raises(ActionError) as coded:
        model_logins.send_code(logins.core, "claude", "1", workspace)
    assert coded.value.status == 409


def test_account_limits_need_hermes(logins: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    assert model_logins.account_limits(SimpleNamespace(engine=None)) == []  # type: ignore[arg-type]

    def broken(settings: Any) -> str:
        raise RuntimeError("no Hermes")

    monkeypatch.setattr(model_logins, "hermes_python", broken)
    assert model_logins.account_limits(logins.core) == []
    monkeypatch.setattr(model_logins, "hermes_python", lambda settings: "/py")
    monkeypatch.setattr(limits, "account_limits", lambda s, py, kept: iter([1]))
    assert model_logins.account_limits(logins.core) == [1]
    with pytest.raises(ActionError):
        model_logins.logins(SimpleNamespace(engine=None))  # type: ignore[arg-type]


# ---- the routes hand the service's answers on ---------------------------------------


def test_the_models_routes_hand_on_the_services_answers(
    env: Any,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _core, _runner, _home = env
    a = ws(client, "Alpha")
    view = {
        "provider": "claude",
        "status": "waiting",
        "url": "https://x",
        "userCode": None,
        "needsCode": True,
        "message": "",
    }
    row = {
        "id": "openai",
        "name": "OpenAI",
        "cli": {"tool": "codex", "installed": False, "account": None, "loginCommand": ""},
        "api": None,
        "apiKey": True,
    }
    asked: list[tuple[Any, ...]] = []

    def answer(name: str, out: Any) -> Any:
        def call(*args: Any) -> Any:
            asked.append((name, *args[1:]))
            return out

        return call

    monkeypatch.setattr(model_keys, "providers", answer("providers", [row]))
    monkeypatch.setattr(model_keys, "save_key", answer("save", {"ok": True, "message": "Saved."}))
    monkeypatch.setattr(model_keys, "test_key", answer("test", {"ok": True, "message": "Works."}))
    monkeypatch.setattr(model_keys, "remove_key", answer("remove", None))
    for step in ("start", "status", "send_code", "cancel"):
        monkeypatch.setattr(model_logins, step, answer(step, view))
    monkeypatch.setattr(model_logins, "logout", answer("logout", None))
    monkeypatch.setattr(model_logins, "provider_of", lambda provider, core=None: provider)
    monkeypatch.setattr(model_logins, "workspace_of", lambda core, w, provider: w)

    assert client.get("/models/providers").json()[0]["id"] == "openai"
    base = "/models/providers/openai/key"
    assert client.put(base, json={"key": KEY}).json() == {"ok": True, "message": "Saved."}
    assert client.post(base + "/test").json()["message"] == "Works."
    assert client.delete(base).status_code == 204
    for root in ("", f"/workspaces/{a}"):
        login = f"{root}/models/providers/claude/login"
        assert client.post(login).status_code == 201
        assert client.get(login).json()["status"] == "waiting"
        assert client.post(login + "/code", json={"code": "42"}).json()["needsCode"]
        assert client.delete(login).json()["url"] == "https://x"
        assert client.post(f"{root}/models/providers/claude/logout").status_code == 204
    assert ("save", "openai", KEY) in asked and ("send_code", "claude", "42", a) in asked
    assert ("logout", "claude", a) in asked and ("logout", "claude") in asked
