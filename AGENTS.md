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

`CLAUDE.md` may be read, but do not edit it unless the user explicitly asks. For this repo, assume it is read-only.

If docs and code disagree:

- the docs describe the intended v4 target system
- the code and tests describe the current implemented baseline
- never assume a later phase exists just because the docs specify it

## Current State

As of the current repository snapshot:

- Phases 1 through 8 from [docs/Plan.md](docs/Plan.md) are substantially implemented and tested.
- The Phase 2 persistence layer is broad and includes the full schema footprint expected by the current tests and initial migration.
- Later workflow packages mostly exist as scaffolds only.

Implemented, tested areas:

- configuration and constants
- core enums and shared types
- structured logging
- SQLAlchemy models, repositories, database helpers, seed data, Alembic bootstrap migration
- market data clients, cache, fallback service, rate limiting
- eligibility classifier, hard rules, sports gate, profile scoring, edge scoring, engine
- scanner types, trigger detection, degraded mode, health monitor, async scanner loop
- risk drawdown, liquidity sizing, correlation, capital rules, sizer, governor
- cost estimation, budget tracking, selectivity tracking, review-cost tracking, feedback loop, governor
- agent registry, prompt manager, provider abstraction, compression, escalation policy, regime adapter, base agent types

Scaffold or mostly empty packages:

- `src/absence`
- `src/bias`
- `src/calibration`
- `src/dashboard_api`
- `src/execution`
- `src/investigation`
- `src/learning`
- `src/notifications`
- `src/positions`
- `src/tradeability`
- `src/viability`
- `src/workflows`

Important implication:

- do not describe those packages as implemented subsystems
- if you build in those areas, you are usually starting Phase 9+ work, not editing finished code

## Verified Baseline

The current test baseline was verified locally with:

```bash
./.venv/bin/pytest
```

Result:

- `620 passed`
- warnings only, no failures

The main warnings worth knowing about:

- `pytest-asyncio` deprecation warnings around the custom `event_loop` fixture in [tests/conftest.py](tests/conftest.py)
- an SQLAlchemy warning about a foreign-key cycle between `positions`, `thesis_cards`, and `workflow_runs` during SQLite drop ordering in tests

Do not "fix" those casually unless your task is specifically about test infrastructure or schema cleanup.

## Source Layout

The Python source layout is unusual and matters:

- Python modules live directly under `src/`
- imports are written as top-level packages such as `from config.settings import AppConfig`
- tests rely on `pythonpath = ["src"]` in [pyproject.toml](pyproject.toml)

This means:

- keep using the current top-level import style
- do not rewrite imports to `from src.config...` unless you are intentionally refactoring packaging across the repo
- when running the app directly, you need `PYTHONPATH=src`

The current startup command that works is:

```bash
PYTHONPATH=src ./.venv/bin/python -m src
```

The command documented in some repo docs, `python -m polymarket_trader`, does not match the current source layout. Treat the code as authoritative here.

## Hard Architectural Rules

These are non-negotiable unless the user explicitly asks for a design change.

### Deterministic Zones

The following are Tier D / deterministic-only areas and must not call LLMs:

- eligibility hard gates and category filtering
- trigger scanner hot path
- drawdown enforcement
- capital rules
- liquidity-relative sizing
- entry impact computation
- cost arithmetic and budget enforcement
- execution permission checks
- calibration statistics
- bias detection statistics
- viability metric computation
- operator absence logic
- base-rate lookup
- friction model calibration
- cache management

In code, this boundary is reflected primarily in:

- [src/core/constants.py](src/core/constants.py)
- [src/risk](src/risk)
- [src/cost](src/cost)
- [src/scanner](src/scanner)
- [src/eligibility](src/eligibility)

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

Any future investigation or review workflow that uses LLMs must be built so that:

- a pre-run estimate exists before the workflow starts
- a cost-governor decision is available before the workflow starts
- actual usage is recorded after the workflow completes

The existing implementation lives in:

- [src/cost/estimator.py](src/cost/estimator.py)
- [src/cost/governor.py](src/cost/governor.py)
- [src/cost/budget.py](src/cost/budget.py)
- [src/cost/selectivity.py](src/cost/selectivity.py)

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

- [src/config/settings.py](src/config/settings.py): Pydantic settings model loaded from YAML plus env vars
- [config/default.yaml](config/default.yaml): default thresholds and endpoints
- [src/core/enums.py](src/core/enums.py): canonical enums
- [src/core/constants.py](src/core/constants.py): model philosophy, provider mapping, deterministic-only list
- [src/core/types.py](src/core/types.py): shared Pydantic runtime types
- [src/logging_/logger.py](src/logging_/logger.py): structlog setup and async context binding

### Persistence

