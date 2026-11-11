# One permission list: every action declares who may run it

Owner-approved 2026-11-11 (chat with Lkhalifa). Agents' powers stay exactly as today: zero agos actions.

## Problem

A member card tried to change an automation; the guard refused with a vague message; the worker retried 5
times, re-reading everything each time (~7M tokens), then restarted (~2M more). Root causes:

1. The Co-Founder routed a Co-Founder-only job onto a member card (nothing tells it which jobs are its own).
2. The refusal message doesn't say "stop and hand to review", and nothing stops a retry loop.
3. Only ~52 of 140 Co-Founder actions are declared in the ops registry; the rest are hand-written tables, so
   there is no single list of "who may do what" to read or enforce.

## What "done" means

1. **Every Co-Founder action is a declared OperationSpec** (ops/specs/*): the ~88 hand-written kinds in
   engine/cofounder_actions.py ACTIONS + engine/cofounder_parity move into specs; the hand-written KINDS /
   EFFECT / OWNER_ONLY rows for them are derived from the catalog (as the 52 already are). Behaviour-neutral:
   same kinds, same gates, same effects, same required fields, same titles (prove with a before/after dump).
2. **Three answers required on every spec, enforced by a guard test**: who runs it (owner_only XOR
   cofounder_domain — already enforced), may agents run it (agent_tool: None = no, and today ALL are None),
   and does it need the owner's yes (gate). A new action without the three answers fails CI.
3. **The Co-Founder's routing reads the list.** Its prompt/skill (cofounder-actions + the kanban guidance)
   says plainly: a job that maps to any Co-Founder action (automations, team, skills, board admin, workspace
   settings) is done by the Co-Founder itself via agos_action, never put on a member card. Card bodies it
   writes for members must not contain Co-Founder-only work.
4. **A member card that still needs a Co-Founder action degrades gracefully**: the guard's refusal message
   tells the worker exactly what to do (one sentence: "Hand the card to review with a note saying what change
   is needed; the Co-Founder will do it. Do not retry."). After the FIRST refusal of a Co-Founder tool in a
   card run, a repeat call of any Co-Founder tool in the same run is answered with the same message plus
   "already refused — hand to review now" (no loop). Optionally the refusal is also posted as a card comment
   so the Co-Founder sees what was needed.

## Hard rules

- Agents: no new powers. agent_tool stays None everywhere.
- Pixel-neutral: no UI change. openapi.json byte-identical.
- Ratchets only shrink; new modules born compliant; follow agos-engineering-standards.

## Lanes

- Lane A (eng/perm-registry): items 1-2 (migration + guard test).
- Lane B (eng/perm-routing): items 3-4 (routing text + guard refusal/loop-stop). Disjoint files:
  hermes_plugin/agos_guard/_, the cofounder-actions skill text, prompt builders. Lane A owns ops/specs/_,
  engine/cofounder_actions.py, engine/cofounder_parity/*, engine/power.py, engine/cofounder_owner_only.py.
