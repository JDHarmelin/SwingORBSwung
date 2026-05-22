"""Universe builder (spec §2).

Applies liquidity filters (price, average dollar volume) to the configured
symbol list to produce the tradable universe. Pure given the candle data it is
handed — the caller supplies daily series per symbol.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from trading_engine.core.config import LiquidityConfig
from trading_engine.core.types import OHLCVSeries


@dataclass(frozen=True)
class UniverseEntry:
    symbol: str
    last_price: float
    avg_dollar_volume: float
    passed: bool
    reasons: list[str] = field(default_factory=list)


def _avg_dollar_volume(series: OHLCVSeries, lookback: int = 20) -> float:
    df = series.to_dataframe()
    tail = df.iloc[-lookback:]
    if tail.empty:
        return 0.0
    return float((tail["close"] * tail["volume"]).mean())


def evaluate_symbol(
    symbol: str, daily: OHLCVSeries, liquidity: LiquidityConfig, *, lookback: int = 20
) -> UniverseEntry:
    df = daily.to_dataframe()
    if df.empty:
        return UniverseEntry(symbol, 0.0, 0.0, False, ["no candle data"])
    last_price = float(df["close"].iloc[-1])
    addv = _avg_dollar_volume(daily, lookback)
    reasons: list[str] = []
    if last_price < liquidity.min_price:
        reasons.append(f"price {last_price:.2f} < min {liquidity.min_price}")
    if addv < liquidity.min_avg_daily_dollar_volume:
        reasons.append(
            f"ADDV {addv:,.0f} < min {liquidity.min_avg_daily_dollar_volume:,.0f}"
        )
    passed = not reasons
    if passed:
        reasons.append("liquidity OK")
    return UniverseEntry(symbol, last_price, addv, passed, reasons)


def build_universe(
    series_by_symbol: dict[str, OHLCVSeries],
    liquidity: LiquidityConfig,
    *,
    lookback: int = 20,
) -> list[UniverseEntry]:
    """Evaluate every symbol; return all entries (filter on ``.passed``)."""
    return [
        evaluate_symbol(sym, series, liquidity, lookback=lookback)
        for sym, series in series_by_symbol.items()
    ]


def tradable_symbols(entries: list[UniverseEntry]) -> list[str]:
    return [e.symbol for e in entries if e.passed]


__all__ = [
    "UniverseEntry",
    "build_universe",
    "evaluate_symbol",
    "tradable_symbols",
]
