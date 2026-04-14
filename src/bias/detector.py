"""Bias detection processor — all five statistical checks.

Fully deterministic (Tier D). Runs weekly, aligned with Performance Review.

Statistical checks performed:
1. Directional bias: arithmetic mean comparison
2. Confidence clustering: histogram computation
3. Anchoring: mean absolute difference computation
4. Narrative coherence over-weighting: correlation analysis
5. Base-rate neglect: statistical comparison

LLM must NOT audit its own reasoning biases — detection is statistical,
interpretation may be LLM-assisted via Performance Analyzer only after
statistical facts are established.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime

import structlog

from bias.types import (
    AnchoringResult,
    BaseRateNeglectResult,
    BiasAlertLevel,
    BiasAlertType,
    BiasAuditResult,
    BiasDetectionInput,
    BiasPatternAlert,
    BiasPatternType,
    ConfidenceClusteringResult,
    DirectionalBiasResult,
    ForecastDataPoint,
    NarrativeOverweightingResult,
)

_log = structlog.get_logger(component="bias_detector")

# --- Thresholds ---

DIRECTIONAL_SKEW_PP_THRESHOLD = 5.0  # flag if persistent > 5pp skew
PERSISTENCE_WEEKS_THRESHOLD = 3  # 3+ consecutive weeks = persistent
CONFIDENCE_CLUSTERING_PCT_THRESHOLD = 0.50  # > 50% in a 20pp band
CONFIDENCE_BAND_WIDTH_PP = 20.0  # 20 percentage-point band
ANCHORING_DIFF_PP_THRESHOLD = 3.0  # flag if avg abs diff < 3pp
MIN_SAMPLE_SIZE = 5  # minimum forecasts needed for meaningful analysis


class BiasDetector:
    """Statistical bias detection processor.

    Runs all five checks on a set of resolved forecasts and produces
    an audit result with pattern tracking and alert generation.

    Usage:
        detector = BiasDetector()
        result = detector.run_audit(input)
    """

    def run_audit(self, inp: BiasDetectionInput) -> BiasAuditResult:
        """Execute all five statistical bias checks.

        Args:
            inp: Detection input with forecasts and previous pattern state.

        Returns:
            Complete BiasAuditResult with check results, pattern tracking, and alerts.
        """
        forecasts = inp.forecasts
        sample_size = len(forecasts)

        result = BiasAuditResult(
            period_start=inp.period_start,
            period_end=inp.period_end,
            sample_size=sample_size,
        )

        if sample_size < MIN_SAMPLE_SIZE:
            _log.info(
                "bias_audit_skipped_insufficient_data",
                sample_size=sample_size,
                min_required=MIN_SAMPLE_SIZE,
            )
            return result

        # Run all five statistical checks
        result.directional = self._check_directional_bias(forecasts)
        result.confidence_clustering = self._check_confidence_clustering(forecasts)
        result.anchoring = self._check_anchoring(forecasts)
        result.narrative_overweighting = self._check_narrative_overweighting(forecasts)
        result.base_rate_neglect = self._check_base_rate_neglect(forecasts)

        # Aggregate
        detected_patterns: list[BiasPatternType] = []
        if result.directional.detected:
            detected_patterns.append(BiasPatternType.DIRECTIONAL)
        if result.confidence_clustering.detected:
            detected_patterns.append(BiasPatternType.CONFIDENCE_CLUSTERING)
        if result.anchoring.detected:
            detected_patterns.append(BiasPatternType.ANCHORING)
        if result.narrative_overweighting.detected:
            detected_patterns.append(BiasPatternType.NARRATIVE_OVERWEIGHTING)
        if result.base_rate_neglect.detected:
            detected_patterns.append(BiasPatternType.BASE_RATE_NEGLECT)

        result.any_bias_detected = len(detected_patterns) > 0
        result.detected_patterns = detected_patterns

        # Update pattern persistence and generate alerts
        result.pattern_weeks = self._update_pattern_persistence(
            detected_patterns, inp.previous_patterns
        )
        result.alerts = self._generate_alerts(
            detected_patterns, result.pattern_weeks, inp.previous_patterns
        )

        _log.info(
            "bias_audit_complete",
            sample_size=sample_size,
            any_detected=result.any_bias_detected,
            patterns=sorted(p.value for p in detected_patterns),
            alerts_count=len(result.alerts),
        )

        return result

    # --- Check 1: Directional Bias ---

    def _check_directional_bias(
        self, forecasts: list[ForecastDataPoint]
    ) -> DirectionalBiasResult:
        """Arithmetic mean comparison: system vs. market probability.

        Flag if persistent > 5pp skew.
        """
        n = len(forecasts)
        if n == 0:
            return DirectionalBiasResult()

        mean_sys = sum(f.system_probability for f in forecasts) / n
        mean_mkt = sum(f.market_implied_probability for f in forecasts) / n
        skew_pp = (mean_sys - mean_mkt) * 100.0  # convert to percentage points

        detected = abs(skew_pp) > DIRECTIONAL_SKEW_PP_THRESHOLD
        direction = None
        if detected:
            direction = "bullish" if skew_pp > 0 else "bearish"

        return DirectionalBiasResult(
            detected=detected,
            mean_system_probability=round(mean_sys, 6),
            mean_market_probability=round(mean_mkt, 6),
            skew_pp=round(skew_pp, 4),
            sample_size=n,
            direction=direction,
        )

    # --- Check 2: Confidence Clustering ---

    def _check_confidence_clustering(
        self, forecasts: list[ForecastDataPoint]
    ) -> ConfidenceClusteringResult:
        """Histogram computation — flag if > 50% of forecasts within a 20pp band."""
        n = len(forecasts)
        if n == 0:
            return ConfidenceClusteringResult()

        probs = [f.system_probability for f in forecasts]

        # Slide a 20pp (0.20) window across [0, 1] in 1pp (0.01) steps
        band_width = CONFIDENCE_BAND_WIDTH_PP / 100.0
        best_count = 0
        best_start = 0.0
        best_end = band_width

        step = 0.01
        current = 0.0
        while current + band_width <= 1.0 + 1e-9:
            band_start = current
            band_end = min(current + band_width, 1.0)
            count = sum(1 for p in probs if band_start <= p <= band_end)
            if count > best_count:
                best_count = count
                best_start = band_start
                best_end = band_end
            current += step

        pct_in_band = best_count / n if n > 0 else 0.0
        detected = pct_in_band > CONFIDENCE_CLUSTERING_PCT_THRESHOLD

        return ConfidenceClusteringResult(
            detected=detected,
            peak_band_start=round(best_start, 4),
            peak_band_end=round(best_end, 4),
            pct_in_peak_band=round(pct_in_band, 4),
            band_width_pp=CONFIDENCE_BAND_WIDTH_PP,
            sample_size=n,
        )

    # --- Check 3: Anchoring ---

    def _check_anchoring(
        self, forecasts: list[ForecastDataPoint]
    ) -> AnchoringResult:
        """Mean absolute difference between system and market.

        Flag if avg absolute difference consistently < 3pp — system
        may be anchoring to market prices rather than forming independent views.
        """
        n = len(forecasts)
        if n == 0:
            return AnchoringResult()

        abs_diffs = [
            abs(f.system_probability - f.market_implied_probability) for f in forecasts
        ]
        mean_diff_pp = (sum(abs_diffs) / n) * 100.0  # convert to pp

        detected = mean_diff_pp < ANCHORING_DIFF_PP_THRESHOLD

        return AnchoringResult(
            detected=detected,
            mean_abs_diff_pp=round(mean_diff_pp, 4),
            threshold_pp=ANCHORING_DIFF_PP_THRESHOLD,
            sample_size=n,
        )

    # --- Check 4: Narrative Over-Weighting ---

    def _check_narrative_overweighting(
        self, forecasts: list[ForecastDataPoint]
    ) -> NarrativeOverweightingResult:
        """Correlation analysis: evidence quality vs. forecast accuracy.

        Check if high-narrative-quality forecasts are less accurate than
        weak-narrative ones. If so, system may be over-weighting compelling
        narratives at the expense of actual predictive power.
        """
        # Filter to forecasts with both evidence quality and accuracy data
        valid = [
            f for f in forecasts
            if f.evidence_quality_score is not None and f.forecast_accuracy is not None
        ]

        n = len(valid)
        if n < MIN_SAMPLE_SIZE:
            return NarrativeOverweightingResult(sample_size=n)

        eq_scores = [f.evidence_quality_score for f in valid]
        accuracies = [f.forecast_accuracy for f in valid]

        # Compute Pearson correlation
        corr = self._pearson_correlation(eq_scores, accuracies)

        # Split into high/low quality groups by median
        sorted_by_eq = sorted(valid, key=lambda f: f.evidence_quality_score or 0)
        mid = len(sorted_by_eq) // 2
        low_group = sorted_by_eq[:mid] if mid > 0 else sorted_by_eq
        high_group = sorted_by_eq[mid:] if mid > 0 else []

        low_acc = (
            sum(f.forecast_accuracy for f in low_group) / len(low_group)
            if low_group else None
        )
        high_acc = (
            sum(f.forecast_accuracy for f in high_group) / len(high_group)
            if high_group else None
        )

        # Detected if higher evidence-quality scores correlate with larger
        # forecast errors and the high-quality group is materially less accurate.
        detected = False
        if corr is not None and corr > 0.1:
            if high_acc is not None and low_acc is not None and high_acc > low_acc:
                # high_acc = high |system - outcome| = worse accuracy
                detected = True

        return NarrativeOverweightingResult(
            detected=detected,
            correlation=round(corr, 6) if corr is not None else None,
            high_quality_accuracy=round(high_acc, 6) if high_acc is not None else None,
            low_quality_accuracy=round(low_acc, 6) if low_acc is not None else None,
            sample_size=n,
        )

    # --- Check 5: Base-Rate Neglect ---

    def _check_base_rate_neglect(
        self, forecasts: list[ForecastDataPoint]
    ) -> BaseRateNeglectResult:
        """Statistical comparison of system estimates vs. base rates.

        Check if deviations are systematically directional.
        """
        valid = [f for f in forecasts if f.base_rate_probability is not None]
        n = len(valid)

        if n < MIN_SAMPLE_SIZE:
            return BaseRateNeglectResult(sample_size=n)

        deviations = [
            f.system_probability - f.base_rate_probability
            for f in valid
        ]
        mean_deviation = sum(deviations) / n

        # Check if deviations are systematically directional
        # (most deviations in the same direction)
        positive_count = sum(1 for d in deviations if d > 0)
        negative_count = sum(1 for d in deviations if d < 0)
        total_directional = positive_count + negative_count

        systematically_directional = False
        if total_directional > 0:
            dominant_fraction = max(positive_count, negative_count) / total_directional
            # If 70%+ of deviations are in the same direction, flag it
            systematically_directional = dominant_fraction >= 0.70

        direction = None
        if systematically_directional:
            direction = "above" if positive_count > negative_count else "below"

        detected = systematically_directional and abs(mean_deviation) > 0.02

        return BaseRateNeglectResult(
            detected=detected,
            mean_deviation=round(mean_deviation, 6),
            deviation_direction=direction,
            systematically_directional=systematically_directional,
            sample_size=n,
        )

    # --- Pattern Persistence ---

    def _update_pattern_persistence(
        self,
        detected_patterns: list[BiasPatternType],
        previous_weeks: dict[str, int],
    ) -> dict[str, int]:
        """Update consecutive weeks count for each pattern type.

        Detected patterns: increment count (or start at 1).
        Not detected patterns: reset to 0.
        """
        updated: dict[str, int] = {}
        all_types = list(BiasPatternType)

        for pt in all_types:
            key = pt.value
            prev = previous_weeks.get(key, 0)
            if pt in detected_patterns:
                updated[key] = prev + 1
            else:
                updated[key] = 0

        return updated

    def _generate_alerts(
        self,
        detected_patterns: list[BiasPatternType],
        current_weeks: dict[str, int],
        previous_weeks: dict[str, int],
    ) -> list[BiasPatternAlert]:
        """Generate bias pattern alerts.

        - DETECTED: newly detected pattern (was 0, now 1)
        - PERSISTENT: pattern present for 3+ consecutive weeks
        - RESOLVED: previously persistent pattern, now gone
        """
        alerts: list[BiasPatternAlert] = []

        for pt in BiasPatternType:
            key = pt.value
            curr = current_weeks.get(key, 0)
            prev = previous_weeks.get(key, 0)

            if curr == 1 and prev == 0:
                # Newly detected
                alerts.append(
                    BiasPatternAlert(
                        alert_type=BiasAlertType.BIAS_PATTERN_DETECTED,
                        pattern_type=pt,
                        consecutive_weeks=curr,
                        details={"status": "new_detection"},
                    )
                )
            elif curr >= PERSISTENCE_WEEKS_THRESHOLD and prev < PERSISTENCE_WEEKS_THRESHOLD:
                # Became persistent
                alerts.append(
                    BiasPatternAlert(
                        alert_type=BiasAlertType.BIAS_PATTERN_PERSISTENT,
                        pattern_type=pt,
                        consecutive_weeks=curr,
                        details={"status": "became_persistent"},
                    )
                )
            elif curr == 0 and prev >= PERSISTENCE_WEEKS_THRESHOLD:
                # Previously persistent, now resolved
                alerts.append(
                    BiasPatternAlert(
                        alert_type=BiasAlertType.BIAS_PATTERN_RESOLVED,
                        pattern_type=pt,
                        consecutive_weeks=0,
                        details={
                            "status": "resolved",
                            "was_persistent_for_weeks": prev,
                        },
                    )
                )

        if alerts:
            _log.info(
                "bias_alerts_generated",
                alert_count=len(alerts),
                alert_types=[a.alert_type.value for a in alerts],
            )

        return alerts

    # --- Statistical Helpers ---

    @staticmethod
    def _pearson_correlation(
        xs: list[float | None], ys: list[float | None]
    ) -> float | None:
        """Compute Pearson correlation coefficient between two sequences.

        Returns None if computation is not possible (insufficient data or zero variance).
        """
        pairs = [
            (x, y)
            for x, y in zip(xs, ys)
            if x is not None and y is not None
        ]
        n = len(pairs)
        if n < 3:
            return None

        xs_clean = [p[0] for p in pairs]
        ys_clean = [p[1] for p in pairs]

        mean_x = sum(xs_clean) / n
        mean_y = sum(ys_clean) / n

        cov = sum((x - mean_x) * (y - mean_y) for x, y in pairs) / n
        std_x = math.sqrt(sum((x - mean_x) ** 2 for x in xs_clean) / n)
        std_y = math.sqrt(sum((y - mean_y) ** 2 for y in ys_clean) / n)

        if std_x < 1e-10 or std_y < 1e-10:
            return None

        return cov / (std_x * std_y)
