"""CLI entrypoint.

Subcommands:
- ``regime``: classify the current regime and print it.
- ``rank``: print top long/short candidate scores.
- ``scan``: full pipeline once; emit alerts to the configured sink.
- ``run``: pipeline + management loop.

Provider/sink wiring is controlled by ``--provider`` and ``--sink``:
- ``--provider mock`` uses synthetic fixtures (no API keys required).
- ``--sink console`` prints alerts to stdout; ``telegram`` posts to the bot
  configured via ``TELEGRAM_BOT_TOKEN`` / ``TELEGRAM_CHAT_ID``.
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
from trading_engine.data.polygon import (
    PolygonEventsProvider,
    PolygonMarketDataProvider,
    PolygonOptionsDataProvider,
)
from trading_engine.services.management_service import ManagementService
from trading_engine.services.scheduler import run_loop, run_once
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
        return (
            PolygonMarketDataProvider(key),
            PolygonOptionsDataProvider(key),
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


def _build_service(args: argparse.Namespace) -> tuple[SignalService, ManagementService, AlertSink]:
    cfg = load_app_config()
    providers = _make_providers(args.provider, cfg)
    sink = _make_sink(args.sink, cfg)
    repo = _make_repo(args.repo, cfg)
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
    return signal_service, management_service, sink


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------


async def cmd_regime(args: argparse.Namespace) -> int:
    signal_service, _mgmt, _sink = _build_service(args)
    # Run only the regime portion by invoking the pipeline and reporting result.
    result = await signal_service.run_pipeline(datetime.now(tz=UTC))
    print("Regime notes:")
    for note in result.regime_notes:
        print(f"  - {note}")
    return 0


async def cmd_rank(args: argparse.Namespace) -> int:
    signal_service, _mgmt, _sink = _build_service(args)
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


async def cmd_scan(args: argparse.Namespace) -> int:
    signal_service, mgmt, _sink = _build_service(args)
    emitted = await run_once(signal_service, mgmt)
    print(f"Emitted {emitted} signal(s) — see configured sink for messages.")
    return 0


async def cmd_run(args: argparse.Namespace) -> int:
    signal_service, mgmt, _sink = _build_service(args)
    await run_loop(
        signal_service,
        mgmt,
        interval_seconds=args.interval,
        iterations=args.iterations,
    )
    return 0


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--provider", choices=["mock", "polygon"], default="mock")
    p.add_argument("--sink", choices=["console", "memory", "telegram"], default="console")
    p.add_argument("--repo", choices=["memory", "sqlite"], default="memory")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="trading-engine")
    sub = parser.add_subparsers(dest="cmd", required=True)

    for name in ("regime", "rank", "scan"):
        p = sub.add_parser(name, help=f"{name} subcommand")
        _add_common(p)

    p_run = sub.add_parser("run", help="run pipeline + management loop")
    _add_common(p_run)
    p_run.add_argument("--interval", type=int, default=300, help="seconds between mgmt ticks")
    p_run.add_argument("--iterations", type=int, default=None, help="cap loop iterations (for tests)")

    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = build_parser()
    args = parser.parse_args(argv)
    coro = {
        "regime": cmd_regime,
        "rank": cmd_rank,
        "scan": cmd_scan,
        "run": cmd_run,
    }[args.cmd](args)
    return asyncio.run(coro)


if __name__ == "__main__":
    sys.exit(main())
