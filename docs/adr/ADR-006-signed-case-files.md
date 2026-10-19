# ADR-006: Ed25519 + RFC 8785 + Merkle tree for case files

- **Status:** Accepted
- **Date:** 2026-10-19

## Context
Filed reports must be provably unaltered, and the proof must be checkable by someone who does not trust the server.

## Decision
Evidence and narrative are canonicalized with RFC 8785, hashed into a Merkle tree, and the root is signed with Ed25519. Case events are stored in an append-only Postgres table with a persisted hash chain. An offline CLI verifies exported files with only the public key.

## Consequences
Standard primitives, no custom crypto. Key management (rotation, key IDs) becomes an operational responsibility documented in the runbook.
