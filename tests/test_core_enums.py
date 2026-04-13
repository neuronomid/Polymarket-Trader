"""Tests for core enums — verify all enums are importable and have expected members."""

from core.enums import (
    CalibrationRegime,
    Category,
    CategoryQualityTier,
    CostClass,
    DrawdownLevel,
    EligibilityOutcome,
    ExcludedCategory,
    ExitClass,
    ModelTier,
    NotificationSeverity,
    NotificationType,
    OperatorMode,
    ReviewTier,
    RiskApproval,
    TriggerClass,
    TriggerLevel,
)


def test_category_has_six_members():
    assert len(Category) == 6
    assert Category.POLITICS.value == "politics"
    assert Category.SPORTS.value == "sports"


def test_excluded_category_has_four_members():
    assert len(ExcludedCategory) == 4
    expected = {"news", "culture", "crypto", "weather"}
    assert {e.value for e in ExcludedCategory} == expected


def test_no_overlap_between_allowed_and_excluded():
    allowed_values = {c.value for c in Category}
    excluded_values = {c.value for c in ExcludedCategory}
    assert allowed_values.isdisjoint(excluded_values)


def test_eligibility_outcome_members():
    assert len(EligibilityOutcome) == 4
    assert EligibilityOutcome.REJECT.value == "reject"
    assert EligibilityOutcome.INVESTIGATE_NOW.value == "investigate_now"


def test_trigger_class_has_seven_members():
    assert len(TriggerClass) == 7


def test_trigger_level_ordering():
    levels = [TriggerLevel.A, TriggerLevel.B, TriggerLevel.C, TriggerLevel.D]
    assert [l.value for l in levels] == ["A", "B", "C", "D"]


def test_exit_class_has_eleven_members():
    assert len(ExitClass) == 11


def test_operator_mode_progressive_rollout():
    """Paper → Shadow → LiveSmall → LiveStandard are the main progression."""
    assert OperatorMode.PAPER.value == "paper"
    assert OperatorMode.SHADOW.value == "shadow"
    assert OperatorMode.LIVE_SMALL.value == "live_small"
    assert OperatorMode.LIVE_STANDARD.value == "live_standard"


def test_operator_mode_has_eight_members():
    assert len(OperatorMode) == 8


def test_drawdown_ladder_has_five_levels():
    assert len(DrawdownLevel) == 5


def test_model_tier_maps_to_cost_class():
    """Each model tier has a corresponding cost class."""
    assert len(ModelTier) == 4
    assert len(CostClass) == 4


def test_risk_approval_members():
    assert len(RiskApproval) == 6


def test_review_tier_members():
    assert len(ReviewTier) == 3


def test_calibration_regime_members():
    assert len(CalibrationRegime) == 3


def test_notification_severity_members():
    assert len(NotificationSeverity) == 3


def test_notification_type_members():
    assert len(NotificationType) == 8


def test_category_quality_tier_members():
    assert len(CategoryQualityTier) == 2
    assert CategoryQualityTier.STANDARD.value == "standard"
    assert CategoryQualityTier.QUALITY_GATED.value == "quality_gated"


def test_all_enums_are_string_enums():
    """All enums should be str enums for JSON serialization."""
    for enum_cls in [
        Category, ExcludedCategory, EligibilityOutcome, TriggerClass,
        TriggerLevel, RiskApproval, ExitClass, OperatorMode, DrawdownLevel,
        ModelTier, CostClass, CalibrationRegime, ReviewTier,
        NotificationSeverity, NotificationType, CategoryQualityTier,
    ]:
        for member in enum_cls:
            assert isinstance(member.value, str), f"{enum_cls.__name__}.{member.name} is not str"
