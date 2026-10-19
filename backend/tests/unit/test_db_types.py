from datetime import UTC, datetime, timedelta, timezone

import pytest

from verita.db.base import UTCDateTime

T = UTCDateTime()


def test_naive_datetime_is_rejected():
    with pytest.raises(ValueError, match="naive"):
        T.process_bind_param(datetime(2024, 1, 1), None)  # type: ignore[arg-type]


def test_aware_datetime_is_normalized_to_utc():
    ist = timezone(timedelta(hours=5, minutes=30))
    out = T.process_bind_param(datetime(2024, 1, 1, 5, 30, tzinfo=ist), None)  # type: ignore[arg-type]
    assert out == datetime(2024, 1, 1, tzinfo=UTC)
    assert out is not None and out.tzinfo == UTC


def test_naive_result_is_assumed_utc():
    out = T.process_result_value(datetime(2024, 1, 1), None)  # type: ignore[arg-type]
    assert out is not None and out.tzinfo == UTC


def test_none_passes_through():
    assert T.process_bind_param(None, None) is None  # type: ignore[arg-type]
    assert T.process_result_value(None, None) is None  # type: ignore[arg-type]


def test_aware_result_is_converted_to_utc():
    ist = timezone(timedelta(hours=5, minutes=30))
    out = T.process_result_value(datetime(2024, 1, 1, 5, 30, tzinfo=ist), None)  # type: ignore[arg-type]
    assert out == datetime(2024, 1, 1, tzinfo=UTC)
