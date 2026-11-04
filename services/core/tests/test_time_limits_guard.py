"""Guard: General settings → Time limits covers every timeout the installed Hermes
has, so a Hermes upgrade can't bring a clock back on the team's work unseen.

It parses the installed Hermes (~/.hermes/hermes-agent, v0.22.2 when written):
- hermes_cli/config_defaults.py DEFAULT_CONFIG (a pure-data module): every key
  whose name holds "timeout", and every auxiliary task's `timeout`;
- every `resolve_timeout("<key>")` in its code (agent/deadline.py: the
  `timeouts.<key>` section of config.yaml);
- the timeouts tools/terminal_tool.py reads from the environment at start.
Each must be on the card (engine/time_limits.py) or in REVIEWED below, with why it
is not a clock on the team's work. A new one fails this test until it is placed.
"""

import re
import runpy
from pathlib import Path
from typing import Any

import pytest

from agos_core.engine.time_limits import BY_KEY

HERMES = Path.home() / ".hermes" / "hermes-agent"
DEFAULTS_FILE = HERMES / "hermes_cli" / "config_defaults.py"

pytestmark = pytest.mark.skipif(not DEFAULTS_FILE.is_file(), reason="Hermes isn't installed")

# Hermes's timeouts that are not on the card, each with why (v0.22.2).
REVIEWED = {
    "agent.gateway_turn_lease_timeout": "a message waiting for a session lease; Hermes forces ≤0 to 5 s",
    "agent.restart_drain_timeout": "the stop budget once Hermes is already stopping (systemd caps it)",
    "agent.cron_drain_timeout": "a floor under that stop wait, clamped to the shutdown watchdog",
    "agent.build_wait_timeout": "only a hung agent build (MCP discovery) before the first answer",
    "agent.stream_drain_timeout": "draining a finished stream (2 s)",
    "agent.gateway_startup_restore_drain_timeout": "the gateway's start-up gate",
    "agent.gateway_startup_warmup_timeout": "the gateway's start-up gate",
    "agent.local_stream_stale_timeout": "a dead local model stream; retried, not a work limit",
    "browser.dialog_timeout_s": "auto-dismisses a page's JS dialog nobody handles",
    "context_file_read_timeout": "reading AGENTS.md-style files at start",
    "mcp_discovery_timeout": "listing an app's tools at start",
    "mcp_single_query_discovery_timeout": "listing an app's tools for a one-shot run",
    "compression.hygiene_timeout_seconds": "pre-turn compaction; on expiry the turn goes on uncompressed",
    "compression.context_timeout_seconds": "silence budget of a compaction, floored at its helper's timeout",
    "auxiliary.compression.no_progress_timeout": "a stalled stream fails over to a retry",
    "dashboard.ws_ping_timeout": "the dashboard's websocket ping",
    "stt.openai.timeout": "OpenAI speech-to-text (AGOS uses Gemini)",
    "skills.inline_shell_timeout": "a skill's inline !`cmd` snippet",
    "discord.voice_playback_timeout_seconds": "a floor Hermes extends to the clip's length",
    "plugins.clone_timeout_seconds": "installing a plugin",
    "plugins.load_timeout_seconds": "loading a plugin at start",
    "cron.script_timeout_seconds": (
        "a cron job's script (cron/scheduler_script.py:450, Hermes's 3600 s): AGOS's"
        " no-agent jobs (an automation's run, engine/automation_run.py; the Daily"
        " digest) only put cards on the board or print a summary, in seconds; the"
        " team's work runs on those cards, under the card's own limits"
    ),
    "cron.session_db_timeout_seconds": "opening the session database for a cron run",
    "cron.media_send_timeout_seconds": "sending one attachment of a cron delivery",
    "kanban.dispatch_stale_timeout_seconds": "a card with no heartbeat; a working card keeps beating",
    "code_execution.kernel_idle_timeout": "an idle code kernel (a running cell is not idle)",
    "gateway.signal_interrupt_grace_timeout": "grace after an unexpected signal",
    "gateway.platform_connect_timeout": "connecting to Telegram/Discord at start",
    "gateway.loop_watchdog_probe_timeout_s": "the gateway's own event-loop watchdog",
    "gateway.startup_watchdog_timeout_seconds": "the gateway's start-up watchdog",
    "gateway.scale_to_zero.idle_timeout_minutes": "scale-to-zero hosting only",
    "doctor.live_probe_timeout": "`hermes doctor --live`",
    "lsp.wait_timeout": "waiting for a language server's diagnostics",
    "lsp.warmup_timeout": "a language server's first start",
    "lsp.idle_timeout": "an idle language server",
    "x_search.timeout_seconds": "the X search tool's request",
}


