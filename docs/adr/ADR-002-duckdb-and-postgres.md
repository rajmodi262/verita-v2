# ADR-002: DuckDB for analytics, Postgres for operational state

- **Status:** Accepted
- **Date:** 2026-10-19

## Context
Transactions and features are large, columnar and append-only. Alerts, cases, users and the ledger are small, transactional and need constraints and triggers.

## Decision
Transactions and features live in partitioned Parquet queried through DuckDB. Operational state lives in Postgres managed by Alembic migrations.

## Consequences
Two stores to reason about, each used for what it is good at. The API reads both through repository classes so services never touch SQL directly.
