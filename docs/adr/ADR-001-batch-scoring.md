# ADR-001: Batch scoring with a read-mostly API

- **Status:** Accepted
- **Date:** 2026-10-19

## Context
Training and feature building run over millions of transactions. The demo host is small, and evaluators need fast, reproducible responses.

## Decision
All training, calibration, scoring and forecasting run in an offline pipeline (Typer CLI tasks). The API serves precomputed results and performs only light per-request work: subgraph extraction, capacity planning for a chosen setting, case actions.

## Consequences
The demo is fast and reproducible from a hashed artifact pack. Real-time ingest is out of scope and documented as such. Online retraining is not possible from the UI.
