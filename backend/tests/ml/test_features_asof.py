"""The leakage guard (PIVOT §6.2, M2.08): no feature of a payment may depend on anything that
happens at or after its own minute. We build features, then mutate or delete every event from
some cut-off onwards, rebuild, and require every payment before the cut-off to be unchanged."""

from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from tests.pipeline.conftest import write_dataset
from verita.ml.features import ALL_FEATURES, build_features
from verita.pipeline.config import DataContract
from verita.pipeline.ingest import ingest

CONTRACT = DataContract.load()
ACCOUNTS = [f"80000{i:04X}" for i in range(6)]
START = datetime(2022, 9, 1)


def _row(minute: int, src: int, dst: int, amount: int, fmt: str = "ACH") -> tuple[str, ...]:
    ts = (START + timedelta(minutes=minute)).strftime("%Y/%m/%d %H:%M")
    return (
        ts,
        "010",
        ACCOUNTS[src],
        "010",
        ACCOUNTS[dst],
        f"{amount}.00",
        "US Dollar",
        f"{amount}.00",
        "US Dollar",
        fmt,
        "0",
    )


events = st.lists(
    st.tuples(
        st.integers(0, 3 * 24 * 60),  # minute within 3 days
        st.integers(0, len(ACCOUNTS) - 1),
        st.integers(0, len(ACCOUNTS) - 1),
        st.integers(1, 9_999),
    ),
    min_size=5,
    max_size=40,
)


def _features(tmp_path, rows) -> pd.DataFrame:
    ds = write_dataset(tmp_path, rows, [])
    ingest(ds, CONTRACT)
    build_features(ds)
    frame = pd.read_parquet(ds.features_parquet)
    return frame.set_index("ts", append=False)


@settings(
    max_examples=25, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(events=events, cut=st.integers(60, 3 * 24 * 60), data=st.data())
def test_future_events_never_change_past_features(tmp_path_factory, events, cut, data):
    base = [_row(m, s, d, a) for m, s, d, a in sorted(events)]
    future_rows = [r for r, (m, *_rest) in zip(base, sorted(events), strict=True) if m >= cut]
    past_rows = [r for r, (m, *_rest) in zip(base, sorted(events), strict=True) if m < cut]
    if not past_rows:
        return
    # Alternative future: drop some future events, change others, and add new ones.
    keep = data.draw(st.lists(st.booleans(), min_size=len(future_rows), max_size=len(future_rows)))
    changed = [
        _row(cut + i, (i + 1) % 6, (i + 3) % 6, 5_000 + i, "Wire")
        for i in range(data.draw(st.integers(0, 5)))
    ]
    alt = past_rows + [r for r, k in zip(future_rows, keep, strict=True) if k] + changed

    a = _features(tmp_path_factory.mktemp("a"), base)
    b = _features(tmp_path_factory.mktemp("b"), sorted(alt))
    cols = [c for c in ALL_FEATURES]
    past_a = a[a.index < START + timedelta(minutes=cut)].sort_values(["seq"])[cols]
    past_b = b[b.index < START + timedelta(minutes=cut)].sort_values(["seq"])[cols]
    pd.testing.assert_frame_equal(
        past_a.reset_index(drop=True), past_b.reset_index(drop=True), check_dtype=False
    )


def test_same_minute_activity_is_invisible(tmp_path):
    rows = [_row(10, 0, 1, 100), _row(10, 0, 2, 200), _row(11, 0, 3, 300)]
    frame = _features(tmp_path, rows).sort_values("seq")
    assert frame["s_out_n_1h"].tolist() == [0, 0, 2]
    assert frame["s_payees_1h"].tolist() == [0, 0, 2]


def test_cycle_is_found_only_when_it_closes(tmp_path):
    # 0 → 1 → 2 → 0 with increasing times; only the closing payment sees the cycle.
    rows = [_row(10, 0, 1, 900), _row(20, 1, 2, 880), _row(30, 2, 0, 860)]
    frame = _features(tmp_path, rows).sort_values("seq")
    assert frame["cycle_found"].tolist() == [0, 0, 1]
    assert frame["cycle_edges"].tolist() == [0, 0, 3]


def test_cycle_requires_time_order(tmp_path):
    # Same accounts, but the middle hop happens after the would-be closing payment.
    rows = [_row(10, 0, 1, 900), _row(40, 1, 2, 880), _row(30, 2, 0, 860)]
    frame = _features(tmp_path, rows).sort_values("seq")
    assert frame["cycle_found"].sum() == 0


def test_cycle_outside_window_is_ignored(tmp_path):
    rows = [_row(0, 0, 1, 900), _row(8 * 24 * 60, 1, 0, 880)]
    frame = _features(tmp_path, rows).sort_values("seq")
    assert frame["cycle_found"].sum() == 0
