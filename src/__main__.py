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
from contextlib import suppress
from pathlib import Path

from config.settings import load_config
from core.enums import OperatorMode
from logging_.logger import get_logger, setup_logging


class _DashboardAPIServer:
    """Own the embedded Uvicorn server so shutdown is explicit and quiet."""

    def __init__(self, log) -> None:
        self._log = log
        self._server = None
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        """Start the dashboard API server in the background."""
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(
            self._serve(),
            name="dashboard_api_server",
        )

    async def stop(self) -> None:
        """Request a graceful Uvicorn shutdown before the loop exits."""
        if self._task is None:
            return

        task = self._task
        server = self._server

        if server is not None and not task.done():
            self._log.info("dashboard_api_stopping", port=8000)
            server.should_exit = True

            done, _ = await asyncio.wait({task}, timeout=5.0)
            if not done:
                self._log.warning(
                    "dashboard_api_shutdown_timeout",
                    timeout_seconds=5.0,
                )
                task.cancel()

        with suppress(asyncio.CancelledError):
            await task

        self._task = None
        self._server = None

    async def _serve(self) -> None:
        """Run the FastAPI dashboard API server."""
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
            self._server = server

            self._log.info("dashboard_api_starting", port=8000)
            await server.serve()
            self._log.info("dashboard_api_stopped", port=8000)
        except ImportError:
            self._log.warning(
                "uvicorn_not_installed",
                message="Dashboard API not started. Install uvicorn.",
            )
        except SystemExit as exc:
            # uvicorn calls sys.exit(1) on bind failure (e.g. port already in use)
            self._log.error(
                "dashboard_api_failed_to_start",
                error=str(exc),
                hint="Port 8000 may already be in use",
            )
        except Exception as exc:
            self._log.error("dashboard_api_error", error=str(exc))
        finally:
            self._server = None


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
    dashboard_api = _DashboardAPIServer(log)

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

        # Start the dashboard API in a background task; failures are logged, not fatal.
        dashboard_api.start()

        # Wait for shutdown signal
        await shutdown_event.wait()

    except Exception as exc:
        log.error("startup_error", error=str(exc))
        raise
    finally:
        log.info("shutting_down")
        await dashboard_api.stop()
        await orchestrator.shutdown()
        log.info("shutdown_complete")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
