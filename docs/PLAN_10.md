# Plan: every area to 10/10

Written 2026-10-20 after the brutal audit (scores in TRACKER.md's rubric review). For each area:
what **10/10 means** (the bar a senior engineer on a regulated compliance product would hold),
the **work**, and the **proof** that closes it. Items marked **(you)** cannot be done by code.

Two honest limits up front:

* **Real-bank validation is out of reach.** No public real AML dataset exists. "10" for
  detection means: matches or beats the published baselines on every public synthetic dataset,
  with the evidence reported either way. No claim of real-world performance, ever.
* **Ownership is yours.** A reviewer will probe the maths and the design. If you can't defend
  them at a whiteboard, no amount of code makes this a 10. Track O below runs through all phases.

---

## Scorecard targets

| # | Area | Now | Target | Phase |
|---|---|---|---|---|
| 1 | Product thinking | 8.5 | 10 | 2, 5 |
| 2 | Detection ML | 5.5 | 10 | 3 |
| 3 | Statistics (Decide) | 8.5 | 10 | 3 |
| 4 | GenAI (Defend) | 7 | 10 | 3 |
| 5 | Security | 7.5 | 10 | 4 |
| 6 | Regulatory fit | 4.5 | 10 | 2 |
| 7 | Backend architecture | 8 | 10 | 4 |
| 8 | Enterprise readiness | 4 | 10 | 4, 5 |
| 9 | Testing | 8.5 | 10 | all |
| 10 | Frontend, UX, accessibility | 7.5 | 10 | 1 |
| 11 | DevOps | 7 | 10 | 5 |
| 12 | Honesty and documentation | 9 | 10 | 5 |
| 13 | Process and git history | 4 | 10 | from now |
| O | Ownership (you) | ? | 10 | all |

---

## Phase 1 — Redesign: from beige to memorable (design is the first thing a reviewer sees)

**Diagnosis.** The UI is monochrome by specification: a cream "paper" body (the saturated AI
default look of 2026), ink text, and accents legally capped at stamp size (DESIGN.md's Ceremony
Rule). Every panel has the same 2px box and the same weight, so nothing leads the eye. The
redesign changes the spec, not just the CSS.

**Pick a direction** (shown as mockups in chat): A Wax seal · B Petrol instrument · C Luminol ·
D Case board. Then:

1. Rewrite DESIGN.md for the chosen direction (palette in OKLCH, two-layer tokens:
   primitives → semantic roles; dark mode designed, not inverted). Update PRODUCT.md's brand
   section. Retire the Ceremony Rule; keep the strong parts (Mono Witness, hard shadows if the
   direction keeps them, AAA contrast).
2. **Colour with meaning, everywhere the data is:** a risk ramp on scores (a heat strip per alert
   row), one colour per typology (8 typologies + unattributed, colour-blind-safe, always with a
   label), verified / alert / pending states, the three Ds as wayfinding.
3. **Hierarchy:** each screen leads with one hero (queue: the riskiest alert's money path;
   capacity: the staffing verdict; case file: the seal; Evidence Room: the headline figure).
   Kill the identical-box grid; vary weight, size and surface.
4. **Money-flow graph as the signature visual:** coloured by role (subject, mule, sink), path
   animated along its edges (reduced-motion: static), amounts on edges.
5. **Ceremony moments that animate real state:** seal sets when the signature verifies, chain
   nodes tick as the ledger verifies, a counter rolls to the staffing verdict.
6. **Fix the UX defects found in the audit:**
   * the capacity estimate is shown as if exact (differs by ~1 point / ~20 analysts) — label it
     "estimate" until the exact plan arrives, and animate the swap;
   * the landing's loading state says "Results appear here after the first evaluation run" —
     make loading and "no results" two distinct states;
   * the queue table overflows at 1024 px — responsive columns;
   * every component gets all states (default, hover, focus, active, disabled, loading, error,
     empty), skeletons instead of "Loading…".
7. Typography: a product-grade scale (fixed rem, 1.125–1.2 ratio); the display serif only on the
   landing and the case-file seal.

**Proof:** contrast tests updated (AAA kept), axe zero in both themes, Playwright visual
regression snapshots for every screen, Lighthouse budgets still met, before/after screenshots in
the PR. Usability: 3 people do the demo path cold; time-to-understand each screen recorded.

---

## Phase 2 — Regulatory fit: from case file to filing (area 6, 1)

1. **goAML XML export** of a signed case (the UNODC format many FIUs use), validated against
   the goAML XSD in CI. The XML is a leaf in the Merkle tree, so the filing itself is signed.
2. **FinCEN SAR field mapping** documented (export optional) — shows breadth.
3. **Data protection:** retention policy per table with a purge job (`verita retention run`) and
   legal hold on open cases; PII masking by role (the reviewer role sees masked accounts);
   DPIA document; right-to-erasure tension with the append-only ledger addressed (crypto-shred
   the PII fields, keep the hash).
4. **Model risk management (SR 11-7 style):** a model inventory; a generated validation report
   per model version (performance, stability, limitations, challenger results); maker-checker
   **promotion** of a model (a data scientist proposes, a model-risk approver signs; the API
   refuses to serve an unapproved champion); monitoring thresholds that open a review.
5. **Full regulator audit export:** every event for a case (alerts, dispositions with reasons,
   drafts, verifications, approvals) in one signed bundle.
6. **Feedback loop:** analyst dispositions feed the next training run (labelled as such, with
   leakage guards), closing Detect ↔ Defend.

**Proof:** XSD validation test, retention tests, masking in the authz matrix, a promotion test
proving an unapproved model cannot score, the generated validation report in `reports/`.

---

## Phase 3 — Models: close the gaps (areas 2, 3, 4)

**Detection (2):**
1. **Credible rules baseline:** real typology rules (structuring under thresholds, velocity,
   fan-in/fan-out, rapid pass-through, round-tripping), thresholds tuned on the train split.
   Replaces today's strawman incumbent (see the Detect tab: it barely beats chance).
2. **Graph features matching the paper's GFP** (temporal fan-in/out, scatter-gather,
   gather-scatter, temporal cycles, in windowed degree form) to close the gap to the published
   GFP + LightGBM baseline shown in the README.
