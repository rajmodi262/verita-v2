"""`verita data split`: temporal splits by transaction count (M1.10, PIVOT §4.4).

Transactions are ordered by ``seq`` (timestamp, then file order) and cut at fixed fractions of
the *count*, never of the time span: the IBM files end in a sparse tail that is mostly
laundering, and a span-based cut would put the whole test set inside it.

    train  [0, 60%)      fit models
    hpo    [60%, 70%)    model selection / hyper-parameter search
    calib  [70%, 80%)    isotonic + conformal calibration
    test   [80%, 100%]   touched only by the evaluation stage

Boundaries are stored as ``seq`` values, so later stages assign splits with one comparison.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import duckdb

from verita.pipeline.config import Dataset, PipelineError

DEFAULT_FRACTIONS = {"train": 0.60, "hpo": 0.10, "calib": 0.10, "test": 0.20}
SPLIT_ORDER = ("train", "hpo", "calib", "test")


@dataclass
class Splits:
    method: str
    fractions: dict[str, float]
    total: int
    # split name -> [first seq, last seq] inclusive
    seq_ranges: dict[str, tuple[int, int]] = field(default_factory=dict)
    summary: dict[str, dict[str, Any]] = field(default_factory=dict)

    def split_of(self, seq: int) -> str:
        for name in SPLIT_ORDER:
            lo, hi = self.seq_ranges[name]
            if lo <= seq <= hi:
                return name
        msg = f"seq {seq} is outside every split"
        raise ValueError(msg)

    def sql_case(self, column: str = "seq") -> str:
        """A SQL CASE expression mapping ``column`` to its split name."""
        arms = " ".join(
            f"WHEN {column} BETWEEN {lo} AND {hi} THEN '{name}'"
            for name, (lo, hi) in self.seq_ranges.items()
        )
        return f"CASE {arms} END"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "method": self.method,
            "fractions": self.fractions,
            "total": self.total,
            "seq_ranges": {k: list(v) for k, v in self.seq_ranges.items()},
            "summary": self.summary,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Splits:
        return cls(
            method=str(data["method"]),
            fractions={k: float(v) for k, v in data["fractions"].items()},
            total=int(data["total"]),
            seq_ranges={k: (int(v[0]), int(v[1])) for k, v in data["seq_ranges"].items()},
            summary=dict(data.get("summary", {})),
        )


def seq_ranges(total: int, fractions: dict[str, float]) -> dict[str, tuple[int, int]]:
    if set(fractions) != set(SPLIT_ORDER):
        msg = f"fractions must name exactly {SPLIT_ORDER}"
        raise PipelineError(msg)
    if abs(sum(fractions.values()) - 1.0) > 1e-9 or min(fractions.values()) <= 0:  # noqa: PLR2004
        msg = "fractions must be positive and sum to 1"
        raise PipelineError(msg)
    if total < len(SPLIT_ORDER):
        msg = f"need at least {len(SPLIT_ORDER)} transactions to split, got {total}"
        raise PipelineError(msg)
    ranges: dict[str, tuple[int, int]] = {}
    start, cumulative = 0, 0.0
    for i, name in enumerate(SPLIT_ORDER):
        cumulative += fractions[name]
        remaining = len(SPLIT_ORDER) - 1 - i  # splits still to place after this one
        if remaining == 0:
            end = total - 1
        else:
            # At least one row here, and at least one row left for every later split.
            end = min(max(round(total * cumulative) - 1, start), total - 1 - remaining)
        ranges[name] = (start, end)
        start = end + 1
    return ranges


def compute_splits(
    dataset: Dataset,
    fractions: dict[str, float] | None = None,
    con: duckdb.DuckDBPyConnection | None = None,
) -> Splits:
    con = con or duckdb.connect()
    fractions = fractions or DEFAULT_FRACTIONS
    tx = str(dataset.transactions_parquet).replace("'", "''")
    row = con.execute(f"SELECT count(*) FROM read_parquet('{tx}')").fetchone()
    total = int(row[0]) if row else 0
    splits = Splits(
        method="count",
        fractions=dict(fractions),
        total=total,
        seq_ranges=seq_ranges(total, fractions),
    )
    for name, (lo, hi) in splits.seq_ranges.items():
        stats = con.execute(
            f"SELECT count(*), count(*) FILTER (WHERE is_laundering), min(ts), max(ts) "
            f"FROM read_parquet('{tx}') WHERE seq BETWEEN ? AND ?",
            [lo, hi],
        ).fetchone()
        if stats is None:  # pragma: no cover - aggregate always returns a row
            continue
        rows, positives = int(stats[0]), int(stats[1])
        splits.summary[name] = {
            "rows": rows,
            "laundering": positives,
            "laundering_rate": round(positives / rows, 6) if rows else 0.0,
            "from": stats[2].isoformat() if stats[2] else None,
            "to": stats[3].isoformat() if stats[3] else None,
        }
    dataset.artifacts_dir.mkdir(parents=True, exist_ok=True)
    dataset.splits_json.write_text(json.dumps(splits.to_dict(), indent=2) + "\n", encoding="utf-8")
    return splits


def load_splits(dataset: Dataset) -> Splits:
    if not dataset.splits_json.exists():
        msg = f"No splits for {dataset.name}; run `verita data split --dataset {dataset.name}`"
        raise PipelineError(msg)
    data: dict[str, Any] = json.loads(dataset.splits_json.read_text(encoding="utf-8"))
    return Splits.from_dict(data)
