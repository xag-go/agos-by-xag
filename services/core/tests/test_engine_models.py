"""Hermes's provider/model inventory → AGOS's catalog and Settings cards."""

from pathlib import Path

import pytest

from agos_core.config import EngineConfig
from agos_core.domain.models import ModelSelection
from agos_core.engine.models import (
    hermes_model,
    hermes_slug,
    mode_of,
    pool_credentials,
    to_catalog,
    to_connections,
)

# Hermes's redacted pool list (list_credential_pool, engine/hermes.py _POOL).
POOL = {
    "pool": {
        "providers": [
            {
                "provider": "anthropic",
                "entries": [
                    {"label": "claude_code", "auth_type": "oauth", "source": "claude_code"}
                ],
            },
            {
                "provider": "copilot",
                "entries": [{"label": "gh auth token", "auth_type": "api_key", "source": "gh_cli"}],
            },
            {
                "provider": "openai-codex",
                "entries": [
                    {"label": "device_code", "auth_type": "oauth", "source": "device_code"}
                ],
            },
        ]
    }
}

LADDER = ["minimal", "low", "medium", "high", "xhigh", "max", "ultra"]

PAYLOAD = {
    "providers": [
        {
            "slug": "anthropic",
            "authenticated": True,
            "models": ["claude-opus-5-5", "claude-haiku-4-5-20251001"],
            "efforts": {"claude-opus-5-5": LADDER, "claude-haiku-4-5-20251001": None},
        },
        {
            "slug": "openai-codex",
            "authenticated": True,
            "models": ["gpt-5.5"],
            "efforts": {"gpt-5.5": LADDER},
        },
        {
            "slug": "copilot",
            "authenticated": True,
            "models": ["gpt-5.4", "gpt-4o"],
            "efforts": {"gpt-5.4": ["high", "low", "medium"], "gpt-4o": None},
        },
        {"slug": "gemini", "authenticated": False, "models": [], "efforts": {}},
        {"slug": "moa", "authenticated": True, "models": ["default"], "efforts": {}},
    ],
    "currentEffort": "xhigh",
}


def test_pool_is_read_without_secrets() -> None:
    pool = pool_credentials(POOL)
    assert [(c.slug, c.label, c.kind) for c in pool] == [
        ("anthropic", "claude_code", "oauth"),
        ("copilot", "gh auth token", "api_key"),
        ("openai-codex", "device_code", "oauth"),
    ]
    assert mode_of("anthropic", pool) == "cli"
    assert mode_of("copilot", pool) == "cli"  # a subscription, whatever the token type


def test_catalog_lists_only_connected_providers() -> None:
    catalog = to_catalog(PAYLOAD, pool_credentials(POOL))
    assert [p["id"] for p in catalog] == ["claude", "openai", "copilot"]
    opus = catalog[0]["models"][0]
    assert opus == {
        "id": "claude-opus-5-5",
        "label": "Claude Opus 5.5",
        "modes": ["cli"],
        # Exactly what `hermes model` offers, plus its "Disable reasoning".
        "efforts": [*LADDER, "none"],
        "defaultEffort": "xhigh",  # the level Hermes is set to
    }
    haiku = catalog[0]["models"][1]
    assert haiku["label"] == "Claude Haiku 4.5" and haiku["efforts"] == ["standard"]
    assert catalog[1]["models"][0]["label"] == "GPT 5.5"
    gpt54, gpt4o = catalog[2]["models"]
    # Copilot publishes its own set per model; Hermes's order, no extra levels.
    assert gpt54["efforts"] == ["low", "medium", "high", "none"]
    assert gpt54["defaultEffort"] == "medium"  # xhigh isn't offered for it
    assert gpt4o["efforts"] == ["standard"]


def test_connections_show_every_known_provider() -> None:
    rows = {r["id"]: r for r in to_connections(PAYLOAD, pool_credentials(POOL))}
    assert rows["claude"]["cli"]["account"] == "your Claude Code login"
    assert rows["copilot"]["cli"]["account"] == "your GitHub account (gh)"
    assert rows["gemini"]["cli"]["account"] is None and rows["gemini"]["api"] is None


