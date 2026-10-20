"""Evidence Room: serves the generated ``reports/metrics.json`` (PIVOT §15) — never live math."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from fastapi import APIRouter, Depends, Request

from verita.api.deps import require_role
from verita.core.errors import AppError
from verita.db.models import Role

router = APIRouter(prefix="/evidence-room", tags=["evidence-room"])
READERS = Depends(require_role(Role.ANALYST, Role.MLRO, Role.VALIDATOR, Role.REVIEWER))


@router.get("/metrics", dependencies=[READERS])
def metrics(request: Request) -> dict[str, Any]:
    """The metrics file every number in the product comes from, plus its SHA-256."""
    path = request.app.state.settings.data_root / "reports" / "metrics.json"
    if not path.exists():
        raise AppError(
            503, "no-metrics", "No evaluation report yet", detail="Run `verita report build`."
        )
    raw = path.read_bytes()
    body: dict[str, Any] = json.loads(raw)
    return {"sha256": hashlib.sha256(raw).hexdigest(), "metrics": body}


@router.get("/headline")
def headline(request: Request) -> dict[str, Any]:
    """Public: the headline figures for the landing page (no detail, no lineage)."""
    data = metrics(request)
    m = data["metrics"]
    return {
        "sha256": data["sha256"],
        "git_sha": m.get("git_sha"),
        "schema_version": m.get("schema_version"),
        "synthetic_data_notice": m.get("synthetic_data_notice"),
        "headline": m.get("headline", []),
    }
