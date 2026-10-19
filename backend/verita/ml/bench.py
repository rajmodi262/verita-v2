"""Latency benchmarks for the interactive paths (M3.18, M5 exit criterion).

Measured in-process (no HTTP) on the loaded dataset, so the numbers isolate the work the API
does per request. Results go to ``artifacts/<dataset>/bench.json``.
"""

from __future__ import annotations

import json
import time
from datetime import date
from typing import Any

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from verita.db.detect_models import Alert
from verita.pipeline.config import Dataset
from verita.services import capacity as cap
from verita.services.alerts import champion
from verita.services.evidence import AlertRef, EvidenceStore


def _summary(ms: list[float]) -> dict[str, float]:
    arr = np.asarray(ms)
    return {
        "n": len(ms),
        "p50_ms": round(float(np.percentile(arr, 50)), 1),
        "p95_ms": round(float(np.percentile(arr, 95)), 1),
        "max_ms": round(float(arr.max()), 1),
    }


def bench_subgraph(
    dataset: Dataset, db: Session, samples: int = 200, seed: int = 0
) -> dict[str, Any]:
    """Subgraph extraction for a random sample of alerts, stratified by nothing: the queue's
    real mix of quiet accounts and hubs."""
    version = champion(db)
    rows = db.execute(
        select(Alert.id, Alert.account_id, Alert.alert_date, Alert.top_txn_id).where(
            Alert.model_version_id == version.id
        )
    ).all()
    rng = np.random.default_rng(seed)
    picks = rng.choice(len(rows), size=min(samples, len(rows)), replace=False)
    store = EvidenceStore(dataset.processed_dir / "evidence.duckdb")
    threshold = float(version.threshold)
    times, nodes, edges = [], [], []
    for i in picks:
        r = rows[int(i)]
        ref = AlertRef(int(r[0]), str(r[1]), r[2], int(r[3]), threshold)
        started = time.perf_counter()
        graph = store.subgraph(ref)
        times.append((time.perf_counter() - started) * 1000)
        nodes.append(len(graph["nodes"]))
        edges.append(len(graph["edges"]))
    return {
        **_summary(times),
        "target_p95_ms": 500,
        "mean_nodes": round(float(np.mean(nodes)), 1),
        "mean_edges": round(float(np.mean(edges)), 1),
    }


def bench_plan(
    dataset: Dataset, db: Session, analysts: tuple[int, ...] = (3, 6, 12)
) -> dict[str, Any]:
    """Exact plans for every replay day: first call (loads the day) and warm calls."""
    art = cap.DecideArtifacts(dataset.artifacts_dir / "decide")
    days = cap.meta(art)["days"]
    cold: list[float] = []
    warm: list[float] = []
    for day in days:
        d = date.fromisoformat(day)
        for i, n in enumerate(analysts):
            started = time.perf_counter()
            cap.compute_plan(db, art, d, n, 0.05, "pooled")
            (cold if i == 0 else warm).append((time.perf_counter() - started) * 1000)
    return {"cold": _summary(cold), "warm": _summary(warm), "days": len(days)}


def run_bench(dataset: Dataset, db: Session) -> dict[str, Any]:
    result = {"subgraph": bench_subgraph(dataset, db), "plan": bench_plan(dataset, db)}
    out = dataset.artifacts_dir / "bench.json"
    out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result
