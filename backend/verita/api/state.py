"""Lazily opened, read-only data artifacts shared by API requests.

Two sources: the full run artifacts on the build machine (``data/`` and ``artifacts/``), or a
verified demo pack (``VERITA_DEMO_PACK``) in a deployed demo.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import Request

from verita.core.config import Settings
from verita.core.errors import AppError
from verita.demo.pack import PackEvidenceStore
from verita.ml.evidence_store import evidence_path
from verita.pipeline.config import get_dataset
from verita.services.capacity import DecideArtifacts
from verita.services.evidence import EvidenceStore, SubgraphSource


def evidence_store(request: Request) -> SubgraphSource:
    store: SubgraphSource | None = getattr(request.app.state, "evidence_store", None)
    if store is None:
        settings: Settings = request.app.state.settings
        if settings.demo_pack is not None:
            store = PackEvidenceStore(settings.demo_pack)
        else:
            dataset = get_dataset(settings.dataset, root=settings.data_root)
            path = evidence_path(dataset)
            if not path.exists():
                raise AppError(
                    503,
                    "no-evidence-store",
                    "Evidence store not built",
                    detail="Run `verita detect alerts` first.",
                )
            store = EvidenceStore(path)
        request.app.state.evidence_store = store
    return store


def decide_artifacts(request: Request) -> DecideArtifacts:
    art: DecideArtifacts | None = getattr(request.app.state, "decide_artifacts", None)
    if art is None:
        settings: Settings = request.app.state.settings
        if settings.demo_pack is not None:
            root = settings.demo_pack / "artifacts" / settings.dataset / "decide"
        else:
            root = get_dataset(settings.dataset, root=settings.data_root).artifacts_dir / "decide"
        art = DecideArtifacts(root)
        request.app.state.decide_artifacts = art
    return art


def metrics_path(settings: Settings) -> Path:
    if settings.demo_pack is not None:
        return settings.demo_pack / "reports" / "metrics.json"
    return settings.data_root / "reports" / "metrics.json"
