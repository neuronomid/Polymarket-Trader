"""Research pack agents — five default research agents per candidate.

Default research pack (spec Section 8.6, step 4):
1. Evidence Research Agent (Tier C) — collect/compress/structure evidence
2. Counter-Case Agent (Tier B) — strongest case against thesis
3. Resolution Review Agent (Tier B) — after deterministic parser
4. Timing/Catalyst Agent (Tier C) — timeline assessment
5. Market Structure Agent (Tier D metrics + Tier C summary)

Optional sub-agents (only when domain manager justifies):
6. Data Cross-Check Agent (Tier C) — verify data consistency
7. Sentiment Drift Agent (Tier C) — detect sentiment shifts
8. Source Reliability Agent (Tier C) — assess source reliability
"""

from __future__ import annotations

import json
from typing import Any

import structlog

from agents.base import BaseAgent
from agents.types import AgentInput, AgentResult, RegimeContext
from investigation.types import EvidenceItem

_log = structlog.get_logger(component="research_pack")


# ========================
# Evidence Research Agent (Tier C)
# ========================


class EvidenceResearchAgent(BaseAgent):
    """Collect, compress, and structure evidence from provided sources.

    Output: structured evidence items with source, freshness, and
    relevance scoring. Does NOT analyze or synthesize — only organizes.
    """

    role_name = "evidence_research"

    async def _execute(
        self,
        agent_input: AgentInput,
        regime: RegimeContext | None,
    ) -> dict[str, Any]:
        result = AgentResult(agent_role=self.role_name)
        candidate = agent_input.context.get("candidate", {})

        user_prompt = (
            "Extract, compress, and structure evidence from the following market context.\n\n"
            f"Market: {candidate.get('title', 'Unknown')}\n"
            f"Description: {candidate.get('description', 'N/A')}\n"
            f"Category: {candidate.get('category', 'Unknown')}\n"
            f"Resolution Source: {candidate.get('resolution_source', 'N/A')}\n"
            f"Tags: {candidate.get('tags', [])}\n\n"
            "Respond with a JSON object containing:\n"
            '  "evidence_items": [\n'
            '    {"content": "...", "source": "...", "freshness": "fresh|recent|stale", '
            '"relevance_score": 0.0-1.0, "url": "..."}\n'
            "  ]\n"
            "Focus on verifiable, factual evidence. Do NOT synthesize or conclude."
        )

        response = await self.call_llm(
            agent_input,
            user_prompt=user_prompt,
            regime=regime,
            result=result,
            max_tokens=2048,
        )

        try:
            data = json.loads(response.content)
            items = data.get("evidence_items", [])
        except (json.JSONDecodeError, TypeError):
            items = []

        evidence = [
            EvidenceItem(
                content=item.get("content", ""),
                source=item.get("source", "unknown"),
                freshness=item.get("freshness", "unknown"),
                relevance_score=float(item.get("relevance_score", 0.5)),
                url=item.get("url"),
            )
            for item in items
        ]

        return {"evidence": [e.model_dump() for e in evidence]}


# ========================
# Counter-Case Agent (Tier B)
# ========================


class CounterCaseAgent(BaseAgent):
    """Construct the strongest structured case AGAINST the proposed thesis.

    Finds weaknesses, not confirmations. Addresses: evidence gaps,
    alternative interpretations, resolution risks, market structure
    concerns, and timing vulnerabilities.
    """

    role_name = "counter_case"

    async def _execute(
        self,
        agent_input: AgentInput,
        regime: RegimeContext | None,
    ) -> dict[str, Any]:
        result = AgentResult(agent_role=self.role_name)
        candidate = agent_input.context.get("candidate", {})
        evidence = agent_input.context.get("evidence", [])
        domain_memo = agent_input.context.get("domain_memo", {})

        user_prompt = (
            "Construct the strongest structured case AGAINST the following thesis.\n\n"
            f"Market: {candidate.get('title', 'Unknown')}\n"
            f"Category: {candidate.get('category', 'Unknown')}\n"
            f"Domain Analysis: {domain_memo.get('summary', 'N/A')}\n"
            f"Key Findings: {domain_memo.get('key_findings', [])}\n\n"
            f"Evidence collected so far:\n{json.dumps(evidence[:5], indent=2, default=str)}\n\n"
            "Be rigorous and specific. Your job is to find weaknesses.\n\n"
            "Respond with a JSON object:\n"
            '  "strongest_arguments_against": ["..."],\n'
            '  "evidence_gaps": ["..."],\n'
            '  "resolution_risks": ["..."],\n'
            '  "alternative_interpretations": ["..."],\n'
            '  "timing_vulnerabilities": ["..."],\n'
            '  "strength_score": 0.0-1.0 (how strong is the counter-case)\n'
        )

        response = await self.call_llm(
            agent_input,
            user_prompt=user_prompt,
            regime=regime,
            result=result,
            max_tokens=2048,
        )

        try:
            return json.loads(response.content)
        except (json.JSONDecodeError, TypeError):
            return {"strength_score": 0.5, "strongest_arguments_against": [response.content[:200]]}


