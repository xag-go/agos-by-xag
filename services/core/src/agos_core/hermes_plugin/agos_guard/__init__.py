"""AGOS guard: the owner's Autonomy rules, enforced inside Hermes before every
tool call (not in the prompt).

This plugin's own file in the profile home, `agos-guard.json`, is the one copy of
the rules (AGOS shows them and writes the owner's changes into it, whole-file):

  {"rules": {"<agent id, "" = Co-Founder, or *>": {"<action>": "do" | "ask" | "never"}}}

Which agent answers in a conversation comes from AGOS when the answer starts
(turn-start's "agent"). Each tool call is mapped to an action type; "never" blocks
it, "ask" sends it to the owner's Allow / Deny (Hermes's approval gate), "do" lets
it run. A "Never" for everyone on a whole toolset is also Hermes's own setting
(`agent.disabled_toolsets`: the tool isn't there at all); this guard covers the
rest Hermes has no setting for: one member's rules, "Ask me", and actions that
share a toolset with reading (files, apps).
Command approvals themselves are Hermes's (`approvals.mode`, per-conversation
YOLO); the guard only makes sure Full access never answers the owner's own rules
(`owner_asks`).
Unknown or unreadable policy = no extra rule (Hermes's own checks still apply).
"""

from __future__ import annotations

import json
import logging
from typing import Any

from . import board_waits, owner_approval, policy, runtime, tool_checks
from .board_waits import ALLOWED_FILE as ALLOWED_FILE
from .board_waits import AUTOMATION_READS as AUTOMATION_READS
from .board_waits import OWNER_OK as OWNER_OK
from .board_waits import REFUSED as REFUSED
from .board_waits import TEAMMATE_WAIT as TEAMMATE_WAIT
from .board_waits import _allowed as _allowed
from .board_waits import _answers as _answers
from .board_waits import _refused as _refused
from .board_waits import answered_block as answered_block
from .board_waits import automation_card as automation_card
from .board_waits import blocked_for_owner as blocked_for_owner
from .board_waits import card_ask as card_ask
from .board_waits import pipeline_event as pipeline_event
from .guard_contract import ACTIONS as ACTIONS
from .guard_contract import ASK_MARK as ASK_MARK
from .guard_contract import POLICY_FILE as POLICY_FILE
from .owner_approval import _ANSWERED as _ANSWERED
from .owner_approval import _ASKING as _ASKING
from .owner_approval import _ASKING_GUARD as _ASKING_GUARD
from .owner_approval import _accepted as _accepted
from .owner_approval import _approval_module as _approval_module
from .owner_approval import _asking as _asking
from .owner_approval import _asks_him_itself as _asks_him_itself
from .owner_approval import _call_of as _call_of
from .owner_approval import _in_cron as _in_cron
from .owner_approval import owner_asks as owner_asks
from .policy import _DELETE_VERBS as _DELETE_VERBS
from .policy import _READ_VERBS as _READ_VERBS
from .policy import READ_TOOLS as READ_TOOLS
from .policy import _cache as _cache
from .policy import _policy as _policy
from .policy import action_of as action_of
from .policy import decide as decide
from .runtime import _CTX as _CTX
from .runtime import _bridge_module as _bridge_module
from .runtime import _contract as _contract
from .runtime import _guard as _guard
from .runtime import _missing as _missing
from .runtime import _own_profile as _own_profile
from .runtime import _report as _report
from .runtime import _sibling as _sibling
from .tool_checks import _FOUNDER_WORD as _FOUNDER_WORD
from .tool_checks import _READS as _READS
from .tool_checks import CONSENT_TOOLS as CONSENT_TOOLS
from .tool_checks import FOUNDER as FOUNDER
from .tool_checks import FOUNDER_REFUSED as FOUNDER_REFUSED
from .tool_checks import founder_refused as founder_refused
from .tool_checks import fresh_read as fresh_read
from .tool_checks import other_workspace as other_workspace
from .tool_checks import own_instructions as own_instructions
from .tool_checks import shared_skill as shared_skill

# The Co-Founder's own AGOS tools: never a team member's (its own profile says
# "member" in the policy).
COFOUNDER_TOOLS = {
    "agos_action",
    "agos_capability",
    # Kanban: the Co-Founder makes the cards and links them; a member works its own.
    "kanban_create",
    "kanban_link",
    "kanban_unblock",
}


