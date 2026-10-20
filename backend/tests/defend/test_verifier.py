"""Claims, verifier rules, offline narratives and fault injection on a fully known case."""

from __future__ import annotations

import pytest

from tests.defend.conftest import alert_input
from verita.defend.claims import extract
from verita.defend.evidence import build_case_evidence, facts
from verita.defend.faults import FAULTS, inject
from verita.defend.narrative import offline_sentences
from verita.defend.verifier import verify

FOREIGN = ["80F00FA11", "8123ABCD9"]


def kinds(text):
    return [(c.kind, c.value) for c in extract(text)]


# ── claim parsing ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("paid $48.5k", [("amount", 48500.0)]),
        ("paid USD 1,234.56", [("amount", 1234.56)]),
        ("1,200.00 Euro and 2.3 million Bitcoin", [("amount", 1200.0), ("amount", 2300000.0)]),
        (
            "on 2022-09-08 and 8 September 2022 and Sept 9, 2022",
            [("date", "2022-09-08"), ("date", "2022-09-08"), ("date", "2022-09-09")],
        ),
        ("in 35 minutes then 6.0 days", [("duration", 35.0), ("duration", 8640.0)]),
        ("account 8000EBD30 at bank 70", [("account", "8000EBD30"), ("bank", "70")]),
        (
            "a fan out then a GATHER-SCATTER",
            [("typology", "FAN-OUT"), ("typology", "GATHER-SCATTER")],
        ),
        ("score of 91.2%", [("percent", 91.2)]),
        ("12 payments to 4 distinct accounts", [("count", 12.0), ("count", 4.0)]),
    ],
)
def test_claim_parsers(text, expected):
    assert kinds(text) == expected


def test_amounts_are_not_double_counted_as_counts():
    assert kinds("sent 3 payments of 1,000.00 US Dollar") == [("count", 3.0), ("amount", 1000.0)]


def test_rounding_resolution_follows_the_writer():
    (claim,) = extract("about $48.5k")
    assert claim.resolution == pytest.approx(50.0)
    (exact,) = extract("48,512.33 US Dollar")
    assert exact.resolution == pytest.approx(0.005)


def test_invalid_dates_are_ignored():
    assert kinds("on 2022-02-30") == []


# ── evidence facts ───────────────────────────────────────────────────────────


def test_case_evidence_has_every_kind(evidence):
    assert {e["kind"] for e in evidence.values()} == {
        "alert",
        "reason",
        "txn",
        "path",
        "motif",
        "case",
    }
    case = evidence["EV-CASE-1"]["payload"]
    assert case["total_usd"] == pytest.approx(9800 + 9750.5 + 9700.25 + 1200 * 1.08)
    assert case["banks"] == ["11", "70", "123"]
    path = evidence["EV-PATH-7"]["payload"]
    assert path["accounts"] == ["8000AAAA1", "8000BBBB2", "8000CCCC3", "8000DDDD4"]
    assert path["duration_minutes"] == 65.0


def test_path_facts_include_the_total_when_single_currency(evidence):
    totals = [f.value for f in facts(evidence["EV-PATH-7"]) if f.kind == "amount"]
    assert 29250.75 in totals


# ── verifier ─────────────────────────────────────────────────────────────────


def test_offline_narrative_verifies_cleanly(evidence):
    report = verify(offline_sentences(evidence), evidence)
    assert report.passed, report.to_dict()
    assert all(report.coverage.values())
    assert report.to_dict()["verifier_version"] == "1.0.0"


def test_rounded_amounts_pass_and_wrong_ones_fail(evidence):
    ok = [
        {
            "section": "how",
            "text": "The first hop paid about $9.8k.",
            "evidence_ids": ["EV-TXN-101"],
        }
    ]
    assert verify(ok, evidence).sentences[0].passed
    bad = [
        {
            "section": "how",
            "text": "The first hop paid 9,950.00 US Dollar.",
            "evidence_ids": ["EV-TXN-101"],
        }
    ]
    result = verify(bad, evidence).sentences[0]
    assert not result.passed
    assert result.claims[0].detail == "cited evidence says amount 9800.0 US Dollar"


