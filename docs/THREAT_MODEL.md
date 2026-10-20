# Threat model

Scope: the deployed demo — nginx (same origin) → FastAPI API (2 workers) → PostgreSQL, a job
worker, a read-only demo pack, an Ed25519 signing key, and optional LLM providers. Method:
STRIDE per trust boundary. Each threat names its control and the test or check that proves the
control works; residual risks are stated, not hidden.

## Assets

| Asset | Why it matters |
|---|---|
| Signed case files and the signing key | A forged or altered case file is the worst outcome for a compliance product |
| The case ledger (`case_events`) | The audit trail regulators rely on |
| Analyst and MLRO sessions | They decide and sign |
| Alert data and evidence (synthetic here) | In a real deployment: personal financial data |
| `reports/metrics.json` | Every claim the product makes about itself |

## Trust boundaries

1. Browser ↔ nginx (public internet)
2. nginx ↔ API (container network)
3. API ↔ PostgreSQL, API ↔ demo pack (filesystem), API ↔ signing key (mounted secret)
4. API/worker ↔ LLM providers (Gemini, Groq; outbound HTTPS, opt-in)
5. Exported case file ↔ any third party who verifies it offline

## STRIDE

| # | Threat | Boundary | Control | Evidence |
|---|---|---|---|---|
| S1 | Credential stuffing / password spray | 1 | argon2id hashes; per-account lockout after 5 failures; per-IP login rate limit; generic error message | `tests/unit/test_auth_service.py`, `tests/integration/test_ratelimit.py` |
| S2 | Session theft | 1 | HttpOnly, SameSite=Lax, Secure cookies; tokens stored hashed; TTL; logout revokes | `tests/integration/test_api_auth.py` |
| S3 | Cross-site request forgery | 1 | Double-submit CSRF token bound to the session on every mutation | authorization matrix `test_mutations_need_csrf` |
| T1 | Tampering with a signed case file after export | 5 | RFC 8785 + RFC 6962 Merkle root signed with Ed25519; `verita-verify` and the browser name the changed leaf | `tests/defend/test_crypto.py`, e2e demo path, `test_api_cases.py` |
| T2 | Rewriting the ledger in the database | 3 | DB trigger rejects UPDATE/DELETE on `case_events` (PostgreSQL + SQLite); the API and worker connect as `verita_app`, which owns nothing and has only SELECT/INSERT on the ledger, audit log and signatures (so it cannot drop or disable the trigger either); hash chain detects edits made around both | `test_postgres.py::test_ledger_is_append_only_on_postgres`, `::test_app_role_cannot_rewrite_the_ledger`, `tests/defend/test_services.py` |
| T3 | Swapped or corrupted demo data | 3 | Demo pack manifest (SHA-256 per file) verified at startup; the API refuses to boot on a mismatch; pickled artifacts load only after hash check | `test_demo_pack.py` |
| T4 | Prompt injection through data fields into the LLM | 4 | Evidence is sent as a marked data block; output must be strict JSON; **every claim is re-verified deterministically** before a case can leave draft | `tests/defend/test_verifier.py`, fault-injection eval |
| R1 | An MLRO denies having signed | 3 | Ledger event with actor, hash chain, signature over a message binding case ID and root; audit log | `test_api_cases.py` |
| I1 | Data exposure to a role that should not see it | 1–2 | Default-deny roles; a policy for every route; truth labels never sent to the queue | `test_authz_matrix.py` (every OpenAPI route × role) |
| I2 | Internal metrics exposed | 1 | nginx returns 404 for `/api/metrics`; optional bearer token | `test_observability.py`, smoke test |
| I3 | Secrets in the repository or logs | — | `.gitignore` for keys and `.env`; gitleaks over the full history in CI; LLM keys only from the environment, held as `SecretStr`, and shown everywhere (errors, logs, `verita llm keys`, eval artifacts) as a SHA-256 fingerprint | CI `secrets` job; `tests/defend/test_keypool.py::test_keys_never_appear_in_errors_status_or_repr` |
| I4 | Clickjacking, MIME sniffing, XSS impact | 1 | CSP `default-src 'self'`, `frame-ancestors 'none'`, nosniff, COOP/COEP/CORP; React escapes output; no `dangerouslySetInnerHTML` | ZAP baseline (0 failures), headers checked in `scripts/smoke.py` |
| D1 | Request floods | 1 | Per-IP, per-login and per-session rate limits (429 + Retry-After) | `test_ratelimit.py`; k6 run that hit the limiter |
| D2 | Expensive endpoints exhausting memory | 2–3 | Plan cache, single-flight cache loads, bounded concurrent solves, bounded subgraph size | k6 stress run (194 req/s, 0 errors, no OOM) after an OOM was found and fixed |
| D3 | Malformed input crashing the API | 1–2 | Typed request models, bounded path IDs | schemathesis fuzzing: 39 operations, zero 5xx |
| E1 | Analyst approving their own case | 2 | Maker-checker in the service: approver ≠ creator ≠ submitter; MLRO role only | `test_api_cases.py::test_maker_checker_blocks_self_approval`, e2e |
| E2 | Container escape impact | 3 | Non-root user, read-only root filesystem, tmpfs `/tmp`, no shell needed at runtime | `deploy/docker-compose.yml` |

## Residual risks

* **Signing key on the host.** In the demo the Ed25519 key is a mounted file. A production
  deployment would hold it in an HSM/KMS and sign by API; the signer interface is one class.
* **In-process rate limits.** Each API worker counts separately, so the effective limit is
  per worker. Several instances would share a Redis counter.
* **Unpatched base-image packages.** The API image carries Debian packages with High findings
  that have no upstream fix yet (docs/SECURITY_EXCEPTIONS.md SE-3). CI fails on any fixable
  High/Critical.
* **Value-matching verifier.** Claims are matched by value, not by role; a wrong number that
  equals another true number in the cited evidence passes (measured: 1 of 2,438 planted faults).
* **Synthetic data.** No real personal data is processed; a real deployment needs a DPIA,
  retention rules and field-level access controls this demo does not implement.
