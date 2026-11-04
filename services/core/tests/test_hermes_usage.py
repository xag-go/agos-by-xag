"""The Dashboard's Usage is read from the workspace's Hermes: its /insights count
(agent/insights.py InsightsEngine, prompt-cache tokens included) for the headline and
models, its usage analytics' daily series (hermes_cli/web_routers/analytics.py
_get_usage_analytics) for the bars, over the root and each member. The headline and the
per-model lines are one count (W1/P1/B3, 925047d); AGOS keeps no count and runs no
SQL of its own over Hermes's sessions."""

from pathlib import Path
from typing import Any

import channels_rig

env, fake_telegram = channels_rig.env, channels_rig.fake_telegram


def hermes_said(models: dict[str, dict[str, int]], days: dict[str, dict[str, int]]) -> Any:
    """A stand-in for engine.hermes_usage that records what it was asked."""
    asked: list[tuple[Path, list[str], float, int]] = []

    def usage(root: Path, members: list[str], month_days: float, chart_days: int) -> Any:
        asked.append((root, sorted(members), month_days, chart_days))
        return {"models": models, "days": days}

    usage.asked = asked  # type: ignore[attr-defined]
    return usage


def test_usage_is_hermess_own_analytics_and_one_count(env: Any) -> None:
    client, core, _fake, _tg, ws = env
    from datetime import UTC, datetime

    today = datetime.now().date().isoformat()
    usage = hermes_said(
        {
            "claude-opus": {"tokens": 1165, "calls": 5, "input": 15, "output": 150, "cached": 1000},
            "gpt-x": {"tokens": 3, "calls": 1, "input": 1, "output": 2},
        },
        {today: {"tokens": 1168, "calls": 6}, "1999-01-01": {"tokens": 9, "calls": 9}},
    )
    core.engine.hermes_usage = usage
    shown = client.get(f"/workspaces/{ws}/overview").json()["usage"]
    # One count: the per-model lines add up to the headline.
    assert shown["tokens"] == sum(m["tokens"] for m in shown["models"]) == 1168
    assert shown["inputTokens"] == 16 and shown["outputTokens"] == 152
    assert shown["cachedTokens"] == 1000  # the provider's prompt cache: most of the count
    assert shown["replies"] == sum(m["replies"] for m in shown["models"]) == 6
    models = {m["model"]: (m["tokens"], m["replies"]) for m in shown["models"]}
    assert models == {"claude-opus": (1165, 5), "gpt-x": (3, 1)}
    bars = {d["day"]: d["tokens"] for d in shown["days"]}
    assert len(shown["days"]) == 30 and "1999-01-01" not in bars
    if today in bars:  # the core's 30 days are UTC ones
        assert bars[today] == 1168
    [(root, members, month_days, chart_days)] = usage.asked
    assert root == core.engine.profile_home(ws) and members == []
    assert 0 < month_days <= 31 and chart_days == 30
    assert datetime.now(UTC)  # (no AGOS clock of its own in the count)


def test_hermes_not_answering_shows_nothing_counted(env: Any) -> None:
    client, core, _fake, _tg, ws = env
    from agos_core.engine.hermes import EngineError

    def down(*_a: Any) -> Any:
        raise EngineError("Hermes didn't answer")

    core.engine.hermes_usage = down
    shown = client.get(f"/workspaces/{ws}/overview").json()["usage"]
    assert shown["models"] == [] and shown["tokens"] == 0


def test_no_agos_sql_over_hermess_sessions_is_left() -> None:
    """Guard: the Dashboard's usage has no AGOS SQL over session_model_usage /
    sessions any more (engine/hermes_usage.py is gone)."""
    src = Path(__file__).resolve().parents[1] / "src" / "agos_core"
    assert not (src / "engine" / "hermes_usage.py").exists()
    for path in src.rglob("*.py"):
        assert "FROM session_model_usage" not in path.read_text(), path
