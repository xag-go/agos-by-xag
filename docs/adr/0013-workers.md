# ADR 0013 — Workers: the workspace's team (Slack-like)

Status: accepted (2026-09-26)

## Context

The owner wants a Slack/Teams-like team per workspace: talk to each agent on its
own, make groups, and in a group either name someone with @ or, when the owner doesn't
know who is in charge, write to the group and let the project's lead pass it on.
The classic Chats stay as they are.

## Decision

- A new workspace tab **Workers** (after Dashboard, Board, Chats) with two parts:
  - **Hierarchy**: an org chart. The **Co-Founder** (the workspace's own agent,
    its SOUL) is on top, and the **members** are under it: the library agents turned on
    in the workspace's Connectors (owner's choice). Each has a card (name, @handle,
    role, what it does, Message).
  - **Messages**: Slack-style sidebar with **Groups (#)** and **Direct messages**
    (one per member, plus the Co-Founder), and the conversation on the right.
- Storage: DMs and groups are `chats` rows with `kind` = `dm` | `group` (classic =
  `chat`), so messages, attachments, voice notes, approvals, Ask/Full access, stop,
  retry, hide-on-delete and the per-chat Hermes session all work unchanged. A DM
  keeps its agent in `agent` (one per agent per workspace, unique index; a hidden
  DM comes back with its history). A group keeps its `members`.
- Who answers a group turn: the member **@mentioned** in the latest message that
  mentions one (only real members that are on). Without a mention, the
  **Co-Founder** answers, or ends its answer with one fenced `agos-handoff` block
  `{"to": member, "note": …}`. AGOS strips the block, shows the Co-Founder's one-line
  "who takes it", and starts the member's turn with the owner's own words plus the
  note, in the same session. A malformed or unknown handoff stays visible text.
  One level only: a member never hands off again (no loops).
- Every agent message records its `speaker`, and the UI shows the name above each
  answer. The group composer autocompletes `@` with the members.
- A member turned off in Connectors drops out: mentions of it go to the
  Co-Founder, and it can't be added to a group.
- Groups and DMs don't appear in Chats or its search. Classic chats are unchanged.

## Verified

- `tests/test_workers.py` (10): mentions, handoff parsing, one DM per member,
  DM talks as the agent, @mention → member only, no mention → Co-Founder →
  handoff → member (same session, owner's words), members must be on, turned-off
  member drops out, per-workspace isolation.
- Live (browser, real Hermes, throwaway workspace, 2 agents): Hierarchy cards;
  group created from the dialog; "We need a logo…" with no @ → Co-Founder:
  "This is a logo job, so @designer takes it." → Designer answered with 3
  ideas; `@ad` autocomplete → "@ads-… " → the Ads expert answered directly; DM with the
  Designer answered as the Designer; Chats tab still shows only "General".

## For the owner to review

- The Co-Founder hands off to one member per message. "Ask two members at
  once" would be a next step.

## Update — Sessions and Workers side by side

The owner asked for four workspace tabs: **Dashboard · Board · Sessions ·
Workers**. "Sessions" is the classic chat (same data, same features), now at
`/w/<id>/sessions`; old `/chats` links redirect there. Workers keeps its two parts
(Hierarchy, Messages). Deleting a DM or group goes back to Workers' Messages. Needs-you
links point to the right place by kind.

## Update — one memory per agent (owner's request)

An agent must not forget in a group what it discussed in its DM, and the reverse.
Each conversation still has its own Hermes session, but every Workers turn now also
gets **what this agent said in the workspace's other DMs and groups** (its latest
15 answers with what the owner asked, newest kept within ~9k characters, hidden
conversations included). The Co-Founder gets its own. Other agents don't get
someone else's DM. In a group, everyone sees what was said there, as in Slack.
The workspace memory (Hermes MEMORY.md) stays shared by all.

Verified live (real Hermes): DM "code name KIWI-…" → in the group the Designer
answered "KIWI-…"; a group decision "deep green" → back in the DM: "Deep green for
the label background". Tests: `test_an_agent_remembers_its_dm_in_groups_and_back`
(including another agent not getting the DM, and hiding the DM not erasing memory).

## Update — the lead is called "Co-Founder" (step 44; "Manager" before)

The workspace's own agent (the agent of its Hermes profile `agos-<id>`, created with
the workspace) is named **Co-Founder** in every workspace (owner decision 2026-10-26;
it was the "Manager" from step 12 to step 43). The Hierarchy box shows "Co-Founder"
with the workspace's name under it (no "leads the team" line). Its DM is titled
"Co-Founder" (existing ones renamed by migration 126, as migration 16 had titled them
"Manager"). The rename reaches the code too: `cofounder_actions` (table, modules,
`/cofounder-actions` routes, `cofounder.actions` setting), the room handle
`@cofounder`, the Office look key `cofounder`, the log area `cofounder`. Rows and
cards written before step 44 still spell `manager` in a few places (an automation
step's agent, a hire's `reports_to`, a room member made before the rename): the
readers take both spellings. The roots' SOUL.md files are rewritten once at start
(`actions/cofounder_move.py`).

