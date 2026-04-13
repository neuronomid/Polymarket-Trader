"""Tests for model philosophy and provider strategy constants."""

from core.constants import (
    CATEGORY_QUALITY_TIERS,
    COST_CLASS_RANGES,
    DETERMINISTIC_ONLY_COMPONENTS,
    MODEL_PRINCIPLES,
    POSITION_REVIEW_COST_PROFILE,
    PROVIDER_MODEL_MAP,
    TIER_COST_CLASS,
)
from core.enums import CostClass, ModelTier


def test_eleven_model_principles():
    assert len(MODEL_PRINCIPLES) == 11


def test_all_model_tiers_have_provider():
    for tier in ModelTier:
        assert tier in PROVIDER_MODEL_MAP


def test_tier_d_has_no_provider():
    assert PROVIDER_MODEL_MAP[ModelTier.D]["provider"] == "none"


def test_all_cost_classes_have_ranges():
    for cc in CostClass:
        assert cc in COST_CLASS_RANGES
        low, high = COST_CLASS_RANGES[cc]
        assert low <= high


def test_zero_cost_class_is_free():
    low, high = COST_CLASS_RANGES[CostClass.Z]
    assert low == 0.0
    assert high == 0.0


def test_tier_cost_class_mapping():
    assert TIER_COST_CLASS[ModelTier.A] == CostClass.H
    assert TIER_COST_CLASS[ModelTier.D] == CostClass.Z


def test_position_review_cost_profile_sums_to_one():
    total = sum(POSITION_REVIEW_COST_PROFILE.values())
    assert abs(total - 1.0) < 0.01


def test_deterministic_components_includes_key_systems():
    assert "risk_governor" in DETERMINISTIC_ONLY_COMPONENTS
    assert "cost_governor" in DETERMINISTIC_ONLY_COMPONENTS
    assert "execution_engine" in DETERMINISTIC_ONLY_COMPONENTS
    assert "trigger_scanner" in DETERMINISTIC_ONLY_COMPONENTS


def test_category_quality_tiers():
    assert CATEGORY_QUALITY_TIERS["sports"] == "quality_gated"
    assert CATEGORY_QUALITY_TIERS["politics"] == "standard"
    assert len(CATEGORY_QUALITY_TIERS) == 6
