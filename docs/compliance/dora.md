# DORA metrics (2026-10-01 → 2026-11-02)

Computed with [`scripts/dora.py`](../../scripts/dora.py) (stdlib Python, read-only git) on `origin/main` at
`33e135a1`:

```bash
git fetch origin
python3 scripts/dora.py --since 2026-10-01 --until 2026-11-02T23:59:59          # markdown
python3 scripts/dora.py --since 2026-10-01 --until 2026-11-02T23:59:59 --json   # for the monthly file
python3 scripts/dora.py ... --wide        # broader fix pattern (upper bound for failures)
python3 scripts/dora.py --ships ships.csv # once a live-ship ledger exists (sha,iso_time per row)
```

## Result (run 2026-11-02)

| Metric                                  | Value                                |
| --------------------------------------- | ------------------------------------ |
| Period                                  | 2026-10-01 .. 2026-11-02 (33.0 days) |
| Deployments                             | 33 (7.0/week, 5 active days)         |
| Lead time, median (all commits)         | 171.0 h                              |
| Lead time, p90 (all commits)            | 533.1 h                              |
| Lead time, median (without bulk sync)   | 3.9 h                                |
| Lead time, median of per-deploy medians | 0.9 h                                |
| Change failure rate                     | 15.2% (5/33)                         |
| Time to restore, median / max           | 10.7 h / 107.4 h                     |

| Failed deploy                                                                    | Fixed by deploy | Fix commit                                                                        | Restore (h) |
| -------------------------------------------------------------------------------- | --------------- | --------------------------------------------------------------------------------- | ----------- |
| `450577bf` Step 44: the root bot is the Co-Founder (#6)                          | `a07018e2`      | `ded62fae` Step 51: fix the lost reports_to write…                                | 15.7        |
| `524dc0d5` Merge pull request #9 (step54/integrate)                              | `7e6dd4b3`      | `be94a520` contract: pin agent.insights.InsightsEngine… (live usage fix d87c7599) | 3.3         |
| `5fd7339a` agos_action from board cards, automation runs and subagents (#18)     | `e02b33fc`      | `f52381d1` fix: a card's or automation's change no longer collides…               | 10.7        |
| `e02b33fc` fix: card changes no longer collide with the Co-Founder's live answer | `f760fdf9`      | `36efee83` fix: a Hermes command typed in a room while it answers…                | 1.2         |
| `f760fdf9` Merge pull request #24 (fix/card-turn)                                | `aaef341c`      | `f9e2d693` Co-Founder kinds: fixes from the real-chat run…                        | 107.4       |

With `--wide` (subjects with broke/wrong/stale/lost/missing/fail… as well): change failure rate 21.2% (7/33),
restore median 5.3 h, max 107.4 h.

## How each number is computed

| Metric                | Definition used                                                                                                                                                                                                                                                                                       | Caveat                                                                                                                                                                                                                                                                                                                   |
| --------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Deployment frequency  | First-parent commits on `main` (each PR merge or direct push).                                                                                                                                                                                                                                        | `main` is merged **after** the live ship (quality audit §6), so this counts merges, not ships. Merges cluster: all 33 fall on 5 days (10-26, 10-27, 10-28, 11-01, 11-02); `main` did not move between 09-26 and 10-26.                                                                                                   |
| Lead time for changes | For each deployment D, every non-merge commit in `D^1..D`: D's commit time − the commit's author time.                                                                                                                                                                                                | One bulk sync, `ea123f3b` "Bring main up to live (50f1c3a9) (#3)", carried 973 of the 1,143 commits deployed in the period (most written before 10-26 and shipped live earlier); it dominates the all-commit median (171 h). The "without bulk sync" (3.9 h) and per-deploy (0.9 h) medians describe the normal PR flow. |
| Change failure rate   | A fix commit (subject matches `fix`/`bug`/`hotfix`/`revert`/`regress`) blames the latest earlier deployment (≤ 7 days, before the fix was authored) that changed a source file the fix touches (tests, docs, lockfiles, `openapi.json`, `core-api.d.ts` ignored). A deployment with ≥ 1 blame failed. | Heuristic: subjects here describe behaviour and rarely say "fix" (quality audit §3: 44 strict vs 269 wide), so the strict number is a lower bound and `--wide` an upper bound. `be94a520` matches only because its subject contains "live usage fix".                                                                    |
| Time to restore       | Failed deployment → the deployment that carried its fix.                                                                                                                                                                                                                                              | Upper bound: live was often fixed earlier by a ship that `main` records only at merge time. The 107.4 h case is the gap between the 10-28 and 11-02 merges, not 4 days of outage.                                                                                                                                        |

Reading: deployment frequency and PR lead time are high (daily-or-better on active days, under a day); change
failure rate of 15-21% and restore measured in hours are the weak side, and they match the bug hotspots (Hermes
boundary files that CI cannot test, quality audit §3).

## Gaps that make the numbers weaker than they should be

1. **No ship ledger** (NEW). Live ships are not recorded in git. Fix: the ship script tags each live ship
   `ship/<UTCstamp>` (lightweight tag on the shipped SHA, pushed) or appends `sha,iso_time` to a private
   `ships.csv`; then run `scripts/dora.py --ships`. This also answers "what runs live" (Well-Architected OE1).
2. **Failures are guessed from subjects** (NEW). Fix: a `Fixes: <sha>` trailer (or `Fixes #<PR>`) on every fix
   commit, and P0/P1 incidents linked from `docs/postmortems/`; the script can then read trailers instead of
   regexes.
3. **Restore time from merges** (NEW, same fix as 1): with ship tags, restore = failed ship → next ship containing
   the fix.

## Monthly report

On the first working day of each month, as part of the compliance review ([README.md](README.md)):

1. `git fetch origin && python3 scripts/dora.py --since <first day of last month> --until <last day>T23:59:59 --json > docs/compliance/dora/<YYYY-MM>.json`
   (with `--ships` once the ledger exists).
2. Add one row per month to the table below; compare with the previous month and the 3-month median.
3. For every failed deployment the script lists: is there a regression test and (P0/P1) a postmortem? If not, open
   the action item.
4. Changes in definitions (pattern, window, ledger) are noted in the row so trends stay comparable.

| Month             | Deploys/week | Lead time median (no bulk) | CFR strict / wide | Restore median | Source           | Notes                                                                     |
| ----------------- | ------------ | -------------------------- | ----------------- | -------------- | ---------------- | ------------------------------------------------------------------------- |
| 2026-10-01..11-02 | 7.0          | 3.9 h                      | 15.2% / 21.2%     | 10.7 h         | merges to `main` | First run; bulk sync `ea123f3b` excluded from the second lead-time figure |
