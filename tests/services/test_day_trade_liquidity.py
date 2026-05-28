"""day_trade liquidity-override selection.

Index-tactical day-trades classify as risk_class=STANDARD but must use the
looser ``day_trade`` option floor. These tests pin both the key-selection
helper and the loaded-config override values.
"""

from __future__ import annotations

from trading_engine.core.config import load_settings
from trading_engine.services.signal_service import liquidity_key


def test_liquidity_key_prefers_day_trade_when_flag_set() -> None:
    # Even though the risk class is "standard", the day_trade flag wins.
    assert liquidity_key("standard", day_trade=True) == "day_trade"


def test_liquidity_key_uses_risk_class_when_not_day_trade() -> None:
    assert liquidity_key("standard", day_trade=False) == "standard"
    assert liquidity_key("a_plus", day_trade=False) == "a_plus"


def test_day_trade_override_resolves_to_loosened_floor() -> None:
    settings = load_settings()
    floor = settings.liquidity.for_risk_class(
        liquidity_key("standard", day_trade=True)
    )
    assert floor.min_option_open_interest == 50
    assert floor.min_option_volume == 50
    assert floor.max_option_bid_ask_spread_pct == 12.0
