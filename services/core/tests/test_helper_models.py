"""Settings → Helper models: Hermes's auxiliary models (one row per auxiliary task
Hermes has, and `agent.image_input_mode`), 100% Hermes.

- The tasks are Hermes's own (DEFAULT_CONFIG["auxiliary"], read at run time from
  Hermes's settings list); a task a Hermes upgrade adds fails the label guard
  until it is seen, and shows on the page meanwhile.
- Values are what Hermes reads (each profile with the managed scope on top), with
  whether it is Hermes's default; Save is Hermes's own `hermes config set` into its
  managed scope, "Use Hermes's default" its `hermes config unset`.
- AGOS picks no value: no start value on a new install, no owner default.
"""

import re
import runpy
from pathlib import Path
from typing import Any

import pytest
from test_agent_profiles import add_agent
from test_library import env, ws  # noqa: F401 - fixture

from agos_core.actions import hermes_managed
from agos_core.engine import config_file, helper_models
from agos_core.engine import hermes_schema as hs

HERMES = Path.home() / ".hermes" / "hermes-agent"
DEFAULTS_FILE = HERMES / "hermes_cli" / "config_defaults.py"
SRC = Path(__file__).resolve().parents[1] / "src" / "agos_core"
WEB = Path(__file__).resolve().parents[3] / "apps" / "web" / "src"

installed = pytest.mark.skipif(not DEFAULTS_FILE.is_file(), reason="Hermes isn't installed")


def _defaults() -> dict[str, Any]:
    found: dict[str, Any] = runpy.run_path(str(DEFAULTS_FILE))["DEFAULT_CONFIG"]
    return found


def _hermes_tasks(defaults: dict[str, Any]) -> list[str]:
    """Hermes's auxiliary tasks: every block of its `auxiliary` section that routes
    a model (has a provider), in Hermes's order."""
    return [
        name
        for name, block in defaults["auxiliary"].items()
        if isinstance(block, dict) and "provider" in block
    ]


def _fields(defaults: dict[str, Any] | None = None) -> list[hs.Field]:
    text = DEFAULTS_FILE.read_text() if DEFAULTS_FILE.is_file() else ""
    return hs.build({}, defaults or _defaults(), text, {"auxiliary.vision.api_key"})


@installed
def test_the_page_has_exactly_hermess_auxiliary_tasks() -> None:
    defaults = _defaults()
    assert helper_models.tasks(_fields(defaults)) == _hermes_tasks(defaults)
    # Every task Hermes has is seen (a plain label); none is stale. A task a
    # Hermes upgrade adds fails here until it is placed.
    assert set(helper_models.LABELS) == set(_hermes_tasks(defaults))


@installed
def test_a_task_hermes_adds_shows_by_itself() -> None:
    defaults = _defaults()
    defaults["auxiliary"]["brand_new"] = {"provider": "auto", "model": "", "api_key": ""}
    rows = {t.task: t for t in helper_models.rows(_fields(defaults))}
    assert "brand_new" in rows
    assert rows["brand_new"].label  # a readable name even without AGOS's label
    assert [f.key for f in rows["brand_new"].fields] == [
        "auxiliary.brand_new.provider",
        "auxiliary.brand_new.model",
    ]


@installed
def test_each_task_has_hermess_routing_fields_never_its_key() -> None:
    defaults = _defaults()
    for row in helper_models.rows(_fields(defaults)):
        block = defaults["auxiliary"][row.task]
        names = [f.key.rsplit(".", 1)[1] for f in row.fields]
        assert names == [n for n in helper_models.ROUTING if n in block], row.task
        assert "api_key" not in names and "key_env" not in names
        for field in row.fields:
            assert field.default == block[field.key.rsplit(".", 1)[1]]
    review = next(r for r in helper_models.rows(_fields(defaults)) if r.task == "review")
    assert "auxiliary.review.api_mode" in [f.key for f in review.fields]
    assert not helper_models.owns("auxiliary.vision.api_key")
    assert not helper_models.owns("auxiliary.vision.timeout")  # a timeout: Time limits
    assert helper_models.owns("auxiliary.vision.model")
    assert helper_models.owns(helper_models.IMAGE_MODE)


