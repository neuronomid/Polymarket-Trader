"""Tests for configuration loading and validation."""

import tempfile
from pathlib import Path

import yaml

from config.settings import AppConfig, load_config


def test_default_config_loads():
    """Config loads with all defaults when no YAML or env vars provided."""
    config = AppConfig()
    assert config.operator_mode == "paper"
    assert config.log_level == "INFO"
    assert config.database.name == "polymarket_trader"


def test_load_config_from_yaml():
    """Config loads values from a YAML file."""
    yaml_data = {
        "operator_mode": "shadow",
        "log_level": "DEBUG",
        "database": {"host": "testhost", "port": 5433},
        "risk": {"max_daily_drawdown_pct": 0.05},
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(yaml_data, f)
        f.flush()
        config = load_config(Path(f.name))

    assert config.operator_mode == "shadow"
    assert config.log_level == "DEBUG"
    assert config.database.host == "testhost"
    assert config.database.port == 5433
    assert config.risk.max_daily_drawdown_pct == 0.05
    # Defaults preserved for unset values
    assert config.database.name == "polymarket_trader"


def test_load_config_missing_file():
    """Config loads defaults when YAML file doesn't exist."""
    config = load_config(Path("/nonexistent/path.yaml"))
    assert config.operator_mode == "paper"


def test_load_config_none_path():
    """Config loads defaults when no path provided."""
    config = load_config(None)
    assert config.operator_mode == "paper"


def test_database_async_url():
    config = AppConfig()
    url = config.database.async_url
    assert url.startswith("postgresql+asyncpg://")
    assert "polymarket_trader" in url


def test_database_sync_url():
    config = AppConfig()
    url = config.database.sync_url
    assert url.startswith("postgresql://")
    assert "polymarket_trader" in url


def test_risk_drawdown_ladder_ordering():
    """Drawdown thresholds must be in ascending order."""
    config = AppConfig()
    r = config.risk
    assert r.soft_warning_pct < r.risk_reduction_pct < r.entries_disabled_pct < r.hard_kill_switch_pct


def test_absence_escalation_ordering():
    """Absence escalation thresholds must be in ascending order."""
    config = AppConfig()
    a = config.absence
    assert (
        a.no_new_entries_hours
        < a.first_size_reduction_hours
        < a.second_size_reduction_hours
        < a.graceful_winddown_hours
    )


def test_cost_config_defaults():
    config = AppConfig()
    assert config.cost.daily_llm_budget_usd == 25.0
    assert config.cost.lifetime_experiment_budget_usd == 5000.0


def test_calibration_config_defaults():
    config = AppConfig()
    assert config.calibration.sports_min_trades == 40
    assert config.calibration.viability_min_forecasts == 50


def test_default_yaml_file_loads():
    """The shipped default.yaml loads without error."""
    path = Path("config/default.yaml")
    if path.exists():
        config = load_config(path)
        assert config.operator_mode == "paper"
