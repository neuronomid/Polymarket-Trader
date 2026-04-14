"""Investigation Engine — Phase 9.

Orchestrates the full investigation workflow: scheduled sweep,
trigger-based, and operator-forced investigation modes. Produces
thesis cards with all spec Section 14.2 fields.

Key components:
- InvestigationOrchestrator: main workflow engine
- Domain managers: six category-specific agents
- Research pack: five default research agents
- Entry impact calculator: Tier D order book walk
- Base-rate system: historical resolution rate lookup
- Candidate rubric: multi-dimensional scoring
- Thesis card builder: assembles all Section 14.2 fields
"""

from investigation.base_rate import BaseRateSystem
from investigation.domain_managers import (
    BaseDomainManager,
    GeopoliticsDomainManager,
    MacroPolicyDomainManager,
    PoliticsDomainManager,
    ScienceHealthDomainManager,
    SportsDomainManager,
    TechnologyDomainManager,
    get_domain_manager_class,
)
from investigation.entry_impact import EntryImpactCalculator
from investigation.orchestrator import InvestigationOrchestrator
from investigation.research_agents import (
    CounterCaseAgent,
    DataCrossCheckAgent,
    EvidenceResearchAgent,
    MarketStructureAgent,
    ResolutionReviewAgent,
    SentimentDriftAgent,
    SourceReliabilityAgent,
    TimingCatalystAgent,
)
from investigation.rubric import CandidateRubric
from investigation.thesis_builder import ThesisCardBuilder
from investigation.types import (
    BaseRateResult,
    CandidateContext,
    CandidateRubricScore,
    DomainMemo,
    EntryImpactResult,
    EvidenceItem,
    InvestigationMode,
    InvestigationOutcome,
    InvestigationRequest,
    InvestigationResult,
    NetEdgeCalculation,
    NoTradeResult,
    ResearchPackResult,
    ThesisCardData,
)

__all__ = [
    # Orchestrator
    "InvestigationOrchestrator",
    # Domain Managers
    "BaseDomainManager",
    "PoliticsDomainManager",
    "GeopoliticsDomainManager",
    "SportsDomainManager",
    "TechnologyDomainManager",
    "ScienceHealthDomainManager",
    "MacroPolicyDomainManager",
    "get_domain_manager_class",
    # Research Agents
    "EvidenceResearchAgent",
    "CounterCaseAgent",
    "ResolutionReviewAgent",
    "TimingCatalystAgent",
    "MarketStructureAgent",
    "DataCrossCheckAgent",
    "SentimentDriftAgent",
    "SourceReliabilityAgent",
    # Core Components
    "EntryImpactCalculator",
    "BaseRateSystem",
    "CandidateRubric",
    "ThesisCardBuilder",
    # Types
    "BaseRateResult",
    "CandidateContext",
    "CandidateRubricScore",
    "DomainMemo",
    "EntryImpactResult",
    "EvidenceItem",
    "InvestigationMode",
    "InvestigationOutcome",
    "InvestigationRequest",
    "InvestigationResult",
    "NetEdgeCalculation",
    "NoTradeResult",
    "ResearchPackResult",
    "ThesisCardData",
]
