"""Domain manager agents — six category-specific investigation managers.

Each domain manager receives a candidate context and produces a
structured DomainMemo with category-specific analysis. All run at
Tier B (Sonnet).

Domain managers:
- Politics
- Geopolitics
- Sports
- Technology
- Science & Health
- Macro/Policy
"""

from __future__ import annotations

import json
from typing import Any

import structlog

from agents.base import BaseAgent
from agents.types import AgentInput, AgentResult, RegimeContext
from investigation.types import CandidateContext, DomainMemo

_log = structlog.get_logger(component="domain_managers")


# --- Base Domain Manager ---


class BaseDomainManager(BaseAgent):
    """Base class for domain-specific investigation managers.

    Subclasses set role_name and override `_build_domain_context()`
    to add domain-specific data to the prompt.
    """

    role_name: str = ""

    async def _execute(
        self,
        agent_input: AgentInput,
        regime: RegimeContext | None,
    ) -> dict[str, Any]:
        """Run domain-specific analysis and produce a DomainMemo."""
        result = AgentResult(agent_role=self.role_name)

        # Extract candidate context
        candidate_data = agent_input.context.get("candidate", {})
        market_id = agent_input.market_id or candidate_data.get("market_id", "")

        # Build domain-specific prompt
        user_prompt = self._build_domain_prompt(candidate_data, regime)

        # Call LLM (Tier B)
        response = await self.call_llm(
            agent_input,
            user_prompt=user_prompt,
            regime=regime,
            result=result,
            max_tokens=2048,
        )

        # Parse response
        memo = self._parse_domain_memo(response.content, market_id, candidate_data)

        return memo.model_dump()

    def _build_domain_prompt(
        self,
        candidate: dict[str, Any],
        regime: RegimeContext | None,
    ) -> str:
        """Build domain-specific user prompt.

        Subclasses may override to add domain-specific instructions.
        """
        from datetime import UTC, datetime as _dt
        current_date = _dt.now(tz=UTC).strftime("%B %d, %Y")

        parts = [
            "Analyze this market candidate and produce a structured domain assessment.",
            "",
            f"IMPORTANT: Today's date is {current_date}. Reason about events relative to this date,",
            "not relative to your training data cutoff. This market is CURRENTLY ACTIVE on Polymarket.",
            "",
            f"Market: {candidate.get('title', 'Unknown')}",
            f"Category: {candidate.get('category', 'Unknown')}",
            f"Description: {candidate.get('description', 'N/A')}",
            f"Current Price: {candidate.get('price', 'N/A')}",
            f"Spread: {candidate.get('spread', 'N/A')}",
            f"Visible Depth: ${candidate.get('visible_depth_usd', 0):.0f}",
            f"Resolution Source: {candidate.get('resolution_source', 'N/A')}",
            "",
            "Your primary task is to estimate the true probability this market resolves YES.",
            "Provide your best probability estimate even under uncertainty — a range or uncertain estimate",
            "is more useful than refusing to estimate. The quantitative system will handle edge/risk decisions.",
            "",
            "Set recommended_proceed=true unless there is a SPECIFIC STRUCTURAL BARRIER such as:",
            "  - the market has already resolved",
            "  - the resolution criteria are fundamentally unanswerable",
            "  - the market question is based on a false premise",
            "Uncertainty, market efficiency, or low confidence are NOT reasons to set recommended_proceed=false.",
            "",
            "Respond with a JSON object containing:",
            '  "summary": brief analysis summary,',
            '  "key_findings": [list of key findings],',
            '  "concerns": [list of concerns or risks],',
            '  "recommended_proceed": true/false (default true unless specific structural barrier),',
            '  "estimated_probability": 0.0-1.0 (REQUIRED: your best estimate of the true YES probability),',
            '  "probability_direction": "overpriced"|"underpriced"|"fair" (vs current market price),',
            '  "optional_agents": [list of optional agents to invoke, if justified],',
            '  "optional_agents_justification": "reason for optional agents",',
            '  "confidence_level": "low"|"medium"|"high",',
            '  "domain_specific_data": {any domain-specific structured data}',
        ]

        return "\n".join(parts)

    def _parse_domain_memo(
        self,
        content: str,
        market_id: str,
        candidate: dict[str, Any],
    ) -> DomainMemo:
        """Parse LLM response into a DomainMemo."""
        try:
            data = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            # Try extracting JSON from markdown code blocks
            import re as _re
            match = _re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, _re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group(1))
                except (json.JSONDecodeError, TypeError):
                    data = {}
            else:
                data = {}
            # Non-blocking fallback: allow investigation to continue with low confidence
            data.setdefault("summary", content[:500])
            data.setdefault("recommended_proceed", True)

        # Parse and validate estimated_probability
        raw_prob = data.get("estimated_probability")
        estimated_prob = None
        if raw_prob is not None:
            try:
                estimated_prob = float(raw_prob)
                if not (0.0 <= estimated_prob <= 1.0):
                    estimated_prob = None
            except (ValueError, TypeError):
                estimated_prob = None

        # Parse probability_direction
        raw_direction = data.get("probability_direction")
        prob_direction = None
        if raw_direction in ("overpriced", "underpriced", "fair"):
            prob_direction = raw_direction

        return DomainMemo(
            category=candidate.get("category", "unknown"),
            market_id=market_id,
            summary=data.get("summary", ""),
            key_findings=data.get("key_findings", []),
            concerns=data.get("concerns", []),
            recommended_proceed=data.get("recommended_proceed", False),
            optional_agents_justified=data.get("optional_agents", []),
            optional_agents_justification=data.get("optional_agents_justification"),
            confidence_level=data.get("confidence_level", "low"),
            domain_specific_data=data.get("domain_specific_data", {}),
            estimated_probability=estimated_prob,
            probability_direction=prob_direction,
        )


