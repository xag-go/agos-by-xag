"""Settings → Hermes settings: every Hermes setting, built from Hermes's own schema
and defaults (no AGOS list of keys), as each workspace's Hermes has it, changed
with `hermes config set` into every root and member. AGOS's forced keys are shown
read-only with the reason; a key a Hermes upgrade adds shows up by itself."""

import json
import runpy
from pathlib import Path
from typing import Any

import pytest
from split_parts import is_part_of
from test_agent_profiles import add_agent
from test_library import env, ws  # noqa: F401 - fixture

from agos_core.actions import hermes_all_settings as hall
from agos_core.engine import config_file
from agos_core.engine import hermes_schema as hs

HERMES = Path.home() / ".hermes" / "hermes-agent"
DEFAULTS_FILE = HERMES / "hermes_cli" / "config_defaults.py"
installed = pytest.mark.skipif(not DEFAULTS_FILE.is_file(), reason="Hermes isn't installed")

SOURCE = """
DEFAULT_CONFIG = {
    # The model.
    "model": "",
    "approvals": {
        # How commands are approved.
        "mode": "smart",
        "cron_mode": "deny",  # what a cron run does
        "deny": [],
    },
    # Pools of keys.
    "credential_pool_strategies": {},
}
"""


def _defaults() -> dict[str, Any]:
    found: dict[str, Any] = runpy.run_path(str(DEFAULTS_FILE))["DEFAULT_CONFIG"]
    return found


def _installed_fields(extra: dict[str, Any] | None = None) -> list[hs.Field]:
    """The page's list from the installed Hermes's defaults (its schema walk is
    the same: one field per leaf), plus anything a test adds."""
    defaults = _defaults()
    for key, value in (extra or {}).items():
        node = defaults
        *parents, last = key.split(".")
        for part in parents:
            node = node.setdefault(part, {})
        node[last] = value
    return hs.build({}, defaults, DEFAULTS_FILE.read_text())


def test_hermes_comments_are_the_descriptions() -> None:
    notes = hs.comments(SOURCE)
    assert notes["model"] == "The model."
    assert notes["approvals.mode"] == "How commands are approved."
    assert notes["approvals.cron_mode"] == "what a cron run does"
    fields = {
        f.key: f
        for f in hs.build(
            {"approvals.deny": {"type": "list", "description": "Approvals → Deny"}},
            {
                "model": "",
                "approvals": {"mode": "smart", "cron_mode": "deny", "deny": []},
                "credential_pool_strategies": {},
            },
            SOURCE,
        )
    }
    # The schema's field; the empty section its walk skips is a setting too.
    assert fields["approvals.deny"].type == "list"
    assert fields["credential_pool_strategies"].type == "object"
    assert fields["credential_pool_strategies"].description == "Pools of keys."
    # No comment of its own: its section's.
    assert fields["approvals.deny"].description == "Approvals → Deny"


@installed
def test_a_key_a_hermes_upgrade_adds_shows_up_by_itself() -> None:
    fields = {
        f.key: f
        for f in _installed_fields(
            {"kanban.brand_new_knob": 3, "brand_new_section.flag": True, "curator.new_one": "x"}
        )
    }
    assert fields["kanban.brand_new_knob"].group == hs.KANBAN
    assert fields["curator.new_one"].group == hs.MEMORY
    # A section AGOS has never seen: listed under Runtime, never dropped.
    assert fields["brand_new_section.flag"].group == hs.RUNTIME
    assert fields["brand_new_section.flag"].type == "boolean"