3. **GNN challenger** (GIN or PNA on the transaction graph) — reported against the champion;
   adopted only if it wins on the test split.
4. **SAML-D transfer** (M8.12) — out-of-distribution result reported, good or bad.
5. Error analysis per typology with examples in the Evidence Room.

**Statistics (3):**
1. **Label-delay sensitivity** (the dropped M2.07): ACI coverage when labels arrive 1–14 days
   late.
2. Conditional coverage per typology and per amount band, with the failures shown.
3. A derivations document (conformal, ACI update, expected-miss formula, CP-SAT model) — also
   your study material.

**GenAI (4):**
1. **Role-aware verifier:** each claim binds to an evidence *field* (amount of txn X, duration of
   path Y), closing the value-matching hole the threat model names.
2. **Prompt that copies instead of computing:** durations and totals pre-computed in the evidence
   (12 of 18 unsupported claims were durations), few-shot examples, a schema reminder.
3. **Bigger LLM evaluation:** ≥ 100 drafts per provider (Gemini and Groq) across days, so the
   raw rate has a tight interval; cost and latency per draft reported.
4. **Prompt-injection red team:** a fixed set of hostile evidence fields; the verifier and the
   JSON contract must hold.
5. **Human rubric:** a 5-point narrative-quality rubric scored on 20 drafts (you + 2 reviewers).

**Proof:** every number regenerated into `reports/`, honesty CI green; the README states the
result even if a target is missed.

---

## Phase 4 — Enterprise and security (areas 5, 7, 8)

1. **OIDC SSO** (Keycloak in compose as the dev IdP; any OIDC provider in prod) and **TOTP MFA**
   required for the MLRO role; local passwords only for the demo.
2. **Signing via KMS/HSM interface:** Vault transit (in compose) or a cloud KMS; the private key
   never touches the API's filesystem. Key rotation tested.
3. **Multi-tenancy:** `tenant_id` on every table + PostgreSQL row-level security; a test proving
   tenant A cannot read tenant B even with a crafted query.
4. **Shared state in Redis:** rate limits, the plan cache, job notifications — so N API replicas
   behave as one.
5. **Online scoring path:** a streaming endpoint (Redis Streams) that scores new transactions
   with the same feature code as batch (a parity test proves it), alongside the batch pipeline.
6. **Scale test:** a 50M-transaction synthetic run (partitioned tables), with the numbers.
7. **Supply chain:** images pinned by digest, signed with cosign, SLSA provenance on release,
   Renovate for dependencies.
8. **OWASP ASVS L2 checklist** mapped to tests.

**Proof:** RLS and SSO tests, the parity test, the scale report, signed release artifacts.

---

## Phase 5 — Ship it (areas 11, 12, 1, 8)

1. **Deploy live (you: VM + domain)** per ADR-008, with staging and prod; uptime monitor.
2. **Cut v1.0.0** through the release workflow (images, SBOMs, signatures, demo pack).
3. **Backups** automated (nightly `pg_dump`, restore test in CI), Prometheus **alert rules**
   shipped, SLOs written down, the worker metrics gap closed (a metrics sidecar endpoint).
4. **Reproducibility capsule:** one command rebuilds every published metric from the raw data
   and diffs the hashes against `reports/metrics.json`.
5. **Demo recording (you)** following DEMO_SCRIPT.md; a written "reviewer guide".

---

## Testing upgrades (area 9, across phases)

Mutation testing (mutmut) on the verifier, canonicalisation, Merkle and conformal code with a
score floor; Playwright visual regression; k6 smoke in CI; chaos test (kill the worker mid-job,
the job completes once); property tests against RFC 8785 / RFC 6962 published vectors.

## Process (area 13, from now)

Every change: issue → branch → PR → CI → self-review checklist → squash merge. Conventional
commits, signed. A GitHub project board mirrors this plan. Releases get CHANGELOG entries. The
existing history stays as it is (rewriting it would look worse); the rhythm from here on is what
a reviewer will see.

## Track O — Ownership (you, throughout)

I write `docs/DEFEND_IT.md`: 40 interview questions with model answers and the code/line each
answer lives in (leakage, conformal, ACI, CP-SAT, JCS/Merkle/Ed25519, verifier limits, why
LightGBM, scaling to a bank). You work through it, then we run mock interviews where I play the
Wolters Kluwer panel and you answer without notes. Done when you can whiteboard Detect → Decide
→ Defend end to end.

---

## Order and size

| Phase | Sessions (rough) | Blocks |
|---|---|---|
| 1 Redesign | 4–6 | your pick of direction |
| 2 Regulatory | 3–4 | — |
| 3 Models | 4–6 | Gemini quota (LLM eval) |
| 4 Enterprise | 5–7 | — |
| 5 Ship | 2–3 | VM + domain, recording (you) |
| O Ownership | ongoing | you |

**Order decided 2026-10-20:** the redesign (phase 1) is parked. Work goes to the lowest-scoring
dimensions first: phase 2 (regulatory), then 4 (enterprise), 3 (models) and 5 (ship); process
improves with every PR.
Each phase lands as a series of PRs with green CI; TRACKER.md gains an M10–M14 section as each
phase starts.
