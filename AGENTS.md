# AGENTS.md

## Purpose

This file is the working guide for coding agents operating in this repository.
It is project-specific. Follow it before making changes.

The repository is a Polymarket trading system with a strict deterministic-first design:

- agents may recommend
- deterministic rules may permit, resize, delay, reject, or force reduction
- no LLM may override deterministic safety, cost, or execution controls

## Read Order

When you start work here, read in this order:

1. [docs/PRDV4.md](docs/PRDV4.md)
2. [docs/specv4.md](docs/specv4.md)
3. [docs/modelsv4.md](docs/modelsv4.md)
4. [docs/Plan.md](docs/Plan.md)
5. [CLAUDE.md](CLAUDE.md) for extra repo guidance only

If you are editing the frontend under [dashboard](dashboard), also read:

- [dashboard/AGENTS.md](dashboard/AGENTS.md)

`CLAUDE.md` may be read, but do not edit it unless the user explicitly asks. For this repo, assume it is read-only.

If docs and code disagree:

- the docs describe the intended v4 target system
- the code and tests describe the current implemented baseline
- never assume a later phase exists just because the docs specify it

## Current State

As of April 16, 2026:

- the repository has moved well beyond the old Phase 1-8 baseline
- phases 1 through 15C from [docs/Plan.md](docs/Plan.md) now have substantial code and test coverage in this repo
- the current runtime is centered on [src/workflows/orchestrator.py](src/workflows/orchestrator.py), not just disconnected subsystem scaffolds
- paper and shadow workflows are the most complete operating modes
- live-mode execution is still not connected to a real exchange adapter

Implemented, tested areas:

- configuration, core enums, shared types, and structlog setup
- SQLAlchemy models, repositories, database helpers, seed data, and Alembic bootstrap migration
- market data clients, cache, fallback service, rate limiting, and watch-list integration
- eligibility classification, hard rules, sports gate, profile scoring, edge scoring, title/slug overrides, and engine
- scanner types, trigger detection, degraded mode, health monitor, and async scanner loop
- risk drawdown, liquidity sizing, correlation, capital rules, sizer, and governor
- cost estimation, budget tracking, selectivity tracking, review-cost tracking, feedback loop, and governor
- agent registry, prompt manager, provider routing, compression, escalation policy, regime adaptation, and base agent types
- investigation orchestration, base-rate system, entry-impact computation, domain managers, proceed-blocker handling, quantitative no-trade context, research agents, rubric scoring, and thesis-card building
- tradeability resolution parsing and tradeability synthesis
- deterministic execution engine, friction calibration, and slippage tracking
- position review scheduling, deterministic-first checks, LLM escalation, exit classification, and paper mark-to-market updates
- calibration store, Brier computation, segment thresholds, sizing calibration, friction feedback, and accumulation tracking
- learning loops, category ledger, no-trade monitoring, patience budget, performance review, and policy review
- bias detection and audit orchestration
- strategy viability checkpoints and lifetime budget tracking
- operator absence escalation and wind-down logic
- notifications event bus, formatting, Telegram delivery, repositories, and service layer
- FastAPI dashboard API, schemas, dashboard data services, and paper portfolio state persistence
- workflow scheduler, scheduled sweep ranking, trigger-to-candidate construction, and full-system orchestration
- Next.js dashboard frontend under [dashboard](dashboard)

Important current limitations:

- the live execution backend in [src/workflows/orchestrator.py](src/workflows/orchestrator.py) is still a placeholder that reports live execution as unavailable
- Docker Compose is still incomplete because the repo does not contain the Dockerfiles referenced by [docker-compose.yml](docker-compose.yml)
- the dashboard exists, but [dashboard/README.md](dashboard/README.md) is still mostly default `create-next-app` boilerplate and should not be treated as the authoritative workflow guide

## Verified Baseline

The current local test baseline was verified on April 16, 2026 with:

