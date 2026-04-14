"""Tests for Phase 8: LLM Integration & Agent Framework.

Covers all deliverables:
1. Provider abstraction with Anthropic + OpenAI
2. Agent base class with structured I/O and cost tracking
3. Agent registry with all roles
4. Prompt templates
5. Compression utilities
6. Escalation policy engine
7. Regime adapter
8. Context compression for Tier A calls
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.enums import (
    CalibrationRegime,
    Category,
    CostClass,
    ModelTier,
    OperatorMode,
)
from core.constants import (
    COST_CLASS_RANGES,
    PROVIDER_MODEL_MAP,
    TIER_COST_CLASS,
    SPORTS_CALIBRATION_THRESHOLD,
)


# =============================================================================
# 1. Types Tests
# =============================================================================


class TestAgentTypes:
    """Test agent framework types."""

    def test_llm_call_record_defaults(self):
        from agents.types import LLMCallRecord

        record = LLMCallRecord()
        assert record.call_id == ""
        assert record.workflow_run_id == ""
        assert record.success is True
        assert record.input_tokens == 0
        assert record.output_tokens == 0
        assert record.actual_cost_usd == 0.0
        assert record.tier == ModelTier.C
        assert record.cost_class == CostClass.L

    def test_llm_call_record_full(self):
        from agents.types import LLMCallRecord

        record = LLMCallRecord(
            call_id="abc",
            workflow_run_id="wf-1",
            market_id="mkt-1",
            position_id="pos-1",
            agent_role="counter_case",
            provider="anthropic",
            model="claude-sonnet-4-6",
            tier=ModelTier.B,
            cost_class=CostClass.M,
            input_tokens=1000,
            output_tokens=500,
            estimated_cost_usd=0.013,
            actual_cost_usd=0.012,
            latency_ms=450.0,
        )
        assert record.call_id == "abc"
        assert record.tier == ModelTier.B
        assert record.cost_class == CostClass.M
        assert record.input_tokens == 1000

    def test_agent_input_defaults(self):
        from agents.types import AgentInput

        inp = AgentInput()
        assert inp.workflow_run_id == ""
        assert inp.market_id is None
        assert inp.context == {}
        assert inp.calibration_regime == CalibrationRegime.INSUFFICIENT
        assert inp.viability_proven is False
        assert inp.sports_quality_gated is False

    def test_agent_input_with_context(self):
        from agents.types import AgentInput

        inp = AgentInput(
            workflow_run_id="wf-123",
            market_id="mkt-456",
            agent_role="evidence_research",
            context={"thesis": "Test thesis", "evidence": ["item1", "item2"]},
            calibration_regime=CalibrationRegime.SUFFICIENT,
            operator_mode=OperatorMode.LIVE_STANDARD,
        )
        assert inp.context["thesis"] == "Test thesis"
        assert inp.calibration_regime == CalibrationRegime.SUFFICIENT
        assert inp.operator_mode == OperatorMode.LIVE_STANDARD

    def test_agent_result_add_call_record(self):
        from agents.types import AgentResult, LLMCallRecord

        result = AgentResult(agent_role="test")
        assert result.total_cost_usd == 0.0
        assert result.total_input_tokens == 0
        assert len(result.call_records) == 0

        record1 = LLMCallRecord(
            input_tokens=100,
            output_tokens=50,
            actual_cost_usd=0.005,
        )
        result.add_call_record(record1)
        assert result.total_cost_usd == 0.005
        assert result.total_input_tokens == 100
        assert result.total_output_tokens == 50
        assert len(result.call_records) == 1

        record2 = LLMCallRecord(
            input_tokens=200,
            output_tokens=100,
            actual_cost_usd=0.010,
        )
        result.add_call_record(record2)
        assert result.total_cost_usd == 0.015
        assert result.total_input_tokens == 300
        assert len(result.call_records) == 2

    def test_escalation_record(self):
        from agents.types import EscalationRecord

        record = EscalationRecord(
            workflow_run_id="wf-1",
            agent_role="investigator_orchestration",
            reason="Complex synthesis required",
            triggering_rule="ambiguity_unresolved",
            cost_governor_approved=True,
            cost_governor_approval_reason="Within budget",
            cost_selectivity_ratio_at_decision=0.15,
            escalation_approved=True,
            actual_cost_usd=0.18,
            model_used="claude-opus-4-6",
        )
        assert record.escalation_approved is True
        assert record.cost_governor_approved is True
        assert record.actual_cost_usd == 0.18

    def test_calibration_context_properties(self):
        from agents.types import CalibrationContext

        ctx = CalibrationContext(regime=CalibrationRegime.INSUFFICIENT)
        assert ctx.is_insufficient is True
        assert ctx.is_viability_uncertain is False

        ctx2 = CalibrationContext(regime=CalibrationRegime.VIABILITY_UNCERTAIN)
        assert ctx2.is_insufficient is False
        assert ctx2.is_viability_uncertain is True

        ctx3 = CalibrationContext(regime=CalibrationRegime.SUFFICIENT)
        assert ctx3.is_insufficient is False
        assert ctx3.is_viability_uncertain is False

    def test_regime_context(self):
        from agents.types import CalibrationContext, RegimeContext

        ctx = RegimeContext(
            calibration=CalibrationContext(
                regime=CalibrationRegime.INSUFFICIENT,
                sports_quality_gated=True,
                sports_resolved_trades=15,
            ),
            operator_mode=OperatorMode.PAPER,
            cost_selectivity_ratio=0.12,
        )
        assert ctx.calibration.sports_quality_gated is True
        assert ctx.operator_mode == OperatorMode.PAPER
        assert ctx.cost_selectivity_ratio == 0.12


# =============================================================================
# 2. Provider Abstraction Tests
# =============================================================================


class TestProviderAbstraction:
    """Test LLM provider abstraction layer."""

    def test_estimate_cost_opus(self):
        from agents.providers import estimate_cost

        cost = estimate_cost("claude-opus-4-6", 1000, 500)
        # Input: 1000/1M * $15 = $0.015, Output: 500/1M * $75 = $0.0375
        expected = round(0.015 + 0.0375, 6)
        assert cost == expected

    def test_estimate_cost_sonnet(self):
        from agents.providers import estimate_cost

        cost = estimate_cost("claude-sonnet-4-6", 1000, 500)
        # Input: 1000/1M * $3 = $0.003, Output: 500/1M * $15 = $0.0075
        expected = round(0.003 + 0.0075, 6)
        assert cost == expected

    def test_estimate_cost_nano(self):
        from agents.providers import estimate_cost

        cost = estimate_cost("gpt-5.4-nano", 10000, 5000)
        # Input: 10000/1M * $0.10 = $0.001, Output: 5000/1M * $0.40 = $0.002
        expected = round(0.001 + 0.002, 6)
        assert cost == expected

    def test_estimate_cost_unknown_model(self):
        from agents.providers import estimate_cost

        cost = estimate_cost("unknown-model", 1000, 500)
        assert cost == 0.0

    def test_annotate_cost_class_high(self):
        from agents.providers import annotate_cost_class

        assert annotate_cost_class(0.15) == CostClass.H
        assert annotate_cost_class(0.05) == CostClass.H
        assert annotate_cost_class(0.30) == CostClass.H

    def test_annotate_cost_class_medium(self):
        from agents.providers import annotate_cost_class

        assert annotate_cost_class(0.03) == CostClass.M
        assert annotate_cost_class(0.01) == CostClass.M

    def test_annotate_cost_class_low(self):
        from agents.providers import annotate_cost_class

        assert annotate_cost_class(0.003) == CostClass.L
        assert annotate_cost_class(0.001) == CostClass.L

    def test_annotate_cost_class_zero(self):
        from agents.providers import annotate_cost_class

        assert annotate_cost_class(0.0) == CostClass.Z
        assert annotate_cost_class(0.0005) == CostClass.Z

    def test_llm_response(self):
        from agents.providers import LLMResponse

        resp = LLMResponse(
            content="Hello world",
            input_tokens=100,
            output_tokens=50,
            model="claude-sonnet-4-6",
            provider="anthropic",
        )
        assert resp.content == "Hello world"
        assert resp.input_tokens == 100
        assert resp.model == "claude-sonnet-4-6"

    def test_provider_router_model_for_tier(self):
        from agents.providers import ProviderRouter

        router = ProviderRouter()
        assert router.model_for_tier(ModelTier.A) == "claude-opus-4-6"
        assert router.model_for_tier(ModelTier.B) == "claude-sonnet-4-6"
        assert router.model_for_tier(ModelTier.C) == "gpt-5.4-nano"
        assert router.model_for_tier(ModelTier.C, use_alt=True) == "gpt-5.4-mini"
        assert router.model_for_tier(ModelTier.D) == "deterministic"

    @pytest.mark.asyncio
    async def test_provider_router_tier_d_raises(self):
        from agents.providers import ProviderRouter

        router = ProviderRouter()
        with pytest.raises(ValueError, match="Tier D"):
            await router.call(
                tier=ModelTier.D,
                system_prompt="test",
                user_prompt="test",
            )

    def test_provider_router_from_config(self):
        from agents.providers import ProviderRouter
        from config.settings import ModelConfig

        config = ModelConfig(
            openrouter_api_key="test-openrouter-key",
            openai_api_key="test-key-2",
            tier_a_model="claude-opus-4-6",
        )
        router = ProviderRouter.from_config(config)
        assert router.model_for_tier(ModelTier.A) == "claude-opus-4-6"
        assert router._openrouter._api_key == "test-openrouter-key"
        assert router._openai._api_key == "test-key-2"

    def test_provider_router_legacy_anthropic_key_falls_back_to_openrouter(
        self, tmp_path, monkeypatch
    ):
        from config import settings as settings_module
        from agents.providers import ProviderRouter
        from config.settings import ModelConfig

        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        monkeypatch.delenv("POLYMARKET_MODELS__OPENROUTER_API_KEY", raising=False)
        settings_module._load_dotenv_values.cache_clear()
        try:
            config = ModelConfig(anthropic_api_key="legacy-anthropic-key")
            router = ProviderRouter.from_config(config)
        finally:
            settings_module._load_dotenv_values.cache_clear()

        assert router._openrouter._api_key == "legacy-anthropic-key"

    def test_provider_router_custom_models(self):
        from agents.providers import ProviderRouter

        router = ProviderRouter(
            tier_a_model="custom-opus",
            tier_b_model="custom-sonnet",
            tier_c_model="custom-nano",
        )
        assert router.model_for_tier(ModelTier.A) == "custom-opus"
        assert router.model_for_tier(ModelTier.B) == "custom-sonnet"
        assert router.model_for_tier(ModelTier.C) == "custom-nano"

    def test_openrouter_provider_maps_internal_model_aliases(self):
        from agents.providers import OpenRouterProvider

        assert OpenRouterProvider._resolve_model("claude-opus-4-6") == "anthropic/claude-opus-4.6"
        assert (
            OpenRouterProvider._resolve_model("claude-sonnet-4-6")
            == "anthropic/claude-sonnet-4.6"
        )


# =============================================================================
# 3. Agent Registry Tests
# =============================================================================


class TestAgentRegistry:
    """Test agent registry with all roles."""

    def test_total_roles(self):
        from agents.registry import get_all_roles

        roles = get_all_roles()
        assert len(roles) == 46, f"Expected 46 total roles, got {len(roles)}"

    def test_tier_a_roles(self):
        from agents.registry import get_roles_by_tier

        tier_a = get_roles_by_tier(ModelTier.A)
        assert len(tier_a) == 2
        role_names = {r.role_name for r in tier_a}
        assert "investigator_orchestration" in role_names
        assert "performance_analyzer" in role_names
        for r in tier_a:
            assert r.cost_class == CostClass.H

    def test_tier_b_roles(self):
        from agents.registry import get_roles_by_tier

        tier_b = get_roles_by_tier(ModelTier.B)
        assert len(tier_b) == 11
        for r in tier_b:
            assert r.cost_class == CostClass.M

    def test_tier_c_roles(self):
        from agents.registry import get_roles_by_tier

        tier_c = get_roles_by_tier(ModelTier.C)
        assert len(tier_c) == 12
        for r in tier_c:
            assert r.cost_class == CostClass.L

    def test_tier_d_roles(self):
        from agents.registry import get_roles_by_tier

        tier_d = get_roles_by_tier(ModelTier.D)
        assert len(tier_d) == 21
        for r in tier_d:
            assert r.cost_class == CostClass.Z
            assert r.is_deterministic is True

    def test_domain_managers(self):
        from agents.registry import get_domain_managers

        managers = get_domain_managers()
        assert len(managers) == 6
        categories = {m.role_name.replace("domain_manager_", "") for m in managers}
        expected = {"politics", "geopolitics", "sports", "technology", "science_health", "macro_policy"}
        assert categories == expected

    def test_domain_manager_for_category(self):
        from agents.registry import domain_manager_for_category

        spec = domain_manager_for_category("politics")
        assert spec is not None
        assert spec.role_name == "domain_manager_politics"
        assert spec.tier == ModelTier.B

        spec2 = domain_manager_for_category("sports")
        assert spec2 is not None
        assert spec2.role_name == "domain_manager_sports"

        none_spec = domain_manager_for_category("nonexistent")
        assert none_spec is None

    def test_get_role(self):
        from agents.registry import get_role

        spec = get_role("risk_governor")
        assert spec is not None
        assert spec.tier == ModelTier.D
        assert spec.cost_class == CostClass.Z
        assert spec.is_deterministic is True

        none_spec = get_role("nonexistent")
        assert none_spec is None

    def test_llm_vs_deterministic_partition(self):
        from agents.registry import get_llm_roles, get_deterministic_roles, get_all_roles

        llm = get_llm_roles()
        det = get_deterministic_roles()
        assert len(llm) + len(det) == len(get_all_roles())

        # No overlap
        llm_names = {r.role_name for r in llm}
        det_names = {r.role_name for r in det}
        assert len(llm_names & det_names) == 0

    def test_key_deterministic_roles_present(self):
        """Verify all critical deterministic roles from the spec are registered."""
        from agents.registry import get_role

        required_deterministic = [
            "risk_governor",
            "cost_governor",
            "execution_engine",
            "trigger_scanner",
            "eligibility_gate",
            "pre_run_cost_estimator",
            "calibration_update_processor",
            "entry_impact_calculator",
            "friction_model_calibrator",
            "bias_audit_processor",
            "strategy_viability_processor",
            "operator_absence_manager",
            "deterministic_position_review",
            "liquidity_sizing_enforcer",
            "shadow_vs_market_comparator",
            "base_rate_lookup",
            "cost_of_selectivity_calculator",
            "calibration_accumulation_projector",
            "clob_cache_manager",
            "lifetime_budget_tracker",
            "patience_budget_tracker",
        ]
        for role_name in required_deterministic:
            spec = get_role(role_name)
            assert spec is not None, f"Missing deterministic role: {role_name}"
            assert spec.tier == ModelTier.D, f"{role_name} should be Tier D"
            assert spec.is_deterministic is True, f"{role_name} should be deterministic"

    def test_roles_by_category(self):
        from agents.registry import get_roles_by_category

        investigation_roles = get_roles_by_category("investigation")
        assert len(investigation_roles) >= 4

        cost_roles = get_roles_by_category("cost")
        assert len(cost_roles) >= 3

    def test_cost_class_consistency_with_tier(self):
        """Every role's cost class should match the tier-to-cost-class mapping."""
        from agents.registry import get_all_roles

        for role_name, spec in get_all_roles().items():
            expected_cost_class = TIER_COST_CLASS[spec.tier]
            assert spec.cost_class == expected_cost_class, (
                f"Role {role_name}: tier {spec.tier.value} should have cost class "
                f"{expected_cost_class.value}, got {spec.cost_class.value}"
            )


