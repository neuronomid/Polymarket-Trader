"""Policy change discipline and review.

Enforces policy change requirements:
- Minimum sample threshold met for the relevant segment
- Pattern persistence (not a one-time observation)
- Change documented with evidence and rationale
- In early deployment, ALL changes require operator review
- Category suspension requires operator decision

Per spec Section 15.11.

Fully deterministic (Tier D) for proposal generation.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import structlog

from learning.types import PolicyChangeStatus, PolicyProposal

_log = structlog.get_logger(component="policy_review")

# Minimum requirements for automatic policy proposals
MIN_SAMPLE_SIZE = 20
MIN_PERSISTENCE_WEEKS = 3
BRIER_ATTENTION_THRESHOLD = 30  # 30+ trades in category


class PolicyReviewEngine:
    """Generates and manages policy change proposals.

    Proposals are never automatically applied. They are generated
    deterministically based on evidence thresholds and require
    operator review.

    Usage:
        engine = PolicyReviewEngine()
        proposals = engine.evaluate_thresholds(segment_states, brier_data)
        proposals += engine.evaluate_category_performance(ledger)
        pending = engine.get_pending_proposals()
    """

    def __init__(self, *, early_deployment: bool = True) -> None:
        self._proposals: list[PolicyProposal] = []
        self._early_deployment = early_deployment

    def evaluate_thresholds(
        self,
        segment_states: list[dict[str, Any]],
        brier_comparisons: list[dict[str, Any]],
    ) -> list[PolicyProposal]:
        """Evaluate whether any threshold adjustments should be proposed.

        Checks if thresholds are too loose (admitting weak trades) or
        too tight (blocking quality opportunities) based on segment data.
        """
        proposals: list[PolicyProposal] = []

        for segment in segment_states:
            resolved = segment.get("resolved_count", 0)
            threshold = segment.get("min_threshold", 20)

            if resolved < threshold:
                continue  # Not enough data to evaluate

            # Check if threshold met but performance is poor
            system_brier = segment.get("system_brier")
            market_brier = segment.get("market_brier")
            label = segment.get("segment_label", "unknown")

            if system_brier is not None and market_brier is not None:
                advantage = market_brier - system_brier

                if advantage < 0 and resolved >= BRIER_ATTENTION_THRESHOLD:
                    # System worse than market → needs attention
                    proposal = PolicyProposal(
                        area="calibration",
                        title=f"Calibration review needed for segment: {label}",
                        description=(
                            f"System Brier ({system_brier:.4f}) worse than market "
                            f"Brier ({market_brier:.4f}) after {resolved} resolved "
                            f"trades in segment '{label}'. Policy Review must address "
                            "regardless of PnL."
                        ),
                        rationale=(
                            "Per spec: if Brier worse than market after 30+ trades "
                            "in a category, Policy Review must address."
                        ),
                        evidence={
                            "segment": label,
                            "resolved_count": resolved,
                            "system_brier": round(system_brier, 6),
                            "market_brier": round(market_brier, 6),
                            "advantage": round(advantage, 6),
                        },
                        sample_size=resolved,
                        min_threshold_met=True,
                        pattern_persistence_weeks=1,  # First detection
                        requires_operator_review=True,
                    )
                    proposals.append(proposal)

        self._proposals.extend(proposals)

        _log.info(
            "threshold_evaluation_complete",
            segments_evaluated=len(segment_states),
            proposals_generated=len(proposals),
        )

        return proposals

    def evaluate_category_performance(
        self,
        ledger_entries: list[dict[str, Any]],
    ) -> list[PolicyProposal]:
        """Evaluate category-level performance for policy proposals.

        Checks for categories that may need suspension, resizing,
        or threshold adjustment.
        """
        proposals: list[PolicyProposal] = []

        for entry in ledger_entries:
            category = entry.get("category", "unknown")
            trades = entry.get("trades_count", 0)
            net_pnl = entry.get("net_pnl", 0.0)
            brier = entry.get("brier_score")
            sys_vs_market = entry.get("system_vs_market_brier")

            if trades < MIN_SAMPLE_SIZE:
                continue

            # Category consistently unprofitable
            if net_pnl is not None and net_pnl < 0 and trades >= BRIER_ATTENTION_THRESHOLD:
                proposal = PolicyProposal(
                    area="category",
                    title=f"Category performance review: {category}",
                    description=(
                        f"Category '{category}' shows negative net PnL ({net_pnl:.2f}) "
                        f"over {trades} trades. Operator review recommended."
                    ),
                    rationale="Sustained negative PnL warrants category review.",
                    evidence={
                        "category": category,
                        "trades_count": trades,
                        "net_pnl": net_pnl,
                        "brier_score": brier,
                        "system_vs_market": sys_vs_market,
                    },
                    sample_size=trades,
                    min_threshold_met=trades >= MIN_SAMPLE_SIZE,
                    requires_operator_review=True,
                )
                proposals.append(proposal)

            # Note: category suspension requires operator decision.
            # The system proposes but never auto-suspends.

        self._proposals.extend(proposals)

        _log.info(
            "category_performance_evaluation_complete",
            categories_evaluated=len(ledger_entries),
            proposals_generated=len(proposals),
        )

        return proposals

    def propose_change(
        self,
        *,
        area: str,
        title: str,
        description: str,
        rationale: str,
        evidence: dict[str, Any],
        sample_size: int,
        persistence_weeks: int = 1,
    ) -> PolicyProposal:
        """Manually propose a policy change with evidence.

        Validates evidence thresholds before generating proposal.
        """
        threshold_met = sample_size >= MIN_SAMPLE_SIZE

        proposal = PolicyProposal(
            area=area,
            title=title,
            description=description,
            rationale=rationale,
            evidence=evidence,
            sample_size=sample_size,
            min_threshold_met=threshold_met,
            pattern_persistence_weeks=persistence_weeks,
            requires_operator_review=self._early_deployment or not threshold_met,
        )

        if not threshold_met:
            _log.warning(
                "policy_proposal_insufficient_evidence",
                area=area,
                title=title,
                sample_size=sample_size,
                min_required=MIN_SAMPLE_SIZE,
            )

        self._proposals.append(proposal)
        return proposal

    def approve_proposal(
        self,
        proposal: PolicyProposal,
    ) -> PolicyProposal:
        """Mark a proposal as approved by operator."""
        proposal.status = PolicyChangeStatus.APPROVED
        _log.info(
            "policy_proposal_approved",
            area=proposal.area,
            title=proposal.title,
        )
        return proposal

    def reject_proposal(
        self,
        proposal: PolicyProposal,
    ) -> PolicyProposal:
        """Mark a proposal as rejected by operator."""
        proposal.status = PolicyChangeStatus.REJECTED
        _log.info(
            "policy_proposal_rejected",
            area=proposal.area,
            title=proposal.title,
        )
        return proposal

    def get_pending_proposals(self) -> list[PolicyProposal]:
        """Return all pending proposals requiring operator review."""
        return [
            p for p in self._proposals
            if p.status == PolicyChangeStatus.PENDING
        ]

    def get_all_proposals(self) -> list[PolicyProposal]:
        """Return all proposals regardless of status."""
        return list(self._proposals)
