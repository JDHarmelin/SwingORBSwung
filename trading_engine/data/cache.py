"""Thin on-disk OHLCV cache."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

from trading_engine.core.types import OHLCVSeries


def _bucket_dt(dt: datetime, timeframe: str) -> datetime:
    """Round datetime to a stable boundary so repeated scans hit cache."""
    if timeframe == "1d":
        return dt.replace(hour=0, minute=0, second=0, microsecond=0)
    try:
        minutes = int(timeframe[:-1])
    except (ValueError, IndexError):
        return dt
    bucket_minute = (dt.minute // minutes) * minutes
    return dt.replace(minute=bucket_minute, second=0, microsecond=0)


class OhlcvDiskCache:
    def __init__(self, cache_dir: Path | None = None) -> None:
        self._dir = cache_dir or Path(".cache/ohlcv")
        self._dir.mkdir(parents=True, exist_ok=True)

    def _key(self, symbol: str, timeframe: str, start: datetime, end: datetime) -> Path:
        b_start = _bucket_dt(start, timeframe)
        b_end = _bucket_dt(end, timeframe)
        raw = f"{symbol}:{timeframe}:{b_start.isoformat()}:{b_end.isoformat()}"
        h = hashlib.sha256(raw.encode()).hexdigest()[:16]
        return self._dir / f"{symbol}_{timeframe}_{h}.json"

    def get(
        self, symbol: str, timeframe: str, start: datetime, end: datetime
    ) -> OHLCVSeries | None:
        path = self._key(symbol, timeframe, start, end)
        if not path.exists():
            return None
        data = json.loads(path.read_text())
        return OHLCVSeries.model_validate(data)

    def put(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
        series: OHLCVSeries,
    ) -> None:
        path = self._key(symbol, timeframe, start, end)
        path.write_text(series.model_dump_json())
