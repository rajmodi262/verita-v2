import duckdb
import pytest

from tests.pipeline.conftest import tx_line, write_dataset
from verita.pipeline.config import DataContract
from verita.pipeline.ingest import ContractViolationError, ingest

CONTRACT = DataContract.load()


def q(path, sql):
    return duckdb.sql(sql.format(t=f"read_parquet('{path.as_posix()}')")).fetchall()


def test_fixture_passes_the_contract(fx_run):
    contract = fx_run["contract"]
    assert contract["passed"]
    assert contract["facts"]["exact_duplicate_rows"] == 1
    assert contract["facts"]["self_transfers"] >= 5


def test_parquet_schema_and_identifiers(fx_run, fx_dataset):
    path = fx_dataset.transactions_parquet
    cols = dict(
        duckdb.sql(f"DESCRIBE SELECT * FROM '{path.as_posix()}'").fetchall()[i][:2]
        for i in range(15)
    )
    assert cols["txn_id"] == "BIGINT" and cols["ts"] == "TIMESTAMP"
    assert cols["from_bank"] == "INTEGER" and cols["is_laundering"] == "BOOLEAN"
    n, ids, seqs = q(path, "SELECT count(*), count(DISTINCT txn_id), count(DISTINCT seq) FROM {t}")[
        0
    ]
    assert n == ids == seqs == fx_run["contract"]["rows"]


def test_seq_follows_time_then_file_order(fx_run, fx_dataset):
    rows = q(fx_dataset.transactions_parquet, "SELECT seq, ts, txn_id FROM {t} ORDER BY seq")
    keys = [(ts, txn) for _, ts, txn in rows]
    assert keys == sorted(keys)
    assert [s for s, _, _ in rows] == list(range(len(rows)))


def test_txn_id_is_file_line_order(tmp_path):
    rows = [
        tx_line(ts="2022/09/02 00:00", amount="1.00"),
        tx_line(ts="2022/09/01 00:00", amount="2.00"),
    ]
    ds = write_dataset(tmp_path, rows, [])
    ingest(ds, CONTRACT)
    out = q(ds.transactions_parquet, "SELECT txn_id, seq, amount_paid FROM {t} ORDER BY txn_id")
    assert out == [(0, 1, 1.0), (1, 0, 2.0)]


def test_bank_ids_are_numeric_in_node_ids(tmp_path):
    ds = write_dataset(tmp_path, [tx_line(from_bank="0110", to_bank="110")], [])
    ingest(ds, CONTRACT)
    assert q(ds.transactions_parquet, "SELECT from_id, to_id FROM {t}") == [
        ("110:800000001", "110:800000002")
    ]


@pytest.mark.parametrize(
    ("override", "violation"),
    [
        ({"ts": "2022-09-01 00:00"}, "bad_timestamp"),
        ({"from_bank": "X1"}, "bad_bank"),
        ({"to_account": " "}, "missing_account"),
        ({"amount": "-5.00"}, "bad_amount"),
        ({"amount": "abc"}, "bad_amount"),
        ({"currency": "Doubloon"}, "unknown_currency"),
        ({"payment_format": "Carrier Pigeon"}, "unknown_payment_format"),
        ({"label": "2"}, "bad_label"),
    ],
)
def test_each_contract_violation_is_detected(tmp_path, override, violation):
    ds = write_dataset(tmp_path, [tx_line(), tx_line(**override)], [])
    with pytest.raises(ContractViolationError) as err:
        ingest(ds, CONTRACT)
    assert err.value.report.violations[violation] == 1
    assert not ds.transactions_parquet.exists()


def test_empty_file_is_a_violation(tmp_path):
    ds = write_dataset(tmp_path, [], [])
    with pytest.raises(ContractViolationError) as err:
        ingest(ds, CONTRACT)
    assert err.value.report.violations["empty_file"] == 1


def test_failed_ingest_still_records_the_report(tmp_path):
    from verita.pipeline import run

    ds = write_dataset(tmp_path, [tx_line(label="9")], [])
    with pytest.raises(ContractViolationError):
        run.stage_ingest(ds)
    report = ds.validation_json.read_text(encoding="utf-8")
    assert '"bad_label": 1' in report
    assert not (ds.manifests_dir / "ingest.json").exists()  # no manifest for a failed stage
