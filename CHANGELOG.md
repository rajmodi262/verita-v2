# Changelog

All notable changes to Verita v2. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versions follow [Semantic Versioning](https://semver.org/). Measured results live in
`reports/metrics.json` and the documents generated from it, not here.

## [Unreleased]

### Added
- **Credible rules incumbent:** seven typology rules (structuring under the USD 10k reporting
  threshold, velocity, fan-out, fan-in, rapid pass-through, round-tripping, high value), every
  threshold tuned on the train split only, lift-weighted alert score, tuned conditions and per-rule
  test hits in the eval report; `verita detect rules` re-tunes it without retraining the champion.
  Replaces the six-rule count that barely beat chance.
- **`docs/DEFEND_IT.md`:** 40 interview questions a financial-crime panel would ask, each
  with a model answer and the file:line that implements it. Results are referenced, never typed.
- **Model governance (model risk management):** model lifecycle (candidate → approved →
  champion → retired/rejected), policy gates in `configs/model_policy.yaml` (discrimination,
  beats the incumbent, seed stability, calibration, label-shuffle leakage, drift with a volume
  floor, typology coverage), a generated validation report stored with its SHA-256, approval by a
  validator and promotion by a different MLRO, a database check that forbids an unreviewed
  champion, and a visible bypass for development and the demo pack. `verita models list|validate`
  and `/api/v1/models`. The model card and eval report now state the gate results.
- **Hardening (M9):** per-IP, per-login and per-session rate limits; schemathesis contract
  fuzzing of every operation; k6 load and stress tests whose results feed the reports;
  Prometheus metrics by route template with a provisioned Grafana dashboard; OpenTelemetry
  tracing when an endpoint is configured.
- **Least-privilege database role:** the API and worker connect as `verita_app`, which owns
  nothing and can only SELECT/INSERT the ledger, audit log and signatures
  (`verita db app-role`).
- **Supply chain:** CycloneDX SBOMs for both images and a grype gate on every fixable
  High/Critical in CI and on release; OWASP ZAP baseline report.
- **Frontend budgets:** Lighthouse CI on the production bundle (performance, accessibility,
  best practices, SEO, LCP, TBT, CLS, transfer size) and a gzip bundle check.
- **Release and deploy:** tag-driven release workflow (GHCR images, SBOMs, Python
  distribution with `verita-verify`); production compose override with Caddy for HTTPS
  (ADR-008); demo-pack release script.
- Docs: THREAT_MODEL, RUNBOOK, DEMO_SCRIPT, ADR-008, security exception SE-3.

### Fixed
- Mutating routes validated the request body before checking the caller's role, so a forbidden
  caller could get a 422 describing the endpoint's input; authorization now runs first everywhere.
- Out-of-memory under concurrent load: plan cache, single-flight cache loads, bounded
  concurrent CP-SAT solves, count cache and Postgres pool sizing.
- Commit-after-response race on PostgreSQL (function-scoped database dependency).
- Path IDs beyond 32 bits crashed the database driver (found by fuzzing).
- nginx dropped security headers in locations with their own `add_header`; it also cached the
  API container's IP, so recreating the API broke the site until nginx restarted.
- Ledger appends locked the last event row, which neither covered a case's first event nor
  works under a role without UPDATE on the ledger; they now lock the case row.
- CSP violations on the landing page: zod's `new Function` probe and a font inlined as a
  `data:` URI. Added `robots.txt` and a favicon.
- Image vulnerabilities: OS packages upgraded at build, pip/setuptools removed from the
  runtime image, unprivileged nginx base.

## [0.1.0] — 2026-10-20 (internal milestone, not released)

### Added
- **M0–M1:** platform skeleton (FastAPI, SQLAlchemy, Alembic, argon2id sessions, CSRF,
  default-deny RBAC), React + TypeScript frontend, CI; contract-checked data pipeline for the
  IBM AML datasets with temporal splits and a data card.
- **M2–M5, Detect and Decide:** LightGBM champion with baselines, bootstrap CIs, ablations and
  per-typology results; alert queue and investigation with reason codes and evidence
  subgraphs; isotonic calibration, Mondrian and adaptive conformal recall guarantees, demand
  forecast, drift monitoring and a CP-SAT capacity planner.
- **M6–M7, Defend:** structured narratives (offline or LLM), a deterministic claim verifier
  with a fault-injection evaluation, RFC 8785 + RFC 6962 + Ed25519 signed case files, an
  append-only hash-chained ledger, maker-checker approval, browser and CLI verification.
- **M8:** honesty pipeline (`reports/metrics.json` → README block, model card, eval report;
  CI rejects hand-typed metrics), Evidence Room, live landing page, reviewer tour, Playwright
  end-to-end and accessibility suite, LI-Small robustness results.
