"""Model philosophy and provider strategy constants.

Encodes the 11 V4 model principles and provider-model mapping as system constants.
These are not configuration — they are architectural invariants.
"""

from core.enums import CostClass, ModelTier

# --- V4 Model Philosophy Principles ---
# These are system invariants, not tunable parameters.

MODEL_PRINCIPLES: list[str] = [
    "Deterministic checks before any LLM call.",
    "Pre-run cost estimation before any multi-LLM workflow.",
    "Deterministic-first position review before LLM-based review.",
    "Cheap models for compression, extraction, formatting, and repetitive utility work.",
    "Workhorse models for repeated, meaningful reasoning tasks.",
    "Premium models only at high-value synthesis or high-risk decision bottlenecks.",
    "One primary provider stack for most reasoning. One secondary for selective fallback.",
    "Every premium escalation must be explainable and logged.",
    "No LLM in any deterministic safety or risk control zone.",
    "No LLM for statistical computation, metric calculation, or bias detection arithmetic.",
    "No LLM for auditing its own reasoning biases — bias detection is statistical.",
]

# --- Provider Strategy ---

PROVIDER_MODEL_MAP: dict[ModelTier, dict[str, str]] = {
    ModelTier.A: {
        "provider": "anthropic",
        "model": "claude-opus-4-6",
        "description": "Premium: final synthesis, adversarial review, weekly performance",
    },
    ModelTier.B: {
        "provider": "anthropic",
        "model": "claude-sonnet-4-6",
        "description": "Workhorse: domain analysis, counter-case, tradeability, position review",
    },
    ModelTier.C: {
        "provider": "openai",
        "model": "gpt-5.4-nano",
        "description": "Utility: journals, alerts, evidence extraction, summaries",
    },
    ModelTier.D: {
        "provider": "none",
        "model": "deterministic",
        "description": "No LLM: risk/cost governor, execution, scanner, calibration, statistics",
    },
}

# Alternative utility model for complex Tier C tasks
TIER_C_ALTERNATIVE_MODEL = "gpt-5.4-mini"

# --- Cost Class Ranges (USD per call) ---

COST_CLASS_RANGES: dict[CostClass, tuple[float, float]] = {
    CostClass.H: (0.05, 0.30),
    CostClass.M: (0.01, 0.05),
    CostClass.L: (0.001, 0.005),
    CostClass.Z: (0.0, 0.0),
}

# Model tier to cost class mapping
TIER_COST_CLASS: dict[ModelTier, CostClass] = {
    ModelTier.A: CostClass.H,
    ModelTier.B: CostClass.M,
    ModelTier.C: CostClass.L,
    ModelTier.D: CostClass.Z,
}

# --- Effective Cost Profile for Position Review (V4) ---
# Most reviews complete deterministically (no LLM cost).

POSITION_REVIEW_COST_PROFILE: dict[str, float] = {
    "deterministic_only_pct": 0.65,  # ~65% of reviews: Tier D, $0 LLM cost
    "workhorse_escalation_pct": 0.25,  # ~25% escalate to Tier B (Sonnet)
    "premium_escalation_pct": 0.10,  # ~10% escalate to Tier A (Opus)
}

# --- Deterministic-Only Zones ---
# These components must NEVER invoke an LLM. This list is for documentation
# and can be used for runtime validation.

DETERMINISTIC_ONLY_COMPONENTS: frozenset[str] = frozenset(
    {
        "risk_governor",
        "cost_governor",
        "execution_engine",
        "trigger_scanner",
        "calibration_statistics",
        "entry_impact_computation",
        "realized_slippage_computation",
        "liquidity_sizing_enforcement",
        "operator_absence_logic",
        "bias_audit_statistics",
        "cost_of_selectivity_computation",
        "calibration_accumulation_projections",
        "shadow_vs_market_brier_comparison",
        "lifetime_budget_tracking",
        "drawdown_enforcement",
        "exposure_limits",
        "kill_switch_logic",
        "eligibility_hard_gates",
        "resolution_parser_core_rules",
        "sports_quality_gate_deterministic",
        "friction_model",
        "clob_cache",
        "base_rate_lookup",
        "position_review_deterministic_checks",
    }
)

# --- Category Configuration ---

CATEGORY_QUALITY_TIERS: dict[str, str] = {
    "politics": "standard",
    "geopolitics": "standard",
    "technology": "standard",
    "science_health": "standard",
    "macro_policy": "standard",
    "sports": "quality_gated",
}

# Sports calibration threshold before normal sizing allowed
SPORTS_CALIBRATION_THRESHOLD = 40  # resolved trades
