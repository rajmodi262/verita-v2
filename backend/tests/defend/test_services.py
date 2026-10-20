"""Ledger hash chain, job queue retries, LLM providers and fallback, PDF rendering."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
import pytest

from verita.db.base import Base
from verita.db.case_models import GENESIS_HASH, CaseEvent, Job
from verita.db.models import Role, User
from verita.db.session import make_engine, make_session_factory, transaction
from verita.defend import narrative as narr
from verita.defend.pdf import latin1, render_pdf
from verita.services import jobs, ledger

# ── ledger ───────────────────────────────────────────────────────────────────


def _event(seq, prev, payload, case_id=1):
    created = datetime(2022, 9, 8, 10, seq, tzinfo=UTC)
    return CaseEvent(
        case_id=case_id,
        seq=seq,
        type="x",
        actor_id=None,
        payload=payload,
        created_at=created,
        prev_hash=prev,
        hash=ledger.event_hash(prev, case_id, seq, "x", None, payload, created),
    )


def _chain(n=3):
    out, prev = [], GENESIS_HASH
    for seq in range(1, n + 1):
        ev = _event(seq, prev, {"n": seq})
        out.append(ev)
        prev = ev.hash
    return out


def test_intact_chain_verifies():
    result = ledger.verify_chain(_chain())
    assert result["valid"] and result["length"] == 3 and result["head"] == _chain()[-1].hash


def test_altered_content_is_detected():
    chain = _chain()
    chain[1].payload = {"n": 99}
    assert ledger.verify_chain(chain) == {
        "valid": False,
        "broken_at": 2,
        "reason": "event content was altered",
    }


def test_deleted_and_relinked_events_are_detected():
    chain = _chain()
    assert ledger.verify_chain([chain[0], chain[2]])["reason"] == "missing event 2"
    forged = _event(2, "f" * 64, {"n": 2})
    assert ledger.verify_chain([chain[0], forged, chain[2]])["reason"] == "prev_hash does not link"


def test_hash_depends_on_every_field():
    base = ledger.event_hash(GENESIS_HASH, 1, 1, "t", 2, {"a": 1}, datetime(2022, 1, 1, tzinfo=UTC))
    variants = [
        ledger.event_hash("1" * 64, 1, 1, "t", 2, {"a": 1}, datetime(2022, 1, 1, tzinfo=UTC)),
        ledger.event_hash(GENESIS_HASH, 2, 1, "t", 2, {"a": 1}, datetime(2022, 1, 1, tzinfo=UTC)),
        ledger.event_hash(GENESIS_HASH, 1, 1, "u", 2, {"a": 1}, datetime(2022, 1, 1, tzinfo=UTC)),
        ledger.event_hash(GENESIS_HASH, 1, 1, "t", 3, {"a": 1}, datetime(2022, 1, 1, tzinfo=UTC)),
        ledger.event_hash(GENESIS_HASH, 1, 1, "t", 2, {"a": 2}, datetime(2022, 1, 1, tzinfo=UTC)),
        ledger.event_hash(GENESIS_HASH, 1, 1, "t", 2, {"a": 1}, datetime(2022, 1, 2, tzinfo=UTC)),
    ]
    assert base not in variants and len(set(variants)) == len(variants)


# ── jobs ─────────────────────────────────────────────────────────────────────


@pytest.fixture
def factory():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    f = make_session_factory(engine)
    with transaction(f) as db:
        db.add(User(username="u", password_hash="x", role=Role.ANALYST))
    return f


def test_job_runs_once_and_records_its_result(factory):
    calls = []

    @jobs.handler("test.ok")
    def _ok(db, job):
        calls.append(job.id)
        return {"echo": job.payload["v"]}

    with transaction(factory) as db:
        job_id = jobs.enqueue(db, "test.ok", {"v": 3}, None).id
    done = jobs.run(factory, job_id)
    assert done is not None and done.status == "done" and done.result == {"echo": 3}
    assert jobs.run(factory, job_id) is None  # nothing left to claim
    assert calls == [job_id]


def test_failing_job_retries_then_fails_and_rolls_back_its_work(factory):
    @jobs.handler("test.boom")
    def _boom(db, job):
        db.add(User(username=f"ghost{job.attempts}", password_hash="x", role=Role.ANALYST))
        db.flush()
        raise RuntimeError("provider down")

    with transaction(factory) as db:
        job_id = jobs.enqueue(db, "test.boom", {}, None).id
    states = [jobs.run(factory, job_id).status for _ in range(jobs.MAX_ATTEMPTS)]  # type: ignore[union-attr]
    assert states == ["queued", "queued", "failed"]
    with factory() as db:
        job = db.get(Job, job_id)
        assert job.attempts == 3 and "provider down" in job.error
        assert db.query(User).filter(User.username.like("ghost%")).count() == 0
        view = jobs.job_view(job)
        assert view["status"] == "failed" and view["progress"] == "failed"


def test_unknown_job_kind_fails(factory):
    with transaction(factory) as db:
        job_id = jobs.enqueue(db, "nope", {}, None).id
    for _ in range(jobs.MAX_ATTEMPTS):
        jobs.run(factory, job_id)
    with factory() as db:
        assert "no handler" in db.get(Job, job_id).error


def test_oldest_queued_job_is_claimed_first(factory):
    with transaction(factory) as db:
        first = jobs.enqueue(db, "a", {}, None).id
        jobs.enqueue(db, "a", {}, None)
    with transaction(factory) as db:
        claimed = jobs.claim(db)
        assert claimed is not None and claimed.id == first and claimed.status == "running"


# ── narrative providers ──────────────────────────────────────────────────────

GOOD = json.dumps({"sentences": [{"section": "who", "text": "x", "evidence_ids": ["EV-CASE-1"]}]})


class FakeProvider:
    def __init__(self, name, replies):
        self.name, self.model, self.replies, self.calls = name, f"{name}-m", list(replies), 0

    def complete(self, system, user):
        self.calls += 1
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def test_parse_output_accepts_json_and_fenced_json_only():
    assert narr.parse_output(GOOD)[0]["section"] == "who"
    assert narr.parse_output(f"```json\n{GOOD}\n```")[0]["text"] == "x"
    for bad in (
        "Here is your narrative: blah",
        '{"sentences": []}',
        '{"sentences":[{"section":"vibes","text":"x"}]}',
    ):
        with pytest.raises(narr.ProviderError):
            narr.parse_output(bad)


def test_draft_falls_back_in_order(evidence):
    gemini = FakeProvider("gemini", ["not json", narr.ProviderError("HTTP 429")])
    groq = FakeProvider("groq", [GOOD])
    d = narr.draft(evidence, [gemini, groq])
    assert (d.mode, d.provider, d.model) == ("llm", "groq", "groq-m")
    assert gemini.calls == 2 and len(d.attempts) == 2
    assert d.prompt_hash == narr.prompt_hash()


def test_draft_goes_offline_when_every_provider_fails(evidence):
    dead = FakeProvider("gemini", [httpx.ConnectError("down")] * 2)
    d = narr.draft(evidence, [dead])
    assert d.mode == "offline" and d.provider == "template" and len(d.attempts) == 2
    with pytest.raises(narr.ProviderError, match="every LLM provider failed"):
        narr.draft(evidence, [FakeProvider("gemini", ["x", "y"])], mode="llm")
    assert narr.draft(evidence, [FakeProvider("gemini", [GOOD])], mode="offline").mode == "offline"


def test_evidence_block_marks_data_and_is_deterministic(evidence):
    block = narr.evidence_block(evidence)
    assert block.startswith("<EVIDENCE>") and block.endswith("</EVIDENCE>")
    assert block == narr.evidence_block(dict(reversed(list(evidence.items()))))


def _mock(monkeypatch, status, body, seen):
    def fake_post(url, headers, json, timeout):
        seen.update(url=url, headers=headers, json=json)
        return httpx.Response(status, json=body)

    monkeypatch.setattr(narr.httpx, "post", fake_post)


def test_gemini_request_and_response(monkeypatch):
    seen = {}
    _mock(monkeypatch, 200, {"candidates": [{"content": {"parts": [{"text": GOOD}]}}]}, seen)
    out = narr.GeminiProvider("k", "gemini-x").complete("sys", "user")
    assert out == GOOD
    assert seen["url"].endswith("/models/gemini-x:generateContent")
    assert seen["headers"] == {"x-goog-api-key": "k"}  # key in a header, never in the URL
    assert seen["json"]["generationConfig"]["temperature"] == 0
    _mock(monkeypatch, 429, {}, seen)
    with pytest.raises(narr.ProviderError, match="429"):
        narr.GeminiProvider("k", "gemini-x").complete("s", "u")
    _mock(monkeypatch, 200, {"candidates": []}, seen)
    with pytest.raises(narr.ProviderError, match="no text"):
        narr.GeminiProvider("k", "gemini-x").complete("s", "u")


def test_groq_request_and_response(monkeypatch):
    seen = {}
    _mock(monkeypatch, 200, {"choices": [{"message": {"content": GOOD}}]}, seen)
    assert narr.GroqProvider("k", "llama").complete("sys", "user") == GOOD
    assert seen["json"]["response_format"] == {"type": "json_object"}
    assert seen["headers"]["Authorization"] == "Bearer k"
    _mock(monkeypatch, 200, {"choices": []}, seen)
    with pytest.raises(narr.ProviderError, match="no text"):
        narr.GroqProvider("k", "llama").complete("s", "u")


def test_providers_follow_settings_and_skip_missing_keys():
    from verita.core.config import Settings

    s = Settings(
        _env_file=None, llm_providers=["groq", "gemini"], groq_api_key="g", gemini_api_key=None
    )
    names = [p.name for p in narr.providers_from_settings(s)]
    assert names == ["groq"]


# ── pdf ──────────────────────────────────────────────────────────────────────


def test_pdf_renders_and_transliterates():
    assert latin1("€1 → £2 — ok") == "EUR1 -> GBP2 - ok"
    export = {
        "case_id": 3,
        "title": "Fan-out around 70:8000AAAA1",
        "items": {
            "EV-CASE-3": {},
            "narrative": {
                "version": 1,
                "provider": "template",
                "model": "m",
                "sentences": [
                    {
                        "section": "who",
                        "text": "Paid 1,200.00 Euro → onward",
                        "evidence_ids": ["EV-CASE-3"],
                    }
                ],
            },
            "approval": {"approved_by": "marcus", "approver_role": "mlro", "approved_at": "2022"},
            "verification": {"verifier_version": "1.0.0", "passed": True},
        },
        "leaves": {"EV-CASE-3": "ab" * 32},
        "merkle_root": "cd" * 32,
        "signature": {
            "key_id": "k" * 16,
            "algorithm": "Ed25519",
            "value": "sig",
            "signed_at": "now",
        },
    }
    assert render_pdf(export).startswith(b"%PDF")
