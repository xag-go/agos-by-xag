"""AGOS's writes that Hermes does itself, run against the installed Hermes:
`hermes sessions pin`, Hermes's write_profile_meta (display_name), and its
usage analytics. Skipped on a machine without Hermes."""

import shutil
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
import yaml

from agos_core.config import EngineConfig
from agos_core.engine import config_file
from agos_core.engine.hermes import HermesEngine


@pytest.fixture
def engine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> HermesEngine:
    monkeypatch.undo()  # the real Hermes, not conftest's stand-in
    hermes = shutil.which("hermes")
    if not hermes:
        pytest.skip("no Hermes install on this machine")
    tools = Path.home() / ".hermes" / "tools"
    return HermesEngine(
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


def test_display_name_is_written_by_hermess_write_profile_meta(
    engine: HermesEngine, tmp_path: Path
) -> None:
    home = tmp_path / "member"
    home.mkdir()
    (home / "profile.yaml").write_text(
        yaml.safe_dump({"description": "Writes scripts", "ui_meta": {"agos": {"reads": ["a"]}}})
    )
    engine.set_display_name(home, "Script Writer")
    meta = yaml.safe_load((home / "profile.yaml").read_text())
    assert meta["display_name"] == "Script Writer"
    assert meta["description"] == "Writes scripts" and meta["ui_meta"]["agos"] == {"reads": ["a"]}


def test_description_is_written_by_hermess_write_profile_meta(
    engine: HermesEngine, tmp_path: Path
) -> None:
    home = tmp_path / "root"
    home.mkdir()
    (home / "profile.yaml").write_text(yaml.safe_dump({"display_name": "Argan"}))
    engine.set_description(home, "Online shop for argan oil.")
    meta = yaml.safe_load((home / "profile.yaml").read_text())
    assert meta["description"] == "Online shop for argan oil." and meta["display_name"] == "Argan"
    assert meta["description_auto"] is False
    engine.set_description(home, "")
    assert yaml.safe_load((home / "profile.yaml").read_text())["description"] == ""


class _Recorded:
    """The real runner, with the commands it ran."""

    def __init__(self, runner: object) -> None:
        self.runner, self.calls = runner, []  # type: ignore[var-annotated]

    def run(self, args: list[str], **kw: object) -> str:
        self.calls.append(list(args))
        return self.runner.run(args, **kw)  # type: ignore[attr-defined,no-any-return]


def test_a_roots_name_and_description_go_through_hermess_profile_cli(
    engine: HermesEngine, tmp_path: Path
) -> None:
    """P6 (925047d area 1): a root's display name is `hermes profile rename default
    <name>`, a description `hermes profile describe <p> --text`; only what Hermes's
    CLI can't do (a member's display name, an empty description) stays on Hermes's
    write_profile_meta."""
    import tempfile

    recorded = _Recorded(engine.runner)
    engine.runner = recorded  # type: ignore[assignment]
    # Outside ~/.hermes: Hermes's profile CLI reads a root inside it as ~/.hermes.
    outside = Path.home() / ".cache" / "agos-tests"
    outside.mkdir(parents=True, exist_ok=True)
    base = Path(tempfile.mkdtemp(dir=outside))
    try:
        _names_through_the_cli(engine, recorded, base / "agos-argan")
    finally:
        shutil.rmtree(base, ignore_errors=True)
    # A root inside ~/.hermes (tmp_path may be under its cache) never reaches the CLI.
    inside = tmp_path / "agos-inside"
    inside.mkdir()
    (inside / "config.yaml").write_text("{}\n")
    recorded.calls.clear()
    if inside.resolve().is_relative_to((Path.home() / ".hermes").resolve()):
        engine.set_display_name(inside, "Inside")
        assert not recorded.calls
        assert yaml.safe_load((inside / "profile.yaml").read_text())["display_name"] == "Inside"


def _names_through_the_cli(engine: HermesEngine, recorded: "_Recorded", root: Path) -> None:
    root.mkdir(parents=True)
    (root / "config.yaml").write_text("{}\n")
    (root / "profile.yaml").write_text(yaml.safe_dump({"ui_meta": {"agos": {"reads": ["a"]}}}))
    engine.set_display_name(root, "Argan Shop")
    engine.set_description(root, "Online shop for argan oil.")
    meta = yaml.safe_load((root / "profile.yaml").read_text())
    assert (
        meta["display_name"] == "Argan Shop" and meta["description"] == "Online shop for argan oil."
    )
    assert meta["ui_meta"]["agos"] == {"reads": ["a"]}
    ran = [c[1:] for c in recorded.calls]
    assert ["profile", "rename", "default", "Argan Shop"] in ran
    assert ["profile", "describe", "default", "--text", "Online shop for argan oil."] in ran
    member = root / "profiles" / "writer"
    member.mkdir(parents=True)
    (member / "config.yaml").write_text("{}\n")
    engine.set_description(member, "Writes scripts")
    assert ["profile", "describe", "writer", "--text", "Writes scripts"] in [
        c[1:] for c in recorded.calls
    ]
    assert yaml.safe_load((member / "profile.yaml").read_text())["description"] == "Writes scripts"


def test_sessions_are_pinned_with_hermess_cli(engine: HermesEngine, tmp_path: Path) -> None:
    home = tmp_path / "root"
    home.mkdir()
    (home / "config.yaml").write_text("{}\n")
    # A session made by Hermes's own SessionDB, in its runtime (the test's setup).
    import json
    import subprocess

    from agos_core.engine.hermes import JUDGE_RUN, child_env

    argv = list(engine._runtime_argv())
    argv[-1] = argv[-1].replace(JUDGE_RUN, "exec(sys.stdin.read())")
    script = (
        "from hermes_state import SessionDB\n"
        "db = SessionDB()\n"
        "db.create_session('agos-archive-1', 'agos', chat_id='t')\n"
        "db.append_message('agos-archive-1', 'user', content='hi', timestamp=1.0)\n"
        "print('AGOS-OK')\n"
    )
    try:
        done = subprocess.run(  # noqa: S603 - Hermes's own launcher, fixed argv
            argv,
            input=script,
            capture_output=True,
            text=True,
            timeout=120,
            env=child_env({**engine._env(), "HERMES_HOME": str(home)}),
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        pytest.skip(f"Hermes's runtime is not usable here: {error}")
    if "AGOS-OK" not in done.stdout:
        pytest.skip(f"Hermes's runtime is not usable here: {json.dumps(done.stderr[-300:])}")
    engine.pin_sessions(home, ["agos-archive-1"])
    with closing(sqlite3.connect(home / "state.db")) as db:
        row = db.execute("SELECT pinned FROM sessions WHERE id = 'agos-archive-1'").fetchone()
    assert row == (1,)


def test_a_chats_yolo_is_read_from_hermess_own_session_index(
    engine: HermesEngine, tmp_path: Path
) -> None:
    """P8 (925047d area 1): the routing entry of a chat and its /yolo are read by
    Hermes (SessionDB read-only + SessionEntry.from_dict), matched by the origin
    Hermes recorded, not by AGOS-built key ends; reading writes nothing."""
    import json
    import subprocess

    from agos_core.engine.hermes import JUDGE_RUN, child_env

    root = tmp_path / "root"
    root.mkdir()
    (root / "config.yaml").write_text("{}\n")
    argv = list(engine._runtime_argv())
    argv[-1] = argv[-1].replace(JUDGE_RUN, "exec(sys.stdin.read())")
    # The test's setup: Hermes's own gateway store makes the lanes and sets /yolo.
    script = (
        "import os\n"
        "from pathlib import Path\n"
        "from gateway.config import GatewayConfig, Platform\n"
        "from gateway.session import SessionSource, SessionStore\n"
        "store = SessionStore(Path(os.environ['HERMES_HOME']) / 'sessions', GatewayConfig())\n"
        "a = store.get_or_create_session(SessionSource(platform=Platform.TELEGRAM, "
        "chat_id='555', chat_type='dm', user_id='555'))\n"
        "t = store.get_or_create_session(SessionSource(platform=Platform.TELEGRAM, "
        "chat_id='-100', chat_type='group', thread_id='42', user_id='9'))\n"
        "store.set_session_yolo(a.session_key, True)\n"
        # The agos platform is a plugin's: its entry as the gateway that loaded it
        # writes it (SessionEntry.to_dict), through Hermes's own routing saver.
        "import json\n"
        "e = dict(store.lookup_by_session_key(a.session_key).to_dict())\n"
        "e['session_key'] = 'agent:main:agos:dm:conv-7'\n"
        "e['origin'] = {'platform': 'agos', 'chat_id': 'conv-7', 'chat_type': 'dm'}\n"
        "store._db.save_gateway_routing_entry(e['session_key'], json.dumps(e), "
        "scope=store._routing_scope())\n"
        "print('AGOS-OK')\n"
    )
    try:
        done = subprocess.run(  # noqa: S603 - Hermes's own launcher, fixed argv
            argv,
            input=script,
            capture_output=True,
            text=True,
            timeout=180,
            env=child_env({**engine._env(), "HERMES_HOME": str(root)}),
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        pytest.skip(f"Hermes's runtime is not usable here: {error}")
    if "AGOS-OK" not in done.stdout:
        pytest.skip(f"Hermes's runtime is not usable here: {json.dumps(done.stderr[-300:])}")
    before = (root / "state.db").stat().st_mtime_ns
    lanes = engine.hermes_lanes(root, [root])[str(root)]
    by = {(lane["platform"], lane["chat_id"], lane["thread_id"]): lane for lane in lanes}
    assert by[("telegram", "555", "")]["yolo"] is True
    assert by[("agos", "conv-7", "")]["yolo"] is True
    assert by[("telegram", "-100", "42")]["yolo"] is False
    assert (root / "state.db").stat().st_mtime_ns == before
    from agos_core.actions.access import _same_chat

    assert _same_chat(by[("agos", "conv-7", "")], "agos:conv-7")
    assert _same_chat(by[("telegram", "-100", "42")], "-100:42")
    assert not _same_chat(by[("telegram", "-100", "42")], "-100:0")
    assert _same_chat(by[("telegram", "555", "")], "555:0")


def test_keys_are_saved_by_hermess_credential_lifecycle(
    engine: HermesEngine, tmp_path: Path
) -> None:
    """General Settings' keys go into a home with Hermes's save_provider_env_credential:
    the .env line AND the credential pool entry the runtime reads (auth.json)."""
    import json

    home = tmp_path / "root"
    home.mkdir()
    (home / "config.yaml").write_text("{}\n")
    try:
        engine.save_credentials(home, {"GEMINI_API_KEY": "AIza-agos-test-key"}, [])
    except Exception as error:  # noqa: BLE001
        pytest.skip(f"Hermes's runtime is not usable here: {error}")
    assert "GEMINI_API_KEY=AIza-agos-test-key" in (home / ".env").read_text()
    pool = json.loads((home / "auth.json").read_text()).get("credential_pool", {})
    assert any(e.get("source") == "env:GEMINI_API_KEY" for e in pool.get("gemini", [])), pool
    engine.save_credentials(home, {}, ["GEMINI_API_KEY"])
    assert "GEMINI_API_KEY" not in (home / ".env").read_text()
    pool = json.loads((home / "auth.json").read_text()).get("credential_pool", {})
    assert not pool.get("gemini"), pool


def test_a_key_is_tested_by_hermess_own_probe(engine: HermesEngine) -> None:
    from agos_core.engine.provider_keys import ProviderKeys

    keys = ProviderKeys(engine.settings)
    try:
        assert keys.probe("AGOS_NO_SUCH_PROVIDER_API_KEY", "x") is None  # Hermes has no probe
    except RuntimeError as error:
        pytest.skip(f"Hermes's runtime is not usable here: {error}")
    found = keys.probe("OPENROUTER_API_KEY", "sk-or-v1-not-a-real-key")
    assert found is not None and not found.ok


def test_the_settings_page_reads_profiles_with_hermess_own_managed_overlay(
    engine: HermesEngine, tmp_path: Path
) -> None:
    """NB-5: each profile as Hermes reads it is merged by Hermes's own
    apply_managed_overlay (not an AGOS copy): leaf by leaf, a None never replaces a
    mapping, a bare managed `model:` string becomes model.default."""
    managed = engine.settings.managed_home
    managed.mkdir(parents=True, exist_ok=True)
    (managed / "config.yaml").write_text(
        yaml.safe_dump({"model": "managed/one", "agent": {"run_budget_seconds": 600}})
    )
    home = tmp_path / "root"
    home.mkdir()
    (home / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "model": {"default": "own/model", "provider": "own"},
                "agent": {"max_turns": 9, "run_budget_seconds": 5},
                "terminal": None,
            }
        )
    )
    other = tmp_path / "empty"
    other.mkdir()
    found = engine.as_hermes_reads([home, other])
    mine = found[str(home)]
    assert mine["model"] == {"default": "managed/one", "provider": "own"}
    assert mine["agent"] == {"max_turns": 9, "run_budget_seconds": 600}
    assert mine["terminal"] is None
    assert found[str(other)]["agent"] == {"run_budget_seconds": 600}


def test_the_env_probe_reads_config_yaml_alone_without_a_fresh_hermes_home(
    engine: HermesEngine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Step 38: the ".env vs config.yaml" probe with the installed Hermes. Its YAML
    side is Hermes's own gateway start on a copy holding config.yaml alone, pointed
    at inside a process started in the profile's own home: Hermes reports what
    config.yaml sets (telegram.reactions → TELEGRAM_REACTIONS=false) while the
    gateway uses the .env line, and no dependency environment is built for the copy
    (a process started in a fresh home would sync one into it: ~400 MB, ~50 s). The
    copy lives outside every Hermes data root, as live's temp folder does."""
    import tempfile

    from agos_core.engine import env_probe

    home = tmp_path / "roots" / "agos-x"
    home.mkdir(parents=True)
    (home / "config.yaml").write_text(
        yaml.safe_dump({"telegram": {"reactions": False}, "terminal": {"timeout": 300}})
    )
    (home / ".env").write_text("TELEGRAM_REACTIONS=true\n")
    outside = Path(tempfile.mkdtemp(prefix="agos-envprobe-", dir=Path.home() / ".cache"))
    monkeypatch.setattr(tempfile, "tempdir", str(outside))
    built: list[bool] = []
    real_copy = env_probe.yaml_only_home

    def copy(h: Path, managed: Path, scratch: Path) -> tuple[Path, Path]:
        yaml_home, scope = real_copy(h, managed, scratch)
        real_run = engine._in_runtime

        def run(at: Path, script: str, tag: str, **kw: object) -> str:
            assert at == home  # never a fresh HERMES_HOME
            out = real_run(at, script, tag, **kw)  # type: ignore[arg-type]
            built.append((yaml_home / "installs").exists())
            return out

        monkeypatch.setattr(engine, "_in_runtime", run)
        return yaml_home, scope

    monkeypatch.setattr(env_probe, "yaml_only_home", copy)
    try:
        found = engine.env_in_use(home)
    finally:
        shutil.rmtree(outside, ignore_errors=True)
    assert found["yaml"]["TELEGRAM_REACTIONS"] == "false"
    assert found["yaml"]["TERMINAL_TIMEOUT"] == "300"
    assert found["used"]["TELEGRAM_REACTIONS"] == "true"  # the .env line wins
    assert built and not any(built)


def test_secret_values_are_found_by_hermess_own_masker(
    engine: HermesEngine, tmp_path: Path
) -> None:
    """M1: the settings page hides the values Hermes's redact_config_value hides."""
    home = tmp_path / "root"
    home.mkdir()
    (home / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "mcp_servers": {
                    "crm": {
                        "headers": {"Authorization": "Bearer abcdefghijklmnop", "X-API-Key": "k"},
                        "env": {"FAL_KEY": "fal-abcdefghijkl", "REGION": "eu"},
                    },
                    "ref": {"headers": {"Authorization": "${CRM_TOKEN}"}},
                },
                "fallback_providers": [{"provider": "x", "api_key": "sk-" + "abcdefghijklmnop"}],
                "compression": {"threshold_tokens": 5},
            }
        )
    )
    found = {tuple(p) for p in engine.hermes_secrets([home])[str(home)]}
    assert found == {
        ("mcp_servers", "crm", "headers", "Authorization"),
        ("mcp_servers", "crm", "headers", "X-API-Key"),
        ("mcp_servers", "crm", "env", "FAL_KEY"),
        ("fallback_providers", 0, "api_key"),
    }
    # The same run as the page's read of the config.
    assert engine.as_hermes_reads([home])[str(home)]["compression"] == {"threshold_tokens": 5}