```bash
./.venv/bin/pytest -q
```

Result:

- `996 passed`
- `12 warnings`

The main warnings worth knowing about:

- `pytest-asyncio` deprecation warnings around the custom `event_loop` fixture in [tests/conftest.py](tests/conftest.py)
- an SQLAlchemy warning about a foreign-key cycle between `positions`, `thesis_cards`, and `workflow_runs` during SQLite drop ordering in tests

Do not claim the suite is fully green on a different commit or worktree unless you rerun it there.

## Runtime Workflow

The current backend entrypoint is [src/__main__.py](src/__main__.py).
Startup now does real system wiring:

- loads config
- initializes [src/workflows/orchestrator.py](src/workflows/orchestrator.py)
- starts market data and scanner services
- starts scheduled background tasks
- starts the FastAPI dashboard API on port `8000`
- waits for shutdown signals or dashboard-triggered stop

The orchestrated pipeline is:

- Eligibility Intake
- Trigger Scanner
- Investigation
- Tradeability
- Risk Approval
- Cost Approval
- Execution
- Position Review
- Calibration
- Performance Review
- Policy Review
- Viability
- Bias Audit
- Absence Management

Recurring tasks currently registered by the orchestrator:

- scheduled sweep every 8 hours
- fast learning loop daily
- slow learning loop weekly
- absence monitor hourly
- daily governor reset every 24 hours
- dashboard state sync every 5 minutes

Mode-specific behavior:

- `paper` and `shadow` mode use local SQLite at `data/paper_trading.sqlite`
- `paper` mode debits cash on entry, persists `paper_transactions`, tracks open exposure as `paper_reserved_capital_usd`, and updates equity mark-to-market during dashboard sync
- all other operator modes use configured Postgres, but final live execution is not wired
- dashboard state such as operator mode, paper balance, and paper transaction history persists in `data/system_state.json`
- dashboard-persisted operator mode can override the startup config on later restarts

## Current Behavior To Preserve

- Investigation domain managers are expected to return `estimated_probability` on every memo.
- `recommended_proceed=false` is reserved for structural blockers such as resolved markets, false premises, backward sides, factual errors, or fundamentally unanswerable resolution criteria.
- Low confidence, possible market efficiency, or thin calibration are not structural blockers; those cases should remain proceed-with-caution and be normalized downstream rather than hard-rejected.
- Scheduled sweep ranking should prefer edge-discovery quality over raw liquidity alone, and trigger-built sports candidates must still honor the configured sports horizon gate.
- Paper-mode execution should preserve the live-style accounting split between cash, reserved capital, and mark-to-market equity, and dashboard portfolio views should expose that split.
- Eligibility should continue using title/slug override patterns for sports and geopolitics when upstream category metadata is weak.

## Source Layout

The Python source layout is unusual and still matters:

- Python modules live directly under `src/`
- imports are written as top-level packages such as `from config.settings import AppConfig`
- tests rely on `pythonpath = ["src"]` in [pyproject.toml](pyproject.toml)

This means:

- keep using the current top-level import style
- do not rewrite imports to `from src.config...` unless you are intentionally refactoring packaging across the repo
- when running the backend directly, you need `PYTHONPATH=src`

Repository layout that matters in practice:

- [src](src): backend runtime and subsystems
- [dashboard](dashboard): Next.js 16 / React 19 dashboard frontend
- [config](config): YAML config
- [migrations](migrations): Alembic
- [data](data): runtime state files such as `paper_trading.sqlite` and `system_state.json`

If you work in [dashboard](dashboard):

- read [dashboard/AGENTS.md](dashboard/AGENTS.md) first
- treat `.next/` and `node_modules/` as generated artifacts

## Hard Architectural Rules

These are non-negotiable unless the user explicitly asks for a design change.

### Deterministic Zones

The following are Tier D / deterministic-only areas and must not call LLMs:

