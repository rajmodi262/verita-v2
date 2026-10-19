import json

import pytest
from typer.testing import CliRunner

from verita.cli import app
from verita.pipeline.config import PipelineError, config_hash, get_dataset, load_yaml
from verita.pipeline.datacard import render_card
from verita.pipeline.manifest import git_revision, run_manifest

runner = CliRunner()


def test_every_stage_writes_a_manifest_with_hashes(fx_run, fx_dataset):
    for stage in ("verify", "ingest", "link", "graph", "split"):
        m = json.loads((fx_dataset.manifests_dir / f"{stage}.json").read_text(encoding="utf-8"))
        assert m["stage"] == stage and m["dataset"] == "fixture"
        assert m["duration_s"] >= 0 and m["peak_memory_mb"] > 0
        assert m["git_revision"]
    ingest = json.loads((fx_dataset.manifests_dir / "ingest.json").read_text(encoding="utf-8"))
    assert all(len(h) == 64 for h in [*ingest["inputs"].values(), *ingest["outputs"].values()])
    assert ingest["config_hash"] == config_hash(ingest["config"])


def test_manifest_is_not_written_when_the_stage_fails(tmp_path):
    with pytest.raises(RuntimeError), run_manifest("boom", "x", tmp_path):
        raise RuntimeError("stage failed")
    assert not (tmp_path / "boom.json").exists()


def test_git_revision_outside_a_repo(tmp_path):
    assert git_revision(tmp_path) == "uncommitted"


def test_validation_report_has_every_section(fx_run, fx_dataset):
    report = json.loads(fx_dataset.validation_json.read_text(encoding="utf-8"))
    assert {"files", "contract", "patterns", "graph", "splits", "daily_volume"} <= set(report)
    assert report["daily_volume"]["days"][0]["day"] == "2022-09-01"


def test_card_numbers_come_from_the_report(fx_run, fx_root):
    card = render_card(["fixture"], root=fx_root)
    assert f"{fx_run['contract']['rows']:,}" in card
    assert "Data contract: **passed**" in card
    assert "UNATTRIBUTED (laundering outside any pattern)" in card
    assert "Do not edit by hand" in card


def test_card_requires_a_complete_report(tmp_path):
    with pytest.raises(PipelineError, match="No validation report"):
        render_card(["fixture"], root=tmp_path)
    ds = get_dataset("fixture", root=tmp_path)
    ds.validation_json.parent.mkdir(parents=True)
    ds.validation_json.write_text('{"files": []}', encoding="utf-8")
    with pytest.raises(PipelineError, match="incomplete"):
        render_card(["fixture"], root=tmp_path)


def test_unknown_dataset(tmp_path):
    with pytest.raises(PipelineError, match="Unknown dataset"):
        get_dataset("nope", root=tmp_path)


def test_load_yaml_errors(tmp_path):
    with pytest.raises(PipelineError, match="Missing config"):
        load_yaml(tmp_path / "missing.yaml")
    bad = tmp_path / "list.yaml"
    bad.write_text("- a\n- b\n", encoding="utf-8")
    with pytest.raises(PipelineError, match="mapping"):
        load_yaml(bad)


def test_cli_end_to_end(tmp_path):
    root = str(tmp_path)
    assert runner.invoke(app, ["data", "fixture", "--root", root]).exit_code == 0
    for stage in ("verify", "ingest", "link", "graph", "split"):
        result = runner.invoke(app, ["data", stage, "--dataset", "fixture", "--root", root])
        assert result.exit_code == 0, result.output
    card = runner.invoke(app, ["data", "card", "--dataset", "fixture", "--root", root])
    assert card.exit_code == 0 and (tmp_path / "DATA_CARD.md").exists()


def test_cli_all_and_errors(tmp_path):
    root = str(tmp_path)
    missing = runner.invoke(app, ["data", "all", "--dataset", "fixture", "--root", root])
    assert missing.exit_code == 1 and "missing" in missing.output
    runner.invoke(app, ["data", "fixture", "--root", root])
    ok = runner.invoke(app, ["data", "all", "--dataset", "fixture", "--root", root])
    assert ok.exit_code == 0 and '"coverage": 1.0' in ok.output
    bad_card = runner.invoke(app, ["data", "card", "--dataset", "li_small", "--root", root])
    assert bad_card.exit_code == 1
