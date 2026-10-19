# Verita v2 — Detect → Decide → Defend

> The complete build plan, from empty repo to demo day. Every feature, screen, dataset, model,
> table, endpoint, test, and deploy step is specified here. If it isn't in this document, it
> isn't in scope.

---

## 0. The rules this project lives by

1. **No hand-typed metrics. Anywhere.** Every number in the README, landing page, model card, and
   UI comes from a generated artifact (`reports/metrics.json`) produced by `poe eval`. CI fails if
   a document contains a metric that doesn't match the artifact. (Section 15.)
2. **Every claim has a test.** "Tamper-evident" has a tamper test. "No leakage" has a leakage
   test. "Recall ≥ 95%" has an empirical coverage test on future data.
3. **Three features. No fourth.** New ideas go to `docs/IDEAS.md`, not the codebase.
4. **No claims about third-party products or employers.** Verita is framed as "built for the kind
   of problems FCC teams face", never "compatible with X".
5. **Show where it fails.** Every evaluation section reports the failure cases, not just the
   headline number. This is the honesty that gets remembered.

---

## 1. Pitch, thesis, and why this project

**One line:** Verita is an anti-money-laundering system that detects laundering *patterns* in a
transaction graph, tells a compliance team exactly how much risk they accept at their staffing
level, and produces a regulator-ready case file whose every sentence is machine-verified and
cryptographically signed.

**Thesis:** Detection accuracy is not the hard problem in AML. The hard problems are
(a) *which* alerts to work with finite analysts, (b) *what you miss* by doing so, and
(c) *defending* every filed report to an examiner. Verita is built around those three.

**The three features:**

| # | Name | Question it answers | Disciplines |
|---|------|---------------------|-------------|
| 1 | **Detect** — temporal money-flow typology detection | "Which money movements look like laundering, and which pattern?" | Data engineering, graph ML, GBM, GNN, evaluation |
| 2 | **Decide** — capacity-aware triage with a recall guarantee | "With 6 analysts tomorrow, what's the most we'll miss, and what does it cost?" | Calibration, conformal prediction, forecasting, optimization, drift |
| 3 | **Defend** — verified, signed case files | "Can every sentence in this SAR be proven from evidence, and can anyone prove it wasn't altered?" | GenAI, NLP claim verification, adversarial evaluation, cryptography |

**The 3-minute story:** open an alert → see the money path that triggered it → move the
"analysts on duty" slider and watch guaranteed recall and expected miss change → draft the case
narrative → watch the verifier catch an injected wrong number → sign → tamper with the file →
watch verification fail.

---

## 2. Users and their jobs

Two audiences, as before: the **evaluator** (interview panel, ~3 minutes, skimming) and the
**in-fiction users** below. Every screen must work for both.

| Persona | Role | Job to be done | Primary screens |
|---------|------|----------------|-----------------|
| **Priya — L1 Analyst** | Works the alert queue | Clear or escalate 40+ alerts/day; needs the "why" fast | Alert Queue, Investigation |
| **Marcus — MLRO / BSA Officer** | Owns filing decisions and staffing | Approve case files; decide staffing vs risk appetite; answer to the regulator | Capacity Planner, Case File (approver) |
| **Elena — Model Validator** | Second line, model risk | Challenge the model: data, leakage, calibration, coverage, drift | Evidence Room |
| **Reviewer (demo)** | Interviewer with read-only access | Understand the system in 3 minutes | Landing → guided tour |

**Maker-checker is a hard rule:** the person who drafts a case cannot approve it. This is a real
compliance control and it shapes the UI (Section 13.6).

---

## 3. Scope

### 3.1 In scope
- The three features above, end to end.
- Six screens (Section 13).
- Batch ML pipeline + online API + Postgres operational store.
- Auth with four roles, maker-checker, append-only case ledger.
- Generated model card, data card, eval report.

### 3.2 Explicit non-goals
- No generic CSV-to-dashboard studio. No SQL playground. No free-text NLP page.
- No real customer data, no real-time streaming ingest (batch + simulated "daily" replay only).
- No multi-tenant SaaS, no billing, no SSO.
- No 3D/WebGL anything.

### 3.3 Cut list (delete in M0)

