"""Core scan pipeline — regime → rank → detect → contract → persist → confirm → alert.

Two-phase, execution-only model:
- ``scan_once`` generates and persists *candidates* (no alert by default).
- ``confirm_and_alert`` runs a ConfirmationGate over open candidates and alerts
  ONLY the ones that have reached their execution moment (Hermes plugs in here).
- ``track_outcomes`` paper-tracks every candidate to a result (the learning log).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from trading_engine.alerts.dedupe import AlertDeduper
from trading_engine.alerts.formatter import format_signal
from trading_engine.core.config import AppConfig, load_app_config
from trading_engine.core.interfaces import AlertSink, Repository
from trading_engine.core.types import RegimeType, SignalEvent, SignalStatus, Timeframe
from trading_engine.data.factory import ProviderBundle
from trading_engine.data.universe import resolve_scan_symbols
from trading_engine.risk.contract_selector import select_contract
from trading_engine.risk.risk_class import classify_risk
from trading_engine.scanners.market_regime import compute_market_regime
from trading_engine.scanners.sector_rank import rank_sectors
from trading_engine.scanners.stock_ranker import rank_stocks
from trading_engine.services.confirmation import ConfirmationGate
from trading_engine.services.paper_tracker import (
    TERMINAL_RESULTS,
    record_outcome,
    simulate_outcome,
)
from trading_engine.setups.base import SetupContext
from trading_engine.setups.registry import all_setups

logger = logging.getLogger(__name__)


class SignalService:
    def __init__(
        self,
        providers: ProviderBundle,
        repo: Repository,
        alerts: AlertSink,
        *,
        config: AppConfig | None = None,
        deduper: AlertDeduper | None = None,
        gate: ConfirmationGate | None = None,
    ) -> None:
        self._providers = providers
        self._repo = repo
        self._alerts = alerts
        self._config = config or load_app_config()
        window = timedelta(minutes=self._config.settings.alerts.dedupe_window_minutes)
        self._deduper = deduper or AlertDeduper(window=window)
        self._gate = gate

    async def scan_once(
        self,
        symbols: list[str] | None = None,
        *,
        filter_liquidity: bool = False,
        alert_candidates: bool = True,
    ) -> list[str]:
        """Run one full scan tick; persist candidates and return their signal_ids.

        ``alert_candidates=True`` (legacy default) alerts on every candidate.
        Set it ``False`` for the execution-only flow, then call
        ``confirm_and_alert`` to alert only confirmed setups.
        """
        config = self._config
        market = self._providers.market
        options = self._providers.options
        events = self._providers.events

        regime = await compute_market_regime(market, events)
        await self._repo.save_regime(regime)
        if regime.regime == RegimeType.NO_TRADE:
            logger.info("no_trade regime — skipping setups")
            return []

        sectors = await rank_sectors(market, config=config)
        await self._repo.save_sector_scores(sectors)

        syms = symbols
        if syms is None:
            syms = await resolve_scan_symbols(
                market,
                options,
                config=config,
                filter_liquidity=filter_liquidity,
            )
        if not syms:
            logger.warning("empty scan universe — check config/universe.yaml or filters")
            return []
        logger.info("scanning %d symbols", len(syms))
        buckets = await rank_stocks(market, syms, sectors, config=config)
        await self._repo.save_symbol_scores(buckets.longs + buckets.shorts)

        ranked_symbols = {s.symbol for s in buckets.longs} | {s.symbol for s in buckets.shorts}
        score_map = {s.symbol: s for s in buckets.longs + buckets.shorts}
        created: list[str] = []
        now = datetime.now(tz=UTC)
        start = now - timedelta(days=60)

        for sym in ranked_symbols:
            score = score_map.get(sym)
            if score is None:
                continue
            daily = await market.get_ohlcv(sym, Timeframe.D1, start, now)
            intraday = await market.get_ohlcv(sym, Timeframe.M5, now - timedelta(days=1), now)
            chain = await options.get_option_chain(sym)
            ctx = SetupContext(
                symbol=sym,
                candles={Timeframe.D1.value: daily, Timeframe.M5.value: intraday},
                regime=regime,
                symbol_score=score,
                option_chain=chain,
            )
            for detector in all_setups():
                for signal in detector.detect(ctx):
                    contract = select_contract(signal, chain, config=config)
                    if contract is None:
                        logger.debug("no liquid contract for %s", sym)
                        continue
                    signal.contract = contract
                    signal.risk_class = classify_risk(signal)
                    await self._repo.save_signal(signal)
                    if alert_candidates:
                        key = f"{signal.signal_id}:{signal.status.value}"
                        if self._deduper.should_send(key):
                            await self._alerts.send(format_signal(signal), dedupe_key=key)
                    created.append(signal.signal_id)
        return created

    async def confirm_and_alert(self) -> list[str]:
        """Assess open candidates; mark + alert only those confirmed for execution.

        This is the execution-only gate: Telegram fires here, not on candidate
        generation. With no gate configured, nothing fires (candidates wait).
        """
        if self._gate is None:
            return []
        confirmed: list[str] = []
        for signal in await self._repo.open_signals():
            if signal.status != SignalStatus.PENDING:
                continue
            decision = await self._gate.assess(signal)
            if not decision.confirmed:
                continue
            signal.status = SignalStatus.TRIGGERED
            await self._repo.save_signal(signal)
            await self._repo.append_signal_event(
                SignalEvent(
                    signal_id=signal.signal_id,
                    event_timestamp=datetime.now(tz=UTC),
                    event_type="triggered",
                    event_payload={
                        "symbol": signal.symbol,
                        "price": signal.trigger_price,
                        "reason_codes": decision.reason_codes,
                    },
                )
            )
            key = f"{signal.signal_id}:{signal.status.value}"
            if self._deduper.should_send(key):
                await self._alerts.send(format_signal(signal), dedupe_key=key)
            confirmed.append(signal.signal_id)
        return confirmed

    async def track_outcomes(self, *, lookback_days: int = 60) -> list[str]:
        """Paper-track open candidates to a terminal result and log it.

        Idempotent: skips signals that already have a ``paper_outcome`` event.
        Returns the signal_ids newly recorded. This is the learning log Hermes
        will train its confidence model on.
        """
        now = datetime.now(tz=UTC)
        start = now - timedelta(days=lookback_days)
        recorded: list[str] = []
        for signal in await self._repo.open_signals():
            events = await self._repo.list_signal_events(signal.signal_id)
            if any(e.event_type == "paper_outcome" for e in events):
                continue
            series = await self._providers.market.get_ohlcv(signal.symbol, Timeframe.D1, start, now)
            outcome = simulate_outcome(signal, series)
            if outcome.result in TERMINAL_RESULTS:
                await record_outcome(self._repo, outcome)
                recorded.append(signal.signal_id)
        return recorded
