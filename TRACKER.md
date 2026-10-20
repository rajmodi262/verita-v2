# Verita v2 — Task Tracker

> Single source of truth for progress. Updated in the same commit as the work it tracks.
> Plan: [PIVOT.md](PIVOT.md). Legend: `[ ]` todo · `[~]` in progress · `[x]` done ·
> `[!]` blocked (needs you) · `[-]` dropped (with reason).

## Status at a glance

| Milestone | Scope | Done / Total | State |
|-----------|-------|--------------|-------|
| M0 | Reset: repo, tooling, CI, auth skeleton | 30 / 30 | Done |
| M1 | Data foundation | 17 / 18 | M1.15 needs license (U7) |
| M2 | Detect — models and evaluation | 21 / 22 | M2.07 dropped (needs a label-delay model) |
| M3 | Detect — Queue and Investigation UX | 18 / 18 | Done |
| M4 | Decide — calibration, conformal, forecast, optimizer, drift | 20 / 20 | Done |
| M5 | Decide — Capacity Planner UX | 10 / 10 | Done |
| M6 | Defend — narratives, verifier, signing, ledger | 22 / 22 | Done |
| M7 | Defend — Case File UX and maker-checker | 12 / 12 | Done |
| M8 | Evidence Room, honesty pipeline, robustness | 13 / 14 | SAML-D optional, needs the dataset |
| M9 | Harden and ship | 14 / 16 | Going live needs a VM + domain (U8); rehearsal recording (U9) |
| M10 | Regulatory fit (PLAN_10 phase 2) | 1 / 6 | In progress |

## Blocked on you