@installed
def test_every_hermes_setting_is_listed_and_the_ones_that_matter_are_where_he_looks() -> None:
    fields = {f.key: f for f in _installed_fields()}
    assert set(fields) == set(hs.leaves(_defaults()))
    want = {
        "approvals.cron_mode": hs.SAFETY,
        "approvals.deny": hs.SAFETY,
        "command_allowlist": hs.SAFETY,
        "memory.write_approval": hs.SAFETY,
        "skills.write_approval": hs.SAFETY,
        "security.website_blocklist.domains": hs.SAFETY,
        "terminal.container_memory": hs.SAFETY,
        "credential_pool_strategies": hs.COST,
        "delegation.model": hs.COST,
        "auxiliary.compression.model": hs.COST,
        "compression.threshold": hs.COST,
        "checkpoints.enabled": hs.RUNTIME,
        "curator.enabled": hs.MEMORY,
        "kanban.dispatch_interval_seconds": hs.KANBAN,
        "display.show_reasoning": hs.CHATS,
        "discord.require_mention": hs.NOT_USED,
    }
    for key, group in want.items():
        assert key in fields, key
        assert fields[key].group == group, key
    assert {f.group for f in fields.values()} == set(hs.GROUPS) - {hs.ENV}  # .env: own rows
    # Hermes's own words, not only the key's name.
    assert "fnmatch" in fields["approvals.deny"].description
    assert fields["checkpoints.enabled"].description.startswith("Filesystem checkpoints")


def test_every_key_agos_forces_has_its_reason() -> None:
    forced = hall.forced_keys()
    assert forced == set(hall.FORCED_WHY), (
        sorted(forced - set(hall.FORCED_WHY)),
        sorted(set(hall.FORCED_WHY) - forced),
    )
    assert all(reason.strip() for reason in hall.FORCED_WHY.values())
    # The keys an AGOS card changes come from those cards' own modules.
    cards = hall.card_keys()
    assert cards["approvals.mode"] == "access"
    assert cards["terminal.timeout"] == "time-limits"
    assert cards["fallback_providers"] == "fallback"
    assert cards["goals.max_turns"] == "workspace-settings"
    assert set(cards.values()) <= set(hall.CARD_LABELS)


def test_secrets_never_reach_the_web() -> None:
    value = {"fakellm": {"base_url": "http://x", "api_key": "sk-123", "key_env": "X"}}
    secrets = {("providers", "fakellm", "api_key")}
    assert hs.masked(value, secrets, "providers") == {
        "fakellm": {"base_url": "http://x", "api_key": hs.MASK, "key_env": "X"}
    }
    assert hs.holds_secret(secrets, "providers") and not hs.holds_secret(secrets, "model")


def test_the_page_masks_what_hermess_own_masker_masks(env: Any) -> None:  # noqa: F811
    """M1 (925047d area 1): which values are secrets is Hermes's rule
    (hermes_cli/config.py redact_config_value / _is_secret_config_key), not an AGOS
    regex: an MCP server's `Authorization` / `X-API-Key` header, a bare `key`, an
    env map's `FAL_KEY` are hidden; a `${VAR}` reference and `token_count` stay."""
    client, core, _runner, _home = env
    _stub_schema(core)
    a = ws(client, "Alpha")
    home = core.engine.profile_home(a)
    config = config_file.read(home)
    config["mcp_servers"] = {
        "crm": {
            "url": "https://crm.example",
            "headers": {"Authorization": "Bearer literal-crm-0001", "X-API-Key": "hdr-key-0002"},
            "env": {"FAL_KEY": "fal-key-value-0003", "REGION": "eu"},
            "key": "bare-key-value-0004",
        },
        "ref": {"headers": {"Authorization": "${CRM_TOKEN}"}, "token_count": 5},
    }
    import yaml

    (home / "config.yaml").write_text(yaml.safe_dump(config))
    body = client.get("/preferences/hermes-settings").json()
    text = json.dumps(body)
    for leak in ("literal-crm-0001", "hdr-key-0002", "fal-key-value-0003", "bare-key-value-0004"):
        assert leak not in text, leak
    assert "${CRM_TOKEN}" in text and '"REGION": "eu"' in text
    assert '"token_count": 5' in text


def _stub_schema(core: Any) -> None:
    fields = hs.build(
        {},
        {
            "checkpoints": {"enabled": False, "max_snapshots": 50},
            "approvals": {"mode": "smart", "cron_mode": "deny", "deny": []},
            "display": {"show_reasoning": True},
            "auxiliary": {"compression": {"model": "", "api_key": ""}},
            "providers": {},
            "sessions": {"auto_prune": True},
            "proxy": {"enabled": False, "enforce_on_docker": True},
            "delegation": {"provider": "", "model": ""},
            "agent": {"disabled_toolsets": []},
        },
        "",
        {"auxiliary.compression.api_key"},  # Hermes's _is_secret_config_key says so
    )
    core.engine.config_schema = lambda: fields


