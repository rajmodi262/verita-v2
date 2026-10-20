"""goAML export: the signed case file as the suspicious transaction report an FIU receives.

goAML is UNODC's reporting platform used by most financial intelligence units. At approval the
report is generated from the case's own evidence and stored as one more Merkle leaf (``goaml``),
so the Ed25519 signature covers the exact XML that would be filed — ``verita-verify`` checks it
with no extra code. The leaf also records the settings it was built with, so anyone holding the
case file can regenerate the XML from the evidence and confirm the filing says what the evidence
says (:func:`regenerates`).

Mapping (one ``<transaction>`` per payment in the case file, ordered by transaction ID):

* amounts are converted to EUR, the local currency the bundled schema fixes; a payment in another
  currency also carries ``from_foreign_currency`` with the original amount and the rate used;
* both sides are accounts (``t_from``/``t_to``), identified by bank code and account number;
* ``reason`` is the verified narrative; ``action`` names the case, the approver and the ledger
  head; report indicators come from the typology (``configs/goaml.yaml``).

Code values (transmission mode, funds type, indicators) are FIU lookup tables; the defaults in
``configs/goaml.yaml`` are valid placeholders, not a claim about any FIU's list.
"""

from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET  # nosec B405 - builds XML, never parses input

from verita.optimize.planner import USD_PER_UNIT
from verita.pipeline.config import CONFIG_DIR, load_yaml

SCHEMA_PATH = Path(__file__).parent / "schemas" / "goaml-5.0.1.xsd"
SCHEMA_NAME = "goAML 5.0.1 (CRF Luxembourg distribution)"
LOCAL_CURRENCY = "EUR"
REASON_MAX = 4000
ISO_CURRENCY = {
    "US Dollar": "USD",
    "Euro": "EUR",
    "UK Pound": "GBP",
    "Yuan": "CNY",
    "Rupee": "INR",
    "Yen": "JPY",
    "Canadian Dollar": "CAD",
    "Swiss Franc": "CHF",
    "Australian Dollar": "AUD",
    "Brazil Real": "BRL",
    "Mexican Peso": "MXN",
    "Ruble": "RUB",
    "Saudi Riyal": "SAR",
    "Shekel": "ILS",
}  # Bitcoin has no ISO 4217 code: such payments carry only the EUR equivalent


def load_settings(path: Path | None = None) -> dict[str, Any]:
    raw: dict[str, Any] = load_yaml(path or CONFIG_DIR / "goaml.yaml")
    return {k: v for k, v in raw.items() if k != "version"}


def _eur(amount: float, currency: str) -> tuple[float, float]:
    """EUR value and the EUR-per-unit rate used (the planner's fixed rates)."""
    rate = USD_PER_UNIT.get(currency, 1.0) / USD_PER_UNIT["Euro"]
    return round(amount * rate, 2), round(rate, 6)


def _sub(parent: ET.Element, tag: str, text: Any = None) -> ET.Element:
    el = ET.SubElement(parent, tag)
    if text is not None:
        el.text = str(text)
    return el


def _account(parent: ET.Element, tag: str, bank: str, account: str) -> None:
    acc = _sub(parent, tag)
    _sub(acc, "institution_code", bank)
    _sub(acc, "account", account)
    _sub(acc, "account_name", f"Account {account} at bank {bank}")


def _side(tx: ET.Element, side: str, p: dict[str, Any], s: dict[str, Any]) -> None:
    prefix = "from" if side == "t_from" else "to"
    amount = p["amount_paid"] if prefix == "from" else p["amount_received"]
    currency = p["currency_paid"] if prefix == "from" else p["currency_received"]
    el = _sub(tx, side)
    _sub(el, f"{prefix}_funds_code", s["funds_code"])
    iso = ISO_CURRENCY.get(currency)
    if iso and iso != LOCAL_CURRENCY:
        fc = _sub(el, f"{prefix}_foreign_currency")
        _sub(fc, "foreign_currency_code", iso)
        _sub(fc, "foreign_amount", f"{amount:.2f}")
        _sub(fc, "foreign_exchange_rate", f"{_eur(1.0, currency)[1]:.6f}")
    _account(el, f"{prefix}_account", p[f"{prefix}_bank"], p[f"{prefix}_account"])
    _sub(el, f"{prefix}_country", "-")  # synthetic banks have no country