def test_voice_providers_and_models_are_hermess_schema(engine: HermesEngine) -> None:
    """C4: Voice notes' providers, models and model keys from Hermes's own schema."""
    from agos_core.engine import hermes_schema as hs
    from agos_core.engine import stt

    hs.forget()
    by = stt.by_name(engine.config_schema())
    assert by["groq"].models[0] == "whisper-large-v3-turbo"
    assert by["elevenlabs"].model_key == "stt.elevenlabs.model_id"
    assert "deepinfra" in by and stt.GEMINI.name in by and stt.OFF_NAME not in by


def test_the_settings_list_carries_hermess_secret_key_names(engine: HermesEngine) -> None:
    """M1: which settings and .env names are secrets comes with Hermes's schema
    (its _is_secret_config_key and the registry's password flag)."""
    from agos_core.engine import hermes_schema as hs

    hs.forget()
    fields = {f.key: f for f in engine.config_schema()}
    assert fields["auxiliary.vision.api_key"].secret
    assert not fields["compression.threshold"].secret
    env = {v.name: v for v in hs.env_registry() or []}
    assert env["FAL_KEY"].secret and env["TELEGRAM_BOT_TOKEN"].secret
    assert not env["TELEGRAM_HOME_CHANNEL"].secret


def test_extra_provider_keys_are_written_by_hermess_env_writer(engine: HermesEngine) -> None:
    """NB-3: a provider's extra keys are numbered lines of the managed .env, written
    by Hermes's own save_env_value / remove_env_value (scope off: Hermes refuses a
    name its scope pins); numbers stay contiguous (Hermes reads _2.. until a gap)."""
    base = "OPENROUTER_API_KEY"
    one, two, three = ("sk-or-v1-" + c * 40 for c in "abc")
    assert engine.managed_keys({"do": "add", "base": base, "key": one})["names"] == [f"{base}_2"]
    engine.managed_keys({"do": "add", "base": base, "key": two})
    engine.managed_keys({"do": "add", "base": base, "key": one})  # already there: no new line
    engine.managed_keys({"do": "add", "base": base, "key": three})
    env = config_file.read_env(engine.settings.managed_home)
    assert [env[f"{base}_{n}"] for n in (2, 3, 4)] == [one, two, three]
    engine.managed_keys({"do": "swap", "base": base, "n": [2, 3]})  # two, one, three
    found = engine.managed_keys({"do": "remove", "base": base, "n": 2})
    assert found["names"] == [f"{base}_2", f"{base}_3"]
    env = config_file.read_env(engine.settings.managed_home)
    assert (env[f"{base}_2"], env[f"{base}_3"]) == (one, three)


