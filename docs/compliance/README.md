# Compliance overview

Standards review of AGOS at commit `33e135a1` (`main` = `eng/foundation`), 2026-11-02. Each file holds the evidence
(file:line or command output) per item. Status is for that commit; fixes committed on Wave 1 lane branches are shown
as "in flight" with their SHA.

## Legend

- **Status:** PASS / PARTIAL / FAIL / N/A (with reason). Scores count PASS over scored items (N/A excluded).
- **Covered by** (from the maintainers' internal engineering plan):
  - `W1-A` security hotfix + release blockers (`eng/sec`), `W1-B` CI gate (`eng/ci`), `W1-C` error monitoring
    (`eng/errors`), `W1-D` docs (`eng/docs`), `W1-E` skills/specs.
  - `W2-GW` Hermes Gateway (timeouts/retry/breaker), `W2-RVA` read-vs-act, `W2-TX` transactions/saga/idempotency,
    `W2-STG` staging + flags + resource limits, `W3` services/web splits/screenshots/evals.
  - `P4-Fn` security audit fix Fn (Phase 4), not yet given a wave. `P5` Phase 5 item without a wave. `ADD` plan
    "Additions" item (proposed, waiting for owner OK, no wave). `P7` the "forever" phase.
  - **`NEW`**: nothing in the plan or the audit fix lists covers it.

## Summary

| Framework                       | File                                                               | Score (PASS / scored)                                                                                  | Top 5 gaps                                                                                                                                                                                                                                                | Owning wave / lane                                            |
| ------------------------------- | ------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------- |
| OWASP ASVS 5.0 L2               | [owasp-asvs-5.md](owasp-asvs-5.md)                                 | **16 / 41** (21 after W1 merges)                                                                       | 1. Agent gate fails open, no server re-check (V8.2) 2. Owner-only powers in `direct` mode (V8.2) 3. Gateway reaches Docker socket → cross-workspace (V8.4) 4. Next RCE + 13 vulnerable Python pkgs (V15.2) 5. Webhooks `INSECURE_NO_AUTH` default (V13.2) | W1-A, P4-F6, NEW, W1-A/W1-B, P4-F8                            |
| OWASP LLM Top 10 2025 + Agentic | [owasp-agentic-top10.md](owasp-agentic-top10.md)                   | **4 / 15** (2 N/A)                                                                                     | 1. No read-vs-act taint (LLM01/ASI01) 2. Excessive agency, `direct` default (LLM06/ASI02-03) 3. Agent self-approves held memory writes (ASI06) 4. Cross-workspace via Docker socket / MCP relay 5. No spend cap, no sandbox limits (LLM10)                | W2-RVA, W1-A + P4-F6, P4-F6 + NEW, NEW + P4-F10, W2-STG + NEW |
| STRIDE threat model             | [threat-model.md](threat-model.md)                                 | **5 / 27** (10 after W1 merges)                                                                        | 1. T11 prompt injection → owner actions 2. T14 gateway escape via Docker socket 3. T3 Next RCE 4. T1 Caddy header forgery 5. T18 no resource limits                                                                                                       | W2-RVA, NEW, W1-A, P4-F7, W2-STG                              |
| NIST SSDF 1.1                   | [nist-ssdf.md](nist-ssdf.md)                                       | **1 / 19**                                                                                             | 1. PS.2 no release integrity (no tags, checksums, signatures) 2. PO.4 no enforced gate (no branch protection, merge after ship) 3. PW.7 no SAST, no review 4. RV.1 no Dependabot/audit 5. PW.9 insecure defaults                                          | ADD + NEW, W1-B + owner, W1-B, W1-B, P4-F4/F6/F8              |
| SLSA v1.0 Build                 | [slsa.md](slsa.md)                                                 | **Build L0; 0 / 10**                                                                                   | 1. No release artifact/provenance 2. No SBOM 3. Unsigned tags, installer clones `main` unverified 4. Actions pinned by tag 5. Base images by tag, sandbox built on each host                                                                              | ADD, ADD, NEW, W1-B, NEW                                      |
| Well-Architected (6 pillars)    | [well-architected.md](well-architected.md)                         | **6 / 32**                                                                                             | 1. No staging, no flags (OE3-4) 2. No backups without password, no restore test (RE2) 3. No resource limits (RE4) 4. Non-atomic DB+Hermes changes (RE5) 5. No real page / first-token measurement (PE3)                                                   | W2-STG, ADD + P5, W2-STG, W2-TX, NEW                          |
| Google SRE                      | [sre.md](sre.md), [postmortem-template.md](postmortem-template.md) | **1 / 5 SLIs measurable today** (S5 backups)                                                           | 1. Page load SLI (no RUM) 2. Chat first token not recorded 3. Availability probes not stored 4. Automation due time not recorded 5. No `scripts/slo.py` report                                                                                            | NEW, NEW, W1-C + NEW, NEW, NEW                                |
| DORA                            | [dora.md](dora.md), `scripts/dora.py`                              | 4 / 4 metrics computed (proxy): 7.0 deploys/week, lead 3.9 h median, CFR 15-21%, restore 10.7 h median | 1. No live-ship ledger (merges ≠ ships) 2. Failures guessed from subjects 3. Restore measured merge-to-merge 4. CFR 15-21% in Hermes-boundary files CI can't test 5. 973-commit bulk sync distorts lead time                                              | NEW, NEW, NEW, W1-B (nightly real-Hermes), — (one-off)        |

Security audit pass of `main..eng/w7` (2026-11, lane m4): [audit-2026-11.md](audit-2026-11.md).

## NEW gaps (not covered by the plan or the audit fix lists)

Ordered by risk. These need a wave/lane assigned.

1. **Gateway → Docker socket / `/proc`** escapes the Landlock wall and reads every workspace (ASVS 21, Agentic 14,
   T14). Gateways must not hold docker-group access: a socket proxy that only starts the workspace's own sandbox spec,
   `hidepid` on `/proc`, or a uid per gateway.
2. **AGOS user is root-equivalent (docker group) and the sandbox terminal runs as root** (ASVS 36, Agentic 12, T16):
   rootless Docker or a small privileged sandbox helper; non-root terminal user.
3. **Tainted turn → every Hermes memory/skill write is held** for the owner, regardless of `write_approval`
   (Agentic 5). The planned read-vs-act gate covers `agos_action` only.
4. **Spend cap** per workspace/day for pay-per-token keys, through the existing ESTOP pause (Agentic 11, T19, CO2).
5. **Per-workspace egress allowlist** option on `agos-egress` (Agentic 3, T17).
6. **MCP check at connect time**: route Hermes's host-side MCP connections through the egress proxy, so the private-range
   check cannot be bypassed by DNS changes after the add-time check (ASVS 38).
7. **Security event logging**: refused Hosts, bad internal/bridge keys → System Log + alert on bursts (ASVS 39, T24).
8. **Rogue-agent alerts**: tell the owner when an agent creates persistence (automation, MCP, skill, key) or exceeds N
   actions in a turn (Agentic 17).
9. **Release integrity beyond the plan's "signed releases"**: signed tags, installer verifies checksum/attestation and
   defaults to the latest tag (not `main`), base images pinned by digest, sandbox image published with provenance,
   SLSA L3 generator (SLSA, SSDF PS.1/PS.2, Agentic 4).
10. **Data inventory**: one page of what data leaves the host, to whom, and retention (ASVS 33).
11. **SLIs that do not exist yet**: web-vitals report + page probe, `chat_turns.first_output_at`, stored `/health`
    probe ledger + deep health, automation due-time record, `scripts/slo.py` (SRE S1-S4).
12. **Ship ledger + `Fixes:` trailer** so DORA and "what runs live" come from data, not merges (DORA, OE1).
13. **CI check that a fix PR touches a test** (SSDF RV.3; the PR template asks, nothing enforces).
14. Low: HSTS when served over HTTPS (ASVS 9); bridge auth before body parsing (ASVS 8, T9); idle-gateway sleep
    (SU1).

## Review cadence

- **Monthly**, first working day (plan Phase 7: "monthly Well-Architected + SRE + security review"): re-run
  `scripts/dora.py` (append to [dora.md](dora.md)), fill the SLO table from [sre.md](sre.md), re-check every
  non-PASS row whose fix merged (flip status with the merge SHA as evidence), re-run `pnpm audit --prod` and
  `uvx pip-audit`, update the scores above.
- **On change**: a new listener, outside service, agent power or trust boundary updates
  [threat-model.md](threat-model.md) in the same PR.
- **Each release**: SLSA table and the SBOM/provenance steps in [slsa.md](slsa.md).
