"""Weekly/biweekly slow learning loop.

Produces the Category Performance Ledger, domain analysis, agent usefulness
review, threshold evaluation, policy change proposals, Brier comparison,
accumulation projections, and friction model accuracy review.

Per spec Section 15.10.

The deterministic substrate runs here (Tier D). The Performance Analyzer
(Opus Tier A) strategic synthesis runs separately in performance_review.py.
"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog

from calibration.accumulation import AccumulationTracker
from calibration.brier import BrierEngine
from calibration.friction import FrictionCalibrator
from calibration.segments import SegmentManager
from learning.no_trade_monitor import NoTradeMonitor
from learning.policy_review import PolicyReviewEngine
from learning.types import SlowLoopInput, SlowLoopResult

_log = structlog.get_logger(component="slow_learning_loop")


class SlowLearningLoop:
    """Weekly/biweekly learning loop — comprehensive analysis and proposals.

    Per spec Section 15.10:
    - Category ledger update
    - Domain and category analysis
    - Agent usefulness by role
    - Prompt and evidence source quality
    - Threshold review (too loose? too tight?)
    - Policy change proposals with evidence
    - Shadow-vs-market Brier comparison
    - Bias audit report (computed separately)
    - Calibration accumulation projections
    - Strategy viability assessment
    - Friction model accuracy review

    Usage:
        loop = SlowLearningLoop(
            brier_engine, segment_manager, accumulation_tracker,
            friction_calibrator, policy_engine, no_trade_monitor,
        )
        result = loop.execute(input_data)
    """

    def __init__(
        self,
        brier_engine: BrierEngine,
        segment_manager: SegmentManager,
        accumulation_tracker: AccumulationTracker,
        friction_calibrator: FrictionCalibrator,
        policy_engine: PolicyReviewEngine,
        no_trade_monitor: NoTradeMonitor,
    ) -> None:
        self._brier = brier_engine
        self._segments = segment_manager
        self._accumulation = accumulation_tracker
        self._friction = friction_calibrator
        self._policy = policy_engine
        self._no_trade = no_trade_monitor

    def execute(self, inp: SlowLoopInput) -> SlowLoopResult:
        """Execute the slow learning loop.

        Produces all deterministic analyses and policy proposals.
        The Opus-level strategic synthesis is NOT done here — that's
        in performance_review.py via the Performance Analyzer agent.
        """
        _log.info(
            "slow_loop_started",
            as_of=inp.as_of.isoformat(),
            period_weeks=inp.period_weeks,
        )

        result = SlowLoopResult(executed_at=inp.as_of)

        # 1. Brier comparison
        brier_comparisons = self._brier.compute_weekly_comparison(inp.as_of)
        result.brier_comparison_included = len(brier_comparisons) > 0

        _log.info(
            "brier_comparison_computed",
            comparisons_count=len(brier_comparisons),
        )

        # 2. Accumulation projections
        accum_report = self._accumulation.compute_weekly_projections(inp.as_of)
        result.accumulation_projection_included = True

        if accum_report.bottleneck_segments:
            result.warnings.append(
                f"Calibration bottleneck segments: {', '.join(accum_report.bottleneck_segments)}"
            )

        _log.info(
            "accumulation_projections_computed",
            bottlenecks=len(accum_report.bottleneck_segments),
            pace=accum_report.overall_pace,
        )

        # 3. Friction model review
        friction_feedback = self._friction.evaluate()
        result.friction_review_included = True

        if friction_feedback.needs_tightening or friction_feedback.can_relax:
            result.warnings.append(
                f"Friction model needs adjustment: ratio={friction_feedback.mean_slippage_ratio:.4f}"
            )

        # 4. Segment state evaluation for policy proposals
        segment_states = self._segments.compute_all_segment_states()
        segment_dicts = [
            {
                "segment_type": s.segment_type.value,
                "segment_label": s.segment_label,
                "resolved_count": s.resolved_count,
                "min_threshold": s.min_threshold,
                "system_brier": s.system_brier,
                "market_brier": s.market_brier,
                "regime": s.regime.value,
            }
            for s in segment_states
        ]

        brier_dicts = [
            {
                "scope": c.scope,
                "scope_label": c.scope_label,
                "system_brier": c.system_brier,
                "market_brier": c.market_brier,
                "system_advantage": c.system_advantage,
                "resolved_count": c.resolved_count,
            }
            for c in brier_comparisons
        ]

        # 5. Threshold evaluation
        threshold_proposals = self._policy.evaluate_thresholds(
            segment_dicts, brier_dicts
        )
        result.threshold_review_complete = True

        # 6. Category performance evaluation
        category_proposals: list = []
        if inp.category_ledger is not None:
            ledger_dicts = [
                {
                    "category": e.category,
                    "trades_count": e.trades_count,
                    "net_pnl": e.net_pnl,
                    "brier_score": e.brier_score,
                    "system_vs_market_brier": e.system_vs_market_brier,
                }
                for e in inp.category_ledger.entries
            ]
            category_proposals = self._policy.evaluate_category_performance(ledger_dicts)
            result.category_analysis_complete = True

            # Categories needing attention
            for entry in inp.category_ledger.entries:
                if entry.net_pnl is not None and entry.net_pnl < 0 and entry.trades_count >= 20:
                    result.categories_needing_attention.append(entry.category)

        # 7. Agent usefulness review (deterministic tracking)
        if inp.agent_usage_by_role:
            result.agent_usefulness_reviewed = True
            for role, usage in inp.agent_usage_by_role.items():
                cost = usage.get("total_cost_usd", 0)
                calls = usage.get("total_calls", 0)
                success_rate = usage.get("success_rate", 1.0)

                if success_rate < 0.5 and calls >= 10:
                    result.underperforming_agents.append(role)

        # Collect all proposals
        all_proposals = threshold_proposals + category_proposals
        result.policy_proposals_generated = len(all_proposals)
        result.policy_proposals = all_proposals

        _log.info(
            "slow_loop_completed",
            brier_included=result.brier_comparison_included,
            accumulation_included=result.accumulation_projection_included,
            friction_reviewed=result.friction_review_included,
            threshold_reviewed=result.threshold_review_complete,
            category_analyzed=result.category_analysis_complete,
            agent_reviewed=result.agent_usefulness_reviewed,
            proposals_count=len(all_proposals),
            warnings_count=len(result.warnings),
        )

        return result
