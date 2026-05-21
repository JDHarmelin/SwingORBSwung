"""Universe builder — liquidity filtering."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from trading_engine.core.config import AppConfig, Universe, load_app_config
from trading_engine.core.interfaces import MarketDataProvider, OptionsDataProvider
from trading_engine.core.types import Timeframe


@dataclass(frozen=True)
class TradableUniverse:
    symbols: list[str]
    sector_etfs: dict[str, str]
    indices: list[str]
    excluded: list[str]


async def build_universe(
    market: MarketDataProvider,
    options: OptionsDataProvider,
    *,
    config: AppConfig | None = None,
    watchlist_override: list[str] | None = None,
) -> TradableUniverse:
    """Apply liquidity rules from spec §2."""
    config = config or load_app_config()
    universe: Universe = config.universe
    liq = config.settings.liquidity
    symbols = watchlist_override or list(universe.symbols)
    now = datetime.now(tz=UTC)
    start = now - timedelta(days=30)
    included: list[str] = []
    excluded: list[str] = []

    for sym in symbols:
        try:
            series = await market.get_ohlcv(sym, Timeframe.D1, start, now)
            if not series.candles:
                excluded.append(sym)
                continue
            last = series.candles[-1]
            avg_dollar = sum(c.close * c.volume for c in series.candles[-20:]) / min(
                20, len(series.candles)
            )
            if last.close < liq.min_price:
                excluded.append(sym)
                continue
            if avg_dollar < liq.min_avg_daily_dollar_volume:
                excluded.append(sym)
                continue
            try:
                chain = await options.get_option_chain(sym)
                liquid = any(
                    c.open_interest >= liq.min_option_open_interest
                    and c.volume >= liq.min_option_volume
                    and (c.spread_pct or 100) <= liq.max_option_bid_ask_spread_pct
                    for c in chain.contracts
                )
                if not liquid:
                    excluded.append(sym)
                    continue
            except Exception:
                # Options API unavailable (403/429) — keep symbol if stock liquidity passed
                pass
            included.append(sym)
        except Exception:
            excluded.append(sym)

    return TradableUniverse(
        symbols=included,
        sector_etfs=dict(universe.sector_etfs),
        indices=list(universe.indices),
        excluded=excluded,
    )


def symbols_from_config(config: AppConfig | None = None) -> list[str]:
    """Stock symbols from ``config/universe.yaml`` (no liquidity filter)."""
    config = config or load_app_config()
    return list(config.universe.symbols)


async def resolve_scan_symbols(
    market: MarketDataProvider,
    options: OptionsDataProvider,
    *,
    config: AppConfig | None = None,
    symbols_override: list[str] | None = None,
    filter_liquidity: bool = False,
) -> list[str]:
    """Symbols for scan/rank/backfill.

    - No override, no filter → YAML ``symbols`` list.
    - ``filter_liquidity=True`` (recommended for Polygon) → ``build_universe()``.
    - ``symbols_override`` → that list, optionally filtered.
    """
    config = config or load_app_config()
    if filter_liquidity:
        watchlist = symbols_override or None
        tradable = await build_universe(
            market,
            options,
            config=config,
            watchlist_override=watchlist,
        )
        return tradable.symbols
    if symbols_override:
        return list(symbols_override)
    return symbols_from_config(config)
