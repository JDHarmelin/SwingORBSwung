"""Synthetic data generators + sample option chain.

Importable from both tests (via ``tests.fixtures``) and runtime code
(e.g. ``trading_engine.data.mock_provider``). Deterministic via a seed
argument so tests are repeatable.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from trading_engine.core.types import (
    OHLCVSeries,
    OptionChain,
    OptionContract,
    OptionType,
    Timeframe,
)

# ---------------------------------------------------------------------------
# OHLCV helpers
# ---------------------------------------------------------------------------


def _timestamps(timeframe: Timeframe, n: int, end: datetime | None = None) -> list[datetime]:
    """Generate ``n`` timestamps ending at ``end`` for the given timeframe.

    Daily timeframes use calendar days (no weekend handling — synthetic).
    Intraday timeframes step by the timeframe's minute count from a fixed
    9:30 ET-equivalent UTC base, also synthetic.
    """
    end = end or datetime(2026, 5, 19, 20, 0, tzinfo=UTC)
    if timeframe is Timeframe.D1:
        start = end - timedelta(days=n - 1)
        return [start + timedelta(days=i) for i in range(n)]
    step_min = {
        Timeframe.M1: 1,
        Timeframe.M5: 5,
        Timeframe.M15: 15,
        Timeframe.M30: 30,
    }[timeframe]
    start = end - timedelta(minutes=step_min * (n - 1))
    return [start + timedelta(minutes=step_min * i) for i in range(n)]


def _series_from_closes(
    closes: np.ndarray,
    symbol: str,
    timeframe: Timeframe,
    *,
    seed: int = 7,
    base_volume: float = 1_000_000,
) -> OHLCVSeries:
    rng = np.random.default_rng(seed)
    ts = _timestamps(timeframe, len(closes))
    # Build OHLCV around the path: open lags close by 1; high/low jitter.
    opens = np.concatenate([[closes[0]], closes[:-1]])
    jitter = np.abs(closes - opens) * 0.5 + np.abs(closes) * 0.002
    highs = np.maximum(opens, closes) + rng.uniform(0.0, 1.0, len(closes)) * jitter
    lows = np.minimum(opens, closes) - rng.uniform(0.0, 1.0, len(closes)) * jitter
    volumes = base_volume * (1.0 + rng.uniform(-0.3, 0.5, len(closes)))

    df = pd.DataFrame(
        {
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
        },
        index=pd.DatetimeIndex(ts, name="timestamp"),
    )
    return OHLCVSeries.from_dataframe(df, symbol=symbol, timeframe=timeframe)


# ---------------------------------------------------------------------------
# Named market shapes
# ---------------------------------------------------------------------------


def clean_uptrend_series(
    symbol: str = "UPTRD", timeframe: Timeframe = Timeframe.D1, n: int = 60, seed: int = 1
) -> OHLCVSeries:
    """Clean uptrend with shallow noise — every close above the 8EMA."""
    rng = np.random.default_rng(seed)
    drift = np.linspace(0.0, 25.0, n)
    noise = rng.normal(0.0, 0.4, n)
    closes = 100.0 + drift + np.cumsum(noise * 0.3)
    return _series_from_closes(closes, symbol, timeframe, seed=seed)


def pullback_to_8ema_series(
    symbol: str = "PB8", timeframe: Timeframe = Timeframe.D1, n: int = 60, seed: int = 2
) -> OHLCVSeries:
    """Uptrend that pulls back to the 8EMA in the final ~8 bars."""
    rng = np.random.default_rng(seed)
    drift = np.linspace(0.0, 30.0, n - 8)
    rising = 100.0 + drift + rng.normal(0.0, 0.3, n - 8).cumsum() * 0.2
    # Pullback ~3% from peak then stabilise
    peak = rising[-1]
    pull = np.linspace(peak, peak * 0.97, 6)
    settle = np.array([peak * 0.972, peak * 0.974])
    closes = np.concatenate([rising, pull, settle])
    return _series_from_closes(closes, symbol, timeframe, seed=seed)


def compression_then_breakout_series(
    symbol: str = "FLAG", timeframe: Timeframe = Timeframe.D1, n: int = 60, seed: int = 3
) -> OHLCVSeries:
    """Range-up, tight compression, then expansion break — flag pattern."""
    rng = np.random.default_rng(seed)
    leg1 = 100.0 + np.linspace(0.0, 15.0, 30) + rng.normal(0, 0.3, 30).cumsum() * 0.2
    coil_base = leg1[-1]
    coil = coil_base + rng.normal(0, 0.15, 20)
    leg2 = coil[-1] + np.linspace(0.5, 8.0, n - 50)
    closes = np.concatenate([leg1, coil, leg2])
    return _series_from_closes(closes, symbol, timeframe, seed=seed, base_volume=1_500_000)


def breakdown_series(
    symbol: str = "BRKD", timeframe: Timeframe = Timeframe.D1, n: int = 60, seed: int = 4
) -> OHLCVSeries:
    """Distribution + key-support break — used for relative-weakness setup."""
    rng = np.random.default_rng(seed)
    top = 120.0 + rng.normal(0, 0.4, 30).cumsum() * 0.2
    drop = np.linspace(top[-1], top[-1] * 0.88, n - 30)
    closes = np.concatenate([top, drop])
    return _series_from_closes(closes, symbol, timeframe, seed=seed)


def choppy_series(
    symbol: str = "CHOP", timeframe: Timeframe = Timeframe.D1, n: int = 60, seed: int = 5
) -> OHLCVSeries:
    """No-trade chop — wide whippy range with no trend."""
    rng = np.random.default_rng(seed)
    closes = 100.0 + np.cumsum(rng.normal(0.0, 1.2, n))
    return _series_from_closes(closes, symbol, timeframe, seed=seed)


# ---------------------------------------------------------------------------
# Sample option chain (used to test contract selection §7)
# ---------------------------------------------------------------------------


def sample_option_chain(
    underlying: str = "UPTRD",
    spot: float = 125.0,
    as_of: datetime | None = None,
) -> OptionChain:
    """Multiple strikes × multiple expiries with greeks. Includes ONE illiquid
    contract that should be rejected by spec §7 (wide spread, low OI/volume).
    """
    as_of = as_of or datetime(2026, 5, 19, 20, 0, tzinfo=UTC)
    today = as_of.date()
    expiries = [
        today + timedelta(days=7),  # weekly
        today + timedelta(days=21),  # ~3wk swing
        today + timedelta(days=45),  # outer swing
    ]
    strikes = [spot - 10, spot - 5, spot, spot + 5, spot + 10]

    contracts: list[OptionContract] = []
    for exp in expiries:
        for k in strikes:
            for typ in (OptionType.CALL, OptionType.PUT):
                moneyness = (spot - k) if typ is OptionType.CALL else (k - spot)
                intrinsic = max(moneyness, 0.0)
                time_val = 1.5 + max(0.0, (exp - today).days / 30.0)
                mid = intrinsic + time_val
                spread = 0.04 + 0.01 * max(0.0, abs(k - spot) - 2)
                bid = max(0.05, mid - spread / 2)
                ask = mid + spread / 2
                # Greeks: rough but plausible
                if typ is OptionType.CALL:
                    delta = float(np.clip(0.5 + (spot - k) * 0.04, 0.05, 0.95))
                else:
                    delta = float(np.clip(-0.5 + (spot - k) * 0.04, -0.95, -0.05))
                contracts.append(
                    OptionContract(
                        ticker=f"O:{underlying}{exp:%y%m%d}{typ.value[0].upper()}{int(k * 1000):08d}",
                        underlying=underlying,
                        expiry=exp,
                        strike=float(k),
                        type=typ,
                        bid=round(bid, 2),
                        ask=round(ask, 2),
                        iv=0.35 + 0.02 * abs(k - spot) / spot,
                        delta=delta,
                        gamma=0.04,
                        theta=-0.05,
                        vega=0.10,
                        open_interest=2_500,
                        volume=400,
                    )
                )

    # One deliberately illiquid contract that should fail §7 rules.
    bad_expiry = today + timedelta(days=60)
    contracts.append(
        OptionContract(
            ticker=f"O:{underlying}{bad_expiry:%y%m%d}C99999000",
            underlying=underlying,
            expiry=bad_expiry,
            strike=spot + 50,
            type=OptionType.CALL,
            bid=0.05,
            ask=0.45,  # ~155% spread vs mid 0.25 — should be rejected
            iv=0.95,
            delta=0.04,
            gamma=0.01,
            theta=-0.01,
            vega=0.02,
            open_interest=12,
            volume=3,
        )
    )

    return OptionChain(underlying=underlying, snapshot_at=as_of, contracts=contracts)


# ---------------------------------------------------------------------------
# Sample universe + sector ETF series
# ---------------------------------------------------------------------------


def sample_universe() -> dict[str, list[str] | dict[str, str]]:
    """Tiny universe used by mock provider tests."""
    return {
        "symbols": ["UPTRD", "PB8", "FLAG", "BRKD", "CHOP"],
        "indices": ["SPY", "QQQ", "VIX"],
        "sector_etfs": {
            "tech_broad": "XLK",
            "semis": "SMH",
            "energy": "XLE",
        },
    }


def sample_sector_etf_series(
    etf: str = "XLK", timeframe: Timeframe = Timeframe.D1, n: int = 60
) -> OHLCVSeries:
    # Map a few common ETFs to representative shapes so tests can reason about
    # relative strength.
    mapping = {
        "XLK": clean_uptrend_series,
        "SMH": clean_uptrend_series,
        "XLE": compression_then_breakout_series,
        "XRT": choppy_series,
        "XLV": choppy_series,
        "SPY": clean_uptrend_series,
        "QQQ": clean_uptrend_series,
        "VIX": choppy_series,
    }
    shape = mapping.get(etf, choppy_series)
    return shape(symbol=etf, timeframe=timeframe, n=n)


def fixtures_dir() -> Path:
    """Path to the tests/fixtures/ directory (for CSV-on-disk variants)."""
    return Path(__file__).resolve().parents[2] / "tests" / "fixtures"


__all__ = [
    "breakdown_series",
    "choppy_series",
    "clean_uptrend_series",
    "compression_then_breakout_series",
    "fixtures_dir",
    "pullback_to_8ema_series",
    "sample_option_chain",
    "sample_sector_etf_series",
    "sample_universe",
]