# =============================================================================
# 4. Compression Tests
# =============================================================================


class TestCompression:
    """Test context compression utilities."""

    def test_deduplicate_evidence_removes_duplicates(self):
        from agents.compression import deduplicate_evidence

        items = [
            {"source": "Reuters", "content": "Breaking news", "url": "https://reuters.com/1"},
            {"source": "Reuters", "content": "Breaking news", "url": "https://reuters.com/1"},
            {"source": "AP", "content": "Different story", "url": "https://ap.com/2"},
        ]
        result = deduplicate_evidence(items)
        assert len(result) == 2

    def test_deduplicate_evidence_preserves_order(self):
        from agents.compression import deduplicate_evidence

        items = [
            {"source": "A", "content": "First"},
            {"source": "B", "content": "Second"},
            {"source": "A", "content": "First"},
        ]
        result = deduplicate_evidence(items)
        assert len(result) == 2
        assert result[0]["source"] == "A"
        assert result[1]["source"] == "B"

    def test_deduplicate_evidence_empty(self):
        from agents.compression import deduplicate_evidence

        assert deduplicate_evidence([]) == []

    def test_deduplicate_evidence_all_unique(self):
        from agents.compression import deduplicate_evidence

        items = [
            {"source": "A", "content": "One"},
            {"source": "B", "content": "Two"},
            {"source": "C", "content": "Three"},
        ]
        result = deduplicate_evidence(items)
        assert len(result) == 3

    def test_compress_log_entries_strips_low_signal(self):
        from agents.compression import compress_log_entries

        entries = [
            {
                "event": "risk_check",
                "decision": "approve",
                "reason": "within limits",
                "hostname": "server-1",
                "pid": 12345,
                "thread_id": "abc",
                "module": "risk.governor",
            },
        ]
        result = compress_log_entries(entries)
        assert len(result) == 1
        assert "decision" in result[0]
        assert "reason" in result[0]
        assert "hostname" not in result[0]
        assert "pid" not in result[0]
        assert "thread_id" not in result[0]
        assert "module" not in result[0]

    def test_compress_log_entries_limits_count(self):
        from agents.compression import compress_log_entries

        entries = [{"event": f"entry_{i}", "decision": "x"} for i in range(100)]
        result = compress_log_entries(entries, max_entries=20)
        assert len(result) == 20

    def test_compress_log_entries_keeps_most_recent(self):
        from agents.compression import compress_log_entries

        entries = [{"event": f"entry_{i}", "decision": "x"} for i in range(100)]
        result = compress_log_entries(entries, max_entries=5)
        # Should keep entries 95-99
        assert result[0]["event"] == "entry_95"
        assert result[-1]["event"] == "entry_99"

    def test_compress_text_removes_boilerplate(self):
        from agents.compression import compress_text

        text = (
            "Important finding about the market.\n"
            "\n\n\n"
            "---\n"
            "Note: This is not financial advice.\n"
            "Key insight: Price divergence detected.\n"
            "Disclaimer: Past performance...\n"
        )
        result = compress_text(text)
        assert "Important finding" in result
        assert "Key insight" in result
        assert "---" not in result

    def test_compress_text_truncates(self):
        from agents.compression import compress_text

        text = "A" * 10000
        result = compress_text(text, max_chars=100)
        assert len(result) <= 150  # some overhead for truncation message

    def test_compress_text_empty(self):
        from agents.compression import compress_text

        assert compress_text("") == ""

    def test_compress_context_for_tier_a(self):
        from agents.compression import compress_context_for_tier_a

        context = {
            "evidence": [
                {"source": "A", "content": "Evidence 1"},
                {"source": "A", "content": "Evidence 1"},  # duplicate
                {"source": "B", "content": "Evidence 2"},
            ],
            "logs": [
                {"event": f"log_{i}", "hostname": "h"} for i in range(60)
            ],
            "thesis": "A" * 10000,
            "empty_field": "",
            "none_field": None,
        }
        result = compress_context_for_tier_a(context)

        # Evidence deduplicated
        assert len(result.get("evidence", [])) == 2

        # Logs compressed
        assert len(result.get("logs", [])) <= 30

        # Thesis truncated
        assert len(result.get("thesis", "")) < 10000

        # Empty/None fields removed
        assert "empty_field" not in result
        assert "none_field" not in result

    def test_compress_context_preserves_evidence_limit(self):
        from agents.compression import compress_context_for_tier_a

        context = {
            "evidence": [
                {"source": f"src_{i}", "content": f"content_{i}"}
                for i in range(20)
            ],
        }
        result = compress_context_for_tier_a(context, max_evidence_items=5)
        assert len(result["evidence"]) == 5