# --- Six Category-Specific Domain Managers ---


class PoliticsDomainManager(BaseDomainManager):
    """Politics domain manager — emphasis on institutional dynamics,
    legislative processes, polling quality, and resolution source reliability."""

    role_name = "domain_manager_politics"

    def _build_domain_prompt(
        self,
        candidate: dict[str, Any],
        regime: RegimeContext | None,
    ) -> str:
        base = super()._build_domain_prompt(candidate, regime)
        domain_context = """

DOMAIN: POLITICS
Focus your analysis on:
- Institutional dynamics and power structures
- Legislative process stage and precedent
- Polling quality and methodology (if relevant)
- Resolution source reliability and potential bias
- Historical resolution patterns for similar political events
- Flag reflexive sentiment markets (polls about popularity, approval ratings)
"""
        return base + domain_context


class GeopoliticsDomainManager(BaseDomainManager):
    """Geopolitics domain manager — emphasis on diplomatic precedent,
    treaty frameworks, sanctions dynamics, and cross-jurisdiction reliability."""

    role_name = "domain_manager_geopolitics"

    def _build_domain_prompt(
        self,
        candidate: dict[str, Any],
        regime: RegimeContext | None,
    ) -> str:
        base = super()._build_domain_prompt(candidate, regime)
        domain_context = """

DOMAIN: GEOPOLITICS
Focus your analysis on:
- Diplomatic precedent and historical analogies
- Treaty frameworks and international law
- Sanctions dynamics and enforcement patterns
- Source reliability across jurisdictions
- Geopolitical interest alignment and pressure dynamics
- Information asymmetry from non-English language sources
"""
        return base + domain_context


class SportsDomainManager(BaseDomainManager):
    """Sports domain manager — elevated conservatism per quality gate."""

    role_name = "domain_manager_sports"

    def _build_domain_prompt(
        self,
        candidate: dict[str, Any],
        regime: RegimeContext | None,
    ) -> str:
        base = super()._build_domain_prompt(candidate, regime)
        domain_context = """

DOMAIN: SPORTS
Focus your analysis on:
- Whether resolution is fully objective (win/loss, final score, standings)
- Whether there is identifiable information asymmetry (injuries, lineup news, form, venue factors)
- Recent form, head-to-head history, and situational edges
- Resolution source reliability and timeline clarity
- For long-term markets (championships): consider market efficiency gaps from narrative bias
Always provide your best estimated_probability based on available information.
Proceed unless the market has already resolved or the resolution criteria are fundamentally unclear.
"""
        return base + domain_context