- eligibility hard gates and category filtering
- scanner hot path, degraded-mode handling, and cache management
- drawdown enforcement
- capital rules
- liquidity-relative sizing
- base-rate lookup and deviation arithmetic
- entry impact computation
- cost arithmetic, budgeting, and selectivity tracking
- execution permission checks and pre-trade revalidation
- realized slippage computation and friction parameter updates
- deterministic position review checks
- calibration statistics and segment threshold computation
- bias detection statistics
- viability metric computation
- operator absence logic

In code, this boundary is reflected primarily in:

- [src/core/constants.py](src/core/constants.py)
- [src/eligibility](src/eligibility)
- [src/scanner](src/scanner)
- [src/risk](src/risk)
- [src/cost](src/cost)
- [src/investigation/entry_impact.py](src/investigation/entry_impact.py)
- [src/execution](src/execution)
- [src/positions/deterministic_checks.py](src/positions/deterministic_checks.py)
- [src/calibration](src/calibration)
- [src/bias](src/bias)
- [src/viability](src/viability)
- [src/absence](src/absence)

### LLM Tier Policy

Model tiers are defined in:

- [docs/modelsv4.md](docs/modelsv4.md)
- [src/core/constants.py](src/core/constants.py)
- [src/agents/registry.py](src/agents/registry.py)

Use:

- Tier A: Claude Opus 4.6 for rare, high-value synthesis
- Tier B: Claude Sonnet 4.6 for repeated reasoning
- Tier C: GPT-5.4 nano or mini for utility work
- Tier D: deterministic only

Never:

- invoke Tier A without justification and logging
- use any LLM inside Tier D zones
- use an LLM to compute metrics that are already deterministic
- use an LLM to audit its own reasoning bias

### Compression-First Rule

Before any Tier A call:

- deduplicate evidence
- compress logs to decision-critical fields
- strip boilerplate
- send only material context

Use the existing utilities in [src/agents/compression.py](src/agents/compression.py). Do not bypass them with ad hoc huge prompts.

### Cost Governor Gate

Any workflow that uses LLMs must be built so that:

- a pre-run estimate exists before the workflow starts
- a cost-governor decision is available before the workflow starts
- actual usage is recorded after the workflow completes

The existing implementation lives in:

- [src/cost/estimator.py](src/cost/estimator.py)
- [src/cost/governor.py](src/cost/governor.py)
- [src/cost/budget.py](src/cost/budget.py)
- [src/cost/selectivity.py](src/cost/selectivity.py)
- [src/cost/review_costs.py](src/cost/review_costs.py)
- [src/cost/feedback.py](src/cost/feedback.py)

### Risk Governor Authority

The Risk Governor is the highest authority for capital protection.
No LLM output may override it.

The current implementation lives in:

- [src/risk/governor.py](src/risk/governor.py)
- [src/risk/capital_rules.py](src/risk/capital_rules.py)
- [src/risk/liquidity.py](src/risk/liquidity.py)
- [src/risk/correlation.py](src/risk/correlation.py)
- [src/risk/sizer.py](src/risk/sizer.py)

## Market-Scope Rules

Allowed categories:

- politics
- geopolitics
- technology
- science_health
- macro_policy
- sports

Excluded categories:

- news
- culture
- crypto
- weather

Sports is special:

- it is quality-gated
- it carries a reduced size multiplier until calibration threshold is met
- it requires objective resolution and a longer horizon

Do not add logic that lets excluded categories flow into downstream workflows unless the user explicitly asks for a scope change and the docs are updated accordingly.

## Code Map

### Core and Config

- [src/config/settings.py](src/config/settings.py): Pydantic settings model loaded from YAML, env vars, and local `.env`
- [config/default.yaml](config/default.yaml): default thresholds, budgets, and API settings
- [src/core/enums.py](src/core/enums.py): canonical enums
- [src/core/constants.py](src/core/constants.py): model philosophy, provider mapping, deterministic-only list
- [src/core/types.py](src/core/types.py): shared Pydantic runtime types
- [src/logging_/logger.py](src/logging_/logger.py): structlog setup and async context binding