def _value(core: Any, key: str, setting: str) -> Any:
    return config_file.get(config_file.read(core.engine.profile_home(key)), setting)


def _row(client: Any, key: str) -> dict[str, Any]:
    r = client.get("/preferences/hermes-settings")
    assert r.status_code == 200, r.text
    return next(s for s in r.json()["settings"] if s["key"] == key)


def test_the_page_shows_each_value_and_writes_into_every_root_and_member(env: Any) -> None:  # noqa: F811
    client, core, runner, _home = env
    _stub_schema(core)
    a, b = ws(client, "Alpha"), ws(client, "Beta")
    add_agent(client, a, "writer")
    body = client.get("/preferences/hermes-settings").json()
    assert body["groups"][0] == hs.SAFETY
    row = _row(client, "checkpoints.enabled")
    assert row["value"] is False and row["default"] is False
    assert row["editable"] and row["rule"] is None and row["same"]

    runner.calls.clear()
    r = client.put(
        "/preferences/hermes-settings", json={"key": "checkpoints.enabled", "value": True}
    )
    assert r.status_code == 200, r.text
    assert r.json()["value"] is True
    for key in (a, f"{a}--a-writer", b):
        assert str(_value(core, key, "checkpoints.enabled")).lower() == "true", key
    sets = [c for c in runner.calls if "config" in c and "set" in c]
    assert all("--force" in c and "checkpoints.enabled" in c for c in sets)
    assert len(sets) == 3
    # Saved again: nothing to write.
    runner.calls.clear()
    client.put("/preferences/hermes-settings", json={"key": "checkpoints.enabled", "value": True})
    assert not [c for c in runner.calls if "config" in c and "set" in c]

    # One workspace only: the page shows where they differ.
    r = client.put(
        "/preferences/hermes-settings",
        json={"key": "checkpoints.max_snapshots", "value": 7, "workspaceId": b},
    )
    assert r.status_code == 200, r.text
    row = r.json()
    assert not row["same"]
    by_ws = {w["id"]: w for w in row["workspaces"]}
    assert by_ws[b]["value"] == 7
    assert by_ws[a]["value"] == 50

    # Hermes takes no checkpoints in a container backend (AGOS's sandbox): said.
    assert "takes no checkpoints" in _row(client, "checkpoints.enabled")["notes"][0]["reason"]
    # Back to Hermes's default: Hermes's own unset.
    r = client.put(
        "/preferences/hermes-settings", json={"key": "checkpoints.enabled", "reset": True}
    )
    assert r.status_code == 200, r.text
    assert r.json()["value"] is False
    assert _value(core, a, "checkpoints.enabled") is None


def test_what_agos_forces_or_a_card_changes_is_read_only_with_why(env: Any) -> None:  # noqa: F811
    client, core, _runner, _home = env
    _stub_schema(core)
    a = ws(client, "Alpha")
    reload = _row(client, "approvals.mcp_reload_confirm")
    assert reload["rule"]["kind"] == "forced" and not reload["editable"]
    assert reload["rule"]["reason"] == hall.FORCED_WHY["approvals.mcp_reload_confirm"]
    assert reload["value"] is False
    mode = _row(client, "approvals.mode")
    assert mode["rule"]["kind"] == "card" and mode["rule"]["card"] == "access"
    # A forced key Hermes's defaults don't list is still shown.
    dm = _row(client, "unauthorized_dm_behavior")
    assert dm["inDefaults"] is False and dm["rule"]["kind"] == "choice"
    # The bot card's keys: read-only here, with the way to the bot's card.
    for key in ("telegram.reactions", "platforms.telegram.enabled"):
        bot = _row(client, key)
        assert bot["rule"]["kind"] == "card" and bot["rule"]["card"] == "bot", key
        assert not bot["editable"]
    for key in ("approvals.mcp_reload_confirm", "approvals.mode", "telegram.reactions"):
        r = client.put("/preferences/hermes-settings", json={"key": key, "value": "deny"})
        assert r.status_code == 409, r.text
    # Hermes's iron-proxy would collide with AGOS's egress proxy: kept, with why.
    for key in ("proxy.enforce_on_docker", "proxy.enabled"):
        proxy = _row(client, key)
        assert proxy["rule"]["kind"] == "locked" and not proxy["editable"], key
        assert "check_docker_env_collisions" in proxy["rule"]["reason"]
        r = client.put("/preferences/hermes-settings", json={"key": key, "value": False})
        assert r.status_code == 409, r.text
    # AGOS's start value: his to change.
    prune = _row(client, "sessions.auto_prune")
    assert prune["rule"]["kind"] == "seeded" and prune["editable"]
    # A secret: never sent, never written here.
    secret = _row(client, "auxiliary.compression.api_key")
    assert secret["rule"]["kind"] == "secret" and not secret["editable"]
    # A mapping holding one (a provider's inline api_key): hidden, read-only here.
    core.engine._hermes(a, "config", "set", "--force", "providers", '{"x": {"api_key": "sk-1"}}')
    providers = _row(client, "providers")
    assert "sk-1" not in str(providers)
    assert providers["rule"]["kind"] == "secret" and not providers["editable"]


