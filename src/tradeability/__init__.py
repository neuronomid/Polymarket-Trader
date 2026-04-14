"""Tradeability & Resolution Engine — Phase 10.

Determines whether a thesis-worthy market is actually tradable
and whether its wording is sufficiently unambiguous.

Components:
- ResolutionParser: Tier D deterministic checks on contract wording
- TradeabilitySynthesizer: Tier B agent for borderline ambiguity
- Hard rejection patterns: auto-reject on severe issues

Design principle: deterministic checks run first. Agent-assisted
interpretation runs only for surviving candidates with non-trivial
residual ambiguity.
"""

from tradeability.resolution_parser import ResolutionParser
from tradeability.synthesizer import TradeabilitySynthesizer
from tradeability.types import (
    HardRejectionReason,
    ResolutionClarity,
    ResolutionParseInput,
    ResolutionParseOutput,
    TradeabilityInput,
    TradeabilityOutcome,
    TradeabilityResult,
)

__all__ = [
    "ResolutionParser",
    "TradeabilitySynthesizer",
    "HardRejectionReason",
    "ResolutionClarity",
    "ResolutionParseInput",
    "ResolutionParseOutput",
    "TradeabilityInput",
    "TradeabilityOutcome",
    "TradeabilityResult",
]
