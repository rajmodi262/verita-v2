"""Laundering-pattern parsing and linking (M1.06, M1.07).

The IBM ``*_Patterns.txt`` file lists laundering attempts as blocks::

    BEGIN LAUNDERING ATTEMPT - FAN-OUT:  Max 16-degree Fan-Out
    2022/09/01 05:14,00952,8139F54E0,0111632,8062C56E0,5331.44,US Dollar,5331.44,US Dollar,ACH,1
    END LAUNDERING ATTEMPT - FAN-OUT

The description after the colon is optional. Each data row is linked to exactly one transaction
in ``transactions.parquet`` on every field, with bank ids compared as numbers (the files write
them with varying leading zeros). Linking is strict: an unmatched row, or a match against a
transaction labelled legitimate, fails the stage.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa

from verita.pipeline.config import DataContract, Dataset, PipelineError

_BEGIN = re.compile(r"^BEGIN LAUNDERING ATTEMPT - ([A-Z-]+)(?::\s*(.*))?$")
_END = re.compile(r"^END LAUNDERING ATTEMPT - ([A-Z-]+)$")
_FIELDS = 11
UNATTRIBUTED = "UNATTRIBUTED"


@dataclass(frozen=True)
class PatternRow:
    ts: datetime
    from_bank: int
    from_account: str
    to_bank: int
    to_account: str
    amount_received: float
    currency_received: str
    amount_paid: float
    currency_paid: str
    payment_format: str


@dataclass
class Attempt:
    attempt_id: int
    typology: str
    description: str
    line: int
    rows: list[PatternRow] = field(default_factory=list)


class PatternFormatError(PipelineError):
    def __init__(self, path: Path, problems: list[str]) -> None:
        shown = "\n".join(f"  {p}" for p in problems[:20])
        more = f"\n  … and {len(problems) - 20} more" if len(problems) > 20 else ""  # noqa: PLR2004
        super().__init__(f"Malformed patterns file {path.name}:\n{shown}{more}")
        self.problems = problems


def _parse_row(fields: list[str], fmt: str) -> PatternRow:
    return PatternRow(
        ts=datetime.strptime(fields[0], fmt),
        from_bank=int(fields[1]),
        from_account=fields[2].strip(),
        to_bank=int(fields[3]),
        to_account=fields[4].strip(),
        amount_received=float(fields[5]),
        currency_received=fields[6],
        amount_paid=float(fields[7]),
        currency_paid=fields[8],
        payment_format=fields[9],
    )


def _data_line(line: str, fmt: str) -> tuple[PatternRow | None, str | None]:
    fields = next(csv.reader([line]))
    if len(fields) != _FIELDS:
        return None, f"{len(fields)} fields, expected {_FIELDS}"
    if fields[10] != "1":
        return None, "pattern row not labelled laundering"
    try:
        return _parse_row(fields, fmt), None
    except ValueError as exc:
        return None, str(exc)


def _open_block(
    begin: re.Match[str], lineno: int, attempt_id: int, contract: DataContract, problems: list[str]
) -> Attempt:
    typology = begin.group(1)
    if typology not in contract.typologies:
        problems.append(f"line {lineno}: unknown typology {typology!r}")
    return Attempt(attempt_id, typology, (begin.group(2) or "").strip(), lineno)


def _close_block(
    end: re.Match[str], lineno: int, current: Attempt | None, problems: list[str]
) -> None:
    if current is None:
        problems.append(f"line {lineno}: END without BEGIN")
    elif end.group(1) != current.typology:
        problems.append(
            f"line {lineno}: END {end.group(1)} closes {current.typology} (line {current.line})"
        )


def parse_patterns(path: Path, contract: DataContract) -> list[Attempt]:
    """Parse every attempt; collect every format problem and raise them together."""
    attempts: list[Attempt] = []
    problems: list[str] = []
    current: Attempt | None = None

    with path.open(encoding="utf-8") as handle:
        for lineno, raw in enumerate(handle, start=1):
            line = raw.strip()
            if not line:
                continue
            if begin := _BEGIN.match(line):
                if current is not None:
                    problems.append(
                        f"line {lineno}: BEGIN inside an open block (line {current.line})"
                    )
                current = _open_block(begin, lineno, len(attempts), contract, problems)
                attempts.append(current)
                continue
            if end := _END.match(line):
                _close_block(end, lineno, current, problems)
                current = None
                continue
            if current is None:
                problems.append(f"line {lineno}: data outside a block")
                continue
            row, problem = _data_line(line, contract.timestamp_format)
            if problem is not None:
                problems.append(f"line {lineno}: {problem}")
            elif row is not None:
                current.rows.append(row)

    if current is not None:
        problems.append(f"end of file: block from line {current.line} is never closed")
    empty = [a for a in attempts if not a.rows]
    problems.extend(f"line {a.line}: attempt has no transactions" for a in empty)
    if problems:
        raise PatternFormatError(path, problems)
    return attempts


@dataclass
class LinkReport:
    attempts: int
    pattern_rows: int
    linked_rows: int
    unmatched_rows: int
    multi_match_rows: int
    label_mismatch: int
    transactions_in_multiple_attempts: int
    laundering_total: int
    laundering_attributed: int
    by_typology: dict[str, dict[str, int]]

    @property
    def coverage(self) -> float:
        return self.laundering_attributed / self.laundering_total if self.laundering_total else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempts": self.attempts,
            "pattern_rows": self.pattern_rows,
            "linked_rows": self.linked_rows,
            "unmatched_rows": self.unmatched_rows,
            "multi_match_rows": self.multi_match_rows,
            "label_mismatch": self.label_mismatch,
            "transactions_in_multiple_attempts": self.transactions_in_multiple_attempts,
            "laundering_total": self.laundering_total,
            "laundering_attributed": self.laundering_attributed,
            "laundering_unattributed": self.laundering_total - self.laundering_attributed,
            "coverage": round(self.coverage, 6),
            "by_typology": self.by_typology,
        }


def _pattern_table(attempts: list[Attempt]) -> pa.Table:
    cols: dict[str, list[Any]] = {
        k: []
        for k in (
            "pattern_row",
            "attempt_id",
            "typology",
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
        )
    }
    n = 0
    for attempt in attempts:
        for row in attempt.rows:
            cols["pattern_row"].append(n)
            cols["attempt_id"].append(attempt.attempt_id)
            cols["typology"].append(attempt.typology)
            for name in list(cols)[3:]:
                cols[name].append(getattr(row, name))
            n += 1
    return pa.table(cols)


def link_patterns(
    dataset: Dataset, attempts: list[Attempt], con: duckdb.DuckDBPyConnection | None = None
) -> LinkReport:
    """Join pattern rows to transactions; write ``pattern_links.parquet``. Strict on errors."""
    con = con or duckdb.connect()
    patterns = _pattern_table(attempts)
    con.register("patterns", patterns)
    tx = str(dataset.transactions_parquet).replace("'", "''")
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE matches AS
        SELECT p.pattern_row, p.attempt_id, p.typology, t.txn_id, t.is_laundering
        FROM patterns p
        JOIN read_parquet('{tx}') t
          ON t.ts = p.ts
         AND t.from_bank = p.from_bank AND t.from_account = p.from_account
         AND t.to_bank = p.to_bank AND t.to_account = p.to_account
         AND t.amount_paid = p.amount_paid AND t.currency_paid = p.currency_paid
         AND t.amount_received = p.amount_received
         AND t.currency_received = p.currency_received
         AND t.payment_format = p.payment_format
    """)

    def scalar(sql: str) -> int:
        row = con.execute(sql).fetchone()
        return int(row[0]) if row and row[0] is not None else 0

    pattern_rows = patterns.num_rows
    linked = scalar("SELECT count(DISTINCT pattern_row) FROM matches")
    multi = scalar(
        "SELECT count(*) FROM (SELECT pattern_row FROM matches GROUP BY 1 HAVING count(*) > 1)"
    )
    mismatch = scalar("SELECT count(*) FROM matches WHERE NOT is_laundering")
    shared = scalar(
        "SELECT count(*) FROM (SELECT txn_id FROM matches GROUP BY 1 "
        "HAVING count(DISTINCT attempt_id) > 1)"
    )
    laundering_total = scalar(f"SELECT count(*) FROM read_parquet('{tx}') WHERE is_laundering")
    attributed = scalar("SELECT count(DISTINCT txn_id) FROM matches")

    by_typology: dict[str, dict[str, int]] = {}
    for typology, n_attempts, n_rows in con.execute(
        "SELECT typology, count(DISTINCT attempt_id), count(*) FROM patterns GROUP BY 1 ORDER BY 1"
    ).fetchall():
        by_typology[str(typology)] = {"attempts": int(n_attempts), "transactions": int(n_rows)}

    report = LinkReport(
        attempts=len(attempts),
        pattern_rows=pattern_rows,
        linked_rows=linked,
        unmatched_rows=pattern_rows - linked,
        multi_match_rows=multi,
        label_mismatch=mismatch,
        transactions_in_multiple_attempts=shared,
        laundering_total=laundering_total,
        laundering_attributed=attributed,
        by_typology=by_typology,
    )
    if report.unmatched_rows or report.label_mismatch:
        msg = (
            f"Pattern linking failed: {report.unmatched_rows} unmatched rows, "
            f"{report.label_mismatch} matched to legitimate transactions"
        )
        raise PipelineError(msg)

    out = str(dataset.pattern_links_parquet).replace("'", "''")
    dataset.processed_dir.mkdir(parents=True, exist_ok=True)
    con.execute(f"""
        COPY (SELECT txn_id, attempt_id, typology FROM matches ORDER BY txn_id, attempt_id)
        TO '{out}' (FORMAT parquet, COMPRESSION zstd)
    """)
    con.unregister("patterns")
    return report
