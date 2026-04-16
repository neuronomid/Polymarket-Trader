"""Workflow orchestrator — wires all subsystems into an end-to-end pipeline.

Phase 15C implementation: connects the 13 system workflows into a single
coordinated runtime.

Pipeline order (from spec Section 15C, Step 6):
    Eligibility Intake → Trigger Scanner → Investigator → Tradeability →
    Risk/Cost Approval → Execution → Position Review → Calibration →
    Performance Review → Policy Review → Viability → Bias Audit →
    Absence Management

This module owns the system lifecycle:
    1. Initialize all subsystems
    2. Wire event callbacks (scanner triggers → pipeline)
    3. Start periodic tasks (learning loops, audits)
    4. Provide the dashboard API with live system state
    5. Handle graceful shutdown
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

import structlog
from sqlalchemy import func, select

from agents.providers import ProviderRouter
from agents.regime import RegimeAdapter
from agents.types import CalibrationContext, RegimeContext
from absence.manager import AbsenceManager
from absence.types import InteractionType, OperatorInteraction
from bias.audit import BiasAuditRunner
from bias.detector import BiasDetector
from calibration.accumulation import AccumulationTracker
from calibration.brier import BrierEngine
from calibration.friction import FrictionCalibrator
from calibration.segments import SegmentManager
from calibration.store import CalibrationStore
from config.settings import AppConfig
from core.enums import (
    CalibrationRegime,
    CategoryQualityTier,
    CostClass,
    EligibilityOutcome,
    ModelTier,
    NotificationSeverity,
    NotificationType,
    OperatorMode,
    TriggerLevel,
)
from cost.governor import CostGovernor
from cost.types import CostRecordInput
from data.database import close_db, get_session_factory, init_db
from eligibility.category_classifier import classify_category
from eligibility.engine import EligibilityEngine
from eligibility.types import MarketEligibilityInput
from execution.engine import ExecutionEngine
from execution.types import EntryMode, ExecutionOutcome, ExecutionRequest
from investigation.orchestrator import InvestigationOrchestrator
from investigation.types import (
    CandidateContext,
    InvestigationMode,
    InvestigationRequest,
    NoTradeResult,
)
from learning.category_ledger import CategoryLedgerBuilder
from learning.fast_loop import FastLearningLoop
from learning.no_trade_monitor import NoTradeMonitor
from learning.patience_budget import PatienceBudgetTracker
from learning.policy_review import PolicyReviewEngine
from learning.slow_loop import SlowLearningLoop
from learning.types import FastLoopInput, SlowLoopInput
from logging_.logger import get_logger
from market_data.service import MarketDataService
from notifications.events import NotificationEventBus
from notifications.service import NotificationService
from notifications.telegram import TelegramClient
from notifications.types import NotificationEnvelope
from risk.governor import RiskGovernor
from risk.types import PortfolioState
from scanner.scanner import TriggerScanner
from scanner.types import MarketWatchEntry, TriggerBatch
from tradeability.resolution_parser import ResolutionParser
from tradeability.synthesizer import TradeabilitySynthesizer
from tradeability.types import TradeabilityInput, TradeabilityOutcome
from viability.processor import ViabilityProcessor
from workflows.scheduler import WorkflowScheduler
from workflows.types import PipelineResult, PipelineStage, SystemPhase, SystemState

_log = get_logger(component="orchestrator")


class _ExecutionBackend(Protocol):
    """Execution sink interface for shadow, paper, and future live modes."""

    async def execute(
        self,
        orchestrator: WorkflowOrchestrator,
        card: Any,
        *,
        execution_request: ExecutionRequest,
        risk_assessment: Any,
        tradeability_result: Any,
        started: datetime,
    ) -> PipelineResult:
        ...


class WorkflowOrchestrator:
    """Central coordinator that wires all subsystems together.

    Owns the full lifecycle: init → start → run → shutdown.

    Usage:
        orchestrator = WorkflowOrchestrator(config)
        await orchestrator.initialize()
        await orchestrator.start()
        # system runs until shutdown signal
        await orchestrator.shutdown()
    """

    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._state = SystemState(operator_mode=config.operator_mode)
        # Live reference to the dashboard's shared state dict — populated in initialize().
        # Used so that mode changes made via the dashboard are respected by the pipeline
        # without requiring a restart.
        self._dashboard_state: dict[str, Any] | None = None
        self._session_factory: Any | None = None
        self._market_catalog: dict[str, Any] = {}

        # --- Subsystems (initialized in initialize()) ---
        # Core infrastructure
        self._market_data: MarketDataService | None = None
        self._scanner: TriggerScanner | None = None
        self._eligibility: EligibilityEngine | None = None

        # Governors (deterministic, highest authority)
        self._risk_governor: RiskGovernor | None = None
        self._cost_governor: CostGovernor | None = None

        # LLM framework
        self._provider_router: ProviderRouter | None = None
        self._regime_adapter: RegimeAdapter | None = None

        # Investigation & execution pipeline
        self._investigator: InvestigationOrchestrator | None = None
        self._resolution_parser: ResolutionParser | None = None
        self._tradeability: TradeabilitySynthesizer | None = None
        self._execution_engine = ExecutionEngine(config.risk)

        # Position management
        # (PositionReviewManager wired separately when positions exist)

        # Calibration & learning
        self._calibration_store: CalibrationStore | None = None
        self._brier_engine: BrierEngine | None = None
        self._segment_manager: SegmentManager | None = None
        self._accumulation_tracker: AccumulationTracker | None = None
        self._friction_calibrator: FrictionCalibrator | None = None
        self._fast_loop: FastLearningLoop | None = None
        self._slow_loop: SlowLearningLoop | None = None
        self._no_trade_monitor: NoTradeMonitor | None = None
        self._patience_budget: PatienceBudgetTracker | None = None

        # Cross-cutting
        self._bias_detector: BiasDetector | None = None
        self._bias_audit: BiasAuditRunner | None = None
        self._viability: ViabilityProcessor | None = None
        self._absence_manager: AbsenceManager | None = None

        # Notifications
        self._event_bus: NotificationEventBus | None = None
        self._notification_service: NotificationService | None = None

        # Scheduler
        self._scheduler = WorkflowScheduler()

        # Portfolio state (in-memory, updated by events)
        balance = getattr(config, "paper_balance_usd", 500.0)
        self._portfolio = PortfolioState(
            operator_mode=OperatorMode(config.operator_mode),
            account_balance_usd=balance,
            start_of_day_equity_usd=balance,
            current_equity_usd=balance,
        )

        # Pipeline lock for sequential processing
        self._pipeline_lock = asyncio.Lock()

        # Investigation cooldown: market_id → (rejected_at, price_at_rejection)
        self._investigation_cooldown: dict[str, tuple[datetime, float]] = {}

    # ================================================================
    # Lifecycle
    # ================================================================

    async def initialize(self) -> None:
        """Initialize all subsystems. Call once before start()."""
        self._state.phase = SystemPhase.INITIALIZING
        _log.info("orchestrator_initializing")

        # 1. Database — use SQLite for paper/shadow mode, PostgreSQL for live
        mode = OperatorMode(self._config.operator_mode)
        if mode in (OperatorMode.PAPER, OperatorMode.SHADOW):
            from pathlib import Path
            db_dir = Path("data")
            db_dir.mkdir(exist_ok=True)
            db_path = db_dir / "paper_trading.sqlite"
            db_url = f"sqlite+aiosqlite:///{db_path}"
            _log.info("using_sqlite_paper_mode", path=str(db_path))
        else:
            db_url = self._config.database.async_url

        try:
            await init_db(db_url)
        except Exception as exc:
            _log.error("database_init_failed", url_type="sqlite" if "sqlite" in db_url else "postgres", error=str(exc))
            raise
        session_factory = get_session_factory()
        self._session_factory = session_factory
        _log.info("database_initialized")
        self._log_activity("system", "Database", "Database initialized", severity="success")

        # 1b. Clean up stale "running" workflow runs from previous sessions.
        # These are safe to mark as failed — the previous process is gone and
        # no lock is held. Without this, the dashboard shows phantom running workflows.
        await self._cleanup_stale_running_workflows(session_factory)

        # 2. Market data service
        self._market_data = MarketDataService(self._config)
        await self._market_data.start()
        self._log_activity("system", "Market Data", "Market data service started")

        # 3. Governors (deterministic, no dependencies)
        self._risk_governor = RiskGovernor(self._config.risk)
        self._cost_governor = CostGovernor(self._config.cost)
        self._log_activity("system", "Governors", "Risk and Cost Governors initialized")

        # 4. Eligibility engine (deterministic)
        self._eligibility = EligibilityEngine(self._config.eligibility)

        # 5. LLM provider router
        self._provider_router = ProviderRouter.from_config(self._config)
        self._regime_adapter = RegimeAdapter()
        self._log_activity("system", "LLM Framework", "Provider router and regime adapter ready")

        # 6. Investigation engine
        self._investigator = InvestigationOrchestrator(
            router=self._provider_router,
            cost_governor=self._cost_governor,
            regime_adapter=self._regime_adapter,
            min_net_edge=self._config.risk.min_viable_impact_adjusted_edge,
            max_entry_impact_edge_fraction=self._config.risk.max_entry_impact_edge_fraction,
        )

        # 7. Tradeability
        self._resolution_parser = ResolutionParser(
            min_depth_usd=self._config.tradeability.min_depth_for_min_position_usd,
            max_spread=self._config.tradeability.max_spread,
        )
        self._tradeability = TradeabilitySynthesizer(
            router=self._provider_router,
        )

        # 8. Scanner (depends on market data)
        self._scanner = TriggerScanner(self._config, self._market_data)
        self._scanner.set_trigger_callback(self._on_triggers)
        self._log_activity("system", "Scanner", "Trigger scanner initialized")

        # 9. Calibration & learning subsystems
        self._calibration_store = CalibrationStore()
        self._brier_engine = BrierEngine(self._calibration_store)
        self._segment_manager = SegmentManager(
            store=self._calibration_store,
            config=self._config.calibration,
        )
        self._accumulation_tracker = AccumulationTracker(
            store=self._calibration_store,
            segment_manager=self._segment_manager,
        )
        self._friction_calibrator = FrictionCalibrator()
        self._no_trade_monitor = NoTradeMonitor()
        self._patience_budget = PatienceBudgetTracker(
            start_date=datetime.now(tz=UTC),
            budget_months=self._config.learning.patience_budget_months,
        )

        self._fast_loop = FastLearningLoop(
            store=self._calibration_store,
            brier_engine=self._brier_engine,
            segment_manager=self._segment_manager,
            friction_calibrator=self._friction_calibrator,
            no_trade_monitor=self._no_trade_monitor,
        )

        policy_engine = PolicyReviewEngine()
        self._slow_loop = SlowLearningLoop(
            brier_engine=self._brier_engine,
            segment_manager=self._segment_manager,
            accumulation_tracker=self._accumulation_tracker,
            friction_calibrator=self._friction_calibrator,
            policy_engine=policy_engine,
            no_trade_monitor=self._no_trade_monitor,
        )
        self._log_activity("system", "Calibration", "Learning loops configured")

        # 10. Cross-cutting systems
        self._bias_detector = BiasDetector()
        self._bias_audit = BiasAuditRunner(
            detector=self._bias_detector,
            calibration_store=self._calibration_store,
        )
        self._viability = ViabilityProcessor(
            calibration_config=self._config.calibration,
            cost_config=self._config.cost,
        )
        self._absence_manager = AbsenceManager(self._config.absence)

        # Record startup as an operator interaction
        self._absence_manager.record_interaction(
            OperatorInteraction(interaction_type=InteractionType.LOGIN)
        )

        # 11. Notification layer
        self._event_bus = NotificationEventBus()
        telegram_client = TelegramClient(self._config.telegram)
        self._notification_service = NotificationService(
            event_bus=self._event_bus,
            telegram_client=telegram_client,
            session_factory=session_factory,
        )

        # 12. Wire dashboard API state
        try:
            from dashboard_api.app import set_session_factory, set_app_config, _system_state, _persisted
            set_session_factory(session_factory)
            set_app_config(self._config)
            # Keep a live reference so pipeline decisions always use the current mode,
            # not the stale startup value from config.
            self._dashboard_state = _system_state
            # Persisted state (written by the dashboard) takes priority over config.
            # Only fall back to the config value when no mode has been saved to disk.
            if "operator_mode" not in _persisted:
                _system_state["operator_mode"] = self._config.operator_mode
            # else: _system_state already holds the dashboard-persisted mode — keep it.
            _system_state["system_status"] = "initializing"
            # Sync paper balance — only as default if not persisted
            balance = getattr(self._config, 'paper_balance_usd', 500.0)
            if _system_state.get("paper_balance_usd") is None:
                _system_state["paper_balance_usd"] = balance
            if _system_state.get("start_of_day_equity_usd") is None:
                _system_state["start_of_day_equity_usd"] = balance
        except ImportError:
            _log.warning("dashboard_api_not_available")

        self._log_activity(
            "system", "Orchestrator",
            f"System initialized in {self._current_mode().value} mode with ${getattr(self._config, 'paper_balance_usd', 500.0):.2f}",
            severity="success",
        )
        _log.info("orchestrator_initialized", subsystems=12)
        self._state.phase = SystemPhase.STARTING

    async def start(self) -> None:
        """Start all subsystems and begin processing."""
        if self._state.phase not in (SystemPhase.STARTING, SystemPhase.STOPPED):
            _log.warning("orchestrator_invalid_start_phase", phase=self._state.phase.value)
            return

        _log.info("orchestrator_starting")

        # Reset daily governors
        self._cost_governor.reset_day()
        self._risk_governor.reset_day(start_of_day_equity=self._portfolio.current_equity_usd)

        # Start notification service
        self._notification_service.start()
        self._state.notification_service_running = True

        # Start scanner
        await self._scanner.start()
        self._state.scanner_running = True
        self._log_activity("system", "Scanner", "Trigger scanner started — polling CLOB API", severity="success")

        # Register periodic tasks
        self._register_periodic_tasks()
        await self._scheduler.start_all()

        # Mark running
        self._state.phase = SystemPhase.RUNNING
        self._state.started_at = datetime.now(tz=UTC)

        # Update dashboard state
        self._sync_dashboard_state()

        # Emit startup notification
        await self._emit_system_health_event(
            "system_started",
            f"Polymarket Trader started in {self._current_mode().value} mode",
        )

        self._log_activity(
            "system", "Orchestrator",
            f"System LIVE in {self._current_mode().value.upper()} mode",
            detail=f"{self._scheduler.task_count} scheduled tasks registered",
            severity="success",
        )

        _log.info(
            "orchestrator_running",
            mode=self._config.operator_mode,
            scanner=self._state.scanner_running,
            scheduled_tasks=self._scheduler.task_count,
        )

    async def shutdown(self) -> None:
        """Gracefully shut down all subsystems."""
        self._state.phase = SystemPhase.SHUTTING_DOWN
        _log.info("orchestrator_shutting_down")

        # Stop periodic tasks
        await self._scheduler.stop_all()

        # Stop scanner
        if self._scanner and self._scanner.is_running:
            await self._scanner.stop()
            self._state.scanner_running = False

        # Stop notification service
        if self._notification_service:
            await self._notification_service.shutdown()
            self._state.notification_service_running = False

        # Stop market data
        if self._market_data:
            await self._market_data.stop()

        # Close database
        await close_db()

        self._state.phase = SystemPhase.STOPPED
        _log.info(
            "orchestrator_shutdown_complete",
            total_scans=self._state.total_scans,
            total_triggers=self._state.total_triggers,
            total_investigations=self._state.total_investigations,
            total_trades=self._state.total_trades_entered,
        )

    # ================================================================
    # Scanner trigger callback
    # ================================================================

    async def _on_triggers(self, batch: TriggerBatch) -> None:
        """Handle a batch of scanner triggers.

        Routes actionable triggers through the full pipeline:
        eligibility → investigation → tradeability → risk/cost → execution.
        """
        await self._refresh_runtime_portfolio_state()

        self._state.total_scans += 1
        self._state.total_triggers += len(batch.triggers)

        self._log_activity(
            "scan", "Scanner",
            f"Scan #{self._state.total_scans}: {len(batch.triggers)} triggers detected",
            detail=f"Batch {batch.batch_id}",
        )

        # Persist ALL triggers (including non-actionable) to the dashboard state
        try:
            from dashboard_api.app import _add_trigger_event
            for t in batch.triggers:
                watch_entry = self._get_watch_entry(token_id=t.token_id, market_id=t.market_id)
                _add_trigger_event(
                    trigger_class=t.trigger_class.value if hasattr(t.trigger_class, "value") else str(t.trigger_class),
                    trigger_level=t.trigger_level.value if hasattr(t.trigger_level, "value") else str(t.trigger_level),
                    market_id=t.market_id or t.token_id,
                    reason=t.reason or "",
                    price=t.price,
                    spread=t.spread,
                    data_source=getattr(t, "data_source", "live"),
                    market_title=watch_entry.title if watch_entry else None,
                )
        except Exception:
            pass

        await self._persist_trigger_events(batch.triggers)

        actionable = batch.actionable_triggers
        if not actionable:
            return

        self._log_activity(
            "trigger", "Scanner",
            f"{len(actionable)} actionable triggers from batch",
            severity="info",
        )

        _log.info(
            "triggers_received",
            batch_id=batch.batch_id,
            total=len(batch.triggers),
            actionable=len(actionable),
        )

        # Check absence restrictions
        if self._absence_manager and not self._absence_manager.can_enter_new_positions():
            _log.info("triggers_blocked_operator_absent")
            self._log_activity("risk", "Absence Manager", "Triggers blocked: operator absent", severity="warning")
            return

        # Check risk governor: can we trade at all?
        can_trade, reason = self._risk_governor.can_trade(self._portfolio)
        if not can_trade:
            _log.info("triggers_blocked_risk_governor", reason=reason)
            self._log_activity("risk", "Risk Governor", f"Triggers blocked: {reason}", severity="warning")
            return

        # Check cost governor
        can_start, reason = self._cost_governor.can_start_workflow()
        if not can_start:
            _log.info("triggers_blocked_cost_governor", reason=reason)
            self._log_activity("cost", "Cost Governor", f"Triggers blocked: {reason}", severity="warning")
            return

        # Process Level C/D triggers through investigation pipeline
        investigation_triggers = [
            t for t in actionable
            if t.trigger_level in (TriggerLevel.C.value, TriggerLevel.D.value, "C", "D")
        ]

        if investigation_triggers:
            self._log_activity(
                "investigation", "Pipeline",
                f"Processing {len(investigation_triggers)} C/D triggers through pipeline",
            )
            async with self._pipeline_lock:
                await self._run_trigger_pipeline(investigation_triggers, batch)

    def _current_mode(self) -> OperatorMode:
        """Return the live operator mode, respecting dashboard changes made at runtime."""
        if self._dashboard_state is not None:
            raw = self._dashboard_state.get("operator_mode", self._config.operator_mode)
        else:
            raw = self._config.operator_mode
        return OperatorMode(raw)

    async def _run_trigger_pipeline(
        self,
        triggers: list,
        batch: TriggerBatch,
    ) -> None:
        """Run the full candidate pipeline for trigger-based investigation."""
        # Build candidate contexts from triggers
        candidates: list[CandidateContext] = []
        for trigger in triggers:
            candidate = await self._build_candidate_from_trigger(trigger)
            if candidate is not None:
                candidates.append(candidate)

        if not candidates:
            return

        # Create investigation request
        run_id = f"trig-{batch.batch_id}-{uuid.uuid4().hex[:6]}"
        request = InvestigationRequest(
            workflow_run_id=run_id,
            mode=InvestigationMode.TRIGGER_BASED,
            candidates=candidates,
            max_candidates=3,
        )

        # Record workflow start
        run_started = datetime.now(tz=UTC)
        await self._persist_workflow_run(
            workflow_run_id=run_id,
            run_type="trigger_based",
            status="running",
            started_at=run_started,
            market_id=candidates[0].market_id if len(candidates) == 1 else None,
            operator_mode=self._current_mode().value,
        )
        try:
            from dashboard_api.app import _add_workflow_run
            _add_workflow_run(
                workflow_run_id=run_id,
                workflow_type="trigger_based",
                status="running",
                candidates_reviewed=len(candidates),
                started_at=run_started,
            )
        except Exception:
            pass

        # Run investigation
        try:
            self._state.total_investigations += 1
            self._log_activity(
                "investigation", "Investigator",
                f"Investigation #{self._state.total_investigations} started with {len(candidates)} candidates",
            )
            result = await self._investigator.run(
                request,
                regime=self._build_regime_context(),
            )
            self._record_investigation_spend(run_id, result)
            await self._persist_investigation_truth(
                workflow_run_id=run_id,
                result=result,
            )

            run_cost = getattr(result, "actual_cost_usd", 0.0) or 0.0

            # Update workflow run as completed
            workflow_outcome = (
                "candidate_accepted"
                if result.thesis_cards
                else "no_trade"
            )
            outcome_reason = self._summarize_no_trade_results(result.no_trade_results)
            cost_estimate = getattr(result, "cost_estimate", None)
            await self._persist_workflow_run(
                workflow_run_id=run_id,
                run_type="trigger_based",
                status="completed",
                completed_at=datetime.now(tz=UTC),
                estimated_cost_usd=getattr(cost_estimate, "expected_cost_max_usd", None),
                actual_cost_usd=run_cost,
                outcome=workflow_outcome,
                outcome_reason=outcome_reason,
                market_id=candidates[0].market_id if len(candidates) == 1 else None,
                operator_mode=self._current_mode().value,
                models_used=list(getattr(result, "models_used", []) or []),
                max_tier_used=getattr(result, "max_tier_used", None),
            )
            try:
                from dashboard_api.app import _add_workflow_run, _record_agent_invocation
                _add_workflow_run(
                    workflow_run_id=run_id,
                    workflow_type="trigger_based",
                    status="completed",
                    candidates_reviewed=len(candidates),
                    candidates_accepted=len(getattr(result, "thesis_cards", [])),
                    cost_usd=run_cost,
                    started_at=run_started,
                    completed_at=datetime.now(tz=UTC),
                )
                for role, cost in (getattr(result, "agent_costs", None) or {}).items():
                    if cost > 0:
                        _record_agent_invocation(role, cost)
            except Exception:
                pass

            # Record no-trade decisions
            if result.no_trade_results:
                self._state.total_no_trade_decisions += len(result.no_trade_results)
                for nt in result.no_trade_results:
                    self._no_trade_monitor.record_run(had_no_trade=True)
                    self._log_activity(
                        "trade", "Investigator",
                        f"No-trade: {getattr(nt, 'reason', 'insufficient edge')}",
                        detail=f"Market: {getattr(nt, 'market_id', '?')}",
                        severity="info",
                    )

                    # Emit no-trade notification
                    await self._emit_no_trade_event(nt)

                # Record investigation cooldowns for all rejected candidates
                for nt in result.no_trade_results:
                    nt_market_id = getattr(nt, "market_id", None)
                    if nt_market_id:
                        candidate_price = next(
                            (c.price for c in candidates if c.market_id == nt_market_id),
                            None,
                        )
                        self._record_investigation_rejection(nt_market_id, candidate_price)

            # Process accepted thesis cards through remaining pipeline
            for card in result.thesis_cards:
                self._no_trade_monitor.record_run(had_no_trade=False)
                self._log_activity(
                    "trade", "Investigator",
                    f"Thesis card accepted: {getattr(card, 'title', '?')[:60]}",
                    severity="success",
                )
                pipeline_result = await self._process_thesis_card(
                    card,
                    cost_approval=getattr(result, "cost_approval", None),
                )
                await self._persist_pipeline_result(
                    workflow_run_id=getattr(card, "workflow_run_id", ""),
                    card=card,
                    pipeline_result=pipeline_result,
                )

                if pipeline_result.accepted:
                    self._state.total_trades_entered += 1
                    self._log_activity(
                        "trade", "Execution",
                        f"Trade #{self._state.total_trades_entered} entered ({self._current_mode().value})",
                        detail=f"Market: {pipeline_result.market_id}",
                        severity="success",
                    )
                else:
                    self._no_trade_monitor.record_run(had_no_trade=True)
                    self._state.total_no_trade_decisions += 1
                    await self._emit_no_trade_event(NoTradeResult(
                        market_id=pipeline_result.market_id,
                        market_title=getattr(card, "core_thesis", None),
                        category=getattr(card, "category", None),
                        reason=pipeline_result.reason,
                        reason_code=pipeline_result.reason_code or "pipeline_reject",
                        stage=pipeline_result.stage_reached.value,
                        reason_detail=pipeline_result.reason_detail,
                        quantitative_context=pipeline_result.quantitative_context,
                        cost_spent_usd=pipeline_result.total_cost_usd,
                    ))

        except Exception as exc:
            _log.error(
                "trigger_pipeline_error",
                batch_id=batch.batch_id,
                error=str(exc),
            )
            self._log_activity("system", "Pipeline", f"Pipeline error: {str(exc)[:100]}", severity="error")
            self._state.recent_errors.append(
                f"Pipeline error: {str(exc)[:200]}"
            )
            await self._persist_workflow_run(
                workflow_run_id=run_id,
                run_type="trigger_based",
                status="failed",
                completed_at=datetime.now(tz=UTC),
                outcome="error",
                outcome_reason=str(exc)[:500],
                market_id=candidates[0].market_id if candidates and len(candidates) == 1 else None,
                operator_mode=self._current_mode().value,
            )
            try:
                from dashboard_api.app import _add_workflow_run
                _add_workflow_run(
                    workflow_run_id=run_id,
                    workflow_type="trigger_based",
                    status="failed",
                    started_at=run_started,
                    completed_at=datetime.now(tz=UTC),
                )
            except Exception:
                pass

    async def _process_thesis_card(
        self,
        card: Any,
        *,
        cost_approval: Any | None = None,
    ) -> PipelineResult:
        """Process a thesis card through tradeability → risk → cost → execution.

        Shadow, paper, and live all share the same approval path and diverge only
        at the final execution backend.
        """
        market_id = getattr(card, "market_id", "unknown")
        started = datetime.now(tz=UTC)

        _log.info(
            "processing_thesis_card",
            market_id=market_id,
            proposed_side=getattr(card, "proposed_side", None),
        )

        # --- Stage 1: Tradeability (deterministic parser first) ---
        try:
            parse_input = self._build_resolution_input(card)
            parse_result = self._resolution_parser.parse(parse_input)

            if parse_result.is_rejected:
                rejection_reason = (
                    parse_result.rejection_reason.value
                    if parse_result.rejection_reason
                    else parse_result.rejection_detail
                )
                return self._pipeline_reject(
                    market_id=market_id,
                    stage=PipelineStage.TRADEABILITY,
                    reason=(
                        "Hard rejection: "
                        f"{rejection_reason}"
                    ),
                    reason_code="tradeability_hard_reject",
                    reason_detail=parse_result.rejection_detail,
                    started=started,
                    quantitative_context={
                        "resolution_clarity": parse_result.clarity.value,
                        "rejection_reason": rejection_reason,
                    },
                )
        except Exception as exc:
            _log.error("tradeability_parse_error", market_id=market_id, error=str(exc))
            return self._pipeline_reject(
                market_id=market_id,
                stage=PipelineStage.TRADEABILITY,
                reason=f"Tradeability parse error: {str(exc)}",
                reason_code="tradeability_parse_error",
                reason_detail=str(exc),
                started=started,
            )

        tradeability_input = TradeabilityInput(
            market_id=market_id,
            workflow_run_id=getattr(card, "workflow_run_id", ""),
            title=parse_input.title,
            description=parse_input.description,
            resolution_parse=parse_result,
            spread=parse_input.spread,
            visible_depth_usd=parse_input.depth_usd,
            liquidity_usd=self._infer_visible_depth(card),
            mid_price=getattr(card, "market_implied_probability", None),
            gross_edge=getattr(card, "gross_edge", None),
            net_edge=getattr(card, "net_edge_after_cost", None),
            entry_impact_bps=getattr(card, "entry_impact_estimate_bps", None),
            min_position_size_usd=self._config.tradeability.min_depth_for_min_position_usd,
            depth_fraction_limit=self._config.risk.max_order_depth_fraction,
        )

        tradeability_result = await self._tradeability.assess(
            tradeability_input,
            regime=self._build_regime_context(),
        )
        if not tradeability_result.is_tradable:
            return self._pipeline_reject(
                market_id=market_id,
                stage=PipelineStage.TRADEABILITY,
                reason=tradeability_result.reason or "Tradeability rejected candidate",
                reason_code=tradeability_result.reason_code or (
                    "tradeability_watch"
                    if tradeability_result.outcome == TradeabilityOutcome.WATCH
                    else "tradeability_reject"
                ),
                reason_detail=tradeability_result.reason,
                started=started,
                quantitative_context={
                    "tradeability_outcome": tradeability_result.outcome.value,
                    "resolution_clarity": tradeability_result.resolution_clarity.value,
                    "liquidity_adjusted_max_size_usd": tradeability_result.liquidity_adjusted_max_size_usd,
                },
            )

        # --- Stage 2: Risk Governor approval ---
        risk_assessment = None
        try:
            risk_assessment = self._risk_governor.assess(
                self._build_sizing_request(card),
                self._portfolio,
            )

            if not risk_assessment.is_approved:
                return self._pipeline_reject(
                    market_id=market_id,
                    stage=PipelineStage.RISK_APPROVAL,
                    reason=f"Risk Governor: {risk_assessment.reason}",
                    reason_code="risk_reject",
                    reason_detail=risk_assessment.reason,
                    started=started,
                    quantitative_context={
                        "risk_approval": getattr(risk_assessment.approval, "value", None),
                    },
                )
        except Exception as exc:
            _log.error("risk_assessment_error", market_id=market_id, error=str(exc))
            return self._pipeline_reject(
                market_id=market_id,
                stage=PipelineStage.RISK_APPROVAL,
                reason=f"Risk assessment error: {str(exc)}",
                reason_code="risk_reject",
                reason_detail=str(exc),
                started=started,
            )

        mode = self._current_mode()
        # --- Stage 3: Cost approval checkpoint ---
        if cost_approval is not None and not cost_approval.is_approved:
            return self._pipeline_reject(
                market_id=market_id,
                stage=PipelineStage.COST_APPROVAL,
                reason=f"Cost Governor: {cost_approval.reason}",
                reason_code="cost_governor_reject",
                reason_detail=cost_approval.reason,
                started=started,
                quantitative_context={
                    "decision": cost_approval.decision.value,
                    "approved_max_tier": (
                        cost_approval.approved_max_tier.value
                        if cost_approval.approved_max_tier is not None
                        else None
                    ),
                    "approved_max_cost_usd": cost_approval.approved_max_cost_usd,
                },
            )

        requested_size = (
            risk_assessment.sizing.recommended_size_usd
            if risk_assessment is not None and risk_assessment.sizing is not None
            else 0.0
        )
        liquidity_adjusted_max = (
            tradeability_result.liquidity_adjusted_max_size_usd
            if tradeability_result.liquidity_adjusted_max_size_usd > 0
            else requested_size
        )
        approved_size = min(requested_size, liquidity_adjusted_max)
        if approved_size <= 0:
            return self._pipeline_reject(
                market_id=market_id,
                stage=PipelineStage.RISK_APPROVAL,
                reason="Approved size after tradeability and risk checks is zero",
                reason_code="risk_reject",
                reason_detail="Combined tradeability and risk sizing left no executable size.",
                started=started,
            )

        execution_request = self._build_execution_request(
            card,
            risk_assessment,
            tradeability_result,
            size_usd=approved_size,
            cost_approval=cost_approval,
        )
        backend = self._execution_backend_for_mode(mode)
        return await backend.execute(
            self,
            card,
            execution_request=execution_request,
            risk_assessment=risk_assessment,
            tradeability_result=tradeability_result,
            started=started,
        )

    def _pipeline_reject(
        self,
        *,
        market_id: str,
        stage: PipelineStage,
        reason: str,
        reason_code: str,
        started: datetime,
        reason_detail: str | None = None,
        quantitative_context: dict[str, Any] | None = None,
    ) -> PipelineResult:
        """Build a consistent rejected pipeline result."""
        return PipelineResult(
            market_id=market_id,
            stage_reached=stage,
            reason=reason,
            reason_code=reason_code,
            reason_detail=reason_detail,
            quantitative_context=quantitative_context or {},
            duration_seconds=(datetime.now(tz=UTC) - started).total_seconds(),
        )

    def _summarize_no_trade_results(self, no_trade_results: list[Any]) -> str | None:
        """Create a short workflow outcome summary from typed no-trade results."""
        parts = []
        for item in no_trade_results or []:
            reason_code = getattr(item, "reason_code", "") or ""
            reason = getattr(item, "reason", "") or reason_code or "no_trade"
            parts.append(f"{reason_code}: {reason}" if reason_code else reason)
        if not parts:
            return None
        return "; ".join(parts)[:500]

    def _execution_backend_for_mode(self, mode: OperatorMode) -> _ExecutionBackend:
        """Resolve the execution backend for the current operator mode."""
        if mode == OperatorMode.SHADOW:
            return _ShadowExecutionBackend()
        if mode == OperatorMode.PAPER:
            return _PaperExecutionBackend()
        return _LiveExecutionBackend()

    def _build_execution_request(
        self,
        card: Any,
        risk_assessment: Any,
        tradeability_result: Any,
        *,
        size_usd: float,
        cost_approval: Any | None,
    ) -> ExecutionRequest:
        """Build a normalized execution request shared by all backends."""
        watch_entry = self._get_watch_entry(market_id=getattr(card, "market_id", ""))
        token_id = watch_entry.token_id if watch_entry else ""
        price = (
            (watch_entry.last_price if watch_entry else None)
            or getattr(card, "market_implied_probability", None)
            or getattr(card, "calibrated_probability", None)
            or 0.5
        )
        current_depth = (
            (watch_entry.last_depth_top3 if watch_entry else None)
            or self._infer_visible_depth(card)
        )

        preferred_entry_mode = EntryMode.IMMEDIATE
        if current_depth and size_usd > current_depth * 0.05:
            preferred_entry_mode = EntryMode.STAGED
        elif tradeability_result.outcome == TradeabilityOutcome.TRADABLE_REDUCED:
            preferred_entry_mode = EntryMode.STAGED

        return ExecutionRequest(
            workflow_run_id=getattr(card, "workflow_run_id", ""),
            market_id=getattr(card, "market_id", ""),
            token_id=token_id,
            side="buy",
            price=float(price),
            size_usd=float(size_usd),
            current_spread=(watch_entry.last_spread if watch_entry else None) or getattr(card, "expected_friction_spread", None),
            current_depth_usd=float(current_depth or 0.0),
            current_mid_price=float(price),
            market_status="active",
            risk_approval=risk_assessment.approval.value,
            risk_conditions=risk_assessment.special_conditions,
            cost_approval=(
                cost_approval.decision.value
                if cost_approval is not None
                else "approved_pre_run"
            ),
            tradeability_outcome=tradeability_result.outcome.value,
            entry_impact_bps=getattr(card, "entry_impact_estimate_bps", 0.0) or 0.0,
            gross_edge=getattr(card, "gross_edge", 0.0) or 0.0,
            liquidity_relative_size_pct=(
                float(size_usd) / float(current_depth)
                if current_depth
                else 0.0
            ),
            preferred_entry_mode=preferred_entry_mode,
            drawdown_level=risk_assessment.drawdown_state.level.value,
            operator_mode=self._current_mode().value,
            approved_at=datetime.now(tz=UTC),
            max_spread=self._config.tradeability.max_spread,
            max_order_depth_fraction=self._config.risk.max_order_depth_fraction,
            max_entry_impact_edge_fraction=self._config.risk.max_entry_impact_edge_fraction,
        )

    # ================================================================
    # Scheduled broad sweep
    # ================================================================

    async def _run_scheduled_sweep(self) -> None:
        """Run a scheduled broad sweep investigation (2-3x daily).

        Discovers eligible markets and investigates top candidates.
        """
        _log.info("scheduled_sweep_starting")

        # Check preconditions
        if not self._absence_manager.can_enter_new_positions():
            _log.info("sweep_skipped_operator_absent")
            return

        can_trade, reason = self._risk_governor.can_trade(self._portfolio)
        if not can_trade:
            _log.info("sweep_skipped_risk", reason=reason)
            return

        can_start, reason = self._cost_governor.can_start_workflow()
        if not can_start:
            _log.info("sweep_skipped_cost", reason=reason)
            return

        sweep_run_id = f"sweep-{uuid.uuid4().hex[:8]}"
        sweep_started = datetime.now(tz=UTC)
        await self._persist_workflow_run(
            workflow_run_id=sweep_run_id,
            run_type="scheduled_sweep",
            status="running",
            started_at=sweep_started,
            operator_mode=self._current_mode().value,
        )
        try:
            from dashboard_api.app import _add_workflow_run
            _add_workflow_run(
                workflow_run_id=sweep_run_id,
                workflow_type="scheduled_sweep",
                status="running",
                started_at=sweep_started,
            )
        except Exception:
            pass

        try:
            # Discover active markets
            markets = await self._market_data.discover_markets()

            # Pre-filter to the eligible horizon window (24h–90d) and sort by
            # liquidity descending so we check the most active markets first.
            _now = datetime.now(tz=UTC)
            _min_horizon = timedelta(hours=self._config.eligibility.min_horizon_hours)
            _max_horizon = timedelta(days=self._config.eligibility.max_horizon_days)
            markets_filtered = [
                m for m in markets
                if m.end_date is None or _min_horizon <= (m.end_date - _now) <= _max_horizon
            ]
            markets_filtered.sort(key=lambda m: m.liquidity or 0.0, reverse=True)

            _log.info(
                "sweep_market_pool",
                total=len(markets),
                after_horizon_filter=len(markets_filtered),
            )

            # Build eligibility inputs and evaluate
            eligible_candidates: list[CandidateContext] = []
            # Collect (market_id_str, elig_result) pairs for DB persistence
            _elig_decisions_to_persist: list[tuple[str, Any]] = []
            for market in markets_filtered[:50]:  # cap to prevent overload
                elig_input = MarketEligibilityInput(
                    market_id=market.market_id or str(uuid.uuid4()),
                    title=market.title or "",
                    description=market.description or "",
                    category_raw=market.category or "",
                    slug=market.slug or "",
                    tags=market.tags or [],
                    liquidity_usd=market.liquidity or 0.0,
                    spread=market.spread or 0.0,
                    end_date=market.end_date,
                    resolution_source=market.resolution_source or "polymarket.com",
                )

                result = self._eligibility.evaluate(elig_input)
                _elig_decisions_to_persist.append((elig_input.market_id, result))

                watchlist_outcomes = {
                    EligibilityOutcome.INVESTIGATE_NOW.value,
                    EligibilityOutcome.TRIGGER_ELIGIBLE.value,
                }
                if result.outcome in watchlist_outcomes:
                    token_id = market.token_ids[0] if market.token_ids else ""
                    # All watchlist-eligible markets go on the scanner watch list.
                    if token_id:
                        self._scanner.add_to_watch_list(
                            MarketWatchEntry(
                                market_id=elig_input.market_id,
                                token_id=token_id,
                                title=elig_input.title,
                                description=elig_input.description,
                                category=result.category_classification.category or "unknown",
                                category_quality_tier=result.category_classification.quality_tier,
                                resolution_source=elig_input.resolution_source,
                                tags=elig_input.tags,
                                end_date=elig_input.end_date,
                                last_spread=elig_input.spread,
                            )
                        )
                    # Only INVESTIGATE_NOW markets become active investigation candidates.
                    if result.outcome == EligibilityOutcome.INVESTIGATE_NOW.value:
                        # Skip near-certainty markets — no exploitable edge.
                        # MarketInfo from discovery has no real-time price; use getattr safely.
                        market_price = getattr(market, 'price', None) or getattr(market, 'mid_price', None)
                        if market_price is not None and (market_price < 0.04 or market_price > 0.96):
                            continue
                        eligible_candidates.append(
                            CandidateContext(
                                market_id=elig_input.market_id,
                                token_id=token_id,
                                title=elig_input.title,
                                category=result.category_classification.category or "unknown",
                                trigger_class="discovery",
                                trigger_level="C",
                                price=getattr(market, 'price', None) or getattr(market, 'mid_price', None) or 0.5,
                                mid_price=getattr(market, 'mid_price', None) or getattr(market, 'price', None) or 0.5,
                                spread=elig_input.spread,
                                visible_depth_usd=elig_input.liquidity_usd,
                                description=market.description,
                                end_date=market.end_date,
                                end_date_hours=max(0.0, (market.end_date - datetime.now(tz=UTC)).total_seconds() / 3600) if market.end_date else None,
                                metadata_status=(
                                    "complete"
                                    if result.category_classification.category and elig_input.title
                                    else "unknown_category"
                                ),
                                metadata_issues=(
                                    []
                                    if result.category_classification.category and elig_input.title
                                    else ["unknown_category"]
                                ),
                            )
                        )

            _log.info(
                "sweep_eligibility_complete",
                markets_checked=min(len(markets_filtered), 50),
                eligible=len(eligible_candidates),
                watch_list_size=self._scanner.get_watch_list().__len__(),
            )

            # Persist eligibility decisions to DB (best-effort — don't fail sweep on error)
            if _elig_decisions_to_persist and self._session_factory is not None:
                try:
                    async with self._session_factory() as session:
                        for ext_market_id, elig_result in _elig_decisions_to_persist:
                            watch_entry = self._get_watch_entry(market_id=ext_market_id)
                            market_obj = await self._ensure_market_row(
                                session,
                                external_market_id=ext_market_id,
                                watch_entry=watch_entry,
                            )
                            await self._persist_eligibility_decision(
                                market_obj=market_obj,
                                result=elig_result,
                                session=session,
                            )
                        await session.commit()
                except Exception as _elig_exc:
                    _log.warning("sweep_eligibility_persist_failed", error=str(_elig_exc))

            if not eligible_candidates:
                self._state.total_no_trade_decisions += 1
                await self._persist_workflow_run(
                    workflow_run_id=sweep_run_id,
                    run_type="scheduled_sweep",
                    status="completed",
                    completed_at=datetime.now(tz=UTC),
                    outcome="no_trade",
                    outcome_reason="No eligible investigate-now candidates",
                    operator_mode=self._current_mode().value,
                )
                try:
                    from dashboard_api.app import _add_workflow_run
                    _add_workflow_run(
                        workflow_run_id=sweep_run_id,
                        workflow_type="scheduled_sweep",
                        status="completed",
                        candidates_reviewed=0,
                        candidates_accepted=0,
                        cost_usd=0.0,
                        started_at=sweep_started,
                        completed_at=datetime.now(tz=UTC),
                    )
                except Exception:
                    pass
                return

            # Run investigation on top candidates
            request = InvestigationRequest(
                workflow_run_id=sweep_run_id,
                mode=InvestigationMode.SCHEDULED_SWEEP,
                candidates=eligible_candidates[:10],
                max_candidates=3,
            )

            self._state.total_investigations += 1
            result = await self._investigator.run(
                request,
                regime=self._build_regime_context(),
            )
            self._record_investigation_spend(sweep_run_id, result)
            await self._persist_investigation_truth(
                workflow_run_id=sweep_run_id,
                result=result,
            )

            sweep_cost = getattr(result, "actual_cost_usd", 0.0) or 0.0
            outcome = "candidate_accepted" if result.thesis_cards else "no_trade"
            outcome_reason = self._summarize_no_trade_results(result.no_trade_results)

            cost_estimate = getattr(result, "cost_estimate", None)
            await self._persist_workflow_run(
                workflow_run_id=sweep_run_id,
                run_type="scheduled_sweep",
                status="completed",
                completed_at=datetime.now(tz=UTC),
                estimated_cost_usd=getattr(cost_estimate, "expected_cost_max_usd", None),
                actual_cost_usd=sweep_cost,
                outcome=outcome,
                outcome_reason=outcome_reason,
                operator_mode=self._current_mode().value,
                models_used=list(getattr(result, "models_used", []) or []),
                max_tier_used=getattr(result, "max_tier_used", None),
            )
            try:
                from dashboard_api.app import _add_workflow_run, _record_agent_invocation
                _add_workflow_run(
                    workflow_run_id=sweep_run_id,
                    workflow_type="scheduled_sweep",
                    status="completed",
                    candidates_reviewed=len(eligible_candidates[:10]),
                    candidates_accepted=len(getattr(result, "thesis_cards", [])),
                    cost_usd=sweep_cost,
                    started_at=sweep_started,
                    completed_at=datetime.now(tz=UTC),
                )
                for role, cost in (getattr(result, "agent_costs", None) or {}).items():
                    if cost > 0:
                        _record_agent_invocation(role, cost)
            except Exception:
                pass

            for card in result.thesis_cards:
                pipeline_result = await self._process_thesis_card(
                    card,
                    cost_approval=getattr(result, "cost_approval", None),
                )
                await self._persist_pipeline_result(
                    workflow_run_id=getattr(card, "workflow_run_id", ""),
                    card=card,
                    pipeline_result=pipeline_result,
                )
                if pipeline_result.accepted:
                    self._state.total_trades_entered += 1
                else:
                    self._no_trade_monitor.record_run(had_no_trade=True)
                    self._state.total_no_trade_decisions += 1
                    await self._emit_no_trade_event(NoTradeResult(
                        market_id=pipeline_result.market_id,
                        market_title=getattr(card, "core_thesis", None),
                        category=getattr(card, "category", None),
                        reason=pipeline_result.reason,
                        reason_code=pipeline_result.reason_code or "pipeline_reject",
                        stage=pipeline_result.stage_reached.value,
                        reason_detail=pipeline_result.reason_detail,
                        quantitative_context=pipeline_result.quantitative_context,
                        cost_spent_usd=pipeline_result.total_cost_usd,
                    ))

            if result.no_trade_results:
                self._state.total_no_trade_decisions += len(result.no_trade_results)
                # Record investigation cooldowns for all rejected sweep candidates
                for nt in result.no_trade_results:
                    nt_market_id = getattr(nt, "market_id", None)
                    if nt_market_id:
                        candidate_price = next(
                            (c.price for c in eligible_candidates if c.market_id == nt_market_id),
                            None,
                        )
                        self._record_investigation_rejection(nt_market_id, candidate_price)

            _log.info(
                "scheduled_sweep_complete",
                candidates_evaluated=result.candidates_evaluated,
                accepted=result.candidates_accepted,
                no_trade=len(result.no_trade_results),
            )

        except Exception as exc:
            await self._persist_workflow_run(
                workflow_run_id=sweep_run_id,
                run_type="scheduled_sweep",
                status="failed",
                completed_at=datetime.now(tz=UTC),
                outcome="error",
                outcome_reason=str(exc)[:500],
                operator_mode=self._current_mode().value,
            )
            _log.error("scheduled_sweep_error", error=str(exc))

    # ================================================================
    # Periodic task functions
    # ================================================================

    def _register_periodic_tasks(self) -> None:
        """Register all recurring background tasks."""
        # Scheduled sweep: every 8 hours (3x daily)
        self._scheduler.register(
            "scheduled_sweep",
            self._run_scheduled_sweep,
            interval_hours=8.0,
            initial_delay_seconds=60.0,
        )

        # Fast learning loop: daily
        self._scheduler.register(
            "fast_loop",
            self._run_fast_loop,
            interval_hours=self._config.learning.fast_loop_interval_hours,
            initial_delay_seconds=120.0,
        )

        # Slow learning loop: weekly
        self._scheduler.register(
            "slow_loop",
            self._run_slow_loop,
            interval_hours=self._config.learning.slow_loop_interval_hours,
            initial_delay_seconds=300.0,
        )

        # Absence monitor: hourly
        self._scheduler.register(
            "absence_monitor",
            self._run_absence_check,
            interval_hours=1.0,
            initial_delay_seconds=30.0,
        )

        # Daily governor reset: every 24 hours
        self._scheduler.register(
            "daily_reset",
            self._run_daily_reset,
            interval_hours=24.0,
            initial_delay_seconds=600.0,
        )

        # Dashboard state sync: every 5 minutes
        self._scheduler.register(
            "dashboard_sync",
            self._run_dashboard_sync,
            interval_hours=5.0 / 60.0,
            initial_delay_seconds=15.0,
        )

    async def _run_fast_loop(self) -> None:
        """Execute the daily fast learning loop."""
        _log.info("fast_loop_executing")

        budget_state = self._cost_governor.budget_tracker.state
        selectivity = self._cost_governor.get_selectivity_snapshot()
        absence_state = self._absence_manager.compute_state()

        inp = FastLoopInput(
            as_of=datetime.now(tz=UTC),
            new_resolutions=0,  # populated from DB in production
            trades_since_friction_check=0,
            daily_spend_usd=budget_state.daily_spent_usd,
            trades_entered_today=0,
            cost_selectivity_ratio=selectivity.cost_to_edge_ratio,
            daily_budget_remaining_pct=(
                budget_state.daily_remaining_usd / max(budget_state.daily_budget_usd, 0.01)
            ),
            lifetime_budget_consumed_pct=(
                budget_state.lifetime_spent_usd / max(budget_state.lifetime_budget_usd, 0.01)
            ),
            operator_absent=absence_state.absence_level.value >= 1,
            absence_hours=absence_state.hours_since_last_interaction,
        )

        result = self._fast_loop.execute(inp)

        if result.warnings:
            _log.warning("fast_loop_warnings", warnings=result.warnings)

        if result.budget_alerts:
            for alert in result.budget_alerts:
                await self._emit_system_health_event("budget_alert", alert)

    async def _run_slow_loop(self) -> None:
        """Execute the weekly slow learning loop."""
        _log.info("slow_loop_executing")

        inp = SlowLoopInput(
            as_of=datetime.now(tz=UTC),
            period_weeks=1,
        )

        result = self._slow_loop.execute(inp)

        if result.warnings:
            _log.warning("slow_loop_warnings", warnings=result.warnings)
        if result.policy_proposals:
            _log.info("slow_loop_proposals", count=len(result.policy_proposals))

    async def _run_absence_check(self) -> None:
        """Check operator absence status."""
        state = self._absence_manager.compute_state()

        if state.absence_level.value >= 1:
            _log.warning(
                "operator_absent",
                level=state.absence_level.value,
                hours=state.hours_since_last_interaction,
            )

            await self._emit_event(
                NotificationType.OPERATOR_ABSENCE,
                NotificationSeverity.WARNING
                if state.absence_level.value < 4
                else NotificationSeverity.CRITICAL,
                payload={
                    "absence_level": state.absence_level.value,
                    "absence_level_name": state.absence_level_name,
                    "hours_since_activity": state.hours_since_last_interaction,
                    "restrictions": [r.value for r in state.restrictions],
                },
            )

    async def _run_daily_reset(self) -> None:
        """Reset daily counters for governors."""
        _log.info("daily_reset_executing")
        self._cost_governor.reset_day()
        self._risk_governor.reset_day(
            start_of_day_equity=self._portfolio.current_equity_usd
        )

    async def _run_dashboard_sync(self) -> None:
        """Sync system state to dashboard API."""
        await self._mark_to_market_paper_positions()
        await self._refresh_runtime_portfolio_state()
        self._sync_dashboard_state()

    # ================================================================
    # Helpers
    # ================================================================

    def _build_regime_context(self) -> RegimeContext:
        """Build the current regime context for agent behavior."""
        selectivity = self._cost_governor.get_selectivity_snapshot() if self._cost_governor else None

        calibration = CalibrationContext(
            regime=CalibrationRegime.INSUFFICIENT,
            viability_proven=False,
            sports_quality_gated=True,
        )

        return RegimeContext(
            calibration=calibration,
            cost_selectivity_ratio=selectivity.cost_to_edge_ratio if selectivity else 0.0,
            operator_mode=self._current_mode(),
        )

    def _record_investigation_spend(self, workflow_run_id: str, result: Any) -> None:
        """Record aggregate investigation spend into the Cost Governor."""
        if self._cost_governor is None:
            return

        actual_cost = float(getattr(result, "actual_cost_usd", 0.0) or 0.0)
        if actual_cost <= 0:
            return

        models_used = [
            str(model).lower()
            for model in (getattr(result, "models_used", None) or [])
        ]
        if any("opus" in model for model in models_used):
            tier = ModelTier.A
            cost_class = CostClass.H
            provider = "openrouter"
        elif any("sonnet" in model for model in models_used):
            tier = ModelTier.B
            cost_class = CostClass.M
            provider = "openrouter"
        else:
            tier = ModelTier.C
            cost_class = CostClass.L
            provider = "openai"

        model_name = models_used[0] if models_used else "aggregate_investigation"
        self._cost_governor.record_spend(
            CostRecordInput(
                workflow_run_id=workflow_run_id,
                agent_role="investigation_workflow",
                model=model_name,
                provider=provider,
                tier=tier,
                cost_class=cost_class,
                input_tokens=0,
                output_tokens=0,
                estimated_cost_usd=actual_cost,
                actual_cost_usd=actual_cost,
            )
        )
        self._sync_dashboard_state()

    def _get_watch_entry(
        self,
        *,
        token_id: str | None = None,
        market_id: str | None = None,
    ) -> MarketWatchEntry | None:
        """Resolve market metadata from the scanner watch list."""
        if self._scanner is None:
            return None
        if token_id:
            entry = self._scanner.get_watch_entry(token_id)
            if entry is not None:
                return entry
        if market_id:
            return self._scanner.get_watch_entry_by_market(market_id)
        return None

    async def _load_market_catalog(self, *, force: bool = False) -> None:
        """Populate a lightweight market metadata cache from Gamma."""
        if self._market_data is None or (self._market_catalog and not force):
            return

        try:
            markets = await self._market_data.discover_markets()
        except Exception as exc:
            _log.warning("market_catalog_refresh_failed", error=str(exc))
            return

        self._market_catalog = {m.market_id: m for m in markets}
        if self._scanner is None:
            return

        for market in markets:
            for token_id in market.token_ids:
                entry = self._scanner.get_watch_entry(token_id)
                if entry is None:
                    continue
                if not entry.title:
                    entry.title = market.title
                if not entry.description:
                    entry.description = market.description
                if not entry.category:
                    entry.category = market.category
                if not entry.tags:
                    entry.tags = market.tags
                if not entry.resolution_source:
                    entry.resolution_source = market.resolution_source
                if entry.end_date is None:
                    entry.end_date = market.end_date

    def _resolve_market_metadata(
        self,
        *,
        external_market_id: str,
        watch_entry: MarketWatchEntry | None = None,
        card: Any | None = None,
    ) -> dict[str, Any]:
        """Resolve market metadata from watch list, catalog, and thesis data."""
        market_info = self._market_catalog.get(external_market_id or "")
        actual_title = (
            (watch_entry.title if watch_entry else None)
            or (market_info.title if market_info else None)
            or getattr(card, "core_thesis", None)
        )
        description = (
            (watch_entry.description if watch_entry else None)
            or (market_info.description if market_info else None)
            or getattr(card, "resolution_interpretation", None)
        )
        raw_category = (
            (watch_entry.category if watch_entry else None)
            or (market_info.category if market_info else None)
            or getattr(card, "category", None)
        )
        tags = list(
            (watch_entry.tags if watch_entry else None)
            or (market_info.tags if market_info else None)
            or []
        )
        slug = getattr(market_info, "slug", None)
        classification = classify_category(
            raw_category=raw_category,
            tags=tags,
            slug=slug,
            title=actual_title or "",
        )

        category = classification.category or (raw_category.strip() if isinstance(raw_category, str) and raw_category.strip() else "unknown")
        quality_tier = (
            (watch_entry.category_quality_tier if watch_entry else None)
            or getattr(card, "category_quality_tier", None)
            or classification.quality_tier
            or ("quality_gated" if category == "sports" else "standard")
        )
        display_title = actual_title or external_market_id or "metadata_incomplete"

        issues: list[str] = []
        if not actual_title:
            issues.append("missing_title")
        if category == "unknown":
            issues.append("unknown_category")
        metadata_status = "complete"
        if "missing_title" in issues:
            metadata_status = "metadata_incomplete"
        elif "unknown_category" in issues:
            metadata_status = "unknown_category"

        return {
            "title": display_title,
            "description": description,
            "category": category,
            "category_quality_tier": quality_tier,
            "resolution_source": (
                (watch_entry.resolution_source if watch_entry else None)
                or (market_info.resolution_source if market_info else None)
                or getattr(card, "resolution_source_language", None)
            ),
            "end_date": (
                (watch_entry.end_date if watch_entry else None)
                or (market_info.end_date if market_info else None)
            ),
            "tags": tags,
            "price": (
                (watch_entry.last_price if watch_entry else None)
                or (market_info.price if market_info else None)
                or (market_info.mid_price if market_info else None)
                or getattr(card, "market_implied_probability", None)
            ),
            "spread": (
                (watch_entry.last_spread if watch_entry else None)
                or (market_info.spread if market_info else None)
            ),
            "visible_depth_usd": (
                (watch_entry.last_depth_top3 if watch_entry else None)
                or (market_info.liquidity if market_info else None)
                or 0.0
            ),
            "metadata_status": metadata_status,
            "metadata_issues": issues,
        }

    # --- Investigation cooldown constants ---
    _INVESTIGATION_COOLDOWN_HOURS: float = 3.0   # don't re-investigate within 3 hours
    _INVESTIGATION_COOLDOWN_PRICE_BAND: float = 0.04  # unless price moved > 4%

    def _is_in_investigation_cooldown(
        self, market_id: str, current_price: float | None
    ) -> bool:
        """Return True if this market was recently rejected and price hasn't moved enough."""
        entry = self._investigation_cooldown.get(market_id)
        if entry is None:
            return False
        rejected_at, rejected_price = entry
        hours_elapsed = (datetime.now(tz=UTC) - rejected_at).total_seconds() / 3600
        if hours_elapsed >= self._INVESTIGATION_COOLDOWN_HOURS:
            del self._investigation_cooldown[market_id]
            return False
        if current_price is not None and abs(current_price - rejected_price) > self._INVESTIGATION_COOLDOWN_PRICE_BAND:
            return False  # Price moved significantly — allow re-investigation
        return True

    def _record_investigation_rejection(self, market_id: str, price: float | None) -> None:
        """Record that a market was rejected by investigation at this price."""
        self._investigation_cooldown[market_id] = (datetime.now(tz=UTC), price or 0.5)

    async def _build_candidate_from_trigger(self, trigger: Any) -> CandidateContext | None:
        """Build a trigger-based candidate with real market metadata."""
        watch_entry = self._get_watch_entry(token_id=trigger.token_id, market_id=trigger.market_id)
        if watch_entry is None or not watch_entry.category or not watch_entry.title:
            await self._load_market_catalog(force=True)
            watch_entry = self._get_watch_entry(token_id=trigger.token_id, market_id=trigger.market_id)
        metadata = self._resolve_market_metadata(
            external_market_id=trigger.market_id or trigger.token_id,
            watch_entry=watch_entry,
        )
        title = metadata["title"]
        description = metadata["description"]
        category = metadata["category"]
        end_date = metadata["end_date"]
        visible_depth = (
            (trigger.depth_snapshot or {}).get("top3_usd")
            or metadata["visible_depth_usd"]
            or 0.0
        )

        end_date_hours = None
        if end_date is not None:
            end_date_hours = max(
                0.0,
                (end_date - datetime.now(tz=UTC)).total_seconds() / 3600.0,
            )

        category_quality_tier = metadata["category_quality_tier"]

        # --- Pre-filter 1: Price at extreme (near certainty — no exploitable edge) ---
        current_price = trigger.price or metadata["price"]
        if current_price is not None and (current_price < 0.04 or current_price > 0.96):
            _log.info(
                "candidate_skipped_price_extreme",
                market_id=trigger.market_id,
                price=current_price,
            )
            return None

        # --- Pre-filter 2: Sports short-horizon (quality-gated markets < 7 days) ---
        if category_quality_tier == "quality_gated" and end_date_hours is not None and end_date_hours < 168:
            _log.info(
                "candidate_skipped_sports_short_horizon",
                market_id=trigger.market_id,
                hours_remaining=end_date_hours,
            )
            return None

        # --- Pre-filter 3: Investigation cooldown ---
        if self._is_in_investigation_cooldown(trigger.market_id or trigger.token_id, current_price):
            _log.debug(
                "candidate_skipped_investigation_cooldown",
                market_id=trigger.market_id,
            )
            return None

        return CandidateContext(
            market_id=trigger.market_id or trigger.token_id,
            token_id=trigger.token_id,
            title=title,
            description=description,
            category=category,
            category_quality_tier=category_quality_tier,
            tags=list(metadata["tags"] or []),
            trigger_class=trigger.trigger_class,
            trigger_level=trigger.trigger_level,
            trigger_reason=trigger.reason or "",
            price=trigger.price or metadata["price"] or 0.5,
            mid_price=trigger.price or metadata["price"] or 0.5,
            spread=trigger.spread if trigger.spread is not None else metadata["spread"],
            visible_depth_usd=float(visible_depth),
            eligibility_outcome=EligibilityOutcome.TRIGGER_ELIGIBLE.value,
            resolution_source=metadata["resolution_source"],
            end_date=end_date,
            end_date_hours=end_date_hours,
            metadata_status=metadata["metadata_status"],
            metadata_issues=metadata["metadata_issues"],
        )

    def _infer_visible_depth(self, card: Any) -> float:
        """Infer visible depth when only a liquidity-adjusted max size is available."""
        explicit = getattr(card, "visible_depth_usd", None)
        if explicit:
            return float(explicit)

        max_size = getattr(card, "liquidity_adjusted_max_size_usd", None)
        if max_size:
            return float(max_size) / max(self._config.risk.max_order_depth_fraction, 0.01)
        return 0.0

    def _build_resolution_input(self, card: Any) -> Any:
        """Build resolution parse input from watch-list market metadata."""
        from tradeability.types import ResolutionParseInput

        watch_entry = self._get_watch_entry(market_id=getattr(card, "market_id", ""))
        title = (watch_entry.title if watch_entry else None) or getattr(card, "core_thesis", "") or getattr(card, "market_id", "")
        description = (
            (watch_entry.description if watch_entry else None)
            or getattr(card, "resolution_interpretation", None)
            or getattr(card, "why_mispriced", None)
        )
        resolution_source = (
            (watch_entry.resolution_source if watch_entry else None)
            or getattr(card, "resolution_source_language", None)
        )
        return ResolutionParseInput(
            market_id=getattr(card, "market_id", ""),
            title=title,
            description=description,
            resolution_source=resolution_source,
            resolution_deadline=watch_entry.end_date if watch_entry else None,
            end_date_hours=(
                max(
                    0.0,
                    (watch_entry.end_date - datetime.now(tz=UTC)).total_seconds() / 3600.0,
                )
                if watch_entry and watch_entry.end_date is not None
                else None
            ),
            spread=(watch_entry.last_spread if watch_entry else None) or getattr(card, "expected_friction_spread", None),
            depth_usd=(watch_entry.last_depth_top3 if watch_entry else None) or self._infer_visible_depth(card),
            min_position_size_usd=self._config.tradeability.min_depth_for_min_position_usd,
        )

    def _build_sizing_request(self, card: Any) -> Any:
        """Build a valid Risk Governor sizing request from a thesis card."""
        from risk.types import SizingRequest

        watch_entry = self._get_watch_entry(market_id=getattr(card, "market_id", ""))
        quality_tier = getattr(card, "category_quality_tier", "standard") or "standard"
        try:
            category_quality_tier = CategoryQualityTier(quality_tier)
        except ValueError:
            category_quality_tier = CategoryQualityTier.STANDARD

        rubric = getattr(card, "rubric_score", None)
        probability_estimate = (
            getattr(card, "probability_estimate", None)
            or getattr(card, "calibrated_probability", None)
            or getattr(card, "market_implied_probability", None)
            or 0.5
        )

        return SizingRequest(
            market_id=getattr(card, "market_id", ""),
            token_id=watch_entry.token_id if watch_entry else "",
            category=getattr(card, "category", "unknown"),
            category_quality_tier=category_quality_tier,
            gross_edge=getattr(card, "gross_edge", 0.0) or 0.0,
            net_edge_after_cost=getattr(card, "net_edge_after_cost", None),
            probability_estimate=probability_estimate,
            confidence_estimate=getattr(card, "confidence_estimate", 0.5) or 0.5,
            calibration_confidence=getattr(card, "calibration_confidence", 0.5) or 0.5,
            evidence_quality_score=getattr(card, "evidence_quality_score", 0.5) or 0.5,
            evidence_diversity_score=getattr(card, "evidence_diversity_score", 0.5) or 0.5,
            ambiguity_score=getattr(card, "ambiguity_score", 0.0) or 0.0,
            visible_depth_usd=(watch_entry.last_depth_top3 if watch_entry else None) or self._infer_visible_depth(card),
            spread=(watch_entry.last_spread if watch_entry else None) or getattr(card, "expected_friction_spread", None),
            correlation_burden_score=(
                getattr(rubric, "cluster_correlation_burden", 0.0) if rubric is not None else 0.0
            ),
            category_resolved_trades=0,
        )

    def _record_shadow_forecast(self, card: Any) -> None:
        """Record a shadow forecast to the calibration store."""
        try:
            from calibration.types import ShadowForecastInput

            forecast = ShadowForecastInput(
                market_id=getattr(card, "market_id", ""),
                workflow_run_id=getattr(card, "workflow_run_id", None),
                category=getattr(card, "category", "unknown"),
                system_probability=getattr(card, "calibrated_probability", 0.5),
                market_implied_probability=getattr(card, "market_implied_probability", 0.5),
                thesis_context={
                    "proposed_side": getattr(card, "proposed_side", None),
                    "core_thesis": getattr(card, "core_thesis", None),
                    "net_edge_after_cost": getattr(card, "net_edge_after_cost", None),
                },
                forecast_at=datetime.now(tz=UTC),
            )
            self._calibration_store.record_forecast(forecast)

            _log.info(
                "shadow_forecast_recorded",
                market_id=forecast.market_id,
                system_prob=forecast.system_probability,
                market_prob=forecast.market_implied_probability,
            )
        except Exception as exc:
            _log.error("shadow_forecast_error", error=str(exc))

    def _paper_unrealized_pnl(
        self,
        side: str,
        size: float,
        entry_price: float,
        current_price: float,
    ) -> float:
        """Compute paper PnL using the repo's position-size convention."""
        if side == "no":
            return round(size * (entry_price - current_price), 2)
        return round(size * (current_price - entry_price), 2)

    async def _refresh_runtime_portfolio_state(self) -> None:
        """Keep the in-memory portfolio aligned with dashboard state and DB."""
        self._portfolio.operator_mode = self._current_mode()

        base_equity = (
            float(self._dashboard_state.get("paper_balance_usd", self._config.paper_balance_usd))
            if self._dashboard_state is not None
            else float(self._config.paper_balance_usd)
        )
        start_of_day = (
            float(self._dashboard_state.get("start_of_day_equity_usd", base_equity))
            if self._dashboard_state is not None
            else base_equity
        )

        self._portfolio.account_balance_usd = base_equity
        self._portfolio.start_of_day_equity_usd = start_of_day

        if self._session_factory is None:
            self._portfolio.current_equity_usd = base_equity
            return

        from data.models import Market, Position

        async with self._session_factory() as session:
            open_result = await session.execute(
                select(Position.size, Position.unrealized_pnl, Market.category)
                .join(Market, Position.market_id == Market.id)
                .where(Position.status == "open")
            )
            rows = open_result.all()

            realized_result = await session.execute(
                select(func.coalesce(func.sum(Position.realized_pnl), 0.0))
            )
            total_realized = float(realized_result.scalar_one() or 0.0)

        total_open_exposure = 0.0
        total_unrealized = 0.0
        category_exposure: dict[str, float] = {}
        for size, unrealized, category in rows:
            size_value = float(size or 0.0)
            total_open_exposure += size_value
            total_unrealized += float(unrealized or 0.0)
            cat = category or "unknown"
            category_exposure[cat] = category_exposure.get(cat, 0.0) + size_value

        self._portfolio.total_open_exposure_usd = round(total_open_exposure, 2)
        self._portfolio.open_position_count = len(rows)
        self._portfolio.category_exposure_usd = category_exposure
        self._portfolio.current_equity_usd = round(
            base_equity + total_realized + total_unrealized,
            2,
        )
        if self._risk_governor is not None:
            self._risk_governor.update_equity(self._portfolio.current_equity_usd)

    async def _mark_to_market_paper_positions(self) -> None:
        """Update open paper positions with the latest watched-market prices."""
        if self._session_factory is None or self._current_mode() != OperatorMode.PAPER:
            return
        if self._scanner is None:
            return

        held_entries = [
            entry for entry in self._scanner.get_watch_list()
            if entry.is_held_position and entry.position_id and entry.last_price is not None
        ]
        if not held_entries:
            return

        from data.models import Market, Position

        updated = False
        async with self._session_factory() as session:
            for entry in held_entries:
                try:
                    position = await session.get(Position, uuid.UUID(entry.position_id))
                except (TypeError, ValueError):
                    continue
                if position is None or position.status != "open":
                    continue

                current_price = float(entry.last_price)
                position.current_price = current_price
                position.unrealized_pnl = self._paper_unrealized_pnl(
                    position.side,
                    float(position.remaining_size or position.size),
                    float(position.entry_price),
                    current_price,
                )
                updated = True

                market_stmt = select(Market).where(Market.market_id == entry.market_id)
                market = (await session.execute(market_stmt)).scalar_one_or_none()
                if market is not None:
                    market.last_price = current_price
                    market.last_spread = entry.last_spread
                    market.last_snapshot_at = datetime.now(tz=UTC)

            if updated:
                await session.commit()

    async def _ensure_market_row(
        self,
        session: Any,
        *,
        external_market_id: str,
        watch_entry: MarketWatchEntry | None = None,
        card: Any | None = None,
    ) -> Any:
        """Create or refresh a Market ORM row from scanner/thesis metadata."""
        from data.models import Market

        stmt = select(Market).where(Market.market_id == external_market_id)
        market = (await session.execute(stmt)).scalar_one_or_none()
        metadata = self._resolve_market_metadata(
            external_market_id=external_market_id,
            watch_entry=watch_entry,
            card=card,
        )
        category = metadata["category"]
        title = metadata["title"]
        description = metadata["description"]

        if market is None:
            market = Market(
                market_id=external_market_id,
                title=title,
                description=description,
                category=category,
                category_quality_tier=metadata["category_quality_tier"],
                resolution_source=metadata["resolution_source"],
                resolution_deadline=metadata["end_date"],
                market_status="active",
                is_active=True,
                last_price=metadata["price"],
                last_spread=metadata["spread"],
                tags=metadata["tags"] or None,
            )
            session.add(market)
            await session.flush()
            return market

        if title and market.title != title:
            market.title = title
        if description and not market.description:
            market.description = description
        if category and not market.category:
            market.category = category
        if metadata["category_quality_tier"]:
            market.category_quality_tier = metadata["category_quality_tier"]
        if metadata["resolution_source"] and not market.resolution_source:
            market.resolution_source = metadata["resolution_source"]
        if metadata["end_date"] and market.resolution_deadline is None:
            market.resolution_deadline = metadata["end_date"]
        if metadata["tags"] and not market.tags:
            market.tags = metadata["tags"]
        if metadata["price"] is not None:
            market.last_price = metadata["price"]
        if metadata["spread"] is not None:
            market.last_spread = metadata["spread"]
            market.last_snapshot_at = datetime.now(tz=UTC)
        return market

    async def _persist_eligibility_decision(
        self,
        *,
        market_obj: Any,
        result: Any,
        session: Any,
    ) -> None:
        """Persist an eligibility decision to the eligibility_decisions DB table."""
        from data.models.workflow import EligibilityDecision

        decision = EligibilityDecision(
            market_id=market_obj.id,
            outcome=result.outcome,
            reason_code=result.reason_code,
            reason_detail=getattr(result, "reason_detail", None),
            rule_version=getattr(result, "rule_version", None),
            decided_at=datetime.now(tz=UTC),
        )
        session.add(decision)

    async def _persist_trigger_events(self, triggers: list[Any]) -> None:
        """Persist scanner trigger history to the DB for dashboard queries."""
        if not triggers or self._session_factory is None:
            return

        from data.models.workflow import TriggerEvent

        needs_refresh = any(
            (
                (entry := self._get_watch_entry(token_id=trigger.token_id, market_id=trigger.market_id)) is None
                or not entry.title
                or not entry.category
            )
            for trigger in triggers
        )
        if needs_refresh:
            await self._load_market_catalog(force=True)

        async with self._session_factory() as session:
            for trigger in triggers:
                watch_entry = self._get_watch_entry(token_id=trigger.token_id, market_id=trigger.market_id)
                market = await self._ensure_market_row(
                    session,
                    external_market_id=trigger.market_id or trigger.token_id,
                    watch_entry=watch_entry,
                )
                session.add(
                    TriggerEvent(
                        market_id=market.id,
                        trigger_class=trigger.trigger_class.value if hasattr(trigger.trigger_class, "value") else str(trigger.trigger_class),
                        trigger_level=trigger.trigger_level.value if hasattr(trigger.trigger_level, "value") else str(trigger.trigger_level),
                        price_at_trigger=trigger.price,
                        spread_at_trigger=trigger.spread,
                        depth_snapshot=trigger.depth_snapshot,
                        data_source=getattr(trigger, "data_source", "live"),
                        reason=trigger.reason or "",
                        escalation_status=getattr(trigger, "escalation_status", None),
                        triggered_at=getattr(trigger, "detected_at", datetime.now(tz=UTC)),
                    )
                )
            await session.commit()

    async def _cleanup_stale_running_workflows(self, session_factory: Any) -> None:
        """Mark any 'running' workflow runs as 'failed' on startup.

        Runs left in 'running' state are from a previous process that exited
        without completing. They are safe to close — no lock is held.
        """
        from data.models.workflow import WorkflowRun
        from sqlalchemy import update

        try:
            async with session_factory() as session:
                now = datetime.now(tz=UTC)
                result = await session.execute(
                    update(WorkflowRun)
                    .where(WorkflowRun.status == "running")
                    .values(
                        status="failed",
                        completed_at=now,
                        outcome="error",
                        outcome_reason="Process exited while workflow was running",
                    )
                )
                await session.commit()
                count = result.rowcount
                if count:
                    _log.info("stale_workflows_cleaned", count=count)
        except Exception as exc:
            _log.warning("stale_workflow_cleanup_failed", error=str(exc))

    async def _persist_workflow_run(
        self,
        *,
        workflow_run_id: str,
        run_type: str,
        status: str,
        market_id: str | None = None,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
        estimated_cost_usd: float | None = None,
        actual_cost_usd: float | None = None,
        outcome: str | None = None,
        outcome_reason: str | None = None,
        operator_mode: str | None = None,
        models_used: list[str] | None = None,
        max_tier_used: str | None = None,
    ) -> None:
        """Persist workflow run lifecycle events to the DB."""
        if self._session_factory is None:
            return

        from data.models.workflow import WorkflowRun

        async with self._session_factory() as session:
            stmt = select(WorkflowRun).where(WorkflowRun.workflow_run_id == workflow_run_id)
            run = (await session.execute(stmt)).scalar_one_or_none()
            watch_entry = self._get_watch_entry(market_id=market_id) if market_id else None
            market = None
            if market_id:
                market = await self._ensure_market_row(
                    session,
                    external_market_id=market_id,
                    watch_entry=watch_entry,
                )

            if run is None:
                run = WorkflowRun(
                    workflow_run_id=workflow_run_id,
                    run_type=run_type,
                    market_id=market.id if market is not None else None,
                    status=status,
                    started_at=started_at,
                    completed_at=completed_at,
                    estimated_cost_usd=estimated_cost_usd,
                    actual_cost_usd=actual_cost_usd,
                    outcome=outcome,
                    outcome_reason=outcome_reason,
                    operator_mode=operator_mode,
                    models_used=models_used,
                    max_tier_used=max_tier_used,
                )
                session.add(run)
            else:
                run.run_type = run_type
                run.status = status
                if market is not None:
                    run.market_id = market.id
                if started_at is not None and run.started_at is None:
                    run.started_at = started_at
                if completed_at is not None:
                    run.completed_at = completed_at
                if estimated_cost_usd is not None:
                    run.estimated_cost_usd = estimated_cost_usd
                if actual_cost_usd is not None:
                    run.actual_cost_usd = actual_cost_usd
                if outcome is not None:
                    run.outcome = outcome
                if outcome_reason is not None:
                    run.outcome_reason = outcome_reason
                if operator_mode is not None:
                    run.operator_mode = operator_mode
                if models_used is not None:
                    run.models_used = models_used
                if max_tier_used is not None:
                    run.max_tier_used = max_tier_used

            await session.commit()

    async def _persist_investigation_truth(
        self,
        *,
        workflow_run_id: str,
        result: Any,
    ) -> None:
        """Persist workflow-level cost truth and candidate diagnostics."""
        if self._session_factory is None:
            return

        from data.models.cost import CostGovernorDecision, PreRunCostEstimate
        from data.models.logging import StructuredLogEntry
        from data.models.workflow import WorkflowRun

        async with self._session_factory() as session:
            run_stmt = select(WorkflowRun).where(WorkflowRun.workflow_run_id == workflow_run_id)
            workflow_run = (await session.execute(run_stmt)).scalar_one_or_none()
            if workflow_run is None:
                return

            cost_estimate = getattr(result, "cost_estimate", None)
            if cost_estimate is not None:
                workflow_run.estimated_cost_usd = cost_estimate.expected_cost_max_usd
                session.add(PreRunCostEstimate(
                    workflow_run_id=workflow_run.id,
                    run_type=cost_estimate.run_type.value,
                    expected_cost_min_usd=cost_estimate.expected_cost_min_usd,
                    expected_cost_max_usd=cost_estimate.expected_cost_max_usd,
                    daily_budget_remaining_usd=cost_estimate.budget_state.daily_remaining_usd,
                    lifetime_budget_remaining_usd=cost_estimate.budget_state.lifetime_remaining_usd,
                    daily_budget_pct_remaining=cost_estimate.budget_state.daily_pct_remaining,
                    agent_budgets=cost_estimate.agent_budgets,
                    estimated_at=cost_estimate.estimated_at,
                ))

            cost_approval = getattr(result, "cost_approval", None)
            if cost_approval is not None:
                session.add(CostGovernorDecision(
                    workflow_run_id=workflow_run.id,
                    decision=cost_approval.decision.value,
                    reason=cost_approval.reason,
                    approved_max_tier=(
                        cost_approval.approved_max_tier.value
                        if cost_approval.approved_max_tier is not None
                        else None
                    ),
                    approved_max_cost_usd=cost_approval.approved_max_cost_usd,
                    cost_selectivity_ratio=cost_approval.cost_selectivity_ratio,
                    opus_escalation_threshold=cost_approval.opus_escalation_threshold,
                    decided_at=cost_approval.decided_at,
                ))

            estimate_accuracy = getattr(result, "estimate_accuracy", None)
            if estimate_accuracy is not None:
                session.add(StructuredLogEntry(
                    workflow_run_id=workflow_run_id,
                    event_type="workflow_cost_accuracy",
                    severity="info",
                    component="cost_governor",
                    payload=estimate_accuracy.model_dump(mode="json"),
                    message=(
                        f"Estimate accuracy ratio {estimate_accuracy.accuracy_ratio:.4f}; "
                        f"within_bounds={estimate_accuracy.within_bounds}"
                    ),
                    logged_at=datetime.now(tz=UTC),
                ))

            if getattr(result, "models_used", None):
                workflow_run.models_used = list(result.models_used)
            if getattr(result, "max_tier_used", None):
                workflow_run.max_tier_used = result.max_tier_used

            for candidate_outcome in getattr(result, "candidate_outcomes", []) or []:
                session.add(StructuredLogEntry(
                    workflow_run_id=workflow_run_id,
                    market_id=candidate_outcome.market_id,
                    event_type="candidate_accepted" if candidate_outcome.accepted else "candidate_rejected",
                    severity="info" if candidate_outcome.accepted else "warning",
                    component="investigation",
                    payload={
                        "market_id": candidate_outcome.market_id,
                        "market_title": candidate_outcome.market_title,
                        "category": candidate_outcome.category,
                        "accepted": candidate_outcome.accepted,
                        "stage_reached": candidate_outcome.stage_reached,
                        "reason": candidate_outcome.reason,
                        "reason_code": candidate_outcome.reason_code,
                        "reason_detail": candidate_outcome.reason_detail,
                        "quantitative_context": candidate_outcome.quantitative_context,
                        "cost_spent_usd": candidate_outcome.cost_spent_usd,
                    },
                    message=candidate_outcome.reason,
                    logged_at=datetime.now(tz=UTC),
                ))

            await session.commit()

    async def _persist_pipeline_result(
        self,
        *,
        workflow_run_id: str,
        card: Any,
        pipeline_result: PipelineResult,
    ) -> None:
        """Persist the final pipeline outcome for an investigated candidate."""
        if self._session_factory is None:
            return

        from data.models.logging import StructuredLogEntry

        async with self._session_factory() as session:
            session.add(StructuredLogEntry(
                workflow_run_id=workflow_run_id,
                market_id=pipeline_result.market_id,
                event_type="candidate_accepted" if pipeline_result.accepted else "candidate_rejected",
                severity="info" if pipeline_result.accepted else "warning",
                component="pipeline",
                payload={
                    "market_id": pipeline_result.market_id,
                    "market_title": getattr(card, "core_thesis", None) or getattr(card, "market_id", None),
                    "category": getattr(card, "category", None),
                    "accepted": pipeline_result.accepted,
                    "stage_reached": pipeline_result.stage_reached.value,
                    "reason": pipeline_result.reason,
                    "reason_code": pipeline_result.reason_code,
                    "reason_detail": pipeline_result.reason_detail,
                    "quantitative_context": pipeline_result.quantitative_context,
                    "cost_spent_usd": pipeline_result.total_cost_usd,
                },
                message=pipeline_result.reason,
                logged_at=datetime.now(tz=UTC),
            ))
            await session.commit()

    async def _execute_paper_trade(
        self,
        card: Any,
        execution_request: ExecutionRequest,
        risk_assessment: Any,
        *,
        started: datetime,
    ) -> PipelineResult:
        """Persist a simulated paper trade so the dashboard can track it."""
        if self._session_factory is None:
            return PipelineResult(
                market_id=getattr(card, "market_id", "unknown"),
                stage_reached=PipelineStage.EXECUTION,
                reason="Paper execution unavailable: no session factory",
                reason_code="execution_backend_unavailable",
                duration_seconds=(datetime.now(tz=UTC) - started).total_seconds(),
            )

        watch_entry = self._get_watch_entry(market_id=getattr(card, "market_id", ""))
        token_id = execution_request.token_id
        price = execution_request.price
        current_depth = execution_request.current_depth_usd
        size_usd = execution_request.size_usd

        if size_usd <= 0:
            return PipelineResult(
                market_id=getattr(card, "market_id", "unknown"),
                stage_reached=PipelineStage.EXECUTION,
                reason="Paper execution rejected: recommended size is zero",
                reason_code="risk_reject",
                duration_seconds=(datetime.now(tz=UTC) - started).total_seconds(),
            )

        execution_result = await self._execution_engine.execute(
            execution_request,
            portfolio_drawdown_pct=self._risk_governor.drawdown_state.current_drawdown_pct,
            portfolio_open_positions=self._portfolio.open_position_count,
            portfolio_exposure_usd=self._portfolio.total_open_exposure_usd,
            account_balance_usd=self._portfolio.account_balance_usd,
        )

        if execution_result.outcome != ExecutionOutcome.EXECUTED:
            return PipelineResult(
                market_id=getattr(card, "market_id", "unknown"),
                stage_reached=PipelineStage.EXECUTION,
                reason=execution_result.rejection_reason or "Paper execution rejected",
                reason_code="execution_revalidation_failed",
                reason_detail=execution_result.rejection_reason,
                quantitative_context={
                    "approval_chain": execution_result.approval_chain,
                },
                duration_seconds=(datetime.now(tz=UTC) - started).total_seconds(),
            )

        self._record_shadow_forecast(card)

        from data.models import Order, Position, Trade
        from data.models.thesis import ThesisCard
        from data.models.workflow import WorkflowRun

        async with self._session_factory() as session:
            market = await self._ensure_market_row(
                session,
                external_market_id=getattr(card, "market_id", ""),
                watch_entry=watch_entry,
                card=card,
            )

            workflow_stmt = select(WorkflowRun).where(
                WorkflowRun.workflow_run_id == getattr(card, "workflow_run_id", "")
            )
            workflow_run = (await session.execute(workflow_stmt)).scalar_one_or_none()
            if workflow_run is None:
                workflow_run_id = getattr(card, "workflow_run_id", "")
                workflow_run_type = "scheduled_sweep"
                if workflow_run_id.startswith("trig-"):
                    workflow_run_type = "trigger_based"
                elif workflow_run_id.startswith("op-"):
                    workflow_run_type = "operator_forced"
                workflow_run = WorkflowRun(
                    workflow_run_id=workflow_run_id,
                    run_type=workflow_run_type,
                    market_id=market.id,
                    status="completed",
                    started_at=started,
                    completed_at=datetime.now(tz=UTC),
                    outcome="candidate_accepted",
                    operator_mode=self._current_mode().value,
                    actual_cost_usd=getattr(card, "expected_inference_cost_usd", 0.0),
                )
                session.add(workflow_run)
                await session.flush()

            thesis_card = ThesisCard(
                market_id=market.id,
                workflow_run_id=workflow_run.id,
                category=getattr(card, "category", "unknown"),
                category_quality_tier=getattr(card, "category_quality_tier", "standard"),
                proposed_side=getattr(card, "proposed_side", "yes"),
                resolution_interpretation=getattr(card, "resolution_interpretation", "") or "",
                resolution_source_language=getattr(card, "resolution_source_language", None),
                core_thesis=getattr(card, "core_thesis", "") or "",
                why_mispriced=getattr(card, "why_mispriced", "") or "",
                supporting_evidence=getattr(card, "supporting_evidence", []) or [],
                opposing_evidence=getattr(card, "opposing_evidence", []) or [],
                expected_catalyst=getattr(card, "expected_catalyst", None),
                expected_time_horizon=getattr(card, "expected_time_horizon", None),
                expected_time_horizon_hours=getattr(card, "expected_time_horizon_hours", None),
                invalidation_conditions=getattr(card, "invalidation_conditions", []) or [],
                resolution_risk_summary=getattr(card, "resolution_risk_summary", None),
                market_structure_summary=getattr(card, "market_structure_summary", None),
                evidence_quality_score=getattr(card, "evidence_quality_score", None),
                evidence_diversity_score=getattr(card, "evidence_diversity_score", None),
                ambiguity_score=getattr(card, "ambiguity_score", None),
                calibration_source_status=getattr(card, "calibration_source_status", None),
                raw_model_probability=getattr(card, "raw_model_probability", None),
                calibrated_probability=getattr(card, "calibrated_probability", None),
                calibration_segment_label=getattr(card, "calibration_segment_label", None),
                probability_estimate=getattr(card, "probability_estimate", None),
                confidence_estimate=getattr(card, "confidence_estimate", None),
                calibration_confidence=getattr(card, "calibration_confidence", None),
                confidence_note=getattr(card, "confidence_note", None),
                gross_edge=getattr(card, "gross_edge", None),
                friction_adjusted_edge=getattr(card, "friction_adjusted_edge", None),
                impact_adjusted_edge=getattr(card, "impact_adjusted_edge", None),
                net_edge_after_cost=getattr(card, "net_edge_after_cost", None),
                expected_friction_spread=getattr(card, "expected_friction_spread", None),
                expected_friction_slippage=getattr(card, "expected_friction_slippage", None),
                entry_impact_estimate_bps=getattr(card, "entry_impact_estimate_bps", None),
                expected_inference_cost_usd=getattr(card, "expected_inference_cost_usd", None),
                recommended_size_band=getattr(card, "recommended_size_band", None),
                urgency_of_entry=getattr(card, "urgency_of_entry", None),
                liquidity_adjusted_max_size=getattr(card, "liquidity_adjusted_max_size_usd", None),
                trigger_source=getattr(card, "trigger_source", None),
                market_implied_probability=getattr(card, "market_implied_probability", None),
                base_rate=getattr(card, "base_rate", None),
                base_rate_deviation=getattr(card, "base_rate_deviation", None),
            )
            session.add(thesis_card)
            await session.flush()

            position = Position(
                market_id=market.id,
                thesis_card_id=thesis_card.id,
                side=getattr(card, "proposed_side", "yes"),
                entry_price=float(execution_result.submitted_price or price),
                current_price=float(execution_result.submitted_price or price),
                size=float(execution_result.submitted_size or size_usd),
                remaining_size=float(execution_result.submitted_size or size_usd),
                status="open",
                entered_at=execution_result.executed_at,
                entry_mode=execution_result.entry_mode.value if execution_result.entry_mode else None,
                review_tier="new",
                unrealized_pnl=0.0,
                realized_pnl=0.0,
                total_inference_cost_usd=float(getattr(card, "expected_inference_cost_usd", 0.0) or 0.0),
                probability_estimate=getattr(card, "probability_estimate", None),
                confidence_estimate=getattr(card, "confidence_estimate", None),
                calibration_confidence=getattr(card, "calibration_confidence", None),
                risk_approval=risk_assessment.approval.value,
            )
            session.add(position)
            await session.flush()

            order = Order(
                position_id=position.id,
                workflow_run_id=workflow_run.id,
                order_type=execution_request.order_type,
                side=execution_request.side,
                price=float(execution_result.submitted_price or price),
                size=float(execution_result.submitted_size or size_usd),
                status="filled",
                submitted_at=execution_result.executed_at,
                filled_at=execution_result.executed_at,
                fill_price=float(execution_result.submitted_price or price),
                filled_size=float(execution_result.submitted_size or size_usd),
                revalidation_passed=True,
                revalidation_details=(
                    execution_result.revalidation.model_dump(mode="json")
                    if execution_result.revalidation is not None
                    else None
                ),
                estimated_impact_bps=execution_result.entry_impact_bps,
                approval_chain=execution_result.approval_chain,
            )
            session.add(order)
            await session.flush()

            trade = Trade(
                order_id=order.id,
                position_id=position.id,
                price=float(execution_result.submitted_price or price),
                size=float(execution_result.submitted_size or size_usd),
                side=execution_request.side,
                executed_at=execution_result.executed_at,
                fee_usd=0.0,
            )
            session.add(trade)

            workflow_run.position_id = position.id
            workflow_run.outcome = "candidate_accepted"
            workflow_run.completed_at = datetime.now(tz=UTC)
            workflow_run.actual_cost_usd = float(getattr(card, "expected_inference_cost_usd", 0.0) or 0.0)
            await session.commit()

        if self._scanner is not None:
            if watch_entry is not None:
                self._scanner.update_watch_entry(
                    watch_entry.token_id,
                    is_held_position=True,
                    position_id=str(position.id),
                    last_price=float(execution_result.submitted_price or price),
                )
            elif token_id:
                self._scanner.add_to_watch_list(
                    MarketWatchEntry(
                        market_id=getattr(card, "market_id", ""),
                        token_id=token_id,
                        title=getattr(card, "core_thesis", "") or getattr(card, "market_id", ""),
                        category=getattr(card, "category", "unknown"),
                        category_quality_tier=getattr(card, "category_quality_tier", "standard"),
                        is_held_position=True,
                        position_id=str(position.id),
                        last_price=float(execution_result.submitted_price or price),
                    )
                )

        await self._refresh_runtime_portfolio_state()
        await self._emit_trade_entry_event(card, paper_mode=True)

        return PipelineResult(
            market_id=getattr(card, "market_id", "unknown"),
            stage_reached=PipelineStage.EXECUTION,
            accepted=True,
            thesis_card_id=str(thesis_card.id),
            execution_id=str(order.id),
            reason="Paper mode: simulated trade executed",
            reason_code="executed",
            total_cost_usd=float(getattr(card, "expected_inference_cost_usd", 0.0) or 0.0),
            quantitative_context={
                "entry_mode": (
                    execution_result.entry_mode.value
                    if execution_result.entry_mode is not None
                    else None
                ),
                "submitted_size_usd": float(execution_result.submitted_size or size_usd),
            },
            duration_seconds=(datetime.now(tz=UTC) - started).total_seconds(),
        )

    def _sync_dashboard_state(self) -> None:
        """Push current system state to the dashboard API module.

        Note: operator_mode is NOT synced here — it is owned by the
        dashboard API layer and persisted to disk independently.
        Overwriting it would undo operator-initiated mode changes.
        """
        try:
            from dashboard_api.app import _system_state
        except Exception as exc:
            _log.debug("dashboard_sync_error", error=str(exc))
            return

        _system_state["system_status"] = self._state.phase.value
        _system_state["agents_running"] = self._state.phase == SystemPhase.RUNNING

        if self._scanner:
            try:
                health = self._scanner.health_monitor.get_health_status()
                _system_state["scanner_api_status"] = (
                    "healthy" if health.api_available else "degraded"
                )
                _system_state["scanner_degraded_level"] = getattr(
                    health.degraded_mode_level,
                    "value",
                    health.degraded_mode_level,
                )
                _system_state["scanner_uptime_pct"] = round(
                    health.uptime_percentage, 1
                )
                _system_state["scanner_consecutive_failures"] = int(
                    getattr(
                        health,
                        "consecutive_failures",
                        getattr(health, "consecutive_global_failures", 0),
                    )
                )
                _system_state["scanner_last_poll"] = (
                    health.last_successful_poll.isoformat()
                    if health.last_successful_poll is not None
                    else None
                )

                if self._market_data is not None:
                    cache_stats = self._market_data.get_cache_stats_snapshot()
                    _system_state["scanner_cache_entries"] = cache_stats.total_entries
                    _system_state["scanner_cache_hit_rate"] = round(
                        cache_stats.hit_rate, 4
                    )
            except Exception as exc:
                _log.debug("dashboard_sync_scanner_error", error=str(exc))

        if self._absence_manager:
            try:
                absence = self._absence_manager.compute_state()
                _system_state["is_absent"] = absence.absence_level.value >= 1
                _system_state["absence_level"] = absence.absence_level.value
                _system_state["hours_since_activity"] = (
                    absence.hours_since_last_interaction
                )
            except Exception as exc:
                _log.debug("dashboard_sync_absence_error", error=str(exc))

        if self._cost_governor:
            try:
                budget = self._cost_governor.budget_tracker.state
                _system_state["daily_spend_usd"] = round(budget.daily_spent_usd, 4)
                _system_state["lifetime_spend_usd"] = round(
                    budget.lifetime_spent_usd, 4
                )
                _system_state["opus_spend_today_usd"] = round(
                    getattr(budget, "daily_opus_spent_usd", 0.0), 4
                )

                selectivity = self._cost_governor.get_selectivity_snapshot()
                _system_state["selectivity_ratio"] = round(
                    selectivity.cost_to_edge_ratio or 0.0, 4
                )
            except Exception as exc:
                _log.debug("dashboard_sync_cost_error", error=str(exc))

        if self._risk_governor:
            try:
                drawdown = self._risk_governor.drawdown_state
                _system_state["drawdown_level"] = drawdown.level.value
                _system_state["drawdown_pct"] = round(
                    drawdown.current_drawdown_pct, 4
                )
            except Exception as exc:
                _log.debug("dashboard_sync_risk_error", error=str(exc))

        try:
            _system_state["paper_equity_usd"] = round(
                float(self._portfolio.current_equity_usd),
                2,
            )
        except Exception as exc:
            _log.debug("dashboard_sync_equity_error", error=str(exc))

        # Equity snapshot for the chart (taken every sync cycle, ~5 min)
        try:
            from dashboard_api.app import _add_equity_snapshot

            equity = _system_state.get(
                "paper_equity_usd", self._portfolio.current_equity_usd
            )
            start_equity = _system_state.get(
                "start_of_day_equity_usd", self._portfolio.start_of_day_equity_usd
            )
            _add_equity_snapshot(
                equity_usd=round(float(equity), 2),
                pnl_usd=round(float(equity) - float(start_equity), 2),
            )
        except Exception as exc:
            _log.debug("dashboard_sync_equity_snapshot_error", error=str(exc))

    # ================================================================
    # Notification helpers
    # ================================================================

    async def _emit_event(
        self,
        event_type: NotificationType,
        severity: NotificationSeverity,
        *,
        market_id: str | None = None,
        payload: dict | None = None,
    ) -> None:
        """Emit a notification event through the event bus."""
        if not self._event_bus:
            return

        envelope = NotificationEnvelope(
            event_type=event_type,
            severity=severity,
            market_id=market_id,
            payload=payload or {},
            timestamp=datetime.now(tz=UTC),
        )
        await self._event_bus.publish(envelope)

    async def _emit_system_health_event(self, event: str, detail: str) -> None:
        """Emit a system health notification."""
        await self._emit_event(
            NotificationType.SYSTEM_HEALTH,
            NotificationSeverity.INFO,
            payload={
                "health_event": event,
                "service": "orchestrator",
                "summary": detail,
                "detail": detail,
            },
        )

    async def _emit_no_trade_event(self, no_trade: Any) -> None:
        """Emit a no-trade notification."""
        await self._emit_event(
            NotificationType.NO_TRADE,
            NotificationSeverity.INFO,
            market_id=getattr(no_trade, "market_id", None),
            payload={
                "reason": getattr(no_trade, "reason", "healthy_no_trade"),
                "stage": getattr(no_trade, "stage", None),
                "reason_code": getattr(no_trade, "reason_code", None),
                "reason_detail": getattr(no_trade, "reason_detail", None),
                "workflow_run_duration_seconds": 0.0,
                "candidates_reviewed": 1,
                "top_rejected_market": (
                    getattr(no_trade, "market_title", None)
                    or getattr(no_trade, "market_id", None)
                ),
                "rejection_reasons": [getattr(no_trade, "reason_code", "")],
                "quantitative_context": getattr(no_trade, "quantitative_context", {}) or {},
                "is_healthy": True,
            },
        )

    async def _emit_trade_entry_event(
        self, card: Any, *, paper_mode: bool = False
    ) -> None:
        """Emit a trade entry notification."""
        await self._emit_event(
            NotificationType.TRADE_ENTRY,
            NotificationSeverity.INFO,
            market_id=getattr(card, "market_id", None),
            payload={
                "paper_mode": paper_mode,
                "proposed_side": getattr(card, "proposed_side", None),
                "category": getattr(card, "category", None),
                "gross_edge": getattr(card, "gross_edge", None),
            },
        )

    # ================================================================
    # Public accessors for external use
    # ================================================================

    @property
    def state(self) -> SystemState:
        """Current system state snapshot."""
        if self._state.started_at:
            self._state.uptime_seconds = (
                datetime.now(tz=UTC) - self._state.started_at
            ).total_seconds()
        self._state.scheduled_tasks = self._scheduler.get_task_states()
        return self._state

    @property
    def scanner(self) -> TriggerScanner | None:
        return self._scanner

    @property
    def risk_governor(self) -> RiskGovernor | None:
        return self._risk_governor

    @property
    def cost_governor(self) -> CostGovernor | None:
        return self._cost_governor

    @property
    def absence_manager(self) -> AbsenceManager | None:
        return self._absence_manager

    @property
    def event_bus(self) -> NotificationEventBus | None:
        return self._event_bus

    def _log_activity(
        self,
        event_type: str,
        component: str,
        message: str,
        detail: str | None = None,
        severity: str = "info",
    ) -> None:
        """Push an activity log entry to the dashboard API shared state."""
        try:
            from dashboard_api.app import _add_activity
            _add_activity(event_type, component, message, detail, severity)
        except ImportError:
            pass  # Dashboard API not available

    def record_operator_interaction(self, interaction_type: str = "login") -> None:
        """Record an operator interaction (from dashboard, API, etc.)."""
        try:
            itype = InteractionType(interaction_type)
        except ValueError:
            itype = InteractionType.LOGIN

        self._absence_manager.record_interaction(
            OperatorInteraction(interaction_type=itype)
        )


