"""Each workspace root's own subscription login (ADR 0020, revised): read only,
through Hermes's own functions (engine.hermes_logins; the stand-in here keeps
Hermes's borrowed rule, the real one is in test_hermes_logins_live.py)."""

import json
from pathlib import Path
from types import SimpleNamespace

from conftest import hermes_logins_read

from agos_core.actions import general_sync

ENGINE = SimpleNamespace(hermes_logins=hermes_logins_read)


def _root(tmp_path: Path, provider: str, pool: list[dict[str, str]]) -> Path:
    root = tmp_path / "agos-alpha"
    root.mkdir()
    (root / "config.yaml").write_text(f"model:\n  provider: {provider}\n  default: x\n")
    (root / "auth.json").write_text(json.dumps({"credential_pool": {provider: pool}}))
    return root


def test_borrowed_claude_code_login_is_not_the_root_own(tmp_path: Path) -> None:
    root = _root(tmp_path, "anthropic", [{"source": "claude_code"}])
    assert not general_sync.own_login(hermes_logins_read(root), "anthropic")
    # Until he connects it, the root keeps reading Claude Code's file.
    assert general_sync.borrowing_needed(ENGINE, root)


def test_root_signed_in_by_hermes_needs_no_borrowing(tmp_path: Path) -> None:
    root = _root(tmp_path, "anthropic", [{"source": "manual:hermes_pkce"}])
    assert general_sync.own_login(hermes_logins_read(root), "anthropic")
    assert not general_sync.borrowing_needed(ENGINE, root)


def test_key_providers_never_need_a_login(tmp_path: Path) -> None:
    root = _root(tmp_path, "openrouter", [{"source": "env:OPENROUTER_API_KEY"}])
    assert not general_sync.borrowing_needed(ENGINE, root)


def test_when_hermes_cant_say_the_root_keeps_borrowing(tmp_path: Path) -> None:
    from agos_core.engine.hermes import EngineError

    def fails(home: Path, status: bool = False) -> dict[str, object]:
        raise EngineError("no runtime")

    root = _root(tmp_path, "anthropic", [{"source": "manual:hermes_pkce"}])
    assert general_sync.borrowing_needed(SimpleNamespace(hermes_logins=fails), root)


def test_no_agos_code_reads_auth_json_or_parses_auth_list() -> None:
    """M2/P7 (925047d area 1): sign-in state and the credential pool are read by
    Hermes's own functions; no AGOS module opens auth.json itself or regex-parses
    `hermes auth list` (migrate_root's one-time move and the plugin excepted)."""
    import re

    src = Path(__file__).resolve().parents[1] / "src" / "agos_core"
    found = []
    for path in sorted(src.rglob("*.py")):
        rel = path.relative_to(src).as_posix()
        if rel.startswith("hermes_plugin/") or rel == "migrate_root.py":
            continue
        text = path.read_text()
        # "auth.json" named, then read within the next lines (json.loads / read_text).
        if re.search(
            r"""["']auth\.json["'][^\n]*(\n[^\n]*){0,3}(read_text|json\.load|open\()""", text
        ):
            found.append(rel)
        if re.search(r"""["']auth["'],\s*["']list["']""", text):
            found.append(rel + " (auth list)")
    assert not found, found