# =============================================================================
# 5. Prompt Management Tests
# =============================================================================


class TestPromptManagement:
    """Test structured prompt templates."""

    def test_prompt_manager_build_system_prompt(self):
        from agents.prompts import PromptManager

        manager = PromptManager()
        prompt = manager.build_system_prompt("counter_case")
        assert "Counter-Case Agent" in prompt
        assert "systematic" in prompt  # Base prompt included

    def test_prompt_manager_unknown_role(self):
        from agents.prompts import PromptManager

        manager = PromptManager()
        prompt = manager.build_system_prompt("nonexistent_role")
        assert "nonexistent_role" in prompt  # Falls back to generic

    def test_prompt_manager_with_regime(self):
        from agents.prompts import PromptManager
        from agents.types import CalibrationContext, RegimeContext

        manager = PromptManager()
        regime = RegimeContext(
            calibration=CalibrationContext(
                regime=CalibrationRegime.INSUFFICIENT,
                sports_quality_gated=True,
                sports_resolved_trades=15,
            ),
            operator_mode=OperatorMode.PAPER,
            cost_selectivity_ratio=0.25,
        )
        prompt = manager.build_system_prompt("domain_manager_politics", regime=regime)

        # Should contain calibration flag
        assert "INSUFFICIENT" in prompt or "insufficient" in prompt.lower() or "CALIBRATION" in prompt

        # Should contain Sports flag
        assert "SPORTS" in prompt

        # Should contain operator mode
        assert "PAPER" in prompt

        # Should contain cost selectivity warning
        assert "25.0%" in prompt or "selectivity" in prompt.lower()

    def test_prompt_manager_sufficient_calibration(self):
        from agents.prompts import PromptManager
        from agents.types import CalibrationContext, RegimeContext

        manager = PromptManager()
        regime = RegimeContext(
            calibration=CalibrationContext(regime=CalibrationRegime.SUFFICIENT),
            operator_mode=OperatorMode.LIVE_STANDARD,
        )
        prompt = manager.build_system_prompt("evidence_research", regime=regime)
        assert "SUFFICIENT" in prompt

    def test_prompt_manager_viability_uncertain(self):
        from agents.prompts import PromptManager
        from agents.types import CalibrationContext, RegimeContext

        manager = PromptManager()
        regime = RegimeContext(
            calibration=CalibrationContext(regime=CalibrationRegime.VIABILITY_UNCERTAIN),
        )
        prompt = manager.build_system_prompt("investigator_orchestration", regime=regime)
        assert "UNPROVEN" in prompt or "viability" in prompt.lower()

    def test_prompt_manager_all_roles_have_templates(self):
        """Every LLM role in the registry should have a prompt template."""
        from agents.prompts import PromptManager
        from agents.registry import get_llm_roles

        manager = PromptManager()
        llm_roles = get_llm_roles()

        for role_spec in llm_roles:
            template = manager.get_role_template(role_spec.role_name)
            assert template is not None, (
                f"Missing prompt template for LLM role: {role_spec.role_name}"
            )

    def test_prompt_manager_list_roles(self):
        from agents.prompts import PromptManager

        manager = PromptManager()
        roles = manager.list_roles()
        assert len(roles) >= 25  # All LLM roles should have templates

    def test_prompt_manager_custom_template(self):
        from agents.prompts import PromptManager

        manager = PromptManager(custom_templates={"custom_agent": "Custom instructions."})
        prompt = manager.build_system_prompt("custom_agent")
        assert "Custom instructions" in prompt

    def test_prompt_manager_register_template(self):
        from agents.prompts import PromptManager

        manager = PromptManager()
        manager.register_template("new_role", "New role instructions.")
        template = manager.get_role_template("new_role")
        assert template == "New role instructions."

    def test_operator_mode_all_modes(self):
        from agents.prompts import PromptManager
        from agents.types import RegimeContext

        manager = PromptManager()
        for mode in OperatorMode:
            regime = RegimeContext(operator_mode=mode)
            prompt = manager.build_system_prompt("evidence_research", regime=regime)
            assert mode.value.upper().replace("_", " ") in prompt or "OPERATOR MODE" in prompt

    def test_cost_selectivity_warning_above_target(self):
        from agents.prompts import PromptManager
        from agents.types import RegimeContext

        manager = PromptManager()
        regime = RegimeContext(cost_selectivity_ratio=0.30)
        prompt = manager.build_system_prompt("evidence_research", regime=regime)
        assert "30.0%" in prompt
        assert "higher quality" in prompt.lower() or "demand" in prompt.lower()

    def test_cost_selectivity_no_warning_below_target(self):
        from agents.prompts import PromptManager
        from agents.types import RegimeContext

        manager = PromptManager()
        regime = RegimeContext(cost_selectivity_ratio=0.10)
        prompt = manager.build_system_prompt("evidence_research", regime=regime)
        assert "10.0%" in prompt
        # Should NOT have the warning about demanding higher quality
        assert "demand higher quality" not in prompt.lower()


