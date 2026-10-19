# ADR-003: Postgres-backed job queue

- **Status:** Accepted
- **Date:** 2026-10-19

## Context
Narrative generation, PDF rendering and some plan computations must run outside the request cycle.

## Decision
A jobs table consumed with SELECT ... FOR UPDATE SKIP LOCKED by a worker process. No Redis or Celery.

## Consequences
One fewer service to deploy and secure. Throughput is far below what this design can handle for the project's scale.
