"""Polygon.io REST adapters — normalization layer + provider."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
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
from trading_engine.data.cache import OhlcvDiskCache

logger = logging.getLogger(__name__)

_TIMEFRAME_MAP = {
    Timeframe.M1: ("minute", 1),
    Timeframe.M5: ("minute", 5),
    Timeframe.M15: ("minute", 15),
    Timeframe.M30: ("minute", 30),
    Timeframe.D1: ("day", 1),
}

# Free Polygon tiers are ~5 calls/min; paid tiers can lower this via env.
_DEFAULT_MIN_INTERVAL = float(os.environ.get("POLYGON_MIN_INTERVAL_SEC", "12"))


def normalize_aggs(payload: dict[str, Any], symbol: str, timeframe: Timeframe) -> OHLCVSeries:
    """Convert Polygon aggregates JSON → OHLCVSeries."""
    results = payload.get("results") or []
    candles: list[Candle] = []
    for bar in results:
        ts_ms = bar.get("t")
        if ts_ms is None:
            continue
        candles.append(
            Candle(
                symbol=symbol,
                timeframe=timeframe,
                timestamp=datetime.fromtimestamp(ts_ms / 1000.0, tz=UTC),
                open=float(bar["o"]),
                high=float(bar["h"]),
                low=float(bar["l"]),
                close=float(bar["c"]),
                volume=float(bar.get("v", 0)),
            )
        )
    return OHLCVSeries(symbol=symbol, timeframe=timeframe, candles=candles)


def normalize_option_chain(
    payload: dict[str, Any], underlying: str, as_of: datetime
) -> OptionChain:
    """Convert Polygon options snapshot → OptionChain."""
    contracts: list[OptionContract] = []
    for item in payload.get("results") or []:
        details = item.get("details") or item
        greeks = item.get("greeks") or {}
        quote = item.get("last_quote") or item
        strike = float(details.get("strike_price", 0))
        exp_str = details.get("expiration_date")
        if not exp_str:
            continue
        exp = date.fromisoformat(exp_str)
        typ = (
            OptionType.CALL
            if (details.get("contract_type") or "").lower() == "call"
            else OptionType.PUT
        )
        bid = float(quote.get("bid", 0) or 0)
        ask = float(quote.get("ask", 0) or 0)
        contracts.append(
            OptionContract(
                ticker=str(details.get("ticker", "")),
                underlying=underlying,
                expiry=exp,
                strike=strike,
                type=typ,
                bid=bid,
                ask=ask,
                iv=float(item.get("implied_volatility") or 0) or None,
                delta=float(greeks.get("delta") or 0) or None,
                gamma=float(greeks.get("gamma") or 0) or None,
                theta=float(greeks.get("theta") or 0) or None,
                vega=float(greeks.get("vega") or 0) or None,
                open_interest=int(item.get("open_interest") or 0),
                volume=int(
                    item.get("day", {}).get("volume", 0) if isinstance(item.get("day"), dict) else 0
                ),
            )
        )
    return OptionChain(underlying=underlying, snapshot_at=as_of, contracts=contracts)


class PolygonClient:
    """Low-level HTTP with global throttle + 429 backoff (one client per API key)."""

    _gate: asyncio.Lock | None = None
    _last_request_at: float = 0.0
    _cooldown_until: float = 0.0

    def __init__(
        self,
        api_key: str,
        *,
        timeout: float = 30.0,
        max_retries: int = 6,
        min_request_interval_sec: float | None = None,
    ) -> None:
        self._key = api_key
        self._timeout = timeout
        self._max_retries = max_retries
        self._interval = (
            min_request_interval_sec
            if min_request_interval_sec is not None
            else _DEFAULT_MIN_INTERVAL
        )
        self._base = "https://api.polygon.io"
        if PolygonClient._gate is None:
            PolygonClient._gate = asyncio.Lock()
        logger.info("Polygon client ready (min %.1fs between requests)", self._interval)

    async def _throttle(self) -> None:
        assert PolygonClient._gate is not None
        async with PolygonClient._gate:
            now = time.monotonic()
            if now < PolygonClient._cooldown_until:
                wait_cd = PolygonClient._cooldown_until - now
                logger.warning("Polygon cooldown — waiting %.0fs before next request", wait_cd)
                await asyncio.sleep(wait_cd)
            now = time.monotonic()
            wait = self._interval - (now - PolygonClient._last_request_at)
            if wait > 0:
                await asyncio.sleep(wait)
            PolygonClient._last_request_at = time.monotonic()

    @staticmethod
    def _retry_after_seconds(resp: httpx.Response, attempt: int) -> float:
        raw = resp.headers.get("Retry-After")
        if raw:
            try:
                return max(float(raw), 30.0)
            except ValueError:
                pass
        # Free tier: wait at least 60s when rate-limited (429 bursts are useless)
        return float(min(120.0, max(60.0, 15.0 * (2**attempt))))

    async def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        params = dict(params or {})
        params["apiKey"] = self._key
        last_err: Exception | None = None
        for attempt in range(self._max_retries):
            await self._throttle()
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    resp = await client.get(f"{self._base}{path}", params=params)
                    if resp.status_code == 429:
                        delay = self._retry_after_seconds(resp, attempt)
                        PolygonClient._cooldown_until = time.monotonic() + delay
                        logger.warning(
                            "Polygon rate limit (429) on %s — pausing %.0fs (attempt %s/%s). "
                            "Tip: wait a minute or use --symbols NVDA,AAPL with fewer tickers.",
                            path,
                            delay,
                            attempt + 1,
                            self._max_retries,
                        )
                        await asyncio.sleep(delay)
                        continue
                    resp.raise_for_status()
                    data = resp.json()
                    if not isinstance(data, dict):
                        raise ValueError("Expected JSON object")
                    return data
            except httpx.HTTPStatusError as e:
                last_err = e
                if e.response.status_code == 403:
                    raise
                await asyncio.sleep(0.5 * (2**attempt))
            except Exception as e:
                last_err = e
                await asyncio.sleep(0.5 * (2**attempt))
        raise RuntimeError(f"Polygon request failed after retries: {last_err}")


class PolygonMarketDataProvider:
    def __init__(self, client: PolygonClient, *, use_cache: bool = True) -> None:
        self._client = client
        self._cache = OhlcvDiskCache() if use_cache else None

    async def get_ohlcv(
        self,
        symbol: str,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
    ) -> OHLCVSeries:
        if self._cache:
            cached = self._cache.get(symbol, timeframe.value, start, end)
            if cached is not None:
                return cached
        span, mult = _TIMEFRAME_MAP[timeframe]
        path = f"/v2/aggs/ticker/{symbol}/range/{mult}/{span}/{start.date()}/{end.date()}"
        payload = await self._client.get(path, {"adjusted": "true", "sort": "asc", "limit": 50000})
        series = normalize_aggs(payload, symbol, timeframe)
        if self._cache:
            self._cache.put(symbol, timeframe.value, start, end, series)
        return series

    async def get_latest_quote(self, symbol: str) -> Candle:
        now = datetime.now(tz=UTC)
        series = await self.get_ohlcv(symbol, Timeframe.M5, now - timedelta(days=1), now)
        return series.candles[-1]


class PolygonOptionsDataProvider:
    def __init__(self, client: PolygonClient, *, ttl_sec: float = 45.0) -> None:
        self._client = client
        self._ttl_sec = ttl_sec
        self._cache: dict[str, tuple[OptionChain, float]] = {}

    async def get_option_chain(self, underlying: str, as_of: datetime | None = None) -> OptionChain:
        as_of = as_of or datetime.now(tz=UTC)
        key = underlying.upper()
        now = time.monotonic()
        if key in self._cache:
            chain, expires_at = self._cache[key]
            if now < expires_at:
                return chain
        path = f"/v3/snapshot/options/{underlying}"
        payload = await self._client.get(path)
        chain = normalize_option_chain(payload, underlying, as_of)
        self._cache[key] = (chain, now + self._ttl_sec)
        return chain


class PolygonEventsProvider:
    def __init__(self, client: PolygonClient) -> None:
        self._client = client

    async def next_earnings_date(self, symbol: str) -> date | None:
        try:
            payload = await self._client.get(
                "/vX/reference/financials",
                {"ticker": symbol, "limit": 1},
            )
            _ = payload
        except Exception:
            logger.debug("earnings lookup unavailable for %s", symbol)
        return None

    async def next_ex_dividend_date(self, symbol: str) -> date | None:
        return None


def _interval_from_project_env() -> float:
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if env_path.is_file():
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line.startswith("POLYGON_MIN_INTERVAL_SEC="):
                _, _, val = line.partition("=")
                try:
                    return max(float(val.strip()), 0.0)
                except ValueError:
                    break
    return float(os.environ.get("POLYGON_MIN_INTERVAL_SEC", str(_DEFAULT_MIN_INTERVAL)))


def create_polygon_client(api_key: str) -> PolygonClient:
    """Shared client for market + options + events (single rate-limit bucket)."""
    interval = _interval_from_project_env()
    return PolygonClient(api_key, min_request_interval_sec=interval)
