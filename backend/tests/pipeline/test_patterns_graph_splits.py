import json
from itertools import pairwise

import duckdb
import pytest
from hypothesis import given
from hypothesis import strategies as st

from tests.pipeline.conftest import tx_line, write_dataset
from verita.pipeline import run
from verita.pipeline.config import DataContract, PipelineError
from verita.pipeline.ingest import ingest
from verita.pipeline.patterns import PatternFormatError, link_patterns, parse_patterns
from verita.pipeline.splits import (
    DEFAULT_FRACTIONS,
    SPLIT_ORDER,
    Splits,
    compute_splits,
    load_splits,
    seq_ranges,
)

CONTRACT = DataContract.load()
L1 = tx_line(
    ts="2022/09/01 01:00",
    from_account="8000000A1",
    to_account="8000000B1",
    to_bank="010",
    amount="500.00",
    label="1",
)
L2 = tx_line(
    ts="2022/09/01 02:00",
    from_account="8000000B1",
    to_account="8000000C1",
    to_bank="010",
    amount="490.00",
    label="1",
)
UNATTR = tx_line(
    ts="2022/09/02 03:00",
    from_account="8000000D1",
    to_account="8000000E1",
    to_bank="010",
    amount="77.00",
    label="1",
)
LEGIT = tx_line(ts="2022/09/01 04:00", amount="10.00")


# ── parsing ──────────────────────────────────────────────────────────────────


def test_fixture_patterns_parse_and_link_fully(fx_run):
    p = fx_run["patterns"]
    assert p["attempts"] == 96 and p["unmatched_rows"] == 0 and p["label_mismatch"] == 0
    assert p["coverage"] == 1.0  # every fixture laundering row belongs to a pattern
    assert len(p["by_typology"]) == 8


def test_description_is_optional(tmp_path):
    ds = write_dataset(tmp_path, [L1, L2], [("CYCLE", "Max 2 hops", [L1]), ("STACK", "", [L2])])
    attempts = parse_patterns(ds.patterns_txt, CONTRACT)
    assert [(a.typology, a.description) for a in attempts] == [
        ("CYCLE", "Max 2 hops"),
        ("STACK", ""),
    ]


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ("BEGIN LAUNDERING ATTEMPT - CYCLE\nBEGIN LAUNDERING ATTEMPT - CYCLE\n", "inside an open"),
        ("END LAUNDERING ATTEMPT - CYCLE\n", "END without BEGIN"),
        ("BEGIN LAUNDERING ATTEMPT - CYCLE\n{row}\nEND LAUNDERING ATTEMPT - STACK\n", "closes"),
        ("{row}\n", "outside a block"),
        (
            "BEGIN LAUNDERING ATTEMPT - WEIRD\n{row}\nEND LAUNDERING ATTEMPT - WEIRD\n",
            "unknown typology",
        ),
        ("BEGIN LAUNDERING ATTEMPT - CYCLE\na,b\nEND LAUNDERING ATTEMPT - CYCLE\n", "2 fields"),
        (
            "BEGIN LAUNDERING ATTEMPT - CYCLE\n{legit}\nEND LAUNDERING ATTEMPT - CYCLE\n",
            "not labelled",
        ),
        (
            "BEGIN LAUNDERING ATTEMPT - CYCLE\n{bad_ts}\nEND LAUNDERING ATTEMPT - CYCLE\n",
            "does not match",
        ),
        ("BEGIN LAUNDERING ATTEMPT - CYCLE\nEND LAUNDERING ATTEMPT - CYCLE\n", "no transactions"),
        ("BEGIN LAUNDERING ATTEMPT - CYCLE\n{row}\n", "never closed"),
    ],
)
def test_malformed_patterns_are_rejected(tmp_path, text, problem):
    path = tmp_path / "p.txt"
    bad_ts = ",".join(tx_line(ts="01-09-2022", label="1"))
    path.write_text(
        text.format(row=",".join(L1), legit=",".join(LEGIT), bad_ts=bad_ts), encoding="utf-8"
    )
    with pytest.raises(PatternFormatError) as err:
        parse_patterns(path, CONTRACT)
    assert any(problem in p for p in err.value.problems)


def test_many_problems_are_summarized(tmp_path):
    path = tmp_path / "p.txt"
    path.write_text("\n".join(",".join(L1) for _ in range(25)) + "\n", encoding="utf-8")
    with pytest.raises(PatternFormatError, match="and 5 more"):
        parse_patterns(path, CONTRACT)


# ── linking ──────────────────────────────────────────────────────────────────


def _ingested(tmp_path, rows, blocks):
    ds = write_dataset(tmp_path, rows, blocks)
    ingest(ds, CONTRACT)
    return ds


def test_linking_counts_unattributed_laundering(tmp_path):
    ds = _ingested(tmp_path, [L1, L2, UNATTR, LEGIT], [("CYCLE", "x", [L1, L2])])
    report = link_patterns(ds, parse_patterns(ds.patterns_txt, CONTRACT))
    assert report.linked_rows == 2 and report.laundering_total == 3
    assert report.to_dict()["laundering_unattributed"] == 1
    assert report.coverage == pytest.approx(2 / 3)


def test_bank_leading_zeros_do_not_break_linking(tmp_path):
    in_file = tx_line(from_bank="0110", label="1")
    in_patterns = tx_line(from_bank="110", label="1")
    ds = _ingested(tmp_path, [in_file], [("FAN-OUT", "x", [in_patterns])])
    assert link_patterns(ds, parse_patterns(ds.patterns_txt, CONTRACT)).linked_rows == 1


