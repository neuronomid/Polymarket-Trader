"""Configuration system using Pydantic Settings with YAML + env var loading.

Config hierarchy: defaults → YAML file → environment variables (highest priority).
"""

from __future__ import annotations

import os
from functools import lru_cache
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


@lru_cache(maxsize=1)
def _load_dotenv_values() -> dict[str, str]:
    """Load key/value pairs from the nearest .env file without exporting them."""
    for base in (Path.cwd(), *Path.cwd().parents):
        dotenv_path = base / ".env"
        if not dotenv_path.exists():
            continue

        values: dict[str, str] = {}
        with open(dotenv_path) as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue

                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip()

                if value and value[0] == value[-1] and value[0] in {'"', "'"}:
                    value = value[1:-1]

                values[key] = value

        return values

    return {}


def _load_env_value(*names: str) -> str:
    """Resolve a config value from env vars first, then the local .env file."""
    dotenv_values = _load_dotenv_values()
    for name in names:
        env_value = os.getenv(name)
        if env_value is not None:
            return env_value

        dotenv_value = dotenv_values.get(name)
        if dotenv_value is not None:
            return dotenv_value

    return ""


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
    max_daily_drawdown_pct: float = 0.04
    max_total_open_exposure_usd: float = 10000.0
    max_simultaneous_positions: int = 20

    # Drawdown ladder thresholds
    soft_warning_pct: float = 0.01
    risk_reduction_pct: float = 0.02
    entries_disabled_pct: float = 0.035
    hard_kill_switch_pct: float = 0.04

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
    min_viable_impact_adjusted_edge: float = 0.002  # deterministic minimum for investigation viability
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
    """LLM API keys and model overrides.

    Tier A/B Anthropic-family models route through OpenRouter by default.
    Tier C OpenAI models route through OpenAI directly.
    """

    openrouter_api_key: str = Field(
        default_factory=lambda: _load_env_value(
            "OPENROUTER_API_KEY",
            "POLYMARKET_MODELS__OPENROUTER_API_KEY",
        )
    )
    openai_api_key: str = Field(
        default_factory=lambda: _load_env_value(
            "OPENAI_API_KEY",
            "POLYMARKET_MODELS__OPENAI_API_KEY",
        )
    )
    anthropic_api_key: str = Field(
        default_factory=lambda: _load_env_value(
            "ANTHROPIC_API_KEY",
            "POLYMARKET_MODELS__ANTHROPIC_API_KEY",
        )
    )
    openrouter_base_url: str = Field(
        default_factory=lambda: _load_env_value(
            "OPENROUTER_BASE_URL",
            "POLYMARKET_MODELS__OPENROUTER_BASE_URL",
        )
        or "https://openrouter.ai/api/v1"
    )

    tier_a_model: str = "claude-opus-4-6"
    tier_b_model: str = "claude-sonnet-4-6"
    tier_c_model: str = "gpt-5.4-nano"
    tier_c_alt_model: str = "gpt-5.4-mini"


class TelegramConfig(BaseSettings):
    """Telegram notification configuration."""

    bot_token: str = ""
    chat_id: str = ""  # comma-separated list of pre-approved chat IDs
    enabled: bool = False

    # Delivery
    max_retries: int = 3
    retry_base_delay_seconds: float = 1.0
    dedup_window_seconds: int = 300  # 5-minute dedup window
    request_timeout_seconds: float = 30.0


class NotificationConfig(BaseSettings):
    """Notification service configuration."""

    # Whether to use LLM composer for complex messages (weekly, critical)
    use_llm_composer: bool = False

    # Severity routing: which severities trigger all-chat broadcast
    broadcast_severities: list[str] = ["critical"]

    # Rate limiting: max notifications per event type per hour
    max_per_type_per_hour: int = 20


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

    # Cross-category pooling
    pool_minimum_combined: int = 15
    pool_minimum_individual: int = 5
    pool_penalty_factor: float = 0.30

    # Accumulation tracking
    accumulation_lookback_weeks: int = 4


class LearningConfig(BaseSettings):
    """Learning system configuration."""

    # Patience budget
    patience_budget_months: int = 9

    # No-trade rate monitoring
    no_trade_low_threshold: float = 0.30
    no_trade_high_threshold: float = 0.90

    # Policy review
    policy_min_sample_size: int = 20
    policy_min_persistence_weeks: int = 3
    early_deployment: bool = True

    # Learning loop cadence (hours)
    fast_loop_interval_hours: int = 24
    slow_loop_interval_hours: int = 168  # weekly


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


class ExecutionConfig(BaseSettings):
    """Execution engine configuration."""

    # Pre-execution revalidation
    max_approval_staleness_seconds: int = 300  # 5 minutes
    staged_entry_depth_fraction: float = 0.05  # staged when > 5% of depth

    # Friction model defaults
    default_spread_estimate: float = 0.02
    default_depth_assumption: float = 5000.0
    default_impact_coefficient: float = 0.5

    # Slippage recalibration
    slippage_recalibration_ratio: float = 1.5
    slippage_recalibration_window: int = 20
    min_trades_for_calibration: int = 10

    # Impact threshold for staged entry (bps)
    high_impact_threshold_bps: float = 50.0


class TradeabilityConfig(BaseSettings):
    """Tradeability and resolution parser configuration."""

    # Spread and depth hard limits
    max_spread: float = 0.15
    min_depth_for_min_position_usd: float = 50.0

    # Ambiguity thresholds
    max_ambiguous_phrases_marginal: int = 1  # 1 → marginal
    max_ambiguous_phrases_reject: int = 4  # 4+ → auto-reject


class PositionReviewConfig(BaseSettings):
    """Position review scheduling and deterministic check thresholds."""

    # Tier 1 (New): first N hours, every N hours
    new_position_hours: float = 48.0
    new_review_interval_hours: float = 3.0  # 2-4 hours, default 3

    # Tier 2 (Stable): every N hours
    stable_review_interval_hours: float = 7.0  # 6-8 hours, default 7
    stable_no_trigger_hours: float = 24.0  # no triggers in 24h for stable

    # Tier 3 (Low-value): every N hours
    low_value_review_interval_hours: float = 12.0
    low_value_percentile: float = 0.20  # bottom 20th percentile

    # Deterministic check thresholds
    price_adverse_move_threshold: float = 0.10  # 10% adverse move
    max_spread_for_hold: float = 0.20  # max spread before flagging
    min_depth_for_exit_usd: float = 100.0  # min depth for exit capability
    catalyst_proximity_hours: float = 24.0  # flag when within 24h
    horizon_warning_pct: float = 0.80  # warn at 80% of horizon


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
    paper_balance_usd: float = 500.0

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
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)
    tradeability: TradeabilityConfig = Field(default_factory=TradeabilityConfig)
    polymarket_api: PolymarketApiConfig = Field(default_factory=PolymarketApiConfig)
    position_review: PositionReviewConfig = Field(default_factory=PositionReviewConfig)
    learning: LearningConfig = Field(default_factory=LearningConfig)
    notification: NotificationConfig = Field(default_factory=NotificationConfig)


def load_config(config_path: Path | None = None) -> AppConfig:
    """Load configuration from YAML file + environment variables.

    Args:
        config_path: Path to YAML config file. If None, loads from env vars only.
    """
    yaml_data = _load_yaml_config(config_path)

    if yaml_data:
        return AppConfig(**yaml_data, config_path=config_path)
    return AppConfig(config_path=config_path)
