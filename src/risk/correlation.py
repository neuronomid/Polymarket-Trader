"""Correlation engine — prevents fake diversification.

Tracks five correlation dimensions: event, narrative, source dependency,
domain overlap, and catalyst overlap. Enforces exposure limits per cluster
and computes aggregate correlation burden scores.

Fully deterministic (Tier D). No LLM calls.
"""

from __future__ import annotations

from enum import Enum

import structlog

from config.settings import RiskConfig
from risk.types import CorrelationAssessment, PortfolioState, RiskRuleResult, SizingRequest


class CorrelationType(str, Enum):
    """Five dimensions of correlation tracked by the engine."""

    EVENT = "event"
    NARRATIVE = "narrative"
    SOURCE = "source"
    DOMAIN = "domain"
    CATALYST = "catalyst"


class ClusterEntry:
    """In-memory representation of a correlation cluster."""

    __slots__ = ("cluster_id", "cluster_type", "name", "max_exposure_usd", "current_exposure_usd", "position_ids")

    def __init__(
        self,
        cluster_id: str,
        cluster_type: CorrelationType,
        name: str,
        max_exposure_usd: float | None = None,
        current_exposure_usd: float = 0.0,
    ) -> None:
        self.cluster_id = cluster_id
        self.cluster_type = cluster_type
        self.name = name
        self.max_exposure_usd = max_exposure_usd
        self.current_exposure_usd = current_exposure_usd
        self.position_ids: list[str] = []


class CorrelationEngine:
    """Evaluates correlation risk for candidate trades.

    Maintains an in-memory registry of clusters. The Risk Governor
    populates clusters from the database at startup and keeps them
    updated as positions open/close.
    """

    def __init__(self, config: RiskConfig) -> None:
        self._config = config
        self._clusters: dict[str, ClusterEntry] = {}
        self._log = structlog.get_logger(component="correlation_engine")

    # --- Cluster management ---

    def register_cluster(
        self,
        cluster_id: str,
        cluster_type: CorrelationType,
        name: str,
        max_exposure_usd: float | None = None,
    ) -> None:
        """Register a cluster in the engine."""
        cap = max_exposure_usd or self._config.max_cluster_exposure_usd
        self._clusters[cluster_id] = ClusterEntry(
            cluster_id=cluster_id,
            cluster_type=cluster_type,
            name=name,
            max_exposure_usd=cap,
        )

    def add_exposure(self, cluster_id: str, position_id: str, exposure_usd: float) -> None:
        """Add exposure from a position to a cluster."""
        cluster = self._clusters.get(cluster_id)
        if cluster is None:
            return
        cluster.current_exposure_usd += exposure_usd
        if position_id not in cluster.position_ids:
            cluster.position_ids.append(position_id)

    def remove_exposure(self, cluster_id: str, position_id: str, exposure_usd: float) -> None:
        """Remove exposure when a position closes or reduces."""
        cluster = self._clusters.get(cluster_id)
        if cluster is None:
            return
        cluster.current_exposure_usd = max(0.0, cluster.current_exposure_usd - exposure_usd)
        if position_id in cluster.position_ids:
            cluster.position_ids.remove(position_id)

    def get_cluster(self, cluster_id: str) -> ClusterEntry | None:
        return self._clusters.get(cluster_id)

    # --- Assessment ---

    def assess(
        self,
        request: SizingRequest,
        portfolio: PortfolioState,
    ) -> CorrelationAssessment:
        """Evaluate correlation risk for a candidate trade.

        Checks all clusters the candidate belongs to and computes
        aggregate burden score.
        """
        if not request.cluster_ids:
            return CorrelationAssessment(passes=True, reason="No cluster memberships")

        violations: list[str] = []
        total_correlated = 0.0

        for cid in request.cluster_ids:
            cluster = self._clusters.get(cid)
            if cluster is None:
                continue

            total_correlated += cluster.current_exposure_usd
            cap = cluster.max_exposure_usd or self._config.max_cluster_exposure_usd
            if cluster.current_exposure_usd >= cap:
                violations.append(
                    f"Cluster '{cluster.name}' ({cluster.cluster_type.value}): "
                    f"${cluster.current_exposure_usd:.2f} >= ${cap:.2f}"
                )

        # Aggregate burden = correlated exposure / total portfolio exposure cap
        max_exposure = self._config.max_total_open_exposure_usd
        burden = total_correlated / max_exposure if max_exposure > 0 else 0.0
        burden = min(burden, 1.0)

        passes = len(violations) == 0 and burden <= self._config.max_correlation_burden_score

        if not passes and not violations:
            violations.append(
                f"Correlation burden {burden:.2f} exceeds max {self._config.max_correlation_burden_score:.2f}"
            )

        return CorrelationAssessment(
            burden_score=burden,
            cluster_violations=violations,
            total_correlated_exposure_usd=total_correlated,
            passes=passes,
            reason="; ".join(violations) if violations else "Correlation within limits",
        )

    def evaluate_rules(
        self,
        request: SizingRequest,
        portfolio: PortfolioState,
    ) -> list[RiskRuleResult]:
        """Evaluate correlation rules and return RiskRuleResults."""
        assessment = self.assess(request, portfolio)
        results: list[RiskRuleResult] = []

        # Overall correlation burden check
        results.append(RiskRuleResult(
            rule_name="correlation_burden",
            passed=assessment.burden_score <= self._config.max_correlation_burden_score,
            reason=f"Correlation burden: {assessment.burden_score:.2f}",
            threshold_value=self._config.max_correlation_burden_score,
            actual_value=assessment.burden_score,
        ))

        # Per-cluster violations
        for cid in request.cluster_ids:
            cluster = self._clusters.get(cid)
            if cluster is None:
                continue
            cap = cluster.max_exposure_usd or self._config.max_cluster_exposure_usd
            results.append(RiskRuleResult(
                rule_name=f"cluster_exposure_{cluster.cluster_type.value}",
                passed=cluster.current_exposure_usd < cap,
                reason=f"Cluster '{cluster.name}': ${cluster.current_exposure_usd:.2f} / ${cap:.2f}",
                threshold_value=cap,
                actual_value=cluster.current_exposure_usd,
                metadata={"cluster_id": cid, "cluster_type": cluster.cluster_type.value},
            ))

        return results
