# Browser, load and failure tests

Three suites beside the core tests, each run only when named
(`services/core/tests/explicit_only.py`): the core suite and CI's core-tests job
never collect them.

| Suite                                                  | What                                                                                                                                | Needs                                         | Where it runs             | Time      |
| ------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------- | ------------------------- | --------- |
| [browser](../../services/core/tests/browser/README.md) | the owner's 7 main flows clicked with Playwright; 39 screens against stored baselines (pixel diff)                                  | a web build, Playwright's Chromium; no Hermes | CI job `browser`, locally | ~1 min    |
| `services/core/tests/load`                             | N workspaces x M cards x K answers at once: latency p50/p95, errors, memory                                                         | real Hermes, ~0.5 GB per workspace            | locally, nightly runner   | 10–40 min |
| `services/core/tests/failure`                          | the gateway killed mid-answer, the model unreachable, the core restarted mid-answer and during a card run, disk full, database busy | real Hermes, ~2 GB                            | locally, nightly runner   | ~45 min   |

```bash
cd services/core
uv run pytest tests/browser                       # needs `pnpm --filter @agos/web build` first
uv run pytest tests/failure                       # a real rig on ports 9621-9623
AGOS_LOAD_WORKSPACES=6 AGOS_LOAD_CARDS=120 AGOS_LOAD_TURNS=24 uv run pytest -s tests/load
```

The load and failure suites drive the e2e rig (`tests/e2e/rooms_e2e.py`, real Hermes
gateways, the fake model, fake Telegram) through `tests/failure/real_rig.py`, in their
own folder (`AGOS_E2E`, default `~/agos-roots-test/e2e-l6-<suite>`) and ports
(`AGOS_E2E_PORTS`); `AGOS_E2E_KEEP=1` keeps the folder (logs, databases) after the
run. Everything the rig started is stopped at the end, also on a failure.

## What the failure tests check

Each test breaks one thing, then checks that AGOS recovers: the answer ends
(completed, or failed with a reason) and is never left "running"; a failed answer
shows in the workspace's Log (problems); nothing he wrote is lost or doubled; the
next message is answered.

| Failure                            | How it is made                                                                            | What AGOS does (measured on the rig)                                                                                                  |
| ---------------------------------- | ----------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| Hermes gateway killed mid-answer   | SIGKILL of the gateway, then Hermes's service start                                       | Hermes waits ~5 min for the dead process's session lock, then resumes the answer; AGOS shows it running meanwhile, then completed     |
| Model unreachable                  | the fake model stopped                                                                    | Hermes retries without end (10 attempts, one more on a rebuilt client, again); the answer stays "running" (see below)                 |
| Core restarted mid-answer          | SIGKILL of the core, start again 5 s later                                                | the answer arrives once (fixed here: it came twice, see below)                                                                        |
| Core restarted during a card's run | SIGKILL of the core right after a card is given to a member                               | the card ends Done, the database checks clean                                                                                         |
| Disk full                          | `prlimit --fsize=4096` on the core (every file write past 4 KiB fails, like a full disk)  | the message is refused with an error, no answer is started, reads keep working, nothing is lost; writes work again once there is room |
| Database busy                      | another process holds `agos.db` in an exclusive transaction for 12 s (the core waits 5 s) | the write waits or fails cleanly; the next message works                                                                              |

### Found by these tests

- **Fixed (agos-guard plugin, `bridge_platform.py`)**: the core restarted while
  Hermes took a message, so the plugin's "done" never arrived; AGOS hands an
  unconfirmed message again after 60 s, and Hermes got it twice — his message and
  the answer showed twice. The plugin now remembers what Hermes already has and only
  confirms a message handed again (`tests/test_agos_adapter.py`).
- **Open (Hermes)**: with the model unreachable, Hermes's retry loop never ends: 10
  attempts, "one last primary attempt" on a rebuilt client, then 10 attempts again
  (seen for 20+ min). The owner sees "Thinking…" with no word of the model being
  down until AGOS's stale close (3 h, `gateway_platform.STALE_AFTER_S`). AGOS sets
  `agent.api_max_retries: 10` on purpose (a provider hiccup is waited out); the
  endless part is Hermes's. A proposal for Hermes: stop after the last attempt and
  end the turn with the error, which AGOS already records and shows in the Log
  ([proposal](../hermes-proposals/model-unreachable-retry-budget.md)).
  The test ends `xfail` while this holds.
- **Open (Hermes)**: after a gateway crash, its restart waits ~5 min on the dead
  process's session lock before resuming the cut answer, and posts a "⏳ Still
  waiting for the other Hermes process on this session (Ns)…" line every 15 s into
  the owner's chat (about 20 lines). A proposal for Hermes: check the lock holder's
  pid and take a dead one's lock at once
  ([proposal](../hermes-proposals/dead-session-lease-on-restart.md)). In one run of two, his cut message was
  missing from the chat afterwards (Hermes's resume starts from its own note); the
  test ends `xfail` when that happens.

## Load: measured limits

Measured on this server (14 CPUs, 14.3 GB, shared with other test runs and five
builders at the time), 6 workspaces (each a Co-Founder gateway), 120 cards, 24
answers asked at once, the fake model (answers in ~0 s, so the times are AGOS's and
Hermes's own):

| What                                      | p50     | p95    | Errors                                |
| ----------------------------------------- | ------- | ------ | ------------------------------------- |
| New workspace (POST /workspaces)          | 5–9 min | 9+ min | 2 of 6 past the 10 min client wait    |
| New card (8 at a time)                    | 0.7 s   | 0.8 s  | 0                                     |
| Chat answer, 24 at once over 6 workspaces | 5.2 s   | 5.6 s  | 0, none left running                  |
| Page reads while the answers run          | 13 ms   | 580 ms | 0 (kanban, inbox, log, workers, home) |

Memory (RSS, peak): the core 140–160 MB; each workspace's gateway about 190–280 MB
at rest; with its Hermes workers during answers about 420–520 MB per workspace.
Idle rig (no workspace): core 100 MB.

What this means for the hardware minimum ([INSTALL.md](../INSTALL.md#minimum-hardware)):

- **Memory**: plan ~0.5 GB per busy workspace on top of ~0.4 GB for the core and the
  web (the sandbox containers come on top, not measured here: the rig runs no Docker).
  Estimate from these numbers: 8 GB carries about 6–8 busy workspaces with room for
  the system and a web build;
  16 GB about 20.
- **New workspace**: on the rig every workspace's Hermes root builds its own
  dependency environment (`installs/`, ~0.6 GB of disk each) when it is made, which is
  most of the 5–9 minutes; count ~0.6 GB of disk per workspace.
- **Answers**: 24 at once stay at ~5 s each end to end with the fake model, and the
  pages stay fast (p50 13 ms); the slowest reads (p95 0.6 s) are the ones that wait on
  Hermes's CLI.
- Not measured yet: 20 workspaces / 200 cards / 50 answers (the default of the test;
  it needs ~12 GB free), real models, the sandbox containers.

Run it again with `AGOS_LOAD_WORKSPACES`, `AGOS_LOAD_CARDS`, `AGOS_LOAD_TURNS`; the
report goes to `AGOS_LOAD_OUT` (`report.md`, `report.json`).

## Browser tests

See [tests/browser/README.md](../../services/core/tests/browser/README.md): the light
rig, the flows, how baselines are made and reviewed.