def test_every_owner_choice_is_written_by_agos_and_none_is_forced() -> None:
    from agos_core.engine import owner_choices

    assert set(hall.choice_keys()) == set(owner_choices.WHY)
    assert not set(owner_choices.WHY) & set(hall.FORCED_WHY)
    assert all(why.strip() for why in owner_choices.WHY.values())


def test_agos_recommendation_is_his_choice_and_a_sync_keeps_it(env: Any) -> None:  # noqa: F811
    from agos_core.actions import access, library

    client, core, _runner, _home = env
    _stub_schema(core)
    a = ws(client, "Alpha")
    cron = _row(client, "approvals.cron_mode")
    assert cron["rule"]["kind"] == "choice" and cron["editable"]
    assert cron["rule"]["recommended"] == "approve" and cron["value"] == "approve"
    assert "AGOS recommends" in cron["rule"]["reason"]
    limit = _row(client, "memory.memory_char_limit")
    assert limit["rule"]["recommended"] == 1000000 and limit["editable"]
    r = client.put(
        "/preferences/hermes-settings", json={"key": "approvals.cron_mode", "value": "deny"}
    )
    assert r.status_code == 200, r.text
    r = client.put(
        "/preferences/hermes-settings", json={"key": "memory.memory_char_limit", "value": 5000}
    )
    assert r.status_code == 200, r.text
    # Every AGOS writer runs again: his values stay.
    (core.engine.profile_home(a) / ".agos-applied").unlink(missing_ok=True)
    (core.engine.profile_home(a) / ".agos-connectors").unlink(missing_ok=True)
    from agos_core.actions import engine as engine_actions

    engine_actions.sync_workspace(core, a)
    assert library.apply_workspace(core, a) is None
    access.set_workspace(core, a, False)
    assert _value(core, a, "approvals.cron_mode") == "deny"
    assert str(_value(core, a, "memory.memory_char_limit")) == "5000"
    # A new member starts on its Co-Founder's choice, not on AGOS's.
    add_agent(client, a, "writer")
    assert _value(core, f"{a}--a-writer", "approvals.cron_mode") == "deny"
    assert str(_value(core, f"{a}--a-writer", "memory.memory_char_limit")) == "5000"


def test_a_new_member_takes_what_he_changed_for_its_cofounder(env: Any) -> None:  # noqa: F811
    client, core, _runner, _home = env
    _stub_schema(core)
    a = ws(client, "Alpha")
    r = client.put(
        "/preferences/hermes-settings", json={"key": "checkpoints.max_snapshots", "value": 7}
    )
    assert r.status_code == 200, r.text
    add_agent(client, a, "writer")
    assert str(_value(core, f"{a}--a-writer", "checkpoints.max_snapshots")) == "7"
    # And a new workspace, what every other workspace has.
    b = ws(client, "Beta")
    assert str(_value(core, b, "checkpoints.max_snapshots")) == "7"


