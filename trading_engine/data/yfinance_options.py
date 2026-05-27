"""yfinance-backed OptionsDataProvider.

Free, no API key, ~15-min delayed. yfinance is synchronous + scraping-based
so calls are wrapped in ``asyncio.to_thread`` and exceptions surface as
empty chains (chained provider can fall through to another source).

yfinance doesn't expose Greeks. We approximate delta from Black-Scholes
using the IV column it does return so the contract_selector's delta-band
logic still works. Risk-free rate is a constant 5.0% (close enough for
contract selection — we're picking a target delta bucket, not pricing).
"""

from __future__ import annotations

import asyncio
import logging
import math
from datetime import UTC, date, datetime

from trading_engine.core.types import OptionChain, OptionContract, OptionType

log = logging.getLogger(__name__)

_RISK_FREE = 0.05  # constant; selector buckets by delta, doesn't need precise pricing


def _f(v) -> float:
    """NaN/None-safe float."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if math.isnan(f) else f


def _i(v) -> int:
    """NaN/None-safe int."""
    f = _f(v)
    return int(f) if f else 0


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _bs_delta(
    spot: float, strike: float, iv: float, days_to_expiry: int, opt_type: OptionType
) -> float | None:
    """Black-Scholes delta. Returns None on degenerate inputs."""
    if spot <= 0 or strike <= 0 or iv <= 0 or days_to_expiry <= 0:
        return None
    t = days_to_expiry / 365.0
    d1 = (math.log(spot / strike) + (_RISK_FREE + 0.5 * iv * iv) * t) / (iv * math.sqrt(t))
    if opt_type is OptionType.CALL:
        return _norm_cdf(d1)
    return _norm_cdf(d1) - 1.0


class YFinanceOptionsDataProvider:
    """OptionsDataProvider implementation backed by yfinance.

    Spot price comes from the same yfinance Ticker so delta math stays
    self-consistent. Failures (network, no chain, parse) return an empty
    OptionChain — caller (typically ChainedOptionsDataProvider) can fall
    through to the next source.
    """

    def __init__(
        self,
        *,
        max_expiries: int = 6,
        max_retries: int = 2,
        backoff_seconds: float = 1.5,
        thin_chain_threshold: int = 20,
    ):
        # Yahoo aggressively throttles — when throttled it returns a tiny chain
        # or empties rather than a clear error. Treat a chain below
        # thin_chain_threshold as "probably throttled" and retry with backoff.
        self._max_expiries = max_expiries
        self._max_retries = max_retries
        self._backoff = backoff_seconds
        self._thin = thin_chain_threshold

    async def get_option_chain(
        self, underlying: str, as_of: datetime | None = None
    ) -> OptionChain:
        ts = as_of or datetime.now(tz=UTC)
        contracts: list[OptionContract] = []
        for attempt in range(self._max_retries + 1):
            try:
                contracts = await asyncio.to_thread(self._fetch_sync, underlying)
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "yfinance: %s attempt %d/%d failed: %s",
                    underlying, attempt + 1, self._max_retries + 1, exc,
                )
                contracts = []
            if len(contracts) >= self._thin:
                break
            if attempt < self._max_retries:
                delay = self._backoff * (2**attempt)
                log.info(
                    "yfinance: %s thin chain (%d contracts) — backing off %.1fs",
                    underlying, len(contracts), delay,
                )
                await asyncio.sleep(delay)
        return OptionChain(underlying=underlying, snapshot_at=ts, contracts=contracts)

    def _fetch_sync(self, underlying: str) -> list[OptionContract]:
        import yfinance as yf

        tk = yf.Ticker(underlying)
        expiries = list(tk.options or [])[: self._max_expiries]
        if not expiries:
            return []
        # Spot — use the most recent close from a 1-day fetch (cheap, cached).
        hist = tk.history(period="1d")
        spot = float(hist["Close"].iloc[-1]) if not hist.empty else 0.0
        today = date.today()

        rows: list[OptionContract] = []
        for exp in expiries:
            try:
                chain = tk.option_chain(exp)
            except Exception as exc:  # noqa: BLE001 — skip bad expiry, keep others
                log.warning("yfinance: %s expiry %s failed: %s", underlying, exp, exc)
                continue
            exp_date = date.fromisoformat(exp)
            dte = (exp_date - today).days
            for df, opt_type in ((chain.calls, OptionType.CALL), (chain.puts, OptionType.PUT)):
                for _, r in df.iterrows():
                    bid = _f(r.get("bid"))
                    ask = _f(r.get("ask"))
                    iv = _f(r.get("impliedVolatility")) or None
                    strike = _f(r.get("strike"))
                    if strike <= 0 or (bid <= 0 and ask <= 0):
                        continue
                    oi = _i(r.get("openInterest"))
                    vol = _i(r.get("volume"))
                    delta = (
                        _bs_delta(spot, strike, iv, dte, opt_type)
                        if iv is not None
                        else None
                    )
                    rows.append(
                        OptionContract(
                            ticker=str(r.get("contractSymbol", "")),
                            underlying=underlying,
                            expiry=exp_date,
                            strike=strike,
                            type=opt_type,
                            bid=bid,
                            ask=ask,
                            iv=iv,
                            delta=delta,
                            open_interest=oi,
                            volume=vol,
                        )
                    )
        return rows


__all__ = ["YFinanceOptionsDataProvider"]
