"""Paper outcome tracking — the learning log.

Every candidate is simulated forward on the underlying so the engine accrues a
signal -> outcome history. This is the ground truth a learning layer (Hermes)
trains on: which setups/conditions actually precede a viable move. Outcomes are
recorded as ``signal_events`` rows (event_type ``paper_outcome``), so no schema
migration is required.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from trading_engine.core.interfaces import Repository
from trading_engine.core.types import Direction, OHLCVSeries, Signal, SignalEvent

TERMINAL_RESULTS = ("win", "loss", "no_trigger")


@dataclass(frozen=True)
class PaperOutcome:
    signal_id: str
    symbol: str
    triggered: bool
    result: str  # "win" | "loss" | "open" | "no_trigger"
    r_multiple: float  # realized R: +rr on target, -1 on stop, 0 if no-trigger/open
    bars_held: int


def simulate_outcome(signal: Signal, series: OHLCVSeries, *, rr: float = 2.0) -> PaperOutcome:
    """Walk ``series`` forward from the trigger and resolve the trade in R units.

    Entry = trigger, risk = |entry - stop|, target = entry +/- rr*risk. Stop is
    checked before target within a bar (conservative). Returns ``no_trigger`` if
    price never reaches the entry, ``open`` if it triggers but never resolves.
    """
    entry = signal.trigger_price
    stop = signal.stop_price
    risk = abs(entry - stop)
    if risk == 0:
        return PaperOutcome(signal.signal_id, signal.symbol, False, "no_trigger", 0.0, 0)
    is_long = signal.direction == Direction.LONG
    target = entry + rr * risk if is_long else entry - rr * risk

    triggered = False
    bars = 0
    for c in series.candles:
        if not triggered:
            if (c.high >= entry) if is_long else (c.low <= entry):
                triggered = True
            else:
                continue
        bars += 1
        if is_long:
            if c.low <= stop:
                return PaperOutcome(signal.signal_id, signal.symbol, True, "loss", -1.0, bars)
            if c.high >= target:
                return PaperOutcome(signal.signal_id, signal.symbol, True, "win", rr, bars)
        else:
            if c.high >= stop:
                return PaperOutcome(signal.signal_id, signal.symbol, True, "loss", -1.0, bars)
            if c.low <= target:
                return PaperOutcome(signal.signal_id, signal.symbol, True, "win", rr, bars)

    if not triggered:
        return PaperOutcome(signal.signal_id, signal.symbol, False, "no_trigger", 0.0, 0)
    return PaperOutcome(signal.signal_id, signal.symbol, True, "open", 0.0, bars)


async def record_outcome(repo: Repository, outcome: PaperOutcome) -> None:
    """Persist a paper outcome as a signal_event (the learning log)."""
    await repo.append_signal_event(
        SignalEvent(
            signal_id=outcome.signal_id,
            event_timestamp=datetime.now(tz=UTC),
            event_type="paper_outcome",
            event_payload={
                "symbol": outcome.symbol,
                "triggered": outcome.triggered,
                "result": outcome.result,
                "r_multiple": outcome.r_multiple,
                "bars_held": outcome.bars_held,
            },
        )
    )
