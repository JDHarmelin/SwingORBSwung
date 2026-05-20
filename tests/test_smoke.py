"""Smoke tests — every core module imports and basic invariants hold."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from trading_engine.core import config as cfg
from trading_engine.core.interfaces import (
    AlertSink,
    EventsProvider,
    MarketDataProvider,
    OptionsDataProvider,
    Repository,
)
from trading_engine.core.types import (
    ContractSuggestion,
    Direction,
    OHLCVSeries,
    RegimeType,
    RiskClass,
    SetupType,
    Signal,
    SignalStatus,
    TargetPlan,
    Timeframe,
)
from trading_engine.data.mock_provider import (
    MockEventsProvider,
    MockMarketDataProvider,
    MockOptionsDataProvider,
)


def test_modules_import() -> None:
    # Ensures every top-level package + core/* + data/mock_provider import.
    import trading_engine  # noqa: F401
    import trading_engine.alerts  # noqa: F401
    import trading_engine.core  # noqa: F401
    import trading_engine.data  # noqa: F401
    import trading_engine.features  # noqa: F401
    import trading_engine.risk  # noqa: F401
    import trading_engine.scanners  # noqa: F401
    import trading_engine.services  # noqa: F401
    import trading_engine.setups  # noqa: F401
    import trading_engine.storage  # noqa: F401


def test_load_settings_and_universe() -> None:
    app = cfg.load_app_config()
    assert (
        abs(
            app.settings.factor_weights.relative_strength
            + app.settings.factor_weights.sector_strength
            + app.settings.factor_weights.structure
            + app.settings.factor_weights.trend
            + app.settings.factor_weights.volume_expansion
            + app.settings.factor_weights.catalyst
            - 1.0
        )
        < 1e-6
    )
    assert "SPY" in app.universe.indices
    assert app.universe.sector_etfs["semis"] == "SMH"


def test_ohlcv_roundtrip(uptrend_daily: OHLCVSeries) -> None:
    df = uptrend_daily.to_dataframe()
    assert set(df.columns) == {"open", "high", "low", "close", "volume"}
    rebuilt = OHLCVSeries.from_dataframe(df, symbol=uptrend_daily.symbol, timeframe=Timeframe.D1)
    assert len(rebuilt.candles) == len(uptrend_daily.candles)


def test_signal_is_json_serializable() -> None:
    s = Signal(
        signal_id="sig-1",
        timestamp=datetime(2026, 5, 20, 14, 30, tzinfo=UTC),
        symbol="NVDA",
        setup_type=SetupType.B_BREAKOUT_RETEST,
        direction=Direction.LONG,
        trigger_price=132.40,
        stop_price=130.95,
        target_plan=TargetPlan(),
        contract=ContractSuggestion(
            ticker="O:NVDA260619C00135000",
            direction="long_call",
            expiry=(datetime(2026, 6, 19)).date(),
            strike=135.0,
            delta=0.38,
            bid_ask_spread_pct=4.8,
        ),
        rationale="SMH leading, NVDA RS vs QQQ positive, prior breakout retest holding",
        confidence=0.81,
        status=SignalStatus.PENDING,
        risk_class=RiskClass.STANDARD,
        reason_codes=["RS_POS", "SECTOR_LEAD", "RETEST_HOLD"],
    )
    payload = json.loads(s.model_dump_json())
    assert payload["symbol"] == "NVDA"
    assert payload["setup_type"] == "B_breakout_retest"


def test_mock_providers_satisfy_protocols() -> None:
    assert isinstance(MockMarketDataProvider(), MarketDataProvider)
    assert isinstance(MockOptionsDataProvider(), OptionsDataProvider)
    assert isinstance(MockEventsProvider(), EventsProvider)


@pytest.mark.asyncio
async def test_mock_market_data_returns_candles() -> None:
    p = MockMarketDataProvider()
    end = datetime(2026, 5, 19, 20, 0, tzinfo=UTC)
    start = end - timedelta(days=90)
    series = await p.get_ohlcv("UPTRD", Timeframe.D1, start, end)
    assert series.candles, "expected non-empty synthetic series"
    quote = await p.get_latest_quote("UPTRD")
    assert quote.close > 0


@pytest.mark.asyncio
async def test_mock_option_chain_contains_illiquid_contract() -> None:
    p = MockOptionsDataProvider()
    chain = await p.get_option_chain("UPTRD")
    # At least one contract should clearly fail §7 spread/OI rules.
    bad = [c for c in chain.contracts if (c.spread_pct or 0) > 50 or c.open_interest < 100]
    assert bad, "fixture should include an explicitly illiquid contract"


def test_enum_completeness() -> None:
    assert {r.value for r in RegimeType} == {"long_bias", "short_bias", "mixed", "no_trade"}
    assert len(list(SetupType)) == 6


# Sanity check that the Repository protocol is well-formed (no instantiation).
def test_repository_protocol_attrs() -> None:
    expected = {
        "upsert_candles",
        "get_candles",
        "save_regime",
        "latest_regime",
        "save_sector_scores",
        "latest_sector_scores",
        "save_symbol_scores",
        "latest_symbol_scores",
        "save_signal",
        "get_signal",
        "open_signals",
        "append_signal_event",
        "list_signal_events",
    }
    assert expected.issubset(set(dir(Repository)))


def test_alert_sink_protocol_attrs() -> None:
    assert "send" in dir(AlertSink)
