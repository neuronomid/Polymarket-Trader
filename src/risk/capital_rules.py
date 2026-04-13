"""Capital rules engine — deterministic capital protection checks.

Evaluates: daily deployment limits, total exposure caps, position count limits,
category exposure caps, and operator mode restrictions.

Fully deterministic (Tier D). No LLM calls.
"""

from __future__ import annotations

import structlog

from config.settings import RiskConfig
from core.enums import DrawdownLevel, OperatorMode
from risk.types import DrawdownState, PortfolioState, RiskRuleResult, SizingRequest


class CapitalRulesEngine:
    """Evaluates deterministic capital protection rules.

    Each rule produces a RiskRuleResult. The Risk Governor aggregates
    all results to make the final approval decision.
    """

    def __init__(self, config: RiskConfig) -> None:
        self._config = config
        self._log = structlog.get_logger(component="capital_rules")

    def evaluate_all(
        self,
        request: SizingRequest,
        portfolio: PortfolioState,
        drawdown: DrawdownState,
    ) -> list[RiskRuleResult]:
        """Run all capital rules and return results."""
        return [
            self._check_drawdown_entries(drawdown),
            self._check_daily_deployment(portfolio),
            self._check_total_exposure(portfolio),
            self._check_position_count(portfolio),
            self._check_category_exposure(request, portfolio),
            self._check_operator_mode(portfolio),
            self._check_evidence_threshold(request, drawdown),
        ]

    def _check_drawdown_entries(self, drawdown: DrawdownState) -> RiskRuleResult:
        """Check if drawdown level allows new entries."""
        if not drawdown.entries_allowed:
            return RiskRuleResult(
                rule_name="drawdown_entries_allowed",
                passed=False,
                reason=f"Drawdown level {drawdown.level.value} blocks new entries "
                       f"(drawdown={drawdown.current_drawdown_pct:.2%})",
                threshold_value=self._config.entries_disabled_pct,
                actual_value=drawdown.current_drawdown_pct,
            )
        return RiskRuleResult(
            rule_name="drawdown_entries_allowed",
            passed=True,
            reason=f"Drawdown level {drawdown.level.value} permits entries",
            threshold_value=self._config.entries_disabled_pct,
            actual_value=drawdown.current_drawdown_pct,
        )

    def _check_daily_deployment(self, portfolio: PortfolioState) -> RiskRuleResult:
        """Check daily new deployment limit."""
        balance = portfolio.account_balance_usd
        max_daily = balance * self._config.max_daily_deployment_pct
        used = portfolio.daily_deployment_used_usd
        remaining = max_daily - used

        passed = remaining > 0
        return RiskRuleResult(
            rule_name="daily_deployment_limit",
            passed=passed,
            reason=f"Daily deployment: ${used:.2f} / ${max_daily:.2f} used"
                   if passed else
                   f"Daily deployment exhausted: ${used:.2f} >= ${max_daily:.2f}",
            threshold_value=max_daily,
            actual_value=used,
            metadata={"remaining_usd": remaining},
        )

    def _check_total_exposure(self, portfolio: PortfolioState) -> RiskRuleResult:
        """Check total open exposure cap."""
        cap = self._config.max_total_open_exposure_usd
        current = portfolio.total_open_exposure_usd
        passed = current < cap

        return RiskRuleResult(
            rule_name="total_exposure_cap",
            passed=passed,
            reason=f"Exposure: ${current:.2f} / ${cap:.2f}"
                   if passed else
                   f"Exposure cap reached: ${current:.2f} >= ${cap:.2f}",
            threshold_value=cap,
            actual_value=current,
        )

    def _check_position_count(self, portfolio: PortfolioState) -> RiskRuleResult:
        """Check max simultaneous positions."""
        cap = self._config.max_simultaneous_positions
        current = portfolio.open_position_count
        passed = current < cap

        return RiskRuleResult(
            rule_name="position_count_limit",
            passed=passed,
            reason=f"Positions: {current} / {cap}"
                   if passed else
                   f"Position limit reached: {current} >= {cap}",
            threshold_value=float(cap),
            actual_value=float(current),
        )

    def _check_category_exposure(
        self, request: SizingRequest, portfolio: PortfolioState,
    ) -> RiskRuleResult:
        """Check category-specific exposure cap."""
        category = request.category
        if category == "sports":
            cap = self._config.sports_category_exposure_cap_usd
        else:
            cap = self._config.default_category_exposure_cap_usd

        current = portfolio.category_exposure_usd.get(category, 0.0)
        passed = current < cap

        return RiskRuleResult(
            rule_name="category_exposure_cap",
            passed=passed,
            reason=f"Category '{category}' exposure: ${current:.2f} / ${cap:.2f}"
                   if passed else
                   f"Category '{category}' cap reached: ${current:.2f} >= ${cap:.2f}",
            threshold_value=cap,
            actual_value=current,
            metadata={"category": category},
        )

    def _check_operator_mode(self, portfolio: PortfolioState) -> RiskRuleResult:
        """Check operator mode restrictions."""
        mode = portfolio.operator_mode
        blocked_modes = {
            OperatorMode.EMERGENCY_HALT,
            OperatorMode.OPERATOR_ABSENT,
        }

        if mode in blocked_modes:
            return RiskRuleResult(
                rule_name="operator_mode_restriction",
                passed=False,
                reason=f"Operator mode '{mode.value}' blocks new entries",
                metadata={"operator_mode": mode.value},
            )

        return RiskRuleResult(
            rule_name="operator_mode_restriction",
            passed=True,
            reason=f"Operator mode '{mode.value}' permits entries",
            metadata={"operator_mode": mode.value},
        )

    def _check_evidence_threshold(
        self, request: SizingRequest, drawdown: DrawdownState,
    ) -> RiskRuleResult:
        """Check minimum evidence quality under elevated drawdown."""
        min_score = drawdown.min_evidence_score
        if min_score <= 0:
            return RiskRuleResult(
                rule_name="evidence_threshold",
                passed=True,
                reason="No elevated evidence threshold at current drawdown level",
                threshold_value=0.0,
                actual_value=request.evidence_quality_score,
            )

        passed = request.evidence_quality_score >= min_score
        return RiskRuleResult(
            rule_name="evidence_threshold",
            passed=passed,
            reason=f"Evidence score {request.evidence_quality_score:.2f} "
                   f"{'meets' if passed else 'below'} threshold {min_score:.2f} "
                   f"(drawdown level: {drawdown.level.value})",
            threshold_value=min_score,
            actual_value=request.evidence_quality_score,
        )