def test_an_old_hand_added_pool_key_is_removed_by_hermes(
    engine: HermesEngine, tmp_path: Path
) -> None:
    """A key once added by hand to a home's pool (before the managed .env) leaves
    that home's pool with the dashboard's own remove, found by its label."""
    import json

    home = tmp_path / "root"
    home.mkdir()
    (home / "config.yaml").write_text("{}\n")
    add = """
import asyncio, logging
logging.disable(logging.CRITICAL)
from hermes_cli.web_routers import ops
from hermes_cli.web_models import CredentialPoolAdd
asyncio.run(ops.add_credential_pool_entry(CredentialPoolAdd(
    provider="openrouter", api_key="agos-old-hand-key-1", label="Old key")))
print("AGOS-ADDED ok")
"""
    try:
        engine._in_runtime(home, add, "AGOS-ADDED")
    except Exception as error:  # noqa: BLE001
        pytest.skip(f"Hermes's runtime is not usable here: {error}")

    def labels() -> list[str]:
        pool = json.loads((home / "auth.json").read_text()).get("credential_pool", {})
        return [str(e.get("label")) for e in pool.get("openrouter", [])]

    assert "Old key" in labels()
    found = engine.credential_pool(
        home, {"do": "remove", "provider": "openrouter", "label": "Old key"}
    )
    assert found.get("removed") is True
    assert "Old key" not in labels()