def test_unmatched_pattern_row_fails(tmp_path):
    ghost = tx_line(amount="999.99", label="1")
    ds = _ingested(tmp_path, [L1], [("CYCLE", "x", [ghost])])
    with pytest.raises(PipelineError, match="1 unmatched"):
        link_patterns(ds, parse_patterns(ds.patterns_txt, CONTRACT))


def test_pattern_matching_a_legitimate_transaction_fails(tmp_path):
    as_laundering = (*LEGIT[:10], "1")
    ds = _ingested(tmp_path, [LEGIT], [("CYCLE", "x", [as_laundering])])
    with pytest.raises(PipelineError, match="1 matched to legitimate"):
        link_patterns(ds, parse_patterns(ds.patterns_txt, CONTRACT))


def test_shared_and_duplicate_matches_are_counted(tmp_path):
    ds = _ingested(tmp_path, [L1, L1], [("CYCLE", "x", [L1]), ("STACK", "y", [L1])])
    report = link_patterns(ds, parse_patterns(ds.patterns_txt, CONTRACT))
    assert report.multi_match_rows == 2  # each pattern row hits both duplicate transactions
    assert report.transactions_in_multiple_attempts == 2


# ── graph ────────────────────────────────────────────────────────────────────


def test_account_day_labels_and_typologies(tmp_path):
    ds = _ingested(tmp_path, [L1, L2, UNATTR, LEGIT], [("CYCLE", "x", [L1, L2])])
    run.stage_link(ds)
    report = run.stage_graph(ds)
    assert report["edges"] == 4
    days = {
        (a, str(d)): (label, list(t))
        for a, d, label, t in duckdb.sql(
            f"SELECT account_id, day, label, typologies FROM '{ds.account_day_parquet.as_posix()}'"
        ).fetchall()
    }
    assert days[("10:8000000B1", "2022-09-01")] == (True, ["CYCLE"])  # received then sent
    assert days[("10:8000000D1", "2022-09-02")] == (True, ["UNATTRIBUTED"])
    assert days[("10:800000001", "2022-09-01")] == (False, [])
    accounts = dict(
        duckdb.sql(
            f"SELECT account_id, laundering_involved FROM '{ds.accounts_parquet.as_posix()}'"
        ).fetchall()
    )
    assert accounts["10:8000000A1"] and not accounts["10:800000001"]
    assert report["accounts_involved"] == 5


def test_fixture_graph_is_consistent(fx_run):
    g = fx_run["graph"]
    assert g["edges"] == fx_run["contract"]["rows"]
    assert 0 < g["positive_account_days"] < g["account_days"]
    assert g["self_loops"] == fx_run["contract"]["facts"]["self_transfers"]


# ── splits ───────────────────────────────────────────────────────────────────


@given(st.integers(min_value=4, max_value=2_000_000))
def test_seq_ranges_partition_everything_in_order(total):
    ranges = seq_ranges(total, DEFAULT_FRACTIONS)
    bounds = [ranges[name] for name in SPLIT_ORDER]
    assert bounds[0][0] == 0 and bounds[-1][1] == total - 1
    for (_, hi), (lo, _) in pairwise(bounds):
        assert lo == hi + 1
    assert all(lo <= hi for lo, hi in bounds)
    if total >= 1_000:
        train = ranges["train"][1] - ranges["train"][0] + 1
        assert abs(train / total - 0.6) < 0.001


@pytest.mark.parametrize(
    "fractions",
    [
        {"train": 0.5, "hpo": 0.1, "calib": 0.1, "test": 0.2},
        {"train": 0.6, "hpo": 0.2, "calib": 0.2},
        {"train": 1.1, "hpo": -0.1, "calib": 0.0, "test": 0.0},
    ],
)
def test_bad_fractions_are_rejected(fractions):
    with pytest.raises(PipelineError):
        seq_ranges(100, fractions)


def test_too_few_rows_to_split():
    with pytest.raises(PipelineError, match="at least"):
        seq_ranges(3, DEFAULT_FRACTIONS)


def test_fixture_splits_are_temporal_and_complete(fx_run, fx_dataset):
    summary = fx_run["splits"]["summary"]
    assert sum(s["rows"] for s in summary.values()) == fx_run["contract"]["rows"]
    assert sum(s["laundering"] for s in summary.values()) == fx_run["contract"]["laundering"]
    order = [summary[name] for name in SPLIT_ORDER]
    for earlier, later in pairwise(order):
        assert earlier["to"] <= later["from"]
    splits = load_splits(fx_dataset)
    path = fx_dataset.transactions_parquet.as_posix()
    by_sql = dict(
        duckdb.sql(f"SELECT {splits.sql_case()} AS s, count(*) FROM '{path}' GROUP BY 1").fetchall()
    )
    assert by_sql == {name: summary[name]["rows"] for name in SPLIT_ORDER}
    assert splits.split_of(0) == "train" and splits.split_of(splits.total - 1) == "test"
    with pytest.raises(ValueError, match="outside"):
        splits.split_of(splits.total)


def test_splits_roundtrip(fx_run, fx_dataset):
    data = json.loads(fx_dataset.splits_json.read_text(encoding="utf-8"))
    assert Splits.from_dict(data).to_dict() == data


def test_load_splits_requires_the_split_stage(tmp_path):
    from verita.pipeline.config import get_dataset

    with pytest.raises(PipelineError, match="No splits"):
        load_splits(get_dataset("fixture", root=tmp_path))


def test_custom_fractions(tmp_path):
    ds = _ingested(tmp_path, [tx_line(ts=f"2022/09/01 0{i}:00") for i in range(8)], [])
    splits = compute_splits(ds, {"train": 0.5, "hpo": 0.25, "calib": 0.125, "test": 0.125})
    assert {k: v["rows"] for k, v in splits.summary.items()} == {
        "train": 4,
        "hpo": 2,
        "calib": 1,
        "test": 1,
    }
