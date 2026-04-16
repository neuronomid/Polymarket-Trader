# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Polymarket Trader Agent — a selective, event-driven, cost-aware trading system for Polymarket prediction markets. Designed for a single operator-owner. The system discovers whether real edge exists against market consensus and survives the discovery process regardless of outcome.

## Tech Stack

- **Backend:** Python 3.12+, asyncio + asyncpg
- **Database:** PostgreSQL 16, SQLAlchemy 2.x + Alembic migrations; paper/shadow mode uses SQLite at `data/paper_trading.sqlite`
- **LLM SDKs:** `anthropic` (Opus 4.6, Sonnet 4.6), `openai` (GPT-5.4 nano/mini)
- **HTTP:** httpx (async)
- **API:** FastAPI (dashboard + internal APIs)
- **Dashboard:** Next.js 15 + React 19 + TypeScript
- **Notifications:** python-telegram-bot (async)
- **Testing:** pytest + pytest-asyncio
- **Config:** Pydantic Settings (YAML + env vars)

## Commands

All commands use the project virtualenv. `PYTHONPATH=src` is required for all backend invocations because modules live directly under `src/` and are imported as top-level packages.

```bash
# Run the application (preferred)
./start.sh
PYTHONPATH=src ./.venv/bin/python -m src
PYTHONPATH=src ./.venv/bin/python -m src config/default.yaml

# Tests
./.venv/bin/pytest -q
./.venv/bin/pytest tests/test_phase9_investigation.py -q
./.venv/bin/pytest tests/test_phase15c_workflows.py::test_name -v

# Linting / type checking
./.venv/bin/ruff check .
./.venv/bin/mypy src

# Database migrations
./.venv/bin/alembic upgrade head
./.venv/bin/alembic revision --autogenerate -m "description"

# Database seeding
PYTHONPATH=src ./.venv/bin/python -m data.seed postgresql+asyncpg://...

# Dashboard frontend (talks to backend API on http://localhost:8000)
cd dashboard && npm run dev   # http://localhost:3000
cd dashboard && npm run lint
```

> **Note:** `python -m polymarket_trader` is mentioned in some docstrings but does not work due to a packaging/entry-point inconsistency. Use `PYTHONPATH=src ./.venv/bin/python -m src` instead.

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

Recurring orchestrator tasks: scheduled sweep (8h), fast learning loop (daily), slow learning loop (weekly), absence monitor (hourly), governor reset (24h), dashboard state sync (5m).

## LLM Model Tiers (Critical Design Constraint)

Every LLM call must follow the tier system defined in `docs/modelsv4.md`:

| Tier | Model | Use | Cost Class |
|------|-------|-----|------------|
| A (Premium) | Claude Opus 4.6 | Final synthesis, adversarial review, weekly performance | H ($0.05-$0.30) |
| B (Workhorse) | Claude Sonnet 4.6 | Domain analysis, counter-case, tradeability, position review | M ($0.01-$0.05) |
| C (Utility) | GPT-5.4 nano/mini | Journals, alerts, evidence extraction, summaries | L ($0.001-$0.005) |
| D (No LLM) | Deterministic | Risk/Cost Governor, execution, scanner, calibration, all statistics | Z ($0) |

**Hard rules:** Deterministic checks before any LLM call. Pre-run cost estimation before multi-LLM workflows. No LLM in safety/risk zones. No LLM for statistical computation or bias detection. Every Tier A escalation must be logged and justified. Compress evidence before any Tier A call (see `src/agents/compression.py`).

## Operator Modes

Paper → Shadow → LiveSmall → LiveStandard (progressive rollout). Also: RiskReduction, EmergencyHalt, OperatorAbsent, ScannerDegraded.

`data/system_state.json` persists operator mode and paper state across restarts. Dashboard-persisted mode can override startup config — check this file if behavior seems inconsistent with config.

## Python Source Layout

Modules live directly under `src/` and are imported as top-level packages:

```python
from config.settings import AppConfig
from risk.types import RiskAssessment
```

Do not use `from src.config...` style imports. Tests rely on `pythonpath = ["src"]` in `pyproject.toml`.

## Tests

Current baseline (April 2026): **996 passed, 12 warnings**.

Test-to-subsystem mapping:
- Investigation changes → `tests/test_phase9_investigation.py`
- Tradeability / execution → `tests/test_phase10_tradeability_execution.py`
- Position review → `tests/test_phase11_position_management.py`
- Calibration / learning → `tests/test_phase12_calibration.py`, `tests/test_phase12_learning.py`
- Bias / viability / absence → `tests/test_phase13_cross_cutting.py`
- Notifications → `tests/test_phase14_notifications.py`
- Dashboard / orchestration → `tests/test_phase15_dashboard.py`, `tests/test_phase15c_workflows.py`

Tests use in-memory SQLite, not Postgres. `JSONB` columns are remapped to `JSON`. Foreign keys are enabled manually. The FK cycle between `positions`, `thesis_cards`, and `workflow_runs` can affect SQLite drop ordering — be aware when changing those relationships.

## Known Gaps

- **Entry point:** `python -m polymarket_trader` does not work. Use `PYTHONPATH=src ./.venv/bin/python -m src`.
- **Docker:** `docker-compose.yml` references a root `Dockerfile` and `dashboard/Dockerfile`, neither of which exist. Docker Compose is not end-to-end ready.
- **Live trading:** Live execution backend is a placeholder. Paper and shadow modes are the most complete operating modes.
- **Dashboard README:** `dashboard/README.md` is default `create-next-app` boilerplate; use code and tests as source of truth.

## Key Design Documents

- `docs/PRDV4.md` — Product requirements, user needs, acceptance criteria
- `docs/specv4.md` — Full technical specification (architecture, workflows, data model, risk controls)
- `docs/modelsv4.md` — LLM tier definitions, provider strategy, cost model
- `docs/Plan.md` — 15-phase implementation plan with deliverables and acceptance criteria
- `AGENTS.md` — Detailed agent/coding guide including code map, hard rules, and extension patterns

## Allowed Market Categories

Politics, Geopolitics, Technology, Science/Health, Macro/Policy, Sports (quality-gated with lower default sizing). Excluded: News, Culture, Crypto, Weather.