### Persistence

- [src/data/models](src/data/models): ORM models for trading, workflow, calibration, risk, cost, execution, notification, bias, and viability records
- [src/data/repositories](src/data/repositories): async repositories
- [src/data/database.py](src/data/database.py): engine and session helpers
- [src/data/seed.py](src/data/seed.py): base rates, thresholds, and friction defaults
- [migrations/versions/5e8f04ccc37e_initial_schema.py](migrations/versions/5e8f04ccc37e_initial_schema.py): bootstrap migration via `Base.metadata`

### Market Intake and Governors

- [src/market_data](src/market_data): Gamma client, CLOB client, secondary source, cache, rate limiting, and service
- [src/eligibility](src/eligibility): category classification, hard rules, sports gate, scoring, and engine
- [src/scanner](src/scanner): trigger detection, degraded mode, health monitor, and scanner loop
- [src/risk](src/risk): drawdown, liquidity, correlation, capital rules, sizer, and governor
- [src/cost](src/cost): estimator, budget, selectivity, review costs, feedback, and governor

### Investigation to Execution

- [src/investigation](src/investigation): investigation orchestrator, base-rate system, entry impact, domain managers, research agents, rubric, and thesis builder
- [src/tradeability](src/tradeability): resolution parser, tradeability synthesizer, and types
- [src/execution](src/execution): deterministic execution engine, friction calibration helpers, slippage tracking, and execution types
- [src/positions](src/positions): review scheduler, deterministic checks, review agents, exit classification, and manager

### Calibration, Learning, and Cross-Cutting Systems

- [src/calibration](src/calibration): forecast store, Brier engine, segment manager, sizing, friction, and accumulation
- [src/learning](src/learning): fast loop, slow loop, category ledger, performance review, policy review, no-trade monitor, and patience budget
- [src/bias](src/bias): deterministic bias detection and audit runner
- [src/viability](src/viability): checkpoint processor and lifetime budget logic
- [src/absence](src/absence): operator absence restrictions and wind-down management
- [src/notifications](src/notifications): event bus, formatter, Telegram client, repositories, and delivery service

### Orchestration and UI

- [src/workflows/orchestrator.py](src/workflows/orchestrator.py): end-to-end system lifecycle and pipeline routing
- [src/workflows/scheduler.py](src/workflows/scheduler.py): recurring task scheduler
- [src/workflows/types.py](src/workflows/types.py): runtime system state and pipeline result models
- [src/dashboard_api/app.py](src/dashboard_api/app.py): FastAPI dashboard routes and persisted shared system state
- [src/dashboard_api/services.py](src/dashboard_api/services.py): dashboard query and aggregation layer
- [dashboard/app/page.tsx](dashboard/app/page.tsx): main frontend dashboard shell
- [dashboard/lib/api.ts](dashboard/lib/api.ts): frontend API client for the dashboard backend

## Development Conventions

### Typing and Data Shapes

Follow the established split:

- Pydantic `BaseModel` for runtime inputs, outputs, and in-process state
- SQLAlchemy ORM models for persistence
- explicit enums for domain states
- structured results with reason fields instead of ambiguous booleans

Avoid adding raw dictionaries as untyped public APIs when a runtime type should exist.

### Imports

Use the repository's current import style:

- `from config.settings import AppConfig`
- `from risk.types import RiskAssessment`

Do not mix in `src.` prefixes unless doing a package-layout refactor.

### Logging

Use `structlog` and bind a meaningful `component`.

Pattern:

```python
import structlog

_log = structlog.get_logger(component="my_component")
```

For async workflow context, use the helpers in [src/logging_/logger.py](src/logging_/logger.py).

### Async and Dependency Injection

