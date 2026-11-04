# 0022 — The usage pause is Hermes's own pause

Date: 2026-10-22 · Status: accepted

## Decision

"Pause at" (General settings → Usage) runs on Hermes's own emergency stop:
when any logged-in account reaches the owner's level, AGOS runs
`hermes pause --reason "Account pause in AGOS: <why>"` in every active
workspace root, and `hermes resume` when usage is back under it
(`actions/account_pause.py`). The owner chose this over the old
AGOS-built hold, so that Hermes is the whole engine (2026-10-22).

Hermes does the holding itself (`agent/estop.py`): the ESTOP sentinel at the
root stops its cron scheduler, its Kanban dispatcher **and new gateway turns —
chats wait too**, which the old hold didn't do. Running work is never killed.
The Usage card says so.

## Rules

- AGOS reads the sentinel's body (`{"reason", "engaged_at"}`) and resumes only
  a pause whose reason starts with `Account pause in AGOS`. A pause the owner
  made by hand (`hermes pause`, `touch ESTOP`, any other reason, a corrupt
  body) is never lifted or overwritten by AGOS.
- Nothing else is flipped: `kanban.dispatch_profiles` always holds the true
  list, and cron jobs keep their own enabled/paused state.
- The pre-Step-33 hold (an emptied dispatch list, jobs paused with
  `Account pause in AGOS`) is put back once at start
  (`account_pause.move_old_pause`), so nothing stays held by the removed way.

## Consequences

- `hermes pause` holds the whole root: the Co-Founder and every member, their
  chats included, until resume. At the owner's 100% Hermes additionally holds
  work by itself (cron `quota_hold`, the Kanban's rate-limit cooldown).
- The sentinel is a Hermes file (ownership `HERMES_FILES["ESTOP"]`, contract
  `agent.estop`): AGOS only reads it; the writes are Hermes's two commands.