def _verdict(
    tool_name: str, args: dict[str, Any], session: str, *, acting: bool = True
) -> tuple[dict[str, Any] | None, bool]:
    """The guard's answer for one tool call, and whether it is an owner's rule that
    asks him first (then `owner_asks` takes it). `acting=False` (the middleware's
    look ahead): nothing is done that the hook does itself (a card's question to
    the owner), only the rule is read."""
    if tool_name == "kanban_block":
        answered = board_waits.answered_block(runtime._current_card(), args)
        if answered is not None:
            return answered, False
    consent_verdict = tool_checks.own_instructions(tool_name, args)
    if consent_verdict is not None:
        return consent_verdict, False
    if tool_name == "kanban_create" and acting:
        # A -> B -> A on the same subtree (delegation.py, Paperclip's rule).
        looped = runtime._sibling("delegation").guard(
            args,
            me=runtime._own_profile(),
            current=runtime._current_card(),
            report=runtime._report,
        )
        if looped:
            return {"action": "block", "message": looped}, False
    if tool_name.startswith("kanban_") and acting and runtime._current_card():
        # Review stages / plan first on the card this worker runs (review.py, step 52).
        held = runtime._sibling("review").guard(
            tool_name,
            args,
            member=str(policy._policy().get("member") or ""),
            post=lambda *a, **k: runtime._bridge_module().post(*a, **k),
        )
        if held:
            return {"action": "block", "message": held}, False
    if policy._policy().get("member") and tool_checks.founder_refused(tool_name, args):
        return {"action": "block", "message": tool_checks.FOUNDER_REFUSED}, False
    if policy._policy().get("member") and tool_name in COFOUNDER_TOOLS:
        return {
            "action": "block",
            "message": "That is the Co-Founder's tool. Say what is needed: the Co-Founder "
            "takes it.",
        }, False
    if tool_name.startswith("agos_"):
        # AGOS's own tools: Hermes asks the owner first when AGOS says so.
        owner: dict[str, str] | None = runtime._bridge_module().owner_decides(
            tool_name, args, session
        )
        if owner is not None:
            return owner, True
    if tool_name == "session_search":
        refused = tool_checks.other_workspace(args)
        if refused:
            return {"action": "block", "message": refused}, False
    name = str(args.get("name") or "")
    if tool_name == "skill_manage" and name.startswith("agos-brain-"):
        return {
            "action": "block",
            "message": "That is a method of the AGOS Brain: only the owner changes it, "
            "in AGOS. Propose a change with your agos_action tool (add_method) instead.",
        }, False
    if tool_name == "skill_manage" and tool_checks.shared_skill(name, args):
        return {
            "action": "block",
            "message": "That skill is this workspace's (its Co-Founder keeps it for the "
            "whole team) or AGOS's own: it isn't changed from here. Ask the Co-Founder to "
            "change it (its agos_action update_skill); or make a skill of your own.",
        }, False
    agent = runtime._bridge_module().agent_of_session(session)
    decision = policy.decide(policy._policy(), agent, tool_name, args)
    if tool_name.startswith("kanban_") and session.startswith("cron_"):
        return (board_waits.automation_card(tool_name, decision, args) if acting else None), False
    card = runtime._current_card()
    if decision and decision.get("action") == "approve" and card:
        # Working a card alone (a member, or the Co-Founder): nobody to click Allow.
        return (
            board_waits.card_ask(policy._policy(), card, tool_name, args) if acting else None
        ), False
    return decision, True


def _member() -> str:
    """This profile's team member ("" = the Co-Founder), read from its policy file."""
    return str(policy._policy().get("member") or "")


def _post(*args: Any, **kwargs: Any) -> Any:
    """The AGOS bridge's post, late-bound: the bridge is read when a tool runs, not at
    registration (a stub bridge without post must not fail register)."""
    return runtime._bridge_module().post(*args, **kwargs)