def test_claims_must_match_the_cited_item_not_the_case(evidence):
    s = [{"section": "how", "text": "It paid 9,750.50 US Dollar.", "evidence_ids": ["EV-TXN-101"]}]
    assert not verify(s, evidence).sentences[0].passed  # true of EV-TXN-102, not of 101


def test_citation_rules(evidence):
    report = verify(
        [
            {"section": "who", "text": "No numbers here.", "evidence_ids": []},
            {"section": "who", "text": "No numbers here.", "evidence_ids": ["EV-TXN-999"]},
            {"section": "vibes", "text": "No numbers here.", "evidence_ids": ["EV-CASE-1"]},
        ],
        evidence,
    )
    errors = [s.errors for s in report.sentences]
    assert "uncited" in errors[0][0]
    assert "EV-TXN-999" in errors[1][0]
    assert "unknown section" in errors[2][0]
    assert not report.passed


def test_coverage_requires_path_total_range_and_typology(evidence):
    only_who = [s for s in offline_sentences(evidence) if s["section"] == "who"]
    report = verify(only_who, evidence)
    assert not report.passed
    assert report.coverage == {
        "dominant path": False,
        "case total": False,
        "date range": False,
        "typology": False,
    }


def test_empty_narrative_fails(evidence):
    report = verify([], evidence)
    assert not report.passed and report.errors[0] == "the narrative is empty"


def test_unattributed_case_must_say_so():
    ev = build_case_evidence(2, [alert_input(8, typology="UNATTRIBUTED")]).items
    assert verify(offline_sentences(ev), ev).passed
    without = [s for s in offline_sentences(ev) if "unattributed" not in s["text"]]
    assert verify(without, ev).coverage["typology"] is False


# ── fault injection ──────────────────────────────────────────────────────────


@pytest.mark.parametrize("fault", FAULTS)
def test_every_fault_is_planted_and_caught(evidence, fault):
    clean = offline_sentences(evidence)
    caught = 0
    for seed in range(20):
        variant = inject(clean, fault, seed, evidence, FOREIGN)
        assert variant is not None
        assert variant.sentences != clean
        report = verify(variant.sentences, evidence)
        caught += not report.passed
    assert caught == 20, fault


def test_injection_is_reproducible(evidence):
    clean = offline_sentences(evidence)
    a = inject(clean, "wrong_date", 3, evidence, FOREIGN)
    b = inject(clean, "wrong_date", 3, evidence, FOREIGN)
    assert a is not None and b is not None and a.sentences == b.sentences
    assert clean == offline_sentences(evidence)  # the clean narrative is untouched


def test_date_range_must_match_both_ends(evidence):
    ok = [
        {
            "section": "when",
            "text": "Between 2022-09-07 and 2022-09-08 it ran.",
            "evidence_ids": ["EV-CASE-1"],
        }
    ]
    assert verify(ok, evidence).sentences[0].passed
    # 2022-09-08 is a real active day, but not where the period starts
    late = [
        {
            "section": "when",
            "text": "Between 2022-09-08 and 2022-09-08 it ran.",
            "evidence_ids": ["EV-CASE-1"],
        }
    ]
    result = verify(late, evidence).sentences[0]
    assert not result.passed
    assert [c.kind for c in result.claims if not c.passed] == ["date_range"]


def test_small_amounts_keep_their_precision():
    from verita.defend.narrative import money

    assert money(0.0034, "Bitcoin") == "0.0034 Bitcoin"
    assert money(1234.5, "Euro") == "1,234.50 Euro"
    assert money(0, "Euro") == "0.00 Euro"
    ev = build_case_evidence(3, [alert_input(9)]).items
    payload = ev["EV-TXN-101"]["payload"]
    payload["amount_paid"] = 0.0034
    sentence = [
        {"section": "how", "text": "It paid 0.0034 US Dollar.", "evidence_ids": ["EV-TXN-101"]}
    ]
    assert verify(sentence, ev).sentences[0].passed
    wrong = [
        {"section": "how", "text": "It paid 0.0035 US Dollar.", "evidence_ids": ["EV-TXN-101"]}
    ]
    assert not verify(wrong, ev).sentences[0].passed


def test_amount_faults_never_plant_a_no_op(evidence):
    clean = offline_sentences(evidence)
    for seed in range(30):
        variant = inject(clean, "amount_small", seed, evidence, FOREIGN)
        assert variant is not None and variant.sentences != clean