# ========================
# Resolution Review Agent (Tier B)
# ========================


class ResolutionReviewAgent(BaseAgent):
    """Evaluate contract resolution language after deterministic parser.

    Focus on residual ambiguity: undefined terms, conditional clauses,
    jurisdiction issues, counter-intuitive resolution scenarios.
    """

    role_name = "resolution_review"

    async def _execute(
        self,
        agent_input: AgentInput,
        regime: RegimeContext | None,
    ) -> dict[str, Any]:
        result = AgentResult(agent_role=self.role_name)
        candidate = agent_input.context.get("candidate", {})

        user_prompt = (
            "Review the resolution language for this contract.\n\n"
            f"Market: {candidate.get('title', 'Unknown')}\n"
            f"Description: {candidate.get('description', 'N/A')}\n"
            f"Resolution Source: {candidate.get('resolution_source', 'N/A')}\n"
            f"End Date: {candidate.get('end_date', 'N/A')}\n\n"
            "Evaluate for residual ambiguity after deterministic checks.\n\n"
            "Respond with a JSON object:\n"
            '  "clarity_score": 0.0-1.0,\n'
            '  "has_named_source": true/false,\n'
            '  "has_deadline": true/false,\n'
            '  "has_ambiguous_wording": true/false,\n'
            '  "ambiguity_flags": ["..."],\n'
            '  "counter_intuitive_resolution_risk": true/false,\n'
            '  "undefined_terms": ["..."],\n'
            '  "resolution_interpretation": "verbatim source language + system interpretation"\n'
        )

        response = await self.call_llm(
            agent_input,
            user_prompt=user_prompt,
            regime=regime,
            result=result,
            max_tokens=1536,
        )

        try:
            return json.loads(response.content)
        except (json.JSONDecodeError, TypeError):
            return {"clarity_score": 0.5, "has_ambiguous_wording": True}


# ========================
# Timing/Catalyst Agent (Tier C)
# ========================


class TimingCatalystAgent(BaseAgent):
    """Assess timeline clarity: catalyst dates, event windows, time pressure."""

    role_name = "timing_catalyst"

    async def _execute(
        self,
        agent_input: AgentInput,
        regime: RegimeContext | None,
    ) -> dict[str, Any]:
        result = AgentResult(agent_role=self.role_name)
        candidate = agent_input.context.get("candidate", {})

        user_prompt = (
            "Assess the timing and catalyst profile for this market.\n\n"
            f"Market: {candidate.get('title', 'Unknown')}\n"
            f"Category: {candidate.get('category', 'Unknown')}\n"
            f"End Date: {candidate.get('end_date', 'N/A')}\n"
            f"Description: {candidate.get('description', 'N/A')}\n\n"
            "Respond with a JSON object:\n"
            '  "expected_catalyst": "description of expected catalyst event",\n'
            '  "expected_catalyst_date": "ISO date or null",\n'
            '  "expected_time_horizon": "days|weeks|months",\n'
            '  "expected_time_horizon_hours": integer,\n'
            '  "timing_clarity_score": 0.0-1.0,\n'
            '  "time_pressure": "none|low|medium|high",\n'
            '  "catalyst_reliability": 0.0-1.0\n'
        )

        response = await self.call_llm(
            agent_input,
            user_prompt=user_prompt,
            regime=regime,
            result=result,
            max_tokens=1024,
        )

        try:
            return json.loads(response.content)
        except (json.JSONDecodeError, TypeError):
            return {"timing_clarity_score": 0.5, "expected_time_horizon": "unknown"}


# ========================
# Market Structure Agent (Tier D metrics + Tier C summary)
# ========================


