"""Agent base class — framework for all LLM-powered agents.

All agents follow the same pattern:
- Input: structured context (not raw text)
- Output: structured result (typed, validated)
- Cost tracking: every call attributed to workflow_run_id, market_id, position_id
- Escalation logging: reason, rule, Cost Governor approval, actual cost
- Compression-first: context compressed before Tier A calls

Subclasses implement `_execute()` with domain-specific logic.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import structlog

from core.enums import ModelTier

from agents.compression import compress_context_for_tier_a
from agents.prompts import PromptManager
from agents.providers import LLMResponse, ProviderRouter
from agents.registry import AgentRoleSpec, get_role
from agents.types import (
    AgentInput,
    AgentResult,
    CalibrationContext,
    LLMCallRecord,
    RegimeContext,
)

_log = structlog.get_logger(component="agent_base")


class BaseAgent:
    """Base class for all LLM-powered agents.

    Provides:
    - Structured input/output handling
    - Automatic cost tracking per call
    - Compression-first enforcement for Tier A calls
    - Escalation logging
    - Regime-aware prompt assembly

    Subclasses must implement `_execute()` and optionally
    override `_build_user_prompt()` and `_parse_response()`.

    Usage:
        class MyAgent(BaseAgent):
            role_name = "evidence_research"

            async def _execute(self, agent_input, context):
                # Make LLM call(s) and return result
                response = await self.call_llm(agent_input, user_prompt="...")
                return {"findings": response.content}

        agent = MyAgent(router=router, prompt_manager=prompt_manager)
        result = await agent.run(agent_input)
    """

    role_name: str = ""

    def __init__(
        self,
        *,
        router: ProviderRouter,
        prompt_manager: PromptManager | None = None,
        role_spec: AgentRoleSpec | None = None,
    ) -> None:
        self._router = router
        self._prompt_manager = prompt_manager or PromptManager()

        # Resolve role spec from registry if not provided
        if role_spec is not None:
            self._role_spec = role_spec
        elif self.role_name:
            self._role_spec = get_role(self.role_name)
        else:
            self._role_spec = None

        self._log = structlog.get_logger(
            component=f"agent.{self.role_name or 'unknown'}"
        )
        self._active_result: AgentResult | None = None

    @property
    def tier(self) -> ModelTier:
        """Default model tier for this agent."""
        if self._role_spec:
            return self._role_spec.tier
        return ModelTier.C

    @property
    def is_deterministic(self) -> bool:
        """Whether this agent is purely deterministic (Tier D)."""
        return self.tier == ModelTier.D

    async def run(
        self,
        agent_input: AgentInput,
        *,
        regime: RegimeContext | None = None,
    ) -> AgentResult:
        """Execute the agent with full tracking.

        Args:
            agent_input: Structured input context.
            regime: Optional regime context for prompt flags.

        Returns:
            AgentResult with tracking records.
        """
        result = AgentResult(agent_role=self.role_name or "unknown")

        try:
            self._log.info(
                "agent_run_start",
                agent_role=self.role_name,
                tier=self.tier.value,
                workflow_run_id=agent_input.workflow_run_id,
                market_id=agent_input.market_id,
            )

            # Apply regime context to input
            if regime:
                agent_input.calibration_regime = regime.calibration.regime
                agent_input.viability_proven = regime.calibration.viability_proven
                agent_input.sports_quality_gated = regime.calibration.sports_quality_gated
                agent_input.cost_selectivity_ratio = regime.cost_selectivity_ratio
                agent_input.operator_mode = regime.operator_mode

            # Execute the agent's domain logic
            self._active_result = result
            try:
                output = await self._execute(agent_input, regime)
            finally:
                self._active_result = None

            result.result = output if isinstance(output, dict) else {"output": output}
            result.success = True

            self._log.info(
                "agent_run_success",
                agent_role=self.role_name,
                total_cost=result.total_cost_usd,
                total_tokens=result.total_input_tokens + result.total_output_tokens,
                call_count=len(result.call_records),
            )

        except Exception as exc:
            result.success = False
            result.error = str(exc)

            self._log.error(
                "agent_run_failed",
                agent_role=self.role_name,
                error=str(exc),
                workflow_run_id=agent_input.workflow_run_id,
            )

        return result

    async def _execute(
        self,
        agent_input: AgentInput,
        regime: RegimeContext | None,
    ) -> dict[str, Any]:
        """Subclass implementation of domain-specific agent logic.

        Must return a dictionary of results. Can call self.call_llm()
        for LLM interactions.
        """
        raise NotImplementedError(
            f"Agent {self.role_name} must implement _execute()"
        )

    async def call_llm(
        self,
        agent_input: AgentInput,
        *,
        user_prompt: str,
        system_prompt: str | None = None,
        tier: ModelTier | None = None,
        regime: RegimeContext | None = None,
        result: AgentResult | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
        compress_for_tier_a: bool = True,
        use_alt_model: bool = False,
    ) -> LLMResponse:
        """Make an LLM call with automatic tracking and compression.

        This is the primary method agents use to interact with LLMs.
        Adds the call record to the result if provided.

        Args:
            agent_input: Agent input with tracking IDs.
            user_prompt: The user prompt content.
            system_prompt: Override system prompt (default: build from role + regime).
            tier: Override model tier (default: agent's default tier).
            regime: Regime context for prompt assembly.
            result: AgentResult to accumulate call records into.
            max_tokens: Maximum output tokens.
            temperature: Sampling temperature.
            compress_for_tier_a: Whether to compress context for Tier A calls.
            use_alt_model: Use alternative Tier C model.

        Returns:
            LLMResponse with the model's output.
        """
        effective_tier = tier or self.tier

        if effective_tier == ModelTier.D:
            raise ValueError(
                f"Agent {self.role_name}: Tier D is deterministic — cannot call LLM"
            )

        # Compression enforcement for Tier A
        if effective_tier == ModelTier.A and compress_for_tier_a:
            if agent_input.context:
                agent_input.context = compress_context_for_tier_a(agent_input.context)
            self._log.debug("context_compressed_for_tier_a", agent_role=self.role_name)

        # Build system prompt if not provided
        if system_prompt is None:
            system_prompt = self._prompt_manager.build_system_prompt(
                agent_role=self.role_name,
                regime=regime,
            )

        # Make the call
        response, call_record = await self._router.call(
            tier=effective_tier,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            agent_role=self.role_name,
            workflow_run_id=agent_input.workflow_run_id,
            market_id=agent_input.market_id,
            position_id=agent_input.position_id,
            max_tokens=max_tokens,
            temperature=temperature,
            use_alt_model=use_alt_model,
        )

        # Track the call
        target_result = result or self._active_result
        if target_result is not None:
            target_result.add_call_record(call_record)
            if (
                self._active_result is not None
                and self._active_result is not target_result
            ):
                self._active_result.add_call_record(call_record)

        return response

    def _build_user_prompt(
        self,
        agent_input: AgentInput,
    ) -> str:
        """Build user prompt from structured input.

        Default implementation serializes context as JSON.
        Subclasses should override for domain-specific formatting.
        """
        return json.dumps(agent_input.context, indent=2, default=str)

    def _parse_response(
        self,
        response: LLMResponse,
    ) -> dict[str, Any]:
        """Parse LLM response into structured output.

        Default implementation returns raw text.
        Subclasses should override for structured parsing.
        """
        # Try JSON parsing first
        try:
            return json.loads(response.content)
        except (json.JSONDecodeError, TypeError):
            return {"content": response.content}


class SimpleAgent(BaseAgent):
    """A simple agent that takes a user prompt shape and returns LLM output.

    Useful for straightforward utility agents (journal writer, alert composer)
    where the input-output mapping is simple.
    """

    async def _execute(
        self,
        agent_input: AgentInput,
        regime: RegimeContext | None,
    ) -> dict[str, Any]:
        result = AgentResult(agent_role=self.role_name)
        user_prompt = self._build_user_prompt(agent_input)
        response = await self.call_llm(
            agent_input,
            user_prompt=user_prompt,
            regime=regime,
            result=result,
        )
        return self._parse_response(response)
