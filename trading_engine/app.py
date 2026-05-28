"""CLI entrypoint.

Subcommands:
- ``regime``     — classify the current regime and print its notes.
- ``rank``       — print top long/short candidate scores.
- ``scan-once``  — generate and persist candidates silently (no alerts).
- ``confirm``    — run the confirmation gate over open candidates; alert only
                    the confirmed ones.
- ``run``        — full execution-only loop: expire → generate → confirm + alert
                    → track outcomes → management tick.

Provider/sink wiring via ``--provider`` and ``--sink``. ``--provider mock`` uses
synthetic fixtures (no API keys); ``--sink telegram`` requires
``TELEGRAM_BOT_TOKEN`` / ``TELEGRAM_CHAT_ID`` (from the project ``.env``,
auto-loaded). ``--gate`` selects the confirmation gate (``price_cross`` for
mechanical trigger detection, ``always_on`` for tests).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import UTC, datetime
from typing import Literal

from trading_engine.alerts.sinks import ConsoleAlertSink, InMemoryAlertSink, TelegramAlertSink
from trading_engine.core.config import AppConfig, load_app_config
from trading_engine.core.interfaces import (
    AlertSink,
    EventsProvider,
    MarketDataProvider,
    OptionsDataProvider,
    Repository,
)
from trading_engine.data.mock_provider import (
    MockEventsProvider,
    MockMarketDataProvider,
    MockOptionsDataProvider,
)
from trading_engine.data.chained_options import ChainedOptionsDataProvider
from trading_engine.data.polygon import (
    PolygonEventsProvider,
    PolygonMarketDataProvider,
    PolygonOptionsDataProvider,
)
from trading_engine.data.yfinance_options import YFinanceOptionsDataProvider
from trading_engine.core.types import Timeframe
from trading_engine.services.backfill import backfill_universe
from trading_engine.services.confirmation import (
    AlwaysOnGate,
    ConfirmationGate,
    PriceCrossConfirmationGate,
)
from trading_engine.services.backtest import (
    Backtester,
    format_summary,
    load_history_from_cache,
    summarize,
    write_csv,
)
from trading_engine.services.management_service import ManagementService
from trading_engine.services.scheduler import run_loop, run_tick
from trading_engine.services.signal_service import SignalService
from trading_engine.storage import InMemoryRepository, SqlRepository

log = logging.getLogger("trading_engine")


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------


def _make_providers(
    kind: Literal["mock", "polygon"], cfg: AppConfig
) -> tuple[MarketDataProvider, OptionsDataProvider, EventsProvider]:
    if kind == "mock":
        return MockMarketDataProvider(), MockOptionsDataProvider(), MockEventsProvider()
    if kind == "polygon":
        key = cfg.secrets.polygon_api_key
        if not key:
            raise SystemExit("POLYGON_API_KEY must be set for --provider polygon")
        # Stock Starter has no options entitlement; fall through to yfinance
        # (free, ~15-min delayed) when Polygon returns an empty chain. If a
        # paid Polygon options upgrade lands later, it'll win automatically.
        options = ChainedOptionsDataProvider(
            [PolygonOptionsDataProvider(key), YFinanceOptionsDataProvider()],
            names=["polygon", "yfinance"],
        )
        return (
            PolygonMarketDataProvider(key),
            options,
            PolygonEventsProvider(key),
        )
    raise ValueError(f"unknown provider kind: {kind}")


def _make_sink(kind: Literal["console", "memory", "telegram"], cfg: AppConfig) -> AlertSink:
    if kind == "console":
        return ConsoleAlertSink()
    if kind == "memory":
        return InMemoryAlertSink()
    if kind == "telegram":
        token = cfg.secrets.telegram_bot_token
        chat = cfg.secrets.telegram_chat_id
        if not token or not chat:
            raise SystemExit("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set for --sink telegram")
        return TelegramAlertSink(token, chat)
    raise ValueError(f"unknown sink kind: {kind}")


def _make_repo(kind: Literal["memory", "sqlite"], cfg: AppConfig) -> Repository:
    if kind == "memory":
        return InMemoryRepository()
    if kind == "sqlite":
        return SqlRepository(cfg.secrets.database_url)
    raise ValueError(f"unknown repo kind: {kind}")


def _make_gate(
    kind: Literal["price_cross", "always_on"], market: MarketDataProvider
) -> ConfirmationGate:
    if kind == "always_on":
        return AlwaysOnGate()
    return PriceCrossConfirmationGate(market)


def _build_service(
    args: argparse.Namespace,
) -> tuple[SignalService, ManagementService, ConfirmationGate, AlertSink]:
    cfg = load_app_config()
    providers = _make_providers(args.provider, cfg)
    sink = _make_sink(args.sink, cfg)
    repo = _make_repo(args.repo, cfg)
    gate = _make_gate(getattr(args, "gate", "price_cross"), providers[0])
    signal_service = SignalService(
        settings=cfg.settings,
        universe=cfg.universe,
        market_data=providers[0],
        options_data=providers[1],
        events=providers[2],
        repo=repo,
        alerts=sink,
    )
    management_service = ManagementService(options_data=providers[1], repo=repo, alerts=sink)
    return signal_service, management_service, gate, sink


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------


async def cmd_regime(args: argparse.Namespace) -> int:
    signal_service, _mgmt, _gate, _sink = _build_service(args)
    result = await signal_service.run_pipeline(datetime.now(tz=UTC))
    print("Regime notes:")
    for note in result.regime_notes:
        print(f"  - {note}")
    return 0


async def cmd_rank(args: argparse.Namespace) -> int:
    signal_service, _mgmt, _gate, _sink = _build_service(args)
    result = await signal_service.run_pipeline(datetime.now(tz=UTC))
    longs = [s for s in result.symbol_scores if s.direction_bucket.value == "long"]
    shorts = [s for s in result.symbol_scores if s.direction_bucket.value == "short"]
    print(f"Top {min(10, len(longs))} long candidates:")
    for s in longs[:10]:
        print(f"  {s.symbol:<6} composite={s.composite_score:+.2f}  {'; '.join(s.reason_codes[:3])}")
    print(f"Top {min(10, len(shorts))} short candidates:")
    for s in shorts[:10]:
        print(f"  {s.symbol:<6} composite={s.composite_score:+.2f}  {'; '.join(s.reason_codes[:3])}")
    return 0


async def cmd_scan_once(args: argparse.Namespace) -> int:
    """Generate candidates silently — no alerts. Run ``confirm`` to fire."""
    signal_service, _mgmt, _gate, _sink = _build_service(args)
    result = await signal_service.run_pipeline(datetime.now(tz=UTC))
    print(f"Persisted {len(result.candidates)} candidate(s). No alerts dispatched (use `confirm`).")
    for c in result.candidates[:10]:
        print(f"  {c.symbol:<6} {c.setup_type.value:<26} {c.direction.value:<6} trigger={c.trigger_price:.2f}")
    return 0


async def cmd_confirm(args: argparse.Namespace) -> int:
    """Run the gate over open candidates and alert the confirmed ones."""
    signal_service, _mgmt, gate, _sink = _build_service(args)
    alerted = await signal_service.confirm_and_alert(gate)
    print(f"Confirmed + alerted {len(alerted)} signal(s).")
    return 0


async def cmd_run(args: argparse.Namespace) -> int:
    signal_service, mgmt, gate, _sink = _build_service(args)
    market_hours_only = getattr(args, "market_hours_only", False)
    if args.iterations is not None and args.iterations <= 1:
        await run_tick(signal_service, mgmt, gate, market_hours_only=market_hours_only)
        return 0
    await run_loop(
        signal_service,
        mgmt,
        gate,
        interval_seconds=args.interval,
        iterations=args.iterations,
        market_hours_only=market_hours_only,
    )
    return 0


async def cmd_wallet(args: argparse.Namespace) -> int:
    """Read-only paper-wallet P&L summary from recorded paper_outcome events."""
    cfg = load_app_config()
    repo = _make_repo(args.repo, cfg)
    outcomes = await repo.all_paper_outcomes()
    print(render_wallet(outcomes, cfg, starting_balance=args.starting_balance))
    return 0


def render_wallet(
    outcomes: list[dict], cfg: AppConfig, *, starting_balance: float = 10_000.0
) -> str:
    """Build the wallet P&L report string. Pure — no I/O — so tests can call it."""
    risk_per_trade = cfg.settings.risk.max_loss_dollars.get("standard", 200.0)

    total = len(outcomes)
    triggered = sum(1 for o in outcomes if o.get("triggered"))
    wins = sum(1 for o in outcomes if o.get("result") == "win")
    losses = sum(1 for o in outcomes if o.get("result") == "loss")
    opens = sum(1 for o in outcomes if o.get("result") == "open")
    resolved = wins + losses
    win_rate = (wins / resolved * 100.0) if resolved else 0.0
    total_r = sum(float(o.get("r_multiple") or 0.0) for o in outcomes)
    total_pnl = total_r * risk_per_trade
    ending = starting_balance + total_pnl

    lines = [
        "===== Paper Wallet =====",
        f"  risk per trade:   ${risk_per_trade:,.2f} (standard)",
        f"  starting balance: ${starting_balance:,.2f}",
        f"  total trades:     {total}",
        f"  triggered:        {triggered}",
        f"  win/loss/open:    {wins}/{losses}/{opens}",
        f"  win rate:         {win_rate:.1f}%",
        f"  total R:          {total_r:+.2f}R",
        f"  total P&L:        ${total_pnl:,.2f}",
        f"  ending balance:   ${ending:,.2f}",
        "  per-setup breakdown:",
    ]

    setups: dict[str, list[dict]] = {}
    for o in outcomes:
        setups.setdefault(o.get("setup_type") or "?", []).append(o)
    for setup in sorted(setups):
        rows = setups[setup]
        s_wins = sum(1 for o in rows if o.get("result") == "win")
        s_losses = sum(1 for o in rows if o.get("result") == "loss")
        s_resolved = s_wins + s_losses
        s_wr = (s_wins / s_resolved * 100.0) if s_resolved else 0.0
        s_r = sum(float(o.get("r_multiple") or 0.0) for o in rows)
        lines.append(
            f"    {setup:<26} trades={len(rows):<3} win_rate={s_wr:5.1f}%  total_R={s_r:+.2f}R"
        )
    return "\n".join(lines)


async def cmd_backtest(args: argparse.Namespace) -> int:
    """Replay historical bars through the production pipeline; record outcomes."""
    from datetime import date as _date
    from pathlib import Path

    cfg = load_app_config()
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    start = _date.fromisoformat(args.start)
    end = _date.fromisoformat(args.end)

    history = load_history_from_cache(symbols)
    missing = [s for s in symbols if s not in history]
    if missing:
        log.warning("backtest: no cached history for %s", missing)
    if not history:
        print("No cached history for requested symbols — aborting.")
        return 1

    universe = cfg.universe.model_copy(update={"symbols": list(history.keys())})
    bt = Backtester(
        settings=cfg.settings,
        universe=universe,
        history=history,
        horizon_bars=args.horizon,
    )
    outcomes = await bt.run(symbols=list(history.keys()), start=start, end=end)
    summary = summarize(outcomes)
    out_path = Path(args.out) if args.out else Path("outputs") / f"backtest_{summary.run_id}.csv"
    write_csv(outcomes, out_path)
    print(format_summary(summary))
    print(f"\nWrote {len(outcomes)} rows -> {out_path}")
    return 0


async def cmd_backfill(args: argparse.Namespace) -> int:
    """Pull OHLCV history from the provider into the repo (and cache as a side-effect)."""
    from datetime import date as _date

    cfg = load_app_config()
    providers = _make_providers(args.provider, cfg)
    repo = _make_repo(args.repo, cfg)
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    start = datetime.combine(_date.fromisoformat(args.start), datetime.min.time(), tzinfo=UTC)
    end = datetime.combine(_date.fromisoformat(args.end), datetime.min.time(), tzinfo=UTC)
    tf = Timeframe(args.timeframe)

    result = await backfill_universe(
        providers[0], repo, symbols, tf, start, end, concurrency=args.concurrency
    )
    for sym, series in sorted(result.items()):
        print(f"  {sym:<6} {tf.value:<4} {len(series.candles):>5} candles")
    total = sum(len(s.candles) for s in result.values())
    print(f"\nBackfilled {len(result)} symbol(s), {total} candles total.")
    return 0


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--provider", choices=["mock", "polygon"], default="mock")
    p.add_argument("--sink", choices=["console", "memory", "telegram"], default="console")
    p.add_argument("--repo", choices=["memory", "sqlite"], default="memory")
    p.add_argument(
        "--gate",
        choices=["price_cross", "always_on"],
        default="price_cross",
        help="confirmation gate (always_on confirms every candidate — testing)",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="trading-engine")
    sub = parser.add_subparsers(dest="cmd", required=True)

    for name in ("regime", "rank", "scan-once", "confirm"):
        p = sub.add_parser(name, help=f"{name} subcommand")
        _add_common(p)

    p_run = sub.add_parser("run", help="execution-only loop (expire → scan → confirm → track)")
    _add_common(p_run)
    p_run.add_argument("--interval", type=int, default=300, help="seconds between ticks")
    p_run.add_argument("--iterations", type=int, default=None, help="cap loop iterations (for tests)")
    p_run.add_argument(
        "--market-hours-only",
        action="store_true",
        help="skip scan/alert when the US market is closed (outcomes still tracked)",
    )

    p_wallet = sub.add_parser("wallet", help="paper-wallet P&L summary (read-only)")
    _add_common(p_wallet)
    p_wallet.add_argument(
        "--starting-balance", type=float, default=10_000.0, help="starting balance (default 10000)"
    )

    p_bf = sub.add_parser("backfill", help="pull OHLCV history from provider into repo")
    _add_common(p_bf)
    p_bf.add_argument("--symbols", required=True, help="comma-separated symbols")
    p_bf.add_argument("--start", required=True, help="ISO date (YYYY-MM-DD)")
    p_bf.add_argument("--end", required=True, help="ISO date (YYYY-MM-DD)")
    p_bf.add_argument("--timeframe", default="1d", help="1m/5m/15m/1h/1d (default 1d)")
    p_bf.add_argument("--concurrency", type=int, default=8)

    p_bt = sub.add_parser("backtest", help="replay historical bars through the pipeline")
    p_bt.add_argument("--symbols", required=True, help="comma-separated symbols, e.g. GS,WMT,SPY")
    p_bt.add_argument("--start", required=True, help="ISO date (YYYY-MM-DD)")
    p_bt.add_argument("--end", required=True, help="ISO date (YYYY-MM-DD)")
    p_bt.add_argument("--horizon", type=int, default=5, help="forward bars to score outcomes (default 5)")
    p_bt.add_argument("--out", default=None, help="output CSV path (default outputs/backtest_<run_id>.csv)")

    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = build_parser()
    args = parser.parse_args(argv)
    coro = {
        "regime": cmd_regime,
        "rank": cmd_rank,
        "scan-once": cmd_scan_once,
        "confirm": cmd_confirm,
        "run": cmd_run,
        "wallet": cmd_wallet,
        "backtest": cmd_backtest,
        "backfill": cmd_backfill,
    }[args.cmd](args)
    return asyncio.run(coro)


if __name__ == "__main__":
    sys.exit(main())
