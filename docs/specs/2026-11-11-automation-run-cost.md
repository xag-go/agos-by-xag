# Automation runs in detail + monthly cost (lane auto-c)

## What the owner gets

- **Runs, expanded**: each run of an automation opens to its steps, in run order. Per step: who
  worked it (the member, the Co-Founder, or "You" for an approval), its state (done, running,
  waiting, skipped + why, failed, needs you, stopped), when it started and ended, how long it took,
  its tokens (in / out / cache) and its cost. The run shows the totals (the sum of its steps).
- **Monthly cost**: each automation shows what its runs cost this calendar month (UTC) and last
  month, with tokens. A small figure in the Automations list, the full one in its Runs dialog.
- **Co-Founder**: a read operation `automation.cost` ("how much did Inspiration Watcher cost
  this month?") answers with the same numbers. A read: no Undo.

## Where the numbers come from (Hermes, read only, through the Gateway)

- A step = a Hermes Kanban card (key `agos-automation:<id>:<run>:<source>:<step>`). Its attempts
  are Hermes's `task_runs` rows (profile, started_at, ended_at, outcome).
- An attempt's session: Hermes's `owner_admitted` event of that run (payload `session_id`,
  `db`), else the run's `metadata.worker_session_id` (Hermes stamps it on complete/block), else the
  `kanban` session of the attempt's profile that started first inside the attempt's window (never
  one already linked to another attempt).
- A session's tokens and cost: Hermes's `sessions` row in the attempt profile's `state.db`
  (`input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_write_tokens`,
  `estimated_cost_usd` / `actual_cost_usd`, `cost_status`).
- A one-agent automation's run = its Hermes cron run; its session = `cron_<job>_…` in the
  profile that holds the job, started inside the run's window.
- **Cost unknown**: a session Hermes priced `unknown` (or with no amount) has no cost. A step's
  cost is the sum of its priced sessions; when none of them is priced and it used tokens, the cost is
  `null` = "unknown" on screen. `priced=false` says part of the tokens has no price. AGOS never
  computes a price itself.
- **Skipped step** (lane b's contract): a card done whose result starts with `agos-skipped:` is
  `skipped`, the reason is the rest of the text; it never started an agent, so 0 tokens / $0.

## Workspace isolation

Every read is the workspace's own: its board (`<root>/kanban.db`), and the `state.db` of a
profile of ITS root only (`home_in(ws, profile)`, profile names checked `[a-z0-9_-]`). An
`owner_admitted` payload whose `db` is outside the workspace root is ignored. Test: two
workspaces, B's sessions never count in A's run, even when A's board names B's state.db.

## Caching

No AGOS table: Hermes keeps sessions 90 days, more than the two months shown. The monthly
figure is kept in memory per automation while the board and the profiles' `state.db` stamps
are unchanged (engine/read_cache), so the Automations list does not re-read Hermes on each view.

## Done means

- `GET /workspaces/{ws}/automations/{id}/runs/{run}/detail` → steps + totals.
- `GET /workspaces/{ws}/automation-costs` → per automation: this month, last month.
- The run history's groups carry the same detail; the Runs dialog's card runs too.
- Tests: skipped step = skipped + reason + 0 tokens; totals = sum of steps; cost unknown stays
  unknown; another workspace's sessions never appear; monthly sums by UTC month.
