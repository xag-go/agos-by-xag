"""What the agents are told lives in Hermes (SOUL.md), never added by AGOS per turn."""

from agos_core.actions.library import profile_settings
from agos_core.engine import identity
from agos_core.engine.cron import automation_prompt


def test_the_rules_are_in_soul_md_for_the_cofounder_and_every_member() -> None:
    cofounder = identity.soul_text("Argan", "Argan oil shop", "", cofounder="## Team\n- @designer")
    member = identity.member_soul("Designer", "Argan", "Argan oil shop", "You draw.")
    for soul in (cofounder, member):
        assert identity.RULES in soul
        for rule in (
            "kanban_create",
            "cronjob tool",
            "Scheduled automations",
            "outside the workspace",
        ):
            assert rule in soul
    assert identity.cofounder_view(cofounder) == "## Team\n- @designer"
    assert identity.cofounder_view(member) == ""


def test_an_automation_job_says_only_what_to_do() -> None:
    prompt = automation_prompt("Summarize new files.")
    assert "Summarize new files." in prompt and "Rules for automations" not in prompt


def test_hermes_loads_soul_md_whole() -> None:
    assert profile_settings([])["context_file_max_chars"] == "1000000"


def test_the_cofounder_does_agos_action_jobs_itself_and_never_hands_them_to_a_member() -> None:
    soul = identity.soul_text("Argan", "Argan oil shop", "")
    assert "does ITSELF" in soul or "do it yourself" in soul
    for kind in ("automations", "team", "skills", "board admin", "workspace settings"):
        assert kind in identity.RULES
    assert "Co-Founder-only work" in identity.RULES
    # A sanity cap so the shared rules stay readable; live's team rules (c65fb288)
    # already put them at ~8.5k.
    assert len(identity.RULES) < 10_000