| Remove | Why |
|--------|-----|
| `frontend/src/immersive/`, `sections/`, `components/landing/ParticleField.tsx`, `components/SignalField.tsx`, `components/CustomCursor.tsx` | Dead or decorative |
| `pages/Studio.tsx` + `components/studio/*`, `pages/NLP.tsx`, `pages/Overview.tsx`, `pages/Landing.tsx` (rebuilt) | Old scope |
| `backend/app/profiling/`, `nlp/`, `agent/`, `services/{dashboard,sql,jobs,data_validation,nlp,agent}_service.py`, matching routers | Old scope |
| Dependencies: three, @react-three/*, gsap, lenis, animejs, framer-motion, iconsax-react, react-grid-layout, jsdom (keep happy-dom), xgboost (LightGBM replaces it) | Unused or replaced |
| `resume/`, `WK-UNIVERSE/`, `JD - Intern…pdf`, `JD_FEATURE_MAP.md`, `FRONTEND_SCAN.md`, `verita_brutal_audit.md`, `implementation_plan.md`, `IMPLEMENTATION_PLAN_9.5.md`, `INTERVIEW_PREP.md`, `BUSINESS_CASE.md`, `.agents/` (duplicate of `.github/skills`) | Personal or stale; move personal material to a private repo |
| `START_BACKEND.bat`, `START_FRONTEND.bat`, `start.bat`, `compile-all-latex.ps1` | Replaced by `make` targets; the backend .bat contains a key (rotate it) |

Kept and hardened: FastAPI skeleton, middleware idea (rewritten), SHAP reason-code module, cost
threshold logic (moves into Decide), PSI function (moves into Decide), Postgres + SQLAlchemy.

Because history contains personal files, consider starting a **fresh public repo** (`verita`
v2) and archiving the current one as private.

---

## 4. Datasets

### 4.1 Primary: IBM synthetic AML transactions
- **Source:** "Realistic Synthetic Financial Transactions for Anti-Money Laundering Models",
  Altman et al., NeurIPS 2023 Datasets & Benchmarks track. Published on Kaggle as *IBM
  Transactions for Anti Money Laundering (AML)*.
- **Files used:** `HI-Small_Trans.csv` (primary), `HI-Small_Patterns.txt` (laundering attempts
  with typology labels), `LI-Small_Trans.csv` + patterns (robustness test, lower illicit ratio).
  `HI-Medium` only for the scale test.
- **Approximate shape (verify on ingest, record actuals in DATA_CARD):** HI-Small ≈ 5M
  transactions, ≈ 500k accounts, illicit ratio ≈ 0.1%. Columns: `Timestamp, From Bank, Account,
  To Bank, Account.1, Amount Received, Receiving Currency, Amount Paid, Payment Currency,
  Payment Format, Is Laundering`.
- **Typology labels (from the patterns file):** FAN-OUT, FAN-IN, GATHER-SCATTER,
  SCATTER-GATHER, CYCLE, RANDOM, BIPARTITE, STACK. Patterns are linked to transactions by
  matching rows; build and test that join (Section 5.3).
- **Why this dataset:** real labels at transaction level, typology ground truth, published
  baselines (the source paper and follow-ups such as Multi-GNN, Egressy et al., AAAI 2024).
  It's synthetic, and we say so on every screen that shows a metric.
- **Baselines file:** `configs/baselines.yaml` — each published number with citation, dataset
  variant, split, and metric definition. Our comparisons only use baselines whose split and
  metric match ours; anything else is listed as "not directly comparable".
- **License:** check the Kaggle page; record license + citation in `DATA_CARD.md`. The raw data is
  never committed; `poe data` verifies the files you downloaded SHA-256 hashes against
  `configs/data_manifest.yaml`.

### 4.2 Secondary: SAML-D (external validity)
- **Source:** Oztas et al., synthetic transaction-monitoring dataset for AML (2023), on Kaggle as
  *Synthetic Transaction Monitoring Dataset (AML)*; ≈9.5M transactions, many typologies.
- **Use:** generalization test only. Map its schema to ours (`configs/saml_d_mapping.yaml`), score
  with the HI-Small model *without retraining*, and report the drop. Then fine-tune and report
  again. "Our model loses X points out-of-distribution" is a finding, not a failure.
- **Optional.** If schema mapping proves lossy, report what couldn't be mapped and stop there.

### 4.3 Simulated operations data (generated, labeled as assumptions)
Analyst handling times and team size don't exist in public data. They are **explicit,
configurable assumptions** in `configs/operations.yaml`:
- handling time per alert: lognormal, median 12 min (configurable), by typology multiplier;
- analysts on duty: 1–20, 6.5 productive hours/day;
- cost of a missed laundering transaction: proportional to amount (configurable rate);
- cost of reviewing an alert: analyst minutes × loaded hourly rate.

Every UI element derived from these shows an "ASSUMPTION" stamp with a link to the config.

### 4.4 Splits (temporal, never random)

> **Measured on the real files (2026-10-19):** bulk traffic spans only 2022-09-01 → 09-10;
> 09-11 → 09-18 is a sparse tail that is mostly laundering. Splits are therefore cut by
> **transaction count in time order** (60/20/20), never by time span, and every time-based
> analysis in Decide runs at **hourly** granularity. The tail is kept (it is real benchmark
> data) but reported separately so it can't inflate any metric.
- Sort by `Timestamp`. Train = first 60% of time, validation = next 20%, test = last 20%.
  If the source paper's split definition differs, add a second split that matches theirs and
  use it only for the baseline comparison table.
- Within validation: first half = model selection / HPO, second half = **calibration set** for
  conformal and isotonic calibration. Test is touched once per release, by `poe eval`.
- **Replay mode:** the test period is replayed day by day to simulate production — this drives
  forecasting, drift, and the ACI coverage experiments.

### 4.5 Data contract and validation
- `pandera` schemas for raw and cleaned tables (types, ranges, non-null, currency codes, bank
  ids). Ingest fails loudly on violation.
- Validation report saved as `reports/data_validation.json` and summarized in DATA_CARD.
- Canonical storage: Parquet, partitioned by date, queried through DuckDB.

---

## 5. Data engineering pipeline

### 5.1 Stages (each is a Typer CLI command and a task)

Task runner: `poethepoet` (cross-platform, no `make` needed on Windows). The names below are
task names: run them as `uv run poe <name>` from `backend/`.

```
poe data        hash-verify the raw files you downloaded
poe ingest      raw CSV → validated, typed Parquet (transactions, accounts, patterns)
poe graph       build edge table + account-day aggregates + pattern→transaction links
poe features    as-of feature tables (no future data) for every scored entity
poe train       train baselines, champion, challenger; log to model registry table
poe calibrate   isotonic calibration + conformal thresholds on calibration set
poe score       score test period; write alerts to Postgres
poe forecast    alert-volume forecasts for the replay period
poe eval        all evaluations → reports/metrics.json + figures + EVAL_REPORT.md
poe cards       render MODEL_CARD.md, DATA_CARD.md from metrics.json
poe demo-pack   export everything the demo deploy needs (Section 18.4)
```

`poe all` runs the chain. Every stage is idempotent and writes a `run_manifest.json` (inputs'
hashes, code git SHA, config hash, timings) — this is the lineage record.

### 5.2 Entities
- **Transaction (edge):** one row, directed `from_account → to_account`, timestamp, amounts,
  currencies, payment format, label.
- **Account (node):** id = `bank_id:account_id`.
- **Alert:** an *account-day* whose max transaction score crosses the threshold. Analysts work
  alerts, not single transactions — this mirrors real transaction-monitoring queues.

### 5.3 Pattern linking

> **Measured (2026-10-19):** every pattern row links to exactly one transaction, but patterns
> cover only **62.0%** (HI-Small) and **28.7%** (LI-Small) of laundering transactions. The rest
> carry the label but no typology. They form an explicit `UNATTRIBUTED` group: included in all
> headline metrics, shown as their own row in per-typology tables, and given their own
> Mondrian conformal threshold.
Join each pattern block in the patterns file to its transactions (timestamp, accounts, amount,
currency). Report: patterns parsed, transactions linked, unlinked count. Target: 100% of
laundering transactions in the patterns file linked; anything less is documented. This gives
every positive a typology label for per-typology evaluation.

### 5.4 Performance targets
- Ingest + graph + features for HI-Small in under 15 minutes on a laptop (16 GB RAM), measured
  and reported in the run manifest.
- Peak memory under 8 GB (DuckDB out-of-core + Parquet).

---

## 6. Feature 1 — DETECT: temporal money-flow typology detection

### 6.1 Problem formulation
- **Primary task:** transaction-level binary classification (laundering vs not), matching the
  benchmark literature.
- **Operational task:** account-day alert scoring = max (and top-3 mean) of its transaction
  scores, plus account-level graph features.
- **Secondary output:** *probable typology* for each alert (multi-class), used for routing and
  for the narrative.

### 6.2 Features (all computed as-of the transaction timestamp)

| Group | Examples | Notes |
|-------|----------|-------|
| Transaction | log amount, amount-paid vs received ratio, currency mismatch, payment format, hour, weekday, round-amount flag | Cheap baseline set |
| Account velocity | out/in count and sum over 1h / 24h / 7d windows, unique counterparties per window | DuckDB window functions with `RANGE` frames |
| Fan patterns | fan-out degree in window, fan-in degree in window, concentration (Gini) of amounts | Directly target FAN-IN/OUT |
| Two-hop flow | money received then forwarded within Δt (pass-through ratio), gather-then-scatter score | Self-joins with time constraints |
| Temporal cycles | participates in a directed cycle of length ≤ 5 within 7 days, with time-respecting edges | Bounded DFS in a compiled helper (numba) over a CSR snapshot per window |
| Counterparty risk | counterparty's prior alert rate (as-of, from past labels only) | Strictly past data; leakage-tested |
| Bank / format | cross-bank flag, rare payment format for this account | |

**Leakage rule:** a feature for an event at time *t* may only read events with timestamp < *t*
(strictly). Enforced by a property-based test (Section 16.3) that perturbs future rows and
asserts features don't change.

### 6.3 Models

| Role | Model | Purpose |
|------|-------|---------|
| Incumbent | **Rules engine**: 6 classic transaction-monitoring rules (large cash-like amount, rapid pass-through, high fan-out, etc.) | The thing banks run today; everything must beat it |
| Baseline | LightGBM on transaction features only | Shows what graph features add |
| **Champion** | LightGBM on transaction + graph features | The production model |
| Challenger | GNN edge classifier (PyTorch Geometric; GINe-style with edge features, reverse message passing, ego-IDs as in Multi-GNN) | Research comparison; optional extra install `pip install .[gnn]` |
| Typology head | LightGBM multi-class on alerts that are true positives in train | Probable typology |

- HPO: Optuna, 50 trials, on the HPO half of validation only, objective = minority-class F1 at
  the validation-optimal threshold (also log PR-AUC).
- Class imbalance: `scale_pos_weight` vs focal loss vs undersampling compared in the ablation.
- Seeds: 5 seeds for the champion; report mean ± std.

### 6.4 Evaluation protocol (all in `poe eval`)
1. **Headline:** minority-class F1, PR-AUC, recall@precision=0.5, on the test period. With
   **bootstrap 95% CIs** (1,000 resamples, block bootstrap by day to respect time correlation).
2. **Vs baselines:** incumbent rules, tabular LightGBM, champion, GNN, and published numbers
   where comparable (Section 4.1).
3. **Per typology:** recall for each typology with CI and support count. Worst typology is
   highlighted, not hidden.
4. **Ablation table:** remove each feature group, report ΔF1 with CI.
5. **Robustness:** LI-Small (lower illicit ratio) and SAML-D transfer (Section 4.2).
6. **Operational:** alert-level precision and alerts/day at the chosen threshold.
7. **Latency:** p50/p95 scoring time per 10k transactions; feature build time.
8. **Sanity checks:** label-shuffle test (must drop to ≈ base rate), and train-on-future check
   (deliberately leaky run must look suspiciously good — documented as proof the guard works).

### 6.5 Explanation: the evidence subgraph
For each alert, the API returns an **evidence subgraph**:
- the alerted account, its transactions in the alert window, and up to 2 hops of
  time-respecting money flow (capped at 60 nodes, pruned by flow amount);
- the **dominant path** (max-flow path through the window) highlighted;
- matched **motif** (fan-in / fan-out / cycle / scatter-gather / pass-through) with the exact
  edges that form it;
- top-5 SHAP reasons (from the champion), each mapped to a plain-English reason code.

Each evidence item gets a stable ID (e.g. `EV-SUBGRAPH-3`, `EV-SHAP-1`, `EV-TXN-8812`) — these
are what Defend's narrative cites.

---

## 7. Feature 2 — DECIDE: capacity-aware triage with a recall guarantee

### 7.1 Calibration
- Isotonic calibration of champion scores on the calibration set.
- Report: reliability diagram, ECE (expected calibration error), Brier score — before and after,
  with CIs. Calibrated probabilities are what make "expected laundered value" meaningful.

### 7.2 The recall guarantee (conformal)
- **Goal:** choose threshold *t* such that recall on future positives ≥ 1 − α with high
  probability. Default α = 0.05 (configurable: 0.01–0.20).
- **Method:** split conformal on calibration-set positives: *t* = the ⌊α(n+1)⌋-th smallest
  calibrated score among the *n* calibration positives. Under exchangeability this gives
  P(score of a new positive ≥ t) ≥ 1 − α.
- **Class-conditional (Mondrian) variant:** a separate threshold per typology so a rare typology
  isn't sacrificed to the average. Compare both.
- **The honest part — drift:** time series data isn't exchangeable. Run the guarantee on the
  replay period month by month and report **empirical recall with CI per month**. Expect
  violations; show them.
- **Fix under drift:** Adaptive Conformal Inference (Gibbs & Candès, 2021) updates α online as
  labels arrive (simulated with a configurable label delay, default 30 days). Report coverage of
  static vs ACI over the replay. This is the most original analysis in the project.
- **Minimum data:** if calibration positives for a typology < 50, that typology falls back to
  the pooled threshold and the UI says so.

### 7.3 Alert-volume forecasting
- Series: daily alert count at the operating threshold, and daily expected review minutes.
- Models: seasonal naive (weekly), ETS (statsmodels), LightGBM with lag/calendar features, and
  a simple mean ensemble.
- Backtest: rolling origin over the replay period, horizon 1–14 days.
- Metrics: MASE, pinball loss at 10/50/90%, and **80%/95% interval coverage** (an interval that
  claims 95% must cover ≈95% — reported, with CI).
- Output: next-14-days forecast with intervals → feeds the staffing view.

### 7.4 Capacity optimization
- **Decision:** which alerts to review tomorrow, given analysts on duty.
- **Formulation (ILP, OR-Tools CP-SAT):**
  maximize Σᵢ xᵢ · pᵢ · vᵢ (calibrated probability × amount at risk)
  subject to Σᵢ xᵢ · hᵢ ≤ analysts × productive minutes,
  and the recall-floor constraint: every alert with score ≥ t_conformal is reviewed
  (if infeasible, the planner reports *exactly how many analysts are needed* to restore the
  guarantee — that's the headline the MLRO wants).
- Greedy ratio heuristic as baseline; report optimality gap.
- **Frontier:** for analysts = 1..20, compute expected recall, expected missed value, review
  cost, and guarantee feasibility → the curve shown in the Capacity Planner.

### 7.5 Drift monitoring
- PSI per feature and on the score distribution, weekly over the replay, with the standard
  0.10 / 0.25 bands, plus a KS test p-value.
- A drift event triggers a "recalibration recommended" banner and links to the ACI chart.

### 7.6 What Decide produces
`/api/capacity/plan?date=…&analysts=…&alpha=…` returns: selected alerts, guaranteed-recall
status, expected recall (point + interval), expected missed value, review minutes, analysts
needed for the guarantee, and the frontier.

---

## 8. Feature 3 — DEFEND: verified, signed case files

### 8.1 Case file model
A **case** groups 1..n alerts on related accounts. It contains:
- evidence items (subgraphs, transactions, SHAP reasons, motif matches, analyst notes) with IDs;
- a narrative (sections per FinCEN SAR narrative guidance: who, what, when, where, why, how);
- verification results;
- state machine: `draft → verified → submitted_for_approval → approved → signed` (or
  `returned` / `closed_no_file` with mandatory reason code).

### 8.2 Narrative generation
- **LLM:** Google Gemini (primary) and Groq (fallback) behind one provider interface, selected
  by `VERITA_LLM_PROVIDERS` (ordered list, default `gemini,groq`). Model names are config
  (`VERITA_GEMINI_MODEL`, `VERITA_GROQ_MODEL`) and recorded on every narrative. Temperature 0.
  Prompts versioned in `prompts/` with a hash recorded on every narrative. Adding another
  provider (e.g. xAI) is one adapter class.
- **Structured output:** the model must return JSON: a list of sentences, each with
  `section`, `text`, and `evidence_ids[]`. Free prose is rejected.
- **Input:** only the structured evidence JSON — never raw free text from the dataset. Account
  names and other strings from data are passed as quoted values with an explicit instruction
  that they are data (prompt-injection hygiene; the verifier is the backstop).
- **Offline mode:** a deterministic template generator produces the same JSON shape with no
  API key. CI uses offline mode; the UI labels which mode wrote each narrative.

### 8.3 The verifier (deterministic)
For every sentence:
1. **Citation rule:** ≥ 1 evidence ID, all IDs exist in this case.
2. **Claim extraction:** amounts (with currency), counts, dates/times, durations, account IDs,
   bank IDs, typology names, percentages — via typed regex parsers + a normalization layer
   (e.g. "$48.5k" = 48,500 USD).
3. **Claim checking:** each extracted claim must match a value in the *cited* evidence, with
   rules: exact for IDs and dates, ±0.5% or rounding-aware for amounts, exact for counts,
   typology must equal the evidence motif or the typology head's prediction.
4. **Coverage rule:** the narrative must mention the dominant path, total amount, date range,
   and typology at least once.
Output: per-sentence pass/fail, per-claim results with the evidence value it was checked
against. A case cannot leave `draft` with any failure (an analyst can edit text; edits are
re-verified).

### 8.4 Adversarial evaluation of the verifier
- Build 300 cases from the test period. Generate a clean narrative for each (both offline and
  LLM modes).
- **Fault injection** (scripted, one fault per variant, ≈2,400 variants): wrong amount (small /
  large error), wrong date, swapped account, invented counterparty, wrong typology, wrong count,
  uncited sentence, cited-but-irrelevant evidence.
- **Metrics:** per fault type: detection rate (recall) with CI; false-alarm rate on clean
  narratives; plus the **raw LLM unsupported-claim rate before verification** on clean
  generations (an honest measure of how much the LLM hallucinates on this task).
- Report the fault types the verifier misses and why (e.g. paraphrased typology names).

### 8.5 Signing and the append-only ledger
- **Canonical form:** RFC 8785 (JSON Canonicalization Scheme) for every evidence item and the
  narrative.
- **Merkle tree:** leaves = SHA-256 of canonical items; root covers evidence + narrative +
  verification report + approver identity + timestamp.
- **Signature:** Ed25519 over the root (`cryptography` library). The signing key is held by the
  backend (env/file in dev; a managed secret in deploy). Public key published at
  `/api/keys` and in the repo (`keys/verita-pub.pem`) with key ID and validity dates.
- **Ledger:** Postgres table `case_events` is append-only — a trigger rejects UPDATE/DELETE;
  corrections are new events that supersede old ones. Each event stores the previous event's
  hash (a real hash chain, persisted this time).
- **Verification:** `GET /api/cases/{id}/verify` and an offline CLI
  `verita-verify case-<id>.json --pubkey keys/verita-pub.pem` that needs nothing but the file.
  It recomputes leaves, root, checks the signature, and prints which leaf changed if any.
- **Export:** signed JSON (the authoritative artifact) + a PDF rendering (WeasyPrint) that prints
  the root hash, key ID, and a verification instruction. The PDF is a view; the JSON is the proof.

---

## 9. System architecture

```
                     ┌──────────────── Batch pipeline (Typer CLI, make) ───────────────┐
 Kaggle raw CSV ──►  │ ingest → graph → features → train → calibrate → score → forecast │
                     │                     → eval → cards → demo-pack                   │
                     └───────┬─────────────────────────┬───────────────────────────────┘
                             │ Parquet (DuckDB)        │ Postgres (alerts, models, evals)
                             ▼                         ▼
                     ┌──────────────────────────────────────────────┐
  React SPA  ◄─────► │ FastAPI (read-mostly API, auth, RBAC)          │
  (Vite, TS)  REST   │  routers → services → repositories             │
                     │  • alerts / evidence  (DuckDB + Postgres)       │
                     │  • capacity planner   (OR-Tools, cached)        │
                     │  • cases / verify / sign (Postgres ledger)      │
                     │  • evidence room      (reports/metrics.json)    │
                     └───────────┬──────────────────────────────────────┘
                                 │ job table (Postgres SKIP LOCKED)
                                 ▼
                     ┌─────────────────────────┐
                     │ Worker: narrative gen,    │──► Gemini / Groq (optional)
                     │ PDF render, plan compute  │
                     └─────────────────────────┘
```

**Decisions (each gets an ADR in `docs/adr/`):**
1. ADR-001 Batch scoring + read-mostly API (not online training) — the free-tier deploy can't
   train on 5M rows; precomputed artifacts make the demo fast and reproducible.
2. ADR-002 DuckDB for analytics, Postgres for operational state — right tool for each.
3. ADR-003 Postgres-backed job queue instead of Redis/Celery — one fewer service.
4. ADR-004 LightGBM champion, GNN challenger — explainability and CPU cost.
5. ADR-005 Conformal + ACI for the recall guarantee — distribution-free, auditable.
6. ADR-006 Ed25519 + RFC 8785 + Merkle — standard primitives, offline verifiable.
7. ADR-007 No user-supplied SQL — removes the largest attack surface of v1.

### 9.1 Backend layout
```
backend/
  verita/
    api/            app.py, deps.py, routers/{auth,alerts,evidence,capacity,cases,evidence_room,health}.py
    services/       alerts.py, evidence.py, capacity.py, cases.py, verify.py, signing.py, narratives.py
    repositories/   postgres/*.py, duckdb/*.py
    pipeline/       ingest.py, graph.py, features/*.py, train.py, calibrate.py, score.py, forecast.py, eval/*.py
    ml/             models/{rules,lgbm,gnn,typology}.py, conformal.py, aci.py, calibration.py, drift.py, shap_reasons.py
    optimize/       ilp.py, greedy.py, frontier.py
    defend/         claims.py, verifier.py, faults.py, merkle.py, jcs.py, pdf.py
    llm/            provider.py, anthropic_client.py, offline_template.py
    core/           config.py (pydantic-settings), logging.py, security.py, errors.py
    cli.py          Typer entry point
  migrations/       Alembic
  tests/            unit/, property/, integration/, contract/, ml/, golden/
  pyproject.toml    (uv or pip-tools lockfile; extras: [gnn], [dev])
```

---

## 10. API specification (v1, all under `/api/v1`)

| Method | Path | Role | Purpose |
|--------|------|------|---------|
| POST | `/auth/login` | public | Username + password → httpOnly session cookie |
| POST | `/auth/logout` | any | End session |
| GET | `/me` | any | Current user + role |
| GET | `/alerts` | analyst+ | Paginated queue. Query: `date`, `status`, `typology`, `min_score`, `sort`, `cursor` |
| GET | `/alerts/{id}` | analyst+ | Alert detail: scores, calibrated prob, typology, SHAP reasons |
| GET | `/alerts/{id}/subgraph` | analyst+ | Evidence subgraph: nodes, edges, dominant path, motif, evidence IDs |
| POST | `/alerts/{id}/disposition` | analyst | `escalate` / `dismiss` with mandatory reason code + note |
| GET | `/capacity/frontier` | mlro+ | Frontier for a date, α |
| GET | `/capacity/plan` | mlro+ | Plan for date, analysts, α (see 7.6) |
| GET | `/capacity/forecast` | mlro+ | 14-day volume forecast with intervals |
| GET | `/capacity/coverage` | validator+ | Static vs ACI empirical coverage over replay |
| POST | `/cases` | analyst | Create case from alert IDs |
| GET | `/cases/{id}` | analyst+ | Case with evidence, narrative, verification, events |
| POST | `/cases/{id}/narrative` | analyst | Enqueue narrative generation (returns job ID) |
| PUT | `/cases/{id}/narrative` | analyst | Save analyst edits (triggers re-verification) |
| POST | `/cases/{id}/verify` | analyst | Run verifier; returns per-claim results |
| POST | `/cases/{id}/submit` | analyst | Submit for approval (requires verified) |
| POST | `/cases/{id}/approve` | mlro (≠ author) | Approve + sign |
| POST | `/cases/{id}/return` | mlro | Return with reason |
| GET | `/cases/{id}/verify-signature` | any | Server-side signature verification |
| GET | `/cases/{id}/export.json` / `export.pdf` | analyst+ | Signed artifact / rendering |
| POST | `/demo/tamper/{id}` | demo only | Returns a deliberately altered copy for the tamper demo |
| GET | `/jobs/{id}` | any | Job status |
| GET | `/evidence-room/metrics` | any | Contents of `reports/metrics.json` |
| GET | `/evidence-room/figures/{name}` | any | Generated eval figures |
| GET | `/keys` | public | Public signing keys |
| GET | `/health/live`, `/health/ready` | public | Liveness (process up) and readiness (DB + artifacts loaded) |

- OpenAPI is the contract. Frontend types are generated from it (`openapi-typescript`) and
  responses are runtime-validated with Zod in dev builds.
- Errors: RFC 9457 problem+json (`type`, `title`, `status`, `detail`, `instance`), never raw
  exception text.
- Pagination: cursor-based. All list endpoints capped (max 200).

---

## 11. Database schema (Postgres, Alembic-managed)

| Table | Key columns | Notes |
|-------|-------------|-------|
| `users` | id, username, password_hash (argon2id), role, created_at | Roles: analyst, mlro, validator, reviewer |
| `sessions` | id, user_id, expires_at, created_at | httpOnly cookie session |
| `model_versions` | id, name, git_sha, config_hash, data_hash, metrics_json, created_at, is_champion | Registry |
| `alerts` | id, account_id, alert_date, score, calibrated_prob, typology_pred, typology_conf, model_version_id, amount_at_risk, status | One per account-day over threshold |
| `alert_reasons` | alert_id, rank, feature, shap_value, reason_code | Top-5 |
| `dispositions` | id, alert_id, user_id, action, reason_code, note, created_at | Append-only |
| `cases` | id, created_by, state, created_at | |
| `case_alerts` | case_id, alert_id | |
| `case_evidence` | id (EV-…), case_id, kind, payload_jsonb, leaf_hash | Immutable after creation |
| `narratives` | id, case_id, version, mode (llm/offline), model_id, prompt_hash, sentences_jsonb, created_by, created_at | Versioned |
| `verifications` | id, narrative_id, passed, results_jsonb, verifier_version, created_at | |
| `case_events` | id, case_id, seq, type, actor_id, payload_jsonb, prev_hash, hash, created_at | **Append-only trigger**; real hash chain |
| `signatures` | case_id, merkle_root, key_id, signature, signed_by, signed_at | |
| `jobs` | id, kind, payload, status, attempts, result, error, created_at, updated_at | SKIP LOCKED queue |
| `capacity_plans` | id, date, analysts, alpha, result_jsonb, created_by, created_at | Cached + auditable |
| `audit_log` | id, actor_id, action, target, ip, created_at | Every mutating request |

Transactions and features stay in Parquet/DuckDB (too large and analytical for the OLTP store).

---

## 12. Security model

**Threat model (STRIDE, summarized in `docs/THREAT_MODEL.md`):**

| Threat | Control |
|--------|---------|
| Spoofing | Argon2id passwords, httpOnly + Secure + SameSite=Lax cookies, CSRF token on mutations, session expiry |
| Tampering | Append-only ledger trigger, signed case files, offline verification, DB role without UPDATE/DELETE on ledger tables |
| Repudiation | `audit_log` on every mutation; maker-checker; actor recorded in signed root |
| Information disclosure | RBAC on every route (default deny), problem+json errors, no stack traces, CSP + security headers, no secrets in repo (gitleaks in CI) |
| DoS | Per-user + per-IP rate limits (in Postgres or a reverse proxy), request size limits, pagination caps, no user SQL, timeouts on every external call |
| Elevation | Role checks in a single dependency; tests that every route rejects every lower role (generated test matrix) |
| Prompt injection | Evidence-only LLM input, strings passed as quoted data, structured output, deterministic verifier as backstop |

**Secrets:** `.env` (gitignored) locally; platform secret store in deploy; `gitleaks` blocking in
CI and as a pre-commit hook.

---

## 13. UI / UX design

### 13.1 Design direction
- **Keep "The Forensic Ledger"** (DESIGN.md) as the identity — it fits an evidence product.
  **Delete the legacy aurora/glass system entirely**; v2 has one design language.
- Two themes from one token set: **Paper** (default, cream ground, iron-gall ink) and
  **Night Ledger** (dark ground, cream ink). Both AAA.
- **Analyst bench density:** the app is a work tool. Data tables and graphs are dense; ceremony
  (stamps, seals) appears only at moments of certainty (verified, approved, signed).

### 13.2 Design tokens (`frontend/src/styles/tokens.css`)
- **Type scale (minimums enforced by lint rule):** body 15px, table 14px, labels 12px mono
  uppercase, nothing under 12px. Headline Fraunces 900; titles Space Grotesk 700; body Inter;
  figures JetBrains Mono (Mono Witness Rule).
- **Color:** ink `#14120b`, faded ink `#4a4434`, paper `#f3eee2`, paper-deep `#ece5d3`,
  vermilion `#c2331f` (alerts, stamps), registrar green `#1c6e4a` (verified), gold `#a8842c`
  (focus, sealed nodes — non-text only), archival blue `#2b3a8c` (links, annotations).
  Night Ledger equivalents defined and contrast-checked by a script in CI.
- **Data-viz palette:** 6 categorical colors chosen for color-vision deficiency safety and
  checked against both grounds; risk scale is a single-hue sequential ramp (never red-green).
- **Shape:** square corners, 2px ink borders, hard offset shadows (`4px 4px 0`).
- **Motion:** 150–250ms state transitions; stamp/seal animations only on real state changes;
  every animation has a `prefers-reduced-motion` instant fallback.

### 13.3 Component library (built once, used everywhere)
`Button` (primary/ghost/danger), `Stamp`, `Badge`, `DataTable` (virtualized, sortable,
keyboard-navigable, sticky header), `Panel`, `Tabs` (ARIA tabs), `Dialog` (focus-trapped),
`Toast`, `Slider` (with numeric input twin), `Stat` (value + interval + "how computed" popover),
`EvidenceChip` (EV-ID, click to highlight source), `ClaimResult` (pass/fail with checked value),
`HashText` (mono, copy button, middle-ellipsis), `AssumptionStamp`, `EmptyState`, `ErrorState`,
`Skeleton`. Charts: `LineWithBand`, `Frontier`, `Reliability`, `CoverageOverTime`, `BarCI`.
Graph: `MoneyFlowGraph`.

Each component has: Vitest tests, an axe check, and a usage example in `docs/components.md`.

### 13.4 Information architecture
```
/                    Landing (public)         — what Verita is, live generated metrics, "Start tour"
/login               Login
/queue               Alert Queue              (analyst)          Feature 1+2
/alerts/:id          Investigation            (analyst)          Feature 1
/capacity            Capacity Planner         (mlro)             Feature 2
/cases/:id           Case File                (analyst, mlro)    Feature 3
/evidence-room       Evidence Room            (validator, all)   All features' evaluations
```
Global: left rail (Queue, Capacity, Cases, Evidence Room), top bar (date in replay, role,
theme toggle, user menu), command palette (`Ctrl+K`).

### 13.5 Screen specifications

#### Screen 1 — Landing (`/`)
- **Purpose:** in 20 seconds, tell the evaluator what this is and prove it's real.
- **Layout:** headline ("Every alert detectable. Every miss quantified. Every report provable."),
  three columns for Detect / Decide / Defend, each with **one live number pulled from
  `metrics.json`** with its CI and dataset label ("synthetic IBM AML, HI-Small"), and a "Start
  the 3-minute tour" button (logs in as read-only reviewer and runs the guided tour).
- **Footer:** links to Evidence Room, GitHub, model card, data card, public key.
- **No scroll-jacking, no WebGL, no smooth-scroll library.** LCP < 1.5s.

#### Screen 2 — Alert Queue (`/queue`)
- **Purpose:** Priya clears her day.
- **Layout:** header strip = today's plan from Decide ("Reviewing 212 of 340 alerts · guaranteed
  recall ≥ 95% · 6 analysts"), then a virtualized table:
  `priority rank | alert ID | account | typology (pred + confidence) | calibrated prob | amount at
  risk | in today's plan? | status`.
- **Filters:** typology, status, in-plan only, score range. Saved views.
- **Interactions:** `J/K` move, `Enter` open, `E` escalate, `D` dismiss (opens reason-code
  dialog — mandatory), `X` multi-select, `C` create case from selection. Dispositions write
  through optimistically with rollback on error.
- **States:** loading skeleton rows; empty ("No alerts for this date"); error with retry and
  problem detail.
- **Acceptance:** 10k rows scroll at 60fps; every action reachable by keyboard; screen reader
  announces row count and selection.

#### Screen 3 — Investigation (`/alerts/:id`)
- **Purpose:** answer "why is this an alert?" in under 10 seconds.
- **Layout (three panes):**
  - **Left:** alert summary (`Stat`s: calibrated prob with interval, amount at risk, typology +
    confidence), top-5 reason codes as plain sentences with SHAP bars.
  - **Center:** `MoneyFlowGraph` — accounts as nodes, transactions as directed edges, time flows
    left→right (layered layout by timestamp), the dominant path drawn thick in vermilion, motif
    edges outlined. Hover edge = amount, currency, time, format. Click node = expand one more
    hop (server call). Toggle: graph / table view (accessible alternative listing every edge).
  - **Right:** timeline of the account's transactions in the window (time axis, amount bars),
    synced with the graph (hover one highlights the other).
- **Actions:** Escalate to case, Dismiss (reason code), Add note, Copy evidence ID.
- **Acceptance:** subgraph renders < 500ms for 60 nodes; graph has a full table alternative;
  every evidence item shows its EV-ID.

#### Screen 4 — Capacity Planner (`/capacity`)
- **Purpose:** Marcus decides staffing vs risk. This is the hero screen of the demo.
- **Layout:**
  - **Controls:** "Analysts on duty" slider 1–20 (with numeric input), α selector (recall
    guarantee 99/95/90/80%), date picker in the replay period, guarantee mode (pooled /
    per-typology).
  - **Headline row (`Stat`s, each with "how computed"):** guaranteed recall status (✓ holds /
    ✗ needs N more analysts), expected recall (with interval), expected missed value, review cost,
    alerts reviewed / total.
  - **Frontier chart:** x = analysts, y = expected recall (band) and missed value (second axis);
    current choice marked; the point where the guarantee becomes feasible marked with a stamp.
  - **Forecast panel:** next 14 days of alert volume with 80/95% bands → "analysts needed per
    day" bars.
  - **Coverage panel (link to Evidence Room):** "Was the guarantee kept last quarter?" static vs
    ACI empirical recall by month.
  - **Assumptions drawer:** handling time, hourly cost, productive hours — editable for
    what-if, each marked with `AssumptionStamp`.
- **Interactions:** slider updates within 150ms (frontier precomputed; plan for a specific
  setting computed server-side and cached); "Save plan" writes a `capacity_plans` record.
- **Acceptance:** every number on screen traceable to an API field and a formula popover.

#### Screen 5 — Case File (`/cases/:id`)
- **Purpose:** draft, verify, approve, sign, verify again.
- **Layout:**
  - **Header:** case ID, state stamp (DRAFT / VERIFIED / AWAITING APPROVAL / SIGNED), author,
    approver, Merkle root (`HashText`).
  - **Left — Evidence:** list of evidence items (EV-IDs) grouped by kind; click opens a preview
    (mini graph, transaction table, SHAP list).
  - **Center — Narrative:** sections (Who/What/When/Where/Why/How). Each sentence shows its
    `EvidenceChip`s; editing is inline; each sentence carries a verification mark.
  - **Right — Verifier:** per-claim results ("$48,500 ✓ matches EV-TXN-8812 amount_paid
    48,500.00 USD"; "14 March ✗ evidence says 13 March"). Failing claims highlight in the text.
- **Flow and interactions:**
  1. "Draft narrative" → job progress (real job status, not fake steps) → narrative appears.
  2. Verifier runs automatically; failures block "Submit for approval".
  3. **Demo moment:** "Inject a fault" button (reviewer/demo only) changes one amount → the
     verifier catches it live.
  4. Submit → MLRO view: "Approve & sign" (disabled for the author, with tooltip "Maker-checker:
     you drafted this case").
  5. On sign: seal animation (real event), signature + key ID shown, export buttons appear.
  6. **Tamper demo:** "Download tampered copy" → drop it on the "Verify a file" dropzone → red
     result naming the changed leaf ("EV-TXN-8812.amount changed").
- **Acceptance:** a case cannot be signed with any failed claim; verification of an exported
  file works in the browser (WebCrypto Ed25519 or a WASM fallback) and via the CLI, both giving
  identical results.

#### Screen 6 — Evidence Room (`/evidence-room`)
- **Purpose:** Elena (and the interviewer) challenge the model. This replaces the README's
  claims with live, generated proof.
- **Tabs:**
  1. **Data:** data card — source, license, counts, validation results, split dates, known
     limitations (synthetic!).
  2. **Detect:** headline metrics with CIs, baseline comparison table (with citations),
     per-typology recall bars with CIs, ablation table, robustness (LI-Small, SAML-D), sanity
     checks (label shuffle).
  3. **Decide:** reliability diagram + ECE, conformal coverage over time (static vs ACI),
     forecast backtest (MASE, interval coverage), optimizer optimality gap.
  4. **Defend:** verifier detection rate per fault type with CIs, false-alarm rate, raw LLM
     unsupported-claim rate, misses explained.
  5. **Lineage:** run manifests — git SHA, data hashes, config hashes, timings, model version.
- Every figure has: a caption stating what it shows and what it doesn't, a data-table
  alternative, and a download of the underlying JSON.

### 13.6 Cross-cutting interaction rules
- **Roles change what you can do, not what you can see** (except reviewer = read-only + demo
  actions). Disabled actions always explain why.
- **Guided tour** (reviewer): 8 steps across Queue → Investigation → Capacity → Case File →
  Evidence Room; skippable; each step points at a real element.
- **Undo:** dispositions have a 10-second undo toast; ledger events are never undone, only
  superseded.
- **Provenance popover:** every `Stat` has "how computed" with formula, inputs, and source
  (API field + metrics.json key).
- **Keyboard map** available with `?`.

### 13.7 Accessibility (the bar: WCAG 2.2 AA everywhere, AAA contrast for text)
- axe-core zero violations in CI on every route (Playwright).
- Keyboard-only walkthrough of the full demo path recorded as an e2e test.
- Every chart and the graph have tabular alternatives; color is never the only signal (icons +
  text on pass/fail, patterns on CI bands).
- Visible focus (2px gold outline + offset); skip-to-content link; landmarks; live regions for
  job progress and verifier results.
- Responsive: queue and case file usable at 375px (stacked panes); graph switches to table view
  on narrow screens by default.

---

## 14. Frontend architecture

- **Stack:** React 18, TypeScript strict (`noUncheckedIndexedAccess` on), Vite, React Router
  with **lazy routes**, TanStack Query (server state), Zustand only for UI state (theme, tour),
  Zod (runtime validation of API responses in dev/test), `openapi-typescript` for types.
- **Styling:** CSS Modules + `tokens.css`. **No inline styles** (ESLint rule). Stylelint with a
  rule enforcing the minimum font sizes and token-only colors.
- **Charts:** ECharts with modular imports (`echarts/core` + only used charts), wrapped in typed
  components that use `replaceMerge` correctly.
- **Graph:** Cytoscape.js with a layered (dagre) layout; one component, lazy-loaded with the
  Investigation route.
- **Quality gates:** ESLint (typescript-eslint strict, jsx-a11y, react-hooks), Prettier,
  `tsc --noEmit`, zero `any` (lint error).
- **Performance budget (CI-enforced):** initial JS ≤ 180 KB gzip, each route ≤ 150 KB gzip,
  LCP ≤ 1.5s and INP ≤ 200ms on the Landing and Queue (Lighthouse CI, throttled).

```
frontend/src/
  app/          router.tsx, providers.tsx, layout/
  routes/       landing/, login/, queue/, investigation/, capacity/, case/, evidence-room/
  components/   ui/ (library), charts/, graph/
  api/          generated types, client.ts, queries/
  styles/       tokens.css, globals.css
  lib/          format.ts (money, dates, hashes), provenance.ts
  test/         setup.ts, fixtures/
```

---

## 15. The honesty mechanism

1. `poe eval` writes `reports/metrics.json` — every metric with value, CI, n, dataset, split,
   git SHA, and a schema version.
2. Landing, Evidence Room, README, MODEL_CARD, and EVAL_REPORT **read from that file**: the
   frontend at build time (imported JSON), the docs via `poe cards` (Jinja templates).
3. README metrics live between `<!-- metrics:start -->` / `<!-- metrics:end -->` markers and are
   regenerated; CI fails if the committed README differs from the regenerated one.
4. A CI script scans `*.md` and `frontend/src` for percentage/decimal literals near metric words
   (recall, precision, AUC, F1, accuracy) outside the generated blocks and fails the build.
5. The demo deploy ships the same `metrics.json` whose hash is printed in the footer.

---

## 16. Testing strategy

### 16.1 Targets
- Backend line coverage ≥ 90%, branch ≥ 80% (excluding the optional GNN module).
- Frontend: every component and route has tests; coverage ≥ 85%.

### 16.2 Layers
| Layer | Tooling | Examples |
|-------|---------|----------|
| Unit | pytest, vitest | claim parsers, Merkle root, conformal threshold math, ILP constraints |
| Property-based | hypothesis | **as-of leakage** (perturb future rows → features unchanged), Merkle (any single-byte change → root changes), conformal (threshold monotone in α), money parser round-trips |
| Golden | pytest snapshots | verifier output on 30 fixed narratives; subgraph extraction on fixed fixtures |
| Integration | pytest + testcontainers Postgres | ledger append-only trigger rejects UPDATE/DELETE; maker-checker enforcement; job queue concurrency |
| Contract | schemathesis against OpenAPI | every endpoint fuzzed; no 500s |
| Authorization matrix | generated pytest | every route × every role → expected allow/deny |
| ML | pytest (marked `ml`) | champion beats incumbent rules on a fixed sample; label-shuffle collapses; calibration reduces ECE; coverage within tolerance on a synthetic exchangeable fixture |
| E2E | Playwright | the full demo path (tour), tamper demo, keyboard-only path |
| Accessibility | axe-core in Playwright | zero violations per route |
| Performance | k6 | `/alerts`, `/alerts/{id}/subgraph`, `/capacity/plan`: p95 < 300ms at 50 VUs on the demo stack |
| Security | bandit, pip-audit, npm audit, gitleaks, CodeQL, ZAP baseline scan | all **blocking** |

### 16.3 Data used in tests
A deterministic 1% sample of HI-Small (`tests/fixtures/hi_small_1pct.parquet`, built by
`poe fixtures`, hash-pinned) plus hand-built micro-graphs for each typology.

---

## 17. Observability

- **Logs:** structlog JSON with request ID, user ID (hashed in logs), route, latency, status.
- **Metrics:** Prometheus — HTTP RED metrics, job queue depth/latency, verifier pass rate,
  LLM latency and error rate, plan computation time.
- **Tracing:** OpenTelemetry for API → DB → LLM spans (exporter optional in dev).
- **Dashboard:** one Grafana dashboard JSON, provisioned automatically in docker compose.
- **SLOs (documented, measured in k6 runs):** 99.5% availability of read endpoints on the demo;
  p95 < 300ms for queue/subgraph/plan.

---

## 18. DevOps

### 18.1 Environments
- **Local:** `docker compose up` = Postgres, API, worker, frontend (nginx), Prometheus, Grafana.
  `make dev` = API + Vite with hot reload against compose Postgres.
- **CI:** GitHub Actions.
- **Demo:** one path only — API + worker on a container host (Fly.io or Render), Postgres on Neon,
  frontend on Vercel (or served by the API's nginx). Choose one in ADR-008 and delete the others.

### 18.2 Containers
- Multi-stage builds, non-root user, pinned base image digests, `HEALTHCHECK` on
  `/health/live`, read-only root filesystem where possible, SBOM generated (syft) and scanned
  (grype) in CI.
- One start command per service, defined once (in the Dockerfile).

### 18.3 CI pipeline (all blocking)
1. Lint/format/type: ruff, ruff format, mypy (strict on `services/`, `defend/`, `ml/`), ESLint,
   Prettier, Stylelint, tsc.
2. Security: bandit, pip-audit, npm audit (high+), gitleaks, CodeQL.
3. Tests: unit + property + golden + integration + contract + authz + ML smoke (1% sample).
4. Build: frontend with bundle-budget check; Docker images + SBOM + vulnerability scan.
5. E2E + axe + Lighthouse CI against the compose stack.
6. Honesty check (Section 15).
7. On tag `v*`: build release, attach `demo-pack` artifacts, deploy, run k6 + smoke against deploy.

### 18.4 Demo pack
Training on 5M rows doesn't belong on a free-tier host. `poe demo-pack` exports: champion model,
calibrator, conformal thresholds, precomputed alerts/subgraph indexes for a 30-day demo window,
forecasts, frontiers, `metrics.json`, figures — each with SHA-256 in a manifest. The deploy
verifies the manifest on startup (readiness fails if a hash mismatches).

---

## 19. Documentation set

| Doc | Content | Generated? |
|-----|---------|------------|
| `README.md` | What/why, 3 screenshots, generated metrics block, quickstart, links | Metrics block generated |
| `docs/ARCHITECTURE.md` | Diagram, components, data flow | Hand-written |
| `docs/adr/ADR-00x-*.md` | Each key decision | Hand-written |
| `MODEL_CARD.md` | Intended use, data, metrics with CIs, per-typology, limitations, ethics | Generated |
| `DATA_CARD.md` | Sources, license, counts, validation, splits, synthetic caveat | Generated |
| `reports/EVAL_REPORT.md` | Every evaluation in Sections 6.4, 7, 8.4 with figures | Generated |
| `docs/THREAT_MODEL.md` | STRIDE table, controls, residual risks | Hand-written |
| `docs/RUNBOOK.md` | Run the pipeline, rotate keys, recover, redeploy | Hand-written |
| `docs/DEMO_SCRIPT.md` | The 3-minute script (Section 22) | Hand-written |
| `docs/components.md` | UI component usage | Hand-written |
| `CONTRIBUTING.md` | Setup, conventions, PR checklist | Hand-written |

---

## 20. Target repository layout

```
verita/
  backend/            (Section 9.1)
  frontend/           (Section 14)
  configs/            data_manifest.yaml, baselines.yaml, operations.yaml, model.yaml, saml_d_mapping.yaml
  prompts/            narrative_v1.md (+ hash)
  keys/               verita-pub.pem (public only)
  reports/            metrics.json, figures/, EVAL_REPORT.md   (generated; committed for the demo)
  docs/               ARCHITECTURE.md, adr/, THREAT_MODEL.md, RUNBOOK.md, DEMO_SCRIPT.md, components.md
  deploy/             docker-compose.yml, grafana/, prometheus/, fly.toml (or render.yaml)
  .github/workflows/  ci.yml, release.yml, codeql.yml
  Makefile, README.md, MODEL_CARD.md, DATA_CARD.md, CONTRIBUTING.md, LICENSE
```

---

## 21. Milestones (each ends with its exit criteria green in CI)

| # | Milestone | Contents | Exit criteria |
|---|-----------|----------|---------------|
| M0 | **Reset** | New repo, cut list executed, tooling (ruff/mypy/ESLint/Prettier/pre-commit/gitleaks), CI skeleton all blocking, Alembic, auth skeleton | Empty app deploys; CI green; no personal files; key rotated |
| M1 | **Data foundation** | `poe data/ingest/graph`, pandera contracts, pattern linking, splits, DATA_CARD v1, fixtures | Counts recorded; 100%/documented pattern linkage; leakage property test exists |
| M2 | **Detect models** | Feature groups, rules incumbent, LightGBM baseline + champion, HPO, typology head, eval §6.4 items 1–4 | Champion beats incumbent and tabular baseline with non-overlapping CIs (or the result is reported honestly if not) |
| M3 | **Detect UX** | Alerts in Postgres, Queue + Investigation screens, subgraph API, MoneyFlowGraph | Screens pass axe + keyboard e2e; subgraph < 500ms |
| M4 | **Decide** | Calibration, conformal (pooled + Mondrian), ACI replay, forecasting, ILP + frontier, drift | Coverage report generated; forecast interval coverage reported; optimizer gap reported |
| M5 | **Decide UX** | Capacity Planner screen | Slider < 150ms; every Stat has provenance |
| M6 | **Defend** | Evidence IDs, narrative (offline + Gemini/Groq), verifier, fault injection eval, JCS + Merkle + Ed25519, ledger trigger, CLI | Verifier eval in metrics.json; tamper test passes in CLI and browser |
| M7 | **Defend UX + roles** | Case File screen, maker-checker, PDF, tamper demo | Full demo path e2e green |
| M8 | **Evidence Room + honesty** | Evidence Room, generated cards/README, honesty CI check, robustness (LI-Small, SAML-D), GNN challenger | No hand-typed metric anywhere; Evidence Room complete |
| M9 | **Harden + ship** | k6, Lighthouse, ZAP, SBOM, observability, runbook, demo pack, deploy, demo script rehearsal | All §23 rubric checks pass |

**Sizing:** this is a large project — realistically 8–12 weeks of focused work for one person.
If time is short, the order above is also the priority order: M0–M7 is a complete, honest
product; M8–M9 is what moves every dimension from ~8.5 to 9.5. The GNN challenger and SAML-D
are the first things to drop if needed, and their absence is stated in the model card.

---

## 22. Demo script (3 minutes)

| Time | Screen | Say / do |
|------|--------|----------|
| 0:00 | Landing | "Detection isn't the hard part of AML. Choosing what to review, knowing what you miss, and defending what you file is. Every number here is generated by the eval pipeline — here's the hash." Start tour. |
| 0:20 | Queue | "Today's plan: 6 analysts, 212 of 340 alerts, recall guaranteed ≥ 95%." Open the top alert. |
| 0:40 | Investigation | "Here's the money path: a fan-in, then a pass-through within 40 minutes. These are the five reasons, in plain English." Escalate to case. |
| 1:10 | Capacity | Drag the slider to 3 analysts: "The guarantee breaks — we need 5. Expected missed value goes from X to Y." Show the coverage panel: "Last quarter the static guarantee slipped in month 2; adaptive conformal held it." |
| 1:50 | Case File | Draft narrative. Inject a fault: "The verifier caught a wrong amount." Fix it, submit. Switch to MLRO: approve and sign. |
| 2:30 | Case File | Download the tampered copy, drop it in: "Verification fails and names the changed field — anyone can check this offline with our public key." |
| 2:45 | Evidence Room | "Here's where it fails: [worst typology] at [its recall], and a [N]-point drop out-of-distribution. That's in the model card too." |

All bracketed values and the example numbers in this script (212 of 340, 6 analysts, etc.) are
placeholders — the rehearsed script reads them from `metrics.json` and the demo window.

---

## 23. The 9.5 rubric — how each dimension is proven

| Dimension | 9.5 means… | Proven by |
|-----------|-----------|-----------|
| Backend architecture / code | Layered (routers → services → repositories), typed, mypy-strict core, no silent excepts, ADRs, migrations | mypy + ruff in CI; `grep "except Exception: pass"` = 0; ADR folder |
| Security | Threat model, default-deny RBAC with authz test matrix, append-only signed ledger, no user SQL, all scanners blocking, no secrets | CI security stage; authz matrix tests; ZAP report |
| ML rigor | Temporal splits, leakage tests, baselines incl. incumbent rules + published, CIs, ablations, per-typology, robustness, sanity checks | EVAL_REPORT generated from metrics.json |
| Statistics | Calibration measured, conformal coverage empirically verified over time with ACI, forecast interval coverage, block bootstrap CIs | Evidence Room "Decide" tab |
| GenAI / NLP | Structured output, deterministic verifier, adversarial fault-injection eval with per-fault detection rates, raw hallucination rate reported | Evidence Room "Defend" tab |
| Frontend engineering | Lazy routes, generated API types, zero `any`, no inline styles, bundle budgets enforced | ESLint/Stylelint/tsc/bundle check in CI |
| UX / accessibility | 6 purposeful screens, keyboard-first, axe zero, AAA text contrast, min 12px, responsive, guided tour | Playwright axe + keyboard e2e; contrast script |
| Tests | ≥ 90% backend coverage, property + golden + contract + authz + e2e + perf | Coverage reports; CI stages |
| DevOps / CI | One deploy path, non-root pinned images, SBOM + scan, health/readiness that work, release automation, k6 against deploy | Release workflow logs |
| Docs vs reality (honesty) | Every metric generated; CI honesty check; limitations front and center | Honesty CI step; Section 15 |
| Repo hygiene | Clean tree, no personal files, conventional commits, CHANGELOG, LICENSE, CONTRIBUTING | Repo inspection; gitleaks |

---

## 24. Risks and mitigations

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| Champion doesn't clearly beat published baselines | Medium | That's acceptable if reported honestly; the novelty is Decide + Defend, not SOTA detection |
| Cycle/motif features too slow on 5M edges | Medium | Bounded windows, numba CSR traversal, sample for HPO, measure and report |
| Conformal thresholds unstable for rare typologies | High | Mondrian with pooled fallback below 50 positives; show it in the UI |
| ACI needs labels the replay doesn't "have yet" | Medium | Configurable label delay; report sensitivity to the delay |
| LLM costs / no key during interviews | Medium | Offline template mode always works; cached LLM narratives in the demo pack |
| WebCrypto Ed25519 support varies by browser | Low | WASM fallback (`@noble/ed25519`); CLI is the reference verifier |
| Scope creep | High | Section 0 rule 3; `docs/IDEAS.md` |
| Time runs out | Medium | Milestone order = priority order; state what was cut |

---

## 25. Interview questions this project is built to answer

| Question | Where the answer lives |
|----------|-----------------------|
| "How do you know there's no leakage?" | Property test (16.2), train-on-future sanity check (6.4.8) |
| "Why should I trust 95% recall?" | Conformal derivation (7.2) + empirical coverage over time + ACI |
| "What happens when the data drifts?" | PSI/KS monitoring, ACI, coverage-by-month chart |
| "Why LightGBM and not a GNN?" | ADR-004 + the comparison table |
| "How do you stop the LLM making things up?" | Verifier + fault-injection eval + raw hallucination rate |
| "What can't it do?" | Model card limitations; worst typology; OOD drop on SAML-D |
| "How would this scale to a real bank?" | ADR-001/002, perf numbers, the batch/online split |
| "How do you prove a filed report wasn't changed?" | Merkle + Ed25519 + append-only ledger + offline CLI |

---

## 26. Decisions

| # | Decision | Status |
|---|----------|--------|
| 1 | Fresh repo: `verita-v2/` with clean git history; v1 untouched. You push it to a new GitHub repo. | Decided |
| 2 | Dataset: you download IBM AML HI-Small + LI-Small from Kaggle; until then everything runs on a generated fixture. | Decided |
| 3 | LLM: Gemini primary, Groq fallback, offline template always available (CI uses offline). | Decided |
| 4 | Demo host: Fly.io vs Render — ADR-008, decided in M9. | Open |
| 5 | Name: Verita. | Decided |
| 6 | Python 3.11 (installed locally), uv for env + lockfile, poethepoet for tasks. | Decided |
| 7 | License: MIT (change before publishing if you prefer another). | Decided (default) |
