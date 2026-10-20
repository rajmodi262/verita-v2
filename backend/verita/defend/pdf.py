"""PDF rendering of a signed case file (a view — the signed JSON is the proof).

fpdf2 (pure Python) instead of WeasyPrint: WeasyPrint needs GTK/Pango system libraries, which
would make the backend image and Windows development heavier for a page that is only a view.
The built-in PDF fonts cover Latin-1 only, so other characters are transliterated (``€`` →
``EUR``); every figure is still printed exactly as signed.
"""

from __future__ import annotations

from typing import Any

from fpdf import FPDF

_REPLACE = {
    "€": "EUR",
    "£": "GBP",
    "₹": "INR",
    "₿": "BTC",
    "₽": "RUB",
    "₪": "ILS",
    "—": "-",
    "–": "-",
    "→": "->",
    "‘": "'",
    "’": "'",
    "“": '"',
    "”": '"',
    "…": "...",
    "≥": ">=",
    "≤": "<=",
    "×": "x",
}


def latin1(text: str) -> str:
    out = "".join(_REPLACE.get(ch, ch) for ch in text)
    return out.encode("latin-1", "replace").decode("latin-1")


def render_pdf(export: dict[str, Any]) -> bytes:
    items = export["items"]
    narrative = items.get("narrative", {})
    approval = items.get("approval", {})
    verification = items.get("verification", {})
    sig = export["signature"]

    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    width = pdf.w - pdf.l_margin - pdf.r_margin

    def line(text: str, size: float = 10, style: str = "", font: str = "Helvetica") -> None:
        pdf.set_font(font, style, size)
        pdf.multi_cell(width, size * 0.55, latin1(text), new_x="LMARGIN", new_y="NEXT")

    line(f"CASE FILE {export['case_id']}", 9, "B", "Courier")
    line(export.get("title", ""), 16, "B")
    line(
        f"Approved by {approval.get('approved_by', '?')} ({approval.get('approver_role', '?')}) "
        f"at {approval.get('approved_at', '?')}",
        9,
    )
    pdf.ln(3)
    line("Narrative", 12, "B")
    line(
        f"Version {narrative.get('version')} - written by {narrative.get('provider')} "
        f"({narrative.get('model')}); verifier {verification.get('verifier_version')}: "
        f"{'PASSED' if verification.get('passed') else 'FAILED'}",
        8,
        "I",
    )
    for s in narrative.get("sentences", []):
        cites = ", ".join(s.get("evidence_ids", []))
        line(f"[{s.get('section', '').upper()}] {s.get('text', '')}", 10)
        line(f"    cites {cites}", 7, "", "Courier")
    pdf.ln(3)
    line("Evidence", 12, "B")
    for name in sorted(k for k in items if k.startswith("EV-")):
        line(f"{name}  {export['leaves'][name]}", 7, "", "Courier")
    pdf.ln(3)
    line("Signature", 12, "B")
    line(f"Merkle root  {export['merkle_root']}", 8, "", "Courier")
    line(f"Key ID       {sig['key_id']}  ({sig['algorithm']})", 8, "", "Courier")
    line(f"Signature    {sig['value']}", 8, "", "Courier")
    line(f"Signed at    {sig['signed_at']}", 8, "", "Courier")
    pdf.ln(2)
    line(
        "This PDF is a rendering. The signed JSON export is the authoritative record: verify it "
        "offline with `verita-verify case-<id>.json --pubkey keys/verita-pub.pem`.",
        8,
        "I",
    )
    return bytes(pdf.output())
