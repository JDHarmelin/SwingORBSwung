"""Relative strength vs SPY/QQQ over multiple lookbacks."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from trading_engine.core.types import OHLCVSeries


@dataclass(frozen=True)
class RelativeStrengthResult:
    """Normalized RS score in [0, 1] plus raw return spreads."""

    score: float
    vs_spy_1d: float
    vs_spy_5d: float
    vs_spy_20d: float
    vs_qqq_1d: float
    reason_codes: list[str]


def _return_pct(series: OHLCVSeries, lookback: int) -> float:
    closes = series.to_dataframe()["close"]
    if len(closes) <= lookback:
        return 0.0
    start = float(closes.iloc[-(lookback + 1)])
    end = float(closes.iloc[-1])
    if start == 0:
        return 0.0
    return (end - start) / start * 100.0


def _normalize_spread(spread: float) -> float:
    """Map return spread (pct) to 0–1 score."""
    return float(np.clip(0.5 + spread / 10.0, 0.0, 1.0))


def relative_strength(
    stock: OHLCVSeries,
    spy: OHLCVSeries,
    qqq: OHLCVSeries,
    *,
    lookbacks: tuple[int, ...] = (1, 5, 20),
) -> RelativeStrengthResult:
    """Stock return minus index return over lookbacks; composite normalized score."""
    stock_1 = _return_pct(stock, lookbacks[0])
    stock_5 = _return_pct(stock, lookbacks[1])
    stock_20 = _return_pct(stock, lookbacks[2])
    spy_1 = _return_pct(spy, lookbacks[0])
    spy_5 = _return_pct(spy, lookbacks[1])
    spy_20 = _return_pct(spy, lookbacks[2])
    qqq_1 = _return_pct(qqq, lookbacks[0])

    vs_spy_1d = stock_1 - spy_1
    vs_spy_5d = stock_5 - spy_5
    vs_spy_20d = stock_20 - spy_20
    vs_qqq_1d = stock_1 - qqq_1

    raw = 0.4 * vs_spy_1d + 0.35 * vs_spy_5d + 0.25 * vs_spy_20d
    score = _normalize_spread(raw)

    reasons: list[str] = []
    if vs_spy_1d > 0.5:
        reasons.append("rs_vs_spy_1d_positive")
    if vs_spy_5d > 1.0:
        reasons.append("rs_vs_spy_5d_positive")
    if vs_spy_20d > 2.0:
        reasons.append("rs_vs_spy_20d_positive")
    if vs_qqq_1d > 0.5:
        reasons.append("rs_vs_qqq_1d_positive")
    if raw < -1.0:
        reasons.append("rs_underperforming")

    return RelativeStrengthResult(
        score=score,
        vs_spy_1d=vs_spy_1d,
        vs_spy_5d=vs_spy_5d,
        vs_spy_20d=vs_spy_20d,
        vs_qqq_1d=vs_qqq_1d,
        reason_codes=reasons,
    )