class _ShadowExecutionBackend:
    """Log-only execution sink for shadow mode."""

    async def execute(
        self,
        orchestrator: WorkflowOrchestrator,
        card: Any,
        *,
        execution_request: ExecutionRequest,
        risk_assessment: Any,
        tradeability_result: Any,
        started: datetime,
    ) -> PipelineResult:
        market_id = getattr(card, "market_id", "unknown")
        _log.info(
            "shadow_mode_trade_decision",
            market_id=market_id,
            mode=orchestrator._current_mode().value,
            message="Trade would be entered in live mode",
        )

        if orchestrator._calibration_store:
            orchestrator._record_shadow_forecast(card)

        await orchestrator._emit_trade_entry_event(card, paper_mode=False)
        return PipelineResult(
            market_id=market_id,
            stage_reached=PipelineStage.EXECUTION,
            accepted=True,
            reason="Shadow mode: trade logged, not executed",
            reason_code="shadow_logged",
            quantitative_context={
                "tradeability_outcome": tradeability_result.outcome.value,
                "requested_size_usd": execution_request.size_usd,
            },
            duration_seconds=(datetime.now(tz=UTC) - started).total_seconds(),
        )


class _PaperExecutionBackend:
    """Simulated execution sink for paper mode."""

    async def execute(
        self,
        orchestrator: WorkflowOrchestrator,
        card: Any,
        *,
        execution_request: ExecutionRequest,
        risk_assessment: Any,
        tradeability_result: Any,
        started: datetime,
    ) -> PipelineResult:
        return await orchestrator._execute_paper_trade(
            card,
            execution_request,
            risk_assessment,
            started=started,
        )


class _LiveExecutionBackend:
    """Placeholder backend for future live execution wiring."""

    async def execute(
        self,
        orchestrator: WorkflowOrchestrator,
        card: Any,
        *,
        execution_request: ExecutionRequest,
        risk_assessment: Any,
        tradeability_result: Any,
        started: datetime,
    ) -> PipelineResult:
        market_id = getattr(card, "market_id", "unknown")
        _log.info(
            "live_execution_unavailable",
            market_id=market_id,
            message="Live execution not yet wired",
        )
        return PipelineResult(
            market_id=market_id,
            stage_reached=PipelineStage.EXECUTION,
            accepted=False,
            reason="Live execution unavailable until the exchange adapter is implemented",
            reason_code="execution_backend_unavailable",
            duration_seconds=(datetime.now(tz=UTC) - started).total_seconds(),
        )
