"""Data persistence layer — models, repositories, and database management.

All SQLAlchemy models are imported here so that Base.metadata contains
complete schema information required by Alembic migrations.
"""

from data.base import Base, TimestampMixin
from data.database import close_db, get_engine, get_session, get_session_factory, init_db

# Import all models so they register with Base.metadata
from data.models import Market, Order, Position, Trade  # noqa: F401
from data.models.bias import BiasAuditReport, BiasPatternRecord  # noqa: F401
from data.models.calibration import (  # noqa: F401
    CalibrationAccumulationProjection,
    CalibrationRecord,
    CalibrationSegment,
    CalibrationThresholdRegistry,
    CategoryPerformanceLedgerEntry,
    ShadowForecastRecord,
)
from data.models.correlation import CorrelationGroup, EventCluster  # noqa: F401
from data.models.cost import (  # noqa: F401
    CostGovernorDecision,
    CostOfSelectivityRecord,
    CostSnapshot,
    CumulativeReviewCostRecord,
    PreRunCostEstimate,
)
from data.models.execution import (  # noqa: F401
    EntryImpactEstimate,
    FrictionModelParameters,
    RealizedSlippageRecord,
)
from data.models.logging import Alert, JournalEntry, StructuredLogEntry  # noqa: F401
from data.models.notification import (  # noqa: F401
    NotificationDeliveryRecord,
    NotificationEvent,
)
from data.models.operator import (  # noqa: F401
    OperatorAbsenceEvent,
    OperatorInteractionEvent,
)
from data.models.reference import (  # noqa: F401
    BaseRateReference,
    MarketImpliedProbabilitySnapshot,
    MarketQualitySnapshot,
    PolicyUpdateRecommendation,
    ShadowVsMarketComparisonRecord,
    SystemHealthSnapshot,
)
from data.models.resolution import (  # noqa: F401
    ResolutionParseResult,
    SportsQualityGateResult,
)
from data.models.risk import RiskSnapshot, RuleDecision  # noqa: F401
from data.models.scanner import (  # noqa: F401
    CLOBCacheEntry,
    ScannerDataSnapshot,
    ScannerHealthEvent,
)
from data.models.thesis import NetEdgeEstimate, ThesisCard  # noqa: F401
from data.models.viability import (  # noqa: F401
    LifetimeBudgetStatus,
    PatienceBudgetStatus,
    StrategyViabilityCheckpoint,
)
from data.models.workflow import (  # noqa: F401
    EligibilityDecision,
    TriggerEvent,
    WorkflowRun,
)

__all__ = [
    "Base",
    "TimestampMixin",
    "init_db",
    "close_db",
    "get_engine",
    "get_session",
    "get_session_factory",
]
