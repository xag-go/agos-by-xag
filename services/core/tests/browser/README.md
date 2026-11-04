# Browser tests (Playwright)

The owner's main flows clicked like he clicks them, and ~40 key screens compared with
stored baselines, on the **real web build** (`next build` standalone server) in front
of the **real core** with the test suite's fake Hermes (the "light rig", no Hermes, no
model, no Docker). CI runs them in the `browser` job (.github/workflows/ci.yml).

| File                 | What                                                                                                                                                                                                                                                                                                |
| -------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `serve_light.py`     | the light core: `work_env`'s fake-Hermes app served by uvicorn on a real port, two seeded workspaces, a thread that answers chat messages ("Fake answer: …")                                                                                                                                        |
| `seed.py`            | what the workspaces hold: cards, goals, a chat, an automation, a plan and a hire waiting in the Inbox                                                                                                                                                                                               |
| `rig.py`             | starts the light core + the standalone web server, stops both                                                                                                                                                                                                                                       |
| `test_flows.py`      | clicks: create a card, block/unblock it, open each card tab, send a chat message and see the answer, approve a hire in the Inbox and Undo it, save workspace settings and put them back, automation off/on                                                                                          |
| `test_screens.py`    | 39 screens vs `screens/<render key>/*.png`, pixel diff with a threshold                                                                                                                                                                                                                             |
| `pages.py`           | ready-wait, frozen animations, masks for live parts (times, "x ms", Thinking, shas), the diff                                                                                                                                                                                                       |
| `test_a11y.py`       | axe-core (the web's pinned dev dependency) on 11 main screens: WCAG 2.0/2.1 A+AA findings per screen and rule vs `axe-baseline.json`, which only shrinks (`AGOS_AXE_UPDATE=1` records fixes)                                                                                                        |
| `test_lighthouse.py` | Lighthouse (pinned dev dependency, Playwright's Chromium, desktop preset) on 5 main screens: performance / accessibility / best-practices scores as missed points vs `lighthouse-baseline.json` (scripts/ci/budget_ratchet.py, 5 pts noise floor; `AGOS_LIGHTHOUSE_UPDATE=1` records better scores) |

## Run

```sh
cd services/core
uv run playwright install chromium            # once (Playwright's own Chromium)
pnpm --filter @agos/web build                 # from the repo root: the web build to test
uv run pytest tests/browser                   # clicks + screens (~1 min)
```

The core suite (`pytest` with no path) skips this folder; it runs only when named.

Environment: `AGOS_BROWSER_PORTS=core,web` (default `9611,9612`), `AGOS_WEB_STANDALONE`
(another build's `.next/standalone/apps/web`), `AGOS_BROWSER_OUT` (screens, diffs and
the rig's `core.log` / `web.log`; CI uploads it when the job fails),
`AGOS_BROWSER_EXECUTABLE` (another Chromium, e.g. `/usr/bin/google-chrome`: its
screens use their own `local-…` baselines).

## Baselines

A screen differs when more than `AGOS_SHOTS_MAX_PIXELS` (default 400) of its pixels
moved by more than the anti-aliasing tolerance (a 100x30 block of new color fails); the diff PNG (changed pixels in red)
is written beside the actual one. After an intended UI change, the owner's design
rule applies: update and look at every changed PNG before committing it.

```sh
AGOS_SHOTS_UPDATE=1 uv run pytest tests/browser/test_screens.py
```

Baselines are keyed by the browser build (`chromium-<major>`): Playwright pins it, the
web's fonts are its own (next/font), so a runner and this server draw the same pixels.
The few system fonts the web names (the Vision line's "Noto Serif") come from
`fonts/` (OFL), loaded into every page by conftest.py, never from the machine: a runner
without them would fall back to DejaVu Serif. The rig also fakes this machine's
`tailscale` command (serve_light.py: "installed, not activated"), so Settings → Access
shows the same card everywhere. A new machine-dependent screen gets the same
treatment (pin or fake it in the rig), not a higher pixel limit.
Bumping Playwright changes the key: make the new folder with `AGOS_SHOTS_UPDATE=1`,
review it, delete the old one.

Pages that read Hermes itself (Settings → Hermes, Helper models, Connectors; the
workspace's Capabilities) show an error on the light rig and are not in the list.
