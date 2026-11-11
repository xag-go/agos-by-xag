"""Check before save: every problem at once, in the owner's words, and the plain
"this is how it will run" preview (engine/automation_check.py)."""

from typing import Any

from agos_core.engine import automation_check as ac
from agos_core.engine.automation_run import _HOLE

TEAM = {
    "intake": ac.Who("Media Intake"),
    "brand": ac.Who("Brand Voice Developer"),
    "editor": ac.Who("Video Editor"),
    "ideas": ac.Who("Ideas Writer"),
    "sleepy": ac.Who("Sleepy Agent", on=False),
}


def spec(steps: list[dict[str, Any]] | None = None, **extra: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "name": "Watcher",
        "instructions": "Do the work.",
        "schedule": "0 9 * * *",
        "hook": False,
        "agent": None,
        "steps": steps or [],
        "variables": [],
        "check_first": False,
    }
    return {**base, **extra}


def step(key: str, agent: str | None = "intake", **extra: Any) -> dict[str, Any]:
    return {"key": key, "title": f"T {key}", "agent": agent, "kind": "work", **extra}


def test_a_cycle_and_an_unknown_agent_come_back_together() -> None:
    steps = [
        step("a", "intake", waits_on=["b"]),
        step("b", "ghost", waits_on=["a"]),
        step("c", "editor", waits_on=["nowhere"]),
    ]
    report = ac.check(spec(steps), TEAM)
    assert not report.ok and report.preview == ""
    text = "\n".join(report.problems)
    assert "@ghost, who is not in this team" in text and "“T b”" in text
    assert "“T a” and “T b” wait on each other in a circle" in text
    assert "“T c” waits on the step “nowhere”, which does not exist" in text
    assert len(report.problems) == 3


def test_blocked_step_and_missing_review_target_and_variables_and_empty_title() -> None:
    steps = [
        step("a", waits_on=["b"]),
        step("b", waits_on=["a"]),
        step("c", waits_on=["a"]),
        {"key": "r", "title": "Check it", "kind": "review", "agent": "brand", "reviews": "zzz"},
        {"key": "e", "title": "", "agent": "intake"},
        step("v", description="Use {topic} and {run.date}"),
    ]
    text = "\n".join(ac.check(spec(steps), TEAM).problems)
    assert "“T c” can never start" in text
    assert "“Check it” reviews the step “zzz”, which does not exist" in text
    assert "Step 5 has no title" in text
    assert "uses {topic}" in text and "run.date" not in text


def test_name_instructions_and_trigger_are_needed() -> None:
    report = ac.check(spec(name="", instructions="", schedule=""), TEAM)
    text = "\n".join(report.problems)
    assert "no name" in text and "no instructions" in text and "Nothing starts it" in text
    assert ac.check(spec(schedule="", hook=True), TEAM).ok


def test_a_review_can_only_check_a_work_step_and_approval_only_is_nobody() -> None:
    steps = [
        {"key": "ok", "title": "OK?", "kind": "approval"},
        {"key": "r", "title": "Review", "kind": "review", "agent": "brand", "reviews": "ok"},
    ]
    text = "\n".join(ac.check(spec(steps), TEAM).problems)
    assert "can only review a work step" in text
    only = ac.check(spec([{"key": "ok", "title": "OK?", "kind": "approval"}]), TEAM)
    assert any("nobody does any work" in p for p in only.problems)


def test_one_agent_automation_unknown_agent_and_variables_in_instructions() -> None:
    report = ac.check(spec(agent="ghost", instructions="Hi {who}"), TEAM)
    assert any("@ghost is not in this team" in p for p in report.problems)
    assert any("The instructions uses {who}" in p for p in report.problems)
    fine = ac.check(
        spec(agent="intake", instructions="Hi {who}", variables=[{"name": "who"}]), TEAM
    )
    assert fine.ok


def test_warnings_do_not_block() -> None:
    steps = [step("a"), step("b", waits_on=["a"]), step("c", "sleepy", waits_on=["b"]), step("d")]
    report = ac.check(spec(steps), TEAM)
    assert report.ok
    text = "\n".join(report.warnings)
    assert "Sleepy Agent is turned off" in text
    assert "“T d” waits for nothing, so it starts together with the first step" in text
    assert "The result of “T d” is not used" in text
    chain = [step(f"s{i}", waits_on=[f"s{i - 1}"] if i else []) for i in range(9)]
    assert any("long chain" in w for w in ac.check(spec(chain), TEAM).warnings)


