# Proposal for Hermes: let a plugin's approval say what it does

Read against Hermes `caafe5389a` (0.23.3).

## What happens

A plugin's `pre_tool_call` hook can return `{"action": "approve", "message": ...}`.
`tools/approval.py` `request_tool_approval` then asks the user with
`display_target=f"<{tool_name}> (plugin approval rule)"`. That label is what every
surface shows as the command (the Telegram card's `<pre>` block), so the user reads
`<agos_action> (plugin approval rule)` and has to guess what will change. The
plugin's own words only reach the "Why it was flagged" line.

## What AGOS does today

`agos_guard/approval_card.py` wraps `BasePlatformAdapter.send_exec_approval` and,
for that label only, shows the first line of the plugin's message as the command
and the rest as the reason. It changes no behaviour (buttons, whole-command check,
Deny-only fallback stay Hermes's), but it is a wrapper on an engine method.

## Proposal

Accept an optional `display` key in the hook's approve decision (a short, one-line
description of the action) and use it as `display_target`, falling back to today's
label. The allowlist key (`plugin_rule:<rule_key>`) is unchanged, so nothing about
"session" / "always" grains moves. With it, AGOS drops the wrapper.
