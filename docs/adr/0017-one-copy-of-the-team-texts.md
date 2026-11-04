# ADR 0017 — One copy of the team's texts (playbooks shows what the team uses)

> Partly superseded: skills are no longer copied (into profiles or `playbooks/skills`);
> see ADR 0020, "Update: skills are Hermes's, one shared folder".

Date: 2026-10-02 · Status: accepted (owner, for every workspace)

## Problem

Each skill and agent of a workspace lived in two editable places:

- in AGOS (library → the profile's `skills/agos-library/`), which is what the
  agents really run with, changed by cards (`update_skill`…);
- as a "master" the agents kept by hand in `/workspace/playbooks/{skills,agents,
automations}` (since tasks #116 / #57), synced to AGOS by sending a card.

plus a third read-only copy in `.agos/team`. Two editable copies drift: a master
changed without its card left the team working from the old text, and the agents
built tools (`build_apply_payload.py --verify-live`) only to compare them. The
skills in AGOS also lacked the masters' references and scripts (14 files in
one workspace), so a skill only worked because the agent read playbooks.

The owner wants everything local, in one place they can see.

## Decision

`/workspace/playbooks` is the one place, and AGOS keeps it exact:

1. `playbooks/skills/<id>/` (SKILL.md + references/scripts), `playbooks/agents/<id>.md`
   and `playbooks/automations/<name>.md` are **written by AGOS** after every change
   (`actions/team_files.py`). A skill is shown as the workspace's agents have it,
   including what they learned on the job.
2. **Read-only in the sandbox**: the three folders are mounted `:ro` over the
   writable `/workspace` (`engine/rules.build_mounts`; the sandbox check refuses
   them writable). Agents change them only with a card, so every change has Undo,
   the owner's Autonomy rules (agos-guard) and history. `update_doc` refuses them.
3. Skills carry their other files: `definition.files` (path → text), set by cards
   (`files`, `""` deletes one; omitted files are kept) and written into the
   library folder, so Hermes gets the whole skill.
4. An edit made to those files **from outside the sandbox** (the owner, a synced
   folder) is taken into AGOS on the next check (same save as the app's, so the
   old version is kept), then shown back. What AGOS last wrote is recorded in
   AGOS's database (`app_settings`), out of the agents' reach.
5. **One-time move** at core start (`adopt`): the old masters are moved to
   `archive/playbooks-before-<date>/` (nothing deleted), reference/script files that
   existed only there are added to their skill (when its SKILL.md is the one the
   team uses), and `.agos/team` is removed.

The Documentation (`team.md`, `flow.md`, `CHANGES.md`…) is unchanged: it never had
a second copy.

## Consequences

- Nothing to keep in sync by hand; what the owner reads in playbooks is what runs.
- A workspace not yet moved is never overwritten (write waits for `adopt`).
- Backups of the moment of the move: `~/agos-data/system/before-one-copy-*`.
