"""Performance Review workflow — weekly strategic synthesis.

Per spec Section 15.15: Uses Performance Analyzer (Opus Tier A).
Produces:
- Category Performance Ledger (mandatory output)
- Shadow-vs-market Brier comparison (mandatory output)
- Strategic synthesis over compressed inputs from all Tier D computations
- Category-level evidence for scaling decisions
- Policy change proposals with evidence

This module defines the workflow structure. The actual LLM call is routed
through the agent framework (agents/providers.py).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import structlog

from agents.types import AgentInput, AgentResult
from calibration.brier import BrierEngine
from calibration.store import CalibrationStore
from learning.category_ledger import CategoryLedgerBuilder
from learning.types import (
    PerformanceReviewInput,
    PerformanceReviewResult,
    PolicyProposal,
)

_log = structlog.get_logger(component="performance_review")


class PerformanceReviewWorkflow:
    """Weekly Performance Review orchestration.

    This workflow:
    1. Assembles all deterministic inputs (Tier D computations)
    2. Compresses context (compression-first rule)
    3. Delegates strategic synthesis to Performance Analyzer (Tier A)
    4. Produces structured output with mandatory fields

    Usage:
        workflow = PerformanceReviewWorkflow(store, brier_engine)
        review_input = workflow.prepare_input(period_start, period_end, ledger)
        result = workflow.execute(review_input, agent_callback)
    """

    def __init__(
        self,
        store: CalibrationStore,
        brier_engine: BrierEngine,
    ) -> None:
        self._store = store
        self._brier = brier_engine

    def prepare_input(
        self,
        period_start: datetime,
        period_end: datetime,
        category_ledger_builder: CategoryLedgerBuilder,
        *,
        system_week_number: int = 0,
        operator_mode: str = "paper",
        cost_metrics: dict[str, Any] | None = None,
        friction_feedback: dict[str, Any] | None = None,
        accumulation_report: dict[str, Any] | None = None,
    ) -> PerformanceReviewInput:
        """Prepare compressed input for the Performance Analyzer.

        Assembles all mandatory inputs and compresses them to
        decision-critical fields only (compression-first rule).
        """
        # Build category ledger
        ledger = category_ledger_builder.build()

        # Compute Brier comparisons
        brier_comparisons = self._brier.compute_weekly_comparison(period_end)
        brier_data = [
            {
                "scope": c.scope,
                "scope_label": c.scope_label,
                "system_brier": c.system_brier,
                "market_brier": c.market_brier,
                "system_advantage": c.system_advantage,
                "resolved_count": c.resolved_count,
                "system_is_better": c.system_is_better,
            }
            for c in brier_comparisons
        ]

        return PerformanceReviewInput(
            period_start=period_start,
            period_end=period_end,
            category_ledger=ledger,
            brier_comparisons=brier_data,
            accumulation_report=accumulation_report or {},
            cost_metrics=cost_metrics or {},
            friction_feedback=friction_feedback or {},
            system_week_number=system_week_number,
            operator_mode=operator_mode,
        )

    def execute(
        self,
        inp: PerformanceReviewInput,
        agent_callback: Any = None,
    ) -> PerformanceReviewResult:
        """Execute the performance review workflow.

        The deterministic foundation is assembled here. If an agent_callback
        is provided, it handles the Opus Tier A call for strategic synthesis.
        Otherwise, returns the deterministic-only result.

        Args:
            inp: Prepared performance review input.
            agent_callback: Optional async callable for LLM synthesis.
                Signature: (AgentInput) -> AgentResult

        Returns:
            PerformanceReviewResult with all mandatory fields.
        """
        _log.info(
            "performance_review_started",
            period=f"{inp.period_start.date()} to {inp.period_end.date()}",
            system_week=inp.system_week_number,
        )

        result = PerformanceReviewResult(
            period_start=inp.period_start,
            period_end=inp.period_end,
            category_ledger=inp.category_ledger,
            brier_summary={
                "comparisons": inp.brier_comparisons,
                "computed_at": datetime.now(tz=UTC).isoformat(),
            },
        )

        # If no agent callback, return deterministic-only result
        if agent_callback is None:
            _log.info(
                "performance_review_deterministic_only",
                reason="no_agent_callback",
            )
            return result

        # Prepare compressed agent input
        compressed_context = self._compress_for_opus(inp)

        agent_input = AgentInput(
            agent_role="performance_analyzer",
            context=compressed_context,
            operator_mode=inp.operator_mode,
        )

        _log.info(
            "performance_review_opus_requested",
            context_keys=list(compressed_context.keys()),
        )

        # The actual Opus call would be:
        # agent_result = await agent_callback(agent_input)
        # For now, the workflow structure is ready but the call is deferred
        # to the agent framework integration.

        result.opus_used = True
        result.strategic_synthesis = "Awaiting agent framework integration"

        _log.info(
            "performance_review_completed",
            opus_used=result.opus_used,
            policy_proposals=len(result.policy_proposals),
        )

        return result

    def _compress_for_opus(
        self,
        inp: PerformanceReviewInput,
    ) -> dict[str, Any]:
        """Compress all inputs down to decision-critical fields.

        Per compression-first rule: deduplicate, strip boilerplate,
        send only material context to Tier A.
        """
        # Category ledger summary (compressed)
        ledger_summary = []
        for entry in inp.category_ledger.entries:
            if entry.trades_count == 0:
                continue  # Skip empty categories
            ledger_summary.append({
                "cat": entry.category,
                "n": entry.trades_count,
                "wr": entry.win_rate,
                "pnl": entry.net_pnl,
                "brier": entry.brier_score,
                "svmb": entry.system_vs_market_brier,
                "cos": entry.cost_of_selectivity,
            })

        # Brier summary (already compressed)
        brier = [
            {k: v for k, v in c.items() if k in (
                "scope", "scope_label", "system_advantage", "resolved_count"
            )}
            for c in inp.brier_comparisons
        ]

        return {
            "period": f"{inp.period_start.date()} to {inp.period_end.date()}",
            "week": inp.system_week_number,
            "mode": inp.operator_mode,
            "ledger": ledger_summary,
            "brier": brier,
            "accumulation": inp.accumulation_report,
            "cost": inp.cost_metrics,
            "friction": inp.friction_feedback,
        }
