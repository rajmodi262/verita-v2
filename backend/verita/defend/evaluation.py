"""Adversarial evaluation of the verifier (PIVOT §8.4, M6.13–M6.15).

For a reproducible sample of test-window alerts, build each case's evidence exactly as the case
service does, write a clean narrative, and measure:

* **false-alarm rate** — clean narratives the verifier rejects;
* **detection rate per fault type** — variants with one planted fault that it rejects, with a
  Wilson 95% interval, plus **localisation** (the failing sentence is the one carrying the
  fault, rather than the narrative failing for another reason);
* **misses** — up to five undetected variants per type, verbatim, so the gaps are visible;
* when an LLM provider is configured: the **raw unsupported-claim rate** of clean LLM drafts
  before any verification — how often the model writes something the evidence does not say.

Results go to ``artifacts/<dataset>/defend/verifier_eval.json``.
"""

from __future__ import annotations

import json
import random
import time
from collections import Counter
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from verita.db.detect_models import Alert
from verita.defend import narrative as narr
from verita.defend.evidence import AlertInput, build_case_evidence
from verita.defend.faults import FAULTS, inject
from verita.defend.verifier import VERIFIER_VERSION, verify
from verita.ml.evaluation import wilson
from verita.pipeline.config import Dataset
from verita.services.alerts import champion
from verita.services.evidence import AlertRef, EvidenceStore, SubgraphSource

MAX_MISSES = 5


def _sample(db: Session, n: int, seed: int) -> list[Alert]:
    version = champion(db)
    ids = list(db.scalars(select(Alert.id).where(Alert.model_version_id == version.id)))
    rng = random.Random(seed)  # noqa: S311  # nosec B311 - sampling, not crypto
    picked = sorted(rng.sample(ids, min(n, len(ids))))
    stmt = select(Alert).where(Alert.id.in_(picked)).options(selectinload(Alert.reasons))
    return list(db.scalars(stmt))


def _inputs(db: Session, store: SubgraphSource, alerts: list[Alert]) -> list[AlertInput]:
    threshold = champion(db).threshold
    out = []
    for a in alerts:
        ref = AlertRef(a.id, a.account_id, a.alert_date, a.top_txn_id, threshold)
        out.append(
            AlertInput(
                id=a.id,
                account_id=a.account_id,
                alert_date=a.alert_date.isoformat(),
                score=a.score,
                typology_pred=a.typology_pred,
                typology_conf=a.typology_conf,
                n_transactions=a.n_transactions,
                n_flagged=a.n_flagged,
                top_txn_id=a.top_txn_id,
                reasons=[
                    {"rank": r.rank, "feature": r.feature, "value": r.value, "text": r.text}
                    for r in a.reasons
                ],
                subgraph=store.subgraph(ref),
            )
        )
    return out


def _rate(hits: int, total: int) -> dict[str, Any]:
    return {"hits": hits, "total": total, **wilson(hits, total).to_dict()}


