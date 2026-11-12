"""Hermes settings AGOS writes as its recommendation, not as a rule.

Each key here used to be re-written on every sync (forced). Re-checked one by one in
Hermes v0.22.2: nothing in AGOS breaks with another value, so it is the owner's
choice. A NEW profile starts on AGOS's value (its writer: engine/rules.py
profile_config, actions/library.py profile_settings, actions/agent_profiles.py
kanban_pairs, actions/access.py CRON_MODE); a profile that already has the key keeps
it (`keep_owner`), and Settings → Hermes settings edits it with Hermes's own
`hermes config set`, showing AGOS's recommended value and why.

Keys AGOS must still force stay in actions/hermes_all_settings.py FORCED_WHY, each
with the Hermes reason it must.
"""

from __future__ import annotations

from typing import Any

# Key → why AGOS recommends its value (shown on the page next to that value).
WHY: dict[str, str] = {
    # The owner's "no limits" rules (Hermes's defaults are lower, nothing in AGOS
    # depends on the numbers).
    "delegation.max_iterations": "AGOS gives subagents no step budget (your rule: nothing is cut for length). The built-in default is 250 (hermes_cli/config_defaults.py delegation.max_iterations).",
    "tool_loop_guardrails.loop_caps.max_web_searches": "AGOS sets no ceiling on web searches per turn (your rule); the loop detector card stops real loops.",
    "tool_loop_guardrails.loop_caps.max_subagents": "AGOS sets no ceiling on subagents per turn (your rule).",
    "agent.api_max_retries": "A provider hiccup (overloaded, timeouts) is waited out, not a failed task.",
    "agent.auto_recovery_cycles": "A provider hiccup is waited out, not a failed task.",
    "compression.max_attempts": "Long chats keep being summarised even after a failed try.",
    "compression.threshold_tokens": "Long chats are summarised at 200K tokens, not at half of a 1M window.",
    "memory.memory_char_limit": "No character cap on the agents' memory (your rule; the built-in default is 2,200).",
    "memory.user_char_limit": "No character cap on what they remember about you (your rule; the built-in default is 1,375).",
    "memory.provider": "Deep memory: a holographic fact store, one per agent (AGOS installs it in each new profile, actions/memory_plugin.py).",
    "curator.consolidate": "The curator also merges overlapping skills it learned.",
    "kanban.auto_decompose": "Rough card ideas are fleshed out and split for the team.",
    # Voice notes (who hears them is General settings → Voice notes, Hermes's
    # managed scope: actions/hermes_voice.py).
    "stt.echo_transcripts": "Your own voice note isn't posted back as text.",
    # How chats look (the owner's rules; Hermes's own behaviour otherwise).
    "display.busy_ack_enabled": 'The engine\'s own notes when you write during a run ("Redirected current run") reach you, as on your own setup.',
    "display.busy_input_mode": "What you write while it works interrupts the run and the run is redirected (the default).",
    "display.busy_ack_detail": "The busy note stays one short line.",
    "display.show_reasoning": "Your rule: no reasoning shown on any channel.",
    "display.tool_progress": 'Your rule: no "what runs in the background" lines (AGOS\'s own chats have their own setting, kept off).',
    "display.memory_notifications": "Your rule: no self-improvement notes in chats.",
    "display.background_process_notifications": "Your rule: no background-process notes in chats.",
    "display.platforms.telegram.tool_progress": "Your rule: no tool progress lines in Telegram.",
    "display.platforms.telegram.cleanup_progress": "Progress lines are removed once the answer is there.",
    "display.platforms.telegram.interim_assistant_messages": "In Telegram only the answer is sent, once (no commentary it then repeats).",
    "display.platforms.telegram.long_running_notifications": 'No "Working" bubble in Telegram.',
    "gateway.message_timestamps.enabled": "Every message an agent reads carries when it was sent, so a long chat knows today's date (AGOS's plugin adds the time on turns the engine doesn't stamp either way).",
    "browser.headed": "The browser opens on the workspace's screen, so the Screen tab shows what it does (headless works too, with nothing to watch).",
    # Telegram (both values work with AGOS's chats and its people card).
    "group_sessions_per_user": "One conversation per Telegram group or topic, like the AGOS chat linked to it (the built-in default splits a group per person).",
    "unauthorized_dm_behavior": 'Someone new writing to the bot gets a pairing code, and you approve him in AGOS ("ignore" stays silent).',
    "platforms.telegram.extra.unauthorized_dm_behavior": "Same as above for Telegram (its own key wins over the global one).",
    # Restarts
    "agent.restart_drain_timeout": "When AGOS restarts a workspace (new folders, new routes), a running answer gets this many seconds to finish and go out first (the engine's default 0 cuts it at once). AGOS's stop waits for the engine's own stop budget from it (gateway/restart.py resolve_systemd_timeout_stop_sec); a value above the gateway unit's TimeoutStopSec counts only once `hermes gateway install` rewrites the unit.",
    # Access
    "approvals.cron_mode": 'An automation\'s run has nobody to ask, so AGOS lets its commands run (your rule). The built-in default "deny" blocks them. "Check with me first" automations wait for your Start on the board either way.',
}


def keep_owner(
    pairs: dict[str, str], config: dict[str, Any], like: dict[str, Any] | None = None
) -> dict[str, str]:
    """`pairs` without the owner's choices this profile already has (config.yaml as
    Hermes wrote it): only a profile that lacks one gets a value. `like`: the config
    a new profile follows (a member its Co-Founder's), so it starts on the owner's
    value there rather than on AGOS's."""
    from agos_core.engine import config_file

    missing = object()
    out: dict[str, str] = {}
    for k, v in pairs.items():
        if k not in WHY:
            out[k] = v
        elif config_file.get(config, k, missing) is missing:
            theirs = config_file.get(like or {}, k, missing)
            out[k] = v if theirs is missing else as_text(theirs)
    return out


def as_text(value: Any) -> str:
    """The `hermes config set` argument Hermes reads back as this value."""
    import json

    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, (list, dict)):
        return json.dumps(value)
    return str(value)
