"""Typed config loader.

Reads ``config/settings.yaml`` and ``config/universe.yaml`` into pydantic
models. Secrets (API keys, Telegram credentials, DB URL) come from the
process environment — never from YAML.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator


class _Cfg(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


class LiquidityConfig(_Cfg):
    min_price: float
    min_avg_daily_dollar_volume: float
    min_option_open_interest: int
    min_option_volume: int
    max_option_bid_ask_spread_pct: float


class FactorWeights(_Cfg):
    relative_strength: float
    sector_strength: float
    structure: float
    trend: float
    volume_expansion: float
    catalyst: float

    @field_validator("catalyst")
    @classmethod
    def _weights_sum_to_one(cls, v: float, info: Any) -> float:
        d = info.data
        total = (
            d["relative_strength"]
            + d["sector_strength"]
            + d["structure"]
            + d["trend"]
            + d["volume_expansion"]
            + v
        )
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"factor_weights must sum to 1.0, got {total}")
        return v


class RiskConfig(_Cfg):
    trim1_gain_pct: float
    trim2_gain_pct: float
    move_stop_to_be_after_trim1: bool
    runner_trail: str
    forced_exit_before_event: bool


class ContractConfig(_Cfg):
    swing_dte_min: int
    swing_dte_max: int
    day_dte_min: int
    day_dte_max: int
    delta_target_min: float
    delta_target_max: float
    lotto_delta_max: float
    reject_if_spread_pct_above: float


class RegimeConfig(_Cfg):
    vwap_lookback_min: int
    emas: list[int]
    block_if_event_within_hours: int
    index_symbols: list[str]


class StorageConfig(_Cfg):
    database_url_env: str = "DATABASE_URL"


class AlertsConfig(_Cfg):
    dedupe_window_minutes: int = 30


class ExecutionConfig(_Cfg):
    """Execution-only layer knobs (candidate lifecycle)."""

    candidate_ttl_hours: int = 24


class LoggingConfig(_Cfg):
    level_env: str = "LOG_LEVEL"
    default_level: str = "INFO"


class Settings(_Cfg):
    liquidity: LiquidityConfig
    factor_weights: FactorWeights
    risk: RiskConfig
    contract: ContractConfig
    regime: RegimeConfig
    storage: StorageConfig = Field(default_factory=StorageConfig)
    alerts: AlertsConfig = Field(default_factory=AlertsConfig)
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)


# ---------------------------------------------------------------------------
# Universe
# ---------------------------------------------------------------------------


class Universe(_Cfg):
    symbols: list[str]
    indices: list[str]
    sector_etfs: dict[str, str]


# ---------------------------------------------------------------------------
# Secrets (resolved from env, not YAML)
# ---------------------------------------------------------------------------


class Secrets(_Cfg):
    polygon_api_key: str | None
    telegram_bot_token: str | None
    telegram_chat_id: str | None
    database_url: str


# ---------------------------------------------------------------------------
# Top-level container
# ---------------------------------------------------------------------------


class AppConfig(_Cfg):
    settings: Settings
    universe: Universe
    secrets: Secrets


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------


def _read_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"Expected mapping at top of {path}, got {type(data).__name__}")
    return data


def _load_secrets(database_url_env: str) -> Secrets:
    return Secrets(
        polygon_api_key=os.environ.get("POLYGON_API_KEY") or None,
        telegram_bot_token=os.environ.get("TELEGRAM_BOT_TOKEN") or None,
        telegram_chat_id=os.environ.get("TELEGRAM_CHAT_ID") or None,
        database_url=os.environ.get(database_url_env, "sqlite:///./trading_engine.db"),
    )


def default_config_dir() -> Path:
    """Repo-root ``config/`` directory."""
    return Path(__file__).resolve().parents[2] / "config"


def load_settings(path: Path | None = None) -> Settings:
    p = path or (default_config_dir() / "settings.yaml")
    return Settings.model_validate(_read_yaml(p))


def load_universe(path: Path | None = None) -> Universe:
    p = path or (default_config_dir() / "universe.yaml")
    return Universe.model_validate(_read_yaml(p))


def load_app_config(config_dir: Path | None = None) -> AppConfig:
    cdir = config_dir or default_config_dir()
    settings = load_settings(cdir / "settings.yaml")
    universe = load_universe(cdir / "universe.yaml")
    secrets = _load_secrets(settings.storage.database_url_env)
    return AppConfig(settings=settings, universe=universe, secrets=secrets)


__all__ = [
    "AlertsConfig",
    "AppConfig",
    "ContractConfig",
    "ExecutionConfig",
    "FactorWeights",
    "LiquidityConfig",
    "LoggingConfig",
    "RegimeConfig",
    "RiskConfig",
    "Secrets",
    "Settings",
    "StorageConfig",
    "Universe",
    "default_config_dir",
    "load_app_config",
    "load_settings",
    "load_universe",
]
