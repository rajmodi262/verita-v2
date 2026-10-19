import csv

import pytest

from verita.pipeline.config import PipelineError, get_dataset
from verita.pipeline.fixture import TYPOLOGIES, generate_fixture
from verita.pipeline.manifest import sha256_file
from verita.pipeline.verify import verify_raw


def test_fixture_is_deterministic(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    generate_fixture(a, seed=3, n_background=2_000)
    generate_fixture(b, seed=3, n_background=2_000)
    for name in ("FIXTURE_Trans.csv", "FIXTURE_Patterns.txt"):
        assert sha256_file(a / name) == sha256_file(b / name)


def test_different_seed_differs(tmp_path):
    generate_fixture(tmp_path / "a", seed=1, n_background=2_000)
    generate_fixture(tmp_path / "b", seed=2, n_background=2_000)
    assert sha256_file(tmp_path / "a" / "FIXTURE_Trans.csv") != sha256_file(
        tmp_path / "b" / "FIXTURE_Trans.csv"
    )


def test_fixture_summary_matches_files(tmp_path):
    summary = generate_fixture(tmp_path, seed=5, n_background=3_000, patterns_per_typology=2)
    with (tmp_path / "FIXTURE_Trans.csv").open(encoding="utf-8") as handle:
        rows = list(csv.reader(handle))[1:]
    assert len(rows) == summary.transactions
    assert sum(r[10] == "1" for r in rows) == summary.laundering_transactions
    assert set(summary.by_typology) == set(TYPOLOGIES)
    assert summary.patterns == 2 * len(TYPOLOGIES)
    text = (tmp_path / "FIXTURE_Patterns.txt").read_text(encoding="utf-8")
    assert text.count("BEGIN LAUNDERING ATTEMPT") == summary.patterns
    assert text.count("END LAUNDERING ATTEMPT") == summary.patterns


def test_pattern_builder_rejects_unknown_typology(tmp_path):
    from verita.pipeline.fixture import _Generator

    gen = _Generator(
        seed=1, n_accounts=50, days=2, start=__import__("datetime").datetime(2022, 9, 1)
    )
    with pytest.raises(ValueError, match="unknown typology"):
        gen.pattern("NOT-A-TYPOLOGY")


def test_verify_accepts_present_files_without_recorded_hash(fx_dataset):
    checks = verify_raw(fx_dataset)
    assert all(c.ok and c.expected_sha256 is None for c in checks)


def test_verify_reports_missing_files(tmp_path):
    with pytest.raises(PipelineError, match="missing"):
        verify_raw(get_dataset("fixture", root=tmp_path))


def test_verify_reports_hash_mismatch(fx_dataset, tmp_path):
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text(
        "files:\n  - name: FIXTURE_Trans.csv\n    sha256: " + "0" * 64 + "\n", encoding="utf-8"
    )
    with pytest.raises(PipelineError, match="hash mismatch"):
        verify_raw(fx_dataset, manifest)


def test_verify_accepts_matching_hash(fx_dataset, tmp_path):
    digest = sha256_file(fx_dataset.transactions_csv)
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text(
        f"files:\n  - name: FIXTURE_Trans.csv\n    sha256: {digest}\n", encoding="utf-8"
    )
    checks = verify_raw(fx_dataset, manifest)
    assert checks[0].to_dict()["ok"] is True


def test_real_manifest_has_every_hash_recorded():
    from verita.pipeline.verify import expected_hashes

    hashes = expected_hashes()
    assert set(hashes) == {
        "HI-Small_Trans.csv",
        "HI-Small_Patterns.txt",
        "LI-Small_Trans.csv",
        "LI-Small_Patterns.txt",
    }
    assert all(h is not None and len(h) == 64 for h in hashes.values())