def test_model_keys_are_one_choice_and_members_toolsets_say_why(env: Any) -> None:  # noqa: F811
    client, core, _runner, _home = env
    _stub_schema(core)
    a = ws(client, "Alpha")
    add_agent(client, a, "writer")
    # A provider key with its model key beside it (Hermes's own list): one choice,
    # edited with the model picker on the page.
    for key in ("delegation.provider", "delegation.model"):
        row = _row(client, key)
        assert row["pair"] == {"provider": "delegation.provider", "model": "delegation.model"}
    # A card's model keys aren't paired here (the card changes them).
    assert _row(client, "auxiliary.compression.model")["pair"] is None
    # A member's extra toolsets off, each with its reason.
    row = _row(client, "agent.disabled_toolsets")
    notes = {n["value"]: n for n in row["notes"]}
    assert "cronjob" in notes, row
    assert "Co-Founder" in notes["cronjob"]["reason"]
    assert notes["cronjob"]["label"].endswith("writer")


def test_hermes_env_settings_show_with_what_hermes_really_uses(env: Any) -> None:  # noqa: F811
    """The page also lists Hermes's .env settings (its own registry): secrets masked
    and read-only, AGOS's forced lines with their reason, and where a .env line beats
    the config.yaml value (or the other way round), the value Hermes really uses."""
    client, core, _runner, _home = env
    _stub_schema(core)
    hs.keep_env(
        hs.env_vars(
            {
                "TELEGRAM_HOME_CHANNEL": {
                    "description": "Default chat ID",
                    "category": "messaging",
                },
                "API_SERVER_PORT": {"description": "API port", "category": "messaging"},
                "API_SERVER_KEY": {
                    "description": "Bearer",
                    "category": "messaging",
                    "password": True,
                },
                "TELEGRAM_ALLOW_ALL_USERS": {"description": "Anyone", "category": "messaging"},
                "DISCORD_HOME_CHANNEL": {"description": "Discord", "category": "messaging"},
                "TERMINAL_MAX_FOREGROUND_TIMEOUT": {"description": "Cap", "category": "tool"},
                "OPENAI_API_KEY": {"description": "", "category": "provider", "password": True},
            }
        )
    )
    a = ws(client, "Alpha")
    home = core.engine.profile_home(a)
    with (home / ".env").open("a") as f:
        f.write("TELEGRAM_REACTIONS=true\nTERMINAL_TIMEOUT=60\nTELEGRAM_HOME_CHANNEL=-100\n")
        f.write("OPENAI_API_KEY=sk-secret-1\nMY_CUSTOM_THING=hush\n")
        f.write("TERMINAL_MAX_FOREGROUND_TIMEOUT=100\n")  # a stale copy the scope beats
    core.engine._hermes(a, "config", "set", "--force", "telegram.reactions", "false")

    def env_in_use(path: Any) -> dict[str, Any]:
        if path != home:
            return {"used": {}, "yaml": {}}
        return {
            # What Hermes's gateway start had (stubbed: the real one runs gateway.run).
            "used": {
                "TELEGRAM_REACTIONS": "true",
                "TERMINAL_TIMEOUT": "300",
                "TERMINAL_MAX_FOREGROUND_TIMEOUT": "600",
            },
            "yaml": {"TELEGRAM_REACTIONS": "false", "TERMINAL_TIMEOUT": "300"},
            # The managed .env pins it (Hermes's load_managed_env, in the probe).
            "managed": ["TERMINAL_MAX_FOREGROUND_TIMEOUT"],
        }

    core.engine.env_in_use = env_in_use
    body = client.get("/preferences/hermes-settings").json()
    assert "sk-secret-1" not in str(body) and "hush" not in str(body)
    rows = {r["key"]: r for r in body["settings"]}
    home_channel = rows["TELEGRAM_HOME_CHANNEL"]
    assert home_channel["source"] == "env" and home_channel["group"] == hs.ENV
    assert home_channel["value"] == "-100" and home_channel["editable"]
    assert rows["DISCORD_HOME_CHANNEL"]["group"] == hs.NOT_USED
    assert rows["API_SERVER_PORT"]["rule"]["kind"] == "forced"
    assert "port" in rows["API_SERVER_PORT"]["rule"]["reason"]
    assert (
        rows["API_SERVER_KEY"]["rule"]["kind"] == "forced"
        and not rows["API_SERVER_KEY"]["editable"]
    )
    assert rows["TELEGRAM_ALLOW_ALL_USERS"]["rule"]["kind"] == "locked"
    assert rows["OPENAI_API_KEY"]["rule"]["kind"] == "secret"
    assert rows["OPENAI_API_KEY"]["value"] == hs.MASK
    assert rows["MY_CUSTOM_THING"]["rule"]["kind"] == "secret"  # unknown: a secret, like Hermes
    # .env beats config.yaml: the env row and the YAML row both say so.
    reactions = rows["TELEGRAM_REACTIONS"]
    assert reactions["rule"]["card"] == "bot"  # the bot card moves it into telegram.reactions
    assert reactions["value"] == "true"
    assert ".env beats config.yaml telegram.reactions" in reactions["notes"][0]["reason"]
    yaml_row = rows["telegram.reactions"]
    assert yaml_row["notes"][0]["value"] == "true"
    assert "TELEGRAM_REACTIONS beats" in yaml_row["notes"][0]["reason"]
    # config.yaml beats .env: the .env line is ignored, Hermes uses the YAML value.
    timeout = rows["TERMINAL_TIMEOUT"]
    assert timeout["rule"] is None and timeout["editable"]  # Hermes maps YAML onto it
    # terminal.timeout itself is in Hermes's managed scope (the Time limits card).
    assert "beats this .env line: the engine uses 300" in timeout["notes"][0]["reason"]
    assert timeout["notes"][0]["value"] == "300"
    # The managed scope's .env beats the profile's stale line: the value Hermes uses.
    pinned = rows["TERMINAL_MAX_FOREGROUND_TIMEOUT"]["notes"][0]
    assert pinned["value"] == "600" and "managed scope" in pinned["reason"]
    # Changed here with Hermes's own `hermes config set` (its .env writer).
    r = client.put(
        "/preferences/hermes-settings", json={"key": "TELEGRAM_HOME_CHANNEL", "value": "-200"}
    )
    assert r.status_code == 200, r.text
    assert config_file.read_env(home)["TELEGRAM_HOME_CHANNEL"] == "-200"
    r = client.put("/preferences/hermes-settings", json={"key": "API_SERVER_PORT", "value": "1"})
    assert r.status_code == 409
    hs.keep_env(None)