def register(ctx: Any) -> None:
    runtime._CTX["ctx"] = ctx
    _quiet_sandbox_cwd()

    def pre_tool_call(
        tool_name: str = "",
        args: dict[str, Any] | None = None,
        task_id: str = "",
        **kwargs: Any,
    ) -> dict[str, Any] | None:
        session = str(kwargs.get("session_id") or task_id or "")
        tool_checks.fresh_read(str(tool_name), str(task_id or ""))
        from . import taint  # read vs act

        tool, parents = str(tool_name), getattr(runtime._bridge_module(), "_parents", {})
        verdict, asks = taint.checked(tool, args or {}, session, parents, runtime._report, _verdict)
        if not asks:
            return verdict
        call = owner_approval._call_of(str(tool_name), kwargs)
        if call and owner_approval._ANSWERED.get() == call:
            return None  # he said yes in the middleware, for this very call
        # Where Hermes runs this hook first (a tool called from execute_code), he
        # is asked here, under Hermes's hook cap; a cut there fails closed.
        return owner_approval.owner_asks(verdict, str(tool_name))

    def tool_execution(
        tool_name: str = "",
        args: dict[str, Any] | None = None,
        next_call: Any = None,
        task_id: str = "",
        **kwargs: Any,
    ) -> Any:
        """Hermes's tool_execution middleware: no timeout (H: hermes_cli/
        middleware.py _run_execution_chain), unlike the pre_tool_call hook. Under
        Full access his yes is asked here, before the call runs; his no returns
        the refusal without running it."""
        payload = args if isinstance(args, dict) else {}
        call = owner_approval._call_of(str(tool_name), kwargs)
        if not call or not owner_approval._asks_him_itself():
            return next_call(payload)
        session = str(kwargs.get("session_id") or task_id or "")
        verdict, asks = _verdict(str(tool_name), payload, session, acting=False)
        if not asks or not verdict or verdict.get("action") != "approve":
            return next_call(payload)
        with owner_approval._asking(session):
            answer = owner_approval.owner_asks(verdict, str(tool_name))
        if answer is not None and answer.get("action") == "block":
            return json.dumps({"error": str(answer.get("message") or "")}, ensure_ascii=False)
        mark = owner_approval._ANSWERED.set(call)
        try:
            return next_call(payload)
        finally:
            owner_approval._ANSWERED.reset(mark)

    def kanban_task_blocked(task_id: str = "", reason: Any = None, **kwargs: Any) -> None:
        try:
            board_waits.blocked_for_owner(str(task_id or ""), reason)
        except Exception as error:  # noqa: BLE001 — an observer never breaks a block
            runtime._report("agos_guard.kanban_task_blocked", error)
        board_waits.pipeline_event(str(task_id or ""))

    def kanban_moved(task_id: str = "", **kwargs: Any) -> None:
        """A card changed on Hermes's board: its pipeline rules (Step 59) look (AGOS
        compares the card's status with the last one it acted on)."""
        del kwargs
        board_waits.pipeline_event(str(task_id or ""))

    def kanban_tick(outcome: str = "", dry_run: bool = False, **kwargs: Any) -> None:
        """Hermes's dispatcher ticked: moves no card hook tells (review, unblock,
        schedule, archive) are found by AGOS's sweep of the board."""
        del kwargs
        if not dry_run and outcome != "skipped_locked":
            board_waits.pipeline_event("", sweep=True)

    ctx.register_hook("pre_tool_call", pre_tool_call)
    # Hermes's own lifecycle hook, fired after the block is written (H:
    # hermes_cli/kanban_db.py block_task -> _fire_task_hook).
    ctx.register_hook("kanban_task_blocked", kanban_task_blocked)
    # Its other card moves (claimed, completed, any status write): AGOS's pipeline
    # rules (H: hermes_cli/kanban_db.py _fire_task_hook / notify_task_updated).
    for hook in ("kanban_task_claimed", "kanban_task_completed", "on_kanban_task_updated"):
        ctx.register_hook(hook, kanban_moved)
    ctx.register_hook("on_kanban_dispatch_tick", kanban_tick)
    # An automation step's "Only if" lines, before its worker's first model call.
    ctx.register_hook("pre_llm_call", runtime._sibling("step_gate").pre_llm_call)

    def subagent_start(
        parent_session_id: str = "", child_session_id: Any = None, **kwargs: Any
    ) -> None:
        """Hermes started a subagent (delegate_task): AGOS's tools called by it act
        from its parent's place (the chat's turn, the card, the automation's run)."""
        del kwargs
        try:
            runtime._bridge_module().subagent_started(
                str(parent_session_id or ""), str(child_session_id or "")
            )
        except Exception as error:  # noqa: BLE001 — an observer never breaks a delegation
            runtime._report("agos_guard.subagent_start", error)

    ctx.register_hook("subagent_start", subagent_start)
    register_middleware = runtime._missing(
        "hermes_cli.plugins.PluginContext.register_middleware",
        getattr(ctx, "register_middleware", None),
    )
    if register_middleware is not None:
        register_middleware("tool_execution", tool_execution)
    ctx.register_cli_command("agos-estimate", "Estimate a Kanban card's effort (for AGOS)", runtime._sibling("estimate").setup, runtime._sibling("estimate").handle)  # fmt: skip
    runtime._bridge_module().register(ctx)
    # The agents' proposals and typed questions to the owner (asks.py): Hermes
    # Kanban cards AGOS writes in the shape its parsers read.
    runtime._sibling("asks").register(
        ctx,
        member_of=_member,
        # Late-bound: the bridge is read when a tool runs, not at registration.
        post=_post,
        guard=runtime._guard,
    )
    # His voice notes, heard by Gemini (stt.provider: gemini).
    register_stt = runtime._missing(
        "hermes_cli.plugins.PluginContext.register_transcription_provider",
        getattr(ctx, "register_transcription_provider", None),
    )
    if register_stt is not None:
        try:
            from . import stt_gemini

            register_stt(stt_gemini.provider())
        except Exception:
            logging.getLogger("agos_guard").warning(
                "Gemini voice notes not registered", exc_info=True
            )
    runtime._sibling("grade").register(ctx)  # `hermes agos-grade`: Skill Studio's grader (step 46)
    runtime._sibling("explain").register(
        ctx
    )  # `hermes agos-explain`: Held-back writes in plain words
    runtime._sibling("watchdog").register(ctx, post=_post, guard=runtime._guard)  # step 48
    runtime._sibling("goals").register(  # agos_goals (step 51): the goal's progress, a change
        ctx,
        member_of=_member,
        post=_post,  # late-bound, like asks
        guard=runtime._guard,
    )
    runtime._sibling("documents").register(  # agos_card_document (step 49): a card's documents
        ctx,
        member_of=_member,
        post=_post,  # late-bound, like asks
        guard=runtime._guard,
    )
    runtime._sibling("review").register(  # agos_review (step 52): review stages, plan first
        ctx,
        member_of=_member,
        me=runtime._own_profile,
        post=_post,  # late-bound, like asks
        guard=runtime._guard,
    )
    runtime._sibling("search").register(
        ctx,
        member_of=_member,
        post=_post,
        guard=runtime._guard,
    )  # agos_search + agos_status_card (step 55)
    runtime._sibling("threads").register(ctx, member_of=_member, post=_post, guard=runtime._guard)  # step 58: card threads, agos_label, agos-bulk  # fmt: skip
    runtime._sibling("services").register(  # agos_service (step 59): a card's dev servers
        ctx,
        card=runtime._current_card,
        profile=runtime._own_profile,
        workspace=lambda: str((runtime._bridge_module().bridge() or {}).get("workspace") or ""),
        post=_post,
        guard=runtime._guard,
    )
    runtime._sibling("skills").register(ctx, member_of=_member, post=_post, guard=runtime._guard, gate=lambda *a: runtime._bridge_module().gate_fields(*a))  # step 63: agos_skill_request + agos_skill_candidate (read vs act: gate.py)  # fmt: skip
    runtime._sibling("taint").register(ctx, post=_post, report=runtime._report, parents=lambda: getattr(runtime._bridge_module(), "_parents", {}))  # read vs act: a session's mark ends with it  # fmt: skip


# Moved to sandbox_cwd.py (the names stay here for their callers).
SandboxCwdNote = runtime._sibling("sandbox_cwd").SandboxCwdNote


_quiet_sandbox_cwd = runtime._sibling("sandbox_cwd").quiet
