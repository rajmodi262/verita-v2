"""`verita data ingest`: raw IBM CSV → validated, typed Parquet (M1.02, M1.05, M1.08).

The data contract is enforced in DuckDB over the raw text, so it scales out of core to the full
files. Any hard violation stops the stage; the report is still written so the cause is visible.

Output ``transactions.parquet`` columns:

=================  =========  ===============================================================
txn_id             BIGINT     0-based line order in the source file — the stable identifier
seq                BIGINT     0-based rank by (ts, txn_id) — the temporal order used by splits
ts                 TIMESTAMP  minute resolution, as in the source
from_bank          INTEGER    bank ids are compared numerically ("0110" == "110")
from_account       VARCHAR
to_bank            INTEGER
to_account         VARCHAR
from_id / to_id    VARCHAR    "<bank>:<account>" — the account node id used everywhere
amount_received    DOUBLE
currency_received  VARCHAR
amount_paid        DOUBLE
currency_paid      VARCHAR
payment_format     VARCHAR
is_laundering      BOOLEAN
=================  =========  ===============================================================
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import duckdb

from verita.pipeline.config import DataContract, Dataset, PipelineError

RAW_NAMES = [
    "ts",
    "from_bank",
    "from_account",
    "to_bank",
    "to_account",
    "amount_received",
    "currency_received",
    "amount_paid",
    "currency_paid",
    "payment_format",
    "label",
]
HARD_CHECKS = (
    "bad_timestamp",
    "bad_bank",
    "missing_account",
    "bad_amount",
    "unknown_currency",
    "unknown_payment_format",
    "bad_label",
)


class ContractViolationError(PipelineError):
    def __init__(self, report: IngestReport) -> None:
        bad = {k: v for k, v in report.violations.items() if v}
        super().__init__(f"Data contract violated in {report.source}: {bad}")
        self.report = report


@dataclass
class IngestReport:
    source: str
    rows: int = 0
    laundering: int = 0
    ts_min: str | None = None
    ts_max: str | None = None
    violations: dict[str, int] = field(default_factory=dict)
    facts: dict[str, int] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return not any(self.violations.values())

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "rows": self.rows,
            "laundering": self.laundering,
            "ts_min": self.ts_min,
            "ts_max": self.ts_max,
            "passed": self.passed,
            "violations": self.violations,
            "facts": self.facts,
        }


def connect(temp_dir: Path | None = None) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    if temp_dir is not None:
        temp_dir.mkdir(parents=True, exist_ok=True)
        con.execute("SET temp_directory = ?", [str(temp_dir)])
    con.execute("SET preserve_insertion_order = true")
    return con


def _sql_list(values: frozenset[str]) -> str:
    return ", ".join("'" + v.replace("'", "''") + "'" for v in sorted(values))


def load_raw(con: duckdb.DuckDBPyConnection, csv_path: Path) -> None:
    """Load the CSV as text into table ``raw``; ``rowid`` then equals the file line order."""
    con.execute(
        "CREATE OR REPLACE TABLE raw AS SELECT * FROM read_csv(?, header = true, "
        "all_varchar = true, names = ?, delim = ',', quote = '\"')",
        [str(csv_path), RAW_NAMES],
    )


def check_contract(
    con: duckdb.DuckDBPyConnection, contract: DataContract, source: str
) -> IngestReport:
    fmt = contract.timestamp_format.replace("'", "''")
    currencies = _sql_list(contract.currencies)
    formats = _sql_list(contract.payment_formats)
    row = con.execute(f"""
        SELECT
          count(*),
          count(*) FILTER (WHERE label = '1'),
          min(try_strptime(ts, '{fmt}')),
          max(try_strptime(ts, '{fmt}')),
          count(*) FILTER (WHERE try_strptime(ts, '{fmt}') IS NULL),
          count(*) FILTER (WHERE try_cast(from_bank AS INTEGER) IS NULL
                             OR try_cast(to_bank AS INTEGER) IS NULL),
          count(*) FILTER (WHERE coalesce(trim(from_account), '') = ''
                             OR coalesce(trim(to_account), '') = ''),
          count(*) FILTER (WHERE try_cast(amount_received AS DOUBLE) IS NULL
                             OR try_cast(amount_paid AS DOUBLE) IS NULL
                             OR try_cast(amount_received AS DOUBLE) < 0
                             OR try_cast(amount_paid AS DOUBLE) < 0),
          count(*) FILTER (WHERE currency_received NOT IN ({currencies})
                             OR currency_paid NOT IN ({currencies})
                             OR currency_received IS NULL OR currency_paid IS NULL),
          count(*) FILTER (WHERE payment_format NOT IN ({formats}) OR payment_format IS NULL),
          count(*) FILTER (WHERE label IS NULL OR label NOT IN ('0', '1')),
          count(*) FILTER (WHERE from_bank = to_bank AND from_account = to_account),
          count(*) FILTER (WHERE currency_received <> currency_paid),
          count(*) FILTER (WHERE try_cast(amount_paid AS DOUBLE) = 0)
        FROM raw
    """).fetchone()
    if row is None:  # pragma: no cover - an aggregate always returns one row
        msg = "contract query returned no row"
        raise PipelineError(msg)
    duplicates = con.execute(
        "SELECT coalesce(sum(n - 1), 0) FROM (SELECT count(*) AS n FROM raw GROUP BY "
        + ", ".join(RAW_NAMES)
        + " HAVING count(*) > 1)"
    ).fetchone()
    report = IngestReport(
        source=source,
        rows=int(row[0]),
        laundering=int(row[1]),
        ts_min=row[2].isoformat() if row[2] else None,
        ts_max=row[3].isoformat() if row[3] else None,
        violations=dict(zip(HARD_CHECKS, (int(v) for v in row[4:11]), strict=True)),
        facts={
            "self_transfers": int(row[11]),
            "cross_currency": int(row[12]),
            "zero_amount": int(row[13]),
            "exact_duplicate_rows": int(duplicates[0]) if duplicates else 0,
        },
    )
    if report.rows == 0:
        report.violations["empty_file"] = 1
    return report


def write_transactions(
    con: duckdb.DuckDBPyConnection, contract: DataContract, out_path: Path
) -> None:
    fmt = contract.timestamp_format.replace("'", "''")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    con.execute(f"""
        COPY (
          WITH typed AS (
            SELECT
              rowid AS txn_id,
              strptime(ts, '{fmt}') AS ts,
              CAST(from_bank AS INTEGER) AS from_bank,
              trim(from_account) AS from_account,
              CAST(to_bank AS INTEGER) AS to_bank,
              trim(to_account) AS to_account,
              CAST(amount_received AS DOUBLE) AS amount_received,
              currency_received,
              CAST(amount_paid AS DOUBLE) AS amount_paid,
              currency_paid,
              payment_format,
              label = '1' AS is_laundering
            FROM raw
          )
          SELECT
            txn_id,
            row_number() OVER (ORDER BY ts, txn_id) - 1 AS seq,
            ts, from_bank, from_account, to_bank, to_account,
            CAST(from_bank AS VARCHAR) || ':' || from_account AS from_id,
            CAST(to_bank AS VARCHAR) || ':' || to_account AS to_id,
            amount_received, currency_received, amount_paid, currency_paid,
            payment_format, is_laundering
          FROM typed
          ORDER BY txn_id
        ) TO '{str(out_path).replace("'", "''")}' (FORMAT parquet, COMPRESSION zstd)
    """)


def ingest(
    dataset: Dataset, contract: DataContract, con: duckdb.DuckDBPyConnection | None = None
) -> IngestReport:
    """Validate the raw CSV and write ``transactions.parquet``. Raises ContractViolationError."""
    con = con or connect(dataset.processed_dir / "_duckdb_tmp")
    load_raw(con, dataset.transactions_csv)
    report = check_contract(con, contract, dataset.transactions_csv.name)
    if not report.passed:
        raise ContractViolationError(report)
    write_transactions(con, contract, dataset.transactions_parquet)
    con.execute("DROP TABLE raw")
    return report
