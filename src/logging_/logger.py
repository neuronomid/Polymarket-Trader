"""Structured JSON logging framework.

Every log entry is attributable to a workflow run with:
timestamp, workflow_run_id, market_id, position_id, event_type, severity, payload.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog


def setup_logging(log_level: str = "INFO") -> None:
    """Configure structlog for JSON-structured output.

    Call once at application startup.
    """
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, log_level.upper(), logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=False,
    )


def get_logger(**initial_bindings: Any) -> structlog.stdlib.BoundLogger:
    """Get a structured logger with optional initial context bindings.

    Usage:
        log = get_logger(workflow_run_id="abc-123", market_id="market-456")
        log.info("eligibility_check", outcome="reject", reason="excluded_category")
    """
    return structlog.get_logger(**initial_bindings)


def bind_workflow_context(
    workflow_run_id: str,
    market_id: str | None = None,
    position_id: str | None = None,
) -> None:
    """Bind workflow context to all subsequent log calls in the current async context.

    Uses structlog contextvars so bindings propagate through async calls.
    """
    structlog.contextvars.clear_contextvars()
    bindings: dict[str, str] = {"workflow_run_id": workflow_run_id}
    if market_id:
        bindings["market_id"] = market_id
    if position_id:
        bindings["position_id"] = position_id
    structlog.contextvars.bind_contextvars(**bindings)


def clear_workflow_context() -> None:
    """Clear workflow context bindings after a workflow completes."""
    structlog.contextvars.clear_contextvars()
