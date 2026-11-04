# Error messages

When AGOS can't do something, it says so in a sentence (the message), and every
error also has a **code** and a **what to do**. This page lists every code. Developers
see the same fields in the API's error answers: `detail` (the message), `code`,
`help` (what to do) and, for errors AGOS logged, `requestId` (the reference shown
in Settings → Errors).

```json
{
  "detail": "The card no longer exists.",
  "code": "not_found",
  "help": "Reload the page to see what is there now."
}
```

The words live in one place, `services/core/src/agos_core/domain/errors.py`; a test
(`tests/test_error_texts.py`) fails when a code has no words, or when this page and
that file disagree.

## Your request

### `invalid_request`

Something in what was asked is missing or not filled in the way AGOS expects.

**What to do:** Read the message, correct the field it names and try again.

### `invalid_value`

A value AGOS received is not one it can use (a wrong date, number or name).

**What to do:** Check what you typed or picked and try again. If it keeps happening, reload the page: it may show an old version of the item.

### `not_allowed`

This is not allowed here: it needs the owner, or a setting turns it off.

**What to do:** Do it yourself from the page it belongs to, or turn on the setting the message names.

### `not_found`

The item is gone: it was deleted, archived or moved, maybe from another window or by an agent.

**What to do:** Reload the page to see what is there now.

### `conflict`

AGOS can't do this right now, in the state the item is in (it is busy, already done, or something else must happen first).

**What to do:** Read the message: it says what is in the way. Wait for it to finish, or do the step it names first, then try again.

### `too_large`

The file or text is bigger than AGOS accepts here.

**What to do:** Use a smaller file (or split it), then try again.

### `unsupported_file`

AGOS can't read this kind of file here.

**What to do:** Save it in one of the formats the message names, then try again.

## Other programs AGOS uses

### `service_failed`

Another program AGOS asked (Hermes, an app you connected, or the model provider) answered with an error.

**What to do:** Try again in a minute. If it keeps failing, check the connection or key in Settings, and look at Settings → Errors for the details.

### `service_unavailable`

A part AGOS needs is not running or not reachable right now.

**What to do:** Wait a minute and try again. If it lasts, run `agos status` on the server (or open Settings → Errors) to see which part is down.

## Hermes, the agents' engine

### `ENGINE_ERROR`

Hermes, the engine behind the agents, could not do what AGOS asked.

**What to do:** Try again. If it keeps failing, open Settings → Errors for what Hermes said.

### `HERMES_FAILED`

Hermes ran but refused or failed this request.

**What to do:** Read the message for Hermes's reason, fix what it names (a setting, a key, a name already in use) and try again.

### `HERMES_TIMEOUT`

Hermes did not answer in time: the server is busy, or the request was long.

**What to do:** Wait a minute and try again. If it happens often, the server may need more memory: see docs/INSTALL.md, "Minimum hardware".

### `HERMES_UNAVAILABLE`

Hermes is not answering right now, so AGOS paused calls to it for a short time.

**What to do:** Wait a minute: AGOS tries again by itself. If it lasts, restart AGOS (`agos restart`) and look at Settings → Errors.

## This machine

### `cage_refused`

Workspace isolation (the cage around each workspace's agents) can't be built on this machine, so AGOS won't start the workspace's agents without it.

**What to do:** Run `agos doctor` on the server: it says why and the exact fix (usually: run the installer again, it installs bubblewrap and its AppArmor profile). See docs/troubleshooting.md, "The cage refused to start".

The installer stops with the same code when its cage self-test fails, and prints the
fix for this machine. Running agents without the cage is possible only on purpose
(`AGOS_SANDBOXD=off`); Settings → Server & backup and `agos doctor` then say so for
as long as it lasts. Details: [troubleshooting](troubleshooting.md#the-cage-refused-to-start).

## AGOS itself

### `internal_error`

AGOS hit a bug. Nothing you did caused it.

**What to do:** Try again. If it happens again, open Settings → Errors, copy the diagnostics and report it with the reference shown in the message.

## Still stuck?

Open Settings → Errors and use **Copy diagnostics**: it copies a report without keys
or personal content. Paste it into a new issue on GitHub (Bug report) with what you
were doing. See [SECURITY.md](../SECURITY.md) for anything that looks like a security
problem: never post those in a public issue.