def test_every_forced_env_line_is_written_by_agos() -> None:
    src = Path(hall.__file__).resolve().parents[1]
    texts = [p.read_text() for p in src.rglob("*.py") if p.name != "hermes_all_settings.py"]
    text = "\n".join(t for t in texts if not is_part_of(t, "actions/hermes_all_settings.py"))
    for name in hall.FORCED_ENV_WHY:
        assert name.rstrip("*") in text, name


@installed
def test_telegram_extras_hermes_reads_get_rows_from_its_own_source() -> None:
    """Keys Hermes's Telegram adapter reads but DEFAULT_CONFIG doesn't list
    (group_topics, dm_topics, mention_patterns, reply_to_mode...): found in Hermes's
    own source, not an AGOS list; the ones its lists hold aren't repeated."""
    listed = {f.key for f in _installed_fields()}
    extras = {f.key: f for f in hs.extra_fields(HERMES, listed)}
    for name in (
        "group_topics",
        "dm_topics",
        "mention_patterns",
        "reply_to_mode",
        "group_allowed_chats",
        "ignored_threads",
        "proxy_url",
        "status_indicator",
    ):
        key = hs.EXTRA_PREFIX + name
        assert key in extras, name
        assert not extras[key].in_defaults
        assert "plugins/platforms/telegram/" in extras[key].description
    assert extras[hs.EXTRA_PREFIX + "group_topics"].type == "list"
    assert (
        "TELEGRAM_GROUP_ALLOWED_CHATS"
        in extras[hs.EXTRA_PREFIX + "group_allowed_chats"].description
    )
    # In Hermes's list already (telegram.reactions): not a second row.
    assert hs.EXTRA_PREFIX + "reactions" not in extras
    # auxiliary.review.* is in Hermes's own defaults now: an ordinary row.
    assert {"auxiliary.review.provider", "auxiliary.review.model"} <= listed


