"""Core shared types for the Polymarket Trader Agent.

Lightweight data containers used across module boundaries.
Domain-specific types belong in their respective modules.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


class WorkflowRunID(BaseModel):
    """Unique identifier for a workflow execution."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))


class MarketRef(BaseModel):
    """Minimal market reference used across modules."""

    market_id: str
    condition_id: str | None = None
    title: str = ""


class PositionRef(BaseModel):
    """Minimal position reference used across modules."""

    position_id: str
    market_id: str


class CostEstimate(BaseModel):
    """Pre-run cost estimate for a workflow step."""

    tier: str
    cost_class: str
    estimated_cost_usd: float
    description: str


class RuleDecisionRecord(BaseModel):
    """Record of a deterministic rule evaluation."""

    rule_name: str
    passed: bool
    reason: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))
    metadata: dict[str, Any] = Field(default_factory=dict)
