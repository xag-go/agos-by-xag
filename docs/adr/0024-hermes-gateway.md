# ADR 0024 — The Hermes Gateway: one place AGOS talks to Hermes

Date: 2026-11-02 · Status: proposed (engineering plan, Phase 2 "Hermes Gateway", lane GW)

## Problem

Hermes is the engine (ADR 0010, 0020), but AGOS reaches it from about 240 places
(audit `architecture.md` §3): 111 raw CLI calls from `actions/` through engine
internals (`core.engine._hermes`, `walled_cli`, `config_writes`, `managed_write`,
`kanban_board._cli`), 8 `subprocess` runs of Hermes outside `engine/`, 33 direct
read-only opens of Hermes's `kanban.db` / `state.db`, 21 runs of Hermes's Python, and
more. The one shared seam, the `Runner` protocol (`engine/hermes.py`), has a timeout
but no retry, no notion of "Hermes is down", no per-call log and no error type: a
dead Hermes costs every page its full timeout, again and again, and the owner sees
whatever text the caller made up.

## Decision

`agos_core/hermes_gateway/` is the boundary. It **wraps** calls; it never does what
Hermes does (hard rule 1). Pieces:

1. **Typed errors** (`errors.py`). `EngineError` moves here (re-exported from
   `engine/hermes.py`) and gets a `code`. Subclasses, all still `EngineError`, so
   every existing `except EngineError` keeps working:
   - `HermesFailed` (`HERMES_FAILED`): Hermes ran and refused (non-zero exit);
     carries `exit_code` and Hermes's own `reason`. Hermes is up.
   - `HermesTimeout` (`HERMES_TIMEOUT`): no answer in time, or the process could not
     start (`OSError`). Same owner-facing text as before ("hermes did not answer").
   - `HermesUnavailable` (`HERMES_UNAVAILABLE`): the root's circuit is open; raised
     at once, nothing is started. Also a `ConnectionError`, so code that already
     treats "could not start Hermes" (`OSError`) as "no answer" degrades the same way.
2. **`GatewayRunner`** (`runner.py`) wraps any `Runner` (the real
   `SubprocessRunner`, or a test's fake) and keeps its interface (`run`, `spawn`).
   `HermesEngine.runner` is a property: assigning a runner wraps it, reading returns
   the wrapper, unknown attributes reach the wrapped runner. The 59 test files that
   pass or assign a fake runner keep working, and their fakes now sit under the
   policies. Around each `run`:
   - **Timeouts**: unchanged (the caller's value, floored by `hermes_wait`).
   - **Circuit breaker per workspace root** (`breaker.py`). The key is the root of
     the call's `HERMES_HOME` (a member home `…/profiles/<m>` counts as its root; no
     home = the shared home). 3 unavailability failures in a row (`HermesTimeout`)
     open it for 30 s; calls then fail fast with `HermesUnavailable`. After the
     cool-down one call is let through as the probe (half-open); success closes, a
     failure re-opens. A refusal (`HermesFailed`) is an answer: it closes the
     circuit. Recovery commands (`update`, `pm`, `gateway`, `doctor`, `--version`)
     always pass, so AGOS can still repair or restart a stuck Hermes. One root down
     never slows another root (workspace isolation, hard rule 2).
   - **Bounded retry, idempotent reads only**: an allowlist of pure-read CLI
     commands (`kanban list/show/…`, `config get/show/path`, `cron list`, `status`,
     …). One more try after 0.5 s, only when the process could not start
     (`OSError`: a busy machine, a binary being replaced by an update). A timed-out
     read is not retried (another full wait would make the page slower, hard rule
     6), and no write is ever retried.
   - **Structured log** (`agos.hermes_gateway`): one record per call with the
     command words (never values: `hermes config set (+2 args)`), the root key,
     duration, exit code and outcome; debug for success, info for a refusal, warning
     for timeouts and an open circuit. The record's `extra` holds the same fields.
3. **Process runs** (`process.py`): `run_process` / `spawn_process` for the places
   that run Hermes's runtime or CLI outside the `Runner` (sign-in flows, runtime
   probes). Same breaker, same log, the caller's own result handling.
4. **CLI facade** (`cli.py`): `cli`, `walled_cli`, `config_writes`, `managed_write`,
   `unmanaged_in`, `unmanaged_writes` — the public names actions call instead of
   engine internals. They forward to the engine's own methods (so the
   per-home write locks and the tests' patches on the engine stay where they are).
5. **Hermes DB reads** (`hermes_db.py`): `connect_ro(path, timeout=…)` is the only
   way AGOS opens Hermes's `kanban.db` / `state.db` (URI `mode=ro`, a busy timeout,
   `sqlite3.Error` as before). The SQL stays the same; moving each query into one
   reader per DB (`BoardReader`, plan G3) is the next step.
6. **Ratchet** (`tests/test_hermes_gateway_ratchet.py`, baseline
   `tests/hermes_gateway_baseline.json`): per file, the count of Hermes calls outside
   the gateway (engine internals called from outside `engine/`, `subprocess`,
   `sqlite3.connect`, `hermes_python(`, `engine.runner`) may only shrink; a shrink
   must lower the baseline in the same change. `actions/` may not import
   `subprocess` or open a database except the files still in the baseline.

## Not now

- HTTP/socket calls to the gateway (4, inside `engine/`), writes into Hermes homes
  (§3H), `config.yaml`/`.env` reads (§3G) and the ~430 other engine method calls (§3E)
  stay where they are; they are later Gateway PRs (plan G6, G8).
- Mapping `HERMES_UNAVAILABLE` to an HTTP status belongs to the error lane
  (`ErrorCode` + `AgosError`); until then callers keep turning `EngineError` into
  their own `ActionError`.

## Consequences

- A dead or wedged root costs three timeouts, then fails in microseconds until it
  answers again; other roots are not affected.
- Every Hermes CLI call leaves a log line with its duration and exit code and no
  argument values.
- New code that runs Hermes outside the gateway fails the ratchet.