| ID | What I need | Unblocks |
|----|-------------|----------|
| U1 | Rotate the Groq key in v1's `START_BACKEND.bat`. Separately, the Windows environment still sets an older `GROQ_API_KEY` (neither the v1 key nor the new one): remove it. v2 reads the `VERITA_*_API_KEYS` pools, so it no longer interferes | Security hygiene |
| U7 | Confirm the IBM AML dataset license on its Kaggle page (I'll record it in `configs/datasets.yaml`) | M1.15, publishing DATA_CARD |
| U8 | A small VM (2 vCPU, 4 GB) and a domain for the public demo; then `deploy/prod/` per ADR-008 | M9.13 going live |
| U9 | Record the demo rehearsal following `docs/DEMO_SCRIPT.md` | M9.15 |
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
- [x] M0.22 Postgres integration tests (testcontainers): migrations, append-only trigger, SKIP LOCKED job claims, least-privilege app role — run locally against Docker and in CI

**Frontend skeleton**
- [x] M0.23 Vite + React 18 + TS strict (`noUncheckedIndexedAccess`), React Router lazy routes
- [x] M0.24 Design tokens (`tokens.css`, Paper + Night Ledger), base components: Button, Panel, Stamp, Field
- [x] M0.25 App shell (rail + top bar), Login page, placeholder routes, TanStack Query + API client with CSRF
- [x] M0.26 ESLint (strict, jsx-a11y, no inline styles, no `any`), Prettier, Stylelint (min font size), Vitest

**Delivery**
- [x] M0.27 Dockerfiles (multi-stage, non-root, read-only root, healthcheck) + `deploy/docker-compose.yml` — built, smoke-tested end to end on Postgres
- [x] M0.28 GitHub Actions CI: lint, types, tests, build, gitleaks, pip-audit, npm audit — all blocking
- [x] M0.29 CI green on GitHub (public repo rajmodi262/verita-v2). The first runs found four issues, all fixed: an order-sensitive leakage property test (row order, not leakage), frontend branch coverage at 79%, gitleaks-action failing on a first push, six bandit findings
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
- [x] M1.11 Paper split confirmed (arXiv:2306.16424v3 §4): 60/20/20 temporal split of timestamp-ordered transaction indices — identical to ours for train and test, so no second split is needed
- [x] M1.12 Run manifest per stage (input/output hashes, git revision, config hash, duration, peak memory); not written if the stage fails
- [x] M1.13 `artifacts/<dataset>/data_validation.json` (files, contract, patterns, graph, splits, daily volume + sparse-tail rule)
- [x] M1.14 `DATA_CARD.md` generated from the reports (`verita data card`). License still marked TO CONFIRM (U7)
- [ ] M1.15 [!U7] 1% real-data sample for tests — blocked until the dataset license is confirmed (committing a sample redistributes data). CI uses the generated fixture meanwhile
- [x] M1.16 LI-Small through the same pipeline
- [x] M1.17 Performance recorded in manifests: HI-Small full run 36 s (ingest 16.3 s), peak 3.1 GB; LI-Small 38 s, peak 4.4 GB — targets were 15 min / 8 GB
- [x] M1.18 Tests: 63 new pipeline tests (contract violations, parser errors, linker edge cases, graph labels, split properties, card, manifests, CLI). Found and fixed 2 real bugs: last split overflowing on tiny inputs; empty typology lists stored as NULL

## M2 — Detect: models and evaluation

Exit: champion vs incumbent vs baselines with CIs; per-typology recall; ablations; sanity checks.

**HI-Small result (test = last 20% of transactions, 1,797 laundering):** champion minority-class
F1 **0.503** (6-h block-bootstrap 95% CI 0.440–0.591), PR-AUC 0.494, precision 0.638, recall
0.415; rules incumbent F1 0.003; transaction-only LightGBM 0.255. Five seeds: 0.509 ± 0.005.
Paper (Altman et al. 2023, Table 2, same 60/20/20 temporal index split): GFP+LightGBM 62.86 ± 0.25,
PNA 56.77, GIN+EU 47.73 — we sit between GIN+EU and PNA, below GFP. Bulk days F1 0.385, sparse
tail 0.718 (label shift: test rate 2.3× train).

- [x] M2.01 Feature framework with strict as-of semantics (window frames end 1 minute before the row)
- [x] M2.02 Transaction features
- [x] M2.03 Velocity windows (1h / 24h / 7d)
- [x] M2.04 Fan-in / fan-out + amount concentration
- [x] M2.05 Two-hop pass-through and gather-scatter features
- [x] M2.06 Time-respecting cycle detection, numba CSR — ≤4 edges (not 5: the 5-edge search hit the expansion cap on hubs), 7 days. Fires on 6.8% of laundering vs 0.08% of legitimate; finds 34/54 labelled CYCLE closings
- [-] M2.07 Counterparty prior-alert-rate — **dropped**: honest only with a label-delay model (labels arrive weeks late); without one it leaks future labels. Recorded as a known gap
- [x] M2.08 Hypothesis property test: perturbing future rows never changes features
- [x] M2.09 Rules-engine incumbent (6 rules)
- [x] M2.10 LightGBM tabular baseline (transaction features only)
- [x] M2.11 LightGBM champion, Optuna 40 trials on the hpo split only (hpo F1 0.494)
- [x] M2.12 Imbalance ablation: 20% negative subsample (pre-registered default) 0.503, all data unweighted **0.543**, scale_pos_weight 0.039. Focal loss not run. The unweighted variant beat the default on test; we do **not** switch on a test result — a re-selection on hpo is queued (M8)
- [x] M2.13 5-seed champion runs: F1 0.509 ± 0.005, PR-AUC 0.503
- [x] M2.14 Typology head: accuracy 0.530 vs 0.255 majority class, macro-F1 0.363
- [x] M2.15 Model registry (`registry.json` + `model_versions` table) with artifact SHA-256
- [x] M2.16 Eval: minority F1, PR-AUC, precision/recall with 6-h block-bootstrap CIs
- [x] M2.17 Per-typology recall with Wilson CI and support (FAN-IN/OUT, GATHER/SCATTER ≈0.65; STACK/RANDOM/BIPARTITE ≈0.30; UNATTRIBUTED 0.007)
- [x] M2.18 Feature-group ablation with paired bootstrap deltas: transaction −0.355, fan −0.095, velocity −0.031 (CI crosses 0), cycle −0.017, recency −0.007 (crosses 0)
- [x] M2.19 Sanity: label-shuffle PR-AUC 0.0021 vs base rate 0.0018 (collapses as it should); random split F1 0.507 vs temporal 0.503
- [x] M2.20 `configs/baselines.yaml`: paper Table 2 (minority F1) for HI-Small and LI-Small, with split and feature comparability notes
- [x] M2.21 SHAP (`pred_contrib`) top-5 reasons → templated plain-English reason codes for all 44 features
- [x] M2.22 Benchmarks: features for 5.08M rows 68 s; scoring 75 ms per 10k rows; full train/eval 91 min

## M3 — Detect: Queue and Investigation UX

Exit: screens pass axe and keyboard e2e; subgraph < 500ms.

- [x] M3.01 `alerts`, `alert_reasons`, `dispositions` tables + migration 0002
- [x] M3.02 `verita detect alerts` writes account-day alerts for the test window (HI-Small: 194,854 alerts, 2,807 truly laundering; floor keeps 99% of hpo positives)
- [x] M3.03 Evidence subgraph (2 hops, ≤60 nodes, ≤200 edges, dominant path reserved inside the caps, motif signals)
- [x] M3.04 Stable evidence IDs (`EV-TXN-`, `EV-PATH-`, `EV-REASON-`, `EV-MOTIF-`)
- [x] M3.05 API: `GET /alerts` (keyset cursor, filters)
- [x] M3.06 API: `GET /alerts/{id}`, `GET /alerts/{id}/subgraph`
- [x] M3.07 API: `POST /alerts/{id}/disposition` (reason code mandatory, audited)
- [x] M3.08 OpenAPI → generated TS types; Zod schemas checked against them at compile time
- [x] M3.09 Queue table — **changed**: keyset paging ("load the next 100") instead of a virtualized grid; virtualization needs inline positioning styles, which the no-inline-style rule forbids, and paging keeps the DOM small
- [x] M3.10 Alert Queue screen + filters in the URL (shareable views; no server-side saved views)
- [x] M3.11 Keyboard shortcuts J/K/Enter/E/D + `?` help (X select and C add-to-case arrive with cases in M7)
- [x] M3.12 MoneyFlowGraph (Cytoscape, lazy chunk, time layout, dominant path); expand-a-hop not built
- [x] M3.13 Graph table alternative (accessible)
- [x] M3.14 Investigation screen (summary, reasons with evidence IDs, graph/table, dominant path)
- [x] M3.15 Loading / empty / error states for both screens
- [x] M3.16 Playwright on the real stack (fixture dataset prepared by `backend/scripts/e2e_prepare.py`, 18 tests, CI job `e2e`): keyboard-only triage (J/K/Enter/D, `?` map)
- [x] M3.17 axe (WCAG 2.2 A/AA) zero violations on every route, paper and night themes; skip link; phone width without sideways scroll (found and fixed: wide tables overflowed 148–192 px on /cases and /evidence-room)
- [x] M3.18 Perf (`verita bench`, 200 random real alerts): subgraph p50 180 ms, **p95 257 ms** (target 500). First version measured p95 4.1 s — hubs with 10⁵ weekly payments were materialised row by row; neighbourhood ranking now runs inside DuckDB

## M4 — Decide: models and analysis

Exit: coverage report, forecast interval coverage, optimizer gap — all in metrics.json.

The unit is the alert (account-day). Granularity is **hourly/daily** because the data has ~10
bulk days (see M1 findings) — "by month" in PIVOT §7 became "by day".

- [x] M4.01 Isotonic calibration on the calib split
- [x] M4.02 Reliability (equal-mass bins, Wilson CIs), ECE, Brier: ECE 0.0116 → **0.0020** on test
- [x] M4.03 Split-conformal recall threshold (pooled), k = ⌊α(n+1)⌋ over 832 calib positives
- [x] M4.04 Mondrian per-typology thresholds; 5 of 9 groups fall back to pooled (<50 positives)
- [x] M4.05 Property tests: threshold monotone in α (hypothesis); exchangeable simulation achieves 1−α ≤ coverage ≤ 1−α+1/(n+1)
- [x] M4.06 Replay engine, hour by hour, configurable label delay
- [x] M4.07 Static conformal realised recall by day with Wilson CIs: α=0.05 → **98.4%** (97.8–98.8), reviewing 134,186 of 565,705 account-days
- [x] M4.08 ACI (γ=0.005): α=0.05 → **96.4%** (95.6–97.0) while reviewing **10.2% fewer** (120,457). Both hold at every α ∈ {0.01, 0.05, 0.10, 0.20}
- [x] M4.09 Label-delay sensitivity (6/24/48 h): 96.3% / 96.4% / 97.1%
- [x] M4.10 Hourly workload series (alerts clearing the α=0.05 threshold)
- [x] M4.11 Forecast models: seasonal naive, ETS, LightGBM quantile, ensemble
- [x] M4.12 Rolling origin every 6 h, 24 h horizon, 40 origins: MASE ETS 1.77 / LGBM 1.85 / ensemble 2.14 / naive 2.92. **Intervals under-cover:** ensemble 95% band covers 67% (ETS 83%) — reported as is; the series is short and the label-shift tail breaks the season
- [x] M4.13 Handling-time and cost model from `configs/operations.yaml` (assumptions, marked in UI)
- [x] M4.14 Exact 0/1 knapsack with OR-Tools CP-SAT + recall-floor constraint, on a candidate pool (forced + 5× the capacity in value density); objective = expected **cases** (default) or expected **USD**
- [x] M4.15 Greedy baseline + optimality gap (CP-SAT beats greedy by 0.04% on 2022-09-09). Bug found: minutes rounded up to integers let greedy win; solver now counts tenths of a minute
- [x] M4.16 Infeasibility → analysts needed: the 95% guarantee needs 401 / 3,139 / 882 analysts on the three bulk days; feasible with ≤14 on the tail days
- [x] M4.17 Frontier for 1–20 analysts × 4 α × 2 modes × 2 objectives, with a replay backtest per point (e.g. 09-08, 6 analysts: expected 33.4%, realised 25.8%)
- [x] M4.18 PSI + KS per feature and on the score, per day. Time-anchored features (account age, time since last activity) excluded — they grow with the calendar by construction (r_age_min showed PSI 4–9 for that reason alone)
- [x] M4.19 `capacity_plans` table (migration 0003), MLRO-only save, audited; per-day alert frames cached per model version
- [x] M4.20 APIs: meta, staffing, frontier, plan (what-if overrides), plans, forecast, coverage, calibration, drift — all with typed response models. Plan latency: warm p95 243 ms, cold (first load of a 140k-alert day) max 891 ms

## M5 — Decide: Capacity Planner UX

Exit: slider < 150ms; every Stat has provenance.

- [x] M5.01 `Stat` with interval + native-`<details>` "How computed" (formula, API field, caveat)
- [x] M5.02 Controls: analysts slider + numeric twin, α, replay day, guarantee mode, objective — all in the URL
- [x] M5.03 Headline row (guarantee status, expected recall, cases caught, missed value, cost, reviewed) + replay check against true labels
- [x] M5.04 Frontier chart (hand-written SVG) with feasibility marker / "needs N analysts" stamp
- [x] M5.05 Forecast panel (out-of-sample bands, 80/95%) + analysts-needed bars (log scale)
- [x] M5.06 Coverage panel (static vs ACI by day, with CIs) + calibration line
- [x] M5.07 Assumptions drawer with AssumptionStamp and what-if edits (never saved)
- [x] M5.08 Save plan (MLRO only; disabled with an explanation otherwise)
- [x] M5.09 Queue header shows the filtered day's saved plan
- [x] M5.10 Chart table alternatives done for all 4 charts; e2e: slider updates the headline in < 150 ms (measured in the browser), every Stat's provenance opens, plan save shows in the queue; axe clean. Slider answers instantly from the precomputed frontier (no request); the exact plan follows after a 300 ms debounce. **Charts:** hand-written SVG instead of ECharts — token theming, no canvas, testable; Capacity route 10 KB gzip

## M6 — Defend: narratives, verifier, signing

Exit: verifier eval in metrics.json; tamper test passes in CLI.

**Verifier evaluation (HI-Small, 300 test-window cases, 13,142 claims checked on clean
narratives):** false alarms **0 / 300** (95% CI 0–1.3%); planted faults detected **2,437 / 2,438
(99.96%, CI 99.77–99.99%)**, every detection localised to the faulty sentence. The one miss is a
real limitation: claims are matched by *value*, not by *role* — a hop amount scaled ×1.8 happened
to equal the path's two-hop total, a true fact the sentence cited. wrong_typology was plantable in
only 40 cases (260 of the 300 are UNATTRIBUTED).

- [x] M6.01 `cases`, `case_alerts`, `case_evidence`, `narratives`, `verifications`, `case_events`, `signatures`, `jobs` tables (migration 0004)
- [x] M6.02 Append-only triggers on `case_events` for PostgreSQL and SQLite (UPDATE/DELETE rejected, tested), plus the `verita_app` login role: owns nothing, SELECT/INSERT only on the ledger, audit log and signatures (`verita db app-role`; tested: UPDATE, DELETE, TRUNCATE, DISABLE/DROP TRIGGER all refused)
- [x] M6.03 Persisted hash chain; `verify_chain` names the first broken, missing or relinked event
- [x] M6.04 State machine draft → verified → submitted → signed, returned, closed; every transition and the 409s tested end to end
- [x] M6.05 Job queue: `FOR UPDATE SKIP LOCKED` claim (atomic UPDATE on SQLite), 3 attempts, work rolled back on failure; `verita worker`; inline mode for dev. PostgreSQL path runs in CI (U3)
- [x] M6.06 Narrative JSON schema (section / text / evidence_ids), free prose rejected
- [x] M6.07 Provider interface: Gemini (key in header, temperature 0, JSON mode) → Groq (JSON mode) → offline; retries; unit-tested with mocked HTTP. **Live run waits on U5** — and see U1: a `GROQ_API_KEY` is set in this machine's environment (possibly the leaked v1 key); the API is launched with providers off and the eval calls an LLM only with `--llm`
- [x] M6.08 Offline deterministic template (section-ordered, pluralised, 8-decimal small amounts)
- [x] M6.09 `prompts/narrative_v1.md`; its SHA-256 is recorded on every narrative and ledger event
- [x] M6.10 Claim parsers: amounts (symbols, codes, names, k/m/bn, rounding resolution), counts, dates (ISO / D Month Y / Month D, Y), **date ranges**, durations, accounts, banks, typologies, percentages
- [x] M6.11 Verifier: citation, claim-match against *cited* evidence only, coverage (path, total, range, typology / unattributed)
- [x] M6.12 Golden snapshot of verdicts on 30 fixed narratives (`tests/defend/golden/verifier_30.json`)
- [x] M6.13 Fault injection: 9 types (the 8 planned + irrelevant citation, chosen to support none of the claims)
- [x] M6.14 Eval with Wilson CIs, localisation and verbatim misses → `artifacts/<ds>/defend/verifier_eval.json`. **Bugs it found:** evidence rounded Bitcoin amounts to 2 decimals (0.0034 → 0.00); a range start inside the range passed (date_range claims added)
- [x] M6.15 Raw LLM unsupported-claim rate — measured on HI-Small through the key pools (`verita defend eval --llm`); the artifact names the model that wrote each draft and why failed attempts failed. This run is Groq only (Gemini's daily quotas were spent); re-run after the reset for a Gemini sample
- [x] M6.16 RFC 8785 canonicalisation (RFC §3.2.2 vector, every double bit pattern round-trips, UTF-16 key order, exact-double integer rule)
- [x] M6.17 RFC 6962 Merkle tree with domain separation; audit-path property tests
- [x] M6.18 Ed25519 signing over `verita-case-v1:<case>:<root>`, key ID = SHA-256(raw key)[:16], `GET /keys` (public), key created on first use in dev (`keys/`, private key git-ignored)
- [x] M6.19 `verita-verify` offline CLI naming the changed leaf (exit 0 valid / 1 invalid / 2 unreadable)
- [x] M6.20 Signed JSON export (canonical bytes, embedded public key and instructions) + tampered demo copy
- [x] M6.21 PDF rendering — **fpdf2 instead of WeasyPrint** (no GTK/Pango system libraries; the PDF is a view, the JSON is the proof)
- [x] M6.22 Case APIs (create, narrative, edit, verify, submit, approve, return, close, export ×3, verify-signature, jobs, keys), typed response models

## M7 — Defend: Case File UX and maker-checker

Exit: full demo path e2e green.

**Live run on HI-Small (2026-10-20):** analyst opened C-1 from alert 19737 → offline draft, 43
claims verified → injected fault (18,888.26 → 19,454.91) highlighted, submit blocked → redraft →
submit → MLRO approved and signed (37 leaves) → the browser dropzone and `verita-verify` both
say VALID for the export and INVALID naming `EV-TXN-1892582` for the tampered copy.

- [x] M7.01 Case File layout (evidence / narrative / verifier), state stamp, ledger panel
- [x] M7.02 Evidence chips on every sentence; selecting one previews the item's payload (a key–value view, not a mini graph)
- [x] M7.03 Editing with re-verification on save (per-sentence form rather than in-text editing)
- [x] M7.04 Claim results per sentence; failing claims highlighted in the text (`<mark>` + screen-reader text)
- [x] M7.05 Real job progress (polls `GET /jobs/{id}`)
- [x] M7.06 Inject-a-fault demo action (+3% on one amount, saved as an edit)
- [x] M7.07 Maker-checker: approve disabled for the case's creator and submitter, with the reason shown
- [x] M7.08 Seal stamp-in on a real signature; reduced-motion falls back to a fade
- [x] M7.09 Export buttons (JSON, PDF) + tampered-copy download
- [x] M7.10 In-browser verification (WebCrypto Ed25519, native JCS) — agrees with Python on the root, every leaf and the signature (fixtures signed by `backend/scripts/make_case_export_fixture.py`). No WASM fallback: Ed25519 WebCrypto ships in current Chrome, Firefox and Safari
- [x] M7.11 Authorization matrix: every OpenAPI route × 4 roles + anonymous, CSRF on every mutation; a route without a policy fails the test
- [x] M7.12 e2e full demo path: alert → case → fault caught and submission blocked → submit → MLRO signs → signed export valid / tampered copy invalid in the browser; maker-checker block

## M8 — Evidence Room, honesty, robustness

Exit: no hand-typed metric anywhere; Evidence Room complete.

- [x] M8.01 `reports/metrics.json` (schema 1): every headline figure with interval, n, split and source artifact; per-dataset data/detect/decide/defend/lineage sections
- [x] M8.02 `uv run poe eval [--dataset …]`: features → train → alerts → decide → verifier eval → bench → reports
- [x] M8.03 MODEL_CARD.md and reports/EVAL_REPORT.md rendered from metrics.json (DATA_CARD from M1)
- [x] M8.04 README block between markers; `verita report check` in CI fails on drift
- [x] M8.05 `verita report scan` in CI (metric word + result-like number outside generated regions; confidence levels and targets allowed; TRACKER/PIVOT exempt by name)
- [x] M8.06 Evidence Room: Data tab (contract, splits, typology coverage, file hashes, limitations)
- [x] M8.07 Detect tab (models vs published baselines, per-typology recall bars with CIs, ablations, sanity checks)
- [x] M8.08 Decide tab (reliability diagram, coverage by day and by α, forecast backtest, drift, latency)
- [x] M8.09 Defend tab (detection by fault type, false alarms, misses verbatim, LLM status)
- [x] M8.10 Lineage tab (stage manifests: git revision, config hash, durations, output hashes); every figure has a caption, a table and a JSON download; metrics.json SHA-256 in the footer
- [x] M8.11 LI-Small robustness results — full `poe eval --dataset li_small`; in metrics.json, the README robustness row and EVAL_REPORT
- [ ] M8.12 SAML-D mapping + transfer results (optional)
- [-] M8.13 GNN challenger — dropped: the published GIN/PNA results on the same split are reported as baselines instead; a GNN would add compute without changing a decision in the product
- [x] M8.14 Landing page reads the public `/evidence-room/headline` (figure, CI, dataset, source, commit, file hash); 8-step skippable reviewer tour

## M9 — Harden and ship

Exit: every PIVOT §23 rubric check passes.

- [x] M9.01 Rate limiting: per IP, per IP on login, per session on mutations; 429 + Retry-After; configurable for load tests
- [x] M9.02 schemathesis contract fuzzing on a populated stack — zero 5xx over every operation (found: path IDs > 32 bits crashed the driver; fixed)
- [x] M9.03 k6 on queue / subgraph / plan against the Docker stack — 50 analysts within budget, plus a no-think-time stress run; results in `perf/results/` → metrics.json (found: OOM under load; fixed)
- [x] M9.04 Lighthouse CI budgets on the production bundle (scores, LCP, TBT as the lab proxy for INP, CLS, bytes) + gzip bundle check, both in CI (found: two CSP violations, robots.txt served as HTML, landing page lazy-loaded; fixed)
- [x] M9.05 ZAP baseline — 0 failures; report in `reports/security/` (found: headers dropped in nginx locations, missing COEP/CORP; fixed)
- [x] M9.06 CycloneDX SBOMs (syft) + grype gate on fixable High/Critical in CI and release; unfixable Debian findings recorded as SE-3
- [x] M9.07 Prometheus metrics by route template (multiprocess-safe, optional bearer token, 404 on the public origin) + provisioned Grafana dashboard
- [x] M9.08 OpenTelemetry tracing (OTLP/HTTP) when an endpoint is configured; trace IDs in logs
- [x] M9.09 THREAT_MODEL.md (STRIDE per trust boundary, each control tied to its test; residual risks)
- [x] M9.10 RUNBOOK.md (pipeline, start/observe, key rotation, recovery table, backups, alerts)
- [x] M9.11 ADR-008: one VM running the compose stack behind Caddy, same origin
- [x] M9.12 Demo pack export (`verita demo pack|verify|load`) + SHA-256 manifest verified at API startup
- [~] M9.13 Deploy config done (`deploy/prod/`: released images, Caddy HTTPS, same origin, least-privilege DB role; nginx re-resolves the API so restarts self-heal). Going live needs a VM and a domain (U8)
- [x] M9.14 Release workflow on `v*.*.*` tags: GHCR images, SBOMs + grype gate, Python dist with `verita-verify`, GitHub release; demo pack attached by `deploy/prod/release-pack.sh`. First run needs the GitHub repo (U4)
- [~] M9.15 DEMO_SCRIPT.md written and checked against the UI and the e2e suite. Rehearsal recording: yours (U9)
- [x] M9.16 Rubric review against PIVOT §23 — see the table below

### M9.16 — Rubric review (PIVOT §23), 2026-10-20

| Dimension | Check | Result |
|---|---|---|
| Backend architecture | routers → services → repositories; mypy strict; silent excepts | mypy clean (88 files); 0 `except …: pass`; ADR-001…008; migrations 0001–0004 |
| Security | threat model, authz matrix, append-only signed ledger, no user SQL, scanners blocking, no secrets | THREAT_MODEL; matrix over every route × role; trigger + least-privilege role; bandit, pip-audit, npm audit, gitleaks, grype blocking; ZAP 0 failures |
| ML rigor | temporal splits, leakage tests, baselines, CIs, ablations, per-typology, robustness | EVAL_REPORT generated; LI-Small robustness in |
| Statistics | calibration, conformal coverage over time with ACI, forecast coverage, bootstrap CIs | Evidence Room Decide tab |
| GenAI / NLP | structured output, deterministic verifier, fault-injection eval, raw hallucination rate | Evidence Room Defend tab, including the raw LLM rate, who wrote the drafts and failed attempts |
| Frontend engineering | lazy routes, generated API types, zero `any`, no inline styles, bundle budgets | 0 `any`, 0 inline styles (ESLint-enforced); bundle check + Lighthouse in CI; landing bundled on purpose |
| UX / accessibility | 6 screens, keyboard-first, axe zero, AAA contrast, ≥ 12 px, responsive, tour | 18 Playwright tests incl. axe in both themes, keyboard triage, phone width; Lighthouse accessibility 1.0 |
| Tests | ≥ 90% backend coverage; property, golden, contract, authz, e2e, perf | 90.6% backend; hypothesis, golden case files, schemathesis, authz matrix, Playwright, k6 |
| DevOps / CI | one deploy path, non-root pinned images, SBOM + scan, health/readiness, release automation, k6 | compose stack = deploy path; CI green on GitHub (incl. grype gate, Lighthouse); release workflow; k6 against the Docker stack |
| Honesty | every metric generated; CI check; limitations up front | `report check` + `report scan` pass; DEMO_SCRIPT quotes no numbers |
| Repo hygiene | clean tree, conventional commits, CHANGELOG, LICENSE, CONTRIBUTING | all present; CHANGELOG added |

Open gaps, all outside the code: the dataset licence (U7), a VM and domain (U8), the recording (U9).

---

## M10 — Regulatory fit (PLAN_10.md phase 2)

Exit: a signed case can be filed (goAML), personal data has retention and role masking, and no
model reaches the queue without independent review.

- [x] M10.01 Model governance: lifecycle (candidate → approved → champion), policy gates in `configs/model_policy.yaml`, generated validation report with SHA-256, validator approves, a different MLRO promotes, DB check forbids an unreviewed champion, visible bypass for dev/demo. Found while building it: mutating routes validated the request body before checking the role (422 leaked the input shape to forbidden callers) — every mutating route now authorizes first; the drift gate needed a volume floor (tail days of 11–396 rows made every feature "drift")
- [ ] M10.02 PII masking by role + retention policy and purge job (legal hold on open cases)
- [ ] M10.03 Regulator audit bundle: every event for a case in one signed export
- [ ] M10.04 goAML XML export of a signed case, validated against the official XSD
- [ ] M10.05 DPIA document; erasure vs append-only ledger (crypto-shredding)
- [ ] M10.06 Disposition feedback into the next training run (with leakage guards)

---

## Change log

| Date | Change |
|------|--------|
| 2026-10-20 | `docs/DEFEND_IT.md`: 40 panel questions (leakage, temporal splits, conformal/ACI, CP-SAT, JCS/Merkle/Ed25519, verifier limits, governance, LightGBM, bank scale), each answered with the file:line where it lives; no hand-typed figures, results point to the Evidence Room. |
| 2026-10-20 | M10.01 model governance (validate → approve → promote, separation of duties, DB-enforced). The real HI-Small champion passes all seven gates; three features show major drift on bulk days, one of them the model's own score. |
| 2026-10-20 | LLM key pools (priority order, instant failover on exhausted quota, cooldowns from the provider's retry time, `verita llm keys`) and the raw LLM evaluation. **Found by running on the real keys:** both default models were unusable (gemini-2.5-flash closed to new projects, Groq retired llama-3.3-70b); one Gemini key's project is denied access; every Groq request exceeded its 8,000-tokens/minute limit (prompt + reserved output), fixed with compact evidence and an output cap; the eval mislabelled Groq failures as quota (now per provider). Raw drafts: few pass the verifier as written, which is the verifier's purpose. |
| 2026-10-20 | M9 hardening: rate limits, schemathesis (zero 5xx), k6 load + stress against the Docker stack, Prometheus/Grafana, OpenTelemetry, ZAP (0 failures), SBOM + grype gate, Lighthouse + bundle budgets, least-privilege DB role, release workflow, prod deploy config, THREAT_MODEL / RUNBOOK / DEMO_SCRIPT / ADR-008. **Bugs found by running it for real:** OOM under concurrent load; a commit-after-response race on Postgres; 64-bit path IDs crashing the driver; nginx dropping security headers and caching the API's IP (a recreated API broke the site); ledger appends locking a row the app role may not lock (and not covering a case's first event); two CSP violations on the landing page; 22 Critical OS findings in the web image (now 0 High/Critical). Backend 90.6% coverage; frontend 160 unit + 18 e2e tests. |
| 2026-10-20 | M8 honesty pipeline, Evidence Room, live landing page, reviewer tour; Playwright suite (18 tests: demo path, keyboard triage, axe on every route in both themes, slider < 150 ms, phone width) green on a fresh fixture stack and wired into CI. Found and fixed: tables overflowing phone screens; report docs rendered from unsorted data (check/build mismatch). |
| 2026-10-20 | M6–M7 built and run on HI-Small. Verifier: 0/300 false alarms, 2,437/2,438 faults caught. Full demo path live: draft → fault caught → submit → maker-checker sign → browser and CLI verification agree. Found and fixed: Bitcoin amounts rounded to 0.00 in evidence; date-range starts not checked; a no-op fault injector; ESLint autofix inverted a null check. **Security note (U1):** a `GROQ_API_KEY` is present in the machine environment; 30 eval calls to Groq failed — LLM use is now opt-in. Backend 307+ tests, 93% coverage; frontend 151 tests. |
| 2026-10-20 | M2–M5 built and run on HI-Small. Detect F1 0.503 (CI 0.440–0.591) vs paper GFP+LightGBM 62.86. Decide: static and ACI guarantees hold at every α; ACI reviews 10% less. The 95% guarantee is unstaffable on bulk days (401–3,139 analysts) — the planner says so. **Bugs found by running on real data:** CLI writes were never committed (`return` inside `for db in session_scope()` skips the commit — fixed with `transaction()` + regression test); CP-SAT lost to greedy because minutes were rounded up; subgraph p95 4.1 s on hub accounts (now 257 ms); drift alarm driven by account-age features (now excluded); dollar objective caught 2% of cases with 97% of value (cases objective added, now default). Backend 215 tests, 93% coverage; frontend 133 tests. |
| 2026-10-19 | Tracker created; decisions recorded in PIVOT §26 |
| 2026-10-19 | M1 complete except M1.11/M1.15. Real data: both datasets pass the contract; 100% of pattern rows link. HI-Small splits — train 3,047,007 (2,298 laundering, 0.075%), hpo 507,835 (558), calib 507,834 (524), test 1,015,669 (1,797, 0.177%). Note the **label shift**: the test laundering rate is 2.3× train (the sparse tail falls in test); M2 must report it and evaluate the bulk and the tail separately. Backend: 120 tests, 99.3% coverage, ruff + mypy strict + bandit + pip-audit clean. |
| 2026-10-19 | Patterns files received (370 HI-Small / 117 LI-Small attempts, all 8 typologies). Prototype linker: 100% of pattern rows (3,209 / 1,023) match exactly one transaction, none labelled legitimate. **Coverage finding:** only 62.0% of HI-Small and 28.7% of LI-Small laundering transactions belong to a typology block; the rest are laundering without a typology. Consequences: per-typology metrics cover the attributed share only and are reported with that denominator; an `UNATTRIBUTED` group is added for per-typology (Mondrian) conformal thresholds; headline detection metrics use all laundering labels. |
| 2026-10-19 | Real data profiled. HI-Small: 5,078,345 txns, 5,177 laundering (0.102%). LI-Small: 6,924,049 txns, 3,565 laundering (0.051%). Currencies and payment formats match the data contract exactly. **Time span finding:** bulk traffic covers only 2022-09-01 → 09-10; 09-11 → 09-18 is a sparse tail that is mostly laundering (e.g. HI-Small 09-11: 396 txns, 232 laundering). Consequences: splits must be by transaction count, not by time span (a time-span split would put the test set in the degenerate tail); Decide must use hourly granularity (≈240 points) instead of daily/monthly. PIVOT §4.4 and §7 to be updated. |
| 2026-10-19 | M1 started: `configs/datasets.yaml`, `configs/data_contract.yaml`, `pipeline/config.py`, `pipeline/manifest.py`, `pipeline/fixture.py` written. Fixture generates 30.6k IBM-format rows, 96 patterns across all 8 typologies. Open: 11 ruff findings in `verita/pipeline`, no tests yet; ingest/patterns/graph/splits/data card not started. Risk to verify on real data: HI-Small may span only ~2–3 weeks, which would force hourly granularity in Decide. |
| 2026-10-19 | M0 built. Backend: 57 tests, 99.4% coverage, ruff + mypy strict clean, bandit + pip-audit clean. Frontend: 101 tests, 98% line coverage, ESLint strict + Stylelint token rules + Prettier + tsc clean; initial JS 117 KB gzip. Real-server smoke test passed (migrate → seed → login → /me). Contrast test caught and fixed 3 AAA failures in the paper theme. |
