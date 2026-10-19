"""Response models: the OpenAPI contract the frontend types are generated from (M3.08)."""

from __future__ import annotations

from pydantic import BaseModel


class AlertSummary(BaseModel):
    id: int
    account_id: str
    alert_date: str
    score: float
    score_top3_mean: float
    calibrated_prob: float | None
    typology_pred: str
    typology_conf: float
    top_txn_id: int
    top_amount: float
    top_currency: str
    n_transactions: int
    n_flagged: int
    status: str


class AlertList(BaseModel):
    items: list[AlertSummary]
    next_cursor: str | None
    total: int
    threshold: float


class Reason(BaseModel):
    rank: int
    feature: str
    value: float
    shap: float
    text: str
    evidence_id: str


class DispositionOut(BaseModel):
    id: int
    action: str
    reason_code: str
    note: str
    user_id: int
    created_at: str


class AlertDetail(AlertSummary):
    reasons: list[Reason]
    dispositions: list[DispositionOut]


class ModelInfo(BaseModel):
    id: int
    name: str
    dataset: str
    threshold: float
    alert_floor: float | None


class DayCount(BaseModel):
    date: str
    alerts: int


class QueueMeta(BaseModel):
    model: ModelInfo
    days: list[DayCount]
    by_status: dict[str, int]
    typologies: list[str]
    dismiss_reasons: dict[str, str]
    escalate_reasons: dict[str, str]


class GraphNode(BaseModel):
    id: str
    is_center: bool
    max_score: float
    degree: int


class GraphEdge(BaseModel):
    evidence_id: str
    txn_id: int
    from_: str
    to: str
    ts: str
    amount_paid: float
    currency_paid: str
    amount_received: float
    currency_received: str
    payment_format: str
    score: float
    flagged: bool
    on_dominant_path: bool

    model_config = {
        "populate_by_name": True,
        "alias_generator": lambda name: "from" if name == "from_" else name,
    }


class Window(BaseModel):
    from_: str
    to: str

    model_config = {
        "populate_by_name": True,
        "alias_generator": lambda name: "from" if name == "from_" else name,
    }


class DominantPath(BaseModel):
    evidence_id: str
    txn_ids: list[int]
    evidence_ids: list[str]


class Motif(BaseModel):
    evidence_id: str
    signals: list[str]


class Subgraph(BaseModel):
    alert_id: int
    window: Window
    center: str
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    dominant_path: DominantPath
    motif: Motif
    truncated: bool
