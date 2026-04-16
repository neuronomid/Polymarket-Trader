"""Deterministic trigger detection engine.

Evaluates market data changes to identify actionable trigger signals.
All detection is Tier D (deterministic) — no LLM in the hot path.

Trigger Classes:
  - Discovery: new eligible market with interesting price characteristics
  - Repricing: significant price move on watched market
  - Liquidity: spread widening, depth change, or liquidity event
  - PositionStress: held position experiencing adverse movement
  - ProfitProtection: held position with favorable move (lock-in opportunity)
  - CatalystWindow: approaching a known catalyst event
  - Operator: manual trigger or system-level event
"""

from __future__ import annotations

from datetime import UTC, datetime

from core.enums import TriggerClass, TriggerLevel
from market_data.types import CachedMarketData
from scanner.types import MarketWatchEntry, TriggerEvent, TriggerThresholds

_ENTRY_EXTREME_PRICE_FLOOR = 0.04
_ENTRY_EXTREME_PRICE_CEILING = 0.96


class TriggerDetector:
    """Deterministic trigger detection for market data changes.

    Compares current market data against previous state and thresholds
    to produce typed trigger events. Zero LLM involvement.
    """

    def __init__(self, thresholds: TriggerThresholds | None = None) -> None:
        self._thresholds = thresholds or TriggerThresholds()

    def detect_triggers(
        self,
        watch_entry: MarketWatchEntry,
        current_data: CachedMarketData,
    ) -> list[TriggerEvent]:
        """Run all trigger detection rules against current market data.

        Args:
            watch_entry: The market being watched (with previous state).
            current_data: Fresh market data from the latest poll.

        Returns:
            List of trigger events detected (may be empty).
        """
        triggers: list[TriggerEvent] = []

        snapshot = current_data.snapshot
        source = current_data.source.value
        current_price = snapshot.mid_price

        # --- Price move detection ---
        price_trigger = self._check_price_move(watch_entry, current_price, source)
        if price_trigger:
            triggers.append(price_trigger)

        # --- Spread detection ---
        spread_trigger = self._check_spread_change(
            watch_entry,
            snapshot.spread,
            current_price,
            source,
        )
        if spread_trigger:
            triggers.append(spread_trigger)

        # --- Depth change detection ---
        depth_trigger = self._check_depth_change(
            watch_entry,
            snapshot.depth_levels,
            current_price,
            source,
        )
        if depth_trigger:
            triggers.append(depth_trigger)

        # --- Position-specific triggers ---
        if watch_entry.is_held_position:
            position_triggers = self._check_position_triggers(
                watch_entry, snapshot.mid_price, source
            )
            triggers.extend(position_triggers)

        # --- Catalyst window ---
        catalyst_trigger = self._check_catalyst_window(watch_entry, source)
        if catalyst_trigger:
            triggers.append(catalyst_trigger)

        # --- Market status change ---
        status_trigger = self._check_market_status(
            watch_entry, snapshot.market_status, source
        )
        if status_trigger:
            triggers.append(status_trigger)

        return triggers

    def _check_price_move(
        self,
        entry: MarketWatchEntry,
        current_price: float | None,
        source: str,
    ) -> TriggerEvent | None:
        """Detect significant price movements."""
        if current_price is None or entry.last_price is None:
            return None

        if entry.last_price == 0:
            return None

        if self._is_extreme_entry_market(entry, current_price):
            return None

        change_pct = abs(current_price - entry.last_price) / entry.last_price
        thresholds = self._thresholds

        if change_pct < thresholds.price_move_level_a:
            return None

        # Classify the level based on magnitude
        if change_pct >= thresholds.price_move_level_d:
            level = TriggerLevel.D
            trigger_class = TriggerClass.REPRICING
        elif change_pct >= thresholds.price_move_level_c:
            level = TriggerLevel.C
            trigger_class = TriggerClass.REPRICING
        elif change_pct >= thresholds.price_move_level_b:
            level = TriggerLevel.B
            trigger_class = TriggerClass.REPRICING
        else:
            level = TriggerLevel.A
            trigger_class = TriggerClass.REPRICING

        direction = "up" if current_price > entry.last_price else "down"

        return TriggerEvent(
            market_id=entry.market_id,
            token_id=entry.token_id,
            trigger_class=trigger_class,
            trigger_level=level,
            price=current_price,
            spread=entry.last_spread,
            previous_value=entry.last_price,
            current_value=current_price,
            change_pct=change_pct,
            reason=(
                f"Price moved {direction} {change_pct:.1%} "
                f"({entry.last_price:.4f} → {current_price:.4f})"
            ),
            data_source=source,
        )

    def _check_spread_change(
        self,
        entry: MarketWatchEntry,
        current_spread: float | None,
        current_price: float | None,
        source: str,
    ) -> TriggerEvent | None:
        """Detect spread widening or narrowing past limits."""
        if current_spread is None:
            return None

        if self._is_extreme_entry_market(entry, current_price):
            return None

        thresholds = self._thresholds

        # Spread widening — liquidity concern
        if current_spread >= thresholds.spread_widen_critical:
            return TriggerEvent(
                market_id=entry.market_id,
                token_id=entry.token_id,
                trigger_class=TriggerClass.LIQUIDITY,
                trigger_level=TriggerLevel.C,
                price=entry.last_price,
                spread=current_spread,
                previous_value=entry.last_spread,
                current_value=current_spread,
                reason=f"Spread critically wide: {current_spread:.4f} (threshold: {thresholds.spread_widen_critical:.4f})",
                data_source=source,
            )

        if current_spread >= thresholds.spread_widen_warning:
            return TriggerEvent(
                market_id=entry.market_id,
                token_id=entry.token_id,
                trigger_class=TriggerClass.LIQUIDITY,
                trigger_level=TriggerLevel.B,
                price=entry.last_price,
                spread=current_spread,
                previous_value=entry.last_spread,
                current_value=current_spread,
                reason=f"Spread widened to warning: {current_spread:.4f}",
                data_source=source,
            )

        # Spread narrowing — potential opportunity
        if (
            current_spread <= thresholds.spread_narrow_opportunity
            and entry.last_spread is not None
            and entry.last_spread > thresholds.spread_narrow_opportunity
        ):
            return TriggerEvent(
                market_id=entry.market_id,
                token_id=entry.token_id,
                trigger_class=TriggerClass.DISCOVERY,
                trigger_level=TriggerLevel.A,
                price=entry.last_price,
                spread=current_spread,
                previous_value=entry.last_spread,
                current_value=current_spread,
                reason=f"Spread narrowed to opportunity level: {current_spread:.4f}",
                data_source=source,
            )

        return None

    def _check_depth_change(
        self,
        entry: MarketWatchEntry,
        current_depth_levels: dict | None,
        current_price: float | None,
        source: str,
    ) -> TriggerEvent | None:
        """Detect sudden depth changes at top levels."""
        if current_depth_levels is None or entry.last_depth_top3 is None:
            return None

        if self._is_extreme_entry_market(entry, current_price):
            return None

        # Compute current top-3 depth
        current_top3 = self._compute_top3_depth(current_depth_levels)
        if current_top3 is None or current_top3 == 0:
            return None

        if entry.last_depth_top3 == 0:
            return None

        change_ratio = abs(current_top3 - entry.last_depth_top3) / entry.last_depth_top3
        thresholds = self._thresholds

        if change_ratio < thresholds.depth_change_warning:
            return None

        is_decrease = current_top3 < entry.last_depth_top3

        if change_ratio >= thresholds.depth_change_critical:
            level = TriggerLevel.C if is_decrease else TriggerLevel.B
        else:
            level = TriggerLevel.B if is_decrease else TriggerLevel.A

        return TriggerEvent(
            market_id=entry.market_id,
            token_id=entry.token_id,
            trigger_class=TriggerClass.LIQUIDITY,
            trigger_level=level,
            price=entry.last_price,
            spread=entry.last_spread,
            depth_snapshot=current_depth_levels,
            previous_value=entry.last_depth_top3,
            current_value=current_top3,
            change_pct=change_ratio,
            reason=(
                f"Depth {'decreased' if is_decrease else 'increased'} {change_ratio:.1%} "
                f"(top3: {entry.last_depth_top3:.2f} → {current_top3:.2f})"
            ),
            data_source=source,
        )

    def _check_position_triggers(
        self,
        entry: MarketWatchEntry,
        current_price: float | None,
        source: str,
    ) -> list[TriggerEvent]:
        """Detect triggers specific to held positions.

        Checks for adverse and favorable moves that may require
        position review or profit protection.
        """
        triggers: list[TriggerEvent] = []

        if current_price is None or entry.last_price is None:
            return triggers

        if entry.last_price == 0:
            return triggers

        change_pct = (current_price - entry.last_price) / entry.last_price
        thresholds = self._thresholds

        # Adverse move (price moving against position)
        if change_pct < 0:
            abs_change = abs(change_pct)
            if abs_change >= thresholds.position_adverse_move_d:
                triggers.append(
                    TriggerEvent(
                        market_id=entry.market_id,
                        token_id=entry.token_id,
                        trigger_class=TriggerClass.POSITION_STRESS,
                        trigger_level=TriggerLevel.D,
                        price=current_price,
                        previous_value=entry.last_price,
                        current_value=current_price,
                        change_pct=change_pct,
                        reason=f"Sharp adverse move: {change_pct:.1%} (D-level intervention required)",
                        data_source=source,
                        escalation_status="immediate_risk_intervention",
                    )
                )
            elif abs_change >= thresholds.position_adverse_move_c:
                triggers.append(
                    TriggerEvent(
                        market_id=entry.market_id,
                        token_id=entry.token_id,
                        trigger_class=TriggerClass.POSITION_STRESS,
                        trigger_level=TriggerLevel.C,
                        price=current_price,
                        previous_value=entry.last_price,
                        current_value=current_price,
                        change_pct=change_pct,
                        reason=f"Significant adverse move: {change_pct:.1%} (full review needed)",
                        data_source=source,
                    )
                )
            elif abs_change >= thresholds.position_adverse_move_b:
                triggers.append(
                    TriggerEvent(
                        market_id=entry.market_id,
                        token_id=entry.token_id,
                        trigger_class=TriggerClass.POSITION_STRESS,
                        trigger_level=TriggerLevel.B,
                        price=current_price,
                        previous_value=entry.last_price,
                        current_value=current_price,
                        change_pct=change_pct,
                        reason=f"Moderate adverse move: {change_pct:.1%}",
                        data_source=source,
                    )
                )

        # Favorable move (profit protection opportunity)
        elif change_pct > 0:
            if change_pct >= thresholds.position_favorable_move_c:
                triggers.append(
                    TriggerEvent(
                        market_id=entry.market_id,
                        token_id=entry.token_id,
                        trigger_class=TriggerClass.PROFIT_PROTECTION,
                        trigger_level=TriggerLevel.C,
                        price=current_price,
                        previous_value=entry.last_price,
                        current_value=current_price,
                        change_pct=change_pct,
                        reason=f"Large favorable move: +{change_pct:.1%} (profit protection review)",
                        data_source=source,
                    )
                )
            elif change_pct >= thresholds.position_favorable_move_b:
                triggers.append(
                    TriggerEvent(
                        market_id=entry.market_id,
                        token_id=entry.token_id,
                        trigger_class=TriggerClass.PROFIT_PROTECTION,
                        trigger_level=TriggerLevel.B,
                        price=current_price,
                        previous_value=entry.last_price,
                        current_value=current_price,
                        change_pct=change_pct,
                        reason=f"Favorable move: +{change_pct:.1%} (lightweight review)",
                        data_source=source,
                    )
                )

        return triggers

    def _is_extreme_entry_market(
        self,
        entry: MarketWatchEntry,
        current_price: float | None,
    ) -> bool:
        """Skip entry-style triggers for unheld markets near certainty.

        The workflow layer rejects new candidates below 4% or above 96%
        because those prices are too extreme to treat as fresh entry
        opportunities. Mirror that rule in the scanner so tiny absolute moves
        on penny-longshots do not get surfaced as C/D opportunities.
        """
        if entry.is_held_position:
            return False

        reference_price = (
            current_price
            if current_price is not None
            else entry.last_price
        )
        if reference_price is None:
            return False
        return (
            reference_price < _ENTRY_EXTREME_PRICE_FLOOR
            or reference_price > _ENTRY_EXTREME_PRICE_CEILING
        )

    def _check_catalyst_window(
        self,
        entry: MarketWatchEntry,
        source: str,
    ) -> TriggerEvent | None:
        """Detect approaching catalyst events."""
        if not entry.catalyst_dates:
            return None

        now = datetime.now(tz=UTC)
        thresholds = self._thresholds

        for catalyst_date in entry.catalyst_dates:
            if catalyst_date <= now:
                continue

            hours_until = (catalyst_date - now).total_seconds() / 3600.0

            if hours_until <= thresholds.catalyst_imminent_hours:
                return TriggerEvent(
                    market_id=entry.market_id,
                    token_id=entry.token_id,
                    trigger_class=TriggerClass.CATALYST_WINDOW,
                    trigger_level=TriggerLevel.C,
                    price=entry.last_price,
                    reason=f"Catalyst imminent in {hours_until:.1f}h (threshold: {thresholds.catalyst_imminent_hours}h)",
                    data_source=source,
                )

            if hours_until <= thresholds.catalyst_window_hours:
                return TriggerEvent(
                    market_id=entry.market_id,
                    token_id=entry.token_id,
                    trigger_class=TriggerClass.CATALYST_WINDOW,
                    trigger_level=TriggerLevel.B,
                    price=entry.last_price,
                    reason=f"Catalyst approaching in {hours_until:.1f}h (threshold: {thresholds.catalyst_window_hours}h)",
                    data_source=source,
                )

        return None

    def _check_market_status(
        self,
        entry: MarketWatchEntry,
        current_status: str | None,
        source: str,
    ) -> TriggerEvent | None:
        """Detect market status changes (halted, resolved, etc.)."""
        if current_status is None:
            return None

        # Status changes that indicate resolution or halt
        critical_statuses = {"resolved", "halted", "closed", "paused"}
        if current_status.lower() in critical_statuses:
            level = (
                TriggerLevel.D
                if entry.is_held_position
                else TriggerLevel.C
            )
            return TriggerEvent(
                market_id=entry.market_id,
                token_id=entry.token_id,
                trigger_class=TriggerClass.REPRICING,
                trigger_level=level,
                price=entry.last_price,
                reason=f"Market status changed to: {current_status}",
                data_source=source,
                escalation_status="status_change" if not entry.is_held_position else "position_status_change",
            )

        return None

    @staticmethod
    def _compute_top3_depth(depth_levels: dict) -> float | None:
        """Compute total size at top 3 levels from a depth snapshot."""
        total = 0.0
        for side in ("bids", "asks"):
            levels = depth_levels.get(side, [])
            for level in levels[:3]:
                if isinstance(level, dict):
                    total += float(level.get("size", 0))
        return total if total > 0 else None
