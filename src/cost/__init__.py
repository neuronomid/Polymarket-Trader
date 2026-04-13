"""Cost Governor & Budget System.

Deterministic cost control authority that prevents inference cost from
consuming expected edge. Every workflow must obtain Cost Governor pre-approval.

Public API:
    CostGovernor         — top-level orchestrator
    PreRunCostEstimator  — estimates cost before workflows
    BudgetTracker        — tracks daily/lifetime/per-position budgets
    SelectivityMonitor   — cost-of-selectivity tracking
    CumulativeReviewTracker — per-position review cost caps
    EstimateAccuracyTracker — estimate vs actual feedback loop
"""

from cost.budget import BudgetTracker
from cost.estimator import PreRunCostEstimator
from cost.feedback import EstimateAccuracyTracker
from cost.governor import CostGovernor
from cost.review_costs import CumulativeReviewTracker
from cost.selectivity import SelectivityMonitor
from cost.types import (
    AgentCostSpec,
    BudgetState,
    CostApproval,
    CostDecision,
    CostEstimate,
    CostEstimateRequest,
    CostRecordInput,
    EstimateAccuracy,
    LifetimeBudgetAlert,
    ReviewCostStatus,
    RunType,
    SelectivitySnapshot,
)

__all__ = [
    # Governor
    "CostGovernor",
    # Components
    "PreRunCostEstimator",
    "BudgetTracker",
    "SelectivityMonitor",
    "CumulativeReviewTracker",
    "EstimateAccuracyTracker",
    # Types
    "AgentCostSpec",
    "BudgetState",
    "CostApproval",
    "CostDecision",
    "CostEstimate",
    "CostEstimateRequest",
    "CostRecordInput",
    "EstimateAccuracy",
    "LifetimeBudgetAlert",
    "ReviewCostStatus",
    "RunType",
    "SelectivitySnapshot",
]
