# Error monitoring

AGOS keeps its own errors in its System Log and groups them in **Settings → Errors**. No
outside service is used (no Sentry, nothing leaves the machine).

## What is collected

| Source   | Where it comes from                                                                                                                 | How                                                                                                                                                                                        |
| -------- | ----------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `core`   | Every ERROR on the core's loggers (`agos.*` and `agos_core.*`), every unhandled error in an API route, a background loop that stops | `actions/system_log.py` (the System Log handler), the catch-all handler in `api/app.py`                                                                                                    |
| `web`    | A page that broke in the browser (error boundaries, unhandled errors) and a page the server failed to render                        | `app/error.tsx`, `app/global-error.tsx`, `shared/ui/error-screen.tsx` → `POST /api/client-error` → core `POST /errors/report`; `instrumentation.ts` `onRequestError` → the same core route |
| `hermes` | ERROR entries of each workspace's Hermes `errors.log`                                                                               | Hermes's own CLI, `hermes logs errors --level ERROR`, in each root every 5 minutes when the file changed (`actions/hermes_errors.py`)                                                      |

An unhandled route error answers `500` with
`{"detail": "AGOS hit an internal error (ref <id>)…", "code": "internal_error", "requestId": "<id>"}`.
The same `ref` is on the System Log line and on the issue.

Secrets are wiped before anything is stored: the System Log's `redact()` (bot tokens, API
keys, webhook secrets, `token=…`-style values, the internal token). The web app wipes the
same families before it sends a report, and the core wipes again.

Reports from the web are rate limited: 5 a minute per open page, 10 a minute per web server
(`/api/client-error`) and 30 a minute in the core.

## Grouping

One row per **issue** (`error_issues`, migration 145). The fingerprint is the source, the
error's type, the message with numbers, ids, paths and quoted values replaced, and the top 3
frames (`module:function`, no line numbers, so a release that moves code keeps the issue).
One issue per fingerprint per workspace (none = AGOS itself).

Each issue keeps its count, first and last time, the AGOS version it was first and last seen
on (`VERSION` + the git commit), the last route, request id and traceback (8 KB). The 1000
issues seen most recently are kept.

## Alerts

The owner is told when an issue is **new**, when one he marked fixed **comes back**, and when
one happens **25 times within an hour** (a spike; told again at most every 6 hours). The
event is `agos.error` in Settings → Notifications:

- Instant: the Co-Founder's chat in AGOS, Telegram and the installed app. With no workspace
  yet, the installed app only.
- Daily digest: the chat in AGOS now, a line in the next digest.
- Silent: nothing; Settings → Errors still lists it.

At most 10 alerts an hour. Errors that already tell the owner themselves (a broken Hermes
contract) are counted but not told twice.

### What else is told this way

The ops watch (`actions/ops_watch.py`) logs these as errors, so they take the
same path: no backup password; no backup a day after the password was set; the
newest backup older than its schedule allows (daily 48 hours, weekly 8 days); a
failed scheduled backup; free disk or memory under 10% for 5 minutes; a failed
monthly restore test (or one skipped for lack of disk, at most once a week); a
failed weekly database check. The backup ones are logged at most once a day.

## Settings → Errors

The list of issues (open by default), filtered by workspace (or "AGOS itself") and source,
with count, first/last seen, version, route, reference and the traceback under Details.
**Mark fixed** has an Undo; an issue marked fixed opens again by itself when it happens again.
The page works with zero workspaces.

The Co-Founder can do the same from a chat: `mark_error_fixed` and `reopen_error`
(`engine/cofounder_parity/`), each with Undo, for errors of its own workspace or of AGOS
itself.

## Dead-man: the core itself is down

When the core is down nothing in it can tell anyone, so a timer outside it does:

- `agos-deadman.timer` (installed by `deploy/install-server.sh`) runs
  `deploy/agos-deadman.py` every minute as the AGOS user. It reads the core's `/health`.
- Down for 3 minutes: one Telegram message to the owner, sent straight to the Bot API.
  Back up: one "AGOS is back up" message.
- Where to send: `<data>/system/deadman.json` (0600), kept up to date by the core while it
  runs (`actions/deadman.py`): the path of the first workspace's Hermes `.env` that has a
  Telegram bot, and the owner's Telegram id. The token is read from that `.env` only when
  sending; AGOS keeps no copy. No bot yet: the message only goes to the journal
  (`journalctl -u agos-deadman`).

Knobs (environment of `agos-deadman.service`): `AGOS_HEALTH_URL`, `AGOS_DEADMAN_AFTER`
(seconds, default 180), `AGOS_TELEGRAM_API`. `services/core/tests/test_deadman.py` runs the
script against a fake `/health` and a fake Bot API.

Existing installs get the timer when the installer runs again (`agos check` lists it).