Most service code is async and dependency-injected.
Preserve that style.

Good patterns already present:

- injectable `httpx.AsyncClient`
- injectable config sections
- injectable rate limiters and service dependencies
- methods with clean, testable return types

### Tests Are Required

If you change behavior in implemented areas, add or update tests.

Current test organization includes:

- focused module tests under `tests/test_*`
- phase-level tests from [tests/test_phase2_data_model.py](tests/test_phase2_data_model.py) through [tests/test_phase15c_workflows.py](tests/test_phase15c_workflows.py)

In practice:

- investigation changes should usually update [tests/test_phase9_investigation.py](tests/test_phase9_investigation.py)
- tradeability or execution changes should usually update [tests/test_phase10_tradeability_execution.py](tests/test_phase10_tradeability_execution.py)
- position review changes should usually update [tests/test_phase11_position_management.py](tests/test_phase11_position_management.py)
- calibration and learning changes should usually update [tests/test_phase12_calibration.py](tests/test_phase12_calibration.py) and [tests/test_phase12_learning.py](tests/test_phase12_learning.py)
- bias, viability, or absence changes should usually update [tests/test_phase13_cross_cutting.py](tests/test_phase13_cross_cutting.py)
- notification changes should usually update [tests/test_phase14_notifications.py](tests/test_phase14_notifications.py)
- dashboard API or orchestration changes should usually update [tests/test_phase15_dashboard.py](tests/test_phase15_dashboard.py) or [tests/test_phase15c_workflows.py](tests/test_phase15c_workflows.py)

### Database Changes

If you change the data model:

- update ORM models
- update repositories if queries change
- update seed data if applicable
- update or add Alembic migrations
- update tests
- consider whether dashboard queries in [src/dashboard_api/services.py](src/dashboard_api/services.py) also need updates

Be careful with the existing FK cycle between `positions`, `thesis_cards`, and `workflow_runs`.
If you change those relationships, expect SQLite test behavior and drop ordering to matter.

### Postgres vs SQLite Test and Runtime Environments

Tests use in-memory SQLite, not Postgres.

Important test harness details from [tests/conftest.py](tests/conftest.py):

- PostgreSQL `JSONB` columns are remapped to generic `JSON`
- all models are imported through `data` so `Base.metadata` is complete
- foreign keys are enabled manually

Important runtime detail:

- paper and shadow mode also use SQLite, but at `data/paper_trading.sqlite`
- all other operator modes use configured Postgres URLs from [src/config/settings.py](src/config/settings.py)

If you introduce additional Postgres-specific behavior, ensure the test harness can still run or update it intentionally.

## Commands

Use the project virtualenv binaries directly when possible.

### Tests

```bash
./.venv/bin/pytest -q
./.venv/bin/pytest tests/test_phase9_investigation.py -q
./.venv/bin/pytest tests/test_phase15c_workflows.py -q
./.venv/bin/pytest tests/test_risk/test_governor.py -q
```

### Backend Startup

```bash
./start.sh
PYTHONPATH=src ./.venv/bin/python -m src
PYTHONPATH=src ./.venv/bin/python src/__main__.py
PYTHONPATH=src ./.venv/bin/python -m src config/default.yaml
```

Current behavior:

- startup initializes the orchestrator and subsystem graph
- scanner and scheduled tasks are started
- the FastAPI dashboard API is started on `http://localhost:8000`
- the process waits until a shutdown signal or dashboard stop request is received

### Dashboard Frontend

```bash
cd dashboard
npm run dev
npm run lint
```

The frontend defaults to `http://localhost:3000` and talks to the backend API on `http://localhost:8000` unless `NEXT_PUBLIC_API_URL` overrides it.

### Migrations

```bash
./.venv/bin/alembic upgrade head
```

### Seeding

Because of the current package layout, prefer:

```bash
PYTHONPATH=src ./.venv/bin/python -m data.seed postgresql+asyncpg://...
```

