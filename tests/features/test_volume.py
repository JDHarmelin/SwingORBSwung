"""VolumeExpansionScore tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd

from trading_engine.core.types import OHLCVSeries, Timeframe
from trading_engine.features.volume import volume_expansion_score


def _series_with_volumes(volumes: list[float]) -> OHLCVSeries:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    rows = []
    for i, v in enumerate(volumes):
        rows.append(
            {
                "timestamp": base + timedelta(days=i),
                "open": 100.0,
                "high": 100.5,
                "low": 99.5,
                "close": 100.0,
                "volume": v,
            }
        )
    df = pd.DataFrame(rows).set_index("timestamp")
    return OHLCVSeries.from_dataframe(df, symbol="X", timeframe=Timeframe.D1)


def test_expansion_score_positive_on_volume_spike() -> None:
    vols = [1000.0] * 30
    vols[-1] = 4000.0
    series = _series_with_volumes(vols)
    v = volume_expansion_score(series, avg_length=20, recent=3)
    assert v.score > 0.4
    assert v.relative_volume > 3.0
    assert any("expansion" in r.lower() for r in v.reason_codes)


def test_expansion_score_negative_on_contraction() -> None:
    vols = [1000.0] * 30
    vols[-1] = 200.0
    series = _series_with_volumes(vols)
    v = volume_expansion_score(series, avg_length=20, recent=3)
    assert v.score < 0
    assert any("contraction" in r.lower() for r in v.reason_codes)


def test_expansion_score_neutral_on_steady_volume() -> None:
    series = _series_with_volumes([1000.0] * 30)
    v = volume_expansion_score(series, avg_length=20, recent=3)
    assert abs(v.score) < 0.05
