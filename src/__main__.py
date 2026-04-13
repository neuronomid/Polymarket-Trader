"""Entry point for `python -m polymarket_trader`.

Loads configuration, sets up logging, and reports system readiness.
Actual workflow scheduling will be added in later phases.
"""

from __future__ import annotations

import asyncio
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

    # Placeholder: workflow scheduler will be wired here in Phase 5+
    log.info("awaiting_shutdown", message="No workflows configured yet. Press Ctrl+C to exit.")
    try:
        await asyncio.Event().wait()
    except asyncio.CancelledError:
        pass

    log.info("shutdown_complete")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