def test_agos_sets_no_default_for_any_helper_or_picture_key() -> None:
    from agos_core.engine import time_limits

    assert not [k for k in time_limits.owner_defaults() if helper_models.owns(k)]
    assert not [k for k in hermes_managed._defaults() if helper_models.owns(k)]
    # Not moved in, not settled: only the owner's own Save writes them.
    assert not [k for k in hermes_managed.by_card() if helper_models.owns(k)]
    for gone in ("VIDEO_DEFAULTS", "with_pictures", "VIDEO_GROUP", "VIDEO_PROVIDER"):
        assert not hasattr(time_limits, gone), gone
    for gone in ("PICTURE_MODEL", "VIDEO_MODEL"):
        assert not hasattr(time_limits, gone), gone


def test_a_new_install_starts_with_no_helper_model(env: Any) -> None:  # noqa: F811
    client, core, runner, _home = env
    a = ws(client, "Alpha")
    add_agent(client, a, "writer")
    managed = config_file.read(core.engine.settings.managed_home)
    assert "agent" not in managed or "image_input_mode" not in managed["agent"]
    for task in (managed.get("auxiliary") or {}).values():
        assert not {"provider", "model", "base_url", "api_mode"} & set(task), task
    hermes_managed.move_once(core)  # again: still nothing of these
    managed = config_file.read(core.engine.settings.managed_home)
    assert not any(
        helper_models.owns(".".join(("auxiliary", t, k)))
        for t, block in (managed.get("auxiliary") or {}).items()
        for k in block
    )
    writes = [c for c in runner.calls if "set" in c and any(helper_models.owns(x) for x in c)]
    assert not writes, writes


def _stub(core: Any, monkeypatch: Any) -> list[hs.Field]:
    defaults = {
        "agent": {"image_input_mode": "auto"},
        "auxiliary": {
            "transient_retries": 2,
            "vision": {
                "provider": "auto",
                "model": "",
                "base_url": "",
                "api_key": "",
                "timeout": 120,
            },
            "review": {
                "provider": "auto",
                "model": "",
                "base_url": "",
                "api_key": "",
                "api_mode": "",
            },
        },
    }
    fields = hs.build({}, defaults, "", {"auxiliary.vision.api_key", "auxiliary.review.api_key"})
    core.engine.config_schema = lambda: fields
    monkeypatch.setattr(hs, "image_modes", lambda: ["auto", "native", "text"])
    return fields


def _page(client: Any) -> dict[str, Any]:
    r = client.get("/preferences/hermes-helper-models")
    assert r.status_code == 200, r.text
    return dict(r.json())


def _field(page: dict[str, Any], key: str) -> dict[str, Any]:
    every = [f for t in page["tasks"] for f in t["fields"]] + [page["imageMode"]]
    return next(f for f in every if f["key"] == key)