_STAGE_SKILL = r"""
import json, logging
logging.disable(logging.CRITICAL)
from tools import write_approval as wa
job = json.loads(@JOB@)
made = wa.stage_write(wa.SKILLS, job, summary="patch demo", origin="foreground")
print("AGOS-STAGED " + json.dumps({"id": made.get("id")}))
"""


def test_an_approved_skill_write_is_undone_by_hermess_skill_ledger(
    engine: HermesEngine, tmp_path: Path
) -> None:
    """Approve a held skill patch, then Undo: Hermes's skill ledger rolls it back
    (tools/skill_ledger.py rollback_entry, by content hash, no size cut). A skill's
    asset of 2 MB or more stays; a later edit makes the Undo refuse."""
    import json

    home = tmp_path / "root"
    folder = home / "skills" / "demo"
    (folder / "assets").mkdir(parents=True)
    (home / "config.yaml").write_text("{}\n")
    skill = "---\nname: demo\ndescription: A demo skill.\n---\n\nOld body line.\n"
    (folder / "SKILL.md").write_text(skill)
    big = bytes(range(256)) * 10_000  # 2.56 MB
    (folder / "assets" / "big.bin").write_bytes(big)

    def stage(old: str, new: str) -> str:
        payload = {"action": "patch", "name": "demo", "old_string": old, "new_string": new}
        script = _STAGE_SKILL.replace("@JOB@", repr(json.dumps(payload)))
        try:
            return str(json.loads(engine._in_runtime(home, script, "AGOS-STAGED"))["id"])
        except Exception as error:  # noqa: BLE001
            pytest.skip(f"Hermes's runtime isn't usable here: {error}")

    done = engine.decide_pending(home, "skills", stage("Old body", "New body"), True, keep=True)
    assert done["gone"] and done["undo"], done
    assert "New body line." in (folder / "SKILL.md").read_text()
    back = engine.undo_pending(home, "skills", done["undo"])
    assert back["ok"], back
    assert (folder / "SKILL.md").read_text() == skill
    assert (folder / "assets" / "big.bin").read_bytes() == big  # never lost

    # A newer edit after the approval: the Undo refuses (it would lose it).
    done = engine.decide_pending(home, "skills", stage("Old body", "Second body"), True, keep=True)
    later = engine.decide_pending(home, "skills", stage("Second body", "Third body"), True)
    assert later["gone"]
    back = engine.undo_pending(home, "skills", done["undo"])
    assert not back["ok"] and "changed since" in back["error"]
    assert "Third body line." in (folder / "SKILL.md").read_text()


