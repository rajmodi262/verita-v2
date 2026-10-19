# Verita v2 — Task Tracker

> Single source of truth for progress. Updated in the same commit as the work it tracks.
> Plan: [PIVOT.md](PIVOT.md). Legend: `[ ]` todo · `[~]` in progress · `[x]` done ·
> `[!]` blocked (needs you) · `[-]` dropped (with reason).

## Status at a glance

| Milestone | Scope | Done / Total | State |
|-----------|-------|--------------|-------|
| M0 | Reset: repo, tooling, CI, auth skeleton | 26 / 30 | 4 left: need Docker (U3) and GitHub (U4) |
| M1 | Data foundation | 16 / 18 | 2 deferred: M1.11 → M2.20, M1.15 needs license (U7) |
| M2 | Detect — models and evaluation | 0 / 22 | Not started |
| M3 | Detect — Queue and Investigation UX | 0 / 18 | Not started |
| M4 | Decide — calibration, conformal, forecast, optimizer, drift | 0 / 20 | Not started |
| M5 | Decide — Capacity Planner UX | 0 / 10 | Not started |
| M6 | Defend — narratives, verifier, signing, ledger | 0 / 22 | Not started |
| M7 | Defend — Case File UX and maker-checker | 0 / 12 | Not started |
| M8 | Evidence Room, honesty pipeline, robustness | 0 / 14 | Not started |
| M9 | Harden and ship | 0 / 16 | Not started |

## Blocked on you

