"""Polygon normalization tests — no live network."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from trading_engine.core.config import load_app_config
from trading_engine.core.types import Timeframe
from trading_engine.data.mock_provider import MockMarketDataProvider, MockOptionsDataProvider
from trading_engine.data.polygon_provider import normalize_aggs
from trading_engine.data.universe import build_universe


def test_normalize_aggs() -> None:
    path = Path(__file__).parent / "fixtures" / "polygon_aggs_sample.json"
    payload = json.loads(path.read_text())
    series = normalize_aggs(payload, "AAPL", Timeframe.D1)
    assert len(series.candles) == 2
    assert series.candles[0].close == 101.0


@pytest.mark.asyncio
async def test_universe_mock_filters() -> None:
    config = load_app_config()
    # Use synthetic symbols from mock
    from trading_engine.testing.synthetic import sample_universe

    u = sample_universe()
    result = await build_universe(
        MockMarketDataProvider(),
        MockOptionsDataProvider(),
        config=config,
        watchlist_override=u["symbols"],  # type: ignore[arg-type]
    )
    assert "UPTRD" in result.symbols or len(result.symbols) > 0
