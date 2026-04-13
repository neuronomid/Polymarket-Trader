# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Polymarket Trader Agent — a selective, event-driven, cost-aware trading system for Polymarket prediction markets. Designed for a single operator-owner. The system discovers whether real edge exists against market consensus and survives the discovery process regardless of outcome.

## Tech Stack

- **Backend:** Python 3.12+, asyncio + asyncpg
- **Database:** PostgreSQL 16, SQLAlchemy 2.x + Alembic migrations
- **LLM SDKs:** `anthropic` (Opus 4.6, Sonnet 4.6), `openai` (GPT-5.4 nano/mini)
- **HTTP:** httpx (async)
- **API:** FastAPI (dashboard + internal APIs)
- **Dashboard:** Next.js 15 + React 19 + TypeScript (Recharts or Tremor for charts)
- **Notifications:** python-telegram-bot (async)
- **Testing:** pytest + pytest-asyncio
- **Config:** Pydantic Settings (YAML + env vars)
- **Containerization:** Docker + Docker Compose

## Expected Commands

```bash
# Run the application
python -m polymarket_trader

# Database migrations
alembic upgrade head
alembic revision --autogenerate -m "description"

# Tests
pytest
pytest tests/path/to/test_file.py
pytest tests/path/to/test_file.py::test_function_name -v

# Docker
docker compose up -d          # Start all services (PostgreSQL, app, dashboard)
docker compose up -d postgres  # Just the database

# Dashboard (Next.js)
cd dashboard && npm run dev
```

## Architecture (7 Layers + 3 Cross-Cutting Systems)

The system processes markets through a pipeline of layers, each with strict authority boundaries:

1. **Market Intake & Eligibility Gate** — Deterministic filtering. Rejects excluded categories (News, Culture, Crypto, Weather), low-quality markets, insufficient liquidity. No LLM.
2. **Trigger Scanner** — Continuous polling loop (1-5 min). Detects price moves, spread changes, depth shifts. Serves from local cache during outages. No LLM in hot path.
3. **Investigation Engine** — Runs only when triggered. Multi-agent research with cost-staged LLM usage. Produces thesis cards.
4. **Tradeability & Resolution Engine** — Checks market wording, ambiguity, liquidity-relative sizing.
5. **Risk Governor & Cost Governor** — Deterministic veto authority. Risk Governor protects capital (drawdown ladder, exposure limits). Cost Governor gates LLM spend (pre-run estimation, lifetime budget). No LLM may override either.
6. **Execution Engine** — Fully deterministic. Pre-trade revalidation, entry impact check, slippage recording.
7. **Position Review & Calibration** — Tiered review frequency. Deterministic-first: ~65% of reviews use no LLM. Shadow forecasts build calibration before live sizing.

**Cross-cutting:** Strategy Viability (Brier score comparison vs market), Bias Detection (statistical only, no LLM self-auditing), Operator Absence (autonomous safe-mode with graceful wind-down).

## LLM Model Tiers (Critical Design Constraint)

Every LLM call must follow the tier system defined in `docs/modelsv4.md`:

| Tier | Model | Use | Cost Class |
|------|-------|-----|------------|
| A (Premium) | Claude Opus 4.6 | Final synthesis, adversarial review, weekly performance | H ($0.05-$0.30) |
| B (Workhorse) | Claude Sonnet 4.6 | Domain analysis, counter-case, tradeability, position review | M ($0.01-$0.05) |
| C (Utility) | GPT-5.4 nano/mini | Journals, alerts, evidence extraction, summaries | L ($0.001-$0.005) |
| D (No LLM) | Deterministic | Risk/Cost Governor, execution, scanner, calibration, all statistics | Z ($0) |

**Hard rules:** Deterministic checks before any LLM call. Pre-run cost estimation before multi-LLM workflows. No LLM in safety/risk zones. No LLM for statistical computation or bias detection. Every Tier A escalation must be logged and justified.

## Operator Modes

Paper → Shadow → LiveSmall → LiveStandard (progressive rollout). Also: RiskReduction, EmergencyHalt, OperatorAbsent, ScannerDegraded.

## Key Design Documents

- `docs/PRDV4.md` — Product requirements, user needs, acceptance criteria
- `docs/specv4.md` — Full technical specification (architecture, workflows, data model, risk controls)
- `docs/modelsv4.md` — LLM tier definitions, provider strategy, cost model
- `docs/Plan.md` — 15-phase implementation plan with deliverables and acceptance criteria

## Allowed Market Categories

Politics, Geopolitics, Technology, Science/Health, Macro/Policy, Sports (quality-gated with lower default sizing). Excluded: News, Culture, Crypto, Weather.

## Project Structure

```
polymarket_trader/
├── src/           # Python source (config, core, data, market_data, eligibility,
│                  #   scanner, risk, cost, agents, investigation, tradeability,
│                  #   execution, positions, calibration, learning, viability,
│                  #   bias, absence, notifications, dashboard_api, logging_, workflows)
├── dashboard/     # Next.js frontend
├── tests/
├── migrations/    # Alembic
├── config/        # YAML config files
└── docs/          # Design documents
```