- [src/data/models/__init__.py](src/data/models/__init__.py): core trading entities
- [src/data/models/thesis.py](src/data/models/thesis.py): thesis cards and net-edge history
- [src/data/models/workflow.py](src/data/models/workflow.py): runs, triggers, eligibility decisions
- [src/data/models/*](src/data/models): calibration, cost, risk, reference, execution, notification, operator, scanner, bias, viability, logging, correlation
- [src/data/repositories/*](src/data/repositories): async repositories
- [src/data/database.py](src/data/database.py): engine and session helpers
- [src/data/seed.py](src/data/seed.py): base rates, thresholds, friction defaults
- [migrations/versions/5e8f04ccc37e_initial_schema.py](migrations/versions/5e8f04ccc37e_initial_schema.py): bootstrap migration via `Base.metadata`

### Deterministic Runtime Systems

- [src/market_data](src/market_data): Gamma client, CLOB client, subgraph fallback, cache, rate limiting, service
- [src/eligibility](src/eligibility): category classification, hard rules, sports gate, profile scoring, edge scoring, engine
- [src/scanner](src/scanner): trigger detection, degraded mode, health monitor, scanner loop
- [src/risk](src/risk): drawdown, liquidity, correlation, capital rules, sizer, governor
- [src/cost](src/cost): estimator, budget, selectivity, review costs, feedback, governor

### LLM Framework

- [src/agents/registry.py](src/agents/registry.py): role registry and tier assignments
- [src/agents/prompts.py](src/agents/prompts.py): role templates plus regime injection
- [src/agents/providers.py](src/agents/providers.py): provider router and per-call tracking
- [src/agents/base.py](src/agents/base.py): base agent and `call_llm`
- [src/agents/escalation.py](src/agents/escalation.py): Tier A escalation rules
- [src/agents/regime.py](src/agents/regime.py): calibration and viability regime adaptation
- [src/agents/types.py](src/agents/types.py): structured agent I/O and tracking records

## Development Conventions

### Typing and Data Shapes

Follow the established split:

- Pydantic `BaseModel` for runtime inputs, outputs, and in-process state
- SQLAlchemy ORM models for persistence
- explicit enums for domain states
- structured results with reason fields instead of ambiguous booleans

Avoid adding raw dictionaries as untyped public APIs when a runtime type should exist.

### Imports

Use the repository’s current import style:

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

Current test organization:

- focused module tests under `tests/test_*`
- phase-level tests such as [tests/test_phase2_data_model.py](tests/test_phase2_data_model.py), [tests/test_phase4_eligibility.py](tests/test_phase4_eligibility.py), [tests/test_phase5_scanner.py](tests/test_phase5_scanner.py), and [tests/test_phase8_agents.py](tests/test_phase8_agents.py)

When adding Phase 9+ code, follow the same pattern:

- add targeted unit tests for deterministic logic
- add integration-style tests around service orchestration
- add a phase-level test file when a new phase becomes substantial

### Database Changes

If you change the data model:

- update ORM models
- update repositories if queries change
- update seed data if applicable
- update or add Alembic migrations
- update tests

Be careful with the existing FK cycle between `positions`, `thesis_cards`, and `workflow_runs`.
If you change those relationships, expect SQLite test behavior and drop ordering to matter.

### Postgres vs SQLite Test Environment

Tests use in-memory SQLite, not Postgres.

Important test harness details from [tests/conftest.py](tests/conftest.py):

- PostgreSQL `JSONB` columns are remapped to generic `JSON`
- all models are imported through `data` so `Base.metadata` is complete
- foreign keys are enabled manually

If you introduce additional Postgres-specific behavior, ensure the test harness can still run or update it intentionally.

## Commands

Use the project virtualenv binaries directly when possible.

### Tests

```bash
./.venv/bin/pytest
./.venv/bin/pytest tests/test_phase4_eligibility.py
./.venv/bin/pytest tests/test_risk/test_governor.py -q
```

### App Startup

```bash
PYTHONPATH=src ./.venv/bin/python -m src
PYTHONPATH=src ./.venv/bin/python -m src config/default.yaml
```

Current behavior:

- startup logs system readiness
- no workflows are wired yet
- process waits indefinitely after logging `awaiting_shutdown`

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
- the working startup path is currently `PYTHONPATH=src ./.venv/bin/python -m src`
- do not assume `python -m polymarket_trader` works just because docs mention it

### Docker Is Not Ready

[docker-compose.yml](docker-compose.yml) references:

- a root `Dockerfile`
- a dashboard build under `dashboard/`

But:

- there is no root `Dockerfile` in the repo
- `dashboard/` is currently empty

So do not claim Docker or the dashboard are currently operational.

### Dashboard and API Are Planned, Not Implemented

The docs specify a Next.js dashboard and FastAPI dashboard API, but the repo does not contain those implementations yet.

### Many Later-Phase Packages Are Empty

Do not build features assuming the presence of:

- investigation orchestration
- tradeability engine
- execution engine
- position management runtime
- calibration runtime workflows
- notifications runtime
- dashboard API
- workflow orchestration

Those must be implemented deliberately.

### Secrets

`.env` is gitignored. Treat it as secret material.

Never:

- print secret values into logs
- copy `.env` contents into docs
- commit real credentials

If you need env-driven behavior, document the variable names, not the values.

## How to Extend the Repo Safely

If you are implementing Phase 9+ work:

1. preserve the deterministic/LLM boundary first
2. build deterministic substrate before agent orchestration
3. reuse the cost and risk governors rather than bypassing them
4. persist structured records before adding narrative helpers
5. add tests as you go

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

## Practical Working Rule

Treat this repository as an implementation of the v4 deterministic foundation plus the LLM framework, not as a finished end-to-end trader.

If you are asked to work on a later-phase feature, first identify:

- which v4 spec section it belongs to
- whether the deterministic prerequisite already exists
- which current modules can be reused
- which persistence records and tests need to be added

That distinction is the difference between extending the real codebase and writing speculative scaffolding.
