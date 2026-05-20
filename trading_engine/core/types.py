"""Shared typed models and enums for the Systematic Momentum Options Engine.

All models are pydantic v2 and JSON-serializable so signals stay replayable
(non-negotiable design rule: every signal replayable from stored candles +
metadata).
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, field_validator

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class Timeframe(StrEnum):
    M1 = "1m"
    M5 = "5m"
    M15 = "15m"
    M30 = "30m"
    D1 = "1d"


class Direction(StrEnum):
    LONG = "long"
    SHORT = "short"


class RegimeType(StrEnum):
    LONG_BIAS = "long_bias"
    SHORT_BIAS = "short_bias"
    MIXED = "mixed"
    NO_TRADE = "no_trade"


class SetupType(StrEnum):
    """Six setups defined in spec §6."""

    A_BREAKOUT_CONTINUATION = "A_breakout_continuation"
    B_BREAKOUT_RETEST = "B_breakout_retest"
    C_EMA_CONTINUATION = "C_ema_continuation"
    D_COMPRESSION_BREAK = "D_compression_break"
    E_RELATIVE_WEAKNESS = "E_relative_weakness"
    F_INDEX_TACTICAL = "F_index_tactical"


class RiskClass(StrEnum):
    A_PLUS = "a_plus"
    STANDARD = "standard"
    LOTTO = "lotto"
    HEDGE = "hedge"


class SignalStatus(StrEnum):
    PENDING = "pending"
    TRIGGERED = "triggered"
    STOPPED = "stopped"
    TRIMMED = "trimmed"
    CLOSED = "closed"
    EXPIRED_RISK = "expired_risk"


class OptionType(StrEnum):
    CALL = "call"
    PUT = "put"


# ---------------------------------------------------------------------------
# Base config (JSON-serializable, no arbitrary types except where explicit)
# ---------------------------------------------------------------------------


class _Base(BaseModel):
    model_config = ConfigDict(
        frozen=False,
        populate_by_name=True,
        use_enum_values=False,
        ser_json_timedelta="iso8601",
    )


# ---------------------------------------------------------------------------
# OHLCV
# ---------------------------------------------------------------------------


class Candle(_Base):
    symbol: str
    timeframe: Timeframe
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float

    @field_validator("high")
    @classmethod
    def _high_ge_low(cls, v: float, info: Any) -> float:
        low = info.data.get("low")
        if low is not None and v < low:
            raise ValueError("Candle.high must be >= Candle.low")
        return v


class OHLCVSeries(_Base):
    """A lightweight wrapper around an ordered list of candles.

    Convertible to/from a pandas DataFrame. The DataFrame uses the candle
    timestamp as the index and columns ['open','high','low','close','volume'].
    """

    symbol: str
    timeframe: Timeframe
    candles: list[Candle] = Field(default_factory=list)

    def to_dataframe(self) -> pd.DataFrame:
        if not self.candles:
            return pd.DataFrame(
                columns=["open", "high", "low", "close", "volume"],
                index=pd.DatetimeIndex([], name="timestamp"),
            )
        rows = [
            {
                "timestamp": c.timestamp,
                "open": c.open,
                "high": c.high,
                "low": c.low,
                "close": c.close,
                "volume": c.volume,
            }
            for c in self.candles
        ]
        df = pd.DataFrame(rows).set_index("timestamp").sort_index()
        return df

    @classmethod
    def from_dataframe(cls, df: pd.DataFrame, symbol: str, timeframe: Timeframe) -> OHLCVSeries:
        required = {"open", "high", "low", "close", "volume"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"DataFrame missing required columns: {missing}")
        candles: list[Candle] = []
        for ts, row in df.iterrows():
            candles.append(
                Candle(
                    symbol=symbol,
                    timeframe=timeframe,
                    timestamp=pd.Timestamp(ts).to_pydatetime(),  # type: ignore[arg-type]
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row["volume"]),
                )
            )
        return cls(symbol=symbol, timeframe=timeframe, candles=candles)


# ---------------------------------------------------------------------------
# Options
# ---------------------------------------------------------------------------


class OptionContract(_Base):
    ticker: str
    underlying: str
    expiry: date
    strike: float
    type: OptionType
    bid: float
    ask: float
    iv: float | None = None
    delta: float | None = None
    gamma: float | None = None
    theta: float | None = None
    vega: float | None = None
    open_interest: int = 0
    volume: int = 0

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0

    @property
    def spread_pct(self) -> float | None:
        if self.mid <= 0:
            return None
        return (self.ask - self.bid) / self.mid * 100.0


class OptionChain(_Base):
    underlying: str
    snapshot_at: datetime
    contracts: list[OptionContract] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Regime / ranking
# ---------------------------------------------------------------------------


class MarketRegime(_Base):
    timestamp: datetime
    regime: RegimeType
    confidence: float = Field(ge=0.0, le=1.0)
    notes: list[str] = Field(default_factory=list)


class SectorScore(_Base):
    timestamp: datetime
    sector: str
    rs_1d: float
    rs_5d: float
    rs_20d: float
    breadth_score: float
    composite_score: float


class SymbolScore(_Base):
    """Composite symbol score (spec §5). Sub-scores match the factor model."""

    timestamp: datetime
    symbol: str
    direction_bucket: Direction
    rs_score: float
    sector_score: float
    structure_score: float
    trend_score: float
    volume_score: float
    catalyst_score: float
    composite_score: float
    reason_codes: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Risk / contract / signal
# ---------------------------------------------------------------------------


class TargetPlan(_Base):
    """Trim-to-breakeven management template (spec §8)."""

    trim1_gain_pct: float = 30.0
    trim2_gain_pct: float = 60.0
    move_stop_to_be_after_trim1: bool = True
    runner_trail: str = "8EMA"  # e.g. "8EMA", "prior_candle_low", "VWAP"
    forced_exit_before_event: bool = True
    notes: list[str] = Field(default_factory=list)


class ContractSuggestion(_Base):
    """Matches JSON example in spec §7."""

    ticker: str
    direction: str  # e.g. "long_call", "long_put"
    expiry: date
    strike: float
    delta: float | None = None
    bid_ask_spread_pct: float | None = None
    classification: str = "standard_swing"  # standard_swing, day, lotto, hedge
    open_interest: int | None = None
    volume: int | None = None


class Signal(_Base):
    """Matches the `signals` table outline (spec, DB outline)."""

    signal_id: str
    timestamp: datetime
    symbol: str
    setup_type: SetupType
    direction: Direction
    trigger_price: float
    stop_price: float
    target_plan: TargetPlan
    contract: ContractSuggestion | None = None
    rationale: str
    confidence: float = Field(ge=0.0, le=1.0)
    status: SignalStatus = SignalStatus.PENDING
    risk_class: RiskClass = RiskClass.STANDARD
    reason_codes: list[str] = Field(default_factory=list)


class SignalEvent(_Base):
    """Matches the `signal_events` table outline."""

    signal_id: str
    event_timestamp: datetime
    event_type: str  # triggered, stop_hit, trim1, be_moved, runner_exit, expiry_risk, roll
    event_payload: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "Candle",
    "ContractSuggestion",
    "Direction",
    "MarketRegime",
    "OHLCVSeries",
    "OptionChain",
    "OptionContract",
    "OptionType",
    "RegimeType",
    "RiskClass",
    "SectorScore",
    "SetupType",
    "Signal",
    "SignalEvent",
    "SignalStatus",
    "SymbolScore",
    "TargetPlan",
    "Timeframe",
]
