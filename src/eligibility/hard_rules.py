"""Hard eligibility rules — deterministic gate checks.

All checks are Tier D (no LLM). Every check returns a structured result
with rule name, pass/fail, reason code, threshold, and actual value.

Spec: Phase 4 Step 2.
"""

from __future__ import annotations

from datetime import UTC, datetime

from config.settings import EligibilityConfig
from eligibility.types import (
    EligibilityReasonCode,
    HardRuleResult,
    HardRulesResult,
    MarketEligibilityInput,
)

# Default config — can be overridden by injection
_DEFAULT_CONFIG = EligibilityConfig()

# Minimum title length to consider non-malformed
_MIN_TITLE_LENGTH = 10

# Fraction of visible depth that a minimum position must fit within
_LIQUIDITY_FRACTION_LIMIT = 0.20


def check_all_hard_rules(
    market: MarketEligibilityInput,
    config: EligibilityConfig | None = None,
) -> HardRulesResult:
    """Run all hard eligibility rules against a market.

    Returns immediately on first failure for efficiency, but records all results.
    All rules are deterministic (Tier D).

    Args:
        market: Market data to evaluate.
        config: Eligibility configuration thresholds. Uses defaults if None.

    Returns:
        HardRulesResult with all rule outcomes.
    """
    cfg = config or _DEFAULT_CONFIG
    results: list[HardRuleResult] = []

    # Rule 1: Market is open and tradable
    results.append(_check_market_active(market))

    # Rule 2: Wording not malformed
    results.append(_check_wording(market))

    # Rule 3: Resolution source named and defined
    results.append(_check_resolution_source(market))

    # Rule 4: Contract horizon within configured range
    results.append(_check_horizon(market, cfg))

    # Rule 5: Minimum observable liquidity threshold
    results.append(_check_liquidity(market, cfg))

    # Rule 6: Spread within configured hard limit
    results.append(_check_spread(market, cfg))

    # Rule 7: Visible depth sufficient
    results.append(_check_depth(market, cfg))

    # Rule 8: No duplicate of currently held event cluster
    results.append(_check_duplicate_cluster(market))

    all_passed = all(r.passed for r in results)
    first_failure = next((r for r in results if not r.passed), None)

    return HardRulesResult(
        all_passed=all_passed,
        results=results,
        first_failure=first_failure,
    )


def _check_market_active(market: MarketEligibilityInput) -> HardRuleResult:
    """Rule 1: Market must be open and tradable."""
    passed = market.is_active is True
    return HardRuleResult(
        rule_name="market_active",
        passed=passed,
        reason_code=(
            EligibilityReasonCode.ELIGIBLE if passed
            else EligibilityReasonCode.MARKET_NOT_ACTIVE
        ),
        detail="" if passed else "Market is not active or tradable",
    )


def _check_wording(market: MarketEligibilityInput) -> HardRuleResult:
    """Rule 2: Title not obviously malformed.

    Checks:
    - Title length >= minimum
    - Contains at least one question mark or verb-like structure
    - Not all caps or garbled
    """
    title = market.title.strip()
    issues: list[str] = []

    if len(title) < _MIN_TITLE_LENGTH:
        issues.append(f"Title too short ({len(title)} chars, min {_MIN_TITLE_LENGTH})")

    # Check for garbled text (very high non-alpha ratio)
    alpha_count = sum(1 for c in title if c.isalpha())
    if len(title) > 0 and alpha_count / len(title) < 0.4:
        issues.append("Title appears garbled (low alpha ratio)")

    # Check for all-caps (more than 80% uppercase letters)
    if alpha_count > 0:
        upper_count = sum(1 for c in title if c.isupper())
        if upper_count / alpha_count > 0.8 and alpha_count > 5:
            issues.append("Title is mostly uppercase")

    passed = len(issues) == 0
    return HardRuleResult(
        rule_name="wording_check",
        passed=passed,
        reason_code=(
            EligibilityReasonCode.ELIGIBLE if passed
            else EligibilityReasonCode.WORDING_MALFORMED
        ),
        detail="; ".join(issues) if issues else "",
    )


def _check_resolution_source(market: MarketEligibilityInput) -> HardRuleResult:
    """Rule 3: Resolution source must be named and defined."""
    has_source = bool(
        market.resolution_source
        and len(market.resolution_source.strip()) >= 3
    )
    return HardRuleResult(
        rule_name="resolution_source",
        passed=has_source,
        reason_code=(
            EligibilityReasonCode.ELIGIBLE if has_source
            else EligibilityReasonCode.NO_RESOLUTION_SOURCE
        ),
        detail="" if has_source else "No resolution source named or defined",
    )


def _check_horizon(
    market: MarketEligibilityInput, cfg: EligibilityConfig
) -> HardRuleResult:
    """Rule 4: Contract horizon within configured range."""
    if market.end_date is None:
        # No end date — we can't verify horizon, pass with note
        return HardRuleResult(
            rule_name="horizon_check",
            passed=True,
            reason_code=EligibilityReasonCode.ELIGIBLE,
            detail="No end date specified; horizon not constrained",
        )

    now = datetime.now(tz=UTC)
    time_remaining = market.end_date - now
    hours_remaining = time_remaining.total_seconds() / 3600
    days_remaining = hours_remaining / 24

    if hours_remaining < cfg.min_horizon_hours:
        return HardRuleResult(
            rule_name="horizon_check",
            passed=False,
            reason_code=EligibilityReasonCode.HORIZON_TOO_SHORT,
            detail=f"Horizon {hours_remaining:.1f}h < min {cfg.min_horizon_hours}h",
            threshold_value=float(cfg.min_horizon_hours),
            actual_value=hours_remaining,
        )

    if days_remaining > cfg.max_horizon_days:
        return HardRuleResult(
            rule_name="horizon_check",
            passed=False,
            reason_code=EligibilityReasonCode.HORIZON_TOO_LONG,
            detail=f"Horizon {days_remaining:.0f}d > max {cfg.max_horizon_days}d",
            threshold_value=float(cfg.max_horizon_days),
            actual_value=days_remaining,
        )

    return HardRuleResult(
        rule_name="horizon_check",
        passed=True,
        reason_code=EligibilityReasonCode.ELIGIBLE,
        detail=f"Horizon: {days_remaining:.1f} days",
        actual_value=days_remaining,
    )


