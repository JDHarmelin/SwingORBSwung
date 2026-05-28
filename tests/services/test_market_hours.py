"""is_us_market_open — regular-session boundary checks."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from trading_engine.services.market_hours import is_us_market_open

_ET = ZoneInfo("America/New_York")


def test_weekday_midday_open() -> None:
    # Tuesday 2026-05-19, 10:00 ET → open.
    assert is_us_market_open(datetime(2026, 5, 19, 10, 0, tzinfo=_ET)) is True


def test_saturday_closed() -> None:
    # Saturday 2026-05-23, 10:00 ET → closed.
    assert is_us_market_open(datetime(2026, 5, 23, 10, 0, tzinfo=_ET)) is False


def test_weekday_evening_closed() -> None:
    # Tuesday 2026-05-19, 20:00 ET → closed.
    assert is_us_market_open(datetime(2026, 5, 19, 20, 0, tzinfo=_ET)) is False


def test_utc_input_converted() -> None:
    # 14:00 UTC on a weekday is 10:00 ET → open.
    assert is_us_market_open(datetime(2026, 5, 19, 14, 0, tzinfo=ZoneInfo("UTC"))) is True
