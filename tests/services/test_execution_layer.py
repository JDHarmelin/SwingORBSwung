"""Tests for the execution-only layer: confirmation gate + paper outcomes."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from trading_engine.core.config import load_app_config
from trading_engine.core.types import (
    Candle,
    Direction,
    OHLCVSeries,
    SetupType,
    Signal,
    SignalEvent,
    SignalStatus,
    TargetPlan,
    Timeframe,
)
from trading_engine.services.confirmation import ConfirmationDecision, PriceCrossConfirmationGate
from trading_engine.services.paper_tracker import simulate_outcome
from trading_engine.services.signal_service import SignalService
from trading_engine.setups.base import _candidate_id


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


# --- candidate dedupe + TTL ---------------------------------------------------


class _FakeRepo:
    """In-memory Repository stand-in for the execution-layer service tests."""

    def __init__(self) -> None:
        self.signals: dict[str, Signal] = {}
        self.events: list[SignalEvent] = []

    async def save_signal(self, signal: Signal) -> None:
        self.signals[signal.signal_id] = signal

    async def get_signal(self, signal_id: str) -> Signal | None:
        return self.signals.get(signal_id)

    async def open_signals(self) -> list[Signal]:
        open_st = {SignalStatus.PENDING, SignalStatus.TRIGGERED, SignalStatus.TRIMMED}
        return [s for s in self.signals.values() if s.status in open_st]

    async def append_signal_event(self, event: SignalEvent) -> None:
        self.events.append(event)

    async def list_signal_events(self, signal_id: str) -> list[SignalEvent]:
        return [e for e in self.events if e.signal_id == signal_id]

    async def list_events_by_type(self, event_type: str) -> list[SignalEvent]:
        return [e for e in self.events if e.event_type == event_type]

    async def latest_regime(self) -> None:
        return None


class _FakeAlert:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    async def send(self, message: str, *, dedupe_key: str) -> None:
        self.sent.append((message, dedupe_key))


class _YesGate:
    async def assess(self, signal: Signal) -> ConfirmationDecision:
        return ConfirmationDecision(True, 0.8, ["always"])


def _service(repo: _FakeRepo, alerts: _FakeAlert) -> SignalService:
    return SignalService(None, repo, alerts, config=load_app_config(), gate=_YesGate())  # type: ignore[arg-type]


def _pending(signal_id: str, *, age_hours: float) -> Signal:
    sig = _signal(100.0, 95.0)
    sig.signal_id = signal_id
    sig.timestamp = datetime.now(tz=UTC) - timedelta(hours=age_hours)
    return sig


def test_candidate_id_is_deterministic_per_symbol_setup_day() -> None:
    ts = datetime(2026, 5, 21, 14, 30, tzinfo=UTC)
    a = _candidate_id("AAPL", SetupType.B_BREAKOUT_RETEST, Direction.LONG, ts)
    b = _candidate_id("AAPL", SetupType.B_BREAKOUT_RETEST, Direction.LONG, ts)
    assert a == b == "AAPL:B_breakout_retest:long:20260521"
    # different direction and different day produce different ids
    assert _candidate_id("AAPL", SetupType.B_BREAKOUT_RETEST, Direction.SHORT, ts) != a
    next_day = ts + timedelta(days=1)
    assert _candidate_id("AAPL", SetupType.B_BREAKOUT_RETEST, Direction.LONG, next_day) != a


def test_expire_stale_candidates() -> None:
    repo = _FakeRepo()
    asyncio.run(repo.save_signal(_pending("old", age_hours=48)))
    asyncio.run(repo.save_signal(_pending("fresh", age_hours=1)))
    svc = _service(repo, _FakeAlert())

    expired = asyncio.run(svc.expire_stale_candidates())

    assert expired == ["old"]
    assert repo.signals["old"].status == SignalStatus.EXPIRED_RISK
    assert repo.signals["fresh"].status == SignalStatus.PENDING
    assert any(e.event_type == "expired_candidate" and e.signal_id == "old" for e in repo.events)


def test_confirm_signal_fires_one_alert() -> None:
    repo = _FakeRepo()
    sig = _pending("fresh", age_hours=1)
    asyncio.run(repo.save_signal(sig))
    alerts = _FakeAlert()
    svc = _service(repo, alerts)

    sent = asyncio.run(svc.confirm_signal(sig, confidence=0.9, reason_codes=["hermes"]))

    assert sent is True
    assert sig.status == SignalStatus.TRIGGERED
    assert len(alerts.sent) == 1
    triggered = [e for e in repo.events if e.event_type == "triggered"]
    assert triggered and triggered[0].event_payload["confidence"] == 0.9


def test_confirm_and_alert_skips_stale() -> None:
    repo = _FakeRepo()
    asyncio.run(repo.save_signal(_pending("old", age_hours=48)))
    asyncio.run(repo.save_signal(_pending("fresh", age_hours=1)))
    alerts = _FakeAlert()
    svc = _service(repo, alerts)

    confirmed = asyncio.run(svc.confirm_and_alert())

    assert confirmed == ["fresh"]
    assert repo.signals["old"].status == SignalStatus.PENDING  # stale: untouched, not fired
    assert len(alerts.sent) == 1
