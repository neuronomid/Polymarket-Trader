"""LLM Provider Abstraction Layer.

Unified interface over OpenRouter (for Anthropic-family tiers A/B)
and OpenAI (GPT-5.4 nano/mini for tier C).
Every call is tracked with: model, provider, input/output tokens, estimated cost,
cost class, and latency. Automatic cost class annotation (H/M/L/Z).

This module does NOT make decisions — it provides the raw capability.
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from typing import Any

import structlog

from core.constants import COST_CLASS_RANGES, PROVIDER_MODEL_MAP, TIER_COST_CLASS
from core.enums import CostClass, ModelTier

from agents.types import LLMCallRecord

_log = structlog.get_logger(component="llm_provider")


# --- Pricing per 1M tokens (approximate, for cost estimation) ---

_PRICING_PER_1M_TOKENS: dict[str, dict[str, float]] = {
    "claude-opus-4-6": {"input": 15.0, "output": 75.0},
    "claude-sonnet-4-6": {"input": 3.0, "output": 15.0},
    "gpt-5.4-nano": {"input": 0.10, "output": 0.40},
    "gpt-5.4-mini": {"input": 0.40, "output": 1.60},
}

_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
_OPENROUTER_MODEL_ALIASES: dict[str, str] = {
    "claude-opus-4-6": "anthropic/claude-opus-4.6",
    "claude-sonnet-4-6": "anthropic/claude-sonnet-4.6",
}


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Estimate cost in USD for a given model and token counts."""
    pricing = _PRICING_PER_1M_TOKENS.get(model)
    if pricing is None:
        return 0.0
    input_cost = (input_tokens / 1_000_000) * pricing["input"]
    output_cost = (output_tokens / 1_000_000) * pricing["output"]
    return round(input_cost + output_cost, 6)


def annotate_cost_class(cost_usd: float) -> CostClass:
    """Assign cost class based on actual cost per call."""
    for cost_class in (CostClass.H, CostClass.M, CostClass.L):
        low, high = COST_CLASS_RANGES[cost_class]
        if cost_usd >= low:
            return cost_class
    return CostClass.Z


class LLMResponse:
    """Response from an LLM provider call."""

    def __init__(
        self,
        content: str,
        input_tokens: int,
        output_tokens: int,
        model: str,
        provider: str,
        raw_response: Any = None,
    ) -> None:
        self.content = content
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.model = model
        self.provider = provider
        self.raw_response = raw_response


class BaseLLMProvider:
    """Base class for LLM providers.

    Subclasses implement `_call()` for the actual API interaction.
    This base class handles call tracking and cost estimation.
    """

    provider_name: str = "base"

    def __init__(self, api_key: str = "") -> None:
        self._api_key = api_key
        self._log = structlog.get_logger(component=f"llm_provider.{self.provider_name}")

    async def call(
        self,
        model: str,
        system_prompt: str,
        user_prompt: str,
        tier: ModelTier,
        *,
        max_tokens: int = 4096,
        temperature: float = 0.0,
        workflow_run_id: str = "",
        agent_role: str = "",
        market_id: str | None = None,
        position_id: str | None = None,
    ) -> tuple[LLMResponse, LLMCallRecord]:
        """Make an LLM call with full tracking.

        Returns both the response and a tracking record.
        """
        call_id = str(uuid.uuid4())[:8]
        cost_class = TIER_COST_CLASS.get(tier, CostClass.Z)
        start = time.monotonic()

        try:
            response = await self._call(
                model=model,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=max_tokens,
                temperature=temperature,
            )

            elapsed_ms = (time.monotonic() - start) * 1000
            actual_cost = estimate_cost(model, response.input_tokens, response.output_tokens)
            annotated_class = annotate_cost_class(actual_cost)

            record = LLMCallRecord(
                call_id=call_id,
                workflow_run_id=workflow_run_id,
                market_id=market_id,
                position_id=position_id,
                agent_role=agent_role,
                provider=self.provider_name,
                model=model,
                tier=tier,
                cost_class=annotated_class,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                estimated_cost_usd=estimate_cost(model, response.input_tokens, response.output_tokens),
                actual_cost_usd=actual_cost,
                latency_ms=round(elapsed_ms, 1),
                success=True,
            )

            self._log.info(
                "llm_call_success",
                call_id=call_id,
                model=model,
                tier=tier.value,
                cost_class=annotated_class.value,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                cost_usd=actual_cost,
                latency_ms=round(elapsed_ms, 1),
                workflow_run_id=workflow_run_id,
                agent_role=agent_role,
            )

            return response, record

        except Exception as exc:
            elapsed_ms = (time.monotonic() - start) * 1000
            record = LLMCallRecord(
                call_id=call_id,
                workflow_run_id=workflow_run_id,
                market_id=market_id,
                position_id=position_id,
                agent_role=agent_role,
                provider=self.provider_name,
                model=model,
                tier=tier,
                cost_class=cost_class,
                latency_ms=round(elapsed_ms, 1),
                success=False,
                error=str(exc),
            )

            self._log.error(
                "llm_call_failed",
                call_id=call_id,
                model=model,
                tier=tier.value,
                error=str(exc),
                workflow_run_id=workflow_run_id,
                agent_role=agent_role,
            )

            raise

    async def _call(
        self,
        model: str,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int,
        temperature: float,
    ) -> LLMResponse:
        """Subclass implementation of the actual API call."""
        raise NotImplementedError


