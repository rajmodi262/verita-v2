"""Honesty scan (PIVOT §15.4): no hand-typed metric in public docs or UI code.

A line fails when it pairs a metric word (recall, precision, F1, AUC, accuracy, ECE, detection
or false-alarm rate) with a numeric literal that looks like a result (``0.87``, ``87%``,
``87.5 %``). A confidence level or a target is not a result ("95% CI", "a 95% guarantee").
Generated regions are skipped: the README block between the metrics markers, and files that
carry the generated banner. Test files are skipped (fixtures are made-up numbers by design).

``TRACKER.md`` (the engineering log, which records measurements as they were taken) and
``PIVOT.md`` (the plan, whose numbers are targets) are not public claims and are exempt —
listed here rather than silently ignored.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from verita.pipeline.config import REPO_ROOT
from verita.reports.docs import BANNER, END, START

METRIC_WORDS = re.compile(
    r"\b(recall|precision|f1|pr-auc|auc|accuracy|ece|calibration error|false[- ]alarm"
    r"|detection rate)\b",
    re.IGNORECASE,
)
RESULT_NUMBER = re.compile(r"(?<![\w.#-])(?:0?\.\d+|\d{1,3}(?:\.\d+)?\s?%)(?![\w.])")
NOT_A_RESULT = re.compile(
    r"\d{1,3}(?:\.\d+)?\s?%\s?(?:recall\s)?(?:CI|confidence|interval|band|guarantee|target|block)",
    re.IGNORECASE,
)
EXEMPT = {"TRACKER.md", "PIVOT.md", "CHANGELOG.md"}
SKIP_DIRS = {"node_modules", ".venv", "dist", "coverage", "test", "fixtures", "__pycache__", ".git"}


@dataclass(frozen=True)
class Finding:
    path: Path
    line: int
    text: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.text.strip()[:140]}"


def _candidates(root: Path) -> list[Path]:
    files = [p for p in root.glob("*.md") if p.name not in EXEMPT]
    files += list((root / "docs").rglob("*.md")) if (root / "docs").exists() else []
    src = root / "frontend" / "src"
    if src.exists():
        files += [
            p
            for p in src.rglob("*")
            if p.suffix in {".ts", ".tsx"}
            and ".test." not in p.name
            and not SKIP_DIRS & set(p.relative_to(src).parts)
            and p.name != "schema.d.ts"
        ]
    return sorted(files)


def scan_text(text: str) -> list[tuple[int, str]]:
    if BANNER in text:
        return []
    hits = []
    inside = False
    for i, line in enumerate(text.splitlines(), start=1):
        if START in line:
            inside = True
        if END in line:
            inside = False
            continue
        if inside:
            continue
        if METRIC_WORDS.search(line) and RESULT_NUMBER.search(NOT_A_RESULT.sub("", line)):
            hits.append((i, line))
    return hits


def scan(root: Path = REPO_ROOT) -> list[Finding]:
    out = []
    for path in _candidates(root):
        for line, text in scan_text(path.read_text(encoding="utf-8")):
            out.append(Finding(path.relative_to(root), line, text))
    return out
