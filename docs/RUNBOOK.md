# Runbook

Operating the demo stack (`deploy/docker-compose.yml`). Commands run from the repository root
unless they say `cd backend`.

## Build the data (build machine)

```bash
cd backend
uv run poe pipeline                      # contract-checked Parquet, splits, data card
uv run poe eval                          # features → train → alerts → decide → verifier eval → bench → reports
uv run poe eval --dataset li_small       # robustness dataset
uv run verita report build               # reports/metrics.json + README block + cards
uv run verita demo pack --dataset hi_small --pack ../demo-pack
uv run verita demo verify --pack ../demo-pack
```

`poe eval` on HI-Small takes about 95 minutes (most of it Optuna and the bootstrap); the demo
pack takes about 4 minutes and is ~40 MB.

## Start, stop, observe

```bash
docker compose -f deploy/docker-compose.yml up --build -d
docker compose -f deploy/docker-compose.yml run --rm api verita users seed-demo
cd backend && VERITA_DEMO_PASSWORD=... uv run python scripts/smoke.py http://localhost:8080
docker compose -f deploy/docker-compose.yml --profile observability up -d   # Prometheus :9090, Grafana :3000
```

Production (ADR-008) adds `deploy/prod/docker-compose.prod.yml`: released images from GHCR and
Caddy for HTTPS; see the header of that file. Releases are cut by pushing a `vX.Y.Z` tag
(`.github/workflows/release.yml`); the demo pack is attached from the build machine with
`deploy/prod/release-pack.sh vX.Y.Z`.

`migrate` connects as the database owner and runs `verita db upgrade`, `verita db app-role --role verita_app` (the least-privilege role the API and worker use; set `VERITA_APP_DB_PASSWORD`) and then `verita demo load`, which verifies the pack and is
idempotent per champion model. The API itself refuses to start if the pack fails verification —
read its log for the file that did not match.

## Signing key

* **Create** (dev): the API creates `keys/verita-signing.pem` on first use; the public half is
  written next to it and published at `GET /api/v1/keys`.
* **Rotate:** generate a new key, mount it as the `signing_key` secret, restart `api` and
  `worker`. Old case files keep verifying with the old public key (their `key_id` names it);
  keep every retired public key in `keys/` and list it in the release notes.
* **Compromise:** rotate immediately, publish the compromised key ID as revoked, and re-sign
  nothing automatically — re-approval is a human decision recorded in the ledger.

## Recovery

| Symptom | Likely cause | Action |
|---|---|---|
| API exits at startup: "demo pack failed verification" | Pack edited or partially copied | Re-copy the pack; `verita demo verify --pack …` |
| 503 `no-model` on the queue | Alerts not loaded | `verita demo load` (or `verita detect alerts` on the build machine) |
| 503 `no-decide` on capacity | Decide artifacts missing from the pack | Rebuild the pack after `verita decide run` |
| Narrative drafts stay "queued" | Worker down, or `VERITA_INLINE_JOBS=false` without a worker | `docker compose … up -d worker`; check its log |
| 429s for everyone behind one proxy | Rate limit keyed on the proxy IP | Make sure nginx sets `X-Forwarded-For` and the API runs with `--proxy-headers` |
| API OOM-killed under load | Too many workers for the host, or caches disabled | `VERITA_WORKERS=1`; check `docker stats`; the plan cache and single-flight loads must be in place |
| `permission denied for table …` in the API log | A new code path writes an append-only table, or a migration added a table after the grant | Re-run `migrate` (it re-grants on every start); never grant UPDATE/DELETE on `case_events`, `audit_log` or `signatures` |
| Site returns 502 after an API restart | (fixed) nginx cached the old container IP; it now re-resolves `api` every 10 s | Wait 10 s; otherwise `docker compose … restart web` |
| Ledger check fails on a case | Rows altered outside the application | Treat as an incident: the trigger was bypassed (superuser). Restore from backup; the hash chain names the first altered event |

## Backups

PostgreSQL holds users, sessions, dispositions, cases, the ledger and signatures:
`pg_dump` nightly; the demo pack and `reports/` are rebuilt from the build machine and do not
need backing up. Restores are verified with `GET /cases/{id}/verify-signature` on a sample.

## Metrics worth alerting on

* `rate(verita_http_requests_total{status=~"5.."}[5m]) > 0`
* p95 of `verita_http_request_duration_seconds` above 300 ms for 10 minutes
* `rate(verita_http_requests_total{status="429"}[5m])` sustained — abuse or a misconfigured proxy

Known gap: verifier runs and jobs executed inside the **worker** process are not scraped (the
worker serves no HTTP); their counters cover work done in the API process only.