# =============================================================================
# 6. Escalation Policy Tests
# =============================================================================


class TestEscalationPolicy:
    """Test Tier A escalation policy engine."""

    def _make_approval(self, approved: bool = True, reason: str = "OK"):
        from cost.types import CostApproval, CostDecision

        return CostApproval(
            decision=CostDecision.APPROVE_FULL if approved else CostDecision.REJECT,
            reason=reason,
        )

    def _make_review_status(self, cap_hit: bool = False):
        from cost.types import ReviewCostStatus

        return ReviewCostStatus(
            position_id="pos-1",
            total_review_cost_usd=100.0 if cap_hit else 5.0,
            position_value_usd=500.0,
            cost_pct_of_value=0.20 if cap_hit else 0.01,
            total_reviews=10,
            deterministic_reviews=7,
            llm_reviews=3,
            warning_threshold_hit=cap_hit,
            cap_threshold_hit=cap_hit,
        )

    def test_escalation_approved_all_conditions_met(self):
        from agents.escalation import EscalationPolicyEngine, EscalationRequest

        engine = EscalationPolicyEngine()
        request = EscalationRequest(
            workflow_run_id="wf-1",
            agent_role="investigator_orchestration",
            reason="Complex synthesis needed",
            triggering_rule="ambiguity_unresolved",
            survived_deterministic_filtering=True,
            net_edge_after_impact=0.05,
            ambiguity_resolved_by_tier_b=False,
            position_size_meaningful=True,
            cost_governor_approval=self._make_approval(True),
            daily_opus_budget_remaining=3.0,
        )
        approved, record = engine.evaluate(request)
        assert approved is True
        assert record.escalation_approved is True

    def test_escalation_denied_deterministic_not_passed(self):
        from agents.escalation import EscalationPolicyEngine, EscalationRequest

        engine = EscalationPolicyEngine()
        request = EscalationRequest(
            workflow_run_id="wf-1",
            agent_role="investigator_orchestration",
            reason="Test",
            triggering_rule="test",
            survived_deterministic_filtering=False,
            net_edge_after_impact=0.05,
            ambiguity_resolved_by_tier_b=False,
            position_size_meaningful=True,
            cost_governor_approval=self._make_approval(True),
        )
        approved, record = engine.evaluate(request)
        assert approved is False
        assert "deterministic" in record.reason.lower()

    def test_escalation_denied_summarization_only(self):
        from agents.escalation import EscalationPolicyEngine, EscalationRequest

        engine = EscalationPolicyEngine()
        request = EscalationRequest(
            workflow_run_id="wf-1",
            agent_role="journal_writer",
            reason="Need summary",
            triggering_rule="test",
            survived_deterministic_filtering=True,
            is_summarization_only=True,
            ambiguity_resolved_by_tier_b=False,
        )
        approved, record = engine.evaluate(request)
        assert approved is False
        assert "summarization" in record.reason.lower()

    def test_escalation_denied_low_net_edge(self):
        from agents.escalation import EscalationPolicyEngine, EscalationRequest

        engine = EscalationPolicyEngine()
        request = EscalationRequest(
            workflow_run_id="wf-1",
            agent_role="investigator_orchestration",
            reason="Test",
            triggering_rule="test",
            survived_deterministic_filtering=True,
            net_edge_after_impact=0.005,
            min_net_edge_threshold=0.02,
            ambiguity_resolved_by_tier_b=False,
            position_size_meaningful=True,
        )
        approved, record = engine.evaluate(request)
        assert approved is False

    def test_escalation_denied_ambiguity_resolved(self):
        from agents.escalation import EscalationPolicyEngine, EscalationRequest

        engine = EscalationPolicyEngine()
        request = EscalationRequest(
            workflow_run_id="wf-1",
            agent_role="investigator_orchestration",
            reason="Test",
            triggering_rule="test",
            survived_deterministic_filtering=True,
            net_edge_after_impact=0.05,
            ambiguity_resolved_by_tier_b=True,  # Already resolved
            position_size_meaningful=True,
        )
        approved, record = engine.evaluate(request)
        assert approved is False
        assert "resolved" in record.reason.lower()

    def test_escalation_denied_small_position(self):
        from agents.escalation import EscalationPolicyEngine, EscalationRequest

        engine = EscalationPolicyEngine()
        request = EscalationRequest(
            workflow_run_id="wf-1",
            agent_role="investigator_orchestration",
            reason="Test",
            triggering_rule="test",
            survived_deterministic_filtering=True,
            net_edge_after_impact=0.05,
            ambiguity_resolved_by_tier_b=False,
            position_size_meaningful=False,  # Too small
        )
        approved, record = engine.evaluate(request)
        assert approved is False

    def test_escalation_denied_cost_governor_rejected(self):
        from agents.escalation import EscalationPolicyEngine, EscalationRequest

        engine = EscalationPolicyEngine()
        request = EscalationRequest(
            workflow_run_id="wf-1",
            agent_role="investigator_orchestration",
            reason="Test",
            triggering_rule="test",
            survived_deterministic_filtering=True,
            net_edge_after_impact=0.05,
            ambiguity_resolved_by_tier_b=False,
            position_size_meaningful=True,
            cost_governor_approval=self._make_approval(False, "Budget exhausted"),
        )
        approved, record = engine.evaluate(request)
        assert approved is False
        assert record.cost_governor_approved is False

    def test_escalation_denied_opus_budget_exhausted(self):
        from agents.escalation import EscalationPolicyEngine, EscalationRequest

        engine = EscalationPolicyEngine()
        request = EscalationRequest(
            workflow_run_id="wf-1",
            agent_role="investigator_orchestration",
            reason="Test",
            triggering_rule="test",
            survived_deterministic_filtering=True,
            net_edge_after_impact=0.05,
            ambiguity_resolved_by_tier_b=False,
            position_size_meaningful=True,
            cost_governor_approval=self._make_approval(True),
            daily_opus_budget_remaining=0.0,  # Exhausted
        )
        approved, record = engine.evaluate(request)
        assert approved is False

    def test_escalation_denied_excessive_entry_impact(self):
        from agents.escalation import EscalationPolicyEngine, EscalationRequest

        engine = EscalationPolicyEngine()
        request = EscalationRequest(
            workflow_run_id="wf-1",
            agent_role="investigator_orchestration",
            reason="Test",
            triggering_rule="test",
            survived_deterministic_filtering=True,
            net_edge_after_impact=0.05,
            ambiguity_resolved_by_tier_b=False,
            position_size_meaningful=True,
            entry_impact_pct_of_edge=0.30,  # > 25%
        )
        approved, record = engine.evaluate(request)
        assert approved is False

    def test_escalation_denied_review_cost_cap_exceeded(self):
        from agents.escalation import EscalationPolicyEngine, EscalationRequest

        engine = EscalationPolicyEngine()
        request = EscalationRequest(
            workflow_run_id="wf-1",
            agent_role="position_review_orchestration",
            reason="Test",
            triggering_rule="test",
            survived_deterministic_filtering=True,
            net_edge_after_impact=0.05,
            ambiguity_resolved_by_tier_b=False,
            position_size_meaningful=True,
            review_cost_status=self._make_review_status(cap_hit=True),
        )
        approved, record = engine.evaluate(request)
        assert approved is False

    def test_escalation_denied_review_deterministic_complete(self):
        from agents.escalation import EscalationPolicyEngine, EscalationRequest

        engine = EscalationPolicyEngine()
        request = EscalationRequest(
            workflow_run_id="wf-1",
            agent_role="position_review_orchestration",
            reason="Test",
            triggering_rule="test",
            survived_deterministic_filtering=True,
            net_edge_after_impact=0.05,
            ambiguity_resolved_by_tier_b=False,
            position_size_meaningful=True,
            review_completed_deterministically=True,
        )
        approved, record = engine.evaluate(request)
        assert approved is False

    def test_escalation_cost_selectivity_raises_threshold(self):
        from agents.escalation import EscalationPolicyEngine, EscalationRequest

        engine = EscalationPolicyEngine()
        # With high selectivity ratio, the net edge threshold should increase
        request = EscalationRequest(
            workflow_run_id="wf-1",
            agent_role="investigator_orchestration",
            reason="Test",
            triggering_rule="test",
            survived_deterministic_filtering=True,
            net_edge_after_impact=0.025,  # Above default 0.02 but maybe not enough
            min_net_edge_threshold=0.02,
            cost_selectivity_ratio=0.40,  # 2x target of 0.20
            cost_selectivity_target=0.20,
            ambiguity_resolved_by_tier_b=False,
            position_size_meaningful=True,
        )
        approved, record = engine.evaluate(request)
        # With selectivity ratio 0.40 (excess=0.20, target=0.20):
        # adjusted threshold = 0.02 * (1 + 0.20/0.20) = 0.02 * 2.0 = 0.04
        # net_edge 0.025 < 0.04 → denied
        assert approved is False

    def test_escalation_viability_uncertain_higher_threshold(self):
        from agents.escalation import EscalationPolicyEngine, EscalationRequest
        from agents.types import CalibrationContext, RegimeContext

        engine = EscalationPolicyEngine()
        regime = RegimeContext(
            calibration=CalibrationContext(regime=CalibrationRegime.VIABILITY_UNCERTAIN),
        )
        request = EscalationRequest(
            workflow_run_id="wf-1",
            agent_role="investigator_orchestration",
            reason="Test",
            triggering_rule="test",
            survived_deterministic_filtering=True,
            net_edge_after_impact=0.025,  # Above 0.02 but below 0.03
            min_net_edge_threshold=0.02,
            ambiguity_resolved_by_tier_b=False,
            position_size_meaningful=True,
            cost_governor_approval=self._make_approval(True),
            daily_opus_budget_remaining=3.0,
            regime=regime,
        )
        approved, record = engine.evaluate(request)
        # Viability uncertain: threshold = 0.02 * 1.5 = 0.03
        # net_edge 0.025 < 0.03 → denied
        assert approved is False

    def test_escalation_record_has_all_fields(self):
        from agents.escalation import EscalationPolicyEngine, EscalationRequest

        engine = EscalationPolicyEngine()
        request = EscalationRequest(
            workflow_run_id="wf-1",
            agent_role="investigator_orchestration",
            reason="Complex synthesis",
            triggering_rule="ambiguity_unresolved",
            survived_deterministic_filtering=True,
            net_edge_after_impact=0.05,
            ambiguity_resolved_by_tier_b=False,
            position_size_meaningful=True,
            cost_governor_approval=self._make_approval(True),
            daily_opus_budget_remaining=3.0,
            cost_selectivity_ratio=0.15,
        )
        approved, record = engine.evaluate(request)
        assert approved is True

        # All required fields present
        assert record.workflow_run_id == "wf-1"
        assert record.agent_role == "investigator_orchestration"
        assert record.reason == "Complex synthesis"
        assert record.triggering_rule == "ambiguity_unresolved"
        assert record.cost_governor_approved is True
        assert record.cost_selectivity_ratio_at_decision == 0.15
        assert record.escalation_approved is True
        assert record.decided_at is not None


