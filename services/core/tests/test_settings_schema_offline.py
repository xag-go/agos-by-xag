"""Hermes's settings list read OFFLINE (engine/settings_schema): what AGOS makes of
Hermes's runtime answer, its defaults file's comments, its .env registry, its
secret paths and the Telegram adapter's `extra` reads. No Hermes install needed:
the answer and the source files are made here, in Hermes's own shapes."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from agos_core.engine.settings_schema import env as schema_env
from agos_core.engine.settings_schema import extras, fields, groups, read_cache
from agos_core.engine.settings_schema import secrets as schema_secrets

DEFAULTS_SOURCE = """
DEFAULT_CONFIG = {
    # How the agent talks.
    # Two comment lines join into one text.
    "display": {
        "skin": "default",  # the skin's name
        "compact": False,
    },
    "agent": {
        "max_turns": 90,
    },
    # Entries are the owner's own.
    "providers": {},
    "toolsets": ["web"],
    "_config_version": 7,
}
"""


@pytest.fixture
def clean_cache() -> Iterator[None]:
    saved = dict(read_cache._cache)
    read_cache.forget()
    yield
    read_cache.forget()
    read_cache._cache.update(saved)


def _answer(source: Path) -> str:
    found = {
        "fields": {
            "display.skin": {"type": "select", "description": "", "options": ["default", "ares"]},
            "agent.max_turns": {"type": "number", "description": "Turns before it stops"},
            "model.api_key": {"type": "string", "description": "Model → Api Key"},
            "broken": "not a mapping",
        },
        "defaults": {
            "display": {"skin": "default", "compact": False},
            "agent": {"max_turns": 90},
            "providers": {},
            "toolsets": ["web"],
            "_config_version": 7,
        },
        "source": str(source),
        "kanban_workflow": {"columns": ["todo", "done"]},
        "kanban_auto_cap": 4,
        "env": {
            "OPENAI_API_KEY": {"description": "OpenAI", "category": "provider", "password": True},
            "SLACK_BOT_TOKEN": {"description": "Slack", "category": "messaging", "password": True},
            "TELEGRAM_HOME": {"description": "Home chat", "category": "messaging"},
            "lower_case": {"description": "skipped"},
            "BAD": "not a mapping",
        },
        "secret_keys": ["model.api_key"],
        "image_modes": ["auto", "native", "text"],
    }
    return "noise before\nAGOS-SCHEMA " + json.dumps(found) + "\n"


def test_hermes_answer_becomes_fields_in_hermes_order_with_its_comments(
    tmp_path: Path, clean_cache: None
) -> None:
    source = tmp_path / "hermes_cli" / "config_defaults.py"
    source.parent.mkdir()
    source.write_text(DEFAULTS_SOURCE)
    got, where = read_cache.parse(_answer(source))
    assert where == source
    by_key = {f.key: f for f in got}
    # The schema's fields first, then the defaults' leaves its walk skipped.
    assert [f.key for f in got][:3] == ["display.skin", "agent.max_turns", "model.api_key"]
    assert "broken" not in by_key and "_config_version" not in by_key
    skin = by_key["display.skin"]
    assert (skin.type, skin.options, skin.default) == ("select", ["default", "ares"], "default")
    # No words of its own: the comment above the section joined with the key's own.
    assert skin.description == "the skin's name"
    assert by_key["display.compact"].description.startswith("How the agent talks.")
    assert by_key["agent.max_turns"].description == "Turns before it stops"
    # A title-only description falls back to the title (no comment for it).
    assert by_key["model.api_key"].secret and not skin.secret
    assert by_key["providers"].type == "object" and by_key["providers"].default == {}
    assert by_key["providers"].description == "Entries are the owner's own."
    assert by_key["toolsets"].type == "list"
    assert by_key["display.compact"].type == "boolean"
    assert isinstance(skin.group, str) and skin.group
    # What the same answer carried, kept beside the list.
    assert read_cache.kanban_workflow() == {"columns": ["todo", "done"]}
    assert read_cache.kanban_auto_cap() == 4
    assert read_cache.image_modes() == ["auto", "native", "text"]
    env = {e.name: e for e in read_cache.env_registry() or []}
    assert set(env) == {"OPENAI_API_KEY", "SLACK_BOT_TOKEN", "TELEGRAM_HOME"}
    assert env["OPENAI_API_KEY"].secret and not env["TELEGRAM_HOME"].secret
    assert env["SLACK_BOT_TOKEN"].group == groups.NOT_USED
    assert env["TELEGRAM_HOME"].group == groups.ENV


def test_the_list_is_kept_while_hermess_file_is_unchanged(
    tmp_path: Path, clean_cache: None
) -> None:
    source = tmp_path / "config_defaults.py"
    source.write_text(DEFAULTS_SOURCE)
    got, _ = read_cache.parse(_answer(source))
    assert read_cache.cached() is None and read_cache.source_path() is None
    read_cache.keep(source, got)
    assert read_cache.cached() == got
    source.write_text(DEFAULTS_SOURCE + "\n# a Hermes upgrade\n")
    assert read_cache.cached() is None
    read_cache.keep(tmp_path / "gone.py", got)  # no file: nothing kept
    assert read_cache.cached() is None
    read_cache.keep_env(None)
    assert read_cache.env_registry() is None
    read_cache.forget()
    assert read_cache.kanban_workflow() is None and read_cache.image_modes() is None
    assert read_cache.kanban_auto_cap() is None


def test_an_answer_without_the_list_or_with_odd_parts(tmp_path: Path, clean_cache: None) -> None:
    with pytest.raises(ValueError):
        read_cache.parse("Traceback: hermes_cli not found\n")
    odd = {"source": str(tmp_path / "missing.py"), "kanban_auto_cap": 0, "env": None}
    got, _ = read_cache.parse("AGOS-SCHEMA " + json.dumps(odd))
    assert got == []
    assert read_cache.kanban_auto_cap() is None and read_cache.env_registry() is None
    assert read_cache.kanban_workflow() is None and read_cache.image_modes() is None


def test_comments_of_a_broken_source_or_one_without_the_mapping() -> None:
    assert fields.comments("DEFAULT_CONFIG = {\n") == {}
    assert fields.comments("OTHER = {'a': 1}  # not it\n") == {}
    assert fields.comments("DEFAULT_CONFIG = {\n    # x\n    1: 2,\n    'b': 3,\n}\n") == {}


def test_a_key_hermes_reads_but_does_not_list() -> None:
    row = fields.unlisted("platforms.x.y", 3, secret=True)
    assert (row.type, row.in_defaults, row.secret, row.default) == ("number", False, True, None)
    assert fields.unlisted("a", {"b": 1}).type == "object"
    assert fields.unlisted("a", "x").type == "string"
    assert fields.unlisted("a", [1]).type == "list"
    assert fields.unlisted("a", True).type == "boolean"
    env = schema_env.unlisted_env("MY_TOOL_KEY")
    assert env.secret and not env.listed and env.category == "custom"
    assert schema_env.env_vars(None) == []


def test_secret_paths_are_masked_before_anything_leaves() -> None:
    paths = schema_secrets.secret_paths(
        [["model", "api_key"], ["providers", 0, "key"], "not a path"]
    )
    assert paths == {("model", "api_key"), ("providers", 0, "key")}
    config = {"model": {"api_key": "sk-x", "name": "m"}, "providers": [{"key": "k", "url": "u"}]}
    shown = schema_secrets.masked(config, paths)
    assert shown["model"] == {"api_key": schema_secrets.MASK, "name": "m"}
    assert shown["providers"] == [{"key": schema_secrets.MASK, "url": "u"}]
    assert schema_secrets.masked({"api_key": ""}, paths, "model") == {"api_key": ""}
    assert schema_secrets.masked(config, None) is config
    assert schema_secrets.holds_secret(paths, "model")
    assert not schema_secrets.holds_secret(paths, "display")


ADAPTER = '''
def _flag(extra, key, default=False):
    """Read a yes/no extra.

    More words."""
    return extra.get(key, default)


def _secret(extra, key, env, default):
    return extra_or_secret(extra, key, env, default)


class Adapter:
    def start(self):
        """The bot starts."""
        topics = self.config.extra.get("group_topics", True)
        mode = (self.config.extra or {}).get("reply_mode", "thread")
        strict = _flag(self.config.extra, "strict_mentions", "false")
        token = extra_or_secret(self.config.extra, "webhook_secret", "TELEGRAM_WEBHOOK_SECRET")
        other = _secret(self.config.extra, "proxy_url", "TELEGRAM_PROXY", None)
        again = self.config.extra.get("group_topics", False)
        skipped = self.config.extra.get(not_a_constant)
        listed = self.config.extra.get("allowed_users", [])
        return topics, mode, strict, token, other, again, skipped, listed
'''


def test_the_telegram_adapters_extra_reads_become_rows(tmp_path: Path) -> None:
    folder = tmp_path / "plugins" / "platforms" / "telegram"
    folder.mkdir(parents=True)
    (folder / "adapter.py").write_text(ADAPTER)
    (folder / "broken.py").write_text("def (:\n")
    rows = {
        f.key.removeprefix(extras.EXTRA_PREFIX): f
        for f in extras.extra_fields(tmp_path, {"telegram.allowed_users"})
    }
    assert set(rows) == {
        "group_topics",
        "reply_mode",
        "strict_mentions",
        "webhook_secret",
        "proxy_url",
    }
    assert rows["group_topics"].type == "boolean" and rows["group_topics"].default is True
    assert "The bot starts." in rows["group_topics"].description
    assert "adapter.py:" in rows["reply_mode"].description and rows["reply_mode"].default == (
        "thread"
    )
    # "false" in Hermes's source is read as the yes/no it means.
    assert rows["strict_mentions"].default is False
    assert "TELEGRAM_WEBHOOK_SECRET wins" in rows["webhook_secret"].description
    assert rows["webhook_secret"].type == "string"
    assert "TELEGRAM_PROXY" in rows["proxy_url"].description
    assert all(not r.in_defaults for r in rows.values())
    # Walked once while its files are unchanged.
    assert extras.platform_extras(tmp_path) == extras.platform_extras(tmp_path)
    assert extras.hermes_root(tmp_path / "hermes_cli" / "config_defaults.py") == tmp_path.resolve()
