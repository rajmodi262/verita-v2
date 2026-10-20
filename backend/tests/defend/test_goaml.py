"""goAML export: valid against the bundled official schema, deterministic, and bound to the case."""

from __future__ import annotations

import copy
from typing import Any

import pytest

from verita.defend import goaml
from verita.defend.merkle import MerkleTree, changed_leaves


def _payment(txn_id: int, amount: float, currency: str, fmt: str = "ACH") -> dict[str, Any]:
    return {
        "id": f"EV-TXN-{txn_id}",
        "kind": "txn",
        "payload": {
            "txn_id": txn_id,
            "ts": "2022-09-09T16:01:00",
            "from_bank": "13554",
            "from_account": "8018BB080",
            "to_bank": "701",
            "to_account": "800A8E530",
            "amount_paid": amount,
            "currency_paid": currency,
            "amount_received": amount,
            "currency_received": currency,
            "payment_format": fmt,
            "score": 0.99,
        },
    }


@pytest.fixture
def items() -> dict[str, Any]:
    return {
        "EV-CASE-7": {"id": "EV-CASE-7", "kind": "case", "payload": {"typology": "FAN-OUT"}},
        "EV-TXN-2": _payment(2, 9_500.0, "US Dollar"),
        "EV-TXN-1": _payment(1, 1_200.5, "Euro", "Wire"),
        "EV-TXN-3": _payment(3, 0.25, "Bitcoin"),
        "narrative": {
            "sentences": [
                {
                    "section": "who",
                    "text": "Account 8018BB080 paid 3 payees.",
                    "evidence_ids": ["EV-CASE-7"],
                }
            ]
        },
        "verification": {"passed": True, "verifier_version": "1.0.0"},
        "approval": {
            "case_id": 7,
            "title": "Fan-out around 13554:8018BB080",
            "approved_by": "marcus",
            "approver_role": "mlro",
            "approved_at": "2026-10-20T10:00:00+00:00",
            "ledger_head": {"seq": 9, "hash": "ab" * 32},
        },
    }


def test_report_is_valid_against_the_official_schema(items):
    leaf = goaml.leaf(items)
    assert leaf["schema_valid"], leaf["errors"]
    xml = leaf["xml"]
    # one transaction per payment, ordered by ID; amounts in EUR
    assert xml.index("<transactionnumber>1<") < xml.index("<transactionnumber>2<")
    assert "<foreign_currency_code>USD</foreign_currency_code>" in xml
    assert "<foreign_amount>9500.00</foreign_amount>" in xml
    assert "<foreign_currency_code>BTC" not in xml  # no ISO code: EUR equivalent only
    assert "<indicator>" in xml and "[EV-CASE-7]" in xml


def test_report_is_deterministic_and_regenerates_from_the_evidence(items):
    leaf = goaml.leaf(items)
    assert goaml.leaf(copy.deepcopy(items))["xml"] == leaf["xml"]
    signed = {**items, "goaml": leaf}
    assert goaml.regenerates(signed) is True
    signed["EV-TXN-2"]["payload"]["amount_paid"] = 9_999.0  # evidence edited after signing
    assert goaml.regenerates(signed) is False
    assert goaml.regenerates(items) is None  # signed before goAML existed


def test_editing_the_filed_xml_breaks_the_case_signature(items):
    signed = {**items, "goaml": goaml.leaf(items)}
    expected = MerkleTree.build(signed).leaf_hex()
    tampered = copy.deepcopy(signed)
    tampered["goaml"]["xml"] = tampered["goaml"]["xml"].replace("9500.00", "950.00")
    assert changed_leaves(expected, tampered) == ["goaml"]


def test_schema_violations_are_reported_not_hidden(items):
    settings = {**goaml.load_settings(), "report_code": "NOT-A-CODE"}
    leaf = goaml.leaf(items, settings)
    assert not leaf["schema_valid"] and any("report_code" in e for e in leaf["errors"])


def test_long_narratives_are_truncated_with_a_pointer(items):
    sentence = {"section": "what", "text": "x" * 500, "evidence_ids": ["EV-CASE-7"]}
    items["narrative"]["sentences"] = [sentence] * 20
    leaf = goaml.leaf(items)
    assert leaf["schema_valid"], leaf["errors"]
    assert "full verified narrative is in the signed case file" in leaf["xml"]
