"""Agent framework types.

Structured input/output containers and tracking records used across the
agent framework. All agent I/O is typed and validated — no raw text.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from core.enums import (
    CalibrationRegime,
    CostClass,
    ModelTier,
    OperatorMode,
)


# --- Per-call LLM tracking ---


class LLMCallRecord(BaseModel):
    """Record of a single LLM API call.

    Every call is attributed to a workflow_run_id, and optionally
    to a market_id and position_id.
    """

    call_id: str = ""
    workflow_run_id: str = ""
    market_id: str | None = None
    position_id: str | None = None

    agent_role: str = ""
    provider: str = ""  # "anthropic" | "openai"
    model: str = ""
    tier: ModelTier = ModelTier.C
    cost_class: CostClass = CostClass.L

    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: float = 0.0
    actual_cost_usd: float = 0.0

    latency_ms: float = 0.0
    success: bool = True
    error: str | None = None

    called_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))


# --- Structured Agent I/O ---


class AgentInput(BaseModel):
    """Structured input to any agent.

    All agents receive structured context — never raw text blobs.
    The `context` dict carries domain-specific data; the metadata
    fields carry tracking and regime information.
    """

    workflow_run_id: str = ""
    market_id: str | None = None
    position_id: str | None = None

    agent_role: str = ""
    context: dict[str, Any] = Field(default_factory=dict)

    # Regime flags injected by the framework
    calibration_regime: CalibrationRegime = CalibrationRegime.INSUFFICIENT
    viability_proven: bool = False
    sports_quality_gated: bool = False
    cost_selectivity_ratio: float | None = None
    operator_mode: OperatorMode = OperatorMode.PAPER


class AgentResult(BaseModel):
    """Structured output from any agent.

    All agent outputs are typed and validated. The `result` dict
    carries domain-specific output; metadata tracks cost and success.
    """

    agent_role: str = ""
    success: bool = True
    result: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None

    # Cost tracking
    call_records: list[LLMCallRecord] = Field(default_factory=list)
    total_cost_usd: float = 0.0
    total_input_tokens: int = 0
    total_output_tokens: int = 0

    completed_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))

    def add_call_record(self, record: LLMCallRecord) -> None:
        """Add a call record and update aggregates."""
        self.call_records.append(record)
        self.total_cost_usd += record.actual_cost_usd
        self.total_input_tokens += record.input_tokens
        self.total_output_tokens += record.output_tokens


# --- Escalation Tracking ---


class EscalationRecord(BaseModel):
    """Record of a Tier A escalation decision.

    Every Tier A escalation must be logged with all required fields
    per spec Section 8.10.
    """

    workflow_run_id: str
    agent_role: str
    reason: str
    triggering_rule: str

    # Cost Governor context
    cost_governor_approved: bool
    cost_governor_approval_reason: str | None = None
    cost_selectivity_ratio_at_decision: float | None = None
    cumulative_position_review_cost: float | None = None

    # Outcome
    escalation_approved: bool
    actual_cost_usd: float | None = None
    model_used: str | None = None

    decided_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))


# --- Calibration & Regime Context ---


class CalibrationContext(BaseModel):
    """Calibration state passed to agents for regime-aware behavior."""

    regime: CalibrationRegime = CalibrationRegime.INSUFFICIENT
    viability_proven: bool = False
    sports_quality_gated: bool = False
    sports_resolved_trades: int = 0
    sports_calibration_threshold: int = 40
    system_brier_score: float | None = None
    market_brier_score: float | None = None

    @property
    def is_insufficient(self) -> bool:
        return self.regime == CalibrationRegime.INSUFFICIENT

    @property
    def is_viability_uncertain(self) -> bool:
        return self.regime == CalibrationRegime.VIABILITY_UNCERTAIN


class RegimeContext(BaseModel):
    """Full regime context assembled for agent execution.

    Combines calibration, operator mode, and cost state.
    """

    calibration: CalibrationContext = Field(default_factory=CalibrationContext)
    operator_mode: OperatorMode = OperatorMode.PAPER
    cost_selectivity_ratio: float | None = None
    daily_opus_budget_remaining: float | None = None
    daily_budget_remaining: float | None = None
