"""Demo pack (M9.12): everything the deployed demo serves, in one verified directory.

The full evidence store (hundreds of MB) and the raw data stay on the build machine. A pack
holds:

``alerts.parquet`` / ``reasons.parquet``   every champion alert and its reason codes
``model_version.json``                      the champion's registry row
``subgraphs.jsonl.gz``                      precomputed evidence subgraphs for the riskiest
                                            alerts of each day (the ones a demo opens)
``artifacts/<dataset>/…``                   Decide artifacts, registry, validation, splits
``reports/metrics.json``                    the generated report
``manifest.json``                           SHA-256 of every file above

The API verifies the manifest at startup and refuses to run on a pack that does not match it;
``isotonic.joblib`` is only unpickled after its hash has been checked. Alerts whose evidence is
not in the pack answer 404 with a reason, never a fabricated graph.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import shutil
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pandas as pd
from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from verita.core.errors import AppError
from verita.db.detect_models import Alert, AlertReason, AlertStatus, ModelVersion
from verita.pipeline.config import REPO_ROOT, Dataset
from verita.services import models as governance
from verita.services.alerts import champion
from verita.services.evidence import AlertRef, EvidenceStore

FORMAT = "verita-demo-pack/1"
NOT_FROM_PACK = {
    "id",
    "created_at",
    "is_champion",
    "status",
    "approved_by_id",
    "approved_at",
    "promoted_by_id",
    "promoted_at",
    "decision_note",
    "bypass_reason",
}
CHUNK = 10_000
ARTIFACT_FILES = (
    "detect/registry.json",
    "detect/metrics.json",
    "data_validation.json",
    "splits.json",
    "decide/calibration.json",
    "decide/coverage.json",
    "decide/drift.json",
    "decide/forecast.json",
    "decide/frontier.json",
    "decide/operations.json",
    "decide/queue.json",
    "decide/thresholds.json",
    "decide/isotonic.joblib",
)
ALERT_COLUMNS = [c.name for c in Alert.__table__.columns]
REASON_COLUMNS = [c.name for c in AlertReason.__table__.columns]


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return cast("list[dict[str, Any]]", frame.to_dict(orient="records"))


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build_pack(
    dataset: Dataset, db: Session, out: Path, subgraphs_per_day: int = 150
) -> dict[str, Any]:
    version = champion(db)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    alerts = pd.read_sql(
        select(*Alert.__table__.columns).where(Alert.model_version_id == version.id),
        db.connection(),
    )
    # A pack is a clean starting point: no dispositions or cases exist in a fresh deployment.
    alerts["status"] = AlertStatus.OPEN.value
    alerts.to_parquet(out / "alerts.parquet", index=False)
    reasons = pd.read_sql(
        select(*AlertReason.__table__.columns)
        .join(Alert, Alert.id == AlertReason.alert_id)
        .where(Alert.model_version_id == version.id),
        db.connection(),
    )
    reasons.to_parquet(out / "reasons.parquet", index=False)
    (out / "model_version.json").write_text(
        json.dumps(
            {c.name: getattr(version, c.name) for c in ModelVersion.__table__.columns},
            default=str,
            indent=2,
        ),
        encoding="utf-8",
    )

    store = EvidenceStore(dataset.processed_dir / "evidence.duckdb")
    top = (
        alerts.sort_values(["alert_date", "score", "id"], ascending=[True, False, True])
        .groupby("alert_date")
        .head(subgraphs_per_day)
    )
    with gzip.open(out / "subgraphs.jsonl.gz", "wt", encoding="utf-8") as f:
        for row in _records(top):
            alert_id = int(row["id"])
            ref = AlertRef(
                alert_id,
                str(row["account_id"]),
                pd.Timestamp(row["alert_date"]).date(),
                int(row["top_txn_id"]),
                version.threshold,
            )
            line = {"alert_id": alert_id, "subgraph": store.subgraph(ref)}
            f.write(json.dumps(line, default=str) + "\n")

    for rel in ARTIFACT_FILES:
        src = dataset.artifacts_dir / rel
        if src.exists():
            dst = out / "artifacts" / dataset.name / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    metrics = REPO_ROOT / "reports" / "metrics.json"
    if metrics.exists():
        (out / "reports").mkdir()
        shutil.copy2(metrics, out / "reports" / "metrics.json")

    files = {p.relative_to(out).as_posix(): _sha(p) for p in sorted(out.rglob("*")) if p.is_file()}
    manifest = {
        "format": FORMAT,
        "dataset": dataset.name,
        "created_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "model": {"name": version.name, "champion_sha256": version.champion_sha256},
        "counts": {"alerts": len(alerts), "reasons": len(reasons), "subgraphs": len(top)},
        "files": files,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def verify_pack(pack: Path) -> list[str]:
    """Every problem with the pack; empty means it matches its manifest exactly."""
    manifest_path = pack / "manifest.json"
    if not manifest_path.exists():
        return ["manifest.json is missing"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    problems = []
    if manifest.get("format") != FORMAT:
        problems.append(f"unknown pack format {manifest.get('format')!r}")
    listed = manifest.get("files", {})
    for rel, sha in listed.items():
        path = pack / rel
        if not path.exists():
            problems.append(f"{rel}: missing")
        elif _sha(path) != sha:
            problems.append(f"{rel}: SHA-256 does not match the manifest")
    extra = (
        {p.relative_to(pack).as_posix() for p in pack.rglob("*") if p.is_file()}
        - set(listed)
        - {"manifest.json"}
    )
    problems += [f"{rel}: not in the manifest" for rel in sorted(extra)]
    return problems


def load_pack(db: Session, pack: Path) -> dict[str, Any]:
    """Load a verified pack's alerts into the database (idempotent per champion model)."""
    problems = verify_pack(pack)
    if problems:
        msg = "demo pack failed verification: " + "; ".join(problems[:5])
        raise ValueError(msg)
    meta = json.loads((pack / "model_version.json").read_text(encoding="utf-8"))
    existing = db.scalar(
        select(ModelVersion).where(ModelVersion.champion_sha256 == meta["champion_sha256"])
    )
    if existing is not None:
        return {
            "loaded": False,
            "reason": "this champion is already loaded",
            "model_version_id": existing.id,
        }
    # Governance does not travel: reviewers on the build machine are not users here. The
    # validation report does travel (with its hash); the model is seated with the demo bypass.
    version = ModelVersion(
        **{
            k: v
            for k, v in meta.items()
            if k not in NOT_FROM_PACK and k in ModelVersion.__table__.columns
        }
    )
    db.add(version)
    db.flush()
    governance.bypass(db, version, governance.DEMO_PACK, "prod")
    alerts = pd.read_parquet(pack / "alerts.parquet")
    reasons = pd.read_parquet(pack / "reasons.parquet")
    old_ids = alerts["id"].tolist()
    for start in range(0, len(old_ids), CHUNK):  # SQLite caps bound parameters per statement
        chunk = old_ids[start : start + CHUNK]
        db.execute(delete(AlertReason).where(AlertReason.alert_id.in_(chunk)))
        db.execute(delete(Alert).where(Alert.id.in_(chunk)))
    alerts = alerts.assign(model_version_id=version.id)
    records = _records(alerts)
    for r in records:
        r["alert_date"] = pd.Timestamp(r["alert_date"]).date()
        r["created_at"] = pd.Timestamp(r["created_at"]).to_pydatetime()
        r["truth_typologies"] = (
            list(r["truth_typologies"]) if r["truth_typologies"] is not None else []
        )
    db.execute(insert(Alert), records)
    db.execute(insert(AlertReason), _records(reasons))
    db.flush()
    return {
        "loaded": True,
        "model_version_id": version.id,
        "alerts": len(alerts),
        "reasons": len(reasons),
    }


class PackEvidenceStore:
    """Serves the pack's precomputed subgraphs with the EvidenceStore interface."""

    def __init__(self, pack: Path) -> None:
        self.pack = pack
        self._index: dict[int, dict[str, Any]] | None = None
        self._lock = threading.Lock()

    def _load(self) -> dict[int, dict[str, Any]]:
        with self._lock:
            return self._load_locked()

    def _load_locked(self) -> dict[int, dict[str, Any]]:
        if self._index is None:
            index = {}
            with gzip.open(self.pack / "subgraphs.jsonl.gz", "rt", encoding="utf-8") as f:
                for line in f:
                    row = json.loads(line)
                    index[int(row["alert_id"])] = row["subgraph"]
            self._index = index
        return self._index

    def subgraph(self, alert: AlertRef) -> dict[str, Any]:
        graph = self._load().get(alert.id)
        if graph is None:
            raise AppError(
                404,
                "evidence-not-in-pack",
                "Evidence for this alert is not in the demo pack",
                detail="The demo ships evidence for the riskiest alerts of each day only.",
            )
        return graph
