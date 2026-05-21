"""Universe resolution from config."""

from __future__ import annotations

import pytest

from trading_engine.core.config import load_app_config
from trading_engine.data.mock_provider import MockMarketDataProvider, MockOptionsDataProvider
from trading_engine.data.universe import resolve_scan_symbols, symbols_from_config


def test_symbols_from_config() -> None:
    syms = symbols_from_config()
    assert "NVDA" in syms
    assert "AAPL" in syms
    assert len(syms) >= 20


@pytest.mark.asyncio
async def test_resolve_yaml_without_filter() -> None:
    config = load_app_config()
    syms = await resolve_scan_symbols(
        MockMarketDataProvider(),
        MockOptionsDataProvider(),
        config=config,
        filter_liquidity=False,
    )
    assert syms == list(config.universe.symbols)


@pytest.mark.asyncio
async def test_resolve_override() -> None:
    syms = await resolve_scan_symbols(
        MockMarketDataProvider(),
        MockOptionsDataProvider(),
        symbols_override=["UPTRD", "FLAG"],
        filter_liquidity=False,
    )
    assert syms == ["UPTRD", "FLAG"]
