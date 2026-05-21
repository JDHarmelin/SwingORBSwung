"""Core scan pipeline — regime → rank → detect → contract → alert → persist."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from trading_engine.alerts.dedupe import AlertDeduper
from trading_engine.alerts.formatter import format_signal
from trading_engine.core.config import AppConfig, load_app_config
from trading_engine.core.interfaces import AlertSink, Repository
from trading_engine.core.types import RegimeType, Timeframe
from trading_engine.data.factory import ProviderBundle
from trading_engine.data.universe import resolve_scan_symbols
from trading_engine.risk.contract_selector import select_contract
from trading_engine.risk.risk_class import classify_risk
from trading_engine.scanners.market_regime import compute_market_regime
from trading_engine.scanners.sector_rank import rank_sectors
from trading_engine.scanners.stock_ranker import rank_stocks
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
    ) -> None:
        self._providers = providers
        self._repo = repo
        self._alerts = alerts
        self._config = config or load_app_config()
        window = timedelta(minutes=self._config.settings.alerts.dedupe_window_minutes)
        self._deduper = deduper or AlertDeduper(window=window)

    async def scan_once(
        self,
        symbols: list[str] | None = None,
        *,
        filter_liquidity: bool = False,
    ) -> list[str]:
        """Run one full scan tick; return signal_ids created."""
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
                    key = f"{signal.signal_id}:{signal.status.value}"
                    if self._deduper.should_send(key):
                        await self._alerts.send(format_signal(signal), dedupe_key=key)
                    created.append(signal.signal_id)
        return created
