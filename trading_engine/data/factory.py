"""Provider factory — mock | polygon."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

from trading_engine.core.config import AppConfig, load_app_config
from trading_engine.core.interfaces import EventsProvider, MarketDataProvider, OptionsDataProvider
from trading_engine.data.mock_provider import (
    MockEventsProvider,
    MockMarketDataProvider,
    MockOptionsDataProvider,
)
from trading_engine.data.polygon_provider import (
    PolygonEventsProvider,
    PolygonMarketDataProvider,
    PolygonOptionsDataProvider,
    create_polygon_client,
)

ProviderKind = Literal["mock", "polygon"]


@dataclass(frozen=True)
class ProviderBundle:
    market: MarketDataProvider
    options: OptionsDataProvider
    events: EventsProvider


def create_providers(
    kind: ProviderKind | None = None,
    *,
    config: AppConfig | None = None,
) -> ProviderBundle:
    """Select provider from env ``DATA_PROVIDER`` or explicit kind."""
    config = config or load_app_config()
    kind = kind or os.environ.get("DATA_PROVIDER", "mock")  # type: ignore[assignment]
    if kind == "polygon":
        key = config.secrets.polygon_api_key
        if not key:
            raise ValueError("POLYGON_API_KEY required for polygon provider")
        client = create_polygon_client(key)
        return ProviderBundle(
            market=PolygonMarketDataProvider(client),
            options=PolygonOptionsDataProvider(client),
            events=PolygonEventsProvider(client),
        )
    return ProviderBundle(
        market=MockMarketDataProvider(),
        options=MockOptionsDataProvider(),
        events=MockEventsProvider(),
    )
