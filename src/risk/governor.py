"""Risk Governor — highest-authority capital protection layer.

Orchestrates drawdown tracking, capital rules, correlation engine,
liquidity sizing, and position sizing to produce final risk approval decisions.

Fully deterministic (Tier D). No LLM may override the Risk Governor.
"""

from __future__ import annotations

import structlog

from config.settings import RiskConfig
from core.enums import DrawdownLevel, OperatorMode, RiskApproval
from market_data.types import OrderBookLevel
from risk.capital_rules import CapitalRulesEngine
from risk.correlation import CorrelationEngine, CorrelationType
from risk.drawdown import DrawdownTracker
from risk.liquidity import LiquiditySizer
from risk.sizer import PositionSizer
from risk.types import (
    CorrelationAssessment,
    DrawdownState,
    LiquidityCheck,
    PortfolioState,
    RiskAssessment,
    RiskRuleResult,
    SizingRequest,
    SizingResult,
)


class RiskGovernor:
    """Top-level risk authority for the trading system.

    Usage:
        governor = RiskGovernor(config)
        governor.reset_day(start_of_day_equity=10000.0)

        assessment = governor.assess(request, portfolio)
        if assessment.is_approved:
            # proceed with execution
            pass
    """

    def __init__(self, config: RiskConfig) -> None:
        self._config = config
        self._drawdown = DrawdownTracker(config)
        self._capital = CapitalRulesEngine(config)
        self._correlation = CorrelationEngine(config)
        self._liquidity = LiquiditySizer(config)
        self._sizer = PositionSizer(config)
        self._log = structlog.get_logger(component="risk_governor")

    # --- Accessors ---

    @property
    def drawdown_tracker(self) -> DrawdownTracker:
        return self._drawdown

    @property
    def correlation_engine(self) -> CorrelationEngine:
        return self._correlation

    @property
    def drawdown_state(self) -> DrawdownState:
        return self._drawdown.state

    # --- Day lifecycle ---

    def reset_day(self, start_of_day_equity: float) -> DrawdownState:
        """Reset drawdown tracking for a new trading day."""
        return self._drawdown.reset_day(start_of_day_equity)

    def update_equity(self, current_equity: float) -> DrawdownState:
        """Update drawdown state with latest equity."""
        return self._drawdown.update(current_equity)

    # --- Core assessment ---

    def assess(
        self,
        request: SizingRequest,
        portfolio: PortfolioState,
        ask_levels: list[OrderBookLevel] | None = None,
    ) -> RiskAssessment:
        """Run full risk assessment for a candidate trade.

        Evaluates all rules, computes sizing, and returns a final decision.
        """
        drawdown = self._drawdown.state
        all_rules: list[RiskRuleResult] = []

        # 1. Capital rules
        capital_results = self._capital.evaluate_all(request, portfolio, drawdown)
        all_rules.extend(capital_results)

        # 2. Correlation rules
        correlation_results = self._correlation.evaluate_rules(request, portfolio)
        all_rules.extend(correlation_results)
        correlation_assessment = self._correlation.assess(request, portfolio)

        # 3. Liquidity check
        liquidity_check = self._liquidity.check(request, ask_levels)
        all_rules.append(RiskRuleResult(
            rule_name="liquidity_depth",
            passed=liquidity_check.passes_depth_check,
            reason=liquidity_check.reason if not liquidity_check.passes_depth_check else "Depth available",
            threshold_value=self._config.max_order_depth_fraction,
            actual_value=liquidity_check.depth_at_top_levels_usd,
        ))
        all_rules.append(RiskRuleResult(
            rule_name="entry_impact",
            passed=liquidity_check.passes_impact_check,
            reason=liquidity_check.reason if not liquidity_check.passes_impact_check else "Impact within bounds",
            threshold_value=self._config.max_entry_impact_edge_fraction,
            actual_value=liquidity_check.entry_impact_edge_fraction,
        ))

        # 4. Check for hard rejections
        failed_rules = [r for r in all_rules if not r.passed]
        hard_reject_rules = {
            "drawdown_entries_allowed",
            "operator_mode_restriction",
            "total_exposure_cap",
            "position_count_limit",
        }

        has_hard_reject = any(r.rule_name in hard_reject_rules for r in failed_rules)
        has_any_failure = len(failed_rules) > 0

        # 5. Determine approval and compute sizing
        if has_hard_reject:
            approval = RiskApproval.REJECT
            reason = "; ".join(r.reason for r in failed_rules if r.rule_name in hard_reject_rules)
            sizing = None
        elif not liquidity_check.passes_depth_check:
            approval = RiskApproval.REJECT
            reason = "Insufficient liquidity depth"
            sizing = None
        elif has_any_failure:
            # Soft failures → may approve with reductions or special conditions
            approval, reason, sizing = self._handle_soft_failures(
                request, portfolio, drawdown, liquidity_check, correlation_assessment, failed_rules,
            )
        else:
            # All rules pass → compute normal sizing
            sizing = self._sizer.compute(request, portfolio, drawdown, liquidity_check)
            if sizing.recommended_size_usd <= 0:
                approval = RiskApproval.REJECT
                reason = "Computed size is zero after all factors"
            elif drawdown.level == DrawdownLevel.SOFT_WARNING:
                approval = RiskApproval.APPROVE_REDUCED
                reason = "Approved with reduced size (soft warning drawdown)"
            elif drawdown.level == DrawdownLevel.RISK_REDUCTION:
                approval = RiskApproval.APPROVE_REDUCED
                reason = "Approved with reduced size (risk reduction drawdown)"
            else:
                approval = RiskApproval.APPROVE_NORMAL
                reason = "All rules passed"

        # Build special conditions
        special_conditions = self._build_special_conditions(
            drawdown, correlation_assessment, liquidity_check,
        )

        assessment = RiskAssessment(
            approval=approval,
            sizing=sizing,
            drawdown_state=drawdown,
            liquidity_check=liquidity_check,
            correlation=correlation_assessment,
            rule_results=all_rules,
            reason=reason,
            special_conditions=special_conditions,
        )

        self._log.info(
            "risk_assessment_complete",
            market_id=request.market_id,
            approval=approval.value,
            reason=reason,
            rules_passed=len(all_rules) - len(failed_rules),
            rules_failed=len(failed_rules),
            recommended_size=sizing.recommended_size_usd if sizing else 0.0,
        )

        return assessment

    def can_trade(self, portfolio: PortfolioState) -> tuple[bool, str]:
        """Quick check: is the system in a state where any new trade is allowed?

        This is the no-trade authority — the ability to do nothing when
        conditions warrant it.
        """
        drawdown = self._drawdown.state

        if not drawdown.entries_allowed:
            return False, f"Drawdown level {drawdown.level.value} blocks all entries"

        if portfolio.operator_mode in (OperatorMode.EMERGENCY_HALT, OperatorMode.OPERATOR_ABSENT):
            return False, f"Operator mode {portfolio.operator_mode.value} blocks entries"

        if portfolio.open_position_count >= self._config.max_simultaneous_positions:
            return False, "Position count limit reached"

        if portfolio.total_open_exposure_usd >= self._config.max_total_open_exposure_usd:
            return False, "Total exposure cap reached"

        balance = portfolio.account_balance_usd
        max_daily = balance * self._config.max_daily_deployment_pct
        if portfolio.daily_deployment_used_usd >= max_daily:
            return False, "Daily deployment limit exhausted"

        return True, "Trading permitted"

    # --- Private helpers ---

    def _handle_soft_failures(
        self,
        request: SizingRequest,
        portfolio: PortfolioState,
        drawdown: DrawdownState,
        liquidity: LiquidityCheck,
        correlation: CorrelationAssessment,
        failed_rules: list[RiskRuleResult],
    ) -> tuple[RiskApproval, str, SizingResult | None]:
        """Handle cases where some non-hard rules failed."""
        failure_names = {r.rule_name for r in failed_rules}

        # Impact too high → reject
        if "entry_impact" in failure_names:
            return RiskApproval.REJECT, "Entry impact exceeds edge threshold", None

        # Category exposure exceeded → reject for this category
        if "category_exposure_cap" in failure_names:
            return RiskApproval.REJECT, "Category exposure cap reached", None

        # Correlation violations → approve with special conditions (reduced)
        if any(n.startswith("cluster_exposure_") for n in failure_names):
            sizing = self._sizer.compute(request, portfolio, drawdown, liquidity)
            return (
                RiskApproval.APPROVE_SPECIAL,
                "Approved with special conditions (correlation concerns)",
                sizing,
            )

        # Evidence threshold failed → delay
        if "evidence_threshold" in failure_names:
            return RiskApproval.DELAY, "Evidence quality below threshold for current drawdown level", None

        # Correlation burden high → reduced sizing
        if "correlation_burden" in failure_names:
            sizing = self._sizer.compute(request, portfolio, drawdown, liquidity)
            return (
                RiskApproval.APPROVE_REDUCED,
                "Approved with reduced size (high correlation burden)",
                sizing,
            )

        # Daily deployment close to limit → reduced
        if "daily_deployment_limit" in failure_names:
            return RiskApproval.REJECT, "Daily deployment limit reached", None

        # Fallback: approve reduced
        sizing = self._sizer.compute(request, portfolio, drawdown, liquidity)
        return (
            RiskApproval.APPROVE_REDUCED,
            f"Approved with reduced size ({len(failed_rules)} soft rule(s) failed)",
            sizing,
        )

    def _build_special_conditions(
        self,
        drawdown: DrawdownState,
        correlation: CorrelationAssessment,
        liquidity: LiquidityCheck,
    ) -> list[str]:
        """Build list of special conditions to attach to approval."""
        conditions: list[str] = []

        if drawdown.level == DrawdownLevel.SOFT_WARNING:
            conditions.append("Shortened review interval due to drawdown warning")
        if drawdown.level == DrawdownLevel.RISK_REDUCTION:
            conditions.append("Tighter revalidation due to risk reduction mode")

        if correlation.burden_score > 0.5:
            conditions.append("High correlation burden — staged entry recommended")

        if liquidity.entry_impact_bps > 50:
            conditions.append("Elevated entry impact — consider price improvement")

        return conditions
