"""Learning System — Phase 12.

Fast (daily) and slow (weekly) learning loops, category performance ledger,
no-trade rate monitoring, patience budget tracking, policy review engine,
and performance review workflow.

Deterministic substrate is Tier D. Strategic synthesis uses Tier A (Opus)
via the Performance Analyzer agent through the agent framework.
"""

from learning.types import (
    CategoryLedgerEntry,
    CategoryLedgerReport,
    FastLoopInput,
    FastLoopResult,
    LearningLoopType,
    NoTradeRateMetrics,
    NoTradeRateSignal,
    PatienceBudgetState,
    PatienceDecision,
    PerformanceReviewInput,
    PerformanceReviewResult,
    PolicyChangeStatus,
    PolicyProposal,
    SlowLoopInput,
    SlowLoopResult,
)
from learning.category_ledger import CategoryLedgerBuilder
from learning.no_trade_monitor import NoTradeMonitor
from learning.patience_budget import PatienceBudgetTracker
from learning.policy_review import PolicyReviewEngine
from learning.fast_loop import FastLearningLoop
from learning.slow_loop import SlowLearningLoop
from learning.performance_review import PerformanceReviewWorkflow

__all__ = [
    # Types
    "CategoryLedgerEntry",
    "CategoryLedgerReport",
    "FastLoopInput",
    "FastLoopResult",
    "LearningLoopType",
    "NoTradeRateMetrics",
    "NoTradeRateSignal",
    "PatienceBudgetState",
    "PatienceDecision",
    "PerformanceReviewInput",
    "PerformanceReviewResult",
    "PolicyChangeStatus",
    "PolicyProposal",
    "SlowLoopInput",
    "SlowLoopResult",
    # Components
    "CategoryLedgerBuilder",
    "NoTradeMonitor",
    "PatienceBudgetTracker",
    "PolicyReviewEngine",
    "FastLearningLoop",
    "SlowLearningLoop",
    "PerformanceReviewWorkflow",
]