def test_usage_is_hermess_own_analytics(engine: HermesEngine) -> None:
    """W1/P1/B3: the Dashboard's headline and per-model lines are Hermes's /insights
    count (InsightsEngine, prompt cache included), its daily bars Hermes's usage
    analytics (_get_usage_analytics), of the root and each member, in Hermes's
    runtime, read only; one count."""
    import json
    import subprocess
    import tempfile

    from agos_core.engine.hermes import JUDGE_RUN, child_env

    # Outside ~/.hermes: Hermes resolves a member by name from its default root.
    outside = Path.home() / ".cache" / "agos-tests"
    outside.mkdir(parents=True, exist_ok=True)
    base = Path(tempfile.mkdtemp(dir=outside))
    try:
        root = base / "agos-x"
        homes = [root, root / "profiles" / "a-writer"]
        from conftest import hermes_ready_home

        hermes_ready_home(root)  # Hermes's per-root environment, not built again
        argv = list(engine._runtime_argv())
        argv[-1] = argv[-1].replace(JUDGE_RUN, "exec(sys.stdin.read())")
        for n, home in enumerate(homes):
            home.mkdir(parents=True, exist_ok=True)
            (home / "config.yaml").write_text("{}\n")
            script = (
                "from hermes_state import SessionDB\n"
                "db = SessionDB()\n"
                f"db.create_session('s-{n}', 'agos', model='claude-opus')\n"
                f"db.update_token_counts('s-{n}', input_tokens=10, output_tokens=5, "
                "cache_read_tokens=100, cache_write_tokens=20, "
                "model='claude-opus', api_call_count=2, billing_provider='anthropic')\n"
                "db.flush_token_counts()\n"
                "db.close()\n"
                "print('AGOS-OK')\n"
            )
            try:
                done = subprocess.run(  # noqa: S603 - Hermes's own launcher, fixed argv
                    argv,
                    input=script,
                    capture_output=True,
                    text=True,
                    timeout=180,
                    env=child_env({**engine._env(), "HERMES_HOME": str(home)}),
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired) as error:
                pytest.skip(f"Hermes's runtime is not usable here: {error}")
            if "AGOS-OK" not in done.stdout:
                pytest.skip(f"Hermes's runtime is not usable: {json.dumps(done.stderr[-300:])}")
        (root / "profiles" / "a-reader").mkdir(parents=True)  # no state.db yet
        found = engine.hermes_usage(root, ["a-writer", "a-reader"], 1.0, 30)
        # Prompt-cache reads and writes count (Hermes's /insights total); the bars
        # are the daily series: input + cache reads + output (no daily cache writes).
        assert found["models"] == {
            "claude-opus": {"tokens": 270, "calls": 4, "input": 20, "output": 10, "cached": 240}
        }, found
        assert sum(d["tokens"] for d in found["days"].values()) == 230
        assert not (root / "profiles" / "a-reader" / "state.db").exists()  # nothing made
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_the_stop_budget_is_hermess_own_from_the_owners_drain(
    engine: HermesEngine, tmp_path: Path
) -> None:
    """#24: the quiet drain answers with Hermes's own stop budget for the home
    (resolve_systemd_timeout_stop_sec of its drain readers)."""
    home = tmp_path / "root"
    home.mkdir()
    (home / "config.yaml").write_text("agent:\n  restart_drain_timeout: 200\n")
    budget = engine._quiet_drain(home, on=True)
    if budget is None:
        pytest.skip("Hermes's runtime is not usable here")
    assert budget == 230.0  # max(200, cron 30 + 10) + 30 headroom
    assert engine._quiet_drain(home, on=False) == 0.0
    assert not (home / ".drain_request.json").exists()


