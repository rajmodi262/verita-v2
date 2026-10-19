# Accepted security exceptions

Every exception is time-boxed and re-checked at each milestone.

| ID | Package | Advisory | Scope | Why accepted | Re-check |
|----|---------|----------|-------|--------------|----------|
| SE-1 | `braces` (via `stylelint` → `micromatch`) | GHSA-vfj7-8cjw-p6xm (ReDoS-style stack exhaustion on deeply nested patterns) | Dev-only lint tool; never shipped, only processes our own globs | No patched release exists upstream; CI gates `npm audit --omit=dev --audit-level=high` (production deps are clean) | Every milestone |
| SE-2 | Ruff S608 / Bandit B608 ("SQL built from strings") | n/a | `verita/pipeline/*.py` only | Pipeline SQL is assembled from internal constants, contract enums escaped as SQL literals, and our own file paths (escaped). No user input reaches it, and no endpoint runs user SQL (ADR-007). Ruff S608 stays active for every other module. | When the pipeline gains any user-supplied parameter |
