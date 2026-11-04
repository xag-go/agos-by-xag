# ADR 0018: Follow-ups and watches — the team keeps things going

Status: accepted (2026-10-05)

## Context

The owner wants the agents to work like OpenAI's Dots, not only question → answer:
an agent that agreed to come back at a time must come back by itself, and an agent
the owner hands a job to must keep an eye on it until it is done, telling the owner only what
matters, while the owner keeps talking to it about other things.

## Decision

Two kinds of ongoing work, in every workspace, for the Co-Founder and every agent.
Both are saved by AGOS (never a promise kept only in the model's memory), belong to
one workspace and one chat, and are listed in Automations → "What the team keeps
going for you", where the owner can Stop / Cancel them.

**Follow-ups** (`followups` table, `actions/followups.py`). The agent ends its answer
with an `agos-followup` block (create / update / cancel; `in_minutes` or `due_at`).
At the time, AGOS starts a turn in the same chat and Hermes session, with a note
that says it is a scheduled follow-up (no fake owner message), so the agent picks up
with the whole conversation. It waits while the chat is answering or has unread
owner messages; a failed answer is tried again with a growing pause. The reply goes
to the chat's channel, or to the workspace's notify channel when the chat has none.

**Timezone.** Clock times the owner gives mean the owner's timezone, chosen in Settings →
General (`owner.timezone`). Until it is set, the agent asks once and AGOS keeps the
first answer. A one-off timezone in a chat never changes the setting.

**Watches** (`watches` table, `actions/watches.py`). The agent ends its answer with an
`agos-watch` block (start / update / stop). Each look runs in the background on the
watch's own Hermes session (`agos-job-<ws>-<id>-check`), so it remembers earlier
looks and the chat stays free. It ends with an `agos-watch-report` block: `tell`
(empty = nothing new = silence), `notes` (shown to every chat answer of the
project, so "fin wslat?" works), `next_check_in_minutes` (its own pace, at least 5),
`done`. It never gives up by itself; it ends when the agent reports the job done or
the owner stops it. The session acts as its agent for the owner's Autonomy rules;
nobody can answer a command during a look, so a risky command is allowed once only
on Full access and the owner's "Ask me" rules are refused (the agent tells the owner instead).

Agents may offer a watch or a follow-up ("Bghiti ntab3 lik hadi?") but start one only
after the owner says yes. Looking ahead asks the same question in its report instead of
making a task.

## Where the owner sees it

Everything that runs by itself is on ONE page, the workspace's Automations tab:
Automations, Looking ahead (Check simple / Check general, moved from Workspace
settings; the old URL redirects), Watches and Follow-ups, with links at the top.

## Pitfalls found live

- `agos-watch-` is Looking ahead's read-only session prefix: watches use `agos-job-`.
- Hermes caches a "not found" for 60 s and its exists() check runs on the host, so it
  can't see a file created in the sandbox; it also blocks a 4th identical read as
  "not changed" even when the file changed. The agos-guard plugin resets Hermes's read
  tracker before every `read_file` / `search_files`, so a look always reads the real
  file (a chat once told the owner a file had been deleted when it had not).
- The chat is told to look again itself before answering about a watched job, not to
  trust the notes alone.

## Limits (said plainly)

- A watch costs tokens at each look; the agent chooses the pace.
- Times show in the owner's timezone on the page; the confirmation line in the chat
  uses it too once it is set (UTC before).
