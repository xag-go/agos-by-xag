"""The owner's "Daily digest" notification option does what it says (actions/digest.py)."""

import inspect

from agos_core.actions import agent_power, digest, idle, notification_rules, token_watch
from agos_core.actions.services.channel import owner_needs


def test_every_card_with_a_delivery_rule_knows_the_digest() -> None:
    """Guard: each consumer of a notification rule handles "batched" (it acted as
    "instant" before: only "silent" was tested)."""
    assert set(notification_rules.EVENTS) == {
        "task.waiting",
        "task.tokens",
        "agos.error",
        "agos.agent_power",
    }
    for module in (owner_needs, token_watch, agent_power):
        source = inspect.getsource(module)
        assert '"batched"' in source, module.__name__
        assert "digest" in source, module.__name__
    # The clock is Hermes's cron (a no-agent job), not an AGOS loop.
    assert "digest" not in inspect.getsource(idle.chores)
    assert not hasattr(digest, "tick")
    assert digest.HOUR == 9 and digest.SCHEDULE == "0 9 * * *"
    # The job's script is standard library only (Hermes runs it with its own Python).
    import ast

    tree = ast.parse(digest.SCRIPT_TEXT)
    names = {
        a.name.split(".")[0]
        for n in ast.walk(tree)
        if isinstance(n, ast.Import | ast.ImportFrom)
        for a in (n.names if isinstance(n, ast.Import) else [ast.alias(n.module or "")])
    }
    assert names <= {"json", "sys", "urllib", "pathlib"}