## Update — the Co-Founder knows the whole project

Before each Co-Founder turn (its DM, groups it answers, and Sessions with the
workspace's own agent), AGOS builds from its own data:

- a **brief** in the instructions: every board task (status, assignee, last
  message), automations, and every conversation (Sessions, DMs, groups, including
  ones the owner deleted from the list) with its latest lines, newest first, within
  ~14k characters;
- the **full log** as Markdown in the workspace folder,
  `/workspace/.agos/project-log/` (index.md, one file per conversation and task,
  latest 400 messages each), rewritten by AGOS each time, for details.

Members don't get the brief; they keep their own recall (their DM + groups).

Superseded (2026-10, ADR 0011): no recall or brief is added to a turn any more; each
agent is its own Hermes and finds other conversations with Hermes's session_search.

Known limit: the log is in the workspace folder, so a member working in the same
sandbox could open it if told to. Everything stays inside the workspace (no
cross-workspace access).

Verified live (real Hermes): Designer DM "logo is saffron yellow", Launch group
"@ads budget 700 dirhams", a board task; the Co-Founder, asked in its DM, answered all
three with where each was said. Tests: `test_cofounder_knows_every_dm_group_session_and_task`,
`test_cofounder_in_group_and_sessions_gets_the_brief`, `test_brief_budget_keeps_newest_conversations`.

## Update — five tabs

Owner's layout: **Dashboard · Board · Sessions · Hierarchy · Messages**. Hierarchy
(`/w/<id>/hierarchy`) and Messages (`/w/<id>/messages`) are their own tabs; the
Workers tab with its sub-tabs is gone, and old `/workers` links redirect.

## Update — the owner orders the tabs

In **Settings → General** (with Appearance): the list of workspace tabs with ↑/↓
buttons, Save, and Reset to default. No drag and drop in the tab bar (owner's
choice). The order is saved in the core (`app_settings.tabs`,
`GET/PUT /preferences/tabs`), the same in every workspace, and survives reloads
and backups. Unknown tabs are dropped and a tab added in a later version appears at
the end.

## Update (2026-09-26): several members per message, tasks from conversations

- **Several members answer one message.** The owner can @mention several members
  ("@ads and @designer, …"). They answer one after the other, in the order named,
  in the same conversation, so each one sees what the ones before it said. Without
  a mention, the Co-Founder's `agos-handoff` block may name several members, each with
  its own note, and only those it concerns (at most 6). A member is told who
  answers after it, so it doesn't do their part. The rest of the queue is kept on
  the turn (`chat_turns.queue`), and stopping a turn stops the queue.
- **Tasks from important messages.** In DMs and groups, the task block an agent
  adds goes on the board by itself, in To do (the owner starts it), assigned to
  the member named or to the agent who wrote it. The agents are told to be
  strict. They add a task only for real work the owner gave or confirmed, never
  for a question, an idea still being weighed, small talk, or work already on the
  board (they see their open tasks, and the Co-Founder sees the whole board). There
  are at most 3 per answer, and the same open title is never added twice. A team
  plan (ADR 0014) takes precedence. Sessions keep the "Add to board" button.
- Verified live: the Co-Founder passed a group message to only Designer + Ads (the
  Writer stayed silent). "@writer and @designer" got two answers in turn, the
  second building on the first. Questions made no task, while "make the final
  poster by Wednesday" in the Designer's DM made one task in To do for the
  Designer.
- **The owner can ask for a task directly** ("make this a task", "add it to the
  board", in any language): it's always added, as one task, without asking again.
  Checked with messages in English and in Moroccan Arabic written in Latin
  letters: an opinion question made no task, a "make this a task" in the
  Co-Founder's DM made one, and the same request to @designer in a group made one.
