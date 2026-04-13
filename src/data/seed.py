"""Seed data for the Polymarket Trader database.

Populates:
- Base-rate reference data (historical resolution rates per market type)
- Calibration threshold registry defaults
- Default friction model parameters

Run via: python -m data.seed
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from data.database import get_session_factory, init_db
from data.models.calibration import CalibrationThresholdRegistry
from data.models.execution import FrictionModelParameters
from data.models.reference import BaseRateReference


# --- Base Rate References ---
# Default 50% when no historical data. More specific rates added as data accumulates.

BASE_RATE_REFERENCES = [
    # Politics
    {"market_type": "politics_election_winner", "category": "politics", "base_rate": 0.50,
     "confidence_level": "none", "source": "default", "sample_size": 0},
    {"market_type": "politics_legislation_passage", "category": "politics", "base_rate": 0.35,
     "confidence_level": "low", "source": "historical_us_congress", "sample_size": 10},
    {"market_type": "politics_appointment_confirmation", "category": "politics", "base_rate": 0.70,
     "confidence_level": "low", "source": "historical_us_senate", "sample_size": 8},
    {"market_type": "politics_general", "category": "politics", "base_rate": 0.50,
     "confidence_level": "none", "source": "default", "sample_size": 0},

    # Geopolitics
    {"market_type": "geopolitics_treaty_agreement", "category": "geopolitics", "base_rate": 0.30,
     "confidence_level": "low", "source": "historical_multilateral", "sample_size": 5},
    {"market_type": "geopolitics_sanctions", "category": "geopolitics", "base_rate": 0.50,
     "confidence_level": "none", "source": "default", "sample_size": 0},
    {"market_type": "geopolitics_general", "category": "geopolitics", "base_rate": 0.50,
     "confidence_level": "none", "source": "default", "sample_size": 0},

    # Technology
    {"market_type": "technology_product_launch", "category": "technology", "base_rate": 0.65,
     "confidence_level": "low", "source": "historical_tech_launches", "sample_size": 12},
    {"market_type": "technology_regulation", "category": "technology", "base_rate": 0.40,
     "confidence_level": "none", "source": "default", "sample_size": 0},
    {"market_type": "technology_general", "category": "technology", "base_rate": 0.50,
     "confidence_level": "none", "source": "default", "sample_size": 0},

    # Science & Health
    {"market_type": "science_health_drug_approval", "category": "science_health", "base_rate": 0.60,
     "confidence_level": "low", "source": "fda_historical", "sample_size": 15},
    {"market_type": "science_health_trial_outcome", "category": "science_health", "base_rate": 0.50,
     "confidence_level": "none", "source": "default", "sample_size": 0},
    {"market_type": "science_health_general", "category": "science_health", "base_rate": 0.50,
     "confidence_level": "none", "source": "default", "sample_size": 0},

    # Macro/Policy
    {"market_type": "macro_policy_rate_decision", "category": "macro_policy", "base_rate": 0.50,
     "confidence_level": "none", "source": "default", "sample_size": 0},
    {"market_type": "macro_policy_general", "category": "macro_policy", "base_rate": 0.50,
     "confidence_level": "none", "source": "default", "sample_size": 0},

    # Sports
    {"market_type": "sports_match_winner", "category": "sports", "base_rate": 0.50,
     "confidence_level": "none", "source": "default", "sample_size": 0},
    {"market_type": "sports_championship", "category": "sports", "base_rate": 0.50,
     "confidence_level": "none", "source": "default", "sample_size": 0},
    {"market_type": "sports_general", "category": "sports", "base_rate": 0.50,
     "confidence_level": "none", "source": "default", "sample_size": 0},
]


# --- Calibration Threshold Registry ---

CALIBRATION_THRESHOLDS = [
    {
        "threshold_name": "initial_calibration_correction",
        "segment_type": "overall",
        "min_trades": 20,
        "description": "Minimum resolved forecasts before applying calibration corrections.",
        "parameters": {"applies_to": "all_segments"},
    },
    {
        "threshold_name": "category_level_calibration",
        "segment_type": "category",
        "min_trades": 30,
        "description": "Category-level minimum for per-category calibration adjustments.",
        "parameters": {"applies_to": "individual_category"},
    },
    {
        "threshold_name": "horizon_bucket_calibration",
        "segment_type": "horizon",
        "min_trades": 25,
        "description": "Horizon-bucket minimum for time-horizon specific calibration.",
        "parameters": {"applies_to": "horizon_buckets"},
    },
    {
        "threshold_name": "sports_calibration",
        "segment_type": "category",
        "min_trades": 40,
        "description": "Sports category requires higher threshold due to Quality-Gated tier.",
        "parameters": {"applies_to": "sports_only", "quality_gated": True},
    },
    {
        "threshold_name": "size_penalty_reduction",
        "segment_type": "overall",
        "min_trades": 30,
        "description": "Minimum before reducing size penalties. Requires Brier improvement vs base rate.",
        "parameters": {"requires_brier_improvement": True},
    },
    {
        "threshold_name": "cross_category_pool_combined",
        "segment_type": "pool",
        "min_trades": 15,
        "description": "Minimum combined pool size for cross-category calibration pooling.",
        "parameters": {"penalty_factor": 0.30, "individual_segment_min": 5},
    },
    {
        "threshold_name": "viability_decision",
        "segment_type": "overall",
        "min_trades": 50,
        "description": "Minimum resolved forecasts for strategy viability decision at week 12.",
        "parameters": {"checkpoint_week": 12},
    },
]


# --- Default Friction Model Parameters ---

DEFAULT_FRICTION_PARAMS = {
    "spread_estimate": 0.03,
    "depth_assumption": 5000.0,
    "impact_coefficient": 0.001,
    "version": 1,
    "is_active": True,
    "trades_since_calibration": 0,
}


async def seed_database(database_url: str) -> None:
    """Seed the database with reference data.

    Idempotent: skips records that already exist.
    """
    await init_db(database_url)
    factory = get_session_factory()

    async with factory() as session:
        async with session.begin():
            await _seed_base_rates(session)
            await _seed_calibration_thresholds(session)
            await _seed_friction_params(session)

    print("Seed data loaded successfully.")


async def _seed_base_rates(session: AsyncSession) -> None:
    """Insert base rate references."""
    now = datetime.now(tz=UTC)
    for ref_data in BASE_RATE_REFERENCES:
        # Check if already exists
        from sqlalchemy import select
        stmt = select(BaseRateReference).where(
            BaseRateReference.market_type == ref_data["market_type"]
        )
        result = await session.execute(stmt)
        if result.scalar_one_or_none() is None:
            ref = BaseRateReference(
                **ref_data,
                last_updated_at=now,
            )
            session.add(ref)
    print(f"  Base rates: {len(BASE_RATE_REFERENCES)} entries checked.")


async def _seed_calibration_thresholds(session: AsyncSession) -> None:
    """Insert calibration threshold registry entries."""
    for thresh_data in CALIBRATION_THRESHOLDS:
        from sqlalchemy import select
        stmt = select(CalibrationThresholdRegistry).where(
            CalibrationThresholdRegistry.threshold_name == thresh_data["threshold_name"]
        )
        result = await session.execute(stmt)
        if result.scalar_one_or_none() is None:
            thresh = CalibrationThresholdRegistry(**thresh_data)
            session.add(thresh)
    print(f"  Calibration thresholds: {len(CALIBRATION_THRESHOLDS)} entries checked.")


async def _seed_friction_params(session: AsyncSession) -> None:
    """Insert default friction model parameters."""
    from sqlalchemy import select
    stmt = select(FrictionModelParameters).where(
        FrictionModelParameters.is_active.is_(True)
    )
    result = await session.execute(stmt)
    if result.scalar_one_or_none() is None:
        params = FrictionModelParameters(**DEFAULT_FRICTION_PARAMS)
        session.add(params)
    print("  Friction model: default parameters checked.")


if __name__ == "__main__":
    # Allow passing database URL as CLI arg or use default
    if len(sys.argv) > 1:
        db_url = sys.argv[1]
    else:
        db_url = "postgresql+asyncpg://polymarket:polymarket@localhost:5432/polymarket_trader"

    asyncio.run(seed_database(db_url))