def test_one_approved_memory_change_is_undone_by_hermess_public_ops(
    engine: HermesEngine, tmp_path: Path
) -> None:
    """#25: add -> remove, replace -> replace back, remove -> add, each through
    MemoryStore's public methods in Hermes's runtime."""
    import json

    home = tmp_path / "root"
    home.mkdir()
    (home / "config.yaml").write_text("{}\n")

    def run(code: str) -> dict[str, list[str]]:
        script = (
            "import json\n"
            "from tools.memory_tool import load_on_disk_store\n"
            "store = load_on_disk_store()\n"
            f"{code}\n"
            "store = load_on_disk_store()\n"
            "print('AGOS-MEM ' + json.dumps({'memory': list(store.memory_entries),"
            " 'user': list(store.user_entries)}))\n"
        )
        try:
            found: dict[str, list[str]] = json.loads(engine._in_runtime(home, script, "AGOS-MEM"))
        except Exception as error:  # noqa: BLE001
            pytest.skip(f"Hermes's runtime isn't usable here: {error}")
        return found

    first = run("store.add('memory', 'Alpha likes tea')")
    second = run("store.add('memory', 'Beta likes coffee')")
    assert engine.undo_pending(home, "memory", {"before": first, "after": second})["ok"]
    assert run("pass") == first
    third = run("store.replace('memory', 'Alpha likes tea', 'Alpha likes green tea')")
    assert engine.undo_pending(home, "memory", {"before": first, "after": third})["ok"]
    assert run("pass") == first
    fourth = run("store.remove('memory', 'Alpha likes tea')")
    assert engine.undo_pending(home, "memory", {"before": first, "after": fourth})["ok"]
    assert run("pass") == first
    # Changed since: refused, nothing lost.
    newer = run("store.add('memory', 'Gamma')")
    back = engine.undo_pending(home, "memory", {"before": fourth, "after": first})
    assert not back["ok"] and "changed since" in back["error"]
    assert run("pass") == newer


