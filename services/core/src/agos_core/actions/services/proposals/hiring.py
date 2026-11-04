"""Acting on an approved hire (through the team's own code) and on an instructions change (the consent token); undoing a hire.
Must not: decide; it only acts once decided.

Split out of agos_core.actions.proposals (which re-exports it); behaviour unchanged.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from agos_core.actions.errors import ActionError
from agos_core.actions.services.proposals.hire_checks import hire_lead_problems, hire_skill_problems
from agos_core.actions.services.proposals.proposal_states import CONSENT_FILE, KEEP_TOKENS
from agos_core.context import Core
from agos_core.db.rows import now
from agos_core.engine import proposals as rules

__all__ = [
    "consent",
    "hire",
    "own_hire",
    "unhire",
]

log = logging.getLogger("agos_core.actions.proposals")  # the old module's logger (one name)

# ---- what an approve does -------------------------------------------------------------


def hire(
    core: Core,
    workspace_id: str,
    payload: dict[str, Any],
    *,
    reason: str = "approved a hire proposal",
    review_after: bool = True,
) -> dict[str, Any]:
    """The member, through the team's own code (its Hermes profile, the Co-Founder's
    dispatch list), its DM and, when asked, its Telegram topic. The coding engine
    stays in the proposal (the card) for later. Returns what Undo needs. Only the
    owner's own decision reaches it: his Approve of a hire card, or his own New agent
    (`reason`: its revision's words)."""
    from agos_core.actions import library as library_actions
    from agos_core.actions import workers

    problems = rules.problems("hire", payload)
    from agos_core.actions import hire_kit
    from agos_core.engine import hire_kit as hire_kit_rules

    # No road to a new member without its whole kit and model (checked in full,
    # against Hermes's catalog, when it was proposed and approved).
    problems += hire_kit.required_problems(core, workspace_id, payload)
    model: dict[str, Any] = payload["model"] if isinstance(payload.get("model"), dict) else {}
    if not model.get("model") or not model.get("provider"):
        problems.append(hire_kit_rules.NO_MODEL)
    if problems:
        raise ActionError("; ".join(problems))
    name = str(payload["name"])

    kit = payload.get("kit") if isinstance(payload.get("kit"), dict) else None
    if kit is not None and hire_kit_rules.is_empty(kit):
        kit = None
    skills = [str(s) for s in payload.get("skills") or []]
    if kit is not None:
        # Its team context and goal ride with the kit (its SOUL's 'Your team').
        kit = {
            **hire_kit.fill(core, workspace_id, kit),
            "goal_id": payload.get("goal_id"),
            "telegram_topic": bool(payload.get("telegram_topic")),
        }
        skills += [s for s in hire_kit.library_skills(core, workspace_id, kit) if s not in skills]
        hire_kit.expect(workspace_id, name, kit)
    reads = [r for r in payload.get("reads") or [] if isinstance(r, dict) and r.get("path")]
    definition: dict[str, Any] = {
        "instructions": str(payload["role"]),
        # Into its Hermes profile like any member's model (team.write: model.*,
        # agent.reasoning_effort).
        "model": {k: model[k] for k in ("provider", "mode", "model", "effort") if k in model},
        "skills": skills,
        "reads": reads,
        "reports_to": str(payload.get("reports_to") or ""),
    }
    from agos_core.actions import agent_revisions

    try:
        with agent_revisions.by("owner", reason):
            item_id = library_actions.save_item(
                core,
                None,
                kind="agent",
                name=name,
                title=str(payload["title"]),
                summary=str(payload.get("summary") or ""),
                definition=definition,
                workspace_id=workspace_id,
            )
    except BaseException:
        hire_kit.forget_pending(workspace_id, name)
        raise
    out: dict[str, Any] = {"member_id": item_id, "name": name}
    from agos_core.actions import hire_review

    # The Co-Founder looks again in a week (never stops the hire: None = not made);
    # the owner's own New agent has no gap to check against.
    review = hire_review.schedule(core, workspace_id, payload) if review_after else None
    if review:
        out["review_job"] = review
    if payload.get("telegram_topic"):
        from agos_core.actions import hermes_channel

        try:
            dm = workers.open_dm(core, workspace_id, name)
            hermes_channel.topic_for(core, workspace_id, dm)
            out["topic"] = True
        except ActionError as error:
            out["topic_error"] = error.message
        except Exception as error:  # the hire stands without its topic
            log.exception("topic for %s in %s", name, workspace_id)
            out["topic_error"] = str(error)[:200]
    if kit is not None:
        # Step 62: its kit given (files, SOUL's 'Your team', memory), then its
        # Readiness moves on. Never stops the hire: the checklist shows what is missing.
        try:
            shown = hire_kit.provision(core, workspace_id, name, kit)
            out["readiness"] = shown["state"] if shown else None
        except Exception:
            log.exception("kit of %s in %s not provisioned", name, workspace_id)
            hire_kit.forget_pending(workspace_id, name)
    return out


def own_hire(
    core: Core,
    workspace_id: str,
    *,
    name: str,
    title: str,
    summary: str,
    definition: dict[str, Any],
) -> int:
    """The owner's own New agent (Hierarchy → Create agent): his click is his
    Approve, so no card, but the same rules as every hire: its whole kit (tools,
    skills, docs, onboarding) and its whole model (an exact version from Hermes's
    catalog and an effort; its why is his choice). Made through hire(), like an
    approved hire. Returns the member's id."""
    from agos_core.actions import agent_profiles, hire_kit, hire_model

    payload = rules.clean(
        "hire",
        {
            "name": name,
            "title": title,
            "role": str(definition.get("instructions") or ""),
            "summary": summary,
            "skills": definition.get("skills") or [],
            "model": definition.get("model"),
            "model_why": hire_model.OWNERS_CHOICE,
            "reports_to": str(definition.get("reports_to") or ""),
            "kit": definition.get("kit") if isinstance(definition.get("kit"), dict) else {},
        },
    )
    payload["reads"] = [r for r in definition.get("reads") or [] if isinstance(r, dict)]
    problems = rules.problems("hire", payload)
    if payload["name"] in agent_profiles.team_names(core, workspace_id):
        problems.append(f"@{payload['name']} is already on the team: edit that one instead")
    problems += hire_lead_problems(core, workspace_id, payload)
    problems += hire_skill_problems(core, workspace_id, payload)
    payload["kit"] = hire_kit.fill(core, workspace_id, payload["kit"])
    problems += hire_kit.kit_problems(core, workspace_id, payload["kit"])
    problems += hire_kit.required_problems(core, workspace_id, payload)
    problems += hire_model.check(core, workspace_id, payload, hire=True)
    if problems:
        raise ActionError("Not created yet: " + "; ".join(problems) + ".")
    made = hire(core, workspace_id, payload, reason="created by the owner", review_after=False)
    return int(made["member_id"])


def unhire(core: Core, workspace_id: str, result: dict[str, Any]) -> None:
    """Undo of a hire: the member goes (its profile, its DM stays as history), and its
    post-hire review with it."""
    from agos_core.actions import hire_review
    from agos_core.actions import library as library_actions

    hire_review.cancel(core, workspace_id, str(result.get("review_job") or ""))
    library_actions.delete_item(core, int(result["member_id"]), workspace_id)


def consent(core: Core, workspace_id: str, member: str, card: str, payload: dict[str, Any]) -> None:
    """The owner's consent for ONE write of the agent's own instruction file: a
    token in the agent's profile home, read by the guard (agos_guard/consent.py)."""
    from agos_core.actions import agent_profiles
    from agos_core.actions.kanban_asks import _write

    if core.engine is None:
        raise ActionError("Hermes isn't available.", 503)
    home = core.engine.profile_home(
        agent_profiles.key(workspace_id, member) if member else workspace_id
    )
    target = home / CONSENT_FILE
    try:
        data = json.loads(target.read_text())
    except (OSError, ValueError):
        data = {}
    tokens = [t for t in (data.get("tokens") or []) if isinstance(t, dict)]
    tokens = [t for t in tokens if t.get("card") != card]  # one token per card
    tokens.append(
        {
            "card": card,
            "target": str(payload.get("target") or ""),
            "sha256": str(payload.get("sha256") or ""),
            "approved_at": now(),
            "consumed": False,
        }
    )
    _write(target, {"tokens": tokens[-KEEP_TOKENS:]})
