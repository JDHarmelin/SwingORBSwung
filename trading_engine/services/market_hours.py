"""US equity market-hours guard.

A tiny, dependency-free check so the scheduler can avoid scanning / alerting
on stale prices outside regular trading hours. Regular session only
(09:30-16:00 America/New_York, Mon-Fri); holidays and early closes are not
modelled — this is a coarse noise filter, not an exchange calendar.
"""

from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

_ET = ZoneInfo("America/New_York")
_OPEN = time(9, 30)
_CLOSE = time(16, 0)


def is_us_market_open(dt: datetime) -> bool:
    """True only Mon-Fri, 09:30-16:00 America/New_York.

    ``dt`` may be tz-aware (e.g. UTC) or naive; naive inputs are assumed UTC
    and converted to ET before the comparison.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    et = dt.astimezone(_ET)
    if et.weekday() >= 5:  # 5 = Saturday, 6 = Sunday
        return False
    return _OPEN <= et.time() < _CLOSE


__all__ = ["is_us_market_open"]
