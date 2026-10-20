"""Golden test (M6.12): the verifier's verdicts on 30 fixed narratives must not drift.

The 30 narratives are the known case's clean narrative, an unattributed case's clean
narrative, and 28 single-fault variants (every fault type, several seeds). Their verdicts —
pass/fail, failing sentences, failing claim kinds and coverage — are snapshotted in
``golden/verifier_30.json``. A change to claims, facts or rules that alters any verdict fails
this test; regenerate deliberately with ``VERITA_UPDATE_GOLDEN=1``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from tests.defend.conftest import alert_input
from verita.defend.evidence import build_case_evidence
from verita.defend.faults import FAULTS, inject
from verita.defend.narrative import offline_sentences
from verita.defend.verifier import verify

GOLDEN = Path(__file__).parent / "golden" / "verifier_30.json"
FOREIGN = ["80F00FA11", "8123ABCD9"]


def _narratives() -> list[tuple[str, list[dict], dict]]:
    known = build_case_evidence(1, [alert_input()]).items
    unattributed = build_case_evidence(2, [alert_input(8, typology="UNATTRIBUTED")]).items
    out = [
        ("clean/known", offline_sentences(known), known),
        ("clean/unattributed", offline_sentences(unattributed), unattributed),
    ]
    seeds = iter(range(1000))
    while len(out) < 30:
        for fault in FAULTS:
            if len(out) == 30:
                break
            seed = next(seeds)
            variant = inject(offline_sentences(known), fault, seed, known, FOREIGN)
            assert variant is not None
            out.append((f"{fault}/{seed}", variant.sentences, known))
    return out


def _verdicts() -> dict[str, dict]:
    verdicts = {}
    for name, sentences, evidence in _narratives():
        report = verify(sentences, evidence)
        verdicts[name] = {
            "passed": report.passed,
            "failed_sentences": report.failed_sentences,
            "failed_claims": sorted(
                {c.kind for s in report.sentences for c in s.claims if not c.passed}
            ),
            "sentence_errors": sorted(
                {e.split(":")[0] for s in report.sentences for e in s.errors}
            ),
            "coverage": report.coverage,
        }
    return verdicts


def test_verdicts_match_the_golden_snapshot():
    verdicts = _verdicts()
    assert len(verdicts) == 30
    if os.environ.get("VERITA_UPDATE_GOLDEN") == "1" or not GOLDEN.exists():
        GOLDEN.parent.mkdir(exist_ok=True)
        GOLDEN.write_text(json.dumps(verdicts, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    assert verdicts == json.loads(GOLDEN.read_text(encoding="utf-8"))


def test_golden_set_is_two_clean_and_twenty_eight_caught():
    verdicts = json.loads(GOLDEN.read_text(encoding="utf-8"))
    clean = [k for k in verdicts if k.startswith("clean/")]
    assert all(verdicts[k]["passed"] for k in clean) and len(clean) == 2
    assert not any(v["passed"] for k, v in verdicts.items() if not k.startswith("clean/"))
