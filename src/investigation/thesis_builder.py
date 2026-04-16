"""Thesis card builder — constructs complete thesis cards.

Assembles all fields from spec Section 14.2 from the various
investigation sub-outputs (domain memo, research pack, entry impact,
base rate, rubric score, net edge calculation).
"""

from __future__ import annotations

from typing import Any

import structlog

from investigation.types import (
    BaseRateResult,
    CandidateContext,
    CandidateRubricScore,
    CalibrationSourceStatus,
    DomainMemo,
    EntryImpactResult,
    EntryUrgency,
    EvidenceItem,
    NetEdgeCalculation,
    ResearchPackResult,
    SizeBand,
    ThesisCardData,
)

_log = structlog.get_logger(component="thesis_card_builder")


class ThesisCardBuilder:
    """Builds complete thesis cards from investigation sub-outputs.

    Usage:
        builder = ThesisCardBuilder()
        card = builder.build(
            candidate=ctx,
            domain_memo=memo,
            research=pack,
            entry_impact=impact,
            base_rate=rate,
            rubric=score,
            net_edge=edge,
            orchestrator_output=synth,
            workflow_run_id="wf-123",
        )
    """

    def build(
        self,
        *,
        candidate: CandidateContext,
        domain_memo: DomainMemo,
        research: ResearchPackResult,
        entry_impact: EntryImpactResult,
        base_rate: BaseRateResult,
        rubric: CandidateRubricScore,
        net_edge: NetEdgeCalculation,
        orchestrator_output: dict[str, Any],
        workflow_run_id: str,
        inference_cost_usd: float = 0.0,
        sports_gate_result: dict[str, Any] | None = None,
    ) -> ThesisCardData:
        """Build a complete thesis card from all investigation sub-outputs.

        Args:
            candidate: Market context.
            domain_memo: Domain manager analysis.
            research: Research pack results.
            entry_impact: Entry impact computation.
            base_rate: Base rate lookup.
            rubric: Candidate rubric score.
            net_edge: Four-level net edge calculation.
            orchestrator_output: Final synthesis from orchestration agent.
            workflow_run_id: Workflow run identifier.
            inference_cost_usd: Total inference cost for this investigation.
            sports_gate_result: Sports Quality Gate result (if Sports).

        Returns:
            Complete ThesisCardData with all spec Section 14.2 fields.
        """
        # Extract orchestrator synthesis fields
        proposed_side = orchestrator_output.get("proposed_side", "yes")
        core_thesis = orchestrator_output.get("core_thesis", "")
        why_mispriced = orchestrator_output.get("why_mispriced", "")
        probability_estimate = orchestrator_output.get("probability_estimate")
        confidence_estimate = orchestrator_output.get("confidence_estimate")
        calibration_confidence = orchestrator_output.get("calibration_confidence")
        confidence_note = orchestrator_output.get("confidence_note")
        invalidation_conditions = orchestrator_output.get("invalidation_conditions", [])

        # Build evidence (top 3 each)
        supporting = self._build_supporting_evidence(research, orchestrator_output)
        opposing = self._build_opposing_evidence(research, orchestrator_output)

        # Resolution interpretation
        resolution_review = research.resolution_review or {}
        resolution_interpretation = resolution_review.get(
            "resolution_interpretation", ""
        )
        resolution_source_language = resolution_review.get(
            "source_language",
            candidate.resolution_source,
        )

        # Timing
        timing = research.timing_assessment or {}
        expected_catalyst = timing.get("expected_catalyst")
        expected_time_horizon = timing.get("expected_time_horizon")
        expected_time_horizon_hours = timing.get("expected_time_horizon_hours")

        # Risk summaries
        resolution_risk_summary = orchestrator_output.get(
            "resolution_risk_summary",
            "; ".join(resolution_review.get("ambiguity_flags", [])),
        )
        market_structure = research.market_structure or {}
        market_structure_summary = market_structure.get("summary", "")

        # Market implied probability
        market_implied = candidate.mid_price or candidate.price or 0.5

        # Friction estimates
        spread_friction = candidate.spread or 0.0
        slippage_estimate = entry_impact.estimated_impact_bps / 10_000 if entry_impact else 0.0

        # Sizing
        size_band = self._determine_size_band(net_edge, rubric)
        urgency = self._determine_urgency(timing, candidate)
        max_size = candidate.visible_depth_usd * 0.12

        # Calibration source status
        calibration_status = self._determine_calibration_status(
            base_rate.sample_size, base_rate.confidence_level
        )

        card = ThesisCardData(
            # Identifiers
            market_id=candidate.market_id,
            workflow_run_id=workflow_run_id,

            # Core thesis
            category=candidate.category,
            category_quality_tier=candidate.category_quality_tier,
            proposed_side=proposed_side,
            resolution_interpretation=resolution_interpretation,
            resolution_source_language=resolution_source_language,
            core_thesis=core_thesis,
            why_mispriced=why_mispriced,

            # Evidence (top 3)
            supporting_evidence=supporting[:3],
            opposing_evidence=opposing[:3],

            # Catalysts and timing
            expected_catalyst=expected_catalyst,
            expected_time_horizon=expected_time_horizon,
            expected_time_horizon_hours=expected_time_horizon_hours,

            # Invalidation
            invalidation_conditions=invalidation_conditions,

            # Risk summaries
            resolution_risk_summary=resolution_risk_summary,
            market_structure_summary=market_structure_summary,

            # Quality scores
            evidence_quality_score=rubric.evidence_quality,
            evidence_diversity_score=rubric.evidence_diversity,
            ambiguity_score=rubric.ambiguity_level,

            # Calibration
            calibration_source_status=calibration_status,
            raw_model_probability=probability_estimate,
            calibrated_probability=orchestrator_output.get("calibrated_probability"),
            calibration_segment_label=orchestrator_output.get("calibration_segment_label"),

            # Section 23: Three separate confidence fields
            probability_estimate=probability_estimate,
            confidence_estimate=confidence_estimate,
            calibration_confidence=calibration_confidence,
            confidence_note=confidence_note,

            # Section 14.3: Four-level net edge distinction
            gross_edge=net_edge.gross_edge,
            friction_adjusted_edge=net_edge.friction_adjusted_edge,
            impact_adjusted_edge=net_edge.impact_adjusted_edge,
            net_edge_after_cost=net_edge.net_edge_after_cost,

            # Friction and impact
            expected_friction_spread=spread_friction,
            expected_friction_slippage=slippage_estimate,
            entry_impact_estimate_bps=entry_impact.estimated_impact_bps,
            expected_inference_cost_usd=inference_cost_usd,

            # Sizing and urgency
            recommended_size_band=size_band,
            urgency_of_entry=urgency,
            liquidity_adjusted_max_size_usd=max_size,

            # Trigger and market context
            trigger_source=candidate.trigger_class,
            market_implied_probability=market_implied,
            base_rate=base_rate.base_rate,
            base_rate_deviation=base_rate.deviation_from_estimate,

            # Sports quality gate
            sports_quality_gate_result=sports_gate_result,

            # Rubric
            rubric_score=rubric,
        )

        _log.info(
            "thesis_card_built",
            market_id=candidate.market_id,
            proposed_side=proposed_side,
            gross_edge=net_edge.gross_edge,
            net_edge=net_edge.net_edge_after_cost,
            size_band=size_band,
            evidence_quality=rubric.evidence_quality,
        )

        return card

    # --- Private helpers ---

    def _build_supporting_evidence(
        self,
        research: ResearchPackResult,
        orchestrator_output: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Build top 3 supporting evidence items with source and freshness."""
        # Prefer orchestrator's selection
        orch_supporting = orchestrator_output.get("supporting_evidence", [])
        if orch_supporting:
            return [self._normalize_evidence_item(item) for item in orch_supporting[:3]]

        # Fallback: highest relevance from research
        sorted_evidence = sorted(
            research.evidence,
            key=lambda e: e.relevance_score,
            reverse=True,
        )
        return [
            self._normalize_evidence_item(e)
            for e in sorted_evidence[:3]
        ]

    def _build_opposing_evidence(
        self,
        research: ResearchPackResult,
        orchestrator_output: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Build top 3 opposing evidence items from counter-case."""
        # Prefer orchestrator's selection
        orch_opposing = orchestrator_output.get("opposing_evidence", [])
        if orch_opposing:
            return [self._normalize_evidence_item(item) for item in orch_opposing[:3]]

        # Fallback: from counter-case agent
        counter = research.counter_case
        arguments = counter.get("strongest_arguments_against", [])
        return [
            self._normalize_evidence_item(
                {
                    "content": arg,
                    "source": "counter_case_agent",
                    "freshness": "current",
                }
            )
            for arg in arguments[:3]
        ]

    def _normalize_evidence_item(
        self,
        item: EvidenceItem | dict[str, Any] | str,
    ) -> dict[str, Any]:
        """Normalize evidence payloads from research and synthesis output."""
        if isinstance(item, EvidenceItem):
            return {
                "content": item.content,
                "source": item.source,
                "freshness": item.freshness,
            }

        if isinstance(item, str):
            return {
                "content": item,
                "source": "orchestrator",
                "freshness": "unknown",
            }

        if isinstance(item, dict):
            content = item.get("content")
            if not content:
                content = str(item)
            return {
                "content": content,
                "source": item.get("source", "orchestrator"),
                "freshness": item.get("freshness", "unknown"),
            }

        return {
            "content": str(item),
            "source": "orchestrator",
            "freshness": "unknown",
        }

    def _determine_size_band(
        self,
        net_edge: NetEdgeCalculation,
        rubric: CandidateRubricScore,
    ) -> str:
        """Determine recommended position size band."""
        edge = net_edge.impact_adjusted_edge

        if edge > 0.08 and rubric.composite_score > 0.6:
            return SizeBand.LARGE.value
        if edge > 0.05 and rubric.composite_score > 0.4:
            return SizeBand.STANDARD.value
        if edge > 0.02:
            return SizeBand.SMALL.value
        return SizeBand.MINIMUM.value

    def _determine_urgency(
        self,
        timing: dict[str, Any],
        candidate: CandidateContext,
    ) -> str:
        """Determine entry urgency based on timing assessment."""
        pressure = timing.get("time_pressure", "none")
        hours = timing.get("expected_time_horizon_hours")

        if pressure == "high" or (hours is not None and hours < 24):
            return EntryUrgency.IMMEDIATE.value
        if pressure == "medium" or (hours is not None and hours < 72):
            return EntryUrgency.WITHIN_HOURS.value
        if hours is not None and hours < 168:
            return EntryUrgency.WITHIN_DAY.value
        return EntryUrgency.LOW.value

    def _determine_calibration_status(
        self,
        sample_size: int,
        confidence_level: str,
    ) -> str:
        """Determine calibration source status."""
        if sample_size == 0:
            return CalibrationSourceStatus.NO_DATA.value
        if confidence_level in ("none", "low"):
            return CalibrationSourceStatus.INSUFFICIENT.value
        if confidence_level == "medium":
            return CalibrationSourceStatus.PRELIMINARY.value
        return CalibrationSourceStatus.RELIABLE.value