def test_inspiration_watcher_like_steps_preview_two_at_the_same_time() -> None:
    steps = [
        step("intake", "intake", title="Collect the link"),
        step("voice", "brand", waits_on=["intake"], title="Brand voice"),
        step("video", "editor", waits_on=["intake"], title="Edit the video"),
        step("done", None, waits_on=["voice", "video"], title="Write the status"),
    ]
    report = ac.check(spec(steps, schedule="", hook=True), TEAM)
    assert report.ok, report.problems
    lines = report.preview.splitlines()
    assert lines[0] == "Starts the moment something arrives on its webhook address."
    assert lines[1] == "1) Media Intake does “Collect the link”."
    assert lines[2] == (
        "2) Brand Voice Developer (“Brand voice”) and Video Editor (“Edit the video”) "
        "work at the same time."
    )
    assert lines[3] == "3) The Co-Founder does “Write the status”."


def test_a_straight_chain_previews_in_order_with_review_approval_and_schedule() -> None:
    steps = [
        step("research", "intake", title="Find topics"),
        step("ideas", "ideas", waits_on=["research"], title="Write ideas"),
        {
            "key": "check",
            "title": "Check",
            "kind": "review",
            "agent": "brand",
            "reviews": "ideas",
        },
        {"key": "ok", "title": "Publish?", "kind": "approval", "waits_on": ["check"]},
    ]
    report = ac.check(spec(steps, check_first=True), TEAM, schedule_text="every day at 09:00")
    assert report.ok, report.problems
    assert report.preview.splitlines()[:7] == [
        "Starts on its schedule (every day at 09:00).",
        "Before anything starts, you approve the run (on the Board).",
        "1) Media Intake does “Find topics”.",
        "2) Ideas Writer does “Write ideas”.",
        "3) Brand Voice Developer checks “Write ideas”.",
        "4) You approve “Publish?”.",
        "Each step starts once the steps it waits for are done.",
    ]


def test_a_later_step_that_is_not_first_with_no_waits_starts_with_the_first() -> None:
    steps = [step("a", title="One"), step("b", "editor", title="Two")]
    lines = ac.check(spec(steps), TEAM).preview.splitlines()
    assert "1) Media Intake (“One”) and Video Editor (“Two”) work at the same time." in lines
    # a wait on a LATER step is no wait in the real run: it starts with the first steps
    steps = [step("a", waits_on=["b"], title="One"), step("b", "editor", title="Two")]
    lines = ac.check(spec(steps), TEAM).preview.splitlines()
    assert any(line.startswith("1) Media Intake") and "Video Editor" in line for line in lines)


def test_ordered_puts_every_step_after_the_ones_it_waits_on_and_keeps_a_good_order() -> None:
    good = [step("a"), step("b", waits_on=["a"])]
    assert ac.ordered(good) == good
    bad = [step("b", waits_on=["a"]), step("a"), step("c", waits_on=["b"])]
    assert [s["key"] for s in ac.ordered(bad)] == ["a", "b", "c"]
    circle = [step("a", waits_on=["b"]), step("b", waits_on=["a"])]
    assert [s["key"] for s in ac.ordered(circle)] == ["a", "b"]


def test_only_if_is_read_defensively_and_shown() -> None:
    steps = [
        step("a", "intake", title="Collect"),
        step("b", "editor", waits_on=["a"], title="Edit", only_if="there is a new video"),
        step("c", "brand", waits_on=["a"], title="Voice", only_if={"text": "it is Monday"}),
    ]
    text = ac.check(spec(steps), TEAM).preview
    assert "Video Editor (“Edit”, only if there is a new video)" in text
    assert "Brand Voice Developer (“Voice”, only if it is Monday)" in text
    single = ac.check(spec([step("b", "editor", title="Edit", only_if="x is new")]), TEAM).preview
    assert "Video Editor does “Edit”, only if x is new." in single


def test_the_hole_matches_the_one_the_run_fills() -> None:
    assert ac.HOLE.pattern == _HOLE.pattern
