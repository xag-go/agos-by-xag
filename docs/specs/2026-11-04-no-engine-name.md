# One update button, no engine name in the app

Owner request 2026-11-04. Both repos (public + private).

## 1. One "Check update" button
- Settings → General: the two cards "Hermes update" and "Update AGOS" become one card **Updates** with one
  **Check update** button. It checks both; if either has a new release it says "An update is ready" (no
  name of which part) and **Update now** does both: AGOS first, then the engine (each with its existing
  backup, fit check and roll-back). Nothing new: "You're up to date".
- An install not made by the installer keeps today's note (updated the way it was installed) for the AGOS
  part only; the engine part still updates from the button.
- Co-Founder parity: one operation `check_updates` / `run_updates` (Undo = the existing rollback; audit row).

## 2. Remove Settings → Hermes settings
- The page, its nav entry and its route go. `/settings/hermes` redirects to `/settings/general`.
- The core API for it stays (the Co-Founder still reads/changes engine settings from chat, with Undo).
- Curated cards (General time limits, Models, Helper models...) stay.

## 3. Errors without source
- No "Web app · AGOS itself" / "Hermes" label on a row, no "Every source" filter. Workspace filter stays.

## 4. Health without the engine name
- Per workspace: two rows **Full check** and **Status** (were `hermes doctor` / `hermes status --full`), no
  folder path. Same checks underneath.

## 5. No "Hermes" word anywhere in the app
- Every owner-visible text (web copy, page titles, hints, toasts, error messages and hints from the core,
  activity/inbox titles, setting descriptions written by AGOS) explains what happens without the name:
  "applies when the workspace next starts", "the engine's own maximum is 10 minutes" → "the maximum is 10
  minutes", etc.
- Only exception: the **Import from Hermes** entries in Connectors, Skills and Capabilities.
- Not touched: code identifiers, API paths, docs/README for developers.
- Guard: a test fails if a web string or a core owner-facing message contains "Hermes" outside the
  allowlisted import entries.

## Done
- Screens checked in a browser (General, Errors, Health, Tools, Library), full CI chain green, both repos.
