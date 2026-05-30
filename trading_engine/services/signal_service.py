"""End-to-end signal pipeline (spec §6 → §10) — execution-only.

Two-phase flow:

1. ``run_pipeline()`` — generates and **persists candidates silently** (no
   Telegram). Idempotent: deterministic signal_ids mean re-scans upsert.
2. ``confirm_and_alert(gate)`` — loops PENDING candidates, runs the
   ``ConfirmationGate``, and fires Telegram only for confirmed ones (flipping
   status to TRIGGERED).

Lifecycle helpers:
- ``expire_stale_candidates()`` — PENDINGs older than the configured TTL move
  to EXPIRED_RISK so the backlog can't grow forever.
- ``track_outcomes()`` — simulates each candidate forward on its underlying
  and records a ``paper_outcome`` event (idempotent). Builds the learning log.

All I/O goes through the provider, repo, and alert sink protocols.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from trading_engine.alerts.formatter import (
    coalesce_signals,
    coalesced_dedupe_key,
    format_signal,
)
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
    SignalEvent,
    SignalStatus,
    SymbolScore,
    Timeframe,
)
from trading_engine.features.sector_rank import rank_sectors
from trading_engine.risk.contract_selector import select_contract_with_diagnostics
from trading_engine.risk.trade_management import build_target_plan, classify_risk
from trading_engine.scanners.market_regime import (
    RegimeInputs,
    classify_regime,
    regime_allows,
)
from trading_engine.scanners.stock_ranker import SymbolRankInputs, rank_symbols
from trading_engine.scanners.universe_builder import build_universe, tradable_symbols
from trading_engine.services.confirmation import ConfirmationGate
from trading_engine.services.paper_tracker import (
    record_outcome,
    simulate_outcome,
)
from trading_engine.setups import EQUITY_DETECTORS, INDEX_DETECTORS
from trading_engine.setups.base import SetupContext

log = logging.getLogger(__name__)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def liquidity_key(risk_class_value: str, *, day_trade: bool) -> str:
    """Resolve the liquidity-override key.

    Index-tactical day-trades classify as ``risk_class=STANDARD`` but need the
    looser ``day_trade`` option floor (short-dated weeklies have thin OI/vol).
    The day_trade flag therefore takes priority over the risk class so the
    override actually applies instead of silently falling back to STANDARD.
    """
    return "day_trade" if day_trade else risk_class_value


@dataclass
class PipelineResult:
    as_of: datetime
    regime_notes: list[str] = field(default_factory=list)
    tradable: list[str] = field(default_factory=list)
    sector_scores: list[SectorScore] = field(default_factory=list)
    symbol_scores: list[SymbolScore] = field(default_factory=list)
    candidates: list[Signal] = field(default_factory=list)


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
    # TTL helpers (public — MCP bridge / tests poke them)
    # ------------------------------------------------------------------
    @property
    def candidate_ttl_hours(self) -> int:
        return self.settings.execution.candidate_ttl_hours

    def _candidate_ttl(self) -> timedelta:
        return timedelta(hours=self.candidate_ttl_hours)

    def is_stale(self, signal: Signal, *, now: datetime | None = None) -> bool:
        """True if a candidate is past its TTL."""
        now = now or datetime.now(tz=UTC)
        return (now - _aware(signal.timestamp)) > self._candidate_ttl()

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
    # Phase 1: generate candidates silently
    # ------------------------------------------------------------------
    async def run_pipeline(self, as_of: datetime) -> PipelineResult:
        """Detect candidates and persist them; **does not alert.**"""
        result = PipelineResult(as_of=as_of)
        cfg = self.settings

        # 1. Index data + regime.
        index_daily = await self._fetch_daily(cfg.regime.index_symbols, as_of)
        index_intraday = await self._fetch_intraday(cfg.regime.index_symbols, as_of)
        regime_inputs = [
            RegimeInputs(
                symbol=s,
                daily=index_daily[s],
                # Only use intraday if it has bars (provider may return empty).
                intraday=index_intraday.get(s)
                if index_intraday.get(s) and index_intraday[s].candles
                else None,
            )
            for s in cfg.regime.index_symbols
            if s in index_daily and index_daily[s].candles
        ]
        if not regime_inputs:
            log.warning("no index data — cannot classify regime; aborting pipeline")
            return result
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
        sector_composite_by_name: dict[str, float] = {}
        spy = index_daily.get("SPY")
        if spy is not None and spy.candles:
            sector_series = await self._fetch_daily(list(self.universe.sector_etfs.values()), as_of)
            etf_to_name = {etf: name for name, etf in self.universe.sector_etfs.items()}
            sector_input = {
                etf_to_name[etf]: series
                for etf, series in sector_series.items()
                if etf in etf_to_name and series.candles
            }
            sector_scores = rank_sectors(sector_input, spy, as_of=as_of)
            await self.repo.save_sector_scores(sector_scores)
            result.sector_scores = sector_scores
            sector_composite_by_name = {s.sector: s.composite_score for s in sector_scores}

        # 4. Stock ranking — RS vs SPY/QQQ (skip benchmarks the provider couldn't supply).
        benchmarks_daily = {
            s: index_daily[s]
            for s in ("SPY", "QQQ")
            if s in index_daily and index_daily[s].candles
        }
        if not benchmarks_daily:
            log.warning("no benchmark daily series — skipping ranker")
            return result
        rank_inputs = [
            SymbolRankInputs(
                symbol=sym,
                daily=equity_daily[sym],
                benchmarks_daily=benchmarks_daily,
                sector_composite=sector_composite_by_name.get(
                    self.universe.symbol_sectors.get(sym, ""), 0.0
                ),
            )
            for sym in result.tradable
        ]
        ranked = rank_symbols(rank_inputs, cfg.factor_weights, as_of=as_of)
        symbol_scores: list[SymbolScore] = [*ranked.longs, *ranked.shorts]
        await self.repo.save_symbol_scores(symbol_scores)
        result.symbol_scores = symbol_scores

        # 5. Setup detection — equity bucket.
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
                sector_composite=sector_composite_by_name.get(
                    self.universe.symbol_sectors.get(score.symbol, ""), 0.0
                ),
                target_plan=build_target_plan(cfg.risk),
            )
            for detector in EQUITY_DETECTORS:
                for sig in detector.detect(ctx):
                    final = await self._persist_candidate(sig, day_trade=False)
                    result.candidates.append(final)

        # 6. Index tactical setups.
        for sym in cfg.regime.index_symbols:
            if sym not in index_daily or not index_daily[sym].candles:
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
                    final = await self._persist_candidate(sig, day_trade=True)
                    result.candidates.append(final)

        return result

    async def _persist_candidate(self, signal: Signal, *, day_trade: bool) -> Signal:
        """Pick a contract, classify risk, save — but don't alert (yet)."""
        cfg = self.settings
        risk_class = classify_risk(signal.confidence, day_trade=day_trade)
        chain = await self.options_data.get_option_chain(signal.symbol)
        contract, diag = select_contract_with_diagnostics(
            chain,
            direction=signal.direction,
            as_of=signal.timestamp.date(),
            contract_cfg=cfg.contract,
            liquidity=cfg.liquidity.for_risk_class(
                liquidity_key(risk_class.value, day_trade=day_trade)
            ),
            risk_class=risk_class,
            day_trade=day_trade,
        )
        log.info(
            "contract_select symbol=%s chain=%d type_ok=%d dte_ok=%d "
            "liq_ok=%d delta_ok=%d picked=%s rejects=%s",
            signal.symbol,
            diag.chain_size,
            diag.after_type,
            diag.after_dte,
            diag.after_liquidity,
            diag.after_delta,
            "yes" if contract is not None else "no",
            dict(diag.rejection_reasons),
        )
        # When nothing was picked, stash a short diagnostic on the signal so
        # the operator can see the "why" in the alert / DB row instead of just
        # the generic "Awaiting chain — no liquid contract found" footer.
        extra_codes: list[str] = []
        if contract is None:
            extra_codes.append(f"contract_unavailable: {diag.short_reason()}")
        final = signal.model_copy(
            update={
                "contract": contract,
                "risk_class": risk_class,
                "reason_codes": [*signal.reason_codes, *extra_codes],
            }
        )
        await self.repo.save_signal(final)
        return final

    # ------------------------------------------------------------------
    # Phase 2: confirm + alert
    # ------------------------------------------------------------------
    async def confirm_and_alert(
        self, gate: ConfirmationGate, *, now: datetime | None = None
    ) -> list[Signal]:
        """Run the gate over open PENDING candidates; alert + flip status for
        the ones the gate confirms. Stale candidates are skipped (and should be
        cleaned up via ``expire_stale_candidates`` on the next tick).

        ``now`` is exposed for deterministic tests; production callers omit it.
        """
        alerted: list[Signal] = []
        now = now or datetime.now(tz=UTC)
        triggered_signals: list[Signal] = []
        for signal in await self.repo.open_signals():
            if signal.status is not SignalStatus.PENDING:
                continue
            if self.is_stale(signal, now=now):
                continue
            decision = await gate.assess(signal)
            if not decision.confirmed:
                continue
            triggered = signal.model_copy(
                update={
                    "status": SignalStatus.TRIGGERED,
                    "confidence": decision.confidence,
                    "reason_codes": [*signal.reason_codes, *decision.reason_codes],
                }
            )
            await self.repo.save_signal(triggered)
            await self.repo.append_signal_event(
                SignalEvent(
                    signal_id=triggered.signal_id,
                    event_timestamp=now,
                    event_type="triggered",
                    event_payload={"trigger": triggered.trigger_price},
                )
            )
            triggered_signals.append(triggered)

        # Coalesce concurrent setups on the same (ticker, bias, bar) so the
        # operator sees a single alert with companion signals listed.
        pairs = list(coalesce_signals(triggered_signals))

        # Outbound-alert gating (noise control). Signals are already TRIGGERED
        # + persisted above so paper tracking keeps working — the floor/cap only
        # decides what actually goes out over the wire.
        exec_cfg = getattr(self.settings, "execution", None)
        floor = getattr(exec_cfg, "min_alert_confidence", 0.70)
        cap = getattr(exec_cfg, "max_alerts_per_tick", 5)
        passed_floor = [p for p in pairs if p[0].confidence >= floor]
        passed_floor.sort(key=lambda pc: pc[0].confidence, reverse=True)
        to_send = passed_floor[:cap]
        log.info(
            "alert_gate: triggered=%d passed_floor=%d sent=%d (floor=%.2f cap=%d)",
            len(triggered_signals),
            len(passed_floor),
            len(to_send),
            floor,
            cap,
        )

        for primary, companions in to_send:
            await self.alerts.send(
                format_signal(primary, companions=companions),
                dedupe_key=coalesced_dedupe_key(primary, companions),
            )
            alerted.append(primary)
        return alerted

    # ------------------------------------------------------------------
    # Lifecycle hygiene
    # ------------------------------------------------------------------
    async def expire_stale_candidates(self) -> list[str]:
        """Move PENDING candidates older than TTL to EXPIRED_RISK. Returns ids."""
        now = datetime.now(tz=UTC)
        expired: list[str] = []
        for signal in await self.repo.open_signals():
            if signal.status is not SignalStatus.PENDING or not self.is_stale(signal, now=now):
                continue
            age_h = (now - _aware(signal.timestamp)).total_seconds() / 3600.0
            await self.repo.save_signal(
                signal.model_copy(update={"status": SignalStatus.EXPIRED_RISK})
            )
            await self.repo.append_signal_event(
                SignalEvent(
                    signal_id=signal.signal_id,
                    event_timestamp=now,
                    event_type="expired_candidate",
                    event_payload={
                        "symbol": signal.symbol,
                        "age_hours": round(age_h, 2),
                        "ttl_hours": self.candidate_ttl_hours,
                    },
                )
            )
            expired.append(signal.signal_id)
        return expired

    async def has_open_work(self) -> bool:
        """True if any signal still needs ticks (PENDING candidate awaiting
        confirm/expiry, or triggered paper signal awaiting an outcome).

        Lets the scheduler skip the entire track_outcomes + management leg on
        market-closed ticks when there's nothing to advance — those paths
        otherwise fan out OHLCV + chain fetches per symbol with no output.
        """
        for signal in await self.repo.open_signals():
            if signal.status is SignalStatus.PENDING:
                return True
            events = await self.repo.list_signal_events(signal.signal_id)
            if not any(e.event_type == "paper_outcome" for e in events):
                return True
        return False

    async def track_outcomes(
        self, as_of: datetime, *, min_age_minutes: int = 15
    ) -> list[str]:
        """Simulate each candidate forward on its underlying; record a
        ``paper_outcome`` event the first time it has terminal information.

        Idempotent — an existing paper_outcome short-circuits. Candidates
        younger than ``min_age_minutes`` are skipped (nothing forward to
        simulate yet; also avoids degenerate zero-length data fetches).
        """
        recorded: list[str] = []
        min_age = timedelta(minutes=min_age_minutes)
        for signal in await self.repo.open_signals():
            sig_ts = _aware(signal.timestamp)
            if as_of - sig_ts < min_age:
                continue
            # Already recorded?
            events = await self.repo.list_signal_events(signal.signal_id)
            if any(e.event_type == "paper_outcome" for e in events):
                continue
            series = await self.market_data.get_ohlcv(
                signal.symbol, Timeframe.M5, sig_ts, as_of,
            )
            if not series.candles:
                continue  # provider couldn't supply data; try again next tick
            outcome = simulate_outcome(
                signal, series, rr=self.settings.execution.paper_rr
            )
            # Only record terminal outcomes ('open' stays open until resolved).
            if outcome.result == "open":
                continue
            if await record_outcome(self.repo, signal, outcome, at=as_of):
                recorded.append(signal.signal_id)
        return recorded


__all__ = ["PipelineResult", "SignalService"]