class MarketStructureAgent(BaseAgent):
    """Market structure analysis. Metrics are computed deterministically;
    the LLM (Tier C) provides a narrative summary of the metrics."""

    role_name = "market_structure_summary"

    async def _execute(
        self,
        agent_input: AgentInput,
        regime: RegimeContext | None,
    ) -> dict[str, Any]:
        candidate = agent_input.context.get("candidate", {})

        # Tier D: Compute metrics deterministically
        metrics = self._compute_structure_metrics(candidate)

        # Tier C: Generate narrative summary
        result = AgentResult(agent_role=self.role_name)
        user_prompt = (
            "Describe what the following market structure metrics mean for tradability.\n\n"
            f"Market: {candidate.get('title', 'Unknown')}\n"
            f"Metrics:\n{json.dumps(metrics, indent=2)}\n\n"
            "Do NOT compute any metrics. Only describe what the provided numbers mean.\n"
            "Keep the summary concise (3-5 sentences)."
        )

        response = await self.call_llm(
            agent_input,
            user_prompt=user_prompt,
            regime=regime,
            result=result,
            max_tokens=512,
        )

        return {
            "metrics": metrics,
            "summary": response.content,
        }

    def _compute_structure_metrics(self, candidate: dict) -> dict[str, Any]:
        """Compute market structure metrics deterministically (Tier D)."""
        price = candidate.get("price")
        spread = candidate.get("spread")
        depth = candidate.get("visible_depth_usd", 0)
        volume = candidate.get("volume_24h")

        metrics: dict[str, Any] = {
            "price": price,
            "spread": spread,
            "depth_usd": depth,
            "volume_24h": volume,
        }

        # Spread quality score (0-1, higher = better)
        if spread is not None:
            if spread < 0.02:
                metrics["spread_quality"] = "excellent"
            elif spread < 0.05:
                metrics["spread_quality"] = "good"
            elif spread < 0.10:
                metrics["spread_quality"] = "fair"
            else:
                metrics["spread_quality"] = "poor"

        # Depth adequacy
        if depth > 0:
            max_position = depth * 0.12
            metrics["max_position_from_depth"] = round(max_position, 2)
            metrics["depth_adequate"] = depth > 1000

        # Price extremity (markets near 0 or 1 have different dynamics)
        if price is not None:
            if price < 0.05 or price > 0.95:
                metrics["price_extreme"] = True
                metrics["price_zone"] = "extreme"
            elif price < 0.15 or price > 0.85:
                metrics["price_extreme"] = False
                metrics["price_zone"] = "tail"
            else:
                metrics["price_extreme"] = False
                metrics["price_zone"] = "mid"

        return metrics


# ========================
# Optional Sub-Agents (Tier C)
# ========================


class DataCrossCheckAgent(BaseAgent):
    """Verify data consistency across sources (optional, Tier C)."""

    role_name = "evidence_research"  # Reuse the evidence research role for cost tracking

    async def _execute(
        self,
        agent_input: AgentInput,
        regime: RegimeContext | None,
    ) -> dict[str, Any]:
        result = AgentResult(agent_role="data_cross_check")
        evidence = agent_input.context.get("evidence", [])

        user_prompt = (
            "Cross-check the following evidence items for consistency.\n\n"
            f"Evidence:\n{json.dumps(evidence[:8], indent=2, default=str)}\n\n"
            "Identify contradictions, inconsistencies, or data quality issues.\n"
            "Respond with JSON: {\"consistent\": true/false, \"issues\": [\"...\"]}"
        )

        response = await self.call_llm(
            agent_input,
            user_prompt=user_prompt,
            regime=regime,
            result=result,
            max_tokens=1024,
        )

        try:
            return json.loads(response.content)
        except (json.JSONDecodeError, TypeError):
            return {"consistent": True, "issues": []}


class SentimentDriftAgent(BaseAgent):
    """Detect sentiment shifts relevant to thesis (optional, Tier C)."""

    role_name = "evidence_research"

    async def _execute(
        self,
        agent_input: AgentInput,
        regime: RegimeContext | None,
    ) -> dict[str, Any]:
        result = AgentResult(agent_role="sentiment_drift")
        candidate = agent_input.context.get("candidate", {})

        user_prompt = (
            "Analyze whether there are recent sentiment shifts for this market.\n\n"
            f"Market: {candidate.get('title', 'Unknown')}\n"
            f"Current Price: {candidate.get('price', 'N/A')}\n\n"
            "Respond with JSON: {\"drift_detected\": true/false, \"direction\": \"positive|negative|neutral\", "
            "\"magnitude\": 0.0-1.0, \"drivers\": [\"...\"]}"
        )

        response = await self.call_llm(
            agent_input,
            user_prompt=user_prompt,
            regime=regime,
            result=result,
            max_tokens=1024,
        )

        try:
            return json.loads(response.content)
        except (json.JSONDecodeError, TypeError):
            return {"drift_detected": False}


class SourceReliabilityAgent(BaseAgent):
    """Assess reliability of key evidence sources (optional, Tier C)."""

    role_name = "evidence_research"

    async def _execute(
        self,
        agent_input: AgentInput,
        regime: RegimeContext | None,
    ) -> dict[str, Any]:
        result = AgentResult(agent_role="source_reliability")
        evidence = agent_input.context.get("evidence", [])

        user_prompt = (
            "Assess the reliability of sources in the following evidence.\n\n"
            f"Evidence:\n{json.dumps(evidence[:8], indent=2, default=str)}\n\n"
            "Respond with JSON: {\"sources\": [{\"source\": \"...\", \"reliability\": 0.0-1.0, "
            "\"type\": \"official|journalistic|social|unknown\"}], \"overall_reliability\": 0.0-1.0}"
        )

        response = await self.call_llm(
            agent_input,
            user_prompt=user_prompt,
            regime=regime,
            result=result,
            max_tokens=1024,
        )

        try:
            return json.loads(response.content)
        except (json.JSONDecodeError, TypeError):
            return {"overall_reliability": 0.5}