def test_the_owner_rules_parts_fit_hermess_own_section_budget(
    engine: HermesEngine, tmp_path: Path
) -> None:
    """#43: the biggest rule set AGOS puts in the sections renders within Hermes's
    own caps (format_system_prompt_sections, the per-section and total limits)."""
    import json

    from agos_core.actions import owner_rules

    n = 0
    while owner_rules.section_parts([f"Rule {i}: " + "x" * 200 for i in range(n + 1)]):
        n += 1
    parts = owner_rules.section_parts([f"Rule {i}: " + "x" * 200 for i in range(n)])
    assert len(parts) == 2 and n > 30  # well over one section's 4,000
    home = tmp_path / "root"
    home.mkdir()
    (home / "config.yaml").write_text("{}\n")
    items = [{"id": i, "content": t} for i, t in zip(owner_rules.SECTION_IDS, parts, strict=True)]
    script = (
        "import json\n"
        "from types import SimpleNamespace\n"
        "from hermes_cli import plugins_dispatch as d\n"
        f"items = [SimpleNamespace(**x) for x in json.loads({json.dumps(json.dumps(items))})]\n"
        "print('AGOS-FIT ' + json.dumps([len(d.format_system_prompt_sections(items)),"
        " d.MAX_SYSTEM_PROMPT_SECTIONS_TOTAL_CHARS, d.MAX_SYSTEM_PROMPT_SECTION_CHARS]))\n"
    )
    try:
        size, total, one = json.loads(engine._in_runtime(home, script, "AGOS-FIT"))
    except Exception as error:  # noqa: BLE001
        pytest.skip(f"Hermes's runtime isn't usable here: {error}")
    assert (total, one) == (owner_rules.TOTAL_MAX, owner_rules.SECTION_MAX)
    assert size <= total and all(len(p.strip()) <= one for p in parts)


def test_a_paired_sender_is_hermess_pairing_store_answer(
    engine: HermesEngine, tmp_path: Path
) -> None:
    """#56: PairingStore.is_approved in Hermes's runtime, in that root."""
    import json

    home = tmp_path / "root"
    folder = home / "platforms" / "pairing"
    folder.mkdir(parents=True)
    (home / "config.yaml").write_text("{}\n")
    (folder / "telegram-approved.json").write_text(
        json.dumps({"555": {"user_name": "Sam", "approved_at": 1.0}})
    )
    try:
        assert engine.pairing_approved(home, "telegram", "555") is True
    except Exception as error:
        if "didn't answer" in str(error):
            pytest.skip(f"Hermes's runtime isn't usable here: {error}")
        raise
    assert engine.pairing_approved(home, "telegram", "556") is False