def test_saved_and_reset_only_through_hermess_writer(env: Any, monkeypatch: Any) -> None:  # noqa: F811
    client, core, runner, _home = env
    _stub(core, monkeypatch)
    a = ws(client, "Alpha")
    add_agent(client, a, "writer")
    page = _page(client)
    assert [t["task"] for t in page["tasks"]] == ["vision", "review"]
    vision = _field(page, "auxiliary.vision.provider")
    assert vision["value"] == "auto" and vision["isDefault"] and not vision["managed"]
    assert page["imageMode"]["options"] == ["auto", "native", "text"]
    assert page["imageMode"]["value"] == "auto" and page["imageMode"]["isDefault"]

    written: list[tuple[dict[str, str], list[str]]] = []
    real = hermes_managed.write

    def spy(core: Any, sets: dict[str, str], unsets: Any = ()) -> None:
        written.append((dict(sets), list(unsets)))
        real(core, sets, unsets)

    monkeypatch.setattr(hermes_managed, "write", spy)
    body = {
        "sets": {
            "auxiliary.vision.provider": "openrouter",
            "auxiliary.vision.model": "google/gemini-2.5-flash",
            "agent.image_input_mode": "text",
        }
    }
    r = client.put("/preferences/hermes-helper-models", json=body)
    assert r.status_code == 200, r.text
    assert written == [(body["sets"], [])]
    # Hermes's own command, into the managed folder (no profile file written).
    sets = [c for c in runner.calls if "config" in c and "set" in c]
    assert any("auxiliary.vision.model" in c for c in sets)
    for key in (a, f"{a}--a-writer"):
        assert "auxiliary" not in config_file.read(core.engine.profile_home(key))
        seen = core.engine.as_hermes_reads([core.engine.profile_home(key)])
        got = next(iter(seen.values()))
        assert config_file.get(got, "auxiliary.vision.model") == "google/gemini-2.5-flash"
        assert config_file.get(got, "agent.image_input_mode") == "text"
    page = r.json()
    model = _field(page, "auxiliary.vision.model")
    assert model["value"] == "google/gemini-2.5-flash" and model["managed"]
    assert not model["isDefault"] and model["hermesDefault"] == ""
    assert _field(page, "agent.image_input_mode")["value"] == "text"

    # "Use Hermes's default": Hermes's `config unset`, nothing written instead.
    keys = ["auxiliary.vision.provider", "auxiliary.vision.model", "agent.image_input_mode"]
    r = client.put("/preferences/hermes-helper-models", json={"unsets": keys})
    assert r.status_code == 200, r.text
    assert written[-1] == ({}, keys)
    managed = config_file.read(core.engine.settings.managed_home)
    assert config_file.get(managed, "auxiliary.vision.model") is None
    page = r.json()
    assert _field(page, "auxiliary.vision.provider")["isDefault"]
    assert _field(page, "agent.image_input_mode")["value"] == "auto"


def test_what_isnt_a_helper_model_is_refused(env: Any, monkeypatch: Any) -> None:  # noqa: F811
    client, core, _runner, _home = env
    _stub(core, monkeypatch)
    ws(client, "Alpha")

    def put(body: dict[str, Any]) -> int:
        return int(client.put("/preferences/hermes-helper-models", json=body).status_code)

    assert put({"sets": {"auxiliary.vision.api_key": "sk-x"}}) == 400  # never a key
    assert put({"sets": {"auxiliary.vision.timeout": "5"}}) == 400  # Time limits'
    assert put({"sets": {"terminal.timeout": "5"}}) == 400
    assert put({"sets": {"auxiliary.vision.provider": "Open Router"}}) == 400
    assert put({"sets": {"auxiliary.vision.model": "bad model\nx"}}) == 400
    assert put({"sets": {"auxiliary.vision.base_url": "file:///etc/passwd"}}) == 400
    assert put({"sets": {"agent.image_input_mode": "sometimes"}}) == 400  # Hermes's modes
    assert put({"unsets": ["auxiliary.vision.api_key"]}) == 400
    managed = config_file.read(core.engine.settings.managed_home)
    assert config_file.get(managed, "auxiliary.vision.provider") is None


def test_a_value_hermes_holds_outside_its_list_is_shown(env: Any, monkeypatch: Any) -> None:  # noqa: F811
    """The live scope holds auxiliary.video.model (Hermes's video tool reads it; its
    DEFAULT_CONFIG has no video block): an ordinary Hermes value on the page, the
    owner decides."""
    client, core, _runner, _home = env
    _stub(core, monkeypatch)
    ws(client, "Alpha")
    core.engine.managed_write([("auxiliary.video.model", "google/gemini-2.5-flash")], [])
    page = _page(client)
    video = next(t for t in page["tasks"] if t["task"] == "video")
    assert not video["inHermesList"]
    field = _field(page, "auxiliary.video.model")
    assert field["value"] == "google/gemini-2.5-flash" and field["managed"]
    assert (
        client.put(
            "/preferences/hermes-helper-models", json={"unsets": ["auxiliary.video.model"]}
        ).status_code
        == 200
    )
    assert not any(t["task"] == "video" for t in _page(client)["tasks"])


def test_workspaces_that_differ_are_shown(env: Any, monkeypatch: Any) -> None:  # noqa: F811
    client, core, _runner, _home = env
    _stub(core, monkeypatch)
    a, b = ws(client, "Alpha"), ws(client, "Beta")
    core.engine.unmanaged_hermes(a, "config", "set", "auxiliary.vision.model", "m/one")
    field = _field(_page(client), "auxiliary.vision.model")
    assert field["spread"] and {s["value"] for s in field["spread"]} == {"m/one", ""}
    assert b