def test_python_is_hermess_own_runtime_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P2 (925047d area 1): the probes' Python is Hermes's own runtime command,
    used as it is (its bootstrap untouched, nothing read out of its text); only its
    run of a module becomes the probe's code or script. No second bootstrap, no
    venv/shebang guessing."""
    import json
    import subprocess
    import sys

    from agos_core.engine import models

    monkeypatch.setattr(models, "_LAUNCHERS", {})
    monkeypatch.setattr(models, "_REPOS", {})
    monkeypatch.setenv("HOME", str(tmp_path))
    repo = tmp_path / "hermes-agent"
    repo.mkdir()
    (repo / "hermes_constants.py").write_text("MARK = 'hermes'\n")
    boot = (
        "import os, sys, runpy; os.environ.pop('PYTHONPATH', None); "
        f"sys.path.insert(0, {str(repo)!r}); os.environ['BOOTED'] = 'yes'; "
        "runpy.run_module('agos_goal_judge', run_name='__main__', alter_sys=True)"
    )
    hermes = tmp_path / "hermes"
    printed = json.dumps([sys.executable, "-I", "-c", boot])
    hermes.write_text(
        "#!/bin/sh\n"
        '[ "$1 $2 $3" = "--print-runtime-command --module agos_goal_judge" ] || exit 2\n'
        f"cat <<'EOF'\n{printed}\nEOF\n"
    )
    hermes.chmod(0o755)
    config = EngineConfig(
        hermes_bin=str(hermes),
        docker_bin="/bin/docker",
        hermes_home=tmp_path,
        profile_prefix="agos-",
        sandbox_image="img:1",
        host_home=tmp_path,
        roots_dir=tmp_path / "roots",
    )
    python = models.hermes_python(config)
    code = "import os, sys, hermes_constants; print(os.environ['BOOTED'], hermes_constants.MARK, sys.argv[1:])"
    done = subprocess.run(  # noqa: S603
        [python, "-c", code, "a", "b"], capture_output=True, text=True, check=True
    )
    assert done.stdout.strip() == "yes hermes ['a', 'b']"
    script = tmp_path / "probe.py"
    script.write_text("import sys, hermes_constants\nprint(hermes_constants.MARK, sys.argv)\n")
    done = subprocess.run([python, str(script), "x"], capture_output=True, text=True, check=True)  # noqa: S603
    assert done.stdout.strip() == f"hermes [{str(script)!r}, 'x']"
    assert models.hermes_repo(config) == repo
    assert not hasattr(models, "_python_of") and not hasattr(models, "_BOOT")


def test_slug_round_trip() -> None:
    assert hermes_slug("claude", "cli") == "anthropic"
    assert hermes_slug("openai", "cli") == "openai-codex"
    assert hermes_slug("openai", "api") == "openai-api"
    assert hermes_slug("copilot", "cli") == "copilot"


MODEL = {"provider": "claude", "mode": "cli", "model": "claude-sonnet-5", "effort": "high"}


def test_model_mapping_keeps_the_owners_choice() -> None:
    sel = ModelSelection.model_validate(MODEL)
    assert hermes_model(sel) == {
        "provider": "anthropic",
        "model": "claude-sonnet-5",
        "model_options": {"reasoning_effort": "high"},
    }
    codex = ModelSelection.model_validate({**MODEL, "provider": "openai", "model": "gpt-5.5"})
    assert hermes_model(codex)["provider"] == "openai-codex"
    api = ModelSelection.model_validate({**MODEL, "provider": "openai", "mode": "api"})
    assert hermes_model(api)["provider"] == "openai-api"
    cop = ModelSelection.model_validate({**MODEL, "provider": "copilot", "model": "gpt-5.4"})
    assert hermes_model(cop)["provider"] == "copilot"


def test_hermess_other_providers_show_up_with_their_own_sign_in_or_key() -> None:
    """Settings → Models lists every provider Hermes has (not a list written in
    AGOS): sign-ins started with Hermes's own login, keys under Hermes's variable."""
    from agos_core.engine.models import to_catalog, to_connections

    payload = {
        "providers": [
            {"slug": "anthropic", "name": "Anthropic", "authenticated": False, "models": []},
            {
                "slug": "deepseek",
                "name": "DeepSeek",
                "authenticated": True,
                "models": ["deepseek-chat"],
                "auth": "api_key",
                "keyEnv": "DEEPSEEK_API_KEY",
            },
            {
                "slug": "minimax-oauth",
                "name": "MiniMax (OAuth)",
                "authenticated": False,
                "models": [],
                "auth": "oauth_minimax",
                "keyEnv": "",
            },
            {
                "slug": "bedrock",
                "name": "AWS Bedrock",
                "authenticated": False,
                "models": [],
                "auth": "aws_sdk",
                "keyEnv": "",
            },
            {
                "slug": "custom",
                "name": "custom",
                "authenticated": False,
                "models": [],
                "auth": "api_key",
                "keyEnv": "",
            },
        ]
    }
    rows = {r["id"]: r for r in to_connections(payload, [])}
    assert "claude" in rows and "bedrock" not in rows and "custom" not in rows
    assert rows["deepseek"]["more"] and rows["deepseek"]["keyEnv"] == "DEEPSEEK_API_KEY"
    assert rows["deepseek"]["api"] is not None and rows["deepseek"]["apiKey"]
    assert rows["minimax-oauth"]["cli"]["installed"] and not rows["minimax-oauth"]["apiKey"]
    assert rows["minimax-oauth"]["cli"]["account"] is None
    catalog = {c["id"]: c for c in to_catalog(payload, [])}
    assert catalog["deepseek"]["label"] == "DeepSeek"
    assert catalog["deepseek"]["models"][0]["id"] == "deepseek-chat"


def test_a_sign_in_for_hermess_other_providers_runs_hermes_auth_add() -> None:
    from agos_core.engine.provider_login import slug_of

    assert slug_of("minimax-oauth") == "minimax-oauth"
    assert slug_of("claude") == "anthropic"
    import pytest

    with pytest.raises(ValueError):
        slug_of("x; rm -rf /")


def test_no_effort_picked_is_hermess_own_default() -> None:
    """A member with no effort of its own gets no agent.reasoning_effort: Hermes's
    default config has none (the model's own level), so AGOS picks nothing."""
    import os
    import runpy
    from pathlib import Path

    import pytest

    from agos_core.engine.rules import model_pairs

    assert "agent.reasoning_effort" not in model_pairs("anthropic", "claude-x", "")
    assert model_pairs("anthropic", "claude-x", "high")["agent.reasoning_effort"] == "high"
    checkout = Path(
        os.environ.get("AGOS_HERMES_SOURCE") or Path.home() / ".hermes" / "hermes-agent"
    )
    defaults = checkout / "hermes_cli" / "config_defaults.py"
    if not defaults.is_file():
        pytest.skip("no Hermes checkout")
    config = runpy.run_path(str(defaults))["DEFAULT_CONFIG"]
    assert not config["agent"].get("reasoning_effort")


def test_subscription_or_key_comes_from_hermes() -> None:
    """No fixed list of AGOS's: Hermes's registry auth type (a sign-in is a
    subscription) and the kind of login its credential pool holds decide."""
    from agos_core.engine.models import (
        Credential,
        extra_providers,
        is_sign_in,
        selection_from_hermes,
        slug_mode,
    )

    assert mode_of("openai-codex", [], "oauth_external") == "cli"  # Hermes: a sign-in
    assert mode_of("openai-api", [], "api_key") == "api"
    assert mode_of("gemini", [Credential("gemini", "GOOGLE_API_KEY", "api_key")]) == "api"
    assert mode_of("anthropic", [Credential("anthropic", "x", "api_key")], "api_key") == "api"
    assert mode_of("anthropic", [Credential("anthropic", "claude_code", "oauth")]) == "cli"
    assert all(is_sign_in(a) for a in ("oauth_device_code", "oauth_external", "oauth_minimax"))
    assert not any(is_sign_in(a) for a in ("api_key", "aws_sdk", "vertex", "external_process"))
    # Hermes's own auth types say what can be connected here (no AGOS list).
    payload = {
        "providers": [
            {"slug": "qwen-oauth", "auth": "oauth_external", "keyEnv": ""},
            {"slug": "copilot-acp", "auth": "external_process", "keyEnv": ""},
            {"slug": "custom", "auth": "api_key", "keyEnv": ""},
        ]
    }
    assert [p["slug"] for p in extra_providers(payload)] == ["qwen-oauth"]
    # A model named in a config: the same mode the catalog gives (Copilot too).
    assert slug_mode("copilot") == "cli" and slug_mode("openai-api") == "api"
    assert slug_mode("openai-codex") == "cli" and slug_mode("gemini") == "api"
    found = selection_from_hermes("copilot", "gpt-5.4", None)
    assert found is not None and found.mode == "cli"


def test_provider_names_are_hermes_s_except_agos_s_merged_rows() -> None:
    """A row that is one Hermes provider under its own slug shows Hermes's name;
    Claude and OpenAI (AGOS's stored ids over Hermes's anthropic / two OpenAI
    providers) keep AGOS's word. The always-listed rows are AGOS's stored ids."""
    from agos_core.engine.models import AGOS_ID, ALWAYS_LISTED, to_connections

    assert list(ALWAYS_LISTED) == list(dict.fromkeys(AGOS_ID.values()))
    payload = {
        "providers": [
            {"slug": "gemini", "name": "Google AI Studio", "authenticated": False, "models": []},
            {"slug": "anthropic", "name": "Anthropic", "authenticated": False, "models": []},
        ]
    }
    names = {r["id"]: r["name"] for r in to_connections(payload, [])}
    assert names["gemini"] == "Google AI Studio" and names["claude"] == "Claude"
    assert names["openai"] == "OpenAI"


def test_hermes_s_default_model_is_the_catalog_s_first_choice() -> None:
    """W5: a picker starts on the catalog's first choice; the core puts Hermes's own
    default model (provider, model, mode) there, and changes nothing otherwise."""
    from agos_core.actions.services.settings.model_catalog import hermes_first
    from agos_core.domain.models import ModelSelection

    def m(i: str, modes: list[str]) -> dict[str, object]:
        return {"id": i, "label": i, "modes": modes, "efforts": [], "defaultEffort": "medium"}

    catalog = [
        {"id": "claude", "label": "Claude", "models": [m("claude-a", ["cli"])]},
        {
            "id": "openai",
            "label": "OpenAI",
            "models": [m("gpt-a", ["cli"]), m("gpt-b", ["cli", "api"])],
        },
    ]
    pick = ModelSelection.model_validate(
        {"provider": "openai", "mode": "api", "model": "gpt-b", "effort": "medium"}
    )
    first = hermes_first(catalog, pick)[0]
    assert (first["id"], first["models"][0]["id"], first["models"][0]["modes"][0]) == (
        "openai",
        "gpt-b",
        "api",
    )
    assert hermes_first(catalog, None) == catalog
    gone = pick.model_copy(update={"model": "gpt-zzz"})
    assert hermes_first(catalog, gone) == catalog
