"""Dashboard data services — bridge between ORM layer and API schemas.

These services query the database and assemble dashboard response objects.
They are the single source of truth for dashboard data, ensuring the API
layer stays thin.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from dashboard_api.schemas import (
    AbsenceStatus,
    AgentStatus,
    AlertItem,
    BiasAuditOverview,
    BiasPatternItem,
    CalibrationOverview,
    CalibrationSegmentStatus,
    CategoryPerformanceEntry,
    CostMetrics,
    DrawdownLadder,
    EquitySnapshot,
    ExposureByCategory,
    PortfolioOverview,
    PositionDetail,
    PositionSummary,
    RejectionBreakdownItem,
    RiskBoard,
    ScannerHealth,
    SystemControlResponse,
    SystemHealthItem,
    SystemHealthOverview,
    TriggerEventItem,
    ViabilityCheckpointItem,
    ViabilityOverview,
    WorkflowCandidateDetail,
    WorkflowCostDecisionDetail,
    WorkflowCostEstimateDetail,
    WorkflowEstimateAccuracyDetail,
    WorkflowRunDetail,
    WorkflowRunSummary,
)

_log = structlog.get_logger(component="dashboard_service")


class DashboardService:
    """Assembles dashboard data from database state and system configuration.

    This service is injected with a session and config, and provides methods
    corresponding to each dashboard page/section.
    """

    def __init__(
        self,
        session: AsyncSession,
        config: Any | None = None,
        system_state: dict[str, Any] | None = None,
    ) -> None:
        self._session = session
        self._config = config
        # Mutable shared state for agent statuses, operator mode, etc.
        self._system_state = system_state or {
            "operator_mode": "paper",
            "system_status": "running",
            "agents_running": False,
        }

    # ─── Portfolio Overview ───────────────────────────

    async def get_portfolio_overview(self) -> PortfolioOverview:
        """Build complete portfolio overview with equity, PnL, drawdown, mode."""
        from data.models import Position

        result = await self._session.execute(
            select(
                func.count(Position.id).label("count"),
                func.coalesce(func.sum(Position.size), 0.0).label("exposure"),
                func.coalesce(func.sum(Position.unrealized_pnl), 0.0).label("unrealized"),
                func.coalesce(func.sum(Position.realized_pnl), 0.0).label("realized"),
            ).where(Position.status == "open")
        )
        row = result.one()

        # Build equity history from in-memory snapshots
        raw_history = self._system_state.get("equity_history", [])
        equity_history = [
            EquitySnapshot(
                timestamp=snap["timestamp"],
                equity_usd=snap["equity_usd"],
                pnl_usd=snap["pnl_usd"],
            )
            for snap in raw_history
        ]

        operator_mode = self._system_state.get("operator_mode", "paper")
        paper_cash = float(self._system_state.get("paper_balance_usd", 500.0))
        paper_equity = float(self._system_state.get("paper_equity_usd", paper_cash))
        rejection_breakdown: list[RejectionBreakdownItem] = []
        if int(row.count) == 0 and operator_mode == "paper":
            rejection_breakdown = await self._get_latest_rejection_breakdown()

        capability_map = {
            "paper": (
                "paper",
                "Autonomous simulated trading enabled.",
            ),
            "shadow": (
                "shadow",
                "Non-executing log-only mode.",
            ),
            "live": (
                "live",
                "Execution unavailable until the exchange adapter is implemented.",
            ),
        }
        capability_status, capability_detail = capability_map.get(
            operator_mode,
            ("unknown", "Mode capability is unknown."),
        )

        return PortfolioOverview(
            total_equity_usd=paper_equity,
            paper_cash_balance_usd=paper_cash,
            paper_equity_usd=paper_equity,
            total_open_exposure_usd=float(row.exposure),
            daily_pnl_usd=float(row.unrealized) + float(row.realized),
            unrealized_pnl_usd=float(row.unrealized),
            realized_pnl_usd=float(row.realized),
            open_positions_count=int(row.count),
            drawdown_level=self._system_state.get("drawdown_level", "normal"),
            drawdown_pct=self._system_state.get("drawdown_pct", 0.0),
            operator_mode=operator_mode,
            mode_capability_status=capability_status,
            mode_capability_detail=capability_detail,
            system_status=self._system_state.get("system_status", "running"),
            latest_rejection_breakdown=rejection_breakdown,
            equity_history=equity_history,
        )

    async def _get_latest_rejection_breakdown(self) -> list[RejectionBreakdownItem]:
        """Summarize recent candidate rejection logs for empty portfolio states."""
        from data.models.logging import StructuredLogEntry

        result = await self._session.execute(
            select(StructuredLogEntry)
            .where(StructuredLogEntry.event_type == "candidate_rejected")
            .order_by(StructuredLogEntry.logged_at.desc())
            .limit(20)
        )
        entries = result.scalars().all()
        grouped: dict[tuple[str, str | None], RejectionBreakdownItem] = {}
        for entry in entries:
            payload = entry.payload or {}
            reason_code = payload.get("reason_code") or "candidate_rejected"
            stage = payload.get("stage_reached")
            key = (reason_code, stage)
            item = grouped.get(key)
            if item is None:
                item = RejectionBreakdownItem(
                    reason_code=reason_code,
                    stage=stage,
                    count=0,
                    latest_market_title=payload.get("market_title"),
                    latest_reason=payload.get("reason"),
                )
                grouped[key] = item
            item.count += 1
        return list(grouped.values())

    # ─── Positions ────────────────────────────────────

    async def get_positions(
        self, status: str | None = None, limit: int = 50, offset: int = 0
    ) -> list[PositionSummary]:
        """List positions with optional status filter."""
        from data.models import Market, Position

        query = (
            select(Position, Market.title, Market.market_id, Market.category)
            .join(Market, Position.market_id == Market.id)
            .order_by(Position.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        if status:
            query = query.where(Position.status == status)

        result = await self._session.execute(query)
        rows = result.all()

        return [
            PositionSummary(
                id=pos.id,
                market_id=mkt_id,
                market_title=title,
                side=pos.side,
                entry_price=pos.entry_price,
                current_price=pos.current_price,
                size=pos.size,
                remaining_size=pos.remaining_size,
                unrealized_pnl=pos.unrealized_pnl,
                realized_pnl=pos.realized_pnl,
                status=pos.status,
                review_tier=pos.review_tier,
                category=cat,
                entered_at=pos.entered_at,
            )
            for pos, title, mkt_id, cat in rows
        ]

    async def get_position_detail(self, position_id: uuid.UUID) -> PositionDetail | None:
        """Get detailed position data including thesis and cost info."""
        from data.models import Market, Position

        result = await self._session.execute(
            select(Position, Market.title, Market.market_id, Market.category)
            .join(Market, Position.market_id == Market.id)
            .where(Position.id == position_id)
        )
        row = result.one_or_none()
        if row is None:
            return None

        pos, title, mkt_id, cat = row
        return PositionDetail(
            id=pos.id,
            market_id=mkt_id,
            market_title=title,
            side=pos.side,
            entry_price=pos.entry_price,
            current_price=pos.current_price,
            size=pos.size,
            remaining_size=pos.remaining_size,
            unrealized_pnl=pos.unrealized_pnl,
            realized_pnl=pos.realized_pnl,
            status=pos.status,
            review_tier=pos.review_tier,
            category=cat,
            entered_at=pos.entered_at,
            probability_estimate=pos.probability_estimate,
            confidence_estimate=pos.confidence_estimate,
            calibration_confidence=pos.calibration_confidence,
            risk_approval=pos.risk_approval,
            cumulative_review_cost_usd=pos.cumulative_review_cost_usd,
            total_inference_cost_usd=pos.total_inference_cost_usd,
            exit_class=pos.exit_class,
            exit_price=pos.exit_price,
            exited_at=pos.exited_at,
            last_reviewed_at=pos.last_reviewed_at,
            next_review_at=pos.next_review_at,
        )

    # ─── Risk Board ───────────────────────────────────

    async def get_risk_board(self) -> RiskBoard:
        """Build risk dashboard with drawdown ladder, exposure breakdown."""
        from data.models import Market, Position

        # Exposure by category
        result = await self._session.execute(
            select(
                Market.category,
                func.sum(Position.size).label("exposure"),
                func.count(Position.id).label("count"),
            )
            .join(Market, Position.market_id == Market.id)
            .where(Position.status == "open")
            .group_by(Market.category)
        )

        risk_cfg = getattr(self._config, "risk", None) if self._config else None
        default_cap = risk_cfg.default_category_exposure_cap_usd if risk_cfg else 5000.0

        exposure_items = []
        total_exposure = 0.0
        for cat, exp, cnt in result.all():
            cap = default_cap
            if risk_cfg and cat == "sports":
                cap = risk_cfg.sports_category_exposure_cap_usd
            exposure_items.append(
                ExposureByCategory(
                    category=cat or "unknown",
                    exposure_usd=float(exp),
                    cap_usd=cap,
                    positions_count=int(cnt),
                    pct_of_cap=float(exp) / cap if cap > 0 else 0.0,
                )
            )
            total_exposure += float(exp)

        drawdown_pct = self._system_state.get("drawdown_pct", 0.0)
        level = self._system_state.get("drawdown_level", "normal")

        return RiskBoard(
            drawdown_ladder=DrawdownLadder(
                current_drawdown_pct=drawdown_pct,
                current_level=level,
            ),
            total_exposure_usd=total_exposure,
            max_exposure_usd=risk_cfg.max_total_open_exposure_usd if risk_cfg else 10000.0,
            exposure_by_category=exposure_items,
            daily_deployment_used_pct=self._system_state.get("daily_deployment_used_pct", 0.0),
            max_daily_deployment_pct=risk_cfg.max_daily_deployment_pct if risk_cfg else 0.10,
        )

    # ─── Workflows ────────────────────────────────────

    async def get_workflow_runs(
        self, limit: int = 20, offset: int = 0
    ) -> list[WorkflowRunSummary]:
        """Get recent workflow run summaries.

        Prefer persisted DB rows so runs survive process restarts. Fall back to
        the live in-memory activity buffer when the DB has no rows yet.
        """
        from data.models import Market
        from data.models.logging import StructuredLogEntry
        from data.models.thesis import ThesisCard
        from data.models.workflow import WorkflowRun

        event_time = func.coalesce(
            WorkflowRun.completed_at,
            WorkflowRun.started_at,
            WorkflowRun.created_at,
        )
        query = (
            select(
                WorkflowRun,
                Market.title,
                func.count(ThesisCard.id).label("accepted_count"),
            )
            .outerjoin(Market, WorkflowRun.market_id == Market.id)
            .outerjoin(ThesisCard, ThesisCard.workflow_run_id == WorkflowRun.id)
            .group_by(WorkflowRun.id, Market.title)
            .order_by(event_time.desc(), WorkflowRun.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self._session.execute(query)
        rows = result.all()

        if rows:
            workflow_ids = [run.workflow_run_id for run, _, _ in rows]
            counts_result = await self._session.execute(
                select(
                    StructuredLogEntry.workflow_run_id,
                    StructuredLogEntry.market_id,
                    StructuredLogEntry.event_type,
                    StructuredLogEntry.logged_at,
                )
                .where(
                    StructuredLogEntry.workflow_run_id.in_(workflow_ids),
                    StructuredLogEntry.event_type.in_(("candidate_accepted", "candidate_rejected")),
                )
                .order_by(StructuredLogEntry.logged_at.asc())
            )
            latest_events: dict[str, dict[str, str]] = {}
            for workflow_run_id, market_id, event_type, _ in counts_result.all():
                latest_events.setdefault(workflow_run_id, {})[market_id or "workflow"] = event_type
            counts: dict[str, dict[str, int]] = {}
            for workflow_run_id, latest_per_market in latest_events.items():
                accepted = sum(1 for event_type in latest_per_market.values() if event_type == "candidate_accepted")
                counts[workflow_run_id] = {
                    "reviewed": len(latest_per_market),
                    "accepted": accepted,
                    "rejected": len(latest_per_market) - accepted,
                }

            return [
                WorkflowRunSummary(
                    id=run.id,
                    workflow_type=run.run_type,
                    status=run.status,
                    started_at=run.started_at,
                    completed_at=run.completed_at,
                    estimated_cost_usd=run.estimated_cost_usd or 0.0,
                    cost_usd=run.actual_cost_usd or 0.0,
                    candidates_reviewed=counts.get(run.workflow_run_id, {}).get("reviewed", int(accepted_count or 0)),
                    candidates_accepted=counts.get(run.workflow_run_id, {}).get("accepted", int(accepted_count or 0)),
                    market_title=title,
                    outcome=run.outcome,
                    outcome_reason=run.outcome_reason,
                    operator_mode=run.operator_mode,
                    final_stage=(
                        "execution"
                        if int(accepted_count or 0) > 0
                        else None
                    ),
                )
                for run, title, accepted_count in rows
            ]

        import uuid as _uuid
        runs = self._system_state.get("workflow_runs", [])
        runs_page = sorted(
            runs,
            key=lambda run: (
                run.get("completed_at")
                or run.get("started_at")
                or run.get("created_at")
                or ""
            ),
            reverse=True,
        )[offset : offset + limit]
        return [
            WorkflowRunSummary(
                id=_uuid.UUID(r["id"]),
                workflow_type=r["workflow_type"],
                status=r["status"],
                started_at=r.get("started_at"),
                completed_at=r.get("completed_at"),
                estimated_cost_usd=r.get("estimated_cost_usd", 0.0),
                cost_usd=r.get("cost_usd", 0.0),
                candidates_reviewed=r.get("candidates_reviewed", 0),
                candidates_accepted=r.get("candidates_accepted", 0),
                market_title=r.get("market_title"),
                outcome=r.get("outcome"),
                outcome_reason=r.get("outcome_reason"),
                operator_mode=r.get("operator_mode"),
                final_stage=r.get("final_stage"),
            )
            for r in runs_page
        ]

    async def get_workflow_run_detail(self, workflow_id: uuid.UUID) -> WorkflowRunDetail | None:
        """Get a full workflow detail payload including candidate diagnostics."""
        from data.models import Market
        from data.models.cost import CostGovernorDecision, PreRunCostEstimate
        from data.models.logging import StructuredLogEntry
        from data.models.workflow import WorkflowRun

        result = await self._session.execute(
            select(WorkflowRun, Market.title)
            .outerjoin(Market, WorkflowRun.market_id == Market.id)
            .where(WorkflowRun.id == workflow_id)
        )
        row = result.one_or_none()
        if row is None:
            return None

        workflow_run, market_title = row

        estimate_row = (
            await self._session.execute(
                select(PreRunCostEstimate)
                .where(PreRunCostEstimate.workflow_run_id == workflow_run.id)
                .order_by(PreRunCostEstimate.estimated_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        decision_row = (
            await self._session.execute(
                select(CostGovernorDecision)
                .where(CostGovernorDecision.workflow_run_id == workflow_run.id)
                .order_by(CostGovernorDecision.decided_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        candidate_logs = (
            await self._session.execute(
                select(StructuredLogEntry)
                .where(
                    StructuredLogEntry.workflow_run_id == workflow_run.workflow_run_id,
                    StructuredLogEntry.event_type.in_(("candidate_accepted", "candidate_rejected")),
                )
                .order_by(StructuredLogEntry.logged_at.asc())
            )
        ).scalars().all()
        accuracy_log = (
            await self._session.execute(
                select(StructuredLogEntry)
                .where(
                    StructuredLogEntry.workflow_run_id == workflow_run.workflow_run_id,
                    StructuredLogEntry.event_type == "workflow_cost_accuracy",
                )
                .order_by(StructuredLogEntry.logged_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

        latest_by_market: dict[str, WorkflowCandidateDetail] = {}
        for entry in candidate_logs:
            payload = entry.payload or {}
            market_id = payload.get("market_id") or entry.market_id or ""
            latest_by_market[market_id] = WorkflowCandidateDetail(
                market_id=market_id,
                market_title=payload.get("market_title"),
                category=payload.get("category"),
                accepted=bool(payload.get("accepted")),
                stage_reached=payload.get("stage_reached"),
                reason=payload.get("reason"),
                reason_code=payload.get("reason_code"),
                reason_detail=payload.get("reason_detail"),
                cost_spent_usd=float(payload.get("cost_spent_usd") or 0.0),
                quantitative_context=payload.get("quantitative_context") or {},
            )
        candidate_outcomes = list(latest_by_market.values())

        final_stage = None
        if candidate_outcomes:
            final_stage = candidate_outcomes[-1].stage_reached
            if any(item.accepted for item in candidate_outcomes):
                final_stage = "execution"

        estimate_accuracy = None
        if accuracy_log is not None and accuracy_log.payload:
            payload = accuracy_log.payload
            estimate_accuracy = WorkflowEstimateAccuracyDetail(
                estimated_min_usd=float(payload.get("estimated_min_usd") or 0.0),
                estimated_max_usd=float(payload.get("estimated_max_usd") or 0.0),
                actual_usd=float(payload.get("actual_usd") or 0.0),
                accuracy_ratio=float(payload.get("accuracy_ratio") or 0.0),
                within_bounds=bool(payload.get("within_bounds")),
            )

        return WorkflowRunDetail(
            id=workflow_run.id,
            workflow_run_id=workflow_run.workflow_run_id,
            workflow_type=workflow_run.run_type,
            status=workflow_run.status,
            started_at=workflow_run.started_at,
            completed_at=workflow_run.completed_at,
            estimated_cost_usd=workflow_run.estimated_cost_usd or 0.0,
            cost_usd=workflow_run.actual_cost_usd or 0.0,
            candidates_reviewed=len(candidate_outcomes),
            candidates_accepted=sum(1 for item in candidate_outcomes if item.accepted),
            market_title=market_title,
            outcome=workflow_run.outcome,
            outcome_reason=workflow_run.outcome_reason,
            operator_mode=workflow_run.operator_mode,
            final_stage=final_stage,
            models_used=list(workflow_run.models_used or []),
            max_tier_used=workflow_run.max_tier_used,
            cost_estimate=(
                WorkflowCostEstimateDetail(
                    expected_cost_min_usd=estimate_row.expected_cost_min_usd,
                    expected_cost_max_usd=estimate_row.expected_cost_max_usd,
                    daily_budget_remaining_usd=estimate_row.daily_budget_remaining_usd,
                    lifetime_budget_remaining_usd=estimate_row.lifetime_budget_remaining_usd,
                    daily_budget_pct_remaining=estimate_row.daily_budget_pct_remaining,
                    estimated_at=estimate_row.estimated_at,
                    agent_budgets=estimate_row.agent_budgets or {},
                )
                if estimate_row is not None
                else None
            ),
            cost_decision=(
                WorkflowCostDecisionDetail(
                    decision=decision_row.decision,
                    reason=decision_row.reason,
                    approved_max_tier=decision_row.approved_max_tier,
                    approved_max_cost_usd=decision_row.approved_max_cost_usd,
                    cost_selectivity_ratio=decision_row.cost_selectivity_ratio,
                    opus_escalation_threshold=decision_row.opus_escalation_threshold,
                    decided_at=decision_row.decided_at,
                )
                if decision_row is not None
                else None
            ),
            estimate_accuracy=estimate_accuracy,
            candidate_outcomes=candidate_outcomes,
        )

    # ─── Trigger Events ──────────────────────────────

    async def get_trigger_events(
        self, limit: int = 50, offset: int = 0
    ) -> list[TriggerEventItem]:
        """Get recent trigger events.

        Prefer persisted DB rows so trigger history survives process restarts.
        Fall back to the in-memory activity buffer when needed.
        """
        from data.models import Market
        from data.models.workflow import TriggerEvent

        query = (
            select(TriggerEvent, Market.title, Market.market_id)
            .join(Market, TriggerEvent.market_id == Market.id)
            .order_by(TriggerEvent.triggered_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self._session.execute(query)
        rows = result.all()

        if rows:
            return [
                TriggerEventItem(
                    id=evt.id,
                    trigger_class=evt.trigger_class,
                    trigger_level=evt.trigger_level,
                    market_id=market_id,
                    market_title=title,
                    reason=evt.reason,
                    price=evt.price_at_trigger,
                    spread=evt.spread_at_trigger,
                    data_source=evt.data_source,
                    timestamp=evt.triggered_at,
                )
                for evt, title, market_id in rows
            ]

        import uuid as _uuid
        events = self._system_state.get("trigger_events", [])
        events_page = sorted(
            events,
            key=lambda event: event.get("timestamp") or "",
            reverse=True,
        )[offset : offset + limit]
        return [
            TriggerEventItem(
                id=_uuid.UUID(e["id"]),
                trigger_class=e["trigger_class"],
                trigger_level=e["trigger_level"],
                market_id=e.get("market_id"),
                market_title=e.get("market_title"),
                reason=e.get("reason"),
                price=e.get("price"),
                spread=e.get("spread"),
                data_source=e.get("data_source", "live"),
                timestamp=e["timestamp"],
            )
            for e in events_page
        ]

    # ─── Cost Metrics ─────────────────────────────────

    async def get_cost_metrics(self) -> CostMetrics:
        """Aggregated cost governor data."""
        cost_cfg = getattr(self._config, "cost", None) if self._config else None
        daily_budget = cost_cfg.daily_llm_budget_usd if cost_cfg else 25.0
        lifetime_budget = cost_cfg.lifetime_experiment_budget_usd if cost_cfg else 5000.0

        daily_spend = self._system_state.get("daily_spend_usd", 0.0)
        lifetime_spend = self._system_state.get("lifetime_spend_usd", 0.0)

        return CostMetrics(
            daily_spend_usd=daily_spend,
            daily_budget_usd=daily_budget,
            daily_budget_remaining_usd=max(0, daily_budget - daily_spend),
            lifetime_spend_usd=lifetime_spend,
            lifetime_budget_usd=lifetime_budget,
            lifetime_budget_pct=(lifetime_spend / lifetime_budget * 100) if lifetime_budget > 0 else 0.0,
            selectivity_ratio=self._system_state.get("selectivity_ratio", 0.0),
            selectivity_target=cost_cfg.cost_of_selectivity_target_ratio if cost_cfg else 0.20,
            opus_spend_today_usd=self._system_state.get("opus_spend_today_usd", 0.0),
            opus_budget_usd=cost_cfg.daily_opus_escalation_budget_usd if cost_cfg else 5.0,
        )

    # ─── Calibration ──────────────────────────────────

    async def get_calibration_overview(self) -> CalibrationOverview:
        """Get calibration status, brier scores, and segment details."""
        # Pull from system state — calibration system populates these
        return CalibrationOverview(
            total_shadow_forecasts=self._system_state.get("total_shadow_forecasts", 0),
            total_resolved=self._system_state.get("total_resolved", 0),
            overall_system_brier=self._system_state.get("overall_system_brier"),
            overall_market_brier=self._system_state.get("overall_market_brier"),
            overall_advantage=self._system_state.get("overall_advantage"),
            patience_budget_remaining_days=self._system_state.get("patience_budget_remaining_days"),
            segments=self._system_state.get("calibration_segments", []),
        )

    # ─── Scanner Health ───────────────────────────────

    async def get_scanner_health(self) -> ScannerHealth:
        """Scanner infrastructure health."""
        return ScannerHealth(
            api_status=self._system_state.get("scanner_api_status", "healthy"),
            degraded_level=self._system_state.get("scanner_degraded_level", 0),
            cache_entries_count=self._system_state.get("scanner_cache_entries", 0),
            cache_hit_rate=self._system_state.get("scanner_cache_hit_rate", 0.0),
            last_successful_poll=self._system_state.get("scanner_last_poll"),
            consecutive_failures=self._system_state.get("scanner_consecutive_failures", 0),
            uptime_pct=self._system_state.get("scanner_uptime_pct", 100.0),
        )

    # ─── Category Performance ─────────────────────────

    async def get_category_performance(self) -> list[CategoryPerformanceEntry]:
        """Category performance ledger entries."""
        entries = self._system_state.get("category_performance", [])
        if isinstance(entries, list) and entries:
            return [
                CategoryPerformanceEntry(**e) if isinstance(e, dict) else e
                for e in entries
            ]
        return []

    # ─── Bias Audit ───────────────────────────────────

    async def get_bias_audit(self) -> BiasAuditOverview:
        """Current bias audit summary."""
        return BiasAuditOverview(
            last_audit_at=self._system_state.get("last_bias_audit_at"),
            active_patterns=[
                BiasPatternItem(**p) if isinstance(p, dict) else p
                for p in self._system_state.get("active_bias_patterns", [])
            ],
            persistent_pattern_count=self._system_state.get("persistent_bias_count", 0),
            resolved_pattern_count=self._system_state.get("resolved_bias_count", 0),
        )

    # ─── Viability ────────────────────────────────────

    async def get_viability(self) -> ViabilityOverview:
        """Strategy viability status."""
        return ViabilityOverview(
            current_signal=self._system_state.get("viability_signal", "unassessed"),
            checkpoints=[
                ViabilityCheckpointItem(**c) if isinstance(c, dict) else c
                for c in self._system_state.get("viability_checkpoints", [])
            ],
            lifetime_budget_pct=self._system_state.get("lifetime_budget_pct", 0.0),
            patience_budget_remaining_days=self._system_state.get(
                "patience_budget_remaining_days"
            ),
        )

    # ─── Absence Status ──────────────────────────────

    async def get_absence_status(self) -> AbsenceStatus:
        """Operator absence state."""
        return AbsenceStatus(
            is_absent=self._system_state.get("is_absent", False),
            absence_level=self._system_state.get("absence_level", 0),
            hours_since_activity=self._system_state.get("hours_since_activity", 0.0),
            last_activity=self._system_state.get("last_activity"),
            restrictions_active=self._system_state.get("absence_restrictions", []),
            autonomous_actions_count=self._system_state.get("autonomous_actions_count", 0),
        )

    # ─── System Health ────────────────────────────────

    async def get_system_health(self) -> SystemHealthOverview:
        """Aggregated system health."""
        components = [
            SystemHealthItem(
                component="Database",
                status="healthy",
                last_check=datetime.now(tz=UTC),
            ),
            SystemHealthItem(
                component="Scanner",
                status=self._system_state.get("scanner_api_status", "healthy"),
                last_check=self._system_state.get("scanner_last_poll"),
            ),
            SystemHealthItem(
                component="Risk Governor",
                status="healthy",
                last_check=datetime.now(tz=UTC),
            ),
            SystemHealthItem(
                component="Cost Governor",
                status="healthy",
                last_check=datetime.now(tz=UTC),
            ),
            SystemHealthItem(
                component="Telegram",
                status=self._system_state.get("telegram_status", "healthy"),
                last_check=self._system_state.get("telegram_last_check"),
            ),
        ]

        # Determine overall
        statuses = [c.status for c in components]
        if "critical" in statuses or "down" in statuses:
            overall = "critical"
        elif "warning" in statuses or "degraded" in statuses:
            overall = "warning"
        else:
            overall = "healthy"

        return SystemHealthOverview(
            overall_status=overall,
            components=components,
            active_alerts_count=self._system_state.get("active_alerts_count", 0),
        )

    # ─── Agent Statuses ───────────────────────────────

    async def get_agent_statuses(self) -> list[AgentStatus]:
        """Get status of all registered agents with live invocation/cost data."""
        is_running = self._system_state.get("agents_running", False)
        invocations = self._system_state.get("agent_invocations", {})
        costs = self._system_state.get("agent_costs", {})
        last_invoked = self._system_state.get("agent_last_invoked", {})

        registry = [
            ("Investigator Orchestrator", "investigator_orchestration", "A"),
            ("Performance Analyzer", "performance_analyzer", "A"),
            ("Domain Manager (Politics)", "domain_manager_politics", "B"),
            ("Domain Manager (Geopolitics)", "domain_manager_geopolitics", "B"),
            ("Domain Manager (Technology)", "domain_manager_technology", "B"),
            ("Evidence Research", "evidence_research", "C"),
            ("Counter-Case", "counter_case", "C"),
            ("Resolution Review", "resolution_review", "C"),
            ("Trigger Scanner", "trigger_scanner", "D"),
            ("Risk Governor", "risk_governor", "D"),
            ("Cost Governor", "cost_governor", "D"),
            ("Execution Engine", "execution_engine", "D"),
        ]

        return [
            AgentStatus(
                name=name,
                role=role,
                tier=tier,
                is_active=is_running,
                total_invocations=invocations.get(role, 0),
                total_cost_usd=costs.get(role, 0.0),
                last_invoked=last_invoked.get(role),
            )
            for name, role, tier in registry
        ]

    # ─── System Control ───────────────────────────────

    async def set_operator_mode(self, mode: str, reason: str | None = None) -> SystemControlResponse:
        """Change the system operator mode."""
        from core.enums import OperatorMode

        valid_modes = {m.value for m in OperatorMode}
        if mode not in valid_modes:
            return SystemControlResponse(
                success=False,
                message=f"Invalid mode '{mode}'. Valid modes: {valid_modes}",
                current_mode=self._system_state.get("operator_mode", "paper"),
                timestamp=datetime.now(tz=UTC),
            )

        old_mode = self._system_state.get("operator_mode", "paper")
        self._system_state["operator_mode"] = mode
        _log.info(
            "operator_mode_changed",
            old_mode=old_mode,
            new_mode=mode,
            reason=reason,
        )

        # Persist to disk so it survives restarts
        from dashboard_api.app import save_persisted_state
        save_persisted_state()

        return SystemControlResponse(
            success=True,
            message=f"Mode changed from '{old_mode}' to '{mode}'",
            current_mode=mode,
            timestamp=datetime.now(tz=UTC),
        )

    async def toggle_agents(self, running: bool) -> SystemControlResponse:
        """Start or stop agents."""
        self._system_state["agents_running"] = running
        status = "running" if running else "stopped"
        self._system_state["system_status"] = status
        _log.info("agents_toggled", running=running)

        return SystemControlResponse(
            success=True,
            message=f"Agents {'started' if running else 'stopped'}",
            current_mode=self._system_state.get("operator_mode", "paper"),
            timestamp=datetime.now(tz=UTC),
        )
