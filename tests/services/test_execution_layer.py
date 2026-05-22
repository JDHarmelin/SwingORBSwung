"""Tests for the execution-only layer: confirmation gate + paper outcomes."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from trading_engine.core.types import (
    Candle,
    Direction,
    OHLCVSeries,
    SetupType,
    Signal,
    SignalStatus,
    TargetPlan,
    Timeframe,
)
from trading_engine.services.confirmation import PriceCrossConfirmationGate
from trading_engine.services.paper_tracker import simulate_outcome


def _candle(day: int, *, high: float, low: float, close: float) -> Candle:
    return Candle(
        symbol="TEST",
        timeframe=Timeframe.D1,
        timestamp=datetime(2026, 5, 1, tzinfo=UTC) + timedelta(days=day),
        open=(high + low) / 2,
        high=high,
        low=low,
        close=close,
        volume=1_000_000,
    )


def _signal(trigger: float, stop: float, direction: Direction = Direction.LONG) -> Signal:
    return Signal(
        signal_id="s-1",
        timestamp=datetime(2026, 5, 1, tzinfo=UTC),
        symbol="TEST",
        setup_type=SetupType.B_BREAKOUT_RETEST,
        direction=direction,
        trigger_price=trigger,
        stop_price=stop,
        target_plan=TargetPlan(trim1_gain_pct=30, trim2_gain_pct=60, runner_trail="8EMA"),
        rationale="test",
        confidence=0.7,
        status=SignalStatus.PENDING,
        reason_codes=[],
    )


def _series(candles: list[Candle]) -> OHLCVSeries:
    return OHLCVSeries(symbol="TEST", timeframe=Timeframe.D1, candles=candles)


# --- paper outcome simulation -------------------------------------------------


def test_outcome_win_long() -> None:
    # trigger 100, stop 95 (risk 5), target = 110. Price triggers then runs up.
    sig = _signal(100.0, 95.0)
    series = _series(
        [
            _candle(0, high=99, low=97, close=98),  # no trigger yet
            _candle(1, high=101, low=99, close=100.5),  # triggers (high>=100)
            _candle(2, high=111, low=101, close=110.5),  # hits target 110
        ]
    )
    out = simulate_outcome(sig, series)
    assert out.triggered is True
    assert out.result == "win"
    assert out.r_multiple == 2.0


def test_outcome_loss_long() -> None:
    sig = _signal(100.0, 95.0)
    series = _series(
        [
            _candle(0, high=101, low=99, close=100.5),  # triggers
            _candle(1, high=100, low=94, close=95.5),  # hits stop 95
        ]
    )
    out = simulate_outcome(sig, series)
    assert out.result == "loss"
    assert out.r_multiple == -1.0


def test_outcome_no_trigger() -> None:
    sig = _signal(100.0, 95.0)
    series = _series([_candle(0, high=99, low=96, close=97)])
    out = simulate_outcome(sig, series)
    assert out.triggered is False
    assert out.result == "no_trigger"


# --- confirmation gate --------------------------------------------------------


class _StubMarket:
    def __init__(self, last_close: float) -> None:
        self._close = last_close

    async def get_latest_quote(self, symbol: str) -> Candle:
        return _candle(0, high=self._close, low=self._close, close=self._close)

    async def get_ohlcv(self, *a: object, **k: object) -> OHLCVSeries:  # pragma: no cover
        return _series([])


def test_gate_confirms_when_price_crosses_long() -> None:
    gate = PriceCrossConfirmationGate(_StubMarket(101.0))
    decision = asyncio.run(gate.assess(_signal(100.0, 95.0)))
    assert decision.confirmed is True
    assert "price_crossed_trigger" in decision.reason_codes


def test_gate_waits_below_trigger_long() -> None:
    gate = PriceCrossConfirmationGate(_StubMarket(99.0))
    decision = asyncio.run(gate.assess(_signal(100.0, 95.0)))
    assert decision.confirmed is False
    assert "awaiting_trigger" in decision.reason_codes
