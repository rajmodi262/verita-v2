"""Stage orchestration: each stage writes its outputs, a run manifest, and its slice of the
validation report (M1.12, M1.13). The CLI and tests call these functions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import duckdb

from verita.pipeline.config import CONFIG_DIR, DataContract, Dataset, PipelineError
from verita.pipeline.graph import build_graph
from verita.pipeline.ingest import ContractViolationError, connect, ingest
from verita.pipeline.manifest import run_manifest
from verita.pipeline.patterns import link_patterns, parse_patterns
from verita.pipeline.splits import DEFAULT_FRACTIONS, compute_splits
from verita.pipeline.verify import verify_raw

# Days whose volume is below this share of the median day are reported as the sparse tail.
TAIL_VOLUME_SHARE = 0.01


def _update_report(dataset: Dataset, section: str, value: Any) -> None:
    path = dataset.validation_json
    report: dict[str, Any] = (
        json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"schema_version": 1}
    )
    report["dataset"] = dataset.name
    report[section] = value
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )


def stage_verify(dataset: Dataset, manifest_path: Path | None = None) -> list[dict[str, Any]]:
    with run_manifest("verify", dataset.name, dataset.manifests_dir) as m:
        checks = [c.to_dict() for c in verify_raw(dataset, manifest_path)]
        m.metrics["files"] = len(checks)
    _update_report(dataset, "files", checks)
    return checks


def stage_ingest(dataset: Dataset, contract: DataContract | None = None) -> dict[str, Any]:
    contract = contract or DataContract.load()
    cfg = {
        "contract_file": str(CONFIG_DIR / "data_contract.yaml"),
        "currencies": sorted(contract.currencies),
        "payment_formats": sorted(contract.payment_formats),
    }
    with run_manifest("ingest", dataset.name, dataset.manifests_dir, cfg) as m:
        m.add_input(dataset.transactions_csv)
        try:
            report = ingest(dataset, contract)
        except ContractViolationError as exc:
            _update_report(dataset, "contract", exc.report.to_dict())
            raise
        m.add_output(dataset.transactions_parquet)
        m.metrics.update(rows=report.rows, laundering=report.laundering)
    result = report.to_dict()
    _update_report(dataset, "contract", result)
    _update_report(dataset, "daily_volume", daily_volume(dataset))
    return result


def stage_link(dataset: Dataset, contract: DataContract | None = None) -> dict[str, Any]:
    contract = contract or DataContract.load()
    with run_manifest("link", dataset.name, dataset.manifests_dir) as m:
        m.add_input(dataset.patterns_txt)
        m.add_input(dataset.transactions_parquet)
        attempts = parse_patterns(dataset.patterns_txt, contract)
        report = link_patterns(dataset, attempts)
        m.add_output(dataset.pattern_links_parquet)
        m.metrics.update(attempts=report.attempts, coverage=round(report.coverage, 6))
    result = report.to_dict()
    _update_report(dataset, "patterns", result)
    return result


def stage_graph(dataset: Dataset) -> dict[str, Any]:
    with run_manifest("graph", dataset.name, dataset.manifests_dir) as m:
        m.add_input(dataset.transactions_parquet)
        m.add_input(dataset.pattern_links_parquet)
        report = build_graph(dataset)
        m.add_output(dataset.accounts_parquet)
        m.add_output(dataset.account_day_parquet)
        m.metrics.update(report.to_dict())
    result = report.to_dict()
    _update_report(dataset, "graph", result)
    return result


def stage_split(dataset: Dataset, fractions: dict[str, float] | None = None) -> dict[str, Any]:
    fractions = fractions or DEFAULT_FRACTIONS
    with run_manifest(
        "split", dataset.name, dataset.manifests_dir, {"fractions": fractions, "method": "count"}
    ) as m:
        m.add_input(dataset.transactions_parquet)
        splits = compute_splits(dataset, fractions)
        m.add_output(dataset.splits_json)
        m.metrics.update({k: v["rows"] for k, v in splits.summary.items()})
    result = splits.to_dict()
    _update_report(dataset, "splits", result)
    return result


def daily_volume(dataset: Dataset) -> dict[str, Any]:
    tx = str(dataset.transactions_parquet).replace("'", "''")
    rows = duckdb.sql(
        f"SELECT CAST(ts AS DATE) AS day, count(*), count(*) FILTER (WHERE is_laundering) "
        f"FROM read_parquet('{tx}') GROUP BY 1 ORDER BY 1"
    ).fetchall()
    days = [
        {
            "day": d.isoformat(),
            "rows": int(n),
            "laundering": int(p),
            "laundering_rate": round(int(p) / int(n), 6),
        }
        for d, n, p in rows
    ]
    counts = sorted(d["rows"] for d in days)
    median = counts[len(counts) // 2] if counts else 0
    tail = [d["day"] for d in days if median and d["rows"] < TAIL_VOLUME_SHARE * median]
    return {
        "days": days,
        "median_rows_per_day": median,
        "sparse_tail_days": tail,
        "tail_rule": f"rows < {TAIL_VOLUME_SHARE:.0%} of the median day",
    }


def stage_all(dataset: Dataset) -> dict[str, Any]:
    """verify → ingest → link → graph → split, stopping at the first failure."""
    connect(None).close()  # fail fast if DuckDB itself is unusable
    results: dict[str, Any] = {
        "files": stage_verify(dataset),
        "contract": stage_ingest(dataset),
        "patterns": stage_link(dataset),
        "graph": stage_graph(dataset),
        "splits": stage_split(dataset),
    }
    if not dataset.validation_json.exists():  # pragma: no cover - written by every stage
        msg = "validation report missing after a successful run"
        raise PipelineError(msg)
    return results