def test_the_hermes_settings_page_sends_these_keys_here() -> None:
    from agos_core.actions import hermes_all_settings as hall

    for key in (
        "auxiliary.compression.model",
        "auxiliary.vision.provider",
        "agent.image_input_mode",
    ):
        rule = hall._rule(key, set(), hall.card_keys(), {})
        assert rule is not None and rule["card"] == "helper-models", key
    assert hall.CARD_LABELS["helper-models"] == "Settings → Helper models"
    timeout = hall._rule("auxiliary.vision.timeout", set(), hall.card_keys(), {})
    assert timeout is not None and timeout["card"] == "time-limits"


def test_the_old_video_and_pictures_wording_is_gone() -> None:
    found = []
    for root in (SRC, WEB):
        for path in root.rglob("*.py" if root == SRC else "*.ts*"):
            if path.name.endswith(".d.ts"):
                continue
            text = path.read_text()
            if re.search(r"Video & pictures|watches videos|VIDEO_DEFAULTS|with_pictures", text):
                found.append(str(path))
    assert not found, found


@installed
def test_every_hermes_task_has_a_plain_name_and_sentence() -> None:
    """Soft guard: a task Hermes adds fails here until AGOS words it, but the page
    still shows it under Hermes's name (test_a_task_hermes_adds_shows_by_itself)."""
    for task in _hermes_tasks(_defaults()):
        name, sentence = helper_models.LABELS[task]
        assert name and sentence.endswith("."), task
        assert "auxiliary" not in name.lower() and "auxiliary" not in sentence.lower()
    assert helper_models.label("brand_new") == "Brand new"
    assert helper_models.summary("brand_new") == ""


def test_picture_modes_in_plain_words_from_hermess_list() -> None:
    choices = helper_models.image_choices(["auto", "native", "text", "later"])
    assert [c["value"] for c in choices] == ["auto", "native", "text", "later"]
    assert [c["label"] for c in choices[:3]] == [
        "Automatic",
        "Send pictures to the model",
        "Describe pictures first",
    ]
    assert choices[3] == {"value": "later", "label": "later", "hint": ""}


def test_picker_uses_the_model_catalogs_hermes_names(env: Any, monkeypatch: Any) -> None:  # noqa: F811
    """A pick is AGOS's picker choice (the /models/catalog providers, the same list
    as the Models page's pickers) and is written as Hermes's provider name from the
    catalog's own mapping (hermes_providers), with the model, by Hermes's writer."""
    from agos_core.api.models import CatalogProvider

    client, core, runner, _home = env
    _stub(core, monkeypatch)
    ws(client, "Alpha")
    entry = CatalogProvider.model_validate(
        {
            "id": "openai",
            "label": "OpenAI",
            "models": [
                {
                    "id": "gpt-5.4-mini",
                    "label": "GPT 5.4 Mini",
                    "modes": ["cli", "api"],
                    "efforts": [],
                    "default_effort": "",
                }
            ],
        }
    )
    written: list[tuple[dict[str, str], list[str]]] = []
    real = hermes_managed.write

    def spy(core: Any, sets: dict[str, str], unsets: Any = ()) -> None:
        written.append((dict(sets), list(unsets)))
        real(core, sets, unsets)

    monkeypatch.setattr(hermes_managed, "write", spy)
    pick = {"provider": "openai", "mode": "cli", "model": "gpt-5.4-mini"}
    r = client.put("/preferences/hermes-helper-models", json={"picks": {"vision": pick}})
    assert r.status_code == 200, r.text
    assert written == [
        (
            {
                "auxiliary.vision.provider": entry.hermes_providers["cli"],
                "auxiliary.vision.model": "gpt-5.4-mini",
            },
            [],
        )
    ]
    assert any("auxiliary.vision.provider" in c for c in runner.calls)
    route = next(t for t in r.json()["tasks"] if t["task"] == "vision")["route"]
    assert route == {
        "main": False,
        "provider": "openai-codex",
        "model": "gpt-5.4-mini",
        "baseUrl": "",
        "catalogProvider": "openai",
        "mode": "cli",
    }
    other = next(t for t in r.json()["tasks"] if t["task"] == "review")
    assert other["route"]["main"] and other["summary"] and other["label"] == "/review reviewer"


