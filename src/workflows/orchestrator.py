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
from typing import Any

import structlog

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
    EligibilityOutcome,
    NotificationSeverity,
    NotificationType,
    OperatorMode,
    TriggerLevel,
)
from cost.governor import CostGovernor
from data.database import close_db, get_session_factory, init_db
from eligibility.engine import EligibilityEngine
from eligibility.types import MarketEligibilityInput
from investigation.orchestrator import InvestigationOrchestrator
from investigation.types import (
    CandidateContext,
    InvestigationMode,
    InvestigationRequest,
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
from viability.processor import ViabilityProcessor
from workflows.scheduler import WorkflowScheduler
from workflows.types import PipelineResult, PipelineStage, SystemPhase, SystemState

_log = get_logger(component="orchestrator")


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
        _log.info("database_initialized")
        self._log_activity("system", "Database", "Database initialized", severity="success")

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
            min_net_edge=self._config.risk.sizing_base_fraction,
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
            from dashboard_api.app import set_session_factory, set_app_config, _system_state
            set_session_factory(session_factory)
            set_app_config(self._config)
            # Keep a live reference so pipeline decisions always use the current mode,
            # not the stale startup value from config.
            self._dashboard_state = _system_state
            # Only set operator_mode from config if no persisted value exists.
            # The dashboard API layer persists mode changes to disk, and we
            # must not overwrite an operator-set mode on restart.
            if "operator_mode" not in _system_state or _system_state["operator_mode"] is None:
                _system_state["operator_mode"] = self._config.operator_mode
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
            f"System initialized in {self._config.operator_mode} mode with ${getattr(self._config, 'paper_balance_usd', 500.0):.2f}",
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
        self._risk_governor.reset_day(start_of_day_equity=self._portfolio.account_balance_usd)

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
            f"Polymarket Trader started in {self._config.operator_mode} mode",
        )

        self._log_activity(
            "system", "Orchestrator",
            f"System LIVE in {self._config.operator_mode.upper()} mode",
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
                _add_trigger_event(
                    trigger_class=t.trigger_class.value if hasattr(t.trigger_class, "value") else str(t.trigger_class),
                    trigger_level=t.trigger_level.value if hasattr(t.trigger_level, "value") else str(t.trigger_level),
                    market_id=t.market_id or t.token_id,
                    reason=t.reason or "",
                    price=t.price,
                    spread=t.spread,
                    data_source=getattr(t, "data_source", "live"),
                )
        except Exception:
            pass

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
            candidate = CandidateContext(
                market_id=trigger.market_id or trigger.token_id,
                token_id=trigger.token_id,
                title=trigger.reason or "",
                category=getattr(trigger, "category", "unknown"),
                trigger_class=trigger.trigger_class,
                trigger_level=trigger.trigger_level,
                price=trigger.price or 0.5,
                mid_price=trigger.price or 0.5,
                spread=trigger.spread or 0.0,
                visible_depth_usd=(trigger.depth_snapshot or {}).get("top3_usd", 0.0),
            )
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

            run_cost = getattr(result, "actual_cost_usd", 0.0) or 0.0

            # Update workflow run as completed
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
                if run_cost > 0:
                    _record_agent_invocation("investigator_orchestration", run_cost)
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

            # Process accepted thesis cards through remaining pipeline
            for card in result.thesis_cards:
                self._no_trade_monitor.record_run(had_no_trade=False)
                self._log_activity(
                    "trade", "Investigator",
                    f"Thesis card accepted: {getattr(card, 'title', '?')[:60]}",
                    severity="success",
                )
                pipeline_result = await self._process_thesis_card(card)

                if pipeline_result.accepted:
                    self._state.total_trades_entered += 1
                    self._log_activity(
                        "trade", "Execution",
                        f"Trade #{self._state.total_trades_entered} entered (shadow)",
                        detail=f"Market: {pipeline_result.market_id}",
                        severity="success",
                    )

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

    async def _process_thesis_card(self, card: Any) -> PipelineResult:
        """Process a thesis card through tradeability → risk → cost → execution.

        In paper/shadow mode, stops before actual execution.
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

            if parse_result.hard_rejected:
                return PipelineResult(
                    market_id=market_id,
                    stage_reached=PipelineStage.TRADEABILITY,
                    reason=f"Hard rejection: {parse_result.rejection_reason}",
                    duration_seconds=(datetime.now(tz=UTC) - started).total_seconds(),
                )
        except Exception as exc:
            _log.error("tradeability_parse_error", market_id=market_id, error=str(exc))

        # --- Stage 2: Risk Governor approval ---
        try:
            risk_assessment = self._risk_governor.assess(
                self._build_sizing_request(card),
                self._portfolio,
            )

            if not risk_assessment.is_approved:
                return PipelineResult(
                    market_id=market_id,
                    stage_reached=PipelineStage.RISK_APPROVAL,
                    reason=f"Risk Governor: {risk_assessment.reason}",
                    duration_seconds=(datetime.now(tz=UTC) - started).total_seconds(),
                )
        except Exception as exc:
            _log.error("risk_assessment_error", market_id=market_id, error=str(exc))
            return PipelineResult(
                market_id=market_id,
                stage_reached=PipelineStage.RISK_APPROVAL,
                reason=f"Risk assessment error: {str(exc)}",
                duration_seconds=(datetime.now(tz=UTC) - started).total_seconds(),
            )

        # --- Stage 3: Paper/Shadow mode → log but don't execute ---
        mode = self._current_mode()
        if mode in (OperatorMode.PAPER, OperatorMode.SHADOW):
            _log.info(
                "paper_mode_trade_decision",
                market_id=market_id,
                mode=mode.value,
                message="Trade would be entered in live mode",
            )

            # Record shadow forecast for calibration
            if self._calibration_store:
                self._record_shadow_forecast(card)

            # Emit trade entry notification (paper mode)
            await self._emit_trade_entry_event(card, paper_mode=True)

            return PipelineResult(
                market_id=market_id,
                stage_reached=PipelineStage.EXECUTION,
                accepted=True,
                reason=f"Paper mode: trade logged, not executed",
                duration_seconds=(datetime.now(tz=UTC) - started).total_seconds(),
            )

        # --- Stage 4: Live execution (future) ---
        _log.info(
            "live_execution_pending",
            market_id=market_id,
            message="Live execution not yet wired",
        )

        return PipelineResult(
            market_id=market_id,
            stage_reached=PipelineStage.EXECUTION,
            accepted=True,
            reason="Approved for execution",
            duration_seconds=(datetime.now(tz=UTC) - started).total_seconds(),
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
                                category=result.category_classification.category or "unknown",
                                last_spread=elig_input.spread,
                            )
                        )
                    # Only INVESTIGATE_NOW markets become active investigation candidates.
                    if result.outcome == EligibilityOutcome.INVESTIGATE_NOW.value:
                        eligible_candidates.append(
                            CandidateContext(
                                market_id=elig_input.market_id,
                                token_id=token_id,
                                title=elig_input.title,
                                category=result.category_classification.category or "unknown",
                                trigger_class="discovery",
                                trigger_level="C",
                                price=0.5,
                                mid_price=0.5,
                                spread=elig_input.spread,
                                visible_depth_usd=elig_input.liquidity_usd,
                            )
                        )

            _log.info(
                "sweep_eligibility_complete",
                markets_checked=min(len(markets_filtered), 50),
                eligible=len(eligible_candidates),
                watch_list_size=self._scanner.get_watch_list().__len__(),
            )

            if not eligible_candidates:
                self._state.total_no_trade_decisions += 1
                return

            # Run investigation on top candidates
            sweep_run_id = f"sweep-{uuid.uuid4().hex[:8]}"
            sweep_started = datetime.now(tz=UTC)
            request = InvestigationRequest(
                workflow_run_id=sweep_run_id,
                mode=InvestigationMode.SCHEDULED_SWEEP,
                candidates=eligible_candidates[:10],
                max_candidates=3,
            )

            try:
                from dashboard_api.app import _add_workflow_run
                _add_workflow_run(
                    workflow_run_id=sweep_run_id,
                    workflow_type="scheduled_sweep",
                    status="running",
                    candidates_reviewed=len(eligible_candidates[:10]),
                    started_at=sweep_started,
                )
            except Exception:
                pass

            self._state.total_investigations += 1
            result = await self._investigator.run(
                request,
                regime=self._build_regime_context(),
            )

            sweep_cost = getattr(result, "actual_cost_usd", 0.0) or 0.0
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
                if sweep_cost > 0:
                    _record_agent_invocation("investigator_orchestration", sweep_cost)
            except Exception:
                pass

            for card in result.thesis_cards:
                await self._process_thesis_card(card)

            if result.no_trade_results:
                self._state.total_no_trade_decisions += len(result.no_trade_results)

            _log.info(
                "scheduled_sweep_complete",
                candidates_evaluated=result.candidates_evaluated,
                accepted=result.candidates_accepted,
                no_trade=len(result.no_trade_results),
            )

        except Exception as exc:
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
            start_of_day_equity=self._portfolio.account_balance_usd
        )

    async def _run_dashboard_sync(self) -> None:
        """Sync system state to dashboard API."""
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

    def _build_resolution_input(self, card: Any) -> Any:
        """Build resolution parse input from a thesis card."""
        from tradeability.types import ResolutionParseInput
        return ResolutionParseInput(
            market_id=getattr(card, "market_id", ""),
            title=getattr(card, "title", ""),
            description=getattr(card, "description", ""),
            resolution_source=getattr(card, "resolution_source", ""),
            end_date=getattr(card, "end_date", None),
        )

    def _build_sizing_request(self, card: Any) -> Any:
        """Build a sizing request from a thesis card."""
        from risk.types import SizingRequest
        return SizingRequest(
            market_id=getattr(card, "market_id", ""),
            category=getattr(card, "category", "unknown"),
            proposed_side=getattr(card, "proposed_side", "yes"),
            proposed_price=getattr(card, "entry_price", 0.5),
            estimated_probability=getattr(card, "calibrated_probability", 0.5),
            gross_edge=getattr(card, "expected_gross_edge", 0.0),
            evidence_score=getattr(card, "evidence_quality_score", 0.5),
            ambiguity_score=getattr(card, "ambiguity_score", 0.0),
            correlation_tags=[],
        )

    def _record_shadow_forecast(self, card: Any) -> None:
        """Record a shadow forecast to the calibration store."""
        try:
            from calibration.types import ShadowForecastInput
            forecast = ShadowForecastInput(
                market_id=getattr(card, "market_id", ""),
                category=getattr(card, "category", "unknown"),
                system_probability=getattr(card, "calibrated_probability", 0.5),
                market_implied_probability=getattr(card, "market_implied_probability", 0.5),
                forecast_at=datetime.now(tz=UTC),
            )
            self._calibration_store.record(forecast)

            _log.info(
                "shadow_forecast_recorded",
                market_id=forecast.market_id,
                system_prob=forecast.system_probability,
                market_prob=forecast.market_implied_probability,
            )
        except Exception as exc:
            _log.error("shadow_forecast_error", error=str(exc))

    def _sync_dashboard_state(self) -> None:
        """Push current system state to the dashboard API module.

        Note: operator_mode is NOT synced here — it is owned by the
        dashboard API layer and persisted to disk independently.
        Overwriting it would undo operator-initiated mode changes.
        """
        try:
            from dashboard_api.app import _system_state

            _system_state["system_status"] = self._state.phase.value
            _system_state["agents_running"] = self._state.phase == SystemPhase.RUNNING

            if self._scanner:
                health = self._scanner.health_monitor.get_health_status()
                _system_state["scanner_api_status"] = "healthy" if health.api_available else "degraded"
                _system_state["scanner_degraded_level"] = health.degraded_mode_level.value
                _system_state["scanner_uptime_pct"] = round(
                    health.uptime_percentage, 1
                )

            if self._absence_manager:
                absence = self._absence_manager.compute_state()
                _system_state["is_absent"] = absence.absence_level.value >= 1
                _system_state["absence_level"] = absence.absence_level.value
                _system_state["hours_since_activity"] = absence.hours_since_last_interaction

            if self._cost_governor:
                budget = self._cost_governor.budget_tracker.state
                _system_state["daily_spend_usd"] = round(budget.daily_spent_usd, 4)
                _system_state["lifetime_spend_usd"] = round(budget.lifetime_spent_usd, 4)
                _system_state["opus_spend_today_usd"] = round(
                    getattr(budget, "daily_opus_spent_usd", 0.0), 4
                )

                selectivity = self._cost_governor.get_selectivity_snapshot()
                _system_state["selectivity_ratio"] = round(
                    selectivity.cost_to_edge_ratio or 0.0, 4
                )

            if self._risk_governor:
                drawdown = self._risk_governor.drawdown_state
                _system_state["drawdown_level"] = drawdown.level.value
                _system_state["drawdown_pct"] = round(drawdown.current_drawdown_pct, 4)

            # Equity snapshot for the chart (taken every sync cycle, ~5 min)
            try:
                from dashboard_api.app import _add_equity_snapshot
                equity = _system_state.get(
                    "paper_balance_usd", self._portfolio.current_equity_usd
                )
                start_equity = _system_state.get(
                    "start_of_day_equity_usd", self._portfolio.start_of_day_equity_usd
                )
                _add_equity_snapshot(
                    equity_usd=round(float(equity), 2),
                    pnl_usd=round(float(equity) - float(start_equity), 2),
                )
            except Exception:
                pass

            # Scanner cache/failure metrics (augment what the health block already set)
            if self._scanner:
                try:
                    health = self._scanner.health_monitor.get_health_status()
                    _system_state["scanner_cache_entries"] = getattr(
                        health, "cache_entries_count", 0
                    )
                    _system_state["scanner_cache_hit_rate"] = getattr(
                        health, "cache_hit_rate", 0.0
                    )
                    _system_state["scanner_consecutive_failures"] = getattr(
                        health, "consecutive_failures", 0
                    )
                    _system_state["scanner_last_poll"] = datetime.now(tz=UTC).isoformat()
                except Exception:
                    pass

        except Exception as exc:
            _log.debug("dashboard_sync_error", error=str(exc))

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
                "workflow_run_duration_seconds": 0.0,
                "candidates_reviewed": 1,
                "top_rejected_market": getattr(no_trade, "market_id", None),
                "rejection_reasons": [getattr(no_trade, "reason_code", "")],
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
                "gross_edge": getattr(card, "expected_gross_edge", None),
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
