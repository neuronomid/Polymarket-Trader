"""Agent registry — all agent roles with default tier, cost class, and metadata.

Maps every agent role to its model tier, cost class, agent category,
and description. This is the single source of truth for which agents
exist and what tier they run at.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from core.enums import CostClass, ModelTier


@dataclass(frozen=True)
class AgentRoleSpec:
    """Specification for a registered agent role."""

    role_name: str
    tier: ModelTier
    cost_class: CostClass
    description: str
    category: str = ""  # grouping category
    is_deterministic: bool = False  # Tier D is always True
    can_escalate_to_tier_a: bool = False  # whether this role may trigger Opus escalation


# --- Complete Agent Registry ---

_REGISTRY: dict[str, AgentRoleSpec] = {}


def _register(spec: AgentRoleSpec) -> AgentRoleSpec:
    """Register an agent role spec."""
    _REGISTRY[spec.role_name] = spec
    return spec


# ========================
# Tier A (Premium, Cost Class H)
# ========================

INVESTIGATOR_ORCHESTRATION = _register(AgentRoleSpec(
    role_name="investigator_orchestration",
    tier=ModelTier.A,
    cost_class=CostClass.H,
    description="Final synthesis, adversarial weighing, no-trade decisions",
    category="investigation",
    can_escalate_to_tier_a=False,  # Already Tier A
))

PERFORMANCE_ANALYZER = _register(AgentRoleSpec(
    role_name="performance_analyzer",
    tier=ModelTier.A,
    cost_class=CostClass.H,
    description="Weekly strategic synthesis with compression-first",
    category="performance",
    can_escalate_to_tier_a=False,  # Already Tier A
))

# ========================
# Tier B (Workhorse, Cost Class M)
# ========================

DOMAIN_MANAGER_POLITICS = _register(AgentRoleSpec(
    role_name="domain_manager_politics",
    tier=ModelTier.B,
    cost_class=CostClass.M,
    description="Politics domain analysis",
    category="domain_manager",
))

DOMAIN_MANAGER_GEOPOLITICS = _register(AgentRoleSpec(
    role_name="domain_manager_geopolitics",
    tier=ModelTier.B,
    cost_class=CostClass.M,
    description="Geopolitics domain analysis",
    category="domain_manager",
))

DOMAIN_MANAGER_SPORTS = _register(AgentRoleSpec(
    role_name="domain_manager_sports",
    tier=ModelTier.B,
    cost_class=CostClass.M,
    description="Sports domain analysis (quality-gated)",
    category="domain_manager",
))

DOMAIN_MANAGER_TECHNOLOGY = _register(AgentRoleSpec(
    role_name="domain_manager_technology",
    tier=ModelTier.B,
    cost_class=CostClass.M,
    description="Technology domain analysis",
    category="domain_manager",
))

DOMAIN_MANAGER_SCIENCE_HEALTH = _register(AgentRoleSpec(
    role_name="domain_manager_science_health",
    tier=ModelTier.B,
    cost_class=CostClass.M,
    description="Science & Health domain analysis",
    category="domain_manager",
))

DOMAIN_MANAGER_MACRO_POLICY = _register(AgentRoleSpec(
    role_name="domain_manager_macro_policy",
    tier=ModelTier.B,
    cost_class=CostClass.M,
    description="Macro/Policy domain analysis",
    category="domain_manager",
))

COUNTER_CASE = _register(AgentRoleSpec(
    role_name="counter_case",
    tier=ModelTier.B,
    cost_class=CostClass.M,
    description="Strongest structured case against thesis",
    category="investigation",
))

RESOLUTION_REVIEW = _register(AgentRoleSpec(
    role_name="resolution_review",
    tier=ModelTier.B,
    cost_class=CostClass.M,
    description="Resolution language review after deterministic parser",
    category="investigation",
))

TRADEABILITY_SYNTHESIZER = _register(AgentRoleSpec(
    role_name="tradeability_synthesizer",
    tier=ModelTier.B,
    cost_class=CostClass.M,
    description="Borderline ambiguity assessment",
    category="tradeability",
))

POSITION_REVIEW_ORCHESTRATION = _register(AgentRoleSpec(
    role_name="position_review_orchestration",
    tier=ModelTier.B,
    cost_class=CostClass.M,
    description="Position review on deterministic anomaly",
    category="position_review",
    can_escalate_to_tier_a=True,
))

THESIS_INTEGRITY = _register(AgentRoleSpec(
    role_name="thesis_integrity",
    tier=ModelTier.B,
    cost_class=CostClass.M,
    description="Thesis integrity on LLM-escalated review",
    category="position_review",
))

# ========================
# Tier C (Utility, Cost Class L)
# ========================

EVIDENCE_RESEARCH = _register(AgentRoleSpec(
    role_name="evidence_research",
    tier=ModelTier.C,
    cost_class=CostClass.L,
    description="Collect/compress/structure evidence",
    category="investigation",
))

TIMING_CATALYST = _register(AgentRoleSpec(
    role_name="timing_catalyst",
    tier=ModelTier.C,
    cost_class=CostClass.L,
    description="Timeline assessment",
    category="investigation",
))

MARKET_STRUCTURE_SUMMARY = _register(AgentRoleSpec(
    role_name="market_structure_summary",
    tier=ModelTier.C,
    cost_class=CostClass.L,
    description="Market structure summary (metrics are Tier D)",
    category="investigation",
))

UPDATE_EVIDENCE = _register(AgentRoleSpec(
    role_name="update_evidence",
    tier=ModelTier.C,
    cost_class=CostClass.L,
    description="Position review — update evidence sub-agent",
    category="position_review",
))

OPPOSING_SIGNAL = _register(AgentRoleSpec(
    role_name="opposing_signal",
    tier=ModelTier.C,
    cost_class=CostClass.L,
    description="Monitor opposing signals (complex → Tier B escalation)",
    category="position_review",
    can_escalate_to_tier_a=False,
))

CATALYST_SHIFT = _register(AgentRoleSpec(
    role_name="catalyst_shift",
    tier=ModelTier.C,
    cost_class=CostClass.L,
    description="Position review — catalyst shift sub-agent",
    category="position_review",
))

LIQUIDITY_DETERIORATION_SUMMARY = _register(AgentRoleSpec(
    role_name="liquidity_deterioration_summary",
    tier=ModelTier.C,
    cost_class=CostClass.L,
    description="Liquidity deterioration narrative (metrics are Tier D)",
    category="position_review",
))

JOURNAL_WRITER = _register(AgentRoleSpec(
    role_name="journal_writer",
    tier=ModelTier.C,
    cost_class=CostClass.L,
    description="Journal entries grounded in structured logs",
    category="utility",
))

ALERT_COMPOSER = _register(AgentRoleSpec(
    role_name="alert_composer",
    tier=ModelTier.C,
    cost_class=CostClass.L,
    description="Templated alert messages",
    category="utility",
))

DASHBOARD_EXPLANATION_HELPER = _register(AgentRoleSpec(
    role_name="dashboard_explanation_helper",
    tier=ModelTier.C,
    cost_class=CostClass.L,
    description="Dashboard explanation generation",
    category="utility",
))

BIAS_AUDIT_SUMMARY_WRITER = _register(AgentRoleSpec(
    role_name="bias_audit_summary_writer",
    tier=ModelTier.C,
    cost_class=CostClass.L,
    description="Bias audit narrative (detection is Tier D)",
    category="calibration",
))

VIABILITY_CHECKPOINT_SUMMARY_WRITER = _register(AgentRoleSpec(
    role_name="viability_checkpoint_summary_writer",
    tier=ModelTier.C,
    cost_class=CostClass.L,
    description="Viability checkpoint narrative (determination is Tier D)",
    category="calibration",
))

# ========================
# Tier D (No LLM, Cost Class Z) — Deterministic Only
# ========================

_TIER_D_ROLES: list[tuple[str, str, str]] = [
    ("risk_governor", "All capital controls", "risk"),
    ("cost_governor", "All arithmetic, budget enforcement, approval decisions", "cost"),
    ("execution_engine", "Pre-execution validation, order placement", "execution"),
    ("trigger_scanner", "Hot path, polling, detection", "scanner"),
    ("eligibility_gate", "Category classification, hard rules", "eligibility"),
    ("pre_run_cost_estimator", "Arithmetic, effective cost profile", "cost"),
    ("calibration_update_processor", "All statistical computation", "calibration"),
    ("entry_impact_calculator", "Order book arithmetic → estimated_impact_bps", "execution"),
    ("friction_model_calibrator", "Realized vs estimated slippage comparison", "execution"),
    ("bias_audit_processor", "5 statistical checks", "calibration"),
    ("strategy_viability_processor", "Brier comparison, threshold determination", "calibration"),
    ("operator_absence_manager", "Timestamp comparison, escalation, wind-down", "operator"),
    ("deterministic_position_review", "7 checks before LLM invocation", "position_review"),
    ("liquidity_sizing_enforcer", "Depth-based ceiling computation", "risk"),
    ("shadow_vs_market_comparator", "Weekly Brier computation", "calibration"),
    ("base_rate_lookup", "Historical resolution rates", "calibration"),
    ("cost_of_selectivity_calculator", "Daily ratio computation", "cost"),
    ("calibration_accumulation_projector", "Threshold timeline projection", "calibration"),
    ("clob_cache_manager", "Cache serving, eviction, freshness", "market_data"),
    ("lifetime_budget_tracker", "Consumption tracking, alerts", "cost"),
    ("patience_budget_tracker", "9-month default, expiry logic", "cost"),
]

for _role_name, _desc, _category in _TIER_D_ROLES:
    _register(AgentRoleSpec(
        role_name=_role_name,
        tier=ModelTier.D,
        cost_class=CostClass.Z,
        description=_desc,
        category=_category,
        is_deterministic=True,
    ))


# --- Registry Access ---


def get_role(role_name: str) -> AgentRoleSpec | None:
    """Get an agent role spec by name."""
    return _REGISTRY.get(role_name)


def get_all_roles() -> dict[str, AgentRoleSpec]:
    """Get all registered agent roles."""
    return dict(_REGISTRY)


def get_roles_by_tier(tier: ModelTier) -> list[AgentRoleSpec]:
    """Get all agent roles for a given tier."""
    return [spec for spec in _REGISTRY.values() if spec.tier == tier]


def get_roles_by_category(category: str) -> list[AgentRoleSpec]:
    """Get all agent roles for a given category."""
    return [spec for spec in _REGISTRY.values() if spec.category == category]


def get_domain_managers() -> list[AgentRoleSpec]:
    """Get all domain manager roles."""
    return get_roles_by_category("domain_manager")


def get_llm_roles() -> list[AgentRoleSpec]:
    """Get all roles that use LLM (Tier A, B, C)."""
    return [spec for spec in _REGISTRY.values() if spec.tier != ModelTier.D]


def get_deterministic_roles() -> list[AgentRoleSpec]:
    """Get all deterministic-only roles (Tier D)."""
    return get_roles_by_tier(ModelTier.D)


def domain_manager_for_category(category: str) -> AgentRoleSpec | None:
    """Get the domain manager for a given market category.

    Args:
        category: Category value (e.g., "politics", "sports").

    Returns:
        AgentRoleSpec for the domain manager, or None.
    """
    role_name = f"domain_manager_{category}"
    return _REGISTRY.get(role_name)
