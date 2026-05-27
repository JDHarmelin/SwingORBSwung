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
    # Per-risk-class overrides. Keys match RiskClass.value (standard/a_plus/
    # lotto/day_trade/hedge). Missing keys fall back to the top-level floor.
    # Lotto and day-trade flows often need looser floors (cheap weeklies have
    # thin OI); a_plus can stay tight.
    option_floor_overrides: dict[str, dict[str, float]] = {}

    def for_risk_class(self, risk_class_value: str) -> "LiquidityConfig":
        """Return a LiquidityConfig with overrides applied for ``risk_class_value``."""
        ov = self.option_floor_overrides.get(risk_class_value) or {}
        if not ov:
            return self
        return self.model_copy(
            update={
                "min_option_open_interest": int(ov.get("min_option_open_interest", self.min_option_open_interest)),
                "min_option_volume": int(ov.get("min_option_volume", self.min_option_volume)),
                "max_option_bid_ask_spread_pct": float(
                    ov.get("max_option_bid_ask_spread_pct", self.max_option_bid_ask_spread_pct)
                ),
            }
        )


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
    # Per-setup-class dollar risk caps (additive; absent keys fall back to
    # DEFAULT_MAX_LOSS_DOLLARS below).
    max_loss_dollars: dict[str, float] = Field(default_factory=dict)


# Sensible defaults when config doesn't provide caps. Keyed by RiskClass.value
# (string tag) plus common synonyms ("day_trade").
DEFAULT_MAX_LOSS_DOLLARS: dict[str, float] = {
    "standard": 200.0,
    "a_plus": 400.0,
    "lotto": 100.0,
    "day_trade": 150.0,
    "hedge": 150.0,
}


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
    """Execution-only alerting controls (spec §6/§8)."""

    candidate_ttl_hours: int = 24
    paper_rr: float = 2.0
    paper_track_bars: int = 30


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
    # Symbol → sector key. Keys must match a key in ``sector_etfs`` for the
    # mapping to contribute to the composite score. Symbols absent here
    # receive a sector_composite of 0.0 (neutral) — never crash.
    symbol_sectors: dict[str, str] = Field(default_factory=dict)


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


def _load_dotenv(path: Path) -> None:
    """Populate ``os.environ`` from a ``.env`` file, but do not overwrite
    variables already set in the real environment (so an explicit shell
    export still wins, which matters for CI).

    Minimal KEY=VALUE parser — strips matching quotes, ignores blank lines and
    ``#`` comments. We deliberately don't pull in ``python-dotenv`` for this.
    """
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]
        # Don't clobber existing exports — explicit env wins.
        os.environ.setdefault(key, value)


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
    # Load the project-root .env (one level above ``config/``) so secrets live
    # with the project, not in the user shell. Explicit shell exports still win.
    _load_dotenv(cdir.parent / ".env")
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
