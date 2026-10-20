"""Response and request models for case files, jobs and keys (drive the frontend's types)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class SentenceIn(BaseModel):
    section: Literal["who", "what", "when", "where", "why", "how"]
    text: str = Field(min_length=1, max_length=600)
    evidence_ids: list[str] = Field(default_factory=list, max_length=20)


class EvidenceItem(BaseModel):
    id: str
    kind: str
    payload: dict[str, Any]


class NarrativeOut(BaseModel):
    id: int
    version: int
    mode: str
    provider: str
    model: str
    prompt_hash: str
    sentences: list[SentenceIn]
    created_by: str
    created_at: str


class ClaimOut(BaseModel):
    kind: str
    text: str
    passed: bool
    expected: str | None
    detail: str


class SentenceReport(BaseModel):
    index: int
    section: str
    text: str
    evidence_ids: list[str]
    passed: bool
    errors: list[str]
    claims: list[ClaimOut]


class Report(BaseModel):
    passed: bool
    verifier_version: str
    sentences: list[SentenceReport]
    coverage: dict[str, bool]
    errors: list[str]
    failed_sentences: list[int]


class VerificationOut(BaseModel):
    id: int
    passed: bool
    report: Report
    created_at: str


class EventOut(BaseModel):
    seq: int
    type: str
    actor: str | None
    payload: dict[str, Any]
    created_at: str
    hash: str
    prev_hash: str


class LedgerCheck(BaseModel):
    valid: bool
    broken_at: int | None
    reason: str | None
    head: str | None = None
    length: int | None = None


class SignatureOut(BaseModel):
    merkle_root: str
    key_id: str
    signed_by: str
    signed_at: str


class Permissions(BaseModel):
    edit: bool
    submit: bool
    approve: bool
    approve_blockers: list[str]
    return_: bool = Field(alias="return")
    close: bool

    model_config = {"populate_by_name": True}


class CaseDetail(BaseModel):
    id: int
    title: str
    state: str
    created_by: str
    created_at: str
    updated_at: str
    alert_ids: list[int]
    evidence: list[EvidenceItem]
    narrative: NarrativeOut | None
    verification: VerificationOut | None
    events: list[EventOut]
    ledger: LedgerCheck
    signature: SignatureOut | None
    permissions: Permissions


class CaseSummary(BaseModel):
    id: int
    title: str
    state: str
    created_by: str
    updated_at: str
    alerts: int


class CaseList(BaseModel):
    items: list[CaseSummary]


class CaseMeta(BaseModel):
    return_reasons: dict[str, str]
    close_reasons: dict[str, str]
    llm_providers: list[str]
    offline_only: bool


class JobOut(BaseModel):
    id: int
    kind: str
    status: str
    attempts: int
    progress: str
    result: dict[str, Any] | None
    error: str | None
    created_at: str
    updated_at: str


class SignatureCheck(BaseModel):
    valid: bool
    signature_valid: bool
    root_matches: bool
    recomputed_root: str
    changed_leaves: list[str]
    ledger: LedgerCheck


class PublicKey(BaseModel):
    key_id: str
    algorithm: str
    public_key_pem: str
    created_at: str
    message_format: str


class Keys(BaseModel):
    keys: list[PublicKey]


class CreateCaseIn(BaseModel):
    alert_ids: list[int] = Field(min_length=1, max_length=10)
    title: str | None = Field(default=None, max_length=200)


class DraftIn(BaseModel):
    mode: Literal["auto", "llm", "offline"] = "auto"


class EditIn(BaseModel):
    sentences: list[SentenceIn] = Field(min_length=1, max_length=40)


class ReasonIn(BaseModel):
    reason: str = Field(min_length=1, max_length=40)
    note: str = Field(default="", max_length=2000)
