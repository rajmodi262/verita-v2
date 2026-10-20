"""A small, fully known case: one alert, a three-hop dominant path, three reasons."""

from __future__ import annotations

import pytest

from verita.defend.evidence import AlertInput, build_case_evidence


def edge(txn_id, src, dst, ts, amount, currency="US Dollar", score=0.8, fmt="ACH"):
    return {
        "txn_id": txn_id,
        "from": src,
        "to": dst,
        "ts": ts,
        "amount_paid": amount,
        "currency_paid": currency,
        "amount_received": amount,
        "currency_received": currency,
        "payment_format": fmt,
        "score": score,
    }


def alert_input(alert_id: int = 7, typology: str = "FAN-OUT") -> AlertInput:
    edges = [
        edge(101, "70:8000AAAA1", "11:8000BBBB2", "2022-09-08T10:00:00", 9800.0, score=0.91),
        edge(102, "11:8000BBBB2", "123:8000CCCC3", "2022-09-08T10:20:00", 9750.5, score=0.85),
        edge(103, "123:8000CCCC3", "11:8000DDDD4", "2022-09-08T11:05:00", 9700.25, score=0.77),
        edge(104, "70:8000AAAA1", "11:8000EEEE5", "2022-09-07T09:00:00", 1200.0, "Euro", 0.40),
    ]
    return AlertInput(
        id=alert_id,
        account_id="70:8000AAAA1",
        alert_date="2022-09-08",
        score=0.9123,
        typology_pred=typology,
        typology_conf=0.6234,
        n_transactions=14,
        n_flagged=3,
        top_txn_id=101,
        reasons=[
            {
                "rank": 1,
                "feature": "s_payees_24h",
                "value": 9.0,
                "text": (
                    "Sender paid 9 different accounts in the previous 24 hours"
                    " — raises the risk score"
                ),
            },
            {
                "rank": 2,
                "feature": "s_since_last_in_min",
                "value": 20.0,
                "text": "Sender last received money 20 min earlier — raises the risk score",
            },
            {
                "rank": 3,
                "feature": "payment_format_code",
                "value": 0.0,
                "text": "Sent by ACH — raises the risk score",
            },
        ],
        subgraph={
            "edges": edges,
            "dominant_path": {"txn_ids": [101, 102, 103]},
            "motif": {"signals": ["sender fanned out to 9 payees in 24 h"]},
        },
    )


@pytest.fixture
def evidence():
    return build_case_evidence(1, [alert_input()]).items
