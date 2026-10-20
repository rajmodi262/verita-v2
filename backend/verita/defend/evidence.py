"""Case evidence: the immutable items a case file is built from (PIVOT §8.1).

Every item is ``{"id": "EV-…", "kind": …, "payload": {...}}``, frozen when the case is created,
and becomes one Merkle leaf. Kinds:

``alert``   the alerted account-day (score, predicted typology, counts)
``reason``  a SHAP reason code (its sentence is evidence too)
``txn``     one payment
``path``    the dominant money path through the alert's riskiest payment
``motif``   structural signals on the riskiest payment
``case``    case-level summary: totals, date range, banks, majority typology

:func:`facts` lists what each item *establishes*, as :class:`~verita.defend.claims.Claim`
objects in the same normal form the verifier extracts from narrative sentences.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from verita.defend.claims import Claim, day_of, extract
from verita.optimize.planner import USD_PER_UNIT

MAX_TXNS_PER_ALERT = 25  # dominant path + the riskiest other payments
AMOUNT_DECIMALS = 8  # Bitcoin payments of 0.0034 must not become 0.00


@dataclass
class AlertInput:
    """What the case builder needs from one alert (DB row + evidence-store subgraph)."""

    id: int
    account_id: str
    alert_date: str
    score: float
    typology_pred: str
    typology_conf: float
    n_transactions: int
    n_flagged: int
    top_txn_id: int
    reasons: list[dict[str, Any]]
    subgraph: dict[str, Any]


@dataclass
class CaseEvidence:
    items: dict[str, dict[str, Any]] = field(default_factory=dict)

    def add(self, ev_id: str, kind: str, payload: dict[str, Any]) -> None:
        self.items[ev_id] = {"id": ev_id, "kind": kind, "payload": payload}

    def of_kind(self, kind: str) -> list[dict[str, Any]]:
        return [i for i in self.items.values() if i["kind"] == kind]


def split_account(full: str) -> tuple[str, str]:
    bank, _, acct = full.partition(":")
    return str(int(bank)) if bank.isdigit() else bank, acct


def usd(amount: float, currency: str) -> float:
    return amount * USD_PER_UNIT.get(currency, 1.0)


def _txn_payload(edge: dict[str, Any]) -> dict[str, Any]:
    fb, fa = split_account(edge["from"])
    tb, ta = split_account(edge["to"])
    return {
        "txn_id": int(edge["txn_id"]),
        "ts": edge["ts"][:19],
        "from_bank": fb,
        "from_account": fa,
        "to_bank": tb,
        "to_account": ta,
        "amount_paid": round(float(edge["amount_paid"]), AMOUNT_DECIMALS),
        "currency_paid": edge["currency_paid"],
        "amount_received": round(float(edge["amount_received"]), AMOUNT_DECIMALS),
        "currency_received": edge["currency_received"],
        "payment_format": edge["payment_format"],
        "score": round(float(edge["score"]), 4),
    }


def _minutes(a: str, b: str) -> float:
    return (datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds() / 60


def build_case_evidence(case_id: int, alerts: list[AlertInput]) -> CaseEvidence:
    ev = CaseEvidence()
    all_txns: dict[int, dict[str, Any]] = {}
    for a in alerts:
        bank, acct = split_account(a.account_id)
        ev.add(
            f"EV-ALERT-{a.id}",
            "alert",
            {
                "alert_id": a.id,
                "bank": bank,
                "account": acct,
                "date": a.alert_date,
                "score": round(a.score, 4),
                "typology_pred": a.typology_pred,
                "typology_conf": round(a.typology_conf, 4),
                "n_transactions": a.n_transactions,
                "n_flagged": a.n_flagged,
            },
        )
        for r in a.reasons:
            ev.add(
                f"EV-REASON-{a.id}-{r['rank']}",
                "reason",
                {
                    "alert_id": a.id,
                    "rank": r["rank"],
                    "feature": r["feature"],
                    "value": round(float(r["value"]), 4),
                    "text": r["text"],
                },
            )
        edges = {int(e["txn_id"]): e for e in a.subgraph.get("edges", [])}
        path_ids = [int(t) for t in a.subgraph.get("dominant_path", {}).get("txn_ids", [])]
        ranked = sorted(edges.values(), key=lambda e: -float(e["score"]))
        chosen = [edges[t] for t in path_ids if t in edges]
        chosen += [e for e in ranked if int(e["txn_id"]) not in path_ids][
            : max(0, MAX_TXNS_PER_ALERT - len(chosen))
        ]
        for e in chosen:
            payload = _txn_payload(e)
            all_txns[payload["txn_id"]] = payload
            ev.add(f"EV-TXN-{payload['txn_id']}", "txn", payload)
        hops = [all_txns[t] for t in path_ids if t in all_txns]
        if hops:
            accounts = [hops[0]["from_account"]] + [h["to_account"] for h in hops]
            ev.add(
                f"EV-PATH-{a.id}",
                "path",
                {
                    "alert_id": a.id,
                    "txn_ids": [h["txn_id"] for h in hops],
                    "accounts": accounts,
                    "banks": sorted({h["from_bank"] for h in hops} | {h["to_bank"] for h in hops}),
                    "first_ts": hops[0]["ts"],
                    "last_ts": hops[-1]["ts"],
                    "duration_minutes": round(_minutes(hops[0]["ts"], hops[-1]["ts"]), 1),
                    "amounts": [
                        {"amount": h["amount_paid"], "currency": h["currency_paid"]} for h in hops
                    ],
                },
            )
        ev.add(
            f"EV-MOTIF-{a.id}",
            "motif",
            {
                "alert_id": a.id,
                "typology": a.typology_pred,
                "signals": list(a.subgraph.get("motif", {}).get("signals", [])),
            },
        )
    txns = list(all_txns.values())
    days = sorted({t["ts"][:10] for t in txns} | {a.alert_date for a in alerts})
    typology = Counter(a.typology_pred for a in alerts).most_common(1)
    case_accounts = {t["from_account"] for t in txns} | {t["to_account"] for t in txns}
    ev.add(
        f"EV-CASE-{case_id}",
        "case",
        {
            "case_id": case_id,
            "alerts": len(alerts),
            "subjects": [
                dict(zip(("bank", "account"), split_account(a.account_id), strict=True))
                for a in alerts
            ],
            "payments": len(txns),
            "accounts": len(case_accounts),
            "banks": sorted({t["from_bank"] for t in txns} | {t["to_bank"] for t in txns}, key=int),
            "first_day": days[0] if days else "",
            "last_day": days[-1] if days else "",
            "days": days,
            "total_usd": round(sum(usd(t["amount_paid"], t["currency_paid"]) for t in txns), 2),
            "typology": typology[0][0] if typology else "UNATTRIBUTED",
            "dominant_paths": [i["id"] for i in ev.of_kind("path")],
        },
    )
    return ev


# ── facts ────────────────────────────────────────────────────────────────────


def _f(kind: Any, value: str | float, unit: str = "") -> Claim:
    return Claim(kind, value, str(value), unit)


def _payment_counts(n: int) -> list[Claim]:
    return [_f("count", float(n), "payment")]


def facts(item: dict[str, Any]) -> list[Claim]:  # noqa: PLR0911 - one branch per kind
    """What an evidence item establishes, in the verifier's normal form."""
    p = item["payload"]
    kind = item["kind"]
    if kind == "alert":
        return [
            _f("account", p["account"]),
            _f("bank", p["bank"]),
            _f("date", p["date"]),
            _f("typology", p["typology_pred"]),
            _f("percent", round(p["score"] * 100, 2)),
            _f("percent", round(p["typology_conf"] * 100, 2)),
            *_payment_counts(p["n_transactions"]),
            *_payment_counts(p["n_flagged"]),
        ]
    if kind == "reason":
        return [*extract(p["text"]), _f("count", float(p["value"]), "any")]
    if kind == "txn":
        return [
            _f("account", p["from_account"]),
            _f("account", p["to_account"]),
            _f("bank", p["from_bank"]),
            _f("bank", p["to_bank"]),
            _f("date", day_of(p["ts"])),
            _f("amount", p["amount_paid"], p["currency_paid"]),
            _f("amount", p["amount_received"], p["currency_received"]),
            _f("percent", round(p["score"] * 100, 2)),
        ]
    if kind == "path":
        amounts = [_f("amount", a["amount"], a["currency"]) for a in p["amounts"]]
        currencies = {a["currency"] for a in p["amounts"]}
        if len(currencies) == 1:
            total = round(sum(a["amount"] for a in p["amounts"]), AMOUNT_DECIMALS)
            amounts.append(_f("amount", total, next(iter(currencies))))
        return [
            *[_f("account", a) for a in p["accounts"]],
            *[_f("bank", b) for b in p["banks"]],
            _f("date", day_of(p["first_ts"])),
            _f("date", day_of(p["last_ts"])),
            _f("date_range", f"{day_of(p['first_ts'])}..{day_of(p['last_ts'])}"),
            _f("duration", p["duration_minutes"], "minutes"),
            _f("count", float(len(p["txn_ids"])), "payment"),
            _f("count", float(len(p["accounts"])), "account"),
            _f("count", float(len(set(p["accounts"]))), "account"),
            _f("count", float(len(p["banks"])), "bank"),
            *amounts,
        ]
    if kind == "motif":
        out = [_f("typology", p["typology"])]
        for s in p["signals"]:
            out += extract(s)
        return out
    if kind == "case":
        return [
            *[_f("account", s["account"]) for s in p["subjects"]],
            *[_f("bank", s["bank"]) for s in p["subjects"]],
            *[_f("bank", b) for b in p["banks"]],
            *[_f("date", d) for d in p["days"]],
            _f("date_range", f"{p['first_day']}..{p['last_day']}"),
            _f("count", float(p["alerts"]), "alert"),
            _f("count", float(p["payments"]), "payment"),
            _f("count", float(p["accounts"]), "account"),
            _f("count", float(len(p["banks"])), "bank"),
            _f("count", float(len(p["days"])), "day"),
            _f("amount", p["total_usd"], "US Dollar"),
            _f("typology", p["typology"]),
        ]
    return []
