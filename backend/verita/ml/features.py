"""Detect features (PIVOT §6.2, M2.01–M2.06).

Every feature of a transaction at time *t* reads only events strictly before *t*'s minute
(window frames end ``1 MINUTE PRECEDING``; the cycle search only follows edges with time < t).
Same-minute activity is therefore invisible, which is conservative but leak-free. The property
test in ``tests/ml/test_features_asof.py`` enforces this.

Groups (used by the ablation study):

* ``transaction`` — the payment itself: amounts, currencies, format, calendar, flags
* ``velocity``    — how many payments the sender and receiver made/received in 1h / 24h / 7d
* ``fan``         — how many *distinct* counterparties in those windows (fan-in / fan-out)
* ``recency``     — account age, minutes since the last payment in and out (pass-through)
* ``cycle``       — whether this payment closes a time-respecting cycle of ≤ 5 hops in 7 days
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import duckdb
import numpy as np
import numpy.typing as npt
import pandas as pd
from numba import njit, prange

from verita.pipeline.config import Dataset

WINDOWS = {"1h": "INTERVAL 1 HOUR", "24h": "INTERVAL 24 HOUR", "7d": "INTERVAL 7 DAY"}
CYCLE_MAX_EDGES = 4  # path v → … → u, so the closed cycle has at most 5 edges
CYCLE_WINDOW_MIN = 7 * 24 * 60
CYCLE_MAX_EXPANSIONS = 20_000  # per query; hitting it is counted and reported

TRANSACTION = [
    "log_amount_paid",
    "log_amount_received",
    "log_fx_ratio",
    "cross_currency",
    "currency_paid_code",
    "currency_received_code",
    "payment_format_code",
    "hour",
    "weekday",
    "round_amount",
    "self_transfer",
    "cross_bank",
]
VELOCITY = [f"{side}_{d}_n_{w}" for side in ("s", "r") for d in ("out", "in") for w in WINDOWS]
FAN = [f"{side}_{d}_{w}" for side in ("s", "r") for d in ("payees", "payers") for w in WINDOWS]
RECENCY = [
    f"{side}_{f}"
    for side in ("s", "r")
    for f in ("age_min", "since_last_in_min", "since_last_out_min")
]
CYCLE = ["cycle_found", "cycle_edges"]

FEATURE_GROUPS: dict[str, list[str]] = {
    "transaction": TRANSACTION,
    "velocity": VELOCITY,
    "fan": FAN,
    "recency": RECENCY,
    "cycle": CYCLE,
}
ALL_FEATURES = [f for group in FEATURE_GROUPS.values() for f in group]
CATEGORICAL = ["currency_paid_code", "currency_received_code", "payment_format_code"]

# Stable category codes (sorted contract enums) so codes never depend on the data seen.
CURRENCIES = sorted(
    [
        "Australian Dollar",
        "Bitcoin",
        "Brazil Real",
        "Canadian Dollar",
        "Euro",
        "Mexican Peso",
        "Ruble",
        "Rupee",
        "Saudi Riyal",
        "Shekel",
        "Swiss Franc",
        "UK Pound",
        "US Dollar",
        "Yen",
        "Yuan",
    ]
)
PAYMENT_FORMATS = sorted(
    ["ACH", "Bitcoin", "Cash", "Cheque", "Credit Card", "Reinvestment", "Wire"]
)


@dataclass
class FeatureReport:
    rows: int
    features: int
    seconds: dict[str, float] = field(default_factory=dict)
    cycle_queries: int = 0
    cycle_found: int = 0
    cycle_capped: int = 0

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def _case(column: str, values: list[str]) -> str:
    arms = " ".join(f"WHEN '{v}' THEN {i}" for i, v in enumerate(values))
    return f"CASE {column} {arms} ELSE -1 END"


def _account_window_sql(tx: str) -> str:
    """Per-event window features for both endpoints of every transaction."""
    aggs = []
    for w in WINDOWS:
        aggs += [
            f"count(*) FILTER (WHERE dir = 's') OVER w{w} AS out_n_{w}",
            f"count(*) FILTER (WHERE dir = 'r') OVER w{w} AS in_n_{w}",
            f"count(DISTINCT cp) FILTER (WHERE dir = 's') OVER w{w} AS payees_{w}",
            f"count(DISTINCT cp) FILTER (WHERE dir = 'r') OVER w{w} AS payers_{w}",
        ]
    windows = ", ".join(
        f"w{w} AS (PARTITION BY account ORDER BY ts RANGE BETWEEN {iv} PRECEDING "
        f"AND INTERVAL 1 MINUTE PRECEDING)"
        for w, iv in WINDOWS.items()
    )
    return f"""
        WITH events AS (
            SELECT from_id AS account, to_id AS cp, ts, 's' AS dir, txn_id FROM read_parquet('{tx}')
            UNION ALL
            SELECT to_id, from_id, ts, 'r', txn_id FROM read_parquet('{tx}')
        )
        SELECT txn_id, dir, {", ".join(aggs)},
            date_diff('minute',
                min(ts) OVER wall, ts) AS age_min,
            date_diff('minute', max(ts) FILTER (WHERE dir = 'r') OVER wall, ts)
                AS since_last_in_min,
            date_diff('minute', max(ts) FILTER (WHERE dir = 's') OVER wall, ts)
                AS since_last_out_min
        FROM events
        WINDOW {windows},
            wall AS (PARTITION BY account ORDER BY ts RANGE BETWEEN UNBOUNDED PRECEDING
                     AND INTERVAL 1 MINUTE PRECEDING)
    """


def _side_columns(side: str) -> str:
    cols = []
    for w in WINDOWS:
        cols += [
            f"{side}.out_n_{w} AS {side}_out_n_{w}",
            f"{side}.in_n_{w} AS {side}_in_n_{w}",
            f"{side}.payees_{w} AS {side}_payees_{w}",
            f"{side}.payers_{w} AS {side}_payers_{w}",
        ]
    for f in ("age_min", "since_last_in_min", "since_last_out_min"):
        cols.append(f"coalesce({side}.{f}, -1) AS {side}_{f}")
    return ", ".join(cols)


def build_tabular(con: duckdb.DuckDBPyConnection, tx: str) -> pd.DataFrame:
    con.execute(f"CREATE OR REPLACE TEMP TABLE acct AS {_account_window_sql(tx)}")
    frame: pd.DataFrame = con.execute(f"""
        SELECT t.txn_id, t.seq, t.ts, t.is_laundering,
            ln(1 + t.amount_paid) AS log_amount_paid,
            ln(1 + t.amount_received) AS log_amount_received,
            CASE WHEN t.amount_paid > 0 THEN ln(t.amount_received / t.amount_paid) ELSE 0 END
                AS log_fx_ratio,
            CAST(t.currency_paid <> t.currency_received AS INTEGER) AS cross_currency,
            {_case("t.currency_paid", CURRENCIES)} AS currency_paid_code,
            {_case("t.currency_received", CURRENCIES)} AS currency_received_code,
            {_case("t.payment_format", PAYMENT_FORMATS)} AS payment_format_code,
            hour(t.ts) AS hour, isodow(t.ts) AS weekday,
            CAST(t.amount_paid >= 100 AND t.amount_paid = round(t.amount_paid, -2) AS INTEGER)
                AS round_amount,
            CAST(t.from_id = t.to_id AS INTEGER) AS self_transfer,
            CAST(t.from_bank <> t.to_bank AS INTEGER) AS cross_bank,
            {_side_columns("s")}, {_side_columns("r")}
        FROM read_parquet('{tx}') t
        JOIN acct s ON s.txn_id = t.txn_id AND s.dir = 's'
        JOIN acct r ON r.txn_id = t.txn_id AND r.dir = 'r'
        ORDER BY t.seq
    """).df()
    con.execute("DROP TABLE acct")
    return frame


# ── time-respecting cycles (numba) ───────────────────────────────────────────


@njit(cache=True)
def _search(  # noqa: PLR0912 - one tight numba loop
    start: int,
    target: int,
    t_close: int,
    t_min: int,
    indptr: npt.NDArray[np.int64],
    dst: npt.NDArray[np.int64],
    times: npt.NDArray[np.int64],
    max_edges: int,
    max_expansions: int,
) -> tuple[int, bool]:
    """Shortest path start → target with non-decreasing edge times in [t_min, t_close).

    Returns (edges in the path or 0, whether the expansion cap was hit). Iterative DFS over a
    CSR whose per-node edges are sorted by time.
    """
    stack_node = np.empty(max_edges * 256 + 1, dtype=np.int64)
    stack_depth = np.empty(max_edges * 256 + 1, dtype=np.int64)
    stack_time = np.empty(max_edges * 256 + 1, dtype=np.int64)
    top = 0
    stack_node[0], stack_depth[0], stack_time[0] = start, 0, t_min
    top = 1
    best = 0
    expansions = 0
    while top > 0:
        top -= 1
        node, depth, after = stack_node[top], stack_depth[top], stack_time[top]
        lo, hi = indptr[node], indptr[node + 1]
        # first edge with time >= after (binary search; edges are time-sorted)
        a, b = lo, hi
        while a < b:
            mid = (a + b) // 2
            if times[mid] < after:
                a = mid + 1
            else:
                b = mid
        for e in range(a, hi):
            if times[e] >= t_close:
                break
            expansions += 1
            if expansions > max_expansions:
                return best, True
            nxt = dst[e]
            if nxt == node:
                continue  # ignore self-transfers
            if nxt == target:
                length = depth + 1
                if best == 0 or length < best:
                    best = length
                    if best == 1:
                        return best, False
                continue
            if depth + 1 < max_edges:
                if top >= stack_node.shape[0]:
                    return best, True  # search frontier too wide: report as capped
                stack_node[top], stack_depth[top], stack_time[top] = nxt, depth + 1, times[e]
                top += 1
    return best, False


@njit(parallel=True, cache=True)
def _all_cycles(
    src: npt.NDArray[np.int64],
    dst_q: npt.NDArray[np.int64],
    t: npt.NDArray[np.int64],
    indptr: npt.NDArray[np.int64],
    csr_dst: npt.NDArray[np.int64],
    csr_times: npt.NDArray[np.int64],
    window: int,
    max_edges: int,
    max_expansions: int,
) -> tuple[npt.NDArray[np.int64], npt.NDArray[np.bool_]]:
    n = src.shape[0]
    out = np.zeros(n, dtype=np.int64)
    capped = np.zeros(n, dtype=np.bool_)
    for i in prange(n):
        u, v = src[i], dst_q[i]
        if u == v:
            continue
        found, hit = _search(
            v, u, t[i], t[i] - window, indptr, csr_dst, csr_times, max_edges, max_expansions
        )
        out[i] = found
        capped[i] = hit
    return out, capped


def cycle_features(
    frame: pd.DataFrame, con: duckdb.DuckDBPyConnection, tx: str
) -> tuple[npt.NDArray[np.int64], int]:
    edges = con.execute(f"""
        SELECT txn_id, from_id, to_id, date_diff('minute', TIMESTAMP '2000-01-01', ts) AS m
        FROM read_parquet('{tx}') ORDER BY txn_id
    """).df()
    codes, uniques = pd.factorize(pd.concat([edges["from_id"], edges["to_id"]]), sort=False)
    n_edges = len(edges)
    src = codes[:n_edges].astype(np.int64)
    dst = codes[n_edges:].astype(np.int64)
    minutes = edges["m"].to_numpy(dtype=np.int64)
    order = np.lexsort((minutes, src))
    counts = np.bincount(src, minlength=len(uniques))
    indptr = np.concatenate([[0], np.cumsum(counts)]).astype(np.int64)
    found, capped = _all_cycles(
        src,
        dst,
        minutes,
        indptr,
        dst[order],
        minutes[order],
        CYCLE_WINDOW_MIN,
        CYCLE_MAX_EDGES,
        CYCLE_MAX_EXPANSIONS,
    )
    by_txn = pd.Series(found, index=edges["txn_id"].to_numpy())
    aligned = by_txn.reindex(frame["txn_id"].to_numpy()).to_numpy(dtype=np.int64)
    return aligned, int(capped.sum())


def build_features(dataset: Dataset, con: duckdb.DuckDBPyConnection | None = None) -> FeatureReport:
    """Write ``features.parquet`` (txn_id, seq, ts, label, all features), ordered by seq."""
    con = con or duckdb.connect()
    con.execute("SET enable_progress_bar = false")
    tx = str(dataset.transactions_parquet).replace("'", "''")
    timings: dict[str, float] = {}
    started = time.perf_counter()
    frame = build_tabular(con, tx)
    timings["tabular"] = round(time.perf_counter() - started, 2)
    started = time.perf_counter()
    edges, capped = cycle_features(frame, con, tx)
    frame["cycle_edges"] = edges + 1  # include the closing payment
    frame.loc[edges == 0, "cycle_edges"] = 0
    frame["cycle_found"] = (edges > 0).astype(np.int64)
    timings["cycle"] = round(time.perf_counter() - started, 2)
    out = dataset.features_parquet
    frame.to_parquet(out, index=False, compression="zstd")
    return FeatureReport(
        rows=len(frame),
        features=len(ALL_FEATURES),
        seconds=timings,
        cycle_queries=len(frame),
        cycle_found=int(frame["cycle_found"].sum()),
        cycle_capped=capped,
    )
