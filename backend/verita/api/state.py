"""Lazily opened, read-only data artifacts shared by API requests."""

from __future__ import annotations

from fastapi import Request

from verita.core.config import Settings
from verita.core.errors import AppError
from verita.ml.evidence_store import evidence_path
from verita.pipeline.config import get_dataset
from verita.services.capacity import DecideArtifacts
from verita.services.evidence import EvidenceStore


def evidence_store(request: Request) -> EvidenceStore:
    store: EvidenceStore | None = getattr(request.app.state, "evidence_store", None)
    if store is None:
        settings: Settings = request.app.state.settings
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
        dataset = get_dataset(settings.dataset, root=settings.data_root)
        art = DecideArtifacts(dataset.artifacts_dir / "decide")
        request.app.state.decide_artifacts = art
    return art
