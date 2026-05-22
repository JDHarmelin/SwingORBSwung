"""Relative strength of a stock vs benchmarks (SPY/QQQ).

Spec §5 RelativeStrength + §4 intraday-vs-index.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from trading_engine.core.types import OHLCVSeries, Timeframe

_DEFAULT_DAILY_LOOKBACKS: tuple[int, ...] = (1, 5, 20)
# Weights chosen so the 20d lookback dominates (longer-term momentum) while
# shorter windows keep the score reactive. Sum to 1.0.
_DEFAULT_WEIGHTS: dict[int, float] = {1: 0.2, 5: 0.3, 20: 0.5}


@dataclass(frozen=True)
class RelativeStrengthResult:
    """RS of a stock vs a benchmark, plus a normalised score in [-1, 1]."""

    symbol: str
    benchmark: str
    timeframe: Timeframe
    raw_returns: dict[str, float]
    benchmark_returns: dict[str, float]
    excess_returns: dict[str, float]
    rs_score: float
    intraday_excess: float | None = None
    reason_codes: list[str] = field(default_factory=list)


def _pct_return(close: pd.Series, lookback: int) -> float:
    if len(close) < lookback + 1:
        return float("nan")
    prev = float(close.iloc[-(lookback + 1)])
    last = float(close.iloc[-1])
    if prev == 0:
        return float("nan")
    return (last / prev) - 1.0


def _intraday_excess(stock_intraday: OHLCVSeries, bench_intraday: OHLCVSeries) -> float | None:
    """Session-to-date return spread between stock and benchmark."""
    s_df = stock_intraday.to_dataframe()
    b_df = bench_intraday.to_dataframe()
    if s_df.empty or b_df.empty:
        return None
    s_sessions = pd.Series(pd.DatetimeIndex(s_df.index).date, index=s_df.index)
    b_sessions = pd.Series(pd.DatetimeIndex(b_df.index).date, index=b_df.index)
    target = s_sessions.iloc[-1]
    s_day = s_df[s_sessions == target]
    b_day = b_df[b_sessions == target]
    if s_day.empty or b_day.empty:
        return None
    s_open = float(s_day["open"].iloc[0])
    b_open = float(b_day["open"].iloc[0])
    if s_open == 0 or b_open == 0:
        return None
    s_ret = float(s_day["close"].iloc[-1]) / s_open - 1.0
    b_ret = float(b_day["close"].iloc[-1]) / b_open - 1.0
    return s_ret - b_ret


def relative_strength(
    stock_daily: OHLCVSeries,
    benchmark_daily: OHLCVSeries,
    *,
    lookbacks: tuple[int, ...] = _DEFAULT_DAILY_LOOKBACKS,
    weights: dict[int, float] | None = None,
    stock_intraday: OHLCVSeries | None = None,
    benchmark_intraday: OHLCVSeries | None = None,
) -> RelativeStrengthResult:
    """RS of ``stock`` vs ``benchmark`` over multiple lookbacks.

    Returns raw, benchmark, and excess returns per lookback, an aggregate
    normalised ``rs_score`` in ``[-1, 1]`` (``tanh`` of weighted excess return,
    scaled), and — if intraday series are supplied — the session-to-date excess.
    """
    if stock_daily.timeframe is not Timeframe.D1 or benchmark_daily.timeframe is not Timeframe.D1:
        raise ValueError("relative_strength requires daily series for stock and benchmark")
    if stock_daily.symbol == benchmark_daily.symbol:
        raise ValueError("stock and benchmark must be different symbols")

    weights = weights or _DEFAULT_WEIGHTS
    if not lookbacks:
        raise ValueError("at least one lookback is required")

    stock_close = stock_daily.to_dataframe()["close"]
    bench_close = benchmark_daily.to_dataframe()["close"]

    raw: dict[str, float] = {}
    bench: dict[str, float] = {}
    excess: dict[str, float] = {}
    reasons: list[str] = []
    weighted_sum = 0.0
    weight_total = 0.0

    for lb in lookbacks:
        key = f"{lb}d"
        s = _pct_return(stock_close, lb)
        b = _pct_return(bench_close, lb)
        raw[key] = s
        bench[key] = b
        if np.isnan(s) or np.isnan(b):
            excess[key] = float("nan")
            continue
        x = s - b
        excess[key] = x
        w = weights.get(lb, 1.0 / len(lookbacks))
        weighted_sum += w * x
        weight_total += w
        if x > 0.01:
            reasons.append(f"RS+ vs {benchmark_daily.symbol} {key}: {x * 100:+.1f}%")
        elif x < -0.01:
            reasons.append(f"RS- vs {benchmark_daily.symbol} {key}: {x * 100:+.1f}%")

    weighted_excess = weighted_sum / weight_total if weight_total else 0.0
    # Map weighted excess return to [-1, 1]. Empirically a 10% multi-week
    # spread vs benchmark is a strong RS signal — scaling by 10 puts that
    # near tanh saturation (~0.76).
    rs_score = float(np.tanh(weighted_excess * 10.0))

    intraday_x: float | None = None
    if stock_intraday is not None and benchmark_intraday is not None:
        intraday_x = _intraday_excess(stock_intraday, benchmark_intraday)
        if intraday_x is not None:
            if intraday_x > 0.005:
                reasons.append(
                    f"Intraday RS+ vs {benchmark_daily.symbol}: {intraday_x * 100:+.2f}%"
                )
            elif intraday_x < -0.005:
                reasons.append(
                    f"Intraday RS- vs {benchmark_daily.symbol}: {intraday_x * 100:+.2f}%"
                )

    return RelativeStrengthResult(
        symbol=stock_daily.symbol,
        benchmark=benchmark_daily.symbol,
        timeframe=Timeframe.D1,
        raw_returns=raw,
        benchmark_returns=bench,
        excess_returns=excess,
        rs_score=rs_score,
        intraday_excess=intraday_x,
        reason_codes=reasons,
    )


@dataclass(frozen=True)
class CompositeRelativeStrength:
    """Combined RS across multiple benchmarks (typically SPY + QQQ)."""

    symbol: str
    per_benchmark: dict[str, RelativeStrengthResult]
    rs_score: float
    reason_codes: list[str] = field(default_factory=list)


def composite_relative_strength(
    stock_daily: OHLCVSeries,
    benchmarks_daily: dict[str, OHLCVSeries],
    *,
    stock_intraday: OHLCVSeries | None = None,
    benchmarks_intraday: dict[str, OHLCVSeries] | None = None,
) -> CompositeRelativeStrength:
    """Average RS across multiple benchmarks (e.g. SPY and QQQ).

    The composite ``rs_score`` is the mean of per-benchmark scores; reason
    codes are concatenated for downstream alerts.
    """
    if not benchmarks_daily:
        raise ValueError("at least one benchmark series is required")
    intra = benchmarks_intraday or {}
    per: dict[str, RelativeStrengthResult] = {}
    reasons: list[str] = []
    for name, bench in benchmarks_daily.items():
        per[name] = relative_strength(
            stock_daily,
            bench,
            stock_intraday=stock_intraday,
            benchmark_intraday=intra.get(name),
        )
        reasons.extend(per[name].reason_codes)
    score = float(np.mean([r.rs_score for r in per.values()]))
    return CompositeRelativeStrength(
        symbol=stock_daily.symbol,
        per_benchmark=per,
        rs_score=score,
        reason_codes=reasons,
    )


__all__ = [
    "CompositeRelativeStrength",
    "RelativeStrengthResult",
    "composite_relative_strength",
    "relative_strength",
]
