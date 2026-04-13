"""Configuration system using Pydantic Settings with YAML + env var loading.

Config hierarchy: defaults → YAML file → environment variables (highest priority).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings


def _load_yaml_config(path: Path | None) -> dict[str, Any]:
    """Load configuration from a YAML file, returning empty dict if not found."""
    if path is None:
        return {}
    resolved = Path(path)
    if not resolved.exists():
        return {}
    with open(resolved) as f:
        data = yaml.safe_load(f)
    return data if isinstance(data, dict) else {}


class DatabaseConfig(BaseSettings):
    """PostgreSQL database configuration."""

    host: str = "localhost"
    port: int = 5432
    name: str = "polymarket_trader"
    user: str = "polymarket"
    password: str = "polymarket"

    @property
    def async_url(self) -> str:
        return f"postgresql+asyncpg://{self.user}:{self.password}@{self.host}:{self.port}/{self.name}"

    @property
    def sync_url(self) -> str:
        return f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{self.name}"


class RiskConfig(BaseSettings):
    """Risk Governor limits. All deterministic, no LLM override."""

    max_daily_deployment_pct: float = 0.10
    max_daily_drawdown_pct: float = 0.08
    max_total_open_exposure_usd: float = 10000.0
    max_simultaneous_positions: int = 20

    # Drawdown ladder thresholds
    soft_warning_pct: float = 0.03
    risk_reduction_pct: float = 0.05
    entries_disabled_pct: float = 0.065
    hard_kill_switch_pct: float = 0.08

    # Category exposure caps (USD per category)
    default_category_exposure_cap_usd: float = 5000.0
    sports_category_exposure_cap_usd: float = 2000.0

    # Correlation engine limits
    max_cluster_exposure_usd: float = 3000.0
    max_single_catalyst_exposure_usd: float = 2000.0
    max_correlation_burden_score: float = 0.8

    # Liquidity-relative sizing
    max_order_depth_fraction: float = 0.12  # 12% of visible depth at top 3 levels
    max_entry_impact_edge_fraction: float = 0.25  # reject if impact > 25% of gross edge
    depth_levels_for_sizing: int = 3

    # Position sizing multipliers and penalties
    sizing_base_fraction: float = 0.05  # base position as fraction of account
    ambiguity_penalty_weight: float = 0.3
    correlation_penalty_weight: float = 0.2
    weak_source_penalty_weight: float = 0.2
    timing_penalty_weight: float = 0.1
    sports_quality_gate_multiplier: float = 0.5  # 50% sizing until calibrated

    # Drawdown-adjusted sizing multipliers
    soft_warning_size_multiplier: float = 0.75
    risk_reduction_size_multiplier: float = 0.40
    min_evidence_score_soft_warning: float = 0.6  # higher threshold under soft warning


class CostConfig(BaseSettings):
    """Cost Governor budgets."""

    daily_llm_budget_usd: float = 25.0
    daily_opus_escalation_budget_usd: float = 5.0
    max_single_workflow_usd: float = 5.0
    max_per_accepted_candidate_usd: float = 10.0
    max_per_open_position_per_day_usd: float = 2.0
    lifetime_experiment_budget_usd: float = 5000.0
    cost_of_selectivity_target_ratio: float = 0.20
    cumulative_review_cost_warning_pct: float = 0.08
    cumulative_review_cost_cap_pct: float = 0.15
    cost_inefficient_edge_fraction: float = 0.20
    daily_budget_restrict_pct: float = 0.10
    lifetime_budget_restrict_pct: float = 0.75


class ScannerConfig(BaseSettings):
    """Trigger scanner intervals and thresholds."""

    poll_interval_seconds: int = 60
    cache_depth_hours: int = 4
    freshness_threshold_seconds: int = 180
    degraded_level1_minutes: int = 3
    degraded_level2_hours: int = 4
    degraded_level3_hours: int = 8


class EligibilityConfig(BaseSettings):
    """Eligibility gate thresholds."""

    min_liquidity_usd: float = 500.0
    max_spread: float = 0.15
    min_horizon_hours: int = 24
    max_horizon_days: int = 90
    sports_min_horizon_hours: int = 48


class ModelConfig(BaseSettings):
    """LLM provider API keys and model overrides."""

    anthropic_api_key: str = ""
    openai_api_key: str = ""

    tier_a_model: str = "claude-opus-4-6"
    tier_b_model: str = "claude-sonnet-4-6"
    tier_c_model: str = "gpt-5.4-nano"
    tier_c_alt_model: str = "gpt-5.4-mini"


class TelegramConfig(BaseSettings):
    """Telegram notification configuration."""

    bot_token: str = ""
    chat_id: str = ""
    enabled: bool = False


class CalibrationConfig(BaseSettings):
    """Calibration and viability thresholds."""

    initial_correction_min_trades: int = 20
    category_min_trades: int = 30
    horizon_bucket_min_trades: int = 25
    sports_min_trades: int = 40
    size_penalty_reduction_min_trades: int = 30

    # Viability checkpoint weeks
    preliminary_week: int = 4
    intermediate_week: int = 8
    decision_week: int = 12
    viability_min_forecasts: int = 50


class PolymarketApiConfig(BaseSettings):
    """Polymarket API endpoints, rate limits, and retry configuration."""

    # Base URLs
    gamma_base_url: str = "https://gamma-api.polymarket.com"
    clob_base_url: str = "https://clob.polymarket.com"
    subgraph_url: str = "https://api.thegraph.com/subgraphs/name/polymarket/polymarket-matic"

    # Timeouts (seconds)
    request_timeout: float = 15.0
    connect_timeout: float = 5.0

    # Rate limiting (conservative vs actual API limits)
    gamma_max_requests_per_10s: int = 250
    clob_max_requests_per_10s: int = 400

    # Retry
    max_retries: int = 3
    backoff_base_seconds: float = 1.0
    backoff_max_seconds: float = 30.0

    # Batch sizing
    market_list_page_size: int = 100
    orderbook_depth_levels: int = 5

    # Health
    consecutive_failure_threshold: int = 5


class AbsenceConfig(BaseSettings):
    """Operator absence escalation thresholds."""

    no_new_entries_hours: int = 48
    first_size_reduction_hours: int = 72
    first_size_reduction_pct: float = 0.25
    second_size_reduction_hours: int = 96
    second_size_reduction_pct: float = 0.25
    graceful_winddown_hours: int = 120


class AppConfig(BaseSettings):
    """Root application configuration.

    Load order: defaults → YAML → environment variables.
    Env vars use POLYMARKET_ prefix (e.g., POLYMARKET_DATABASE__HOST).
    """

    model_config = {"env_prefix": "POLYMARKET_", "env_nested_delimiter": "__"}

    # System
    operator_mode: str = "paper"
    log_level: str = "INFO"
    config_path: Path | None = None

    # Sub-configs
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    cost: CostConfig = Field(default_factory=CostConfig)
    scanner: ScannerConfig = Field(default_factory=ScannerConfig)
    eligibility: EligibilityConfig = Field(default_factory=EligibilityConfig)
    models: ModelConfig = Field(default_factory=ModelConfig)
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
    calibration: CalibrationConfig = Field(default_factory=CalibrationConfig)
    absence: AbsenceConfig = Field(default_factory=AbsenceConfig)
    polymarket_api: PolymarketApiConfig = Field(default_factory=PolymarketApiConfig)


def load_config(config_path: Path | None = None) -> AppConfig:
    """Load configuration from YAML file + environment variables.

    Args:
        config_path: Path to YAML config file. If None, loads from env vars only.
    """
    yaml_data = _load_yaml_config(config_path)

    if yaml_data:
        return AppConfig(**yaml_data, config_path=config_path)
    return AppConfig(config_path=config_path)