def _reason(items: dict[str, Any]) -> str:
    lines = []
    for sentence in items["narrative"]["sentences"]:
        cited = ", ".join(sentence.get("evidence_ids", []))
        lines.append(f"{sentence['text']} [{cited}]")
    text = "\n".join(lines)
    if len(text) > REASON_MAX:
        note = "\n[Truncated: the full verified narrative is in the signed case file.]"
        text = text[: REASON_MAX - len(note)] + note
    return text


def build(items: dict[str, Any], settings: dict[str, Any]) -> str:
    """The goAML ``<report>`` for a case, as UTF-8 XML text (deterministic)."""
    approval = items["approval"]
    case = next(
        v["payload"] for v in items.values() if isinstance(v, dict) and v.get("kind") == "case"
    )
    payments = sorted(
        (v["payload"] for v in items.values() if isinstance(v, dict) and v.get("kind") == "txn"),
        key=lambda p: int(p["txn_id"]),
    )
    report = ET.Element("report")
    _sub(report, "rentity_id", settings["rentity_id"])
    _sub(report, "submission_code", settings["submission_code"])
    _sub(report, "report_code", settings["report_code"])
    _sub(report, "entity_reference", f"VERITA-CASE-{approval['case_id']}")
    _sub(report, "submission_date", approval["approved_at"][:19])
    _sub(report, "currency_code_local", LOCAL_CURRENCY)
    _sub(report, "reason", _reason(items))
    _sub(
        report,
        "action",
        f"Verita case {approval['case_id']} ({approval['title']}) approved by "
        f"{approval['approved_by']} ({approval['approver_role']}) at {approval['approved_at']}; "
        f"narrative verified by verifier {items['verification'].get('verifier_version')}; "
        f"case ledger head #{approval['ledger_head']['seq']} {approval['ledger_head']['hash']}. "
        "This report is a leaf of the signed case file.",
    )
    for p in payments:
        tx = _sub(report, "transaction")
        _sub(tx, "transactionnumber", p["txn_id"])
        _sub(tx, "internal_ref_number", f"EV-TXN-{p['txn_id']}")
        _sub(
            tx,
            "transaction_description",
            f"{p['payment_format']}: {p['amount_paid']:.2f} {p['currency_paid']} paid, "
            f"{p['amount_received']:.2f} {p['currency_received']} received "
            f"(model score {p['score']})",
        )
        _sub(tx, "date_transaction", p["ts"][:19])
        _sub(
            tx,
            "transmode_code",
            settings["transmode_by_format"].get(p["payment_format"], settings["default_transmode"]),
        )
        _sub(tx, "amount_local", f"{_eur(p['amount_paid'], p['currency_paid'])[0]:.2f}")
        _side(tx, "t_from", p, settings)
        _side(tx, "t_to", p, settings)
    indicators = _sub(report, "report_indicators")
    codes = settings["indicators_by_typology"].get(case["typology"], settings["default_indicators"])
    for code in codes:
        _sub(indicators, "indicator", code)
    ET.indent(report)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(report, encoding="unicode") + "\n"
    )


@lru_cache(maxsize=1)
def _schema() -> Any:
    import xmlschema  # noqa: PLC0415 - heavy import, only when validating

    return xmlschema.XMLSchema11(str(SCHEMA_PATH))


def validate(xml: str) -> list[str]:
    """Schema and assertion errors (empty when the report is valid)."""
    return [f"{e.path}: {(e.reason or e.message)[:200]}" for e in _schema().iter_errors(xml)][:20]


def leaf(items: dict[str, Any], settings: dict[str, Any] | None = None) -> dict[str, Any]:
    """The ``goaml`` Merkle leaf for a case about to be signed."""
    settings = settings or load_settings()
    xml = build(items, settings)
    errors = validate(xml)
    return {
        "schema": SCHEMA_NAME,
        "schema_valid": not errors,
        "errors": errors,
        "settings": settings,
        "sha256": hashlib.sha256(xml.encode("utf-8")).hexdigest(),
        "xml": xml,
    }


def regenerates(items: dict[str, Any]) -> bool | None:
    """Does the stored report follow from the signed evidence? None when there is no report."""
    stored = items.get("goaml")
    if not isinstance(stored, dict):
        return None
    rest = {k: v for k, v in items.items() if k != "goaml"}
    try:
        return bool(build(rest, stored["settings"]) == stored["xml"])
    except (KeyError, TypeError, StopIteration):
        return False
