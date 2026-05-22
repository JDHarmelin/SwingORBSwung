"""Polygon.io adapters implementing the data + events protocols.

Provides live equivalents of the mock providers:
- ``PolygonMarketDataProvider``  → ``MarketDataProvider``
- ``PolygonOptionsDataProvider`` → ``OptionsDataProvider``
- ``PolygonEventsProvider``      → ``EventsProvider``

All adapters take an injected ``httpx.AsyncClient`` so they can be tested
against ``httpx.MockTransport`` without touching the network. Auth is via
the ``Authorization: Bearer <api_key>`` header (Polygon also accepts an
``apiKey`` query param; the bearer form keeps URLs clean in logs).

Rate-limit + transient-error handling: 429 and 5xx are retried with
exponential backoff up to ``max_retries``.

This module pulls the wire format mapping; the engine-side ``OHLCVSeries`` /
``OptionContract`` types are unaware of Polygon.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, date, datetime
from typing import Any

import httpx

from trading_engine.core.types import (
    Candle,
    OHLCVSeries,
    OptionChain,
    OptionContract,
    OptionType,
    Timeframe,
)

log = logging.getLogger(__name__)

POLYGON_BASE_URL = "https://api.polygon.io"

# Timeframe → Polygon aggregate (multiplier, timespan)
_TIMEFRAME_TO_AGG: dict[Timeframe, tuple[int, str]] = {
    Timeframe.M1: (1, "minute"),
    Timeframe.M5: (5, "minute"),
    Timeframe.M15: (15, "minute"),
    Timeframe.M30: (30, "minute"),
    Timeframe.D1: (1, "day"),
}


# ---------------------------------------------------------------------------
# Shared HTTP plumbing
# ---------------------------------------------------------------------------


class _PolygonHttp:
    """Thin auth/retry wrapper. Adapters share one instance per client."""

    def __init__(
        self,
        api_key: str,
        *,
        client: httpx.AsyncClient | None = None,
        base_url: str = POLYGON_BASE_URL,
        max_retries: int = 4,
        backoff_seconds: float = 0.5,
    ) -> None:
        if not api_key:
            raise ValueError("Polygon api_key is required")
        self._api_key = api_key
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=20.0)
        self._base_url = base_url
        self._max_retries = max_retries
        self._backoff = backoff_seconds

    async def get_json(self, path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """GET ``path`` and return parsed JSON. Handles 429/5xx retries."""
        url = path if path.startswith("http") else f"{self._base_url}{path}"
        headers = {"Authorization": f"Bearer {self._api_key}"}
        last_exc: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                resp = await self._client.get(url, params=params, headers=headers)
            except httpx.TimeoutException as exc:
                last_exc = exc
                log.warning("polygon timeout attempt %d: %s", attempt + 1, exc)
                await asyncio.sleep(self._backoff * (2**attempt))
                continue
            if resp.status_code == 429 or resp.status_code >= 500:
                last_exc = httpx.HTTPStatusError(
                    f"polygon {resp.status_code}", request=resp.request, response=resp
                )
                log.warning("polygon %s attempt %d", resp.status_code, attempt + 1)
                await asyncio.sleep(self._backoff * (2**attempt))
                continue
            resp.raise_for_status()
            data = resp.json()
            assert isinstance(data, dict)
            return data
        assert last_exc is not None
        raise last_exc

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()


# ---------------------------------------------------------------------------
# Market data
# ---------------------------------------------------------------------------


def _agg_to_candle(symbol: str, tf: Timeframe, row: dict[str, Any]) -> Candle:
    return Candle(
        symbol=symbol,
        timeframe=tf,
        # Polygon timestamps are unix milliseconds; convert to tz-aware UTC.
        timestamp=datetime.fromtimestamp(row["t"] / 1000.0, tz=UTC),
        open=float(row["o"]),
        high=float(row["h"]),
        low=float(row["l"]),
        close=float(row["c"]),
        volume=float(row.get("v", 0.0)),
    )


class PolygonMarketDataProvider:
    """OHLCV + latest quote via Polygon aggregates."""

    def __init__(
        self,
        api_key: str,
        *,
        client: httpx.AsyncClient | None = None,
        base_url: str = POLYGON_BASE_URL,
    ) -> None:
        self._http = _PolygonHttp(api_key, client=client, base_url=base_url)

    async def get_ohlcv(
        self, symbol: str, timeframe: Timeframe, start: datetime, end: datetime
    ) -> OHLCVSeries:
        mult, span = _TIMEFRAME_TO_AGG[timeframe]
        # Polygon accepts YYYY-MM-DD or unix-ms — using date is simpler for daily,
        # ms for intraday so partial-day ranges round-trip correctly.
        if timeframe is Timeframe.D1:
            f_str = start.date().isoformat()
            t_str = end.date().isoformat()
        else:
            f_str = str(int(start.timestamp() * 1000))
            t_str = str(int(end.timestamp() * 1000))
        path = f"/v2/aggs/ticker/{symbol}/range/{mult}/{span}/{f_str}/{t_str}"
        data = await self._http.get_json(
            path, params={"adjusted": "true", "sort": "asc", "limit": 50000}
        )
        rows: list[dict[str, Any]] = data.get("results") or []
        candles = [_agg_to_candle(symbol, timeframe, r) for r in rows]
        return OHLCVSeries(symbol=symbol, timeframe=timeframe, candles=candles)

    async def get_latest_quote(self, symbol: str) -> Candle:
        # /v2/aggs/ticker/{ticker}/prev returns the most recent completed bar.
        path = f"/v2/aggs/ticker/{symbol}/prev"
        data = await self._http.get_json(path, params={"adjusted": "true"})
        rows: list[dict[str, Any]] = data.get("results") or []
        if not rows:
            raise RuntimeError(f"no recent bar for {symbol}")
        return _agg_to_candle(symbol, Timeframe.D1, rows[0])

    async def aclose(self) -> None:
        await self._http.aclose()


# ---------------------------------------------------------------------------
# Options
# ---------------------------------------------------------------------------


def _snapshot_to_contract(symbol: str, row: dict[str, Any]) -> OptionContract | None:
    details = row.get("details") or {}
    quote = row.get("last_quote") or {}
    greeks = row.get("greeks") or {}
    day = row.get("day") or {}
    ticker = details.get("ticker") or row.get("ticker")
    expiry_str = details.get("expiration_date")
    strike = details.get("strike_price")
    contract_type = details.get("contract_type")
    if not (ticker and expiry_str and strike and contract_type):
        return None
    expiry = date.fromisoformat(expiry_str)
    typ = OptionType.CALL if contract_type.lower() == "call" else OptionType.PUT
    bid = float(quote.get("bid") or row.get("fair_market_value") or 0.0)
    ask = float(quote.get("ask") or bid)
    return OptionContract(
        ticker=ticker,
        underlying=symbol,
        expiry=expiry,
        strike=float(strike),
        type=typ,
        bid=bid,
        ask=ask,
        iv=row.get("implied_volatility"),
        delta=greeks.get("delta"),
        gamma=greeks.get("gamma"),
        theta=greeks.get("theta"),
        vega=greeks.get("vega"),
        open_interest=int(row.get("open_interest") or 0),
        volume=int(day.get("volume") or 0),
    )


class PolygonOptionsDataProvider:
    """Option-chain snapshot via Polygon's options snapshot endpoint."""

    def __init__(
        self,
        api_key: str,
        *,
        client: httpx.AsyncClient | None = None,
        base_url: str = POLYGON_BASE_URL,
    ) -> None:
        self._http = _PolygonHttp(api_key, client=client, base_url=base_url)
        self._base_url = base_url

    async def get_option_chain(self, underlying: str, as_of: datetime | None = None) -> OptionChain:
        path = f"/v3/snapshot/options/{underlying}"
        contracts: list[OptionContract] = []
        next_url: str | None = path
        params: dict[str, Any] | None = {"limit": 250}
        while next_url is not None:
            data = await self._http.get_json(next_url, params=params)
            for row in data.get("results") or []:
                c = _snapshot_to_contract(underlying, row)
                if c is not None:
                    contracts.append(c)
            next_url = data.get("next_url")
            params = None  # next_url already carries query params
        snapshot_at = as_of or datetime.now(tz=UTC)
        if snapshot_at.tzinfo is None:
            snapshot_at = snapshot_at.replace(tzinfo=UTC)
        return OptionChain(underlying=underlying, snapshot_at=snapshot_at, contracts=contracts)

    async def aclose(self) -> None:
        await self._http.aclose()


