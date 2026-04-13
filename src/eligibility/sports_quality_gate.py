"""Sports Quality Gate — five-criteria deterministic check.

Spec: Phase 4 Step 3 / Section 2.4.

Sports markets require:
1. Resolution fully objective (win/loss, final score)
2. Resolves in > 48 hours
3. Adequate liquidity and depth
4. Not primarily a statistical modeling problem
5. Credible evidential basis beyond public statistics

Sports markets carry a lower default size multiplier (0.7) than
Standard Tier categories until category calibration threshold (40 trades) met.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from config.settings import EligibilityConfig
from eligibility.types import SportsGateInput, SportsGateResult

_DEFAULT_CONFIG = EligibilityConfig()

# Default size multiplier for sports markets (reduced from 1.0)
_SPORTS_DEFAULT_SIZE_MULTIPLIER = 0.7

# Keywords that indicate objective resolution (win/loss, score, etc.)
_OBJECTIVE_RESOLUTION_KEYWORDS = {
    "win", "wins", "winner", "lose", "loss", "beat", "defeat",
    "score", "final score", "goals", "points", "sets",
    "champion", "championship", "title", "trophy",
    "qualify", "qualifies", "qualified", "advance", "advances",
    "gold medal", "silver medal", "bronze medal",
    "first place", "second place", "third place",
    "knockout", "decision", "submission",
    "finish", "podium",
}

# Keywords that suggest statistical modeling dominance
_STATISTICAL_MODELING_KEYWORDS = {
    "over/under", "over under", "spread", "point spread",
    "total points", "total goals", "total runs",
    "handicap", "prop bet", "player stats",
    "batting average", "yards", "rebounds",
    "saves percentage", "completion rate",
    "exact score", "correct score",
}

# Keywords that suggest credible evidential basis beyond stats
_EVIDENCE_BASIS_KEYWORDS = {
    "injury", "lineup", "roster", "coach", "strategy",
    "matchup", "venue", "home advantage", "form",
    "motivation", "fatigue", "schedule",
    "return from", "suspension", "eligibility",
    "weather conditions", "surface", "altitude",
    "historical record", "head to head",
}


def evaluate_sports_gate(
    market: SportsGateInput,
    config: EligibilityConfig | None = None,
) -> SportsGateResult:
    """Evaluate the five-criteria Sports Quality Gate.

    All checks are deterministic (Tier D). Any failed criterion
    produces a rejection reason.

    Args:
        market: Sports market data to evaluate.
        config: Eligibility configuration thresholds.

    Returns:
        SportsGateResult with per-criteria outcomes and size multiplier.
    """
    cfg = config or _DEFAULT_CONFIG
    rejection_reasons: list[str] = []

    # Criterion 1: Resolution fully objective
    resolution_objective = _check_objective_resolution(market)
    if not resolution_objective:
        rejection_reasons.append(
            "Resolution does not appear fully objective (win/loss/final score)"
        )

    # Criterion 2: Resolves in > 48 hours
    resolves_48h = _check_48h_horizon(market, cfg)
    if not resolves_48h:
        rejection_reasons.append(
            f"Resolves within {cfg.sports_min_horizon_hours}h — too short for sports"
        )

    # Criterion 3: Adequate liquidity and depth
    adequate_liquidity = _check_sports_liquidity(market, cfg)
    if not adequate_liquidity:
        rejection_reasons.append("Insufficient liquidity or depth for sports market")

    # Criterion 4: Not primarily a statistical modeling problem
    not_statistical = _check_not_statistical_modeling(market)
    if not not_statistical:
        rejection_reasons.append(
            "Market appears dominated by statistical modeling (e.g., over/under, spreads)"
        )

    # Criterion 5: Credible evidential basis beyond public statistics
    credible_evidence = _check_credible_evidence_basis(market)
    if not credible_evidence:
        rejection_reasons.append(
            "No credible evidential basis beyond publicly available statistics"
        )

    all_passed = len(rejection_reasons) == 0

    return SportsGateResult(
        resolution_fully_objective=resolution_objective,
        resolves_in_48h_plus=resolves_48h,
        adequate_liquidity_and_depth=adequate_liquidity,
        not_statistical_modeling=not_statistical,
        credible_evidential_basis=credible_evidence,
        all_criteria_passed=all_passed,
        size_multiplier=_SPORTS_DEFAULT_SIZE_MULTIPLIER if all_passed else 0.0,
        rejection_reasons=rejection_reasons,
    )


def _check_objective_resolution(market: SportsGateInput) -> bool:
    """Criterion 1: Resolution must be fully objective (win/loss, final score)."""
    text = f"{market.title} {market.description or ''} {market.resolution_source or ''}".lower()
    return any(keyword in text for keyword in _OBJECTIVE_RESOLUTION_KEYWORDS)


def _check_48h_horizon(market: SportsGateInput, cfg: EligibilityConfig) -> bool:
    """Criterion 2: Must resolve in more than 48 hours."""
    if market.end_date is None:
        # No end date — can't verify, fail safe
        return False

    now = datetime.now(tz=UTC)
    hours_remaining = (market.end_date - now).total_seconds() / 3600
    return hours_remaining >= cfg.sports_min_horizon_hours


def _check_sports_liquidity(market: SportsGateInput, cfg: EligibilityConfig) -> bool:
    """Criterion 3: Adequate liquidity and depth for sports markets."""
    # Sports markets require at least the standard minimum liquidity
    if market.liquidity_usd is None or market.liquidity_usd < cfg.min_liquidity_usd:
        return False

    # Also check spread if available
    if market.spread is not None and market.spread > cfg.max_spread:
        return False

    return True


def _check_not_statistical_modeling(market: SportsGateInput) -> bool:
    """Criterion 4: Not primarily a statistical modeling problem.

    Markets like point spreads, over/unders, and player prop bets
    are dominated by statistical models — our LLM reasoning offers
    no informational advantage there.
    """
    text = f"{market.title} {market.description or ''}".lower()
    # If there are strong statistical modeling markers, reject
    stat_matches = sum(1 for keyword in _STATISTICAL_MODELING_KEYWORDS if keyword in text)
    return stat_matches < 2  # Allow one passing mention, reject on 2+


def _check_credible_evidence_basis(market: SportsGateInput) -> bool:
    """Criterion 5: Credible evidential basis beyond public statistics.

    There must be some reason to believe thesis-based reasoning could
    add value — e.g., injury info, matchup dynamics, coaching changes.

    For deterministic evaluation, we check whether the market's context
    (title, description, tags) references factors beyond pure stats.
    """
    text = f"{market.title} {market.description or ''}".lower()

    # Check for evidence basis keywords
    evidence_matches = sum(
        1 for keyword in _EVIDENCE_BASIS_KEYWORDS if keyword in text
    )

    # Also consider tags as a signal
    tag_text = " ".join(market.tags).lower()
    tag_evidence = sum(
        1 for keyword in _EVIDENCE_BASIS_KEYWORDS if keyword in tag_text
    )

    # If we find NO evidence basis markers, we still pass if the market
    # is a simple win/loss market (those are inherently thesis-viable)
    if evidence_matches + tag_evidence >= 1:
        return True

    # For simple win/loss markets, we assume there's always a potential
    # evidential basis (lineup changes, injuries, form — even if not mentioned)
    for keyword in {"win", "winner", "beat", "champion", "qualify"}:
        if keyword in text:
            return True

    return False