def run_eval(
    dataset: Dataset,
    db: Session,
    cases: int = 300,
    seed: int = 0,
    providers: list[narr.Provider] | None = None,
    llm_cases: int = 30,
) -> dict[str, Any]:
    started = time.perf_counter()
    store = EvidenceStore(dataset.processed_dir / "evidence.duckdb")
    inputs = _inputs(db, store, _sample(db, cases, seed))
    built = [(a, build_case_evidence(a.id, [a]).items) for a in inputs]
    accounts = sorted({a.account_id.partition(":")[2] for a in inputs})

    clean_fail: list[dict[str, Any]] = []
    per_fault: dict[str, dict[str, Any]] = {
        f: {"planted": 0, "detected": 0, "localised": 0, "misses": []} for f in FAULTS
    }
    claims_checked = 0
    for a, ev in built:
        sentences = narr.offline_sentences(ev)
        report = verify(sentences, ev)
        claims_checked += sum(len(s.claims) for s in report.sentences)
        if not report.passed:
            clean_fail.append(
                {"alert_id": a.id, "errors": report.errors, "failed": report.failed_sentences}
            )
            continue  # faults are planted only in narratives that verify cleanly
        own = {e["payload"].get("account") for e in ev.values() if e["kind"] == "alert"}
        own |= {
            acct for e in ev.values() if e["kind"] == "path" for acct in e["payload"]["accounts"]
        }
        foreign = [x for x in accounts if x not in own]
        for fault in FAULTS:
            variant = inject(sentences, fault, a.id, ev, foreign)
            if variant is None:
                continue
            stats = per_fault[fault]
            stats["planted"] += 1
            checked = verify(variant.sentences, ev)
            if not checked.passed:
                stats["detected"] += 1
                if variant.sentence in checked.failed_sentences:
                    stats["localised"] += 1
            elif len(stats["misses"]) < MAX_MISSES:
                stats["misses"].append(
                    {
                        "alert_id": a.id,
                        "change": variant.description,
                        "sentence": variant.sentences[variant.sentence],
                    }
                )

    faults_out = {
        f: {
            "planted": s["planted"],
            "detection": _rate(s["detected"], s["planted"]),
            "localisation": _rate(s["localised"], s["detected"]),
            "misses": s["misses"],
        }
        for f, s in per_fault.items()
    }
    total_planted = sum(s["planted"] for s in per_fault.values())
    total_detected = sum(s["detected"] for s in per_fault.values())
    result: dict[str, Any] = {
        "dataset": dataset.name,
        "verifier_version": VERIFIER_VERSION,
        "seed": seed,
        "cases": len(built),
        "claims_checked_on_clean": claims_checked,
        "clean_false_alarm": _rate(len(clean_fail), len(built)),
        "clean_failures": clean_fail[:MAX_MISSES],
        "faults": faults_out,
        "overall_detection": _rate(total_detected, total_planted),
        "typologies": dict(Counter(a.typology_pred for a in inputs)),
        "llm": _llm_eval(built[:llm_cases], providers or []),
    }
    result["seconds"] = round(time.perf_counter() - started, 1)
    out = dataset.artifacts_dir / "defend"
    out.mkdir(parents=True, exist_ok=True)
    (out / "verifier_eval.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def _llm_eval(
    built: list[tuple[AlertInput, dict[str, Any]]], providers: list[narr.Provider]
) -> dict[str, Any]:
    """Raw quality of LLM drafts *before* verification gates them (M6.15)."""
    if not providers:
        return {
            "run": False,
            "reason": "not requested (run with --llm and a GEMINI_API_KEY / GROQ_API_KEY)",
        }
    drafts = claims = unsupported = uncited = sentences_total = passed = fallbacks = 0
    by_kind: Counter[str] = Counter()
    drafted_by: Counter[str] = Counter()  # keys and providers fail over, so record who wrote it
    for _, ev in built:
        try:
            d = narr.draft(ev, providers, mode="llm")
        except narr.ProviderError:
            fallbacks += 1
            continue
        drafts += 1
        drafted_by[f"{d.provider}/{d.model}"] += 1
        report = verify(d.sentences, ev)
        passed += report.passed
        for s in report.sentences:
            sentences_total += 1
            uncited += any("uncited" in e or "not in this case" in e for e in s.errors)
            for c in s.claims:
                claims += 1
                if not c.passed:
                    unsupported += 1
                    by_kind[c.kind] += 1
    return {
        "run": True,
        "providers": [p.name for p in providers],
        "models": [p.model for p in providers],
        "drafts": drafts,
        "provider_failures": fallbacks,
        "drafted_by": dict(drafted_by),
        "unsupported_claim_rate": _rate(unsupported, claims),
        "unsupported_by_kind": dict(by_kind),
        "citation_error_rate": _rate(uncited, sentences_total),
        "drafts_passing_verification": _rate(passed, drafts),
    }
