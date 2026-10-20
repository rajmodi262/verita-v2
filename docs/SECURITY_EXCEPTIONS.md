# Accepted security exceptions

Every exception is time-boxed and re-checked at each milestone.

| ID | Package | Advisory | Scope | Why accepted | Re-check |
|----|---------|----------|-------|--------------|----------|
| SE-1 | `braces` (via `stylelint` → `micromatch`) | GHSA-vfj7-8cjw-p6xm (ReDoS-style stack exhaustion on deeply nested patterns) | Dev-only lint tool; never shipped, only processes our own globs | No patched release exists upstream; CI gates `npm audit --omit=dev --audit-level=high` (production deps are clean) | Every milestone |
| SE-2 | Ruff S608 / Bandit B608 ("SQL built from strings") | n/a | `verita/pipeline/*.py` only | Pipeline SQL is assembled from internal constants, contract enums escaped as SQL literals, and our own file paths (escaped). No user input reaches it, and no endpoint runs user SQL (ADR-007). Ruff S608 stays active for every other module. | When the pipeline gains any user-supplied parameter |
| SE-3 | Debian 13 base packages in the API image (`util-linux`, `glibc`, `perl-base`, `gcc-14` runtime libs, `ncurses`, `zlib1g`, `acl`) | 55 High (grype, 2026-10-20); 54 marked *won't fix* by Debian security, 1 *not fixed* | OS layer of `python:3.12-slim`; none of these binaries is invoked by the API, which runs as a non-root user on a read-only root filesystem | No patched package exists; `apt-get upgrade` runs at build time so any fix lands on the next build. CI fails on every **fixable** High/Critical (`grype --only-fixed --fail-on high`). The web image has no High/Critical at all | Every release; re-scan on every CI run |
