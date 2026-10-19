# Contributing

## Setup
See the Quickstart in [README.md](README.md).

## Before you push
```bash
cd backend  && uv run poe check     # ruff, format check, mypy, pytest
cd frontend && npm run check        # eslint, stylelint, prettier, tsc, vitest
```
CI runs the same commands and every gate is blocking.

## Conventions
- Commits: Conventional Commits (`feat:`, `fix:`, `test:`, `docs:`, `chore:`, `refactor:`).
- Every task in [TRACKER.md](TRACKER.md) is ticked in the same commit as the work.
- No hand-typed metrics in docs or UI (PIVOT §15).
- No inline styles and no `any` in the frontend; no bare `except` in the backend.
- New decisions get an ADR in `docs/adr/`.
