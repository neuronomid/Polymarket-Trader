"""Alert composer agent.

Tier C utility model for formatting complex notification messages
(weekly performance summaries, critical events) that benefit from
LLM-assisted formatting beyond what templates provide.

Most messages use the deterministic formatter (formatter.py).
The composer is invoked only for:
    - Weekly performance summaries with synthesis
    - Complex critical alerts needing context
    - Detailed viability checkpoint reports

This agent follows the BaseAgent pattern and is registered
in the agent registry as ``alert_composer``.
"""

from __future__ import annotations

from typing import Any

import structlog

from agents.base import BaseAgent
from agents.types import AgentInput, AgentResult, RegimeContext

_log = structlog.get_logger(component="alert_composer")


class AlertComposerAgent(BaseAgent):
    """Tier C agent for composing human-readable notification messages.

    Takes structured event data and produces concise, scannable
    Telegram messages. Used only for complex events; simple events
    use deterministic template formatting.
    """

    role_name = "alert_composer"

    async def _execute(
        self,
        agent_input: AgentInput,
        regime: RegimeContext | None,
    ) -> dict[str, Any]:
        """Compose a formatted alert message from structured input.

        Input context should contain:
            - event_type: the notification type
            - severity: severity level
            - payload: the typed event payload as dict
            - format_instructions: optional formatting guidance

        Returns:
            dict with "formatted_message" key.
        """
        context = agent_input.context or {}
        event_type = context.get("event_type", "unknown")
        severity = context.get("severity", "info")
        payload = context.get("payload", {})
        instructions = context.get(
            "format_instructions",
            "Format as a concise, scannable Telegram message. "
            "Use emoji for visual structure. Keep under 500 characters "
            "where possible. Structured, timestamped, actionable.",
        )

        user_prompt = (
            f"Format this {severity.upper()} {event_type} notification "
            f"for the Polymarket Trading System operator.\n\n"
            f"Event data:\n{payload}\n\n"
            f"Format instructions: {instructions}\n\n"
            f"Rules:\n"
            f"- Concise and scannable\n"
            f"- Use severity emoji: ℹ️ INFO, ⚠️ WARNING, 🚨 CRITICAL\n"
            f"- Include all key data points\n"
            f"- Never include API keys, secrets, or credentials\n"
            f"- End with timestamp and reference ID if available"
        )

        result = AgentResult(agent_role=self.role_name)

        response = await self.call_llm(
            agent_input,
            user_prompt=user_prompt,
            regime=regime,
            result=result,
            max_tokens=1024,
            temperature=0.0,
        )

        return {
            "formatted_message": response.content.strip(),
            "llm_cost": result.total_cost_usd,
        }
