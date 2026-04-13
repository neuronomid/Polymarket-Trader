"""Risk, cost, calibration, and supporting entity repositories."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Sequence

from sqlalchemy import select

from data.models.risk import RiskSnapshot, RuleDecision
from data.models.cost import (
    CostGovernorDecision,
    CostOfSelectivityRecord,
    CostSnapshot,
    CumulativeReviewCostRecord,
    PreRunCostEstimate,
)
from data.models.calibration import (
    CalibrationAccumulationProjection,
    CalibrationRecord,
    CalibrationThresholdRegistry,
    CategoryPerformanceLedgerEntry,
    ShadowForecastRecord,
)
from data.models.reference import BaseRateReference
from data.repositories import BaseRepository


class RiskSnapshotRepository(BaseRepository[RiskSnapshot]):
    model = RiskSnapshot

    async def get_by_position(self, position_id: uuid.UUID) -> Sequence[RiskSnapshot]:
        stmt = (
            select(RiskSnapshot)
            .where(RiskSnapshot.position_id == position_id)
            .order_by(RiskSnapshot.snapshot_at.desc())
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_latest(self) -> RiskSnapshot | None:
        stmt = select(RiskSnapshot).order_by(RiskSnapshot.snapshot_at.desc()).limit(1)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()


class CostSnapshotRepository(BaseRepository[CostSnapshot]):
    model = CostSnapshot

    async def get_by_workflow_run(
        self, workflow_run_id: uuid.UUID
    ) -> Sequence[CostSnapshot]:
        stmt = select(CostSnapshot).where(
            CostSnapshot.workflow_run_id == workflow_run_id
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_daily_total(self, date: datetime) -> float:
        """Sum actual cost for a day."""
        from sqlalchemy import func

        start = date.replace(hour=0, minute=0, second=0, microsecond=0)
        end = date.replace(hour=23, minute=59, second=59, microsecond=999999)
        stmt = select(func.coalesce(func.sum(CostSnapshot.actual_cost_usd), 0.0)).where(
            CostSnapshot.recorded_at.between(start, end)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one()


class CalibrationRecordRepository(BaseRepository[CalibrationRecord]):
    model = CalibrationRecord

    async def get_by_segment(
        self, segment_type: str, segment_label: str
    ) -> CalibrationRecord | None:
        stmt = (
            select(CalibrationRecord)
            .where(CalibrationRecord.segment_type == segment_type)
            .where(CalibrationRecord.segment_label == segment_label)
            .order_by(CalibrationRecord.updated_at_cal.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_all_segments(self) -> Sequence[CalibrationRecord]:
        stmt = select(CalibrationRecord).order_by(
            CalibrationRecord.segment_type, CalibrationRecord.segment_label
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()


class ShadowForecastRepository(BaseRepository[ShadowForecastRecord]):
    model = ShadowForecastRecord

    async def get_unresolved(self) -> Sequence[ShadowForecastRecord]:
        stmt = select(ShadowForecastRecord).where(
            ShadowForecastRecord.is_resolved.is_(False)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_resolved_by_category(
        self, category: str
    ) -> Sequence[ShadowForecastRecord]:
        stmt = (
            select(ShadowForecastRecord)
            .where(ShadowForecastRecord.category == category)
            .where(ShadowForecastRecord.is_resolved.is_(True))
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()


class CategoryPerformanceLedgerRepository(
    BaseRepository[CategoryPerformanceLedgerEntry]
):
    model = CategoryPerformanceLedgerEntry

    async def get_latest_by_category(
        self, category: str
    ) -> CategoryPerformanceLedgerEntry | None:
        stmt = (
            select(CategoryPerformanceLedgerEntry)
            .where(CategoryPerformanceLedgerEntry.category == category)
            .order_by(CategoryPerformanceLedgerEntry.period_end.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()


class BaseRateReferenceRepository(BaseRepository[BaseRateReference]):
    model = BaseRateReference

    async def get_by_market_type(self, market_type: str) -> BaseRateReference | None:
        stmt = select(BaseRateReference).where(
            BaseRateReference.market_type == market_type
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_all_rates(self) -> Sequence[BaseRateReference]:
        stmt = select(BaseRateReference).order_by(BaseRateReference.category)
        result = await self.session.execute(stmt)
        return result.scalars().all()


class CalibrationThresholdRegistryRepository(
    BaseRepository[CalibrationThresholdRegistry]
):
    model = CalibrationThresholdRegistry

    async def get_by_name(self, name: str) -> CalibrationThresholdRegistry | None:
        stmt = select(CalibrationThresholdRegistry).where(
            CalibrationThresholdRegistry.threshold_name == name
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_all_thresholds(self) -> Sequence[CalibrationThresholdRegistry]:
        stmt = select(CalibrationThresholdRegistry).order_by(
            CalibrationThresholdRegistry.threshold_name
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()
