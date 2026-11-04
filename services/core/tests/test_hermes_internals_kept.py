"""The Hermes internals AGOS still calls are exactly the ones v0.22.2 has no public
CLI or API for (each with the reason); a new one, or one coming back after it
moved to Hermes's CLI/API, fails here."""

import re
from pathlib import Path

from ownership_scan import REGISTRY_MODULES

SRC = Path(__file__).resolve().parents[1] / "src" / "agos_core"

# internal -> where it may be used (and why it stays, Hermes v0.22.2 source):
KEPT = {
    # Webhook routes with filters and enabled: `hermes webhook subscribe` has
    # neither (hermes_cli/subcommands/webhook.py); Hermes's dashboard uses the same
    # helper (hermes_cli/web_routers/ops.py).
    "_mutate_subscriptions": {"engine/hermes/webhooks.py"},
    # A quiet stop: `hermes gateway stop` has no quiet flag (subcommands/gateway.py).
    "drain_control": {"engine/hermes/gateway_run.py"},
    # The unit's name: no CLI prints it (`gateway status` has no JSON).
    "get_service_name": {"engine/hermes/gateway_unit.py"},
    # MCP sign-in for the web: `hermes mcp login` is interactive only
    # (subcommands/mcp.py); the URL hand-off is the dashboard's own flow class.
    "_probe_single_server": {"engine/connect_helper.py"},
    "_oauth_tokens_present": {"engine/connect_helper.py"},
    "DashboardOAuthFlow": {"engine/connect_helper.py"},
}


def _sources() -> dict[str, str]:
    return {
        p.relative_to(SRC).as_posix(): p.read_text()
        for p in SRC.rglob("*.py")
        if not p.relative_to(SRC).as_posix().startswith(("db/migrations", "hermes_plugin/"))
        and p.name != "hermes_contract.py"  # the list of every one (with this file's)
        and not p.relative_to(SRC).as_posix().startswith("engine/contract/")  # its entries
        # evidence text, not a use (the registry and its files part)
        and p.relative_to(SRC).as_posix() not in REGISTRY_MODULES
    }


def test_only_the_kept_internals_are_used_where_allowed() -> None:
    for name, allowed in KEPT.items():
        used = {rel for rel, text in _sources().items() if re.search(rf"\b{name}\b", text)}
        assert used <= allowed, (name, used)


def test_the_cron_bridge_keeps_only_what_has_no_cli() -> None:
    """get (executions: no --json), pause with a reason (CLI/API take none), the
    schedule check (parse_schedule, no CLI), and a missed run's slot for catch-up
    (compute_next_run + the grace, no CLI: `hermes cron` prints no past occurrence).
    The rest is `hermes cron ...`."""
    from agos_core.engine.cron import _BRIDGE

    ops = set(re.findall(r'op == "(\w+)"', _BRIDGE))
    assert ops == {"get", "pause", "check", "slots"}, ops
    assert "J.trigger_job" not in _BRIDGE and "J.create_job" not in _BRIDGE
    assert "J.update_job" not in _BRIDGE and "J.remove_job" not in _BRIDGE
    used = {rel for rel, text in _sources().items() if "from cron import jobs" in text}
    assert used == {"engine/cron.py"}, used


def test_what_i_learned_reads_the_ledger_and_writes_nothing() -> None:
    """`hermes curator ledger` prints a table only (no --json; hermes_cli/curator.py
    _cmd_ledger) and `hermes journey --json` has skill/memory nodes, no ledger ids
    or before/after (agent/learning_graph.py): AGOS reads the ledger with Hermes's own
    list_entries / read_blob in its runtime (engine _SKILL_CHANGES), never the file;
    an undo is Hermes's own `curator rollback <id>`."""
    from agos_core.engine import hermes as engine_hermes

    text = (SRC / "actions" / "proactive.py").read_text()
    assert ".curator_ledger.jsonl" not in text and '"curator", "rollback"' in text
    script = engine_hermes._SKILL_CHANGES
    assert "skill_ledger.list_entries(" in script and "skill_ledger.read_blob(" in script
    for write in ("write_text", "write_bytes", "unlink", "open(", "rollback_entry", "append"):
        assert write not in script.replace("out.append(", ""), write
