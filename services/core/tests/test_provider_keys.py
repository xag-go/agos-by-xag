"""API keys from Settings → Models: tested with the provider before Hermes saves them."""

import pytest

from agos_core.engine.models import Credential, to_connections
from agos_core.engine.provider_keys import KeyProblem, clean_key, verdict


def test_hermess_probe_answer_in_the_owners_words() -> None:
    """Hermes's own probe (validate_provider_credential / doctor's Anthropic probe)
    tests the key; AGOS only words its answer."""
    assert verdict({"ok": True, "reachable": True, "probed": True}) is not None
    assert verdict({"ok": True, "reachable": True}).ok  # type: ignore[union-attr]
    refused = verdict({"ok": False, "reachable": True, "message": "That API key was rejected."})
    assert refused is not None and not refused.ok and "rejected" in refused.message
    away = verdict({"ok": False, "reachable": False, "message": ""})
    assert away is not None and not away.ok and "reach" in away.message
    assert verdict({"ok": True, "reachable": False, "probed": False}) is None  # no probe


def test_agos_has_no_http_probe_of_its_own() -> None:
    from pathlib import Path

    from agos_core.engine import provider_keys

    text = Path(provider_keys.__file__).read_text()
    assert "import httpx" not in text and "api.openai.com" not in text
    assert "validate_provider_credential" in text and "_probe_anthropic" in text
    assert "save_provider_env_credential" in text and "remove_provider_env_credential" in text
    assert "save_env_value" not in text


def test_key_shape_and_provider_checked() -> None:
    from agos_core.engine.provider_keys import _checked_env

    assert clean_key("  sk-abc  ") == "sk-abc"
    for bad in ("", "sk a", "x" * 501):
        with pytest.raises(KeyProblem):
            clean_key(bad)
    with pytest.raises(KeyProblem):
        _checked_env("copilot")  # not a Hermes variable name


def test_claude_shows_subscription_and_key_together() -> None:
    payload = {"providers": [{"slug": "anthropic", "authenticated": True}]}
    pool = [
        Credential("anthropic", "anthropic-oauth-1", "oauth"),
        Credential("anthropic", "ANTHROPIC_API_KEY", "api_key"),
    ]
    rows = {r["id"]: r for r in to_connections(payload, pool)}
    assert rows["claude"]["cli"]["account"] == "your Claude account"
    assert rows["claude"]["api"] is not None
    assert rows["copilot"]["apiKey"] is False
    assert rows["openai"]["apiKey"] is True
