"""Tests for structured logging framework."""

import json

from logging_.logger import (
    bind_workflow_context,
    clear_workflow_context,
    get_logger,
    setup_logging,
)


def test_setup_logging_does_not_raise():
    setup_logging("INFO")
    setup_logging("DEBUG")


def test_get_logger_with_bindings(capsys):
    setup_logging("DEBUG")
    log = get_logger(component="test")
    log.info("test_event", key="value")

    output = capsys.readouterr().out
    parsed = json.loads(output.strip())
    assert parsed["component"] == "test"
    assert parsed["event"] == "test_event"
    assert parsed["key"] == "value"
    assert "timestamp" in parsed


def test_bind_and_clear_workflow_context(capsys):
    setup_logging("DEBUG")
    bind_workflow_context(workflow_run_id="wf-123", market_id="mkt-456")

    log = get_logger()
    log.info("context_test")

    output = capsys.readouterr().out
    parsed = json.loads(output.strip())
    assert parsed["workflow_run_id"] == "wf-123"
    assert parsed["market_id"] == "mkt-456"

    clear_workflow_context()

    log.info("after_clear")
    output = capsys.readouterr().out
    parsed = json.loads(output.strip())
    assert "workflow_run_id" not in parsed
