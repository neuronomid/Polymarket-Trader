"""Tests for Phase 5: Trigger Scanner.

Tests cover:
  - TriggerDetector: all trigger detection rules
  - DegradedModeManager: escalation ladder and recovery
  - ScannerHealthMonitor: health tracking and events
  - TriggerScanner: integration with market data service (scan_once)
  - Types: TriggerBatch properties and helpers

All scanner logic is Tier D (deterministic), no LLM mocking needed.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from config.settings import AppConfig, ScannerConfig
from core.enums import TriggerClass, TriggerLevel
from market_data.types import (
    CachedMarketData,
    DataSource,
    FreshnessStatus,
    MarketSnapshot,
)
from scanner.degraded_mode import DegradedModeManager
from scanner.health_monitor import ScannerHealthMonitor
from scanner.scanner import TriggerScanner
from scanner.trigger_detector import TriggerDetector
from scanner.types import (
    DegradedModeLevel,
    MarketWatchEntry,
    TriggerBatch,
    TriggerEvent,
    TriggerThresholds,
)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def thresholds() -> TriggerThresholds:
    """Default trigger thresholds for testing."""
    return TriggerThresholds()


@pytest.fixture
def detector(thresholds: TriggerThresholds) -> TriggerDetector:
    """Trigger detector with default thresholds."""
    return TriggerDetector(thresholds)


@pytest.fixture
def scanner_config() -> ScannerConfig:
    """Scanner config with quick degraded-mode escalation for testing."""
    return ScannerConfig(
        poll_interval_seconds=1,
        degraded_level1_minutes=3,
        degraded_level2_hours=4,
        degraded_level3_hours=8,
    )


@pytest.fixture
def degraded_mode(scanner_config: ScannerConfig) -> DegradedModeManager:
    """Fresh degraded mode manager for each test."""
    return DegradedModeManager(scanner_config)


@pytest.fixture
def health_monitor(degraded_mode: DegradedModeManager) -> ScannerHealthMonitor:
    """Scanner health monitor wired to degraded mode manager."""
    return ScannerHealthMonitor(degraded_mode)


def _make_watch_entry(
    market_id: str = "market-1",
    token_id: str = "token-1",
    last_price: float | None = 0.50,
    last_spread: float | None = 0.05,
    last_depth_top3: float | None = 1000.0,
    is_held_position: bool = False,
    catalyst_dates: list[datetime] | None = None,
) -> MarketWatchEntry:
    """Helper factory for MarketWatchEntry."""
    return MarketWatchEntry(
        market_id=market_id,
        token_id=token_id,
        last_price=last_price,
        last_spread=last_spread,
        last_depth_top3=last_depth_top3,
        is_held_position=is_held_position,
        catalyst_dates=catalyst_dates or [],
    )


def _make_cached_data(
    token_id: str = "token-1",
    mid_price: float | None = 0.55,
    spread: float | None = 0.05,
    depth_levels: dict | None = None,
    source: DataSource = DataSource.LIVE,
    freshness: FreshnessStatus = FreshnessStatus.FRESH,
    market_status: str | None = None,
) -> CachedMarketData:
    """Helper factory for CachedMarketData."""
    snapshot = MarketSnapshot(
        token_id=token_id,
        mid_price=mid_price,
        price=mid_price,
        spread=spread,
        depth_levels=depth_levels,
        market_status=market_status,
    )
    return CachedMarketData(
        snapshot=snapshot,
        source=source,
        freshness=freshness,
        cache_age_seconds=0.0,
    )


# ============================================================================
# TriggerDetector: Price Move Tests
# ============================================================================


class TestTriggerDetectorPriceMove:
    """Tests for price movement trigger detection."""

    def test_no_trigger_on_small_move(self, detector: TriggerDetector):
        """Price move below level A threshold should produce no trigger."""
        entry = _make_watch_entry(last_price=0.50)
        data = _make_cached_data(mid_price=0.505)  # 1% move
        triggers = detector.detect_triggers(entry, data)
        price_triggers = [t for t in triggers if t.trigger_class == TriggerClass.REPRICING]
        assert len(price_triggers) == 0

    def test_level_a_trigger(self, detector: TriggerDetector):
        """Price move at level A threshold triggers log-only event."""
        entry = _make_watch_entry(last_price=0.50)
        data = _make_cached_data(mid_price=0.515)  # 3% move
        triggers = detector.detect_triggers(entry, data)
        price_triggers = [t for t in triggers if t.trigger_class == TriggerClass.REPRICING]
        assert len(price_triggers) == 1
        assert price_triggers[0].trigger_level == TriggerLevel.A

    def test_level_b_trigger(self, detector: TriggerDetector):
        """5%+ price move triggers level B (lightweight review)."""
        entry = _make_watch_entry(last_price=0.50)
        data = _make_cached_data(mid_price=0.535)  # 7% move
        triggers = detector.detect_triggers(entry, data)
        price_triggers = [t for t in triggers if t.trigger_class == TriggerClass.REPRICING]
        assert len(price_triggers) == 1
        assert price_triggers[0].trigger_level == TriggerLevel.B

    def test_level_c_trigger(self, detector: TriggerDetector):
        """10%+ price move triggers level C (full investigation)."""
        entry = _make_watch_entry(last_price=0.50)
        data = _make_cached_data(mid_price=0.56)  # 12% move
        triggers = detector.detect_triggers(entry, data)
        price_triggers = [t for t in triggers if t.trigger_class == TriggerClass.REPRICING]
        assert len(price_triggers) == 1
        assert price_triggers[0].trigger_level == TriggerLevel.C

    def test_level_d_trigger(self, detector: TriggerDetector):
        """20%+ price move triggers level D (immediate risk intervention)."""
        entry = _make_watch_entry(last_price=0.50)
        data = _make_cached_data(mid_price=0.65)  # 30% move
        triggers = detector.detect_triggers(entry, data)
        price_triggers = [t for t in triggers if t.trigger_class == TriggerClass.REPRICING]
        assert len(price_triggers) == 1
        assert price_triggers[0].trigger_level == TriggerLevel.D

    def test_downward_price_move(self, detector: TriggerDetector):
        """Downward price movement should also produce triggers."""
        entry = _make_watch_entry(last_price=0.50)
        data = _make_cached_data(mid_price=0.40)  # -20% move
        triggers = detector.detect_triggers(entry, data)
        price_triggers = [t for t in triggers if t.trigger_class == TriggerClass.REPRICING]
        assert len(price_triggers) == 1
        assert "down" in price_triggers[0].reason

    def test_no_trigger_when_no_previous_price(self, detector: TriggerDetector):
        """No trigger when watch entry has no previous price."""
        entry = _make_watch_entry(last_price=None)
        data = _make_cached_data(mid_price=0.50)
        triggers = detector.detect_triggers(entry, data)
        price_triggers = [t for t in triggers if t.trigger_class == TriggerClass.REPRICING]
        assert len(price_triggers) == 0

    def test_no_trigger_when_no_current_price(self, detector: TriggerDetector):
        """No trigger when current data has no mid price."""
        entry = _make_watch_entry(last_price=0.50)
        data = _make_cached_data(mid_price=None)
        triggers = detector.detect_triggers(entry, data)
        price_triggers = [t for t in triggers if t.trigger_class == TriggerClass.REPRICING]
        assert len(price_triggers) == 0

    def test_trigger_records_change_pct(self, detector: TriggerDetector):
        """Trigger event should record the change percentage."""
        entry = _make_watch_entry(last_price=0.50)
        data = _make_cached_data(mid_price=0.56)  # 12%
        triggers = detector.detect_triggers(entry, data)
        price_triggers = [t for t in triggers if t.trigger_class == TriggerClass.REPRICING]
        assert price_triggers[0].change_pct is not None
        assert abs(price_triggers[0].change_pct - 0.12) < 0.01

    def test_trigger_records_previous_and_current(self, detector: TriggerDetector):
        """Trigger should capture both previous and current values."""
        entry = _make_watch_entry(last_price=0.50)
        data = _make_cached_data(mid_price=0.56)
        triggers = detector.detect_triggers(entry, data)
        price_triggers = [t for t in triggers if t.trigger_class == TriggerClass.REPRICING]
        assert price_triggers[0].previous_value == 0.50
        assert price_triggers[0].current_value == 0.56

    def test_extreme_probability_repricing_is_ignored_for_unheld_market(
        self,
        detector: TriggerDetector,
    ):
        """Tiny longshot repricings should not surface as entry signals."""
        entry = _make_watch_entry(last_price=0.0075, is_held_position=False)
        data = _make_cached_data(mid_price=0.0085)
        triggers = detector.detect_triggers(entry, data)
        price_triggers = [t for t in triggers if t.trigger_class == TriggerClass.REPRICING]
        assert price_triggers == []


# ============================================================================
# TriggerDetector: Spread Tests
# ============================================================================


class TestTriggerDetectorSpread:
    """Tests for spread-based trigger detection."""

    def test_spread_widen_warning(self, detector: TriggerDetector):
        """Spread widening to warning level (>=0.10)."""
        entry = _make_watch_entry(last_spread=0.05)
        data = _make_cached_data(spread=0.12)
        triggers = detector.detect_triggers(entry, data)
        spread_triggers = [t for t in triggers if t.trigger_class == TriggerClass.LIQUIDITY]
        assert len(spread_triggers) == 1
        assert spread_triggers[0].trigger_level == TriggerLevel.B

    def test_spread_widen_critical(self, detector: TriggerDetector):
        """Spread widening to critical level (>=0.20)."""
        entry = _make_watch_entry(last_spread=0.05)
        data = _make_cached_data(spread=0.25)
        triggers = detector.detect_triggers(entry, data)
        spread_triggers = [t for t in triggers if t.trigger_class == TriggerClass.LIQUIDITY]
        assert len(spread_triggers) == 1
        assert spread_triggers[0].trigger_level == TriggerLevel.C

    def test_spread_narrow_opportunity(self, detector: TriggerDetector):
        """Spread narrowing to opportunity level should trigger discovery."""
        entry = _make_watch_entry(last_spread=0.08)
        data = _make_cached_data(spread=0.02)
        triggers = detector.detect_triggers(entry, data)
        discovery_triggers = [t for t in triggers if t.trigger_class == TriggerClass.DISCOVERY]
        assert len(discovery_triggers) == 1
        assert discovery_triggers[0].trigger_level == TriggerLevel.A

    def test_no_spread_trigger_on_normal_spread(self, detector: TriggerDetector):
        """Normal spread should not trigger anything."""
        entry = _make_watch_entry(last_spread=0.05)
        data = _make_cached_data(spread=0.06)
        triggers = detector.detect_triggers(entry, data)
        spread_triggers = [t for t in triggers if t.trigger_class == TriggerClass.LIQUIDITY]
        assert len(spread_triggers) == 0

    def test_no_spread_trigger_when_none(self, detector: TriggerDetector):
        """No trigger when spread data is None."""
        entry = _make_watch_entry(last_spread=0.05)
        data = _make_cached_data(spread=None)
        triggers = detector.detect_triggers(entry, data)
        spread_triggers = [t for t in triggers if t.trigger_class == TriggerClass.LIQUIDITY]
        assert len(spread_triggers) == 0


# ============================================================================
# TriggerDetector: Depth Change Tests
# ============================================================================


class TestTriggerDetectorDepth:
    """Tests for depth change trigger detection."""

    def test_depth_decrease_warning(self, detector: TriggerDetector):
        """30%+ depth decrease triggers a warning."""
        entry = _make_watch_entry(last_depth_top3=1000.0)
        depth = {
            "bids": [{"price": 0.50, "size": 200}, {"price": 0.49, "size": 100}],
            "asks": [{"price": 0.52, "size": 200}, {"price": 0.53, "size": 100}],
        }
        data = _make_cached_data(depth_levels=depth)  # top3 = 600
        triggers = detector.detect_triggers(entry, data)
        depth_triggers = [
            t for t in triggers
            if t.trigger_class == TriggerClass.LIQUIDITY
            and t.depth_snapshot is not None
        ]
        assert len(depth_triggers) == 1
        assert depth_triggers[0].trigger_level in (TriggerLevel.B, TriggerLevel.C)

    def test_depth_decrease_critical(self, detector: TriggerDetector):
        """50%+ depth decrease triggers critical level."""
        entry = _make_watch_entry(last_depth_top3=1000.0)
        depth = {
            "bids": [{"price": 0.50, "size": 100}, {"price": 0.49, "size": 50}],
            "asks": [{"price": 0.52, "size": 100}, {"price": 0.53, "size": 50}],
        }
        data = _make_cached_data(depth_levels=depth)  # top3 = 300
        triggers = detector.detect_triggers(entry, data)
        depth_triggers = [
            t for t in triggers
            if t.trigger_class == TriggerClass.LIQUIDITY
            and t.depth_snapshot is not None
        ]
        assert len(depth_triggers) == 1
        assert depth_triggers[0].trigger_level == TriggerLevel.C

    def test_no_depth_trigger_on_stable(self, detector: TriggerDetector):
        """No trigger when depth is stable."""
        entry = _make_watch_entry(last_depth_top3=1000.0)
        depth = {
            "bids": [{"price": 0.50, "size": 300}, {"price": 0.49, "size": 200}],
            "asks": [{"price": 0.52, "size": 300}, {"price": 0.53, "size": 200}],
        }
        data = _make_cached_data(depth_levels=depth)  # top3 = 1000
        triggers = detector.detect_triggers(entry, data)
        depth_triggers = [
            t for t in triggers
            if t.trigger_class == TriggerClass.LIQUIDITY
            and t.depth_snapshot is not None
        ]
        assert len(depth_triggers) == 0

    def test_no_depth_trigger_when_no_previous(self, detector: TriggerDetector):
        """No trigger when no previous depth data."""
        entry = _make_watch_entry(last_depth_top3=None)
        depth = {
            "bids": [{"price": 0.50, "size": 300}],
            "asks": [{"price": 0.52, "size": 300}],
        }
        data = _make_cached_data(depth_levels=depth)
        triggers = detector.detect_triggers(entry, data)
        depth_triggers = [
            t for t in triggers
            if t.trigger_class == TriggerClass.LIQUIDITY
            and t.depth_snapshot is not None
        ]
        assert len(depth_triggers) == 0

    def test_extreme_probability_depth_change_is_ignored_for_unheld_market(
        self,
        detector: TriggerDetector,
    ):
        """Longshot depth shocks should not surface as entry opportunities."""
        entry = _make_watch_entry(
            last_price=0.0015,
            last_depth_top3=500000.0,
            is_held_position=False,
        )
        depth = {
            "bids": [{"price": 0.0010, "size": 50000}],
            "asks": [{"price": 0.0020, "size": 65000}],
        }
        data = _make_cached_data(mid_price=0.0010, depth_levels=depth)
        triggers = detector.detect_triggers(entry, data)
        depth_triggers = [
            t for t in triggers
            if t.trigger_class == TriggerClass.LIQUIDITY
            and t.depth_snapshot is not None
        ]
        assert depth_triggers == []


# ============================================================================
# TriggerDetector: Position-Specific Tests
# ============================================================================


class TestTriggerDetectorPositionTriggers:
    """Tests for held-position specific triggers."""

    def test_adverse_move_level_b(self, detector: TriggerDetector):
        """Moderate adverse move on held position → level B."""
        entry = _make_watch_entry(last_price=0.50, is_held_position=True)
        data = _make_cached_data(mid_price=0.47)  # -6% move
        triggers = detector.detect_triggers(entry, data)
        stress_triggers = [t for t in triggers if t.trigger_class == TriggerClass.POSITION_STRESS]
        assert len(stress_triggers) == 1
        assert stress_triggers[0].trigger_level == TriggerLevel.B

    def test_adverse_move_level_c(self, detector: TriggerDetector):
        """Significant adverse move → level C (full review)."""
        entry = _make_watch_entry(last_price=0.50, is_held_position=True)
        data = _make_cached_data(mid_price=0.44)  # -12% move
        triggers = detector.detect_triggers(entry, data)
        stress_triggers = [t for t in triggers if t.trigger_class == TriggerClass.POSITION_STRESS]
        assert len(stress_triggers) == 1
        assert stress_triggers[0].trigger_level == TriggerLevel.C

    def test_adverse_move_level_d(self, detector: TriggerDetector):
        """Sharp adverse move → level D (immediate risk intervention)."""
        entry = _make_watch_entry(last_price=0.50, is_held_position=True)
        data = _make_cached_data(mid_price=0.40)  # -20% move
        triggers = detector.detect_triggers(entry, data)
        stress_triggers = [t for t in triggers if t.trigger_class == TriggerClass.POSITION_STRESS]
        assert len(stress_triggers) == 1
        assert stress_triggers[0].trigger_level == TriggerLevel.D
        assert stress_triggers[0].requires_immediate_action

    def test_favorable_move_level_b(self, detector: TriggerDetector):
        """Favorable move on position → profit protection level B."""
        entry = _make_watch_entry(last_price=0.50, is_held_position=True)
        data = _make_cached_data(mid_price=0.545)  # +9% move
        triggers = detector.detect_triggers(entry, data)
        profit_triggers = [t for t in triggers if t.trigger_class == TriggerClass.PROFIT_PROTECTION]
        assert len(profit_triggers) == 1
        assert profit_triggers[0].trigger_level == TriggerLevel.B

    def test_favorable_move_level_c(self, detector: TriggerDetector):
        """Large favorable move → profit protection level C."""
        entry = _make_watch_entry(last_price=0.50, is_held_position=True)
        data = _make_cached_data(mid_price=0.60)  # +20%
        triggers = detector.detect_triggers(entry, data)
        profit_triggers = [t for t in triggers if t.trigger_class == TriggerClass.PROFIT_PROTECTION]
        assert len(profit_triggers) == 1
        assert profit_triggers[0].trigger_level == TriggerLevel.C

    def test_no_position_triggers_for_non_held(self, detector: TriggerDetector):
        """Non-held positions should not produce position-specific triggers."""
        entry = _make_watch_entry(last_price=0.50, is_held_position=False)
        data = _make_cached_data(mid_price=0.40)  # -20%
        triggers = detector.detect_triggers(entry, data)
        position_triggers = [
            t for t in triggers
            if t.trigger_class in (TriggerClass.POSITION_STRESS, TriggerClass.PROFIT_PROTECTION)
        ]
        assert len(position_triggers) == 0


# ============================================================================
# TriggerDetector: Catalyst Window Tests
# ============================================================================


class TestTriggerDetectorCatalyst:
    """Tests for catalyst window approach detection."""

    def test_catalyst_approaching(self, detector: TriggerDetector):
        """Catalyst within window hours → level B."""
        catalyst = datetime.now(tz=UTC) + timedelta(hours=36)
        entry = _make_watch_entry(catalyst_dates=[catalyst])
        data = _make_cached_data()
        triggers = detector.detect_triggers(entry, data)
        catalyst_triggers = [t for t in triggers if t.trigger_class == TriggerClass.CATALYST_WINDOW]
        assert len(catalyst_triggers) == 1
        assert catalyst_triggers[0].trigger_level == TriggerLevel.B

    def test_catalyst_imminent(self, detector: TriggerDetector):
        """Catalyst within imminent hours → level C."""
        catalyst = datetime.now(tz=UTC) + timedelta(hours=6)
        entry = _make_watch_entry(catalyst_dates=[catalyst])
        data = _make_cached_data()
        triggers = detector.detect_triggers(entry, data)
        catalyst_triggers = [t for t in triggers if t.trigger_class == TriggerClass.CATALYST_WINDOW]
        assert len(catalyst_triggers) == 1
        assert catalyst_triggers[0].trigger_level == TriggerLevel.C

    def test_catalyst_in_past_ignored(self, detector: TriggerDetector):
        """Past catalysts should not trigger."""
        catalyst = datetime.now(tz=UTC) - timedelta(hours=1)
        entry = _make_watch_entry(catalyst_dates=[catalyst])
        data = _make_cached_data()
        triggers = detector.detect_triggers(entry, data)
        catalyst_triggers = [t for t in triggers if t.trigger_class == TriggerClass.CATALYST_WINDOW]
        assert len(catalyst_triggers) == 0

    def test_no_catalyst_dates(self, detector: TriggerDetector):
        """No catalyst dates → no trigger."""
        entry = _make_watch_entry(catalyst_dates=[])
        data = _make_cached_data()
        triggers = detector.detect_triggers(entry, data)
        catalyst_triggers = [t for t in triggers if t.trigger_class == TriggerClass.CATALYST_WINDOW]
        assert len(catalyst_triggers) == 0

    def test_catalyst_far_away_no_trigger(self, detector: TriggerDetector):
        """Catalyst more than 48h away → no trigger."""
        catalyst = datetime.now(tz=UTC) + timedelta(days=7)
        entry = _make_watch_entry(catalyst_dates=[catalyst])
        data = _make_cached_data()
        triggers = detector.detect_triggers(entry, data)
        catalyst_triggers = [t for t in triggers if t.trigger_class == TriggerClass.CATALYST_WINDOW]
        assert len(catalyst_triggers) == 0


# ============================================================================
# TriggerDetector: Market Status Tests
# ============================================================================


class TestTriggerDetectorMarketStatus:
    """Tests for market status change detection."""

    @pytest.mark.parametrize("status", ["resolved", "halted", "closed", "paused"])
    def test_critical_status_non_held(self, detector: TriggerDetector, status: str):
        """Critical market status on non-held market → level C."""
        entry = _make_watch_entry(is_held_position=False)
        data = _make_cached_data(market_status=status)
        triggers = detector.detect_triggers(entry, data)
        status_triggers = [
            t for t in triggers
            if t.reason and "status" in t.reason.lower()
        ]
        assert len(status_triggers) == 1
        assert status_triggers[0].trigger_level == TriggerLevel.C

    @pytest.mark.parametrize("status", ["resolved", "halted", "closed", "paused"])
    def test_critical_status_held_position(self, detector: TriggerDetector, status: str):
        """Critical market status on held position → level D."""
        entry = _make_watch_entry(is_held_position=True)
        data = _make_cached_data(market_status=status)
        triggers = detector.detect_triggers(entry, data)
        status_triggers = [
            t for t in triggers
            if t.reason and "status" in t.reason.lower()
        ]
        assert len(status_triggers) == 1
        assert status_triggers[0].trigger_level == TriggerLevel.D

    def test_normal_status_no_trigger(self, detector: TriggerDetector):
        """Normal status (None or active) should not trigger."""
        entry = _make_watch_entry()
        data = _make_cached_data(market_status=None)
        triggers = detector.detect_triggers(entry, data)
        status_triggers = [
            t for t in triggers
            if t.reason and "status" in t.reason.lower()
        ]
        assert len(status_triggers) == 0


# ============================================================================
# DegradedModeManager Tests
# ============================================================================


class TestDegradedModeManager:
    """Tests for degraded mode escalation and recovery."""

    def test_initial_state_is_normal(self, degraded_mode: DegradedModeManager):
        """Fresh manager should be at level 0 (normal)."""
        assert degraded_mode.current_level == DegradedModeLevel.NORMAL
        assert not degraded_mode.is_degraded
        assert degraded_mode.discovery_triggers_allowed
        assert degraded_mode.size_reduction_pct == 0.0
        assert not degraded_mode.position_reduction_active

    def test_single_failure_no_transition(self, degraded_mode: DegradedModeManager):
        """Single failure within freshness window should not escalate."""
        event = degraded_mode.record_failure()
        # May or may not produce event depending on whether the freshness
        # threshold was exceeded. With default 3min, a single instant failure
        # should not yet reach stale level.
        assert degraded_mode.current_level == DegradedModeLevel.NORMAL

    def test_escalation_to_stale_cache(self, degraded_mode: DegradedModeManager):
        """After freshness threshold exceeded → level 1 (stale cache)."""
        # Simulate degraded_since being more than 3 minutes ago
        degraded_mode._degraded_since = datetime.now(tz=UTC) - timedelta(minutes=5)
        degraded_mode._consecutive_failures = 10
        event = degraded_mode.record_failure()

        assert degraded_mode.current_level == DegradedModeLevel.STALE_CACHE
        assert degraded_mode.is_degraded
        assert not degraded_mode.discovery_triggers_allowed
        assert degraded_mode.stale_data_flag
        assert event is not None
        assert event.event_type in ("degraded_enter", "degraded_level_change")

    def test_escalation_to_size_reduction(self, degraded_mode: DegradedModeManager):
        """After 4+ hours → level 2 (size reduction)."""
        degraded_mode._degraded_since = datetime.now(tz=UTC) - timedelta(hours=5)
        degraded_mode._consecutive_failures = 100
        degraded_mode._current_level = DegradedModeLevel.STALE_CACHE  # Simulate prior state
        event = degraded_mode.record_failure()

        assert degraded_mode.current_level == DegradedModeLevel.SIZE_REDUCTION
        assert degraded_mode.size_reduction_pct == 0.15

    def test_escalation_to_position_reduction(self, degraded_mode: DegradedModeManager):
        """After 8+ hours → level 3 (position reduction)."""
        degraded_mode._degraded_since = datetime.now(tz=UTC) - timedelta(hours=9)
        degraded_mode._consecutive_failures = 200
        degraded_mode._current_level = DegradedModeLevel.SIZE_REDUCTION
        event = degraded_mode.record_failure()

        assert degraded_mode.current_level == DegradedModeLevel.POSITION_REDUCTION
        assert degraded_mode.position_reduction_active
        assert event is not None
        assert event.severity == "critical"

    def test_recovery_from_degraded(self, degraded_mode: DegradedModeManager):
        """Successful poll should recover from any degraded level."""
        # Set up degraded state
        degraded_mode._current_level = DegradedModeLevel.SIZE_REDUCTION
        degraded_mode._degraded_since = datetime.now(tz=UTC) - timedelta(hours=5)
        degraded_mode._consecutive_failures = 50

        event = degraded_mode.record_success()

        assert degraded_mode.current_level == DegradedModeLevel.NORMAL
        assert not degraded_mode.is_degraded
        assert degraded_mode.consecutive_failures == 0
        assert event is not None
        assert event.event_type == "recovery"

    def test_no_event_on_normal_success(self, degraded_mode: DegradedModeManager):
        """Success during normal operation should not emit an event."""
        event = degraded_mode.record_success()
        assert event is None

    def test_restrictions_summary(self, degraded_mode: DegradedModeManager):
        """Restrictions summary should reflect current state."""
        summary = degraded_mode.get_restrictions_summary()
        assert summary["level"] == 0
        assert summary["is_degraded"] is False
        assert summary["discovery_triggers_allowed"] is True


# ============================================================================
# ScannerHealthMonitor Tests
# ============================================================================


class TestScannerHealthMonitor:
    """Tests for the scanner health monitor."""

    def test_initial_health_status(self, health_monitor: ScannerHealthMonitor):
        """Initial health should show API as available."""
        status = health_monitor.get_health_status()
        assert status.api_available
        assert status.degraded_mode_level == DegradedModeLevel.NORMAL
        assert status.total_polls == 0

    def test_poll_success_tracking(self, health_monitor: ScannerHealthMonitor):
        """Successful polls should be counted."""
        health_monitor.record_poll_success(triggers_detected=3)
        health_monitor.record_poll_success(triggers_detected=1)

        status = health_monitor.get_health_status()
        assert status.total_polls == 2
        assert status.total_triggers_detected == 4

    def test_poll_failure_tracking(self, health_monitor: ScannerHealthMonitor):
        """Failed polls should be tracked and emit health events."""
        health_monitor.record_poll_failure("Connection timeout")
        health_monitor.record_poll_failure("504 Gateway Timeout")

        status = health_monitor.get_health_status()
        assert status.total_polls == 2
        assert status.consecutive_global_failures == 2

    def test_health_events_stored(self, health_monitor: ScannerHealthMonitor):
        """Health events should be stored for retrieval."""
        health_monitor.record_poll_failure("test error")
        events = health_monitor.get_recent_health_events()
        assert len(events) >= 1
        assert events[0].event_type == "api_failure"

    def test_recovery_event_emitted(self, health_monitor: ScannerHealthMonitor):
        """Recovery from degraded mode should emit a health event."""
        # Force into degraded state
        dm = health_monitor._degraded_mode
        dm._current_level = DegradedModeLevel.STALE_CACHE
        dm._degraded_since = datetime.now(tz=UTC) - timedelta(minutes=5)
        dm._consecutive_failures = 10

        event = health_monitor.record_poll_success()
        assert event is not None
        assert event.event_type == "recovery"


# ============================================================================
# TriggerBatch Tests
# ============================================================================


class TestTriggerBatch:
    """Tests for TriggerBatch properties and helpers."""

    def test_empty_batch(self):
        """Empty batch should have zero counts."""
        batch = TriggerBatch(batch_id="test")
        assert batch.trigger_count == 0
        assert batch.actionable_triggers == []
        assert not batch.has_immediate_actions
        assert batch.trigger_summary() == {}

    def test_batch_with_triggers(self):
        """Batch should correctly aggregate triggers."""
        triggers = [
            TriggerEvent(
                market_id="m1", token_id="t1",
                trigger_class=TriggerClass.REPRICING, trigger_level=TriggerLevel.A,
                reason="price move",
            ),
            TriggerEvent(
                market_id="m2", token_id="t2",
                trigger_class=TriggerClass.LIQUIDITY, trigger_level=TriggerLevel.C,
                reason="spread wide",
            ),
            TriggerEvent(
                market_id="m3", token_id="t3",
                trigger_class=TriggerClass.POSITION_STRESS, trigger_level=TriggerLevel.D,
                reason="sharp adverse",
            ),
        ]
        batch = TriggerBatch(batch_id="test", triggers=triggers)

        assert batch.trigger_count == 3
        assert len(batch.actionable_triggers) == 2  # B, C, D levels
        assert batch.has_immediate_actions  # Level D present

    def test_triggers_by_level(self):
        """Triggers should be groupable by level."""
        triggers = [
            TriggerEvent(
                market_id="m1", token_id="t1",
                trigger_class=TriggerClass.REPRICING, trigger_level=TriggerLevel.A,
                reason="p1",
            ),
            TriggerEvent(
                market_id="m2", token_id="t2",
                trigger_class=TriggerClass.REPRICING, trigger_level=TriggerLevel.A,
                reason="p2",
            ),
            TriggerEvent(
                market_id="m3", token_id="t3",
                trigger_class=TriggerClass.LIQUIDITY, trigger_level=TriggerLevel.C,
                reason="s1",
            ),
        ]
        batch = TriggerBatch(batch_id="test", triggers=triggers)
        by_level = batch.triggers_by_level()

        assert len(by_level[TriggerLevel.A]) == 2
        assert len(by_level[TriggerLevel.C]) == 1

    def test_trigger_summary(self):
        """Summary should provide class_level counts."""
        triggers = [
            TriggerEvent(
                market_id="m1", token_id="t1",
                trigger_class=TriggerClass.REPRICING, trigger_level=TriggerLevel.B,
                reason="p1",
            ),
            TriggerEvent(
                market_id="m2", token_id="t2",
                trigger_class=TriggerClass.REPRICING, trigger_level=TriggerLevel.B,
                reason="p2",
            ),
        ]
        batch = TriggerBatch(batch_id="test", triggers=triggers)
        summary = batch.trigger_summary()
        assert summary["repricing_B"] == 2


# ============================================================================
# TriggerEvent Properties Tests
# ============================================================================


class TestTriggerEvent:
    """Tests for TriggerEvent model properties."""

    def test_level_a_is_not_actionable(self):
        """Level A triggers are log-only, not actionable."""
        event = TriggerEvent(
            market_id="m1", token_id="t1",
            trigger_class=TriggerClass.REPRICING, trigger_level=TriggerLevel.A,
            reason="test",
        )
        assert not event.is_actionable
        assert not event.requires_immediate_action

    def test_level_b_is_actionable(self):
        """Level B triggers are actionable (lightweight review)."""
        event = TriggerEvent(
            market_id="m1", token_id="t1",
            trigger_class=TriggerClass.REPRICING, trigger_level=TriggerLevel.B,
            reason="test",
        )
        assert event.is_actionable
        assert not event.requires_immediate_action

    def test_level_d_requires_immediate_action(self):
        """Level D triggers require immediate risk intervention."""
        event = TriggerEvent(
            market_id="m1", token_id="t1",
            trigger_class=TriggerClass.POSITION_STRESS, trigger_level=TriggerLevel.D,
            reason="test",
        )
        assert event.is_actionable
        assert event.requires_immediate_action


# ============================================================================
# TriggerScanner Integration Tests
# ============================================================================


class TestTriggerScannerIntegration:
    """Integration tests for the full scanner loop using mocked MarketDataService."""

    @pytest.fixture
    def mock_market_data(self) -> MagicMock:
        """Mock MarketDataService."""
        service = AsyncMock()
        service.poll_batch = AsyncMock(return_value={})
        service.run_eviction = AsyncMock(return_value=0)
        service.get_failure_count = MagicMock(return_value=0)
        service.get_failure_threshold = MagicMock(return_value=3)
        return service

    @pytest.fixture
    def scanner(self, mock_market_data: AsyncMock) -> TriggerScanner:
        """TriggerScanner with mocked dependencies."""
        config = AppConfig()
        return TriggerScanner(config, mock_market_data)

    @pytest.mark.asyncio
    async def test_scan_once_empty_watch_list(self, scanner: TriggerScanner):
        """Scan with empty watch list should return empty batch."""
        batch = await scanner.scan_once()
        assert batch.markets_scanned == 0
        assert batch.trigger_count == 0

    @pytest.mark.asyncio
    async def test_scan_once_with_markets(
        self, scanner: TriggerScanner, mock_market_data: AsyncMock
    ):
        """Scan with watched markets should poll and detect triggers."""
        # Add a market to watch
        entry = _make_watch_entry(last_price=0.50)
        scanner.add_to_watch_list(entry)

        # Mock poll returning data with a big price move
        mock_market_data.poll_batch.return_value = {
            "token-1": _make_cached_data(mid_price=0.65),  # 30% move
        }

        batch = await scanner.scan_once()
        assert batch.markets_scanned == 1
        assert batch.trigger_count >= 1  # At least a price move trigger

    @pytest.mark.asyncio
    async def test_scan_updates_watch_entry(
        self, scanner: TriggerScanner, mock_market_data: AsyncMock
    ):
        """After scan, watch entry should be updated with latest data."""
        entry = _make_watch_entry(last_price=0.50)
        scanner.add_to_watch_list(entry)

        mock_market_data.poll_batch.return_value = {
            "token-1": _make_cached_data(mid_price=0.52, spread=0.04),
        }

        await scanner.scan_once()

        updated = scanner._watch_list["token-1"]
        assert updated.last_price == 0.52
        assert updated.last_spread == 0.04
        assert updated.last_scanned_at is not None

    @pytest.mark.asyncio
    async def test_scan_poll_failure(
        self, scanner: TriggerScanner, mock_market_data: AsyncMock
    ):
        """Poll failure should record failure and return empty batch."""
        entry = _make_watch_entry()
        scanner.add_to_watch_list(entry)

        mock_market_data.poll_batch.side_effect = Exception("API timeout")

        batch = await scanner.scan_once()
        assert batch.markets_scanned == 0

    @pytest.mark.asyncio
    async def test_trigger_callback_invoked(
        self, scanner: TriggerScanner, mock_market_data: AsyncMock
    ):
        """Trigger callback should be invoked when triggers are detected."""
        received_batches: list[TriggerBatch] = []

        async def callback(batch: TriggerBatch):
            received_batches.append(batch)

        scanner.set_trigger_callback(callback)
        entry = _make_watch_entry(last_price=0.50)
        scanner.add_to_watch_list(entry)

        mock_market_data.poll_batch.return_value = {
            "token-1": _make_cached_data(mid_price=0.65),  # Big move
        }

        await scanner.scan_once()

        assert len(received_batches) == 1
        assert received_batches[0].trigger_count >= 1

    @pytest.mark.asyncio
    async def test_no_callback_on_empty_triggers(
        self, scanner: TriggerScanner, mock_market_data: AsyncMock
    ):
        """Callback should not be invoked when no triggers detected."""
        received: list[TriggerBatch] = []

        async def callback(batch: TriggerBatch):
            received.append(batch)

        scanner.set_trigger_callback(callback)
        entry = _make_watch_entry(last_price=0.50)
        scanner.add_to_watch_list(entry)

        mock_market_data.poll_batch.return_value = {
            "token-1": _make_cached_data(mid_price=0.505),  # Tiny move, < 2%
        }

        await scanner.scan_once()
        assert len(received) == 0

    @pytest.mark.asyncio
    async def test_watch_list_management(self, scanner: TriggerScanner):
        """Watch list add/remove/set should work correctly."""
        entry1 = _make_watch_entry(token_id="t1", market_id="m1")
        entry2 = _make_watch_entry(token_id="t2", market_id="m2")

        scanner.add_to_watch_list(entry1)
        scanner.add_to_watch_list(entry2)
        assert len(scanner.get_watch_list()) == 2

        scanner.remove_from_watch_list("t1")
        assert len(scanner.get_watch_list()) == 1

        scanner.set_watch_list([entry1])
        assert len(scanner.get_watch_list()) == 1
        assert scanner._watch_list["t1"].market_id == "m1"

    @pytest.mark.asyncio
    async def test_health_accessible(self, scanner: TriggerScanner):
        """Scanner should expose health monitor."""
        assert scanner.health_monitor is not None
        status = scanner.health_monitor.get_health_status()
        assert status.api_available

    @pytest.mark.asyncio
    async def test_degraded_mode_suppresses_on_poll_failure(
        self, scanner: TriggerScanner, mock_market_data: AsyncMock
    ):
        """During degraded mode with a poll failure, batch reflects degraded level."""
        entry = _make_watch_entry(last_price=0.50, is_held_position=False)
        scanner.add_to_watch_list(entry)

        # Force degraded mode
        scanner._degraded_mode._current_level = DegradedModeLevel.STALE_CACHE
        scanner._degraded_mode._degraded_since = datetime.now(tz=UTC) - timedelta(minutes=5)

        # Simulate a failed poll
        mock_market_data.poll_batch.side_effect = Exception("API down")

        batch = await scanner.scan_once()
        # Batch should reflect degraded mode level and have no triggers
        assert batch.degraded_mode_level == DegradedModeLevel.STALE_CACHE
        assert batch.trigger_count == 0
        assert batch.markets_scanned == 0

    @pytest.mark.asyncio
    async def test_stale_data_skips_non_held_markets(
        self, scanner: TriggerScanner, mock_market_data: AsyncMock
    ):
        """Stale cache data for non-held positions should be skipped during degraded mode."""
        non_held = _make_watch_entry(last_price=0.50, is_held_position=False, token_id="t1")
        held = _make_watch_entry(last_price=0.50, is_held_position=True, token_id="t2", market_id="m2")
        scanner.add_to_watch_list(non_held)
        scanner.add_to_watch_list(held)

        # Force degraded mode — but poll succeeds (cache serving)
        scanner._degraded_mode._current_level = DegradedModeLevel.STALE_CACHE
        scanner._degraded_mode._degraded_since = datetime.now(tz=UTC) - timedelta(minutes=5)
        scanner._degraded_mode._consecutive_failures = 10

        mock_market_data.poll_batch.return_value = {
            "t1": _make_cached_data(
                token_id="t1", mid_price=0.65,
                freshness=FreshnessStatus.STALE, source=DataSource.CACHE,
            ),
            "t2": _make_cached_data(
                token_id="t2", mid_price=0.35,
                freshness=FreshnessStatus.STALE, source=DataSource.CACHE,
            ),
        }

        batch = await scanner.scan_once()
        # Non-held stale data should be skipped, held position should still trigger
        position_triggers = [t for t in batch.triggers if t.token_id == "t2"]
        non_held_triggers = [t for t in batch.triggers if t.token_id == "t1"]
        # Held position with adverse move should still trigger
        assert len(position_triggers) >= 1
        # Non-held with stale data should be skipped
        assert len(non_held_triggers) == 0


# ============================================================================
# Threshold Customization Tests
# ============================================================================


class TestCustomThresholds:
    """Tests that custom thresholds are applied correctly."""

    def test_custom_price_threshold(self):
        """Custom price threshold should change trigger sensitivity."""
        thresholds = TriggerThresholds(
            price_move_level_a=0.01,  # 1% instead of 2%
            price_move_level_b=0.03,  # 3% instead of 5%
        )
        detector = TriggerDetector(thresholds)

        entry = _make_watch_entry(last_price=0.50)
        data = _make_cached_data(mid_price=0.508)  # 1.6% move

        triggers = detector.detect_triggers(entry, data)
        price_triggers = [t for t in triggers if t.trigger_class == TriggerClass.REPRICING]
        assert len(price_triggers) == 1
        assert price_triggers[0].trigger_level == TriggerLevel.A

    def test_custom_spread_threshold(self):
        """Custom spread thresholds should affect sensitivity."""
        thresholds = TriggerThresholds(spread_widen_warning=0.05)
        detector = TriggerDetector(thresholds)

        entry = _make_watch_entry(last_spread=0.03)
        data = _make_cached_data(spread=0.06)

        triggers = detector.detect_triggers(entry, data)
        spread_triggers = [t for t in triggers if t.trigger_class == TriggerClass.LIQUIDITY]
        assert len(spread_triggers) == 1


# ============================================================================
# Edge Cases
# ============================================================================


class TestEdgeCases:
    """Edge case handling tests."""

    def test_zero_previous_price_no_crash(self, detector: TriggerDetector):
        """Zero previous price shouldn't cause division by zero."""
        entry = _make_watch_entry(last_price=0.0)
        data = _make_cached_data(mid_price=0.50)
        triggers = detector.detect_triggers(entry, data)
        # Should not crash, and no price trigger
        price_triggers = [t for t in triggers if t.trigger_class == TriggerClass.REPRICING]
        assert len(price_triggers) == 0

    def test_zero_previous_depth_no_crash(self, detector: TriggerDetector):
        """Zero previous depth shouldn't cause division by zero."""
        entry = _make_watch_entry(last_depth_top3=0.0)
        depth = {"bids": [{"price": 0.50, "size": 100}], "asks": [{"price": 0.52, "size": 100}]}
        data = _make_cached_data(depth_levels=depth)
        triggers = detector.detect_triggers(entry, data)
        # Should not crash

    def test_multiple_trigger_types_same_market(self, detector: TriggerDetector):
        """A single market can produce multiple trigger types in one scan."""
        entry = _make_watch_entry(
            last_price=0.50,
            last_spread=0.05,
            is_held_position=True,
        )
        # Big price drop + wide spread
        data = _make_cached_data(mid_price=0.40, spread=0.25)

        triggers = detector.detect_triggers(entry, data)
        classes = set(t.trigger_class for t in triggers)
        # Should have repricing, liquidity, and position stress
        assert TriggerClass.REPRICING in classes
        assert TriggerClass.LIQUIDITY in classes
        assert TriggerClass.POSITION_STRESS in classes

    def test_empty_depth_levels(self, detector: TriggerDetector):
        """Empty depth data should not crash."""
        entry = _make_watch_entry(last_depth_top3=500.0)
        data = _make_cached_data(depth_levels={"bids": [], "asks": []})
        triggers = detector.detect_triggers(entry, data)
        # Should not crash — depth trigger requires computable top3

    def test_compute_top3_depth_helper(self):
        """Top-3 depth computation helper should work correctly."""
        depth = {
            "bids": [
                {"price": 0.50, "size": 100},
                {"price": 0.49, "size": 200},
                {"price": 0.48, "size": 300},
                {"price": 0.47, "size": 400},  # 4th level, excluded
            ],
            "asks": [
                {"price": 0.52, "size": 150},
                {"price": 0.53, "size": 250},
                {"price": 0.54, "size": 350},
                {"price": 0.55, "size": 450},  # 4th level, excluded
            ],
        }
        result = TriggerDetector._compute_top3_depth(depth)
        # Top 3 bids: 100+200+300 = 600, Top 3 asks: 150+250+350 = 750
        assert result == 1350.0