### Linting / Type Checking

Dev dependencies declare Ruff and mypy in [pyproject.toml](pyproject.toml). If they are installed in the venv, use:

```bash
./.venv/bin/ruff check .
./.venv/bin/mypy src
```

## Known Gaps and Pitfalls

These are important and easy to miss.

### Packaging / Entry-Point Inconsistency

- `pyproject.toml` package naming, docs, and runtime layout are not fully aligned
- the working backend startup path is still `PYTHONPATH=src ./.venv/bin/python -m src`
- do not assume `python -m polymarket_trader` works just because some docstrings mention it

### Docker Compose Is Still Not Ready End-to-End

[docker-compose.yml](docker-compose.yml) references:

- a root `Dockerfile`
- a dashboard `Dockerfile` under `dashboard/`

But:

- there is no root `Dockerfile` in the repo
- there is no `dashboard/Dockerfile` in the repo

So do not claim Docker Compose works end-to-end without adding those files.

### Live Trading Is Not Fully Wired

- shadow and paper share the full approval pipeline and differ only at the final execution backend
- live modes currently reach a placeholder backend in [src/workflows/orchestrator.py](src/workflows/orchestrator.py)
- do not describe the repo as having a finished exchange-connected live execution path

### Dashboard Docs Lag the Actual Implementation

- the frontend under [dashboard](dashboard) exists and is implemented
- the API under [src/dashboard_api](src/dashboard_api) exists and is implemented
- [dashboard/README.md](dashboard/README.md) is still mostly default scaffolding text, so use code and tests as the source of truth

### Persisted Runtime State Can Override Expectations

- `data/system_state.json` persists operator mode, paper-balance state, and `paper_transactions` across restarts
- dashboard-persisted mode can take precedence over config on later startup
- `data/paper_trading.sqlite` retains paper/shadow runtime data until you intentionally reset it

If behavior seems inconsistent with config, inspect those files before assuming the code is wrong.

### Secrets

`.env` is gitignored. Treat it as secret material.

Never:

- print secret values into logs
- copy `.env` contents into docs
- commit real credentials

If you need env-driven behavior, document the variable names, not the values.

## How to Extend the Repo Safely

When extending the current repo:

1. preserve the deterministic/LLM boundary first
2. prefer extending an existing subsystem over adding speculative parallel scaffolding
3. reuse the current workflow orchestrator, cost governor, risk governor, and notification layer rather than bypassing them
4. persist structured records before adding dashboard or narrative helpers
5. add or update phase tests as you go

For new LLM-powered workflows:

1. define structured input and output types
2. register agent roles in [src/agents/registry.py](src/agents/registry.py) if needed
3. add prompt templates in [src/agents/prompts.py](src/agents/prompts.py) if needed
4. route all calls through [src/agents/providers.py](src/agents/providers.py)
5. enforce compression before Tier A
6. use escalation policy instead of ad hoc Opus calls
7. attribute every call to workflow, market, and/or position context

For new deterministic workflows:

1. keep them free of agent/provider imports
2. return structured results with explicit reason fields
3. expose thresholds via config, not magic numbers
4. log state transitions clearly
5. test edge cases first

For dashboard work:

1. update backend schemas and services before wiring new frontend views
2. keep operator controls consistent with persisted dashboard state behavior
3. treat the backend API as the source of truth, not frontend mock assumptions

## Practical Working Rule

Treat this repository as an end-to-end paper/shadow trading runtime with deterministic governors, agentic investigation, dashboard API, and dashboard frontend.

Do not treat it as a finished production live-trading deployment.

If you are asked to work on a feature, first identify:

- which current subsystem owns it
- whether the deterministic prerequisite already exists
- whether the workflow orchestrator or dashboard service already has a hook for it
- which persistence records and tests need to move with it

That distinction is the difference between extending the real codebase and writing speculative scaffolding.