def test_same_as_the_main_model_unsets_the_tasks_keys(env: Any, monkeypatch: Any) -> None:  # noqa: F811
    client, core, _runner, _home = env
    _stub(core, monkeypatch)
    ws(client, "Alpha")
    core.engine.managed_write(
        [
            ("auxiliary.review.provider", "openrouter"),
            ("auxiliary.review.model", "m/x"),
            ("auxiliary.review.base_url", "https://example.test/v1"),
            ("auxiliary.vision.model", "m/keep"),
        ],
        [],
    )
    written: list[tuple[dict[str, str], list[str]]] = []
    real = hermes_managed.write

    def spy(core: Any, sets: dict[str, str], unsets: Any = ()) -> None:
        written.append((dict(sets), list(unsets)))
        real(core, sets, unsets)

    monkeypatch.setattr(hermes_managed, "write", spy)
    r = client.put("/preferences/hermes-helper-models", json={"picks": {"review": None}})
    assert r.status_code == 200, r.text
    assert written == [
        (
            {},
            ["auxiliary.review.provider", "auxiliary.review.model", "auxiliary.review.base_url"],
        )
    ]
    managed = config_file.read(core.engine.settings.managed_home)
    assert config_file.get(managed, "auxiliary.review.provider") is None
    assert config_file.get(managed, "auxiliary.vision.model") == "m/keep"  # other tasks stay
    review = next(t for t in r.json()["tasks"] if t["task"] == "review")
    assert review["route"]["main"]


def test_a_pick_drops_the_tasks_custom_endpoint(env: Any, monkeypatch: Any) -> None:  # noqa: F811
    """Hermes sends a task with a base_url to that address: a picker choice clears
    the one the managed scope holds, so the call goes where the owner picked."""
    client, core, _runner, _home = env
    _stub(core, monkeypatch)
    ws(client, "Alpha")
    core.engine.managed_write([("auxiliary.review.base_url", "https://example.test/v1")], [])
    pick = {"provider": "claude", "mode": "api", "model": "claude-haiku-4-5"}
    r = client.put("/preferences/hermes-helper-models", json={"picks": {"review": pick}})
    assert r.status_code == 200, r.text
    managed = config_file.read(core.engine.settings.managed_home)
    assert config_file.get(managed, "auxiliary.review.base_url") is None
    assert config_file.get(managed, "auxiliary.review.provider") == "anthropic"
    assert config_file.get(managed, "auxiliary.review.model") == "claude-haiku-4-5"


def test_a_pick_for_no_such_task_or_without_a_model_is_refused(env: Any, monkeypatch: Any) -> None:  # noqa: F811
    client, core, _runner, _home = env
    _stub(core, monkeypatch)
    ws(client, "Alpha")

    def put(picks: dict[str, Any]) -> int:
        body = {"picks": picks}
        return int(client.put("/preferences/hermes-helper-models", json=body).status_code)

    assert put({"nope": None}) == 400
    assert put({"vision": {"provider": "openai", "mode": "cli", "model": ""}}) == 400
    assert put({"vision": {"provider": "openai", "mode": "web", "model": "x"}}) == 422
    managed = config_file.read(core.engine.settings.managed_home)
    assert config_file.get(managed, "auxiliary.vision.provider") is None


def test_the_web_picks_helpers_with_the_shared_model_picker() -> None:
    """The helper rows use AGOS's ModelPicker fed by getModelCatalog (the logged-in
    providers' models, like every other picker), not text boxes for names."""
    page = (WEB / "features" / "settings" / "helper-models.tsx").read_text()
    assert "ModelPicker" in page and "Same as the main model" in page
    route = (WEB / "app" / "(app)" / "settings" / "[section]" / "page.tsx").read_text()
    block = route[route.index('case "helper-models"') :][:400]
    assert "getModelCatalog()" in block
