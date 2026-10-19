# ADR-005: Conformal prediction for the recall guarantee

- **Status:** Accepted
- **Date:** 2026-10-19

## Context
The compliance question is how much laundering is missed at a given threshold. Point estimates of recall on a test set do not bound future misses.

## Decision
Split conformal thresholds on calibration-set positives give a distribution-free recall guarantee under exchangeability. Mondrian (per-typology) thresholds protect rare typologies. Adaptive Conformal Inference handles drift during the replay.

## Consequences
The guarantee is only as good as its assumptions, so empirical coverage over time is always reported next to it, including months where it fails.