class OpenRouterProvider(BaseLLMProvider):
    """OpenRouter provider for Anthropic-family tiers A/B.

    Uses OpenRouter's OpenAI-compatible API surface with the user's
    OpenRouter API key.
    """

    provider_name = "openrouter"

    def __init__(self, api_key: str = "", *, base_url: str = _OPENROUTER_BASE_URL) -> None:
        super().__init__(api_key)
        self._client = None
        self._base_url = base_url

    @staticmethod
    def _resolve_model(model: str) -> str:
        """Map internal Anthropic-family aliases to OpenRouter model IDs."""
        return _OPENROUTER_MODEL_ALIASES.get(model, model)

    def _ensure_client(self) -> Any:
        """Lazily initialize the OpenRouter client."""
        if self._client is None:
            try:
                import openai

                self._client = openai.AsyncOpenAI(
                    api_key=self._api_key,
                    base_url=self._base_url,
                )
            except ImportError:
                raise RuntimeError(
                    "openai package not installed. Install with: pip install openai"
                )
        return self._client

    async def _call(
        self,
        model: str,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int,
        temperature: float,
    ) -> LLMResponse:
        client = self._ensure_client()
        response = await client.chat.completions.create(
            model=self._resolve_model(model),
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )

        content = ""
        usage_input = 0
        usage_output = 0

        if response.choices:
            content = response.choices[0].message.content or ""
        if response.usage:
            usage_input = response.usage.prompt_tokens
            usage_output = response.usage.completion_tokens

        return LLMResponse(
            content=content,
            input_tokens=usage_input,
            output_tokens=usage_output,
            model=model,
            provider=self.provider_name,
            raw_response=response,
        )


class OpenAIProvider(BaseLLMProvider):
    """OpenAI API provider (GPT-5.4 nano, GPT-5.4 mini).

    Tier C (Utility).
    """

    provider_name = "openai"

    def __init__(self, api_key: str = "") -> None:
        super().__init__(api_key)
        self._client = None

    def _ensure_client(self) -> Any:
        """Lazily initialize the OpenAI async client."""
        if self._client is None:
            try:
                import openai

                self._client = openai.AsyncOpenAI(api_key=self._api_key)
            except ImportError:
                raise RuntimeError(
                    "openai package not installed. Install with: pip install openai"
                )
        return self._client

    async def _call(
        self,
        model: str,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int,
        temperature: float,
    ) -> LLMResponse:
        client = self._ensure_client()
        response = await client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )

        content = ""
        usage_input = 0
        usage_output = 0

        if response.choices:
            content = response.choices[0].message.content or ""
        if response.usage:
            usage_input = response.usage.prompt_tokens
            usage_output = response.usage.completion_tokens

        return LLMResponse(
            content=content,
            input_tokens=usage_input,
            output_tokens=usage_output,
            model=model,
            provider=self.provider_name,
            raw_response=response,
        )