# ---------------------------------------------------------------------------
# Events (earnings + ex-dividend)
# ---------------------------------------------------------------------------


class PolygonEventsProvider:
    """Corporate events.

    ``next_ex_dividend_date`` uses Polygon's ``/v3/reference/dividends``.
    ``next_earnings_date`` is best-effort — Polygon doesn't expose a stable
    "next earnings" endpoint on every plan, so we look for future filing dates
    in ``/vX/reference/financials`` and return the earliest. When unavailable
    (e.g. free tier), the method returns ``None`` rather than raising; the
    regime engine treats absent events as "no event-risk window".
    """

    def __init__(
        self,
        api_key: str,
        *,
        client: httpx.AsyncClient | None = None,
        base_url: str = POLYGON_BASE_URL,
        today: date | None = None,
    ) -> None:
        self._http = _PolygonHttp(api_key, client=client, base_url=base_url)
        self._today_override = today

    def _today(self) -> date:
        return self._today_override or datetime.now(tz=UTC).date()

    async def next_earnings_date(self, symbol: str) -> date | None:
        today = self._today()
        try:
            data = await self._http.get_json(
                "/vX/reference/financials",
                params={
                    "ticker": symbol,
                    "order": "asc",
                    "limit": 4,
                    "filing_date.gt": today.isoformat(),
                },
            )
        except httpx.HTTPStatusError:
            return None
        rows = data.get("results") or []
        future_dates: list[date] = []
        for r in rows:
            filing = r.get("filing_date") or r.get("end_date")
            if not filing:
                continue
            try:
                d = date.fromisoformat(filing)
            except ValueError:
                continue
            if d > today:
                future_dates.append(d)
        return min(future_dates) if future_dates else None

    async def next_ex_dividend_date(self, symbol: str) -> date | None:
        today = self._today()
        data = await self._http.get_json(
            "/v3/reference/dividends",
            params={
                "ticker": symbol,
                "order": "asc",
                "limit": 1,
                "ex_dividend_date.gte": today.isoformat(),
            },
        )
        rows = data.get("results") or []
        if not rows:
            return None
        ex = rows[0].get("ex_dividend_date")
        try:
            return date.fromisoformat(ex) if ex else None
        except (TypeError, ValueError):
            return None

    async def aclose(self) -> None:
        await self._http.aclose()


__all__ = [
    "POLYGON_BASE_URL",
    "PolygonEventsProvider",
    "PolygonMarketDataProvider",
    "PolygonOptionsDataProvider",
]
