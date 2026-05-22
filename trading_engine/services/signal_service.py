"""End-to-end signal pipeline (spec §6 → §10).

regime → sector rank → stock rank → setup detection → contract selection →
risk classification → persistence → alert dispatch.

Pure async orchestration; all I/O goes through the provider, repo, and alert
sink protocols so it can be wired against mocks or live infra.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from trading_engine.alerts.formatter import dedupe_key, format_signal
from trading_engine.core.config import Settings, Universe
from trading_engine.core.interfaces import (
    AlertSink,
    EventsProvider,
    MarketDataProvider,
    OptionsDataProvider,
    Repository,
)
from trading_engine.core.types import (
    Direction,
    OHLCVSeries,
    SectorScore,
    Signal,
    SymbolScore,
    Timeframe,
)
from trading_engine.features.sector_rank import rank_sectors
from trading_engine.risk.contract_selector import select_contract
from trading_engine.risk.trade_management import build_target_plan, classify_risk
from trading_engine.scanners.market_regime import (
    RegimeInputs,
    classify_regime,
    regime_allows,
)
from trading_engine.scanners.stock_ranker import SymbolRankInputs, rank_symbols
from trading_engine.scanners.universe_builder import build_universe, tradable_symbols
from trading_engine.setups import EQUITY_DETECTORS, INDEX_DETECTORS
from trading_engine.setups.base import SetupContext

log = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    as_of: datetime
    regime_notes: list[str] = field(default_factory=list)
    tradable: list[str] = field(default_factory=list)
    sector_scores: list[SectorScore] = field(default_factory=list)
    symbol_scores: list[SymbolScore] = field(default_factory=list)
    signals: list[Signal] = field(default_factory=list)


class SignalService:
    """Pipeline driver. Stateless apart from the injected collaborators."""

    def __init__(
        self,
        *,
        settings: Settings,
        universe: Universe,
        market_data: MarketDataProvider,
        options_data: OptionsDataProvider,
        events: EventsProvider,
        repo: Repository,
        alerts: AlertSink,
    ) -> None:
        self.settings = settings
        self.universe = universe
        self.market_data = market_data
        self.options_data = options_data
        self.events = events
        self.repo = repo
        self.alerts = alerts

    # ------------------------------------------------------------------
    # Data fetch
    # ------------------------------------------------------------------
    async def _fetch_daily(
        self, symbols: list[str], end: datetime, days: int = 90
    ) -> dict[str, OHLCVSeries]:
        start = end - timedelta(days=days)
        out: dict[str, OHLCVSeries] = {}
        for sym in symbols:
            out[sym] = await self.market_data.get_ohlcv(sym, Timeframe.D1, start, end)
        return out

    async def _fetch_intraday(
        self, symbols: list[str], end: datetime, bars: int = 120
    ) -> dict[str, OHLCVSeries]:
        # 120 × 5m ≈ 10 hours — enough for a session.
        start = end - timedelta(minutes=5 * bars)
        out: dict[str, OHLCVSeries] = {}
        for sym in symbols:
            out[sym] = await self.market_data.get_ohlcv(sym, Timeframe.M5, start, end)
        return out

    # ------------------------------------------------------------------
    # Pipeline
    # ------------------------------------------------------------------
    async def run_pipeline(self, as_of: datetime) -> PipelineResult:
        result = PipelineResult(as_of=as_of)
        cfg = self.settings

        # 1. Index data + regime.
        index_daily = await self._fetch_daily(cfg.regime.index_symbols, as_of)
        index_intraday = await self._fetch_intraday(cfg.regime.index_symbols, as_of)
        regime_inputs = [
            RegimeInputs(symbol=s, daily=index_daily[s], intraday=index_intraday.get(s))
            for s in cfg.regime.index_symbols
            if s in index_daily
        ]
        regime = classify_regime(
            regime_inputs,
            as_of=as_of,
            block_if_event_within_hours=cfg.regime.block_if_event_within_hours,
        )
        await self.repo.save_regime(regime)
        result.regime_notes = list(regime.notes)
        log.info("regime: %s (conf %.2f)", regime.regime.value, regime.confidence)
        if regime.regime.value == "no_trade":
            return result  # non-negotiable: never alert in no-trade

        # 2. Universe + liquidity filter.
        equity_daily = await self._fetch_daily(self.universe.symbols, as_of)
        entries = build_universe(equity_daily, cfg.liquidity)
        result.tradable = tradable_symbols(entries)
        if not result.tradable:
            return result

        # 3. Sector ranking (SPY as benchmark).
        spy = index_daily.get("SPY")
        if spy is not None:
            sector_series = await self._fetch_daily(list(self.universe.sector_etfs.values()), as_of)
            etf_to_name = {etf: name for name, etf in self.universe.sector_etfs.items()}
            sector_input = {
                etf_to_name[etf]: series for etf, series in sector_series.items() if etf in etf_to_name
            }
            sector_scores = rank_sectors(sector_input, spy, as_of=as_of)
            await self.repo.save_sector_scores(sector_scores)
            result.sector_scores = sector_scores

        # 4. Stock ranking — RS vs SPY/QQQ.
        benchmarks_daily = {s: index_daily[s] for s in ("SPY", "QQQ") if s in index_daily}
        if not benchmarks_daily:
            log.warning("no benchmark daily series — skipping ranker")
            return result
        rank_inputs = [
            SymbolRankInputs(
                symbol=sym,
                daily=equity_daily[sym],
                benchmarks_daily=benchmarks_daily,
                sector_composite=0.0,  # symbol→sector map not in universe yet
            )
            for sym in result.tradable
        ]
        ranked = rank_symbols(rank_inputs, cfg.factor_weights, as_of=as_of)
        symbol_scores: list[SymbolScore] = [*ranked.longs, *ranked.shorts]
        await self.repo.save_symbol_scores(symbol_scores)
        result.symbol_scores = symbol_scores

        # 5. Setup detection on the ranked candidates.
        intraday_candidates = await self._fetch_intraday(result.tradable, as_of)
        scores_by_symbol = {s.symbol: s for s in symbol_scores}
        for score in symbol_scores:
            if score.direction_bucket is Direction.SHORT and not regime_allows(regime, want_short=True):
                continue
            if score.direction_bucket is Direction.LONG and not regime_allows(regime, want_short=False):
                continue
            ctx = SetupContext(
                symbol=score.symbol,
                as_of=as_of,
                daily=equity_daily[score.symbol],
                intraday=intraday_candidates.get(score.symbol),
                regime=regime,
                symbol_score=score,
                sector_composite=0.0,
                target_plan=build_target_plan(cfg.risk),
            )
            for detector in EQUITY_DETECTORS:
                signals = detector.detect(ctx)
                for sig in signals:
                    await self._finalise_and_dispatch(sig, day_trade=False)
                    result.signals.append(sig)

        # 6. Index tactical setups.
        for sym in cfg.regime.index_symbols:
            if sym not in index_daily:
                continue
            ctx = SetupContext(
                symbol=sym,
                as_of=as_of,
                daily=index_daily[sym],
                intraday=index_intraday.get(sym),
                regime=regime,
                symbol_score=scores_by_symbol.get(sym),
                sector_composite=0.0,
                is_index=True,
                target_plan=build_target_plan(cfg.risk),
            )
            for detector in INDEX_DETECTORS:
                for sig in detector.detect(ctx):
                    await self._finalise_and_dispatch(sig, day_trade=True)
                    result.signals.append(sig)

        return result

    # ------------------------------------------------------------------
    # Per-signal finalisation
    # ------------------------------------------------------------------
    async def _finalise_and_dispatch(self, signal: Signal, *, day_trade: bool) -> None:
        cfg = self.settings
        # Risk classification.
        risk_class = classify_risk(signal.confidence, day_trade=day_trade)
        # Contract selection (skip on no-options index, which still has chains).
        chain = await self.options_data.get_option_chain(signal.symbol)
        contract = select_contract(
            chain,
            direction=signal.direction,
            as_of=signal.timestamp.date(),
            contract_cfg=cfg.contract,
            liquidity=cfg.liquidity,
            risk_class=risk_class,
            day_trade=day_trade,
        )
        final = signal.model_copy(
            update={"contract": contract, "risk_class": risk_class}
        )
        await self.repo.save_signal(final)
        await self.alerts.send(format_signal(final), dedupe_key=dedupe_key(final))


__all__ = ["PipelineResult", "SignalService"]