class ProviderRouter:
    """Routes LLM calls to the correct provider based on model tier.

    Handles provider selection, fallback, and per-call tracking.

    Usage:
        router = ProviderRouter(config)
        response, record = await router.call(
            tier=ModelTier.B,
            system_prompt="...",
            user_prompt="...",
            agent_role="domain_manager_politics",
            workflow_run_id="wf-123",
        )
    """

    def __init__(
        self,
        openrouter_api_key: str = "",
        openai_api_key: str = "",
        *,
        anthropic_api_key: str = "",
        openrouter_base_url: str = _OPENROUTER_BASE_URL,
        tier_a_model: str = "",
        tier_b_model: str = "",
        tier_c_model: str = "",
        tier_c_alt_model: str = "",
    ) -> None:
        self._openrouter = OpenRouterProvider(
            api_key=openrouter_api_key or anthropic_api_key,
            base_url=openrouter_base_url,
        )
        self._openai = OpenAIProvider(api_key=openai_api_key)

        # Allow model overrides; fall back to constants
        self._tier_models = {
            ModelTier.A: tier_a_model or PROVIDER_MODEL_MAP[ModelTier.A]["model"],
            ModelTier.B: tier_b_model or PROVIDER_MODEL_MAP[ModelTier.B]["model"],
            ModelTier.C: tier_c_model or PROVIDER_MODEL_MAP[ModelTier.C]["model"],
        }
        self._tier_c_alt = tier_c_alt_model or "gpt-5.4-mini"

        self._log = structlog.get_logger(component="provider_router")

    def _provider_for_tier(self, tier: ModelTier) -> BaseLLMProvider:
        """Select provider based on tier."""
        if tier in (ModelTier.A, ModelTier.B):
            return self._openrouter
        elif tier == ModelTier.C:
            return self._openai
        else:
            raise ValueError(f"Tier D is deterministic — no LLM call allowed (tier={tier})")

    def model_for_tier(self, tier: ModelTier, *, use_alt: bool = False) -> str:
        """Get the model name for a given tier."""
        if tier == ModelTier.D:
            return "deterministic"
        if tier == ModelTier.C and use_alt:
            return self._tier_c_alt
        return self._tier_models.get(tier, "unknown")

    async def call(
        self,
        tier: ModelTier,
        system_prompt: str,
        user_prompt: str,
        *,
        agent_role: str = "",
        workflow_run_id: str = "",
        market_id: str | None = None,
        position_id: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
        use_alt_model: bool = False,
        model_override: str | None = None,
    ) -> tuple[LLMResponse, LLMCallRecord]:
        """Route an LLM call to the appropriate provider.

        Args:
            tier: Model tier (A/B/C). Tier D raises ValueError.
            system_prompt: System prompt content.
            user_prompt: User prompt content.
            agent_role: Name of the agent making this call.
            workflow_run_id: Workflow run identifier.
            market_id: Optional market attribution.
            position_id: Optional position attribution.
            max_tokens: Maximum output tokens.
            temperature: Sampling temperature.
            use_alt_model: If True, use the alternative Tier C model.
            model_override: Override the default model for this tier.

        Returns:
            Tuple of (LLMResponse, LLMCallRecord).

        Raises:
            ValueError: If tier is D (deterministic — no LLM call).
        """
        if tier == ModelTier.D:
            raise ValueError("Tier D is deterministic — cannot make LLM call")

        provider = self._provider_for_tier(tier)
        model = model_override or self.model_for_tier(tier, use_alt=use_alt_model)

        self._log.debug(
            "routing_call",
            tier=tier.value,
            model=model,
            provider=provider.provider_name,
            agent_role=agent_role,
        )

        return await provider.call(
            model=model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            tier=tier,
            max_tokens=max_tokens,
            temperature=temperature,
            workflow_run_id=workflow_run_id,
            agent_role=agent_role,
            market_id=market_id,
            position_id=position_id,
        )

    @classmethod
    def from_config(cls, config: Any) -> ProviderRouter:
        """Create a ProviderRouter from an AppConfig or ModelConfig."""
        # Support both AppConfig (config.models.*) and ModelConfig directly
        models = getattr(config, "models", config)
        return cls(
            openrouter_api_key=getattr(models, "openrouter_api_key", "")
            or getattr(models, "anthropic_api_key", ""),
            openai_api_key=getattr(models, "openai_api_key", ""),
            openrouter_base_url=getattr(models, "openrouter_base_url", _OPENROUTER_BASE_URL),
            tier_a_model=getattr(models, "tier_a_model", ""),
            tier_b_model=getattr(models, "tier_b_model", ""),
            tier_c_model=getattr(models, "tier_c_model", ""),
            tier_c_alt_model=getattr(models, "tier_c_alt_model", ""),
        )


# Backward-compatible alias: Anthropic-family tiers now route through OpenRouter.
AnthropicProvider = OpenRouterProvider
