"""Eligibility Gate & Category Classification.

Phase 4: Deterministic market filtering pipeline that prevents excluded
categories and low-quality markets from reaching investigation.

All components are Tier D (no LLM calls).
"""

from eligibility.category_classifier import classify_category
from eligibility.edge_scoring import score_edge_discovery
from eligibility.engine import EligibilityEngine
from eligibility.hard_rules import check_all_hard_rules
from eligibility.market_profile import evaluate_market_profile
from eligibility.sports_quality_gate import evaluate_sports_gate
from eligibility.types import (
    CategoryClassification,
    EdgeDiscoveryScore,
    EligibilityReasonCode,
    HardRulesResult,
    MarketEligibilityInput,
    MarketEligibilityResult,
    MarketProfileScore,
    SportsGateResult,
)

__all__ = [
    "EligibilityEngine",
    "classify_category",
    "check_all_hard_rules",
    "evaluate_sports_gate",
    "evaluate_market_profile",
    "score_edge_discovery",
    "CategoryClassification",
    "EdgeDiscoveryScore",
    "EligibilityReasonCode",
    "HardRulesResult",
    "MarketEligibilityInput",
    "MarketEligibilityResult",
    "MarketProfileScore",
    "SportsGateResult",
]
