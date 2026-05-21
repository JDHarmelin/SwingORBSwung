"""Trade management transitions — spec §8."""

from __future__ import annotations

from datetime import UTC, datetime

from trading_engine.core.config import AppConfig, load_app_config
from trading_engine.core.types import Signal, SignalEvent, SignalStatus


def evaluate_management(
    signal: Signal,
    *,
    option_gain_pct: float,
    current_price: float | None = None,
    config: AppConfig | None = None,
) -> SignalEvent | None:
    """Emit next management event given simulated option gain."""
    config = config or load_app_config()
    risk = config.settings.risk
    now = datetime.now(tz=UTC)

    if signal.status == SignalStatus.PENDING and option_gain_pct >= 5:
        return SignalEvent(
            signal_id=signal.signal_id,
            event_timestamp=now,
            event_type="triggered",
            event_payload={"symbol": signal.symbol, "price": current_price},
        )
    if option_gain_pct >= risk.trim1_gain_pct and signal.status == SignalStatus.TRIGGERED:
        return SignalEvent(
            signal_id=signal.signal_id,
            event_timestamp=now,
            event_type="trim1",
            event_payload={"gain_pct": option_gain_pct},
        )
    if option_gain_pct >= risk.trim2_gain_pct:
        return SignalEvent(
            signal_id=signal.signal_id,
            event_timestamp=now,
            event_type="runner_exit",
            event_payload={"gain_pct": option_gain_pct},
        )
    if option_gain_pct <= -100 * (signal.trigger_price - signal.stop_price) / signal.trigger_price:
        return SignalEvent(
            signal_id=signal.signal_id,
            event_timestamp=now,
            event_type="stop_hit",
            event_payload={"symbol": signal.symbol},
        )
    if risk.move_stop_to_be_after_trim1 and signal.status == SignalStatus.TRIMMED:
        return SignalEvent(
            signal_id=signal.signal_id,
            event_timestamp=now,
            event_type="be_moved",
            event_payload={},
        )
    return None
