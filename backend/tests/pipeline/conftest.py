"""Pipeline fixtures: a generated IBM-format dataset in a temp repo root, and helpers to write
hand-made CSV / patterns files for precise edge-case tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from verita.pipeline import run
from verita.pipeline.config import Dataset, get_dataset
from verita.pipeline.fixture import HEADER, generate_fixture


@pytest.fixture(scope="session")
def fx_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("repo")
    generate_fixture(get_dataset("fixture", root=root).raw_dir)
    return root


@pytest.fixture(scope="session")
def fx_dataset(fx_root: Path) -> Dataset:
    return get_dataset("fixture", root=fx_root)


@pytest.fixture(scope="session")
def fx_run(fx_dataset: Dataset) -> dict[str, Any]:
    """The whole pipeline, run once per test session on the generated fixture."""
    return run.stage_all(fx_dataset)


Line = tuple[str, str, str, str, str, str, str, str, str, str, str]


def tx_line(
    ts: str = "2022/09/01 00:00",
    from_bank: str = "010",
    from_account: str = "800000001",
    to_bank: str = "020",
    to_account: str = "800000002",
    amount: str = "100.00",
    currency: str = "US Dollar",
    payment_format: str = "ACH",
    label: str = "0",
) -> Line:
    return (
        ts,
        from_bank,
        from_account,
        to_bank,
        to_account,
        amount,
        currency,
        amount,
        currency,
        payment_format,
        label,
    )


def write_dataset(
    root: Path, rows: list[Line], blocks: list[tuple[str, str, list[Line]]], name: str = "fixture"
) -> Dataset:
    """Write a tiny IBM-format pair into the given root under the fixture dataset's paths."""
    ds = get_dataset(name, root=root)
    ds.raw_dir.mkdir(parents=True, exist_ok=True)
    lines = [",".join(HEADER)] + [",".join(r) for r in rows]
    ds.transactions_csv.write_text("\n".join(lines) + "\n", encoding="utf-8")
    out = []
    for typology, description, block_rows in blocks:
        header = f"BEGIN LAUNDERING ATTEMPT - {typology}"
        out.append(f"{header}:  {description}" if description else header)
        out.extend(",".join(r) for r in block_rows)
        out.append(f"END LAUNDERING ATTEMPT - {typology}")
        out.append("")
    ds.patterns_txt.write_text("\n".join(out) + "\n", encoding="utf-8")
    return ds