| ID | What I need | Unblocks |
|----|-------------|----------|
| U1 | Rotate the Groq key that is in v1's `START_BACKEND.bat` | Security hygiene (v1) |
| U3 | Start Docker Desktop (needed for Postgres-only tests and compose) | M0.22, M0.27 |
| U4 | Create an empty GitHub repo for v2 and push (I won't publish anything) | M0.29 (CI running on GitHub) |
| U5 | Put `GEMINI_API_KEY` and `GROQ_API_KEY` in `backend/.env` when we reach M6 | M6.07 |
| U7 | Confirm the IBM AML dataset license on its Kaggle page (I'll record it in `configs/datasets.yaml`) | M1.15, publishing DATA_CARD |
| U6 | Upgrade Node 20.18 → Node 22 LTS (Node 20 is end-of-life; Vite 7+ and Vitest 5 need ≥20.19/22). CI already uses 22. | Future tooling upgrades |

---

## M0 — Reset

Exit: empty app builds and runs locally; every CI gate is blocking and green; no personal files.

**Repository**
- [x] M0.01 Fresh git repo `verita-v2/` (clean history), `main` branch
- [x] M0.02 `.gitignore`, `.gitattributes` (LF normalization), `.editorconfig`
- [x] M0.03 `LICENSE` (MIT), `README.md` skeleton with generated-metrics markers, `CONTRIBUTING.md`
- [x] M0.04 `docs/adr/` with ADR-001…007 from PIVOT §9
- [x] M0.05 `configs/operations.yaml` (assumptions), `configs/data_manifest.yaml` (placeholder hashes)

**Backend skeleton**
- [x] M0.06 `backend/pyproject.toml` on Python 3.11, uv lockfile, extras `[dev]`
- [x] M0.07 Package layout `verita/{api,core,db,services,repositories,pipeline,ml,optimize,defend,llm}`
- [x] M0.08 Settings via pydantic-settings (`VERITA_*` env, `.env.example`), validated at startup
- [x] M0.09 Structured JSON logging (structlog) with request ID
- [x] M0.10 RFC 9457 problem+json error handling; no exception text leaks
- [x] M0.11 Security headers middleware (CSP, X-Content-Type-Options, Referrer-Policy, frame-ancestors)
- [x] M0.12 SQLAlchemy 2 engine/session, `users`, `sessions`, `audit_log` models
- [x] M0.13 Alembic configured; first migration creates M0 tables
- [x] M0.14 Password hashing (argon2id), login lockout after 5 failures
- [x] M0.15 Session cookie auth (httpOnly, Secure in prod, SameSite=Lax) + CSRF double-submit token
- [x] M0.16 Roles (analyst, mlro, validator, reviewer) + `require_role` dependency (default deny)
- [x] M0.17 Routes: `/api/v1/health/live`, `/health/ready`, `/auth/login`, `/auth/logout`, `/me`
- [x] M0.18 CLI (`verita`): `db upgrade`, `users create`, `users seed-demo`
- [x] M0.19 Task runner (poethepoet): `lint`, `fmt`, `typecheck`, `test`, `serve`, `migrate`

**Backend quality**
- [x] M0.20 ruff (lint + format) and mypy strict, both clean
- [x] M0.21 Tests: config, hashing, lockout, CSRF, role matrix, problem+json, health
- [~] M0.22 [!U3] Postgres integration test path (testcontainers) — written; skips locally (Docker off), runs in CI against a Postgres service

**Frontend skeleton**
- [x] M0.23 Vite + React 18 + TS strict (`noUncheckedIndexedAccess`), React Router lazy routes
- [x] M0.24 Design tokens (`tokens.css`, Paper + Night Ledger), base components: Button, Panel, Stamp, Field
- [x] M0.25 App shell (rail + top bar), Login page, placeholder routes, TanStack Query + API client with CSRF
- [x] M0.26 ESLint (strict, jsx-a11y, no inline styles, no `any`), Prettier, Stylelint (min font size), Vitest

**Delivery**
- [~] M0.27 [!U3] Dockerfiles (multi-stage, non-root, healthcheck) + `deploy/docker-compose.yml` — written, not yet built (Docker off)
- [~] M0.28 GitHub Actions CI: lint, types, tests, build, gitleaks, pip-audit, npm audit — all blocking — written, first run needs U4
- [ ] M0.29 [!U4] CI green on GitHub
- [x] M0.30 pre-commit hooks (ruff, prettier, gitleaks)

---

## M1 — Data foundation

Exit: real data ingested and validated; counts recorded; pattern linkage measured; leakage test exists.

- [x] M1.01 Synthetic fixture generator with all 8 typologies (for tests and before data arrives)
- [x] M1.02 Data contract (`configs/data_contract.yaml`) enforced in DuckDB over the raw text — 7 hard checks + facts. Deviation from plan: DuckDB checks instead of pandera, because they scale out of core to 5M+ rows
- [x] M1.03 `verita data verify`: presence + SHA-256 against `configs/data_manifest.yaml`
- [x] M1.04 Record real file hashes in the manifest — all 4 files recorded
- [x] M1.05 `verita data ingest`: CSV → typed Parquet with stable `txn_id` (file order) and `seq` (time order). Single file per dataset (partitioning unnecessary at this size)
- [x] M1.06 Patterns-file parser: collects every format problem (10 kinds tested) and fails together
- [x] M1.07 Pattern → transaction linker: strict (unmatched or legitimate match fails); HI-Small 3,209/3,209 and LI-Small 1,023/1,023 linked
- [x] M1.08 Node ids `bank:account` with numeric bank ids; currency + format enums in the contract
- [x] M1.09 `verita data graph`: accounts + account-day tables (label, typologies incl. UNATTRIBUTED). Alert candidates are scored account-days, built in M3.02
- [x] M1.10 Count-based temporal split train 60 / hpo 10 / calib 10 / test 20, stored as `seq` ranges in `splits.json`
- [ ] M1.11 Paper-matching split for baseline comparison — moved to M2.20 (needs the paper's exact split definition, read together with its baselines)
- [x] M1.12 Run manifest per stage (input/output hashes, git revision, config hash, duration, peak memory); not written if the stage fails
- [x] M1.13 `artifacts/<dataset>/data_validation.json` (files, contract, patterns, graph, splits, daily volume + sparse-tail rule)
- [x] M1.14 `DATA_CARD.md` generated from the reports (`verita data card`). License still marked TO CONFIRM (U7)
- [ ] M1.15 [!U7] 1% real-data sample for tests — blocked until the dataset license is confirmed (committing a sample redistributes data). CI uses the generated fixture meanwhile
- [x] M1.16 LI-Small through the same pipeline
- [x] M1.17 Performance recorded in manifests: HI-Small full run 36 s (ingest 16.3 s), peak 3.1 GB; LI-Small 38 s, peak 4.4 GB — targets were 15 min / 8 GB
- [x] M1.18 Tests: 63 new pipeline tests (contract violations, parser errors, linker edge cases, graph labels, split properties, card, manifests, CLI). Found and fixed 2 real bugs: last split overflowing on tiny inputs; empty typology lists stored as NULL

## M2 — Detect: models and evaluation

Exit: champion vs incumbent vs baselines with CIs; per-typology recall; ablations; sanity checks.

- [ ] M2.01 Feature framework with strict as-of semantics
- [ ] M2.02 Transaction features
- [ ] M2.03 Velocity windows (1h / 24h / 7d)
- [ ] M2.04 Fan-in / fan-out + amount concentration
- [ ] M2.05 Two-hop pass-through and gather-scatter features
- [ ] M2.06 Time-respecting cycle detection (≤5 hops, 7 days), numba CSR
- [ ] M2.07 Counterparty prior-alert-rate (past labels only)
- [ ] M2.08 Property test: perturbing future rows never changes features (leakage guard)
- [ ] M2.09 Rules-engine incumbent (6 rules)
- [ ] M2.10 LightGBM tabular baseline
- [ ] M2.11 LightGBM champion (+ graph features), Optuna HPO on HPO half only
- [ ] M2.12 Imbalance ablation (scale_pos_weight / focal / undersample)
- [ ] M2.13 5-seed champion runs, mean ± std
- [ ] M2.14 Typology head (multi-class)
- [ ] M2.15 Model registry table + artifact hashing
- [ ] M2.16 Eval: minority F1, PR-AUC, recall@P=0.5 with day-block bootstrap CIs
- [ ] M2.17 Eval: per-typology recall with CI and support
- [ ] M2.18 Eval: feature-group ablation table
- [ ] M2.19 Eval: label-shuffle and train-on-future sanity checks
- [ ] M2.20 `configs/baselines.yaml` with published numbers and citations
- [ ] M2.21 SHAP top-5 reasons → plain-English reason codes
- [ ] M2.22 Scoring latency and feature-build time benchmarks

## M3 — Detect: Queue and Investigation UX

Exit: screens pass axe and keyboard e2e; subgraph < 500ms.

- [ ] M3.01 `alerts`, `alert_reasons`, `dispositions` tables + migration
- [ ] M3.02 `poe score` writes alerts (account-day) for the test window
- [ ] M3.03 Evidence subgraph extraction (2 hops, ≤60 nodes, dominant path, motif edges)
- [ ] M3.04 Stable evidence IDs (`EV-…`)
- [ ] M3.05 API: `GET /alerts` (cursor pagination, filters)
- [ ] M3.06 API: `GET /alerts/{id}`, `GET /alerts/{id}/subgraph`
- [ ] M3.07 API: `POST /alerts/{id}/disposition` (reason code mandatory)
- [ ] M3.08 OpenAPI → generated TS types; Zod validation in dev
- [ ] M3.09 DataTable component (virtualized, sortable, keyboard)
- [ ] M3.10 Alert Queue screen + filters + saved views
- [ ] M3.11 Keyboard shortcuts (J/K/Enter/E/D/X/C) + `?` help
- [ ] M3.12 MoneyFlowGraph (Cytoscape, layered by time, dominant path, hover, expand hop)
- [ ] M3.13 Graph table alternative (accessible)
- [ ] M3.14 Investigation screen (summary, reasons, graph, synced timeline)
- [ ] M3.15 Loading / empty / error states for both screens
- [ ] M3.16 Playwright e2e: triage flow, keyboard-only
- [ ] M3.17 axe zero violations on both routes
- [ ] M3.18 Perf: subgraph p95 < 500ms; queue scroll 10k rows

## M4 — Decide: models and analysis

Exit: coverage report, forecast interval coverage, optimizer gap — all in metrics.json.

- [ ] M4.01 Isotonic calibration on calibration set
- [ ] M4.02 Reliability diagram, ECE, Brier (before / after, with CIs)
- [ ] M4.03 Split-conformal recall threshold (pooled)
- [ ] M4.04 Mondrian per-typology thresholds with pooled fallback (<50 positives)
- [ ] M4.05 Property tests: threshold monotone in α; exchangeable fixture achieves coverage
- [ ] M4.06 Replay engine (day-by-day test period, configurable label delay)
- [ ] M4.07 Static conformal empirical recall by month with CIs
- [ ] M4.08 Adaptive Conformal Inference online update; static vs ACI comparison
- [ ] M4.09 Label-delay sensitivity analysis
- [ ] M4.10 Daily alert-volume and review-minutes series
- [ ] M4.11 Forecast models: seasonal naive, ETS, LightGBM-lag, ensemble
- [ ] M4.12 Rolling-origin backtest: MASE, pinball, 80/95% interval coverage
- [ ] M4.13 Handling-time and cost model from `configs/operations.yaml`
- [ ] M4.14 ILP planner (OR-Tools CP-SAT) with recall-floor constraint
- [ ] M4.15 Greedy baseline + optimality gap
- [ ] M4.16 Infeasibility → "analysts needed to restore guarantee"
- [ ] M4.17 Frontier for 1–20 analysts
- [ ] M4.18 PSI + KS drift per feature and score, weekly
- [ ] M4.19 `capacity_plans` table + caching
- [ ] M4.20 APIs: `/capacity/frontier`, `/plan`, `/forecast`, `/coverage`

## M5 — Decide: Capacity Planner UX

Exit: slider < 150ms; every Stat has provenance.

- [ ] M5.01 Stat component with interval + "how computed" popover
- [ ] M5.02 Controls: analysts slider + numeric twin, α selector, date, guarantee mode
- [ ] M5.03 Headline row (guarantee status, expected recall, missed value, cost, reviewed)
- [ ] M5.04 Frontier chart with feasibility stamp
- [ ] M5.05 Forecast panel with bands + analysts-needed bars
- [ ] M5.06 Coverage panel (static vs ACI)
- [ ] M5.07 Assumptions drawer with AssumptionStamp, what-if edits
- [ ] M5.08 Save plan
- [ ] M5.09 Queue header shows today's plan
- [ ] M5.10 e2e + axe + chart table alternatives

## M6 — Defend: narratives, verifier, signing

Exit: verifier eval in metrics.json; tamper test passes in CLI.

- [ ] M6.01 `cases`, `case_alerts`, `case_evidence`, `narratives`, `verifications`, `case_events`, `signatures`, `jobs` tables
- [ ] M6.02 Append-only trigger on `case_events` + DB role without UPDATE/DELETE
- [ ] M6.03 Persisted hash chain on `case_events`
- [ ] M6.04 Case state machine with tests for every transition
- [ ] M6.05 Postgres SKIP LOCKED job queue + worker process
- [ ] M6.06 Narrative JSON schema (sentences with section + evidence IDs)
- [ ] M6.07 [!U5] LLM provider interface: Gemini primary, Groq fallback, timeouts, retries
- [ ] M6.08 Offline deterministic template generator
- [ ] M6.09 Prompt v1 + prompt hash recorded
- [ ] M6.10 Claim parsers (money, counts, dates, durations, accounts, banks, typologies, %)
- [ ] M6.11 Verifier: citation, claim-match, coverage rules
- [ ] M6.12 Golden tests on 30 fixed narratives
- [ ] M6.13 Fault injection (8 fault types)
- [ ] M6.14 Verifier eval: per-fault detection with CI, clean false-alarm rate
- [ ] M6.15 Raw LLM unsupported-claim rate on clean generations
- [ ] M6.16 RFC 8785 canonicalization
- [ ] M6.17 Merkle tree + property tests
- [ ] M6.18 Ed25519 signing, key ID, public key endpoint, key file handling
- [ ] M6.19 `verita-verify` offline CLI naming the changed leaf
- [ ] M6.20 Signed JSON export
- [ ] M6.21 PDF rendering (WeasyPrint) with root hash + key ID
- [ ] M6.22 APIs for cases (create, narrative, verify, submit, approve, return, export, verify-signature)

## M7 — Defend: Case File UX and maker-checker

Exit: full demo path e2e green.

- [ ] M7.01 Case File layout (evidence / narrative / verifier)
- [ ] M7.02 EvidenceChip + evidence previews
- [ ] M7.03 Inline narrative editing with re-verification
- [ ] M7.04 ClaimResult component + in-text highlights
- [ ] M7.05 Real job progress for narrative drafting
- [ ] M7.06 Inject-a-fault demo action
- [ ] M7.07 Maker-checker: approve disabled for author, with explanation
- [ ] M7.08 Seal animation on real sign event (+ reduced-motion fallback)
- [ ] M7.09 Export buttons + tampered-copy download (demo)
- [ ] M7.10 In-browser verification dropzone (WebCrypto Ed25519, WASM fallback)
- [ ] M7.11 Authorization matrix test for every route × role
- [ ] M7.12 e2e: full demo path

## M8 — Evidence Room, honesty, robustness

Exit: no hand-typed metric anywhere; Evidence Room complete.

- [ ] M8.01 `metrics.json` schema + writer
- [ ] M8.02 `poe eval` orchestrates all evaluations
- [ ] M8.03 Generated MODEL_CARD, DATA_CARD, EVAL_REPORT
- [ ] M8.04 README generated metrics block + CI diff check
- [ ] M8.05 CI scan for hand-typed metrics in docs and frontend
- [ ] M8.06 Evidence Room: Data tab
- [ ] M8.07 Evidence Room: Detect tab
- [ ] M8.08 Evidence Room: Decide tab
- [ ] M8.09 Evidence Room: Defend tab
- [ ] M8.10 Evidence Room: Lineage tab
- [ ] M8.11 LI-Small robustness results
- [ ] M8.12 SAML-D mapping + transfer results (optional)
- [ ] M8.13 GNN challenger (optional extra)
- [ ] M8.14 Landing page reading live metrics + guided tour

## M9 — Harden and ship

Exit: every PIVOT §23 rubric check passes.

- [ ] M9.01 Rate limiting (per user + per IP)
- [ ] M9.02 schemathesis contract fuzzing — zero 500s
- [ ] M9.03 k6 on queue / subgraph / plan — p95 < 300ms at 50 VUs
- [ ] M9.04 Lighthouse CI budgets (LCP, INP, bundle)
- [ ] M9.05 ZAP baseline scan
- [ ] M9.06 SBOM (syft) + vulnerability scan (grype)
- [ ] M9.07 Prometheus metrics + provisioned Grafana dashboard
- [ ] M9.08 OpenTelemetry tracing
- [ ] M9.09 THREAT_MODEL.md
- [ ] M9.10 RUNBOOK.md (pipeline, key rotation, recovery)
- [ ] M9.11 ADR-008 demo host decision
- [ ] M9.12 Demo pack export + manifest verification on startup
- [ ] M9.13 Deploy (API, worker, Postgres, frontend) — must be same-origin (SPA + /api on one host) because session cookies are SameSite=Lax
- [ ] M9.14 Release workflow on tags
- [ ] M9.15 DEMO_SCRIPT.md + rehearsal recording
- [ ] M9.16 Final rubric review against PIVOT §23

---

## Change log

| Date | Change |
|------|--------|
| 2026-10-19 | Tracker created; decisions recorded in PIVOT §26 |
| 2026-10-19 | M1 complete except M1.11/M1.15. Real data: both datasets pass the contract; 100% of pattern rows link. HI-Small splits — train 3,047,007 (2,298 laundering, 0.075%), hpo 507,835 (558), calib 507,834 (524), test 1,015,669 (1,797, 0.177%). Note the **label shift**: the test laundering rate is 2.3× train (the sparse tail falls in test); M2 must report it and evaluate the bulk and the tail separately. Backend: 120 tests, 99.3% coverage, ruff + mypy strict + bandit + pip-audit clean. |
| 2026-10-19 | Patterns files received (370 HI-Small / 117 LI-Small attempts, all 8 typologies). Prototype linker: 100% of pattern rows (3,209 / 1,023) match exactly one transaction, none labelled legitimate. **Coverage finding:** only 62.0% of HI-Small and 28.7% of LI-Small laundering transactions belong to a typology block; the rest are laundering without a typology. Consequences: per-typology metrics cover the attributed share only and are reported with that denominator; an `UNATTRIBUTED` group is added for per-typology (Mondrian) conformal thresholds; headline detection metrics use all laundering labels. |
| 2026-10-19 | Real data profiled. HI-Small: 5,078,345 txns, 5,177 laundering (0.102%). LI-Small: 6,924,049 txns, 3,565 laundering (0.051%). Currencies and payment formats match the data contract exactly. **Time span finding:** bulk traffic covers only 2022-09-01 → 09-10; 09-11 → 09-18 is a sparse tail that is mostly laundering (e.g. HI-Small 09-11: 396 txns, 232 laundering). Consequences: splits must be by transaction count, not by time span (a time-span split would put the test set in the degenerate tail); Decide must use hourly granularity (≈240 points) instead of daily/monthly. PIVOT §4.4 and §7 to be updated. |
| 2026-10-19 | M1 started: `configs/datasets.yaml`, `configs/data_contract.yaml`, `pipeline/config.py`, `pipeline/manifest.py`, `pipeline/fixture.py` written. Fixture generates 30.6k IBM-format rows, 96 patterns across all 8 typologies. Open: 11 ruff findings in `verita/pipeline`, no tests yet; ingest/patterns/graph/splits/data card not started. Risk to verify on real data: HI-Small may span only ~2–3 weeks, which would force hourly granularity in Decide. |
| 2026-10-19 | M0 built. Backend: 57 tests, 99.4% coverage, ruff + mypy strict clean, bandit + pip-audit clean. Frontend: 101 tests, 98% line coverage, ESLint strict + Stylelint token rules + Prettier + tsc clean; initial JS 117 KB gzip. Real-server smoke test passed (migrate → seed → login → /me). Contrast test caught and fixed 3 AAA failures in the paper theme. |