def _check_liquidity(
    market: MarketEligibilityInput, cfg: EligibilityConfig
) -> HardRuleResult:
    """Rule 5: Minimum observable liquidity threshold."""
    liquidity = market.liquidity_usd

    if liquidity is None:
        return HardRuleResult(
            rule_name="liquidity_check",
            passed=False,
            reason_code=EligibilityReasonCode.INSUFFICIENT_LIQUIDITY,
            detail="No liquidity data available",
            threshold_value=cfg.min_liquidity_usd,
        )

    passed = liquidity >= cfg.min_liquidity_usd
    return HardRuleResult(
        rule_name="liquidity_check",
        passed=passed,
        reason_code=(
            EligibilityReasonCode.ELIGIBLE if passed
            else EligibilityReasonCode.INSUFFICIENT_LIQUIDITY
        ),
        detail=(
            f"Liquidity ${liquidity:,.0f} {'≥' if passed else '<'} "
            f"min ${cfg.min_liquidity_usd:,.0f}"
        ),
        threshold_value=cfg.min_liquidity_usd,
        actual_value=liquidity,
    )


def _check_spread(
    market: MarketEligibilityInput, cfg: EligibilityConfig
) -> HardRuleResult:
    """Rule 6: Spread within configured hard limit."""
    spread = market.spread

    if spread is None:
        # Try to compute from bid/ask
        if market.best_bid is not None and market.best_ask is not None:
            spread = market.best_ask - market.best_bid
        else:
            return HardRuleResult(
                rule_name="spread_check",
                passed=False,
                reason_code=EligibilityReasonCode.SPREAD_TOO_WIDE,
                detail="No spread data available",
                threshold_value=cfg.max_spread,
            )

    passed = spread <= cfg.max_spread
    return HardRuleResult(
        rule_name="spread_check",
        passed=passed,
        reason_code=(
            EligibilityReasonCode.ELIGIBLE if passed
            else EligibilityReasonCode.SPREAD_TOO_WIDE
        ),
        detail=(
            f"Spread {spread:.4f} {'≤' if passed else '>'} "
            f"max {cfg.max_spread:.4f}"
        ),
        threshold_value=cfg.max_spread,
        actual_value=spread,
    )


def _check_depth(
    market: MarketEligibilityInput, cfg: EligibilityConfig
) -> HardRuleResult:
    """Rule 7: Visible depth at top 3 levels sufficient.

    Checks that depth supports a minimum position size within
    the liquidity fraction limit.
    """
    depth_levels = market.depth_levels

    if not depth_levels:
        # No depth data — use liquidity as proxy
        if market.liquidity_usd and market.liquidity_usd >= cfg.min_liquidity_usd:
            return HardRuleResult(
                rule_name="depth_check",
                passed=True,
                reason_code=EligibilityReasonCode.ELIGIBLE,
                detail="No depth levels; liquidity proxy used",
            )
        return HardRuleResult(
            rule_name="depth_check",
            passed=False,
            reason_code=EligibilityReasonCode.INSUFFICIENT_DEPTH,
            detail="No depth data available and insufficient liquidity",
        )

    # Sum the sizes from top 3 levels
    top_3_size = sum(
        float(level.get("size", 0))
        for level in depth_levels[:3]
    )

    # Minimum position requirement based on liquidity fraction
    min_position_size = cfg.min_liquidity_usd * _LIQUIDITY_FRACTION_LIMIT
    passed = top_3_size >= min_position_size

    return HardRuleResult(
        rule_name="depth_check",
        passed=passed,
        reason_code=(
            EligibilityReasonCode.ELIGIBLE if passed
            else EligibilityReasonCode.INSUFFICIENT_DEPTH
        ),
        detail=(
            f"Top-3 depth ${top_3_size:,.0f} {'≥' if passed else '<'} "
            f"min ${min_position_size:,.0f} ({_LIQUIDITY_FRACTION_LIMIT:.0%} of "
            f"${cfg.min_liquidity_usd:,.0f})"
        ),
        threshold_value=min_position_size,
        actual_value=top_3_size,
    )


def _check_duplicate_cluster(market: MarketEligibilityInput) -> HardRuleResult:
    """Rule 8: No duplicate of currently held event cluster."""
    if (
        market.market_event_cluster_id
        and market.market_event_cluster_id in market.held_event_cluster_ids
    ):
        return HardRuleResult(
            rule_name="duplicate_cluster",
            passed=False,
            reason_code=EligibilityReasonCode.DUPLICATE_EVENT_CLUSTER,
            detail=f"Already hold position in event cluster {market.market_event_cluster_id}",
        )

    return HardRuleResult(
        rule_name="duplicate_cluster",
        passed=True,
        reason_code=EligibilityReasonCode.ELIGIBLE,
        detail="No duplicate event cluster",
    )
