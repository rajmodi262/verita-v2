# ADR-008: Demo hosting — one VM running the compose stack, same origin

- **Status:** Accepted
- **Date:** 2026-10-20

## Context
The demo needs PostgreSQL (append-only trigger, `SKIP LOCKED` job queue), a long-running job
worker, a 40 MB demo pack mounted read-only, a signing key as a secret, and the SPA and the API
on **one origin** (session cookies are `SameSite=Lax`; splitting origins would need
cross-site cookies and CORS credentials, which this design avoids on purpose). The API image is
large (~1.8 GB: LightGBM, OR-Tools, statsmodels) and wants ~2 GB of memory with two workers.

Options considered:

| Option | For | Against |
|---|---|---|
| Static SPA on Vercel + API on Render (v1's setup) | Free tiers | Two origins (cookie and CSRF model breaks), free API instances sleep and have 512 MB |
| Fly.io machines | Simple, global | Volumes per region; still needs Postgres elsewhere; memory pricing for 2 GB |
| **One small VM (2 vCPU, 4 GB) running `deploy/docker-compose.yml` behind Caddy/HTTPS** | Exactly the tested stack, one origin, real Postgres, worker, secrets | We operate the VM ourselves |

## Decision
Deploy the compose stack unchanged to one VM (any provider), with a TLS terminator (Caddy) in
front of the `web` service. The release workflow builds and publishes the images and the demo
pack; the VM pulls a tag and runs `docker compose up -d`, then `scripts/smoke.py` against the
public URL.

## Consequences
* What runs in the demo is byte-for-byte what CI and the smoke test exercised.
* Scaling beyond one VM needs a shared rate-limit store (Redis) and a managed Postgres; the
  code does not change.
* Someone holds the VM credentials and the signing key; RUNBOOK.md documents rotation.