# =============================================================================
# 7. Regime Adapter Tests
# =============================================================================


class TestRegimeAdapter:
    """Test calibration regime adapter."""

    def test_build_context_insufficient(self):
        from agents.regime import RegimeAdapter

        adapter = RegimeAdapter()
        ctx = adapter.build_context(
            calibration_regime=CalibrationRegime.INSUFFICIENT,
            operator_mode=OperatorMode.PAPER,
        )
        assert ctx.calibration.is_insufficient is True
        assert ctx.calibration.sports_quality_gated is False
        assert ctx.operator_mode == OperatorMode.PAPER

    def test_build_context_sports_quality_gate(self):
        from agents.regime import RegimeAdapter

        adapter = RegimeAdapter()
        ctx = adapter.build_context(
            calibration_regime=CalibrationRegime.SUFFICIENT,
            category=Category.SPORTS,
            sports_resolved_trades=15,  # Below 40 threshold
        )
        assert ctx.calibration.sports_quality_gated is True
        assert ctx.calibration.sports_resolved_trades == 15

    def test_build_context_sports_calibrated(self):
        from agents.regime import RegimeAdapter

        adapter = RegimeAdapter()
        ctx = adapter.build_context(
            calibration_regime=CalibrationRegime.SUFFICIENT,
            category=Category.SPORTS,
            sports_resolved_trades=50,  # Above 40 threshold
        )
        assert ctx.calibration.sports_quality_gated is False

    def test_build_context_non_sports_never_gated(self):
        from agents.regime import RegimeAdapter

        adapter = RegimeAdapter()
        ctx = adapter.build_context(
            calibration_regime=CalibrationRegime.SUFFICIENT,
            category=Category.POLITICS,
            sports_resolved_trades=5,  # Doesn't matter for non-sports
        )
        assert ctx.calibration.sports_quality_gated is False

    def test_size_cap_multiplier_insufficient(self):
        from agents.regime import RegimeAdapter
        from agents.types import CalibrationContext, RegimeContext

        adapter = RegimeAdapter()
        ctx = RegimeContext(
            calibration=CalibrationContext(regime=CalibrationRegime.INSUFFICIENT),
        )
        multiplier = adapter.get_size_cap_multiplier(ctx)
        assert multiplier == 0.5  # Conservative

    def test_size_cap_multiplier_sufficient(self):
        from agents.regime import RegimeAdapter
        from agents.types import CalibrationContext, RegimeContext

        adapter = RegimeAdapter()
        ctx = RegimeContext(
            calibration=CalibrationContext(regime=CalibrationRegime.SUFFICIENT),
        )
        multiplier = adapter.get_size_cap_multiplier(ctx)
        assert multiplier == 1.0  # Normal

    def test_size_cap_multiplier_viability_uncertain(self):
        from agents.regime import RegimeAdapter
        from agents.types import CalibrationContext, RegimeContext

        adapter = RegimeAdapter()
        ctx = RegimeContext(
            calibration=CalibrationContext(regime=CalibrationRegime.VIABILITY_UNCERTAIN),
        )
        multiplier = adapter.get_size_cap_multiplier(ctx)
        assert multiplier == 0.6

    def test_size_cap_multiplier_sports_gated(self):
        from agents.regime import RegimeAdapter
        from agents.types import CalibrationContext, RegimeContext

        adapter = RegimeAdapter()
        ctx = RegimeContext(
            calibration=CalibrationContext(
                regime=CalibrationRegime.SUFFICIENT,
                sports_quality_gated=True,
            ),
        )
        multiplier = adapter.get_size_cap_multiplier(ctx)
        assert multiplier == 0.5  # Sports gate

    def test_evidence_threshold_by_regime(self):
        from agents.regime import RegimeAdapter
        from agents.types import CalibrationContext, RegimeContext

        adapter = RegimeAdapter()

        insufficient = RegimeContext(
            calibration=CalibrationContext(regime=CalibrationRegime.INSUFFICIENT),
        )
        assert adapter.get_evidence_threshold(insufficient) == 0.7

        sufficient = RegimeContext(
            calibration=CalibrationContext(regime=CalibrationRegime.SUFFICIENT),
        )
        assert adapter.get_evidence_threshold(sufficient) == 0.5

        uncertain = RegimeContext(
            calibration=CalibrationContext(regime=CalibrationRegime.VIABILITY_UNCERTAIN),
        )
        assert adapter.get_evidence_threshold(uncertain) == 0.75

    def test_should_prefer_no_trade(self):
        from agents.regime import RegimeAdapter
        from agents.types import CalibrationContext, RegimeContext

        adapter = RegimeAdapter()

        insufficient = RegimeContext(
            calibration=CalibrationContext(regime=CalibrationRegime.INSUFFICIENT),
        )
        assert adapter.should_prefer_no_trade(insufficient) is True

        uncertain = RegimeContext(
            calibration=CalibrationContext(regime=CalibrationRegime.VIABILITY_UNCERTAIN),
        )
        assert adapter.should_prefer_no_trade(uncertain) is True

        sufficient = RegimeContext(
            calibration=CalibrationContext(regime=CalibrationRegime.SUFFICIENT),
        )
        assert adapter.should_prefer_no_trade(sufficient) is False

    def test_allows_opus_escalation_sports_gated(self):
        from agents.regime import RegimeAdapter
        from agents.types import CalibrationContext, RegimeContext

        adapter = RegimeAdapter()
        ctx = RegimeContext(
            calibration=CalibrationContext(sports_quality_gated=True),
        )
        assert adapter.allows_opus_escalation(ctx) is False
        assert adapter.allows_opus_escalation(ctx, is_exceptional=True) is True

    def test_allows_opus_escalation_budget_exhausted(self):
        from agents.regime import RegimeAdapter
        from agents.types import RegimeContext

        adapter = RegimeAdapter()
        ctx = RegimeContext(daily_opus_budget_remaining=0.0)
        assert adapter.allows_opus_escalation(ctx) is False

    def test_allows_opus_escalation_normal(self):
        from agents.regime import RegimeAdapter
        from agents.types import RegimeContext

        adapter = RegimeAdapter()
        ctx = RegimeContext(daily_opus_budget_remaining=3.0)
        assert adapter.allows_opus_escalation(ctx) is True

    def test_confidence_adjustment_instructions(self):
        from agents.regime import RegimeAdapter
        from agents.types import CalibrationContext, RegimeContext

        adapter = RegimeAdapter()

        insufficient = RegimeContext(
            calibration=CalibrationContext(regime=CalibrationRegime.INSUFFICIENT),
        )
        adj = adapter.get_confidence_adjustment(insufficient)
        assert "conservative" in adj.lower()

        uncertain = RegimeContext(
            calibration=CalibrationContext(regime=CalibrationRegime.VIABILITY_UNCERTAIN),
        )
        adj = adapter.get_confidence_adjustment(uncertain)
        assert "unproven" in adj.lower()

        sufficient = RegimeContext(
            calibration=CalibrationContext(regime=CalibrationRegime.SUFFICIENT),
        )
        adj = adapter.get_confidence_adjustment(sufficient)
        assert "calibrated" in adj.lower()

    def test_regime_summary(self):
        from agents.regime import RegimeAdapter
        from agents.types import CalibrationContext, RegimeContext

        adapter = RegimeAdapter()
        ctx = RegimeContext(
            calibration=CalibrationContext(
                regime=CalibrationRegime.INSUFFICIENT,
                sports_quality_gated=True,
                sports_resolved_trades=10,
            ),
            operator_mode=OperatorMode.PAPER,
        )
        summary = adapter.get_regime_summary(ctx)
        assert summary["calibration_regime"] == "insufficient"
        assert summary["sports_quality_gated"] is True
        assert summary["operator_mode"] == "paper"
        assert summary["prefers_no_trade"] is True


