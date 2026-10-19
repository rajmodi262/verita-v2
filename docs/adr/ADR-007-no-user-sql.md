# ADR-007: No user-supplied SQL

- **Status:** Accepted
- **Date:** 2026-10-19

## Context
v1's SQL playground was the largest attack surface and needed a fragile blocklist.

## Decision
v2 exposes no endpoint that executes user-written SQL. All queries are parameterized and authored in the codebase.

## Consequences
Analysts cannot run ad-hoc queries in the UI. This is an accepted product limitation.
