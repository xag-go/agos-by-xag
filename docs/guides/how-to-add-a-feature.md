# How to add a feature

This is the step-by-step for any change that adds or changes behaviour. Follow
it in order. Each step says what to do and which test holds you to it.

The target design is the **service layer**
([ARCHITECTURE.md §10](../../ARCHITECTURE.md#10-target-design-the-service-layer)).
It is being migrated. A new feature moves the code toward it and never away
from it.

## 0. Write a one-page spec first

Before code, write down in plain words:

- **What** the owner can do, and on which screen.
- **Who else** can do it: the Co-Founder (always, see step 5), agents, Telegram,
  an automation.
- **Where the data lives.** Hermes first. AGOS stores only what Hermes has no
  place for (step 2).
- **Edge cases**: Hermes down, a double click, a half-done step, an empty
  workspace, a workspace in the trash.
- **Done when**: the checks a reviewer can run.

Put it in the pull request description, or in an ADR when it is a design
decision ([docs/adr](../adr/README.md)).

## 1. Find the service

Pick the action set the feature belongs to: Workspace, Board, Team, Hire,
Automation, Library, Connector, Docs, Chat, Channel, Cofounder, Inbox, Settings
or System. The full map of today's modules to services is in the architecture
§10.

- If the service package exists, add the operation there.
- If not yet, add **one new module** for the feature's rules (for example a new
  `board_due_dates.py` in `actions/`). Do not grow a router, `cofounder_more.py`, or
  any file over 800 lines.

## 2. Decide where the data lives

1. Does Hermes have a place for it (its config, a profile, its Kanban, cron,
   sessions, rooms, memory)? Then store it **in Hermes**, through Hermes's CLI
   or the engine's public methods. Read it back from Hermes. Keep no copy.
2. Only if Hermes has no place: add a table, column or setting in AGOS.
   - Add a **migration** at the end of `services/core/src/agos_core/db/migrations.py`.
     Never edit a shipped one. Make it safe to run twice (`IF NOT EXISTS`, the
     `-- agos: ensure-column` directive). Append its hash to
     `tests/test_migrations_frozen.py`.
   - Register every new table, column and `app_settings` key in
     `services/core/src/agos_core/db/ownership/` as `AGOS_ONLY` with a
     one-line reason. If you can't write the reason, the data belongs in Hermes.
   - Tests that hold you: `tests/test_ownership.py`, `tests/test_migrations_frozen.py`,
     `tests/test_old_copies.py`.
3. Writing a Hermes file directly (not through its CLI) is allowed only for the
   modules listed in `tests/test_hermes_writes_guard.py`, with a reason.

Details: [hermes-ownership.md](../hermes-ownership.md).

## 3. Write the operation

Shape the code as an operation, even before the registry exists:

| Part         | What to write                                                                                                      |
| ------------ | ------------------------------------------------------------------------------------------------------------------ |
| **validate** | a Pydantic input model. No hand-written `dict` coercion.                                                           |
| **do**       | the change. SQL inside `transaction()`. Hermes through `core.engine` public methods only (never `_hermes`).        |
| **undo**     | how to take it back. Reuse the service's restore or revision code when there is one.                               |
| **audit**    | a short title for the activity log and the Co-Founder's card.                                                      |
| **gate**     | `undo` (done at once, with Undo), `owner` (waits for the owner's yes: deletes, imports, people) or `once` (a run). |

Rules for the `do` step:

- **All or nothing.** When a step touches the database and Hermes, do the
  Hermes step so it can be undone, and undo it when a later step fails. Never
  delete the AGOS row before Hermes confirmed (an orphan job would keep running).
- **Idempotent.** A retry or a double click must not do the work twice. Check
  "already done" or accept an idempotency key.
- **Notifications after commit.** Telegram, push and Co-Founder messages go out
  only when the change is committed (`channel_outbox` today, the Outbox in the
  target).
- **Errors.** Raise `ActionError` with a plain message the owner can act on.
  Don't pick HTTP statuses in new rule code when you can avoid it.
- **Config.** Read settings from `core.settings`, never `os.environ`.
- **Logging.** Use `logging.getLogger("agos.<module>")`. Warnings and errors on
  `agos.*` reach the System Log.

## 4. Add the API route and the web screen

1. Add a route in the screen's router in `services/core/src/agos_core/api/`.
   The router only maps HTTP to your operation: no SQL, no Hermes calls, no
   business rules.
2. Regenerate the contract and the web's types:
   ```bash
   cd services/core && uv run python scripts/export_openapi.py
   pnpm --filter @agos/web gen:api
   ```
   `tests/test_contract.py` fails while `openapi.json` is stale.
3. Build the screen in `apps/web/src/features/<feature>/`. Server actions go
   in a `*-actions.ts` file and call the core. The web never reads data or
   files itself. Give it loading, empty and error states.
4. Keep the look: use the shared UI pieces and tokens. Check light and dark
   themes, and a phone width.

## 5. Co-Founder parity

The Co-Founder can do anything the owner can do. For every new web server
action:

1. Add a Co-Founder kind for it in `services/core/src/agos_core/engine/cofounder_parity/<domain>.py`
   (domain, required fields, title, gate), and its `do`/`undo` in the
   Co-Founder actions.
2. Map the web action: to the kind in `DO` or to a read in `READS` (same
   file), or to an owner-only exception **with its reason** in `OWNER_ONLY`
   (`engine/cofounder_owner_only.py`; for example, a step that needs the
   owner's own sign-in on an outside site).
3. `tests/test_cofounder_parity.py` fails on any web action these tables don't
   know.

The Co-Founder's card shows what changed, with **Undo** or **Approve**, using
the gate from step 3.

## 6. Tests

Write the test first when you fix a bug: it must fail before the fix and pass
after.

| Add                                    | Where                                                             |
| -------------------------------------- | ----------------------------------------------------------------- |
| the rules (pure functions)             | `services/core/tests/test_<feature>.py`                           |
| the operation, with a fake engine      | same file; swap the engine `Runner` like the existing tests       |
| the API route                          | through the FastAPI test client                                   |
| the Co-Founder kind (do and undo)      | `tests/test_cofounder_*.py`                                       |
| Hermes behaviour that fakes can't show | a `*_live.py` test or an e2e check (see [testing.md](testing.md)) |
| web logic                              | `apps/web/scripts/*.test.mjs` (`node --test`)                     |

A new test that needs a real Hermes must skip itself when Hermes is missing, or
be added to the `--ignore` list in `.github/workflows/ci.yml`.

## 7. Docs and changelog

- Add a line under **Unreleased** in [CHANGELOG.md](../../CHANGELOG.md), in
  the owner's words (what they can do now).
- Update the [user guide](../user-guide.md) when a screen changed, and
  [ARCHITECTURE.md](../../ARCHITECTURE.md) when a rule or a piece changed.
- Run `python3 scripts/check-docs.py`.

## 8. Definition of Done

A change is done when every box is ticked:

- [ ] The spec (step 0) is in the pull request, and the change does what it says.
- [ ] Data lives in Hermes where Hermes has a place; anything new in AGOS is in
      `ownership.py` with a reason.
- [ ] The operation validates its input, is all-or-nothing and is safe to retry.
- [ ] The Co-Founder can do it (or `OWNER_ONLY` says why not), with Undo or Approve.
- [ ] No new layer violation, no new file over 800 lines (the ratchets).
- [ ] Tests cover the rules, the route and the Co-Founder kind; a bug fix has a
      test that failed before.
- [ ] `pnpm check` passes. Hermes-dependent tests you touched pass locally.
- [ ] `openapi.json` and the web's types are regenerated.
- [ ] CHANGELOG, user guide and architecture are updated where needed;
      `scripts/check-docs.py` passes.
- [ ] No keys, tokens or personal data in code, tests, docs or screenshots.
- [ ] Checked by hand in the browser (light and dark, desktop and phone width).
