# ADR 0014 — Team plans: the Co-Founder plans, the code runs the chain

Status: accepted (2026-09-26)

## Context

The owner wants the agents to work like a company. The owner gives a request, the
Co-Founder splits it into tasks on the board, each employee (agent) does its part,
and some tasks wait for others. The owner's brief:

- A task can **wait** on others. It stays **locked** until they are done.
- When a task is done, the system **wakes** whatever was waiting on it.
- The result travels as a **file** plus a note. The next one starts by reading it.
- Tasks that don't depend on each other run **at the same time**.
- A **review** can send work back with notes, with a **limit** (2 rounds). After
  that it goes to the owner, so nobody loops.
- **Agents don't coordinate. Code does.** The code watches the board and moves
  the chain, because code is reliable, doesn't make mistakes, and costs nothing.
- **Agents don't talk to each other freely.** Everything goes through the task
  (handoff, review, question, answer), so every decision has a record. A
  question goes to the Co-Founder, who answers it, asks the member who knows, or
  brings it to the owner (in the app, synced to the linked channels).

The owner also rejected "one Hermes profile per agent". The team stays inside the
workspace's profile (ADR 0013).

## Decision

**1. The Co-Founder proposes, the owner approves once.** Whenever the Co-Founder
answers (its DM, groups, or a Session with the workspace's agent), it gets the
member list and a format. For real team work it ends its answer with a fenced
`agos-plan` block: steps with `key`, `title`, `agent` (a member, or "cofounder"),
`kind` (`work` | `review` | `approval`), `waits_on` and `reviews`. AGOS checks
it: members must be on in Connectors, keys must be unique, waits must be real,
no cycles, at most 15 steps, and a review waits on what it reviews. A bad plan
stays visible with the reason. The plan shows as a card under the answer, with
**Approve plan** and **Reject**. Members' turns never create plans.

**2. Approving creates the steps on the board** (table `plans`; on `tasks`:
`plan_id`, `step_key`, `step_kind`, `waits_on`, `reviews_task`, `rounds`). Every
step starts `locked`, then `advance` unlocks the ones that wait on nothing. Steps
use autonomy "decide": the chain moves by itself, and the owner has a say in
**approval** steps.

**3. The chain is code** (`engine/chain.py` rules, `actions/chain.py`). After
any change, `advance` does the following:

- steps whose waits are all complete go to Start (or to Review + "Waiting for
  you" for the owner's approval steps);
- when every step is complete, the plan is closed and the Co-Founder tells the
  owner in its DM.

A locked step can't be started by hand. The owner can only cancel it.

**4. Handoffs.** A finished step's report summary is saved as a `handoff` note
on its task. Its files go in `/workspace/plans/plan-<id>/`. The next step's run
gets the handoffs of what it waited on, also through the owner's approval steps
(the owner's approval note travels too, e.g. "Go with idea 3"). It also gets the reviews
and answers written on its own task since its last run.

**5. Reviews.** A review step reports `review` (pass) or `changes` + reason.
`changes` writes a `review` note on the reviewed task, sends it back to Start
and locks the review again. After `MAX_ROUNDS` (2) sends-back, the reviewed task
goes to Review with "Your decision" instead. The owner approves it as it is
(this closes the review too) or requests changes.

**6. Questions go through the Co-Founder's desk.** A step that reports `clarify`
gets "Asked the Co-Founder", and a `desk_runs` row starts a Co-Founder run with the
project brief. The Co-Founder ends with `agos-route`, one of:

- `answer`: the answer is written on the task, and the step goes back to Start;
- `ask` + member: that member's run answers, and its answer goes to the task;
- `owner`: the task waits in Clarify, and the Co-Founder asks the owner in its DM
  ("❓ Task #12 … needs your decision"). That DM is the one the channels mirror.

The owner can answer in the task chat, or in the Co-Founder's DM (the Co-Founder
passes it on with an `agos-answer` block). Either way the step goes on by itself.

**7. No agent-to-agent tool.** Agents only read their task and write their
report. The one bounded discussion is writer ↔ reviewer, through review notes,
capped at 2 rounds.

**8. Commands waiting for approval on the board** (found live). Workspaces use
`approvals.mode: manual`. A board run that hit a command needing approval used
to wait 5 minutes unseen and then fail. Now the work loop records Hermes's
`waiting_for_approval` status on the run. The task shows "Asks to run a
command" with **Allow once / Deny** (never wider), and the request appears in
Needs you and in channel notifications (`task.approval`).

## Verified

- Unit and flow tests (`tests/test_chain.py`, 10): plan parsing (members, cycles,
  unknown waits, size), readiness, review rounds, routing, and the full chain
  with a fake Hermes. That covers approval steps, parallel steps, handoffs
  through approvals, send-back with notes, round limit → owner, the three
  question routes, reject, turned-off member, and per-workspace isolation. Also
  `test_workers.test_cofounder_plan_is_captured_from_its_answer` and
  `test_work.test_a_command_waiting_for_approval_reaches_the_owner`. In all,
  229 tests pass.
- **Live**, with real Hermes, a throwaway workspace and 3 agents (Ideas, Writer,
  Reviewer):
  1. The Co-Founder turned "make one TikTok script" into 4 steps
     (ideas → owner's pick → script → review). The card was shown and approved
     from the UI.
  2. Ideas wrote 3 concepts to `plans/plan-1/` in 50 s. The chain stopped at the
     owner's pick. The owner approved it on the Board with "Go with idea 3", and the
     Writer started at once with the ideas' handoff and the note.
  3. The Reviewer sent the script back ("the end must ask viewers to comment").
     The Writer fixed it in round 2, the review passed, the plan closed, and the
     Co-Founder's DM said "✅ The team finished the plan".
  4. Question path: the Writer asked for the price. The Co-Founder judged it an
     owner decision and asked in its DM. Answered there with "149 MAD for 50 ml,
     no offer", the Writer finished with that exact price.

## Limits / for the owner to review

- The Co-Founder proposes plans only when it judges the work is team work. Asking
  "make it a plan for the board" makes it certain.
- The first live run hit the approval timeout (item 8) before the fix. The fix
  is covered by a test with a fake Hermes. A live approval wasn't triggered
  again, because the re-run didn't need a risky command.
- Channels: the Co-Founder's messages reach Telegram/Buzz through the existing
  per-chat links once the owner links the Co-Founder's DM. Per-agent bots and
  topics (the owner's Telegram idea) are a separate step.
