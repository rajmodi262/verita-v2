"""Evidence subgraph for an alert (PIVOT §6.5, M3.03–M3.04).

Given an alert on (account, day) the investigation may only use what was known by the end of
that day: the window is the 7 days up to and including the alert day.

* Nodes: the alerted account, its counterparties, and the strongest second-hop counterparties
  (≤ 60 nodes, ranked by the riskiest payment linking them).
* Edges: payments among those nodes in the window (≤ 200, riskiest first; dominant-path
  payments always included).
* Dominant path: starting from the alert's riskiest payment, follow the riskiest earlier payment
  into the sender and the riskiest later payment out of the receiver (≤ 3 hops each way,
  time-respecting).
* Motif: which structural signals the riskiest payment carries (from its features).

Every item has a stable evidence ID that the case narrative (Defend) cites.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import duckdb
import pandas as pd

MAX_NODES = 60
MAX_EDGES = 200
NEIGHBOUR_LIMIT = 500  # counterparties ranked per hop before the node cap is applied
PATH_HOPS = 3
WINDOW_DAYS = 7


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return cast("list[dict[str, Any]]", frame.to_dict(orient="records"))


def txn_evidence_id(txn_id: int) -> str:
    return f"EV-TXN-{txn_id}"


@dataclass(frozen=True)
class AlertRef:
    id: int
    account_id: str
    alert_date: date
    top_txn_id: int
    threshold: float


class EvidenceStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def _con(self) -> duckdb.DuckDBPyConnection:
        con = duckdb.connect(str(self.path), read_only=True)
        con.execute("SET enable_progress_bar = false")
        return con

    def subgraph(self, alert: AlertRef) -> dict[str, Any]:
        end = datetime.combine(alert.alert_date + timedelta(days=1), datetime.min.time())
        start = end - timedelta(days=WINDOW_DAYS)
        con = self._con()
        try:
            return self._build(con, alert, start, end)
        finally:
            con.close()

    def _counterparties(
        self,
        con: duckdb.DuckDBPyConnection,
        accounts: list[str],
        start: datetime,
        end: datetime,
        limit: int,
    ) -> dict[str, float]:
        """Accounts that paid or were paid by ``accounts`` in the window, with the riskiest
        linking payment's score — aggregated in DuckDB, so a hub account with 10⁵ payments a
        week costs one grouped scan instead of 10⁵ Python rows."""
        if not accounts:
            return {}
        con.register("acct", pd.DataFrame({"a": accounts}))
        rows = con.execute(
            """
            WITH t AS (
                SELECT to_id AS other, score FROM out_edges
                 WHERE from_id IN (SELECT a FROM acct) AND ts >= ? AND ts < ?
                UNION ALL
                SELECT from_id AS other, score FROM in_edges
                 WHERE to_id IN (SELECT a FROM acct) AND ts >= ? AND ts < ?
            )
            SELECT other, max(score) AS w FROM t
             WHERE other NOT IN (SELECT a FROM acct)
             GROUP BY other ORDER BY w DESC, other LIMIT ?
        """,
            [start, end, start, end, limit],
        ).fetchall()
        con.unregister("acct")
        return {str(a): float(w) for a, w in rows}

    def _edges_among(
        self, con: duckdb.DuckDBPyConnection, keep: set[str], start: datetime, end: datetime
    ) -> tuple[list[dict[str, Any]], int]:
        """The riskiest ``MAX_EDGES`` payments between kept accounts, and how many there were."""
        con.register("keep", pd.DataFrame({"a": sorted(keep)}))
        where = """
            FROM out_edges
            WHERE from_id IN (SELECT a FROM keep) AND to_id IN (SELECT a FROM keep)
              AND ts >= ? AND ts < ?
        """
        total_row = con.execute(f"SELECT count(*) {where}", [start, end]).fetchone()
        frame = con.execute(
            f"SELECT * {where} ORDER BY score DESC, ts LIMIT ?", [start, end, MAX_EDGES]
        ).df()
        con.unregister("keep")
        return _records(frame), int(total_row[0]) if total_row else 0

    def _build(
        self, con: duckdb.DuckDBPyConnection, alert: AlertRef, start: datetime, end: datetime
    ) -> dict[str, Any]:
        center = alert.account_id
        path = self._dominant_path(con, alert.top_txn_id, start, end)
        path_ids = {p["txn_id"] for p in path}
        path_accounts = {a for p in path for a in (p["edge"]["from_id"], p["edge"]["to_id"])}
        neighbours = self._counterparties(con, [center], start, end, NEIGHBOUR_LIMIT)
        top_neighbours = list(neighbours)[: MAX_NODES // 3]
        weight = dict(neighbours)
        second = self._counterparties(con, top_neighbours, start, end, NEIGHBOUR_LIMIT)
        for acct, w in second.items():
            if acct != center:
                weight[acct] = max(weight.get(acct, 0.0), w)
        # The centre and the dominant path always stay; the riskiest others fill the rest.
        keep = {center} | path_accounts
        room = max(0, MAX_NODES - len(keep))
        others = sorted((a for a in weight if a not in keep), key=lambda a: (-weight[a], a))
        keep |= set(others[:room])
        among, total = self._edges_among(con, keep, start, end)
        edges_by_id: dict[int, dict[str, Any]] = {int(e["txn_id"]): e for e in among}
        for p in path:
            edges_by_id[p["txn_id"]] = p["edge"]
        edges = sorted(edges_by_id.values(), key=lambda e: (-float(e["score"]), e["ts"]))
        on_path = [e for e in edges if int(e["txn_id"]) in path_ids]
        rest = [e for e in edges if int(e["txn_id"]) not in path_ids]
        edges = on_path + rest[: max(0, MAX_EDGES - len(on_path))]
        node_ids = {center} | {e["from_id"] for e in edges} | {e["to_id"] for e in edges}
        return {
            "alert_id": alert.id,
            "window": {"from": start.isoformat(), "to": end.isoformat()},
            "center": center,
            "nodes": [self._node(a, center, edges) for a in sorted(node_ids)],
            "edges": [
                self._edge(e, alert.threshold, int(e["txn_id"]) in path_ids)
                for e in sorted(edges, key=lambda e: e["ts"])
            ],
            "dominant_path": {
                "evidence_id": f"EV-PATH-{alert.id}",
                "txn_ids": [p["txn_id"] for p in path],
                "evidence_ids": [txn_evidence_id(p["txn_id"]) for p in path],
            },
            "motif": self._motif(con, alert),
            "truncated": total > MAX_EDGES or len(weight) + 1 > MAX_NODES,
        }

    def _dominant_path(
        self, con: duckdb.DuckDBPyConnection, top_txn_id: int, start: datetime, end: datetime
    ) -> list[dict[str, Any]]:
        top_rows = _records(
            con.execute("SELECT * FROM out_edges WHERE txn_id = ?", [top_txn_id]).df()
        )
        if not top_rows:
            return []
        top = top_rows[0]
        backward: list[dict[str, Any]] = []
        current = top
        for _ in range(PATH_HOPS):
            rows = con.execute(
                """
                SELECT * FROM in_edges WHERE to_id = ? AND ts >= ? AND ts <= ?
                  AND from_id <> to_id AND txn_id <> ?
                ORDER BY score DESC, ts DESC LIMIT 1
            """,
                [current["from_id"], start, current["ts"], current["txn_id"]],
            ).df()
            if rows.empty:
                break
            current = _records(rows)[0]
            backward.append(current)
        forward: list[dict[str, Any]] = []
        current = top
        for _ in range(PATH_HOPS):
            rows = con.execute(
                """
                SELECT * FROM out_edges WHERE from_id = ? AND ts >= ? AND ts < ?
                  AND from_id <> to_id AND txn_id <> ?
                ORDER BY score DESC, ts LIMIT 1
            """,
                [current["to_id"], current["ts"], end, current["txn_id"]],
            ).df()
            if rows.empty:
                break
            current = _records(rows)[0]
            forward.append(current)
        chain = [*reversed(backward), top, *forward]
        seen: set[int] = set()
        out = []
        for e in chain:
            tid = int(e["txn_id"])
            if tid not in seen:
                seen.add(tid)
                out.append({"txn_id": tid, "edge": e})
        return out

    def _motif(self, con: duckdb.DuckDBPyConnection, alert: AlertRef) -> dict[str, Any]:
        rows = _records(
            con.execute("SELECT * FROM motif_features WHERE txn_id = ?", [alert.top_txn_id]).df()
        )
        signals: list[str] = []
        if rows:
            f = rows[0]
            if f["cycle_found"]:
                signals.append(f"closes a {int(f['cycle_edges'])}-transfer loop")
            if f["s_payees_24h"] >= 5:  # noqa: PLR2004
                signals.append(f"sender fanned out to {int(f['s_payees_24h'])} payees in 24 h")
            if f["r_payers_24h"] >= 5:  # noqa: PLR2004
                signals.append(f"receiver was paid by {int(f['r_payers_24h'])} payers in 24 h")
            if 0 <= f["s_since_last_in_min"] < 60:  # noqa: PLR2004
                signals.append(
                    f"sender passed money on {int(f['s_since_last_in_min'])} min after receiving"
                )
        return {"evidence_id": f"EV-MOTIF-{alert.id}", "signals": signals}

    @staticmethod
    def _node(account: str, center: str, edges: list[dict[str, Any]]) -> dict[str, Any]:
        touching = [e for e in edges if account in (e["from_id"], e["to_id"])]
        return {
            "id": account,
            "is_center": account == center,
            "max_score": round(max((float(e["score"]) for e in touching), default=0.0), 6),
            "degree": len(touching),
        }

    @staticmethod
    def _edge(e: dict[str, Any], threshold: float, on_path: bool) -> dict[str, Any]:
        ts = e["ts"]
        return {
            "evidence_id": txn_evidence_id(int(e["txn_id"])),
            "txn_id": int(e["txn_id"]),
            "from": e["from_id"],
            "to": e["to_id"],
            "ts": ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
            "amount_paid": round(float(e["amount_paid"]), 2),
            "currency_paid": e["currency_paid"],
            "amount_received": round(float(e["amount_received"]), 2),
            "currency_received": e["currency_received"],
            "payment_format": e["payment_format"],
            "score": round(float(e["score"]), 6),
            "flagged": float(e["score"]) >= threshold,
            "on_dominant_path": on_path,
        }