class TechnologyDomainManager(BaseDomainManager):
    """Technology domain manager — emphasis on regulatory timelines,
    product launch patterns, and latency-dominated markets."""

    role_name = "domain_manager_technology"

    def _build_domain_prompt(
        self,
        candidate: dict[str, Any],
        regime: RegimeContext | None,
    ) -> str:
        base = super()._build_domain_prompt(candidate, regime)
        domain_context = """

DOMAIN: TECHNOLOGY
Focus your analysis on:
- Regulatory timelines and precedent
- Product launch patterns and corporate communication signals
- Patent rulings and IP landscape
- Technical feasibility assessment
- Flag LATENCY-DOMINATED markets (breaking tech news, product drops)
- Assess information edge vs. market efficiency
"""
        return base + domain_context


class ScienceHealthDomainManager(BaseDomainManager):
    """Science & Health domain manager — emphasis on clinical trial phases,
    regulatory approval timelines, and expert consensus."""

    role_name = "domain_manager_science_health"

    def _build_domain_prompt(
        self,
        candidate: dict[str, Any],
        regime: RegimeContext | None,
    ) -> str:
        base = super()._build_domain_prompt(candidate, regime)
        domain_context = """

DOMAIN: SCIENCE & HEALTH
Focus your analysis on:
- Clinical trial phase and historical success rates for phase
- Regulatory approval timeline patterns (FDA, EMA)
- Publication patterns and pre-print significance
- Expert consensus formation and dissent
- Scientific evidence hierarchy (RCTs > observational > case reports)
- Domain knowledge barriers that create information asymmetry
"""
        return base + domain_context


class MacroPolicyDomainManager(BaseDomainManager):
    """Macro/Policy domain manager — emphasis on central bank communication,
    legislative calendars, and economic indicator patterns."""

    role_name = "domain_manager_macro_policy"

    def _build_domain_prompt(
        self,
        candidate: dict[str, Any],
        regime: RegimeContext | None,
    ) -> str:
        base = super()._build_domain_prompt(candidate, regime)
        domain_context = """

DOMAIN: MACRO/POLICY
Focus your analysis on:
- Central bank communication and forward guidance signals
- Legislative calendar and procedural requirements
- Economic indicator patterns and historical distributions
- Policy precedent and institutional behavior patterns
- Whether the market price appears to reflect all public information correctly
- Identify any specific factors that might cause mispricing (data surprises, political shocks, timing gaps)
Always provide your best estimated_probability. Proceed unless the resolution criteria are unanswerable.
"""
        return base + domain_context


# --- General (Fallback) Domain Manager ---


class GeneralDomainManager(BaseDomainManager):
    """General-purpose domain manager for markets that don't match a
    specific category. Uses broad analytical framing."""

    role_name = "domain_manager_general"

    def _build_domain_prompt(
        self,
        candidate: dict[str, Any],
        regime: RegimeContext | None,
    ) -> str:
        base = super()._build_domain_prompt(candidate, regime)
        domain_context = """

DOMAIN: GENERAL
This market does not fit a specific category. Apply broad analytical reasoning:
- Identify the core question and what would drive resolution
- Assess resolution source reliability and objectivity
- Check for structural biases or information asymmetry
- Consider base rates for similar types of predictions
- Evaluate whether public information is already priced in
- Be explicit about your estimated probability even if uncertain
"""
        return base + domain_context


# --- Domain Manager Factory ---

DOMAIN_MANAGERS: dict[str | None, type[BaseDomainManager]] = {
    "politics": PoliticsDomainManager,
    "geopolitics": GeopoliticsDomainManager,
    "sports": SportsDomainManager,
    "technology": TechnologyDomainManager,
    "science_health": ScienceHealthDomainManager,
    "macro_policy": MacroPolicyDomainManager,
    None: GeneralDomainManager,
}


def get_domain_manager_class(category: str | None) -> type[BaseDomainManager] | None:
    """Get the domain manager class for a given category.

    Falls back to GeneralDomainManager for unknown/unmapped categories.
    """
    return DOMAIN_MANAGERS.get(category) or DOMAIN_MANAGERS.get(None)
