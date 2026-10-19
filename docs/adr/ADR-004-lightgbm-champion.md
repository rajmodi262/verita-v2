# ADR-004: LightGBM champion, GNN challenger

- **Status:** Accepted
- **Date:** 2026-10-19

## Context
Graph neural networks are the research state of the art on the IBM AML benchmark but are costly on CPU and harder to explain to an analyst.

## Decision
The production model is LightGBM over transaction plus engineered graph features, explained with SHAP. A GNN edge classifier is trained as a challenger and reported in the comparison table.

## Consequences
Explanations stay exact and cheap. If the GNN wins on F1 by a meaningful margin, the trade-off is reported honestly rather than hidden.
