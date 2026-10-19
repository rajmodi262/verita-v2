"""`verita data graph`: account and account-day tables (M1.09).

* ``accounts.parquet`` — one row per account node: activity span, degrees, distinct
  counterparties, and whether it ever touched a laundering transaction.
* ``account_day.parquet`` — one row per (account, day) with any activity: the unit an analyst
  works as an alert (PIVOT §5.2). ``label`` is true when the account sent or received a
  laundering transaction that day; ``typologies`` lists the attributed typologies involved
  (``UNATTRIBUTED`` for laundering outside any pattern block).

Amounts are kept per currency elsewhere; nothing here sums across currencies.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import duckdb

from verita.pipeline.config import Dataset
from verita.pipeline.patterns import UNATTRIBUTED


@dataclass
class GraphReport:
    accounts: int
    accounts_involved: int
    account_days: int
    positive_account_days: int
    edges: int
    self_loops: int

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def _q(path: object) -> str:
    return str(path).replace("'", "''")


def build_graph(dataset: Dataset, con: duckdb.DuckDBPyConnection | None = None) -> GraphReport:
    con = con or duckdb.connect()
    tx, links = _q(dataset.transactions_parquet), _q(dataset.pattern_links_parquet)
    con.execute(f"""
        CREATE OR REPLACE TEMP VIEW tx AS
        SELECT t.*, coalesce(l.typology, CASE WHEN t.is_laundering THEN '{UNATTRIBUTED}' END)
               AS typology
        FROM read_parquet('{tx}') t
        LEFT JOIN (SELECT txn_id, min(typology) AS typology FROM read_parquet('{links}')
                   GROUP BY 1) l USING (txn_id)
    """)
    con.execute("""
        CREATE OR REPLACE TEMP VIEW ends AS
        SELECT from_id AS account_id, from_bank AS bank, to_id AS counterparty, ts,
               is_laundering, typology, 'sent' AS direction FROM tx
        UNION ALL
        SELECT to_id, to_bank, from_id, ts, is_laundering, typology, 'received' FROM tx
    """)
    dataset.processed_dir.mkdir(parents=True, exist_ok=True)
    con.execute(f"""
        COPY (
          SELECT account_id, min(bank) AS bank, min(ts) AS first_seen, max(ts) AS last_seen,
                 count(*) FILTER (WHERE direction = 'sent') AS n_sent,
                 count(*) FILTER (WHERE direction = 'received') AS n_received,
                 count(DISTINCT counterparty) FILTER (WHERE direction = 'sent') AS n_payees,
                 count(DISTINCT counterparty) FILTER (WHERE direction = 'received') AS n_payers,
                 bool_or(is_laundering) AS laundering_involved
          FROM ends GROUP BY account_id ORDER BY account_id
        ) TO '{_q(dataset.accounts_parquet)}' (FORMAT parquet, COMPRESSION zstd)
    """)
    con.execute(f"""
        COPY (
          SELECT account_id, CAST(ts AS DATE) AS day,
                 count(*) FILTER (WHERE direction = 'sent') AS sent_count,
                 count(*) FILTER (WHERE direction = 'received') AS received_count,
                 count(*) FILTER (WHERE direction = 'sent' AND is_laundering) AS sent_laundering,
                 count(*) FILTER (WHERE direction = 'received' AND is_laundering)
                   AS received_laundering,
                 bool_or(is_laundering) AS label,
                 coalesce(
                   list_sort(list_distinct(
                     list(typology) FILTER (WHERE typology IS NOT NULL))),
                   []
                 ) AS typologies
          FROM ends GROUP BY account_id, day ORDER BY day, account_id
        ) TO '{_q(dataset.account_day_parquet)}' (FORMAT parquet, COMPRESSION zstd)
    """)

    def one(sql: str) -> int:
        row = con.execute(sql).fetchone()
        return int(row[0]) if row and row[0] is not None else 0

    accounts, days = _q(dataset.accounts_parquet), _q(dataset.account_day_parquet)
    return GraphReport(
        accounts=one(f"SELECT count(*) FROM '{accounts}'"),
        accounts_involved=one(f"SELECT count(*) FROM '{accounts}' WHERE laundering_involved"),
        account_days=one(f"SELECT count(*) FROM '{days}'"),
        positive_account_days=one(f"SELECT count(*) FROM '{days}' WHERE label"),
        edges=one("SELECT count(*) FROM tx"),
        self_loops=one("SELECT count(*) FROM tx WHERE from_id = to_id"),
    )