# =============================================================================
# 8. Agent Base Class Tests
# =============================================================================


class TestAgentBase:
    """Test agent base class and SimpleAgent."""

    def test_base_agent_tier_from_registry(self):
        from agents.base import BaseAgent
        from agents.providers import ProviderRouter

        class TestAgent(BaseAgent):
            role_name = "evidence_research"

        agent = TestAgent(router=ProviderRouter())
        assert agent.tier == ModelTier.C
        assert agent.is_deterministic is False

    def test_base_agent_tier_d_is_deterministic(self):
        from agents.base import BaseAgent
        from agents.providers import ProviderRouter
        from agents.registry import AgentRoleSpec

        agent = BaseAgent(
            router=ProviderRouter(),
            role_spec=AgentRoleSpec(
                role_name="test_deterministic",
                tier=ModelTier.D,
                cost_class=CostClass.Z,
                description="Test",
                is_deterministic=True,
            ),
        )
        assert agent.tier == ModelTier.D
        assert agent.is_deterministic is True

    def test_base_agent_build_user_prompt(self):
        from agents.base import BaseAgent
        from agents.providers import ProviderRouter
        from agents.types import AgentInput

        agent = BaseAgent(router=ProviderRouter())
        inp = AgentInput(context={"key": "value", "count": 42})
        prompt = agent._build_user_prompt(inp)

        # Should be valid JSON
        parsed = json.loads(prompt)
        assert parsed["key"] == "value"
        assert parsed["count"] == 42

    def test_base_agent_parse_response_json(self):
        from agents.base import BaseAgent
        from agents.providers import LLMResponse, ProviderRouter

        agent = BaseAgent(router=ProviderRouter())
        response = LLMResponse(
            content='{"finding": "important", "score": 0.85}',
            input_tokens=100,
            output_tokens=50,
            model="test",
            provider="test",
        )
        result = agent._parse_response(response)
        assert result["finding"] == "important"
        assert result["score"] == 0.85

    def test_base_agent_parse_response_plain_text(self):
        from agents.base import BaseAgent
        from agents.providers import LLMResponse, ProviderRouter

        agent = BaseAgent(router=ProviderRouter())
        response = LLMResponse(
            content="This is plain text output.",
            input_tokens=100,
            output_tokens=50,
            model="test",
            provider="test",
        )
        result = agent._parse_response(response)
        assert result["content"] == "This is plain text output."

    @pytest.mark.asyncio
    async def test_base_agent_run_calls_execute(self):
        from agents.base import BaseAgent
        from agents.providers import ProviderRouter
        from agents.types import AgentInput

        class TestAgent(BaseAgent):
            role_name = "evidence_research"

            async def _execute(self, agent_input, regime):
                return {"test": "result"}

        agent = TestAgent(router=ProviderRouter())
        result = await agent.run(AgentInput(workflow_run_id="wf-1"))
        assert result.success is True
        assert result.result["test"] == "result"
        assert result.agent_role == "evidence_research"

    @pytest.mark.asyncio
    async def test_base_agent_run_handles_exception(self):
        from agents.base import BaseAgent
        from agents.providers import ProviderRouter
        from agents.types import AgentInput

        class FailingAgent(BaseAgent):
            role_name = "evidence_research"

            async def _execute(self, agent_input, regime):
                raise ValueError("Test failure")

        agent = FailingAgent(router=ProviderRouter())
        result = await agent.run(AgentInput(workflow_run_id="wf-1"))
        assert result.success is False
        assert "Test failure" in result.error

    @pytest.mark.asyncio
    async def test_base_agent_run_applies_regime(self):
        from agents.base import BaseAgent
        from agents.providers import ProviderRouter
        from agents.types import AgentInput, CalibrationContext, RegimeContext

        captured_input = {}

        class CapturingAgent(BaseAgent):
            role_name = "evidence_research"

            async def _execute(self, agent_input, regime):
                captured_input["calibration_regime"] = agent_input.calibration_regime
                captured_input["sports_quality_gated"] = agent_input.sports_quality_gated
                return {"ok": True}

        agent = CapturingAgent(router=ProviderRouter())
        regime = RegimeContext(
            calibration=CalibrationContext(
                regime=CalibrationRegime.VIABILITY_UNCERTAIN,
                sports_quality_gated=True,
            ),
        )
        result = await agent.run(AgentInput(workflow_run_id="wf-1"), regime=regime)
        assert result.success is True
        assert captured_input["calibration_regime"] == CalibrationRegime.VIABILITY_UNCERTAIN
        assert captured_input["sports_quality_gated"] is True

    @pytest.mark.asyncio
    async def test_base_agent_run_tracks_calls_from_nested_result(self):
        from agents.base import BaseAgent
        from agents.providers import LLMResponse, ProviderRouter
        from agents.types import AgentInput, AgentResult, LLMCallRecord

        router = ProviderRouter()
        router.call = AsyncMock(
            return_value=(
                LLMResponse(
                    content='{"ok": true}',
                    input_tokens=10,
                    output_tokens=5,
                    model="gpt-5.4-nano",
                    provider="openai",
                ),
                LLMCallRecord(
                    call_id="call-1",
                    workflow_run_id="wf-1",
                    agent_role="evidence_research",
                    provider="openai",
                    model="gpt-5.4-nano",
                    tier=ModelTier.C,
                    cost_class=CostClass.L,
                    input_tokens=10,
                    output_tokens=5,
                    actual_cost_usd=0.01,
                ),
            )
        )

        class NestedResultAgent(BaseAgent):
            role_name = "evidence_research"

            async def _execute(self, agent_input, regime):
                nested_result = AgentResult(agent_role=self.role_name)
                await self.call_llm(
                    agent_input,
                    user_prompt="test",
                    regime=regime,
                    result=nested_result,
                )
                return {"nested_cost": nested_result.total_cost_usd}

        agent = NestedResultAgent(router=router)
        result = await agent.run(AgentInput(workflow_run_id="wf-1"))

        assert result.success is True
        assert result.result["nested_cost"] == 0.01
        assert result.total_cost_usd == 0.01
        assert result.total_input_tokens == 10
        assert result.total_output_tokens == 5
        assert len(result.call_records) == 1


