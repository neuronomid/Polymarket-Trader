"""LLM Integration & Agent Framework.

Provider abstraction, agent orchestration, per-call cost tracking,
context compression, prompt management, escalation policy, and
calibration regime adaptation.
"""

from agents.base import BaseAgent, SimpleAgent
from agents.compression import (
    compress_context_for_tier_a,
    compress_log_entries,
    compress_text,
    deduplicate_evidence,
)
from agents.escalation import (
    EscalationPolicyEngine,
    EscalationRequest,
)
from agents.prompts import PromptManager
from agents.providers import (
    AnthropicProvider,
    LLMResponse,
    OpenAIProvider,
    ProviderRouter,
    annotate_cost_class,
    estimate_cost,
)
from agents.regime import RegimeAdapter
from agents.registry import (
    AgentRoleSpec,
    domain_manager_for_category,
    get_all_roles,
    get_deterministic_roles,
    get_domain_managers,
    get_llm_roles,
    get_role,
    get_roles_by_category,
    get_roles_by_tier,
)
from agents.types import (
    AgentInput,
    AgentResult,
    CalibrationContext,
    EscalationRecord,
    LLMCallRecord,
    RegimeContext,
)

__all__ = [
    # Base
    "BaseAgent",
    "SimpleAgent",
    # Providers
    "AnthropicProvider",
    "LLMResponse",
    "OpenAIProvider",
    "ProviderRouter",
    "annotate_cost_class",
    "estimate_cost",
    # Types
    "AgentInput",
    "AgentResult",
    "CalibrationContext",
    "EscalationRecord",
    "LLMCallRecord",
    "RegimeContext",
    # Registry
    "AgentRoleSpec",
    "domain_manager_for_category",
    "get_all_roles",
    "get_deterministic_roles",
    "get_domain_managers",
    "get_llm_roles",
    "get_role",
    "get_roles_by_category",
    "get_roles_by_tier",
    # Prompts
    "PromptManager",
    # Compression
    "compress_context_for_tier_a",
    "compress_log_entries",
    "compress_text",
    "deduplicate_evidence",
    # Escalation
    "EscalationPolicyEngine",
    "EscalationRequest",
    # Regime
    "RegimeAdapter",
]
