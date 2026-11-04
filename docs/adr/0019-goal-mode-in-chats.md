# ADR 0019: Goal mode in chats; Looking ahead removed

Status: accepted (2026-10-05)

## Decision

The owner removed Looking ahead entirely (Check simple, Check general, the
`/check-simple` and `/check-general` commands, their cards and their place in
Automations). Its tables stay (applied migrations never change) but nothing runs
them; suggestion cards already on the board can still be started or dismissed, and
the learning loop ("What I learned") is unchanged. The old Looking ahead URL opens
Automations.

In its place: Hermes's goal mode, also for ordinary work in chats (not only board
tasks). When a chat answer did real work (it used tools), Hermes's own goal judge
(`judge_goal`, with the workspace's model) checks the owner's request against what
was done (`actions/chat_goal.py`):

- `done` / `blocked` / a failed judge: nothing more (a failing judge never loops).
- `continue`: the same agent goes on by itself in the same chat and Hermes session,
  with what is missing, in a turn that says it is not a message from the owner. The
  judge always checks the owner's original request, not the note.
- At most the workspace's number of rounds (Workspace settings → General, "Check
  that work is finished"; default 10 like Hermes; 0 = off). At the limit the agent
  says so once and asks whether to go on.
- A new message from the owner always comes first: the pending round is dropped and
  the owner's message is answered.
- Plain questions and answers (no tools) are never judged, so they cost nothing.

Board tasks keep their own goal mode (ADR 0016 / `actions/goals.py`).