def test_platform_extras_follow_helpers_that_take_the_key(tmp_path: Path) -> None:
    folder = tmp_path / "plugins" / "platforms" / "telegram"
    folder.mkdir(parents=True)
    (folder / "adapter.py").write_text(
        """
class A:
    def _flag(self, key, env_name, default):
        return extra_or_secret(self.config.extra, key, env_name, None) or default

    def topics(self):
        \"\"\"Topics the bot opens.\"\"\"
        return self.config.extra.get("brand_new_topics", [])

    def gate(self):
        return self._flag("brand_new_gate", "TELEGRAM_BRAND_NEW_GATE", "true")
"""
    )
    found = {e.key: e for e in hs.platform_extras(tmp_path)}
    assert (
        found["brand_new_topics"].default == []
        and found["brand_new_topics"].doc == "Topics the bot opens."
    )
    assert found["brand_new_gate"].env == "TELEGRAM_BRAND_NEW_GATE"
    assert found["brand_new_gate"].default == "true"


def test_keys_no_listed_setting_covers_are_found_the_same_way_quickly() -> None:
    """_uncovered looks a path's dotted parents up instead of scanning every known
    key for each path (it ran ~30,000 prefix checks per profile)."""
    known = {"a.b", "a.c.d", "providers", "x"}
    config = {
        "a": {"b": 1, "c": {"d": 2, "e": 3}, "f": {"g": 4}},
        "providers": {"one": {"api_key": "k"}},
        "x": {"deep": 1},
        "new": {"k": 1},
        "flat": 5,
        "_config_version": 9,
    }
    assert hall._uncovered(config, known) == {
        "a.c.e": 3,
        "a.f": {"g": 4},
        "new.k": 1,
        "flat": 5,
    }


def test_the_shared_homes_keys_that_matter_show_read_only_with_why(env: Any) -> None:  # noqa: F811
    client, core, _runner, _home = env
    _stub_schema(core)
    ws(client, "Alpha")
    shared = core.engine.settings.hermes_home
    shared.mkdir(parents=True, exist_ok=True)
    (shared / "config.yaml").write_text("model:\n  provider: anthropic\n  default: claude-x\n")
    body = client.get("/preferences/hermes-settings").json()
    assert body["sharedHome"] == str(shared)
    rows = {r["key"]: r for r in body["shared"]}
    assert rows["model.default"]["value"] == "claude-x" and rows["model.default"]["set"]
    assert "new workspace starts" in rows["model.default"]["reason"]
    assert rows["agent.reasoning_effort"]["set"] is False
    # A managed key: this home's own value, and the one AGOS's runs use.
    zone = rows["timezone"]
    assert "HERMES_MANAGED_DIR" in zone["reason"]
    # Nothing of the shared home is a row the page writes.
    assert all(s["key"] != "model.default" or s["source"] == "config" for s in body["settings"])


def test_back_to_hermess_default_on_an_owner_choice_survives_agos_s_next_sync(
    env: Any,  # noqa: F811
) -> None:
    """ "Use Hermes's default" on an owner-choice row writes Hermes's default value
    itself: an unset would look like a new profile, and AGOS's next sync
    (owner_choices.keep_owner) would write AGOS's recommendation back."""
    from agos_core.engine import owner_choices

    client, core, _runner, _home = env
    _stub_schema(core)
    a = ws(client, "Alpha")
    row = _row(client, "sessions.auto_prune")
    assert row["rule"]["kind"] in ("choice", "seeded")
    r = client.put(
        "/preferences/hermes-settings", json={"key": "sessions.auto_prune", "reset": True}
    )
    assert r.status_code == 200, r.text
    assert r.json()["value"] is True  # Hermes's default
    assert _value(core, a, "sessions.auto_prune") is True  # written, not unset
    config = config_file.read(core.engine.profile_home(a))
    if row["rule"]["kind"] == "choice":
        assert "sessions.auto_prune" not in owner_choices.keep_owner(
            {"sessions.auto_prune": "false"}, config
        )
    else:  # a seeded start value only fills a key the profile lacks (engine.apply)
        assert config_file.get(config, "sessions.auto_prune") not in (None, "")