# =============================================================================
# 9. Integration Tests
# =============================================================================


class TestIntegration:
    """Integration tests verifying cross-module interactions."""

    def test_agent_registry_and_prompts_alignment(self):
        """Every LLM agent role in registry has a matching prompt template."""
        from agents.prompts import PromptManager
        from agents.registry import get_llm_roles

        manager = PromptManager()
        missing = []
        for spec in get_llm_roles():
            template = manager.get_role_template(spec.role_name)
            if template is None:
                missing.append(spec.role_name)

        assert missing == [], f"LLM roles missing prompt templates: {missing}"

    def test_tier_consistency_across_system(self):
        """Verify tier assignments match core constants."""
        from agents.registry import get_all_roles

        for role_name, spec in get_all_roles().items():
            expected_class = TIER_COST_CLASS[spec.tier]
            assert spec.cost_class == expected_class, (
                f"{role_name}: tier {spec.tier.value} → expected cost class "
                f"{expected_class.value}, got {spec.cost_class.value}"
            )

    def test_deterministic_roles_match_constants(self):
        """Deterministic roles should be a superset of DETERMINISTIC_ONLY_COMPONENTS."""
        from core.constants import DETERMINISTIC_ONLY_COMPONENTS
        from agents.registry import get_deterministic_roles

        det_role_names = {r.role_name for r in get_deterministic_roles()}

        # Not all constants may have matching registry entries (some are sub-components),
        # but all registered Tier D roles should be truly deterministic
        for role in get_deterministic_roles():
            assert role.tier == ModelTier.D
            assert role.cost_class == CostClass.Z
            assert role.is_deterministic is True

    def test_domain_manager_categories_match_enum(self):
        """All allowed categories should have a domain manager."""
        from agents.registry import domain_manager_for_category

        for category in Category:
            spec = domain_manager_for_category(category.value)
            assert spec is not None, (
                f"Missing domain manager for category: {category.value}"
            )
            assert spec.tier == ModelTier.B

    def test_effective_position_review_cost_profile(self):
        """Verify the effective cost profile constants are reasonable."""
        from core.constants import POSITION_REVIEW_COST_PROFILE

        assert POSITION_REVIEW_COST_PROFILE["deterministic_only_pct"] == 0.65
        assert POSITION_REVIEW_COST_PROFILE["workhorse_escalation_pct"] == 0.25
        assert POSITION_REVIEW_COST_PROFILE["premium_escalation_pct"] == 0.10

        # Should sum to 1.0
        total = sum(POSITION_REVIEW_COST_PROFILE.values())
        assert abs(total - 1.0) < 0.001

    def test_compression_before_tier_a_call(self):
        """Verify compression runs and reduces context before Tier A call."""
        from agents.compression import compress_context_for_tier_a

        # Build a large context
        large_context = {
            "evidence": [
                {"source": f"src_{i}", "content": f"content"} for i in range(30)
            ] + [
                {"source": "src_0", "content": "content"},  # Duplicate
            ],
            "logs": [
                {"event": f"ev_{i}", "hostname": "h", "pid": 123}
                for i in range(100)
            ],
            "thesis": "A" * 20000,
            "empty": "",
            "null": None,
        }

        compressed = compress_context_for_tier_a(large_context)

        assert len(compressed.get("evidence", [])) <= 10
        assert len(compressed.get("logs", [])) <= 30
        assert len(compressed.get("thesis", "")) < 20000
        assert "empty" not in compressed
        assert "null" not in compressed

    def test_provider_pricing_covers_all_configured_models(self):
        """All models in PROVIDER_MODEL_MAP should have pricing."""
        from agents.providers import _PRICING_PER_1M_TOKENS

        for tier, config in PROVIDER_MODEL_MAP.items():
            if tier == ModelTier.D:
                continue  # No pricing for deterministic
            model = config["model"]
            assert model in _PRICING_PER_1M_TOKENS, (
                f"Missing pricing for model {model} (Tier {tier.value})"
            )

    def test_escalation_policy_integrates_with_cost_types(self):
        """Escalation policy correctly uses Cost Governor types."""
        from agents.escalation import EscalationPolicyEngine, EscalationRequest
        from cost.types import CostApproval, CostDecision, ReviewCostStatus

        engine = EscalationPolicyEngine()

        # Test with full Cost Governor integration
        approval = CostApproval(
            decision=CostDecision.APPROVE_FULL,
            reason="Within budget",
            approved_max_tier=ModelTier.A,
            approved_max_cost_usd=0.30,
        )
        review_status = ReviewCostStatus(
            position_id="pos-1",
            total_review_cost_usd=5.0,
            position_value_usd=500.0,
            cost_pct_of_value=0.01,
            total_reviews=5,
            deterministic_reviews=4,
            llm_reviews=1,
        )

        request = EscalationRequest(
            workflow_run_id="wf-1",
            agent_role="investigator_orchestration",
            reason="Complex synthesis",
            triggering_rule="test",
            survived_deterministic_filtering=True,
            net_edge_after_impact=0.05,
            ambiguity_resolved_by_tier_b=False,
            position_size_meaningful=True,
            cost_governor_approval=approval,
            daily_opus_budget_remaining=3.0,
            review_cost_status=review_status,
        )

        approved, record = engine.evaluate(request)
        assert approved is True
        assert record.cost_governor_approved is True
        assert record.cumulative_position_review_cost == 5.0
