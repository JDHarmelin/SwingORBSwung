"""CLI entrypoint — mock + console by default; Polygon + Telegram via env."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

from trading_engine.alerts.console import ConsoleAlertSink
from trading_engine.core.config import AppConfig, load_app_config
from trading_engine.core.interfaces import AlertSink
from trading_engine.data.factory import ProviderBundle, create_providers
from trading_engine.data.mock_provider import MOCK_SYMBOLS
from trading_engine.data.universe import resolve_scan_symbols
from trading_engine.scanners.market_regime import compute_market_regime
from trading_engine.scanners.sector_rank import rank_sectors
from trading_engine.scanners.stock_ranker import rank_stocks
from trading_engine.services.backfill import backfill_universe
from trading_engine.services.confirmation import PriceCrossConfirmationGate
from trading_engine.services.scheduler import Scheduler
from trading_engine.services.signal_service import SignalService
from trading_engine.storage.db import create_engine_from_config, init_schema
from trading_engine.storage.repository import SqlRepository


def _parse_env_file(path: Path, *, override: bool = True) -> None:
    """Minimal .env loader (no dependency on python-dotenv)."""
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if not key:
            continue
        if override or key not in os.environ:
            os.environ[key] = value


def _load_dotenv() -> None:
    """Load ``.env`` from repo root and/or cwd (always; dotenv is optional)."""
    candidates = [
        Path(__file__).resolve().parents[1] / ".env",
        Path.cwd() / ".env",
    ]
    seen: set[Path] = set()
    for env_path in candidates:
        resolved = env_path.resolve()
        if resolved in seen or not resolved.is_file():
            continue
        seen.add(resolved)
        _parse_env_file(resolved)
        try:
            from dotenv import load_dotenv

            load_dotenv(resolved, override=True)
        except ImportError:
            pass


def _setup_logging() -> None:
    level = os.environ.get("LOG_LEVEL", "INFO")
    logging.basicConfig(level=getattr(logging, level.upper(), logging.INFO))
    logging.getLogger("httpx").setLevel(logging.WARNING)


def _repo() -> SqlRepository:
    config = load_app_config()
    engine = create_engine_from_config(config)
    init_schema(engine)
    return SqlRepository(engine=engine)


def _alerts(kind: str) -> AlertSink:
    if kind == "telegram":
        from trading_engine.alerts.telegram import TelegramAlertSink

        return TelegramAlertSink()
    return ConsoleAlertSink()


def _filter_liquidity(args: argparse.Namespace) -> bool:
    if getattr(args, "no_filter_universe", False):
        return False
    if getattr(args, "filter_universe", False):
        return True
    return bool(args.provider == "polygon")


def _symbols_override(args: argparse.Namespace) -> list[str] | None:
    raw = getattr(args, "symbols", None)
    if not raw:
        return None
    return [s.strip().upper() for s in raw.split(",") if s.strip()]


def _validate_runtime(args: argparse.Namespace) -> None:
    if args.provider == "polygon" and not os.environ.get("POLYGON_API_KEY"):
        print("error: POLYGON_API_KEY is required for --provider polygon", file=sys.stderr)
        sys.exit(1)
    if args.alerts == "telegram":
        try:
            from trading_engine.alerts.telegram_config import (
                load_telegram_credentials,
                verify_bot_username,
            )

            token, chat_id = load_telegram_credentials()
            verify_bot_username(token)
            # Pin to .env values so shell env cannot redirect alerts elsewhere
            os.environ["TELEGRAM_BOT_TOKEN"] = token
            os.environ["TELEGRAM_CHAT_ID"] = chat_id
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            sys.exit(1)


async def _resolve_symbols(
    args: argparse.Namespace,
    providers: ProviderBundle,
    *,
    config: AppConfig | None = None,
) -> list[str]:
    config = config or load_app_config()
    override = _symbols_override(args)
    # Mock data only serves real shapes for the synthetic symbols; the real
    # ticker universe would all fall back to choppy data and trigger nothing.
    if override is None and args.provider == "mock":
        override = list(MOCK_SYMBOLS)
    syms = await resolve_scan_symbols(
        providers.market,
        providers.options,
        config=config,
        symbols_override=override,
        filter_liquidity=_filter_liquidity(args),
    )
    logging.getLogger(__name__).info(
        "universe: %d symbols (provider=%s, filter=%s)",
        len(syms),
        args.provider,
        _filter_liquidity(args),
    )
    return syms


async def cmd_scan_once(args: argparse.Namespace) -> None:
    config = load_app_config()
    providers = create_providers(args.provider, config=config)
    symbols = await _resolve_symbols(args, providers, config=config)
    gate = PriceCrossConfirmationGate(providers.market)
    svc = SignalService(providers, _repo(), _alerts(args.alerts), config=config, gate=gate)
    candidates = await svc.scan_once(symbols, filter_liquidity=False, alert_candidates=False)
    expired = await svc.expire_stale_candidates()
    confirmed = await svc.confirm_and_alert()
    tracked = await svc.track_outcomes()
    print(
        f"{len(candidates)} candidate(s) from {len(symbols)} symbol(s); "
        f"{len(expired)} expired; {len(confirmed)} confirmed → alerted; "
        f"{len(tracked)} outcome(s) logged"
    )


async def cmd_regime(args: argparse.Namespace) -> None:
    providers = create_providers(args.provider)
    regime = await compute_market_regime(providers.market, providers.events)
    print(regime.model_dump_json(indent=2))


async def cmd_rank(args: argparse.Namespace) -> None:
    config = load_app_config()
    providers = create_providers(args.provider, config=config)
    symbols = await _resolve_symbols(args, providers, config=config)
    sectors = await rank_sectors(providers.market, config=config)
    buckets = await rank_stocks(providers.market, symbols, sectors, config=config)
    print("LONGS:", [s.symbol for s in buckets.longs[:20]])
    print("SHORTS:", [s.symbol for s in buckets.shorts[:20]])


async def cmd_backfill(args: argparse.Namespace) -> None:
    config = load_app_config()
    providers = create_providers(args.provider, config=config)
    if args.symbols:
        symbols = _symbols_override(args) or []
    else:
        symbols = await _resolve_symbols(args, providers, config=config)
    n = await backfill_universe(providers.market, _repo(), symbols)
    print(f"Backfilled {n} candles for {len(symbols)} symbol(s)")


async def cmd_run(args: argparse.Namespace) -> None:
    config = load_app_config()
    providers = create_providers(args.provider, config=config)
    symbols = await _resolve_symbols(args, providers, config=config)
    gate = PriceCrossConfirmationGate(providers.market)
    svc = SignalService(providers, _repo(), _alerts(args.alerts), config=config, gate=gate)
    interval = getattr(args, "interval", 300)
    sched = Scheduler(svc, intraday_interval_sec=interval)
    await sched.run(symbols)


async def cmd_mcp(args: argparse.Namespace) -> None:
    """Run the Hermes MCP bridge server over stdio (engine = MCP server).

    Hermes connects as an MCP client and drives confirmation. No mechanical
    gate is wired (gate=None): Hermes is the confirmation brain. Alert/paper-only.
    """
    try:
        from trading_engine.integrations.hermes_mcp import build_hermes_mcp
    except ImportError:
        print(
            "error: the 'mcp' package is required for the Hermes bridge.\n"
            '       install it with:  pip install -e ".[hermes]"  (or  pip install mcp)',
            file=sys.stderr,
        )
        sys.exit(1)
    config = load_app_config()
    providers = create_providers(args.provider, config=config)
    svc = SignalService(providers, _repo(), _alerts(args.alerts), config=config, gate=None)
    server = build_hermes_mcp(svc, _repo())
    logging.getLogger(__name__).info(
        "Hermes MCP bridge listening on stdio (provider=%s)", args.provider
    )
    await server.run_stdio_async()


def _add_global_flags(parser: argparse.ArgumentParser) -> None:
    # default=SUPPRESS so a flag given before the subcommand is NOT overwritten
    # by the subparser's copy of the same flag (argparse re-applies subparser
    # defaults over the namespace otherwise). Real defaults are filled in by
    # _apply_global_defaults() after parsing.
    parser.add_argument(
        "--provider",
        choices=["mock", "polygon"],
        default=argparse.SUPPRESS,
        help="Data source (default: mock, or DATA_PROVIDER env)",
    )
    parser.add_argument(
        "--alerts",
        choices=["console", "telegram"],
        default=argparse.SUPPRESS,
        help="Alert sink (default: console, or ALERT_SINK env)",
    )
    parser.add_argument(
        "--symbols",
        metavar="SYM,...",
        default=argparse.SUPPRESS,
        help="Override tickers (default: config/universe.yaml; mock synthetic set for --provider mock)",
    )
    parser.add_argument(
        "--filter-universe",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Apply liquidity rules via build_universe() (default for polygon)",
    )
    parser.add_argument(
        "--no-filter-universe",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Use YAML list only; skip liquidity filter (default for mock)",
    )


def _apply_global_defaults(args: argparse.Namespace) -> None:
    """Fill global flags not supplied in either position (root or subcommand).

    Pairs with default=SUPPRESS in _add_global_flags: a flag set anywhere on the
    command line survives; only genuinely-absent flags fall back to env/defaults.
    """
    defaults = {
        "provider": os.environ.get("DATA_PROVIDER", "mock"),
        "alerts": os.environ.get("ALERT_SINK", "console"),
        "symbols": None,
        "filter_universe": False,
        "no_filter_universe": False,
    }
    for key, value in defaults.items():
        if not hasattr(args, key):
            setattr(args, key, value)


def main(argv: list[str] | None = None) -> None:
    _load_dotenv()
    _setup_logging()

    # Shared flags on subcommands so:  scan-once --provider polygon  works
    common = argparse.ArgumentParser(add_help=False)
    _add_global_flags(common)

    parser = argparse.ArgumentParser(
        prog="trading_engine",
        description="Systematic momentum options engine (alert/paper-only).",
    )
    # Same flags on root so:  --provider polygon scan-once  also works
    _add_global_flags(parser)

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("scan-once", parents=[common], help="Run one full scan tick")
    p_run = sub.add_parser("run", parents=[common], help="Intraday scheduler loop")
    p_run.add_argument(
        "--interval",
        type=int,
        default=300,
        help="Seconds between scans (default: 300)",
    )
    sub.add_parser("backfill", parents=[common], help="Store historical candles")
    sub.add_parser("regime", parents=[common], help="Print current market regime")
    sub.add_parser("rank", parents=[common], help="Print top long/short ranked symbols")
    sub.add_parser("mcp", parents=[common], help="Run the Hermes MCP bridge (stdio)")

    args = parser.parse_args(argv)
    _apply_global_defaults(args)
    _validate_runtime(args)

    cmds = {
        "scan-once": cmd_scan_once,
        "run": cmd_run,
        "backfill": cmd_backfill,
        "regime": cmd_regime,
        "rank": cmd_rank,
        "mcp": cmd_mcp,
    }
    asyncio.run(cmds[args.command](args))


if __name__ == "__main__":
    main()
