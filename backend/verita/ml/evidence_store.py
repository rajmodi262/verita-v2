"""Evidence store: a read-only DuckDB file the API queries for subgraphs (M3.03, ADR-002).

Built once by ``verita detect alerts``. Transactions are stored twice — sorted by sender and by
receiver — so DuckDB's zone maps turn "all payments touching account X in a week" into a
small range read instead of a full scan.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

from verita.pipeline.config import Dataset


def evidence_path(dataset: Dataset) -> Path:
    return dataset.processed_dir / "evidence.duckdb"


def build_evidence_store(dataset: Dataset) -> Path:
    path = evidence_path(dataset)
    tmp = path.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    con = duckdb.connect(str(tmp))
    con.execute("SET enable_progress_bar = false")
    tx, scores = dataset.transactions_parquet, dataset.processed_dir / "scores.parquet"
    feats = dataset.features_parquet
    con.execute(f"""
        CREATE TABLE edges AS
        SELECT t.txn_id, t.ts, t.from_id, t.to_id, t.amount_paid, t.currency_paid,
               t.amount_received, t.currency_received, t.payment_format, s.score, s.split
        FROM read_parquet('{tx}') t JOIN read_parquet('{scores}') s USING (txn_id)
    """)
    con.execute("CREATE TABLE out_edges AS SELECT * FROM edges ORDER BY from_id, ts")
    con.execute("CREATE TABLE in_edges AS SELECT * FROM edges ORDER BY to_id, ts")
    con.execute(f"""
        CREATE TABLE motif_features AS
        SELECT txn_id, cycle_found, cycle_edges, s_payees_24h, r_payers_24h,
               s_since_last_in_min, s_in_n_24h
        FROM read_parquet('{feats}') ORDER BY txn_id
    """)
    con.execute("DROP TABLE edges")
    con.close()
    path.unlink(missing_ok=True)
    tmp.rename(path)
    return path
