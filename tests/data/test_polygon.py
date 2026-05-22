"""Polygon adapters via httpx.MockTransport — no network involved."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import httpx
import pytest

from trading_engine.core.interfaces import (
    EventsProvider,
    MarketDataProvider,
    OptionsDataProvider,
)
from trading_engine.core.types import OptionType, Timeframe
from trading_engine.data.polygon import (
    PolygonEventsProvider,
    PolygonMarketDataProvider,
    PolygonOptionsDataProvider,
)


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# ---------------------------------------------------------------------------
# Market data
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_polygon_market_data_get_ohlcv_maps_aggregates() -> None:
    captured: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["path"] = req.url.path
        captured["params"] = dict(req.url.params)
        captured["auth"] = req.headers.get("Authorization")
        # Two daily bars.
        body = {
            "status": "OK",
            "results": [
                {"t": 1_716_000_000_000, "o": 100.0, "h": 102.0, "l": 99.0, "c": 101.0, "v": 1.5e6},
                {"t": 1_716_086_400_000, "o": 101.0, "h": 103.0, "l": 100.5, "c": 102.5, "v": 1.7e6},
            ],
        }
        return httpx.Response(200, json=body)

    async with _client(handler) as client:
        provider = PolygonMarketDataProvider("test-key", client=client)
        series = await provider.get_ohlcv(
            "NVDA",
            Timeframe.D1,
            datetime(2026, 5, 18, tzinfo=UTC),
            datetime(2026, 5, 19, tzinfo=UTC),
        )

    assert isinstance(provider, MarketDataProvider)
    assert len(series.candles) == 2
    assert series.candles[0].close == 101.0
    assert series.candles[1].volume == 1.7e6
    assert captured["path"].startswith("/v2/aggs/ticker/NVDA/range/1/day/")
    assert captured["params"]["adjusted"] == "true"
    assert captured["params"]["sort"] == "asc"
    assert captured["auth"] == "Bearer test-key"


@pytest.mark.asyncio
async def test_polygon_market_data_retries_on_429() -> None:
    state = {"count": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        state["count"] += 1
        if state["count"] == 1:
            return httpx.Response(429, json={"error": "rate limit"})
        return httpx.Response(
            200,
            json={"results": [{"t": 1_716_000_000_000, "o": 1.0, "h": 1.0, "l": 1.0, "c": 1.0, "v": 1.0}]},
        )

    async with _client(handler) as client:
        provider = PolygonMarketDataProvider("k", client=client)
        # Override backoff so retries are fast.
        provider._http._backoff = 0.0  # type: ignore[attr-defined]
        series = await provider.get_ohlcv(
            "AAPL", Timeframe.D1, datetime(2026, 5, 18, tzinfo=UTC), datetime(2026, 5, 19, tzinfo=UTC)
        )
    assert state["count"] == 2
    assert len(series.candles) == 1


# ---------------------------------------------------------------------------
# Options
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_polygon_options_chain_assembles_contracts() -> None:
    page1 = {
        "results": [
            {
                "details": {
                    "ticker": "O:AAPL260619C00200000",
                    "expiration_date": "2026-06-19",
                    "strike_price": 200.0,
                    "contract_type": "call",
                },
                "last_quote": {"bid": 5.0, "ask": 5.20},
                "greeks": {"delta": 0.38, "gamma": 0.04, "theta": -0.05, "vega": 0.10},
                "day": {"volume": 320},
                "implied_volatility": 0.32,
                "open_interest": 2500,
            }
        ],
        "next_url": "https://api.polygon.io/v3/snapshot/options/AAPL?cursor=abc",
    }
    page2 = {
        "results": [
            {
                "details": {
                    "ticker": "O:AAPL260619P00200000",
                    "expiration_date": "2026-06-19",
                    "strike_price": 200.0,
                    "contract_type": "put",
                },
                "last_quote": {"bid": 4.0, "ask": 4.10},
                "greeks": {"delta": -0.40},
                "day": {"volume": 100},
                "open_interest": 1500,
            }
        ],
    }

    def handler(req: httpx.Request) -> httpx.Response:
        if "cursor=abc" in str(req.url):
            return httpx.Response(200, json=page2)
        return httpx.Response(200, json=page1)

    async with _client(handler) as client:
        provider = PolygonOptionsDataProvider("k", client=client)
        chain = await provider.get_option_chain("AAPL")

    assert isinstance(provider, OptionsDataProvider)
    assert len(chain.contracts) == 2
    types = {c.type for c in chain.contracts}
    assert types == {OptionType.CALL, OptionType.PUT}
    call = next(c for c in chain.contracts if c.type is OptionType.CALL)
    assert call.delta == 0.38
    assert call.expiry == date(2026, 6, 19)
    assert call.open_interest == 2500


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_polygon_events_returns_next_ex_dividend() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"results": [{"ex_dividend_date": "2026-06-05"}]},
        )

    async with _client(handler) as client:
        provider = PolygonEventsProvider("k", client=client, today=date(2026, 5, 22))
        got = await provider.next_ex_dividend_date("AAPL")

    assert isinstance(provider, EventsProvider)
    assert got == date(2026, 6, 5)


@pytest.mark.asyncio
async def test_polygon_events_returns_none_when_no_dividend() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": []})

    async with _client(handler) as client:
        provider = PolygonEventsProvider("k", client=client, today=date(2026, 5, 22))
        assert await provider.next_ex_dividend_date("XYZ") is None


@pytest.mark.asyncio
async def test_polygon_events_next_earnings_picks_earliest_future() -> None:
    today = date(2026, 5, 22)

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "results": [
                    {"filing_date": (today - timedelta(days=10)).isoformat()},  # past — ignore
                    {"filing_date": (today + timedelta(days=40)).isoformat()},
                    {"filing_date": (today + timedelta(days=12)).isoformat()},
                ]
            },
        )

    async with _client(handler) as client:
        provider = PolygonEventsProvider("k", client=client, today=today)
        got = await provider.next_earnings_date("AAPL")
    assert got == today + timedelta(days=12)


@pytest.mark.asyncio
async def test_polygon_events_earnings_returns_none_on_4xx() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": "not in plan"})

    async with _client(handler) as client:
        provider = PolygonEventsProvider("k", client=client, today=date(2026, 5, 22))
        assert await provider.next_earnings_date("AAPL") is None
