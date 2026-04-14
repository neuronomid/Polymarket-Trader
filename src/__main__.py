"""Entry point for `python -m polymarket_trader`.

Loads configuration, sets up logging, initializes all subsystems via the
WorkflowOrchestrator, and starts the full pipeline including:
  - Scanner polling loop
  - Scheduled investigation sweeps
  - Position review scheduler
  - Calibration learning loops (fast + slow)
  - Absence monitoring
  - Dashboard API
  - Notification service
"""

from __future__ import annotations

import asyncio
import signal
import sys
from pathlib import Path

from config.settings import load_config
from core.enums import OperatorMode
from logging_.logger import get_logger, setup_logging


async def main() -> None:
    # Resolve config path: CLI arg or default
    config_path: Path | None = None
    if len(sys.argv) > 1:
        config_path = Path(sys.argv[1])
    else:
        default = Path("config/default.yaml")
        if default.exists():
            config_path = default

    config = load_config(config_path)
    setup_logging(config.log_level)
    log = get_logger(component="main")

    log.info(
        "startup",
        operator_mode=config.operator_mode,
        config_source=str(config_path) if config_path else "env_only",
        database_host=config.database.host,
        database_name=config.database.name,
    )

    # Validate operator mode
    try:
        mode = OperatorMode(config.operator_mode)
    except ValueError:
        log.error("invalid_operator_mode", mode=config.operator_mode)
        sys.exit(1)

    log.info(
        "system_ready",
        mode=mode.value,
        risk_max_drawdown=config.risk.max_daily_drawdown_pct,
        cost_daily_budget=config.cost.daily_llm_budget_usd,
        cost_lifetime_budget=config.cost.lifetime_experiment_budget_usd,
    )

    # --- Initialize and start the orchestrator ---
    from workflows.orchestrator import WorkflowOrchestrator

    orchestrator = WorkflowOrchestrator(config)

    # Set up graceful shutdown
    shutdown_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    def _signal_handler():
        log.info("shutdown_signal_received")
        shutdown_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _signal_handler)

    # Inject shutdown event into the dashboard API so the Stop button works
    try:
        from dashboard_api.app import set_shutdown_event
        set_shutdown_event(shutdown_event)
        log.info("shutdown_event_wired_to_dashboard")
    except ImportError:
        log.debug("dashboard_api_not_available_for_shutdown")

    try:
        await orchestrator.initialize()
        log.info("orchestrator_initialized")

        await orchestrator.start()
        log.info(
            "orchestrator_running",
            mode=mode.value,
            message="System is live. Press Ctrl+C to shut down.",
        )

        # Optionally start the dashboard API in a background task
        dashboard_task = asyncio.create_task(_start_dashboard_api(config, log))

        # Wait for shutdown signal
        await shutdown_event.wait()

    except Exception as exc:
        log.error("startup_error", error=str(exc))
        raise
    finally:
        log.info("shutting_down")
        await orchestrator.shutdown()
        log.info("shutdown_complete")


async def _start_dashboard_api(config, log) -> None:
    """Start the FastAPI dashboard API server in the background."""
    try:
        import uvicorn
        from dashboard_api.app import create_dashboard_app

        app = create_dashboard_app()

        uv_config = uvicorn.Config(
            app,
            host="0.0.0.0",
            port=8000,
            log_level="warning",
            access_log=False,
        )
        server = uvicorn.Server(uv_config)

        log.info("dashboard_api_starting", port=8000)
        await server.serve()
    except ImportError:
        log.warning("uvicorn_not_installed", message="Dashboard API not started. Install uvicorn.")
    except Exception as exc:
        log.error("dashboard_api_error", error=str(exc))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