def _defaults() -> dict[str, Any]:
    config = runpy.run_path(str(DEFAULTS_FILE))["DEFAULT_CONFIG"]
    assert isinstance(config, dict)
    return config


def _leaves(node: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in node.items():
        if isinstance(value, dict):
            out |= _leaves(value, f"{prefix}{key}.")
        else:
            out[f"{prefix}{key}"] = value
    return out


def _code() -> list[Path]:
    skip = {"tests", "node_modules", "venv", ".venv", "evals", "website", "__pycache__"}
    return [p for p in HERMES.rglob("*.py") if not skip & set(p.relative_to(HERMES).parts)]


def hermes_timeouts() -> dict[str, Any]:
    """Every timeout of the installed Hermes → its default (None when in code)."""
    config = _defaults()
    found = {k: v for k, v in _leaves(config).items() if "timeout" in k.rsplit(".", 1)[-1]}
    for task, block in config["auxiliary"].items():
        if isinstance(block, dict):
            found.setdefault(f"auxiliary.{task}.timeout", block.get("timeout"))
    call = re.compile(r"resolve_timeout\(\s*[\"']([\w.]+)[\"']")
    for path in _code():
        for key in call.findall(path.read_text(encoding="utf-8", errors="replace")):
            found.setdefault(f"timeouts.{key}", None)
    terminal = (HERMES / "tools" / "terminal_tool.py").read_text()
    for name in re.findall(r"_safe_parse_import_env\(\s*\"([A-Z_]*TIMEOUT[A-Z_]*)\"", terminal):
        found.setdefault(name, None)
    return found


def test_hermes_has_no_timeout_the_card_misses() -> None:
    found = hermes_timeouts()
    missing = sorted(k for k in found if k not in BY_KEY and k not in REVIEWED)
    assert not missing, (
        "Hermes has timeouts General settings → Time limits doesn't cover. Add each to "
        f"engine/time_limits.py (or, if it isn't a clock on the team's work, to REVIEWED): {missing}"
    )
    # The resolve_timeout keys this was written against are still found (the parser works).
    assert {"timeouts.tools.sequential_call", "timeouts.mcp.tool_call"} <= set(found)
    assert "TERMINAL_MAX_FOREGROUND_TIMEOUT" in found


def test_the_card_matches_what_hermes_reads() -> None:
    """P3 (925047d area 2): no copy of a default DEFAULT_CONFIG has (the card reads
    those from Hermes's settings list); only a key DEFAULT_CONFIG lacks keeps the
    literal from Hermes's code, with its source."""
    found = hermes_timeouts()
    stale = sorted(k for k in REVIEWED if k not in found)
    assert not stale, f"REVIEWED names timeouts Hermes no longer has: {stale}"
    for key, limit in BY_KEY.items():
        if not limit.read_by_hermes:
            assert key not in found or found[key] is None, (
                f"Hermes reads {key} now: mark it read in engine/time_limits.py"
            )
            continue
        assert key in found, f"{key} is on the card but Hermes no longer has it"
        if found[key] is not None:  # in DEFAULT_CONFIG: read from Hermes, never copied
            assert limit.code_default is None, f"{key}: Hermes's default is copied"
        else:  # a default only in Hermes's code: kept with where it is
            assert limit.code_default is not None and limit.source, key
