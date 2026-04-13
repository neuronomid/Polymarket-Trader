# Polymarket Trader Agent — Development Plan

## Document Status

v1.0 — Created 2026-04-13

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend / Core | Python 3.12+ |
| Database | PostgreSQL 16 |
| ORM / Migrations | SQLAlchemy 2.x + Alembic |
| Async Runtime | asyncio + asyncpg |
| LLM SDKs | anthropic (Opus 4.6, Sonnet 4.6), openai (GPT-5.4 nano/mini) |
| HTTP Client | httpx (async) |
| Task Scheduling | APScheduler or custom async scheduler |
| Telegram | python-telegram-bot (async) |
| Dashboard Frontend | Next.js 15 + React 19 + TypeScript |
| Dashboard Charts | Recharts or Tremor |
| Dashboard API | FastAPI (serves both dashboard and internal APIs) |
| Testing | pytest + pytest-asyncio |
| Config | Pydantic Settings (YAML/env-based) |
| Containerization | Docker + Docker Compose |

---

## Phase Overview

| # | Phase | Key Outcome | Depends On |
|---|-------|-------------|------------|
| 1 | Project Foundation & Configuration | Runnable project skeleton, config system, logging | — |
| 2 | Data Model & Persistence Layer | Full database schema, repository layer, migrations | 1 |
| 3 | Market Data Layer | CLOB API client, local cache, secondary source | 1, 2 |
| 4 | Eligibility Gate & Category Classification | Deterministic market filtering pipeline | 2, 3 |
| 5 | Trigger Scanner | Event-driven scanning loop with degraded-mode handling | 3, 4 |
| 6 | Risk Governor & Correlation Engine | Deterministic capital protection, drawdown ladder, liquidity sizing | 2 |
| 7 | Cost Governor & Budget System | Pre-run gating, post-run accounting, lifetime budget | 2 |
| 8 | LLM Integration & Agent Framework | Provider abstraction, agent orchestration, cost tracking | 1, 7 |
| 9 | Investigation Engine & Thesis Cards | Full investigation workflow, thesis card generation | 4, 5, 6, 7, 8 |
| 10 | Tradeability, Resolution & Execution | Resolution parser, execution engine, slippage tracking | 6, 7, 9 |
| 11 | Position Management & Review | Tiered reviews, deterministic-first, exit classification | 6, 7, 8, 10 |
| 12 | Calibration & Learning System | Shadow forecasts, Brier scores, category ledger, friction model | 2, 11 |
| 13 | Cross-Cutting Systems | Bias detection, strategy viability, operator absence | 6, 7, 12 |
| 14 | Operator Notifications (Telegram) | Event-driven notification delivery for all event types | All workflow phases |
| 15 | Dashboard & System Integration | Next.js dashboard, end-to-end workflows, Paper/Shadow mode | All phases |

---

## Phase 1: Project Foundation & Configuration

### Goal
Establish the project structure, configuration system, logging infrastructure, and core types that every subsequent phase builds on.

### Steps

1. **Project structure**
   ```
   polymarket_trader/
   ├── src/
   │   ├── config/           # Configuration management
   │   ├── core/             # Core types, enums, constants
   │   ├── data/             # Database models, repositories
   │   ├── market_data/      # CLOB API, cache, secondary source
   │   ├── eligibility/      # Eligibility gate, category classifier
   │   ├── scanner/          # Trigger scanner
   │   ├── risk/             # Risk Governor, correlation engine
   │   ├── cost/             # Cost Governor, budget tracking
   │   ├── agents/           # LLM integration, agent framework
   │   ├── investigation/    # Investigation engine
   │   ├── tradeability/     # Resolution parser, tradeability
   │   ├── execution/        # Execution engine, slippage
   │   ├── positions/        # Position management, reviews
   │   ├── calibration/      # Calibration, Brier scores
   │   ├── learning/         # Performance review, policy review
   │   ├── viability/        # Strategy viability system
   │   ├── bias/             # Bias detection system
   │   ├── absence/          # Operator absence system
   │   ├── notifications/    # Telegram and notification layer
   │   ├── dashboard_api/    # FastAPI for dashboard
   │   ├── logging_/         # Structured logging, journals
   │   └── workflows/        # Workflow orchestration
   ├── dashboard/            # Next.js frontend
   ├── tests/
   ├── migrations/           # Alembic migrations
   ├── docs/
   ├── config/               # YAML config files
   ├── pyproject.toml
   └── docker-compose.yml
   ```

2. **Configuration system** — Pydantic Settings loading from YAML + environment variables. Separate config sections for: system, risk limits, cost budgets, scanner intervals, eligibility thresholds, model tiers, Telegram, database, operator absence thresholds, calibration thresholds, lifetime budget, patience budget.

3. **Structured logging framework** — JSON-structured log entries with: timestamp, workflow_run_id, market_id, position_id, event_type, severity, and payload. Every log entry attributable to a workflow run.

4. **Core types and enums** — Define all shared types:
   - `Category` enum (Politics, Geopolitics, Technology, ScienceHealth, MacroPolicy, Sports)
   - `ExcludedCategory` enum (News, Culture, Crypto, Weather)
   - `EligibilityOutcome` enum (Reject, Watchlist, TriggerEligible, InvestigateNow)
   - `TriggerClass` enum (Discovery, Repricing, Liquidity, PositionStress, ProfitProtection, CatalystWindow, Operator)
   - `TriggerLevel` enum (A, B, C, D)
   - `RiskApproval` enum (Reject, Delay, Watch, ApproveReduced, ApproveNormal, ApproveSpecial)
   - `ExitClass` enum (all 11 exit types)
   - `OperatorMode` enum (Paper, Shadow, LiveSmall, LiveStandard, RiskReduction, EmergencyHalt, OperatorAbsent, ScannerDegraded)
   - `CalibrationRegime` enum (Insufficient, Sufficient, ViabilityUncertain)
   - `DrawdownLevel` enum (Normal, SoftWarning, RiskReduction, EntriesDisabled, HardKillSwitch)
   - `ReviewTier` enum (New, Stable, LowValue)
   - `ModelTier` enum (A, B, C, D)
   - `CostClass` enum (H, M, L, Z)
   - `NotificationSeverity` enum (INFO, WARNING, CRITICAL)
   - `NotificationType` enum (TradeEntry, TradeExit, RiskAlert, NoTrade, WeeklyPerformance, SystemHealth, StrategyViability, OperatorAbsence)
   - `CategoryQualityTier` enum (Standard, QualityGated)
   - All severity levels, notification types, etc.

5. **Model philosophy constants** — Encode the 11 V4 model principles as system constants:
   - Deterministic checks before any LLM call
   - Pre-run cost estimation before any multi-LLM workflow
   - Deterministic-first position review before LLM-based review
   - Cheap models for compression/extraction/formatting
   - Workhorse models for repeated meaningful reasoning
   - Premium models only at high-value synthesis/decision bottlenecks
   - One primary provider stack, one secondary for fallback
   - Every premium escalation explainable and logged
   - No LLM in any deterministic safety or risk control zone
   - No LLM for statistical computation, metric calculation, or bias detection
   - No LLM for auditing its own reasoning biases

6. **Provider strategy constants** — Define provider-model mapping:
   - Tier A (Premium): Claude Opus 4.6 — final synthesis, adversarial review, weekly performance
   - Tier B (Workhorse): Claude Sonnet 4.6 — domain managers, counter-case, tradeability, position review
   - Tier C (Utility): GPT-5.4 nano (default), GPT-5.4 mini (complex utility) — journals, alerts, evidence extraction, summaries, bias audit summaries, viability reports
   - Tier D (No LLM): All deterministic — Risk Governor, Cost Governor, Execution, Scanner, Calibration, entry impact, slippage, bias statistics, viability metrics, operator absence, position review checks, liquidity sizing, friction model, CLOB cache, base-rate lookup, lifetime budget
   - Cost class ranges: H ($0.05–$0.30), M ($0.01–$0.05), L ($0.001–$0.005), Z ($0)

7. **Docker Compose** — PostgreSQL service, application service, dashboard service.

### Deliverables
- Runnable Python project with `pyproject.toml`, dependency management
- Config loading from YAML with validation
- Structured JSON logging operational
- All core enums and types defined
- Docker Compose with PostgreSQL running
- Test infrastructure (pytest) working

### Acceptance Criteria
- `python -m polymarket_trader` starts without error
- Config loads and validates from YAML
- Structured logs emit valid JSON
- All core types importable and tested
- PostgreSQL accessible from application container

---

## Phase 2: Data Model & Persistence Layer

### Goal
Implement the full database schema from spec Section 25, with repository patterns for clean data access.

### Steps

1. **SQLAlchemy models** — Implement all core entities from spec Section 25.1:
   - `Market`, `Position`, `Order`, `Trade`
   - `ThesisCard` (with all fields from spec Section 14.2)
   - `WorkflowRun`, `TriggerEvent`, `EligibilityDecision`
   - `RiskSnapshot`, `RuleDecision`
   - `CostSnapshot`, `PreRunCostEstimate`, `CostGovernorDecision`
   - `CalibrationRecord`, `CalibrationSegment`, `ShadowForecastRecord`
   - `CategoryPerformanceLedgerEntry`
   - `EntryImpactEstimate`, `RealizedSlippageRecord`, `FrictionModelParameters`
   - `BiasAuditReport`, `BiasPatternRecord`
   - `OperatorInteractionEvent`, `OperatorAbsenceEvent`
   - `StrategyViabilityCheckpoint`, `LifetimeBudgetStatus`, `PatienceBudgetStatus`
   - `CLOBCacheEntry`, `ScannerDataSnapshot`, `ScannerHealthEvent`
   - `NotificationEvent`, `NotificationDeliveryRecord`
   - `JournalEntry`, `StructuredLogEntry`, `Alert`
   - `EventCluster`, `CorrelationGroup`
   - `ResolutionParseResult`, `SportsQualityGateResult`
   - `BaseRateReference`, `MarketImpliedProbabilitySnapshot`
   - `NetEdgeEstimate`, `CumulativeReviewCostRecord`
   - `CostOfSelectivityRecord`, `CalibrationAccumulationProjection`
   - `PolicyUpdateRecommendation`, `SystemHealthSnapshot`
   - `MarketQualitySnapshot`, `ShadowVsMarketComparisonRecord`
   - `CalibrationThresholdRegistry`

2. **Relationships** — Implement all relationships from spec Section 25.2.

3. **Repository layer** — One repository class per major entity group with async methods for CRUD and common queries.

4. **Alembic migrations** — Initial migration creating all tables.

5. **Seed data** — Base-rate reference data, calibration threshold registry defaults, default configuration values.

### Deliverables
- All SQLAlchemy models with proper relationships and indexes
- Repository layer with async database access
- Alembic migration system with initial migration
- Seed data scripts

### Acceptance Criteria
- `alembic upgrade head` creates all tables without error
- Repository CRUD operations tested for all major entities
- Foreign key relationships enforced
- All thesis card fields from spec Section 14.2 present in model

---

## Phase 3: Market Data Layer

### Goal
Build the Polymarket CLOB API client, local data cache, and secondary price source — the data foundation for the scanner and all downstream decisions.

### Steps

1. **CLOB API client** — Async httpx client for Polymarket CLOB API:
   - Fetch market list (active markets, metadata, categories)
   - Fetch order book per market (best bid/ask, depth at top N levels, spread)
   - Fetch last trade price/timestamp, market status
   - Rate limit handling with exponential backoff on 429s
   - Configurable polling interval (default: 60s per batch)
   - Health event emission on 5 consecutive failures per market

2. **Local CLOB data cache** — In-memory cache (with optional disk persistence):
   - Store every successful poll result with timestamp per market
   - Configurable cache depth (default: 4 hours)
   - Cache serving when API poll fails, with cache age flag
   - Freshness threshold (default: 3 minutes) — data older than this is stale
   - Cache eviction for data older than cache depth
   - Cache statistics (hit rate, age distribution)

3. **Secondary price source** — Client for Polymarket subgraph/GraphQL:
   - Basic price monitoring only
   - Used only when CLOB API unavailable
   - Not used for depth analysis or full trigger detection

4. **Market data types** — Data classes for:
   - `OrderBookSnapshot` (bids, asks, depth levels, spread, mid-price)
   - `MarketSnapshot` (price, status, last trade, depth, timestamp)
   - `CachedMarketData` (snapshot + cache metadata: age, source, freshness)

### Deliverables
- Working CLOB API client with rate limiting
- Local cache with configurable depth and freshness
- Secondary price source client
- Integration tests against Polymarket API (or mock)

### Acceptance Criteria
- API client fetches order book data correctly
- Cache serves stale data when API fails, flagged appropriately
- Cache eviction works within configured depth
- Rate limit backoff tested
- Secondary source provides basic price data

---

## Phase 4: Eligibility Gate & Category Classification

### Goal
Build the deterministic market filtering pipeline that prevents excluded categories and low-quality markets from reaching investigation.

### Steps

1. **Category classifier** — Deterministic pattern matching on market metadata:
   - Map market tags/slugs to allowed categories
   - Immediately reject excluded categories (News, Culture, Crypto, Weather)
   - Escalation to Tier C (LLM) only for genuinely unclear classification (rare)
   - Log every classification decision

2. **Hard eligibility rules** — Deterministic checks:
   - Market is open and tradable
   - Wording not obviously malformed
   - Resolution source named and defined
   - Contract horizon within configured range
   - Minimum observable liquidity threshold met
   - Spread within configured hard limit
   - Visible depth at top 3 levels sufficient for minimum position size ÷ liquidity fraction limit
   - No duplicate of currently held event cluster

3. **Sports Quality Gate** — Five criteria from spec Section 2.4:
   - Resolution fully objective (win/loss, final score)
   - Resolves in > 48 hours
   - Adequate liquidity and depth
   - Not primarily a statistical modeling problem
   - Credible evidential basis beyond public statistics
   - Output: `SportsQualityGateResult` record
   - Sports markets carry a **lower default size multiplier** than Standard Tier categories until category calibration threshold (40 resolved trades) met

4. **Preferred market profile filter** — Prioritize contracts that are:
   - Objectively resolvable against a named authoritative source
   - Not reflexive sentiment contests
   - Not dominated by latency advantages
   - Supported by verifiable public evidence across independent sources
   - Suitable for thesis-based holding over days to weeks
   - Liquid enough for reasonable entry/exit friction

5. **Edge discovery focus scoring** — Rank eligible markets by information asymmetry potential:
   - Prioritize: niche political events with limited coverage, specific policy decisions requiring technical interpretation, scientific outcomes with domain-knowledge barriers, timing-sensitive markets
   - Deprioritize: heavily covered events (major elections, championship finals, top-line economic releases) where market prices are likely already efficient

6. **Category quality tier assignment** — Tag each eligible market:
   - Standard Tier: Politics, Geopolitics, Technology, Science and Health, Macro/Policy
   - Quality-Gated Tier: Sports (lower default size multiplier until calibration threshold met)

7. **Eligibility output** — Tag each market: Reject (with reason code), Watchlist, Trigger-Eligible, or Investigate-Now.

8. **Eligibility logging** — Every decision logged with: market identifier, outcome, reason code, timestamp, eligibility rule version, depth snapshot.

### Deliverables
- Category classifier with excluded-category enforcement
- Full eligibility rule engine with all hard rules
- Sports Quality Gate with size multiplier
- Preferred market profile filter
- Edge discovery focus scoring
- Category quality tier assignment
- Eligibility decision logging with reason codes

### Acceptance Criteria
- Excluded categories never reach investigation
- Malformed/ambiguous contracts rejected before any LLM use
- Sports markets carry a Quality Gate result record
- Markets with insufficient depth rejected at intake
- All decisions logged with reason codes and timestamps
- 100% unit test coverage on eligibility rules

---

## Phase 5: Trigger Scanner

### Goal
Build the event-driven scanning loop that watches eligible and held-position markets, detects trigger conditions deterministically, and manages degraded-mode escalation.

### Steps

1. **Scanner polling loop** — Async loop:
   - Poll CLOB API at configured intervals (default: 60s per batch)
   - Store results in local cache
   - Serve from cache during short outages (< 3 min)
   - No LLM in hot path

2. **Trigger detection** — Deterministic signal detection:
   - Price move beyond threshold
   - Spread widening/narrowing past limits
   - Sudden depth change
   - Catalyst window approach
   - Held position sharp adverse/favorable move
   - Market status changes
   - Structured external event hooks (RSS, event APIs)

3. **Trigger classification** — Assign each trigger:
   - Class: Discovery, Repricing, Liquidity, PositionStress, ProfitProtection, CatalystWindow, Operator
   - Level: A (log only), B (lightweight review), C (full investigation/review), D (immediate risk intervention)

4. **Degraded mode escalation** — Time-based ladder:
   - Level 0: Cache served, normal operation (INFO log)
   - Level 1: Cache stale → alert, no new discovery triggers, stale flags
   - Level 2 (4+ hours): Position sizes reduced 15%, review frequency up, escalated alert
   - Level 3 (8+ hours): Graceful position reduction begins, critical alert
   - Recovery: API back → refill cache → return to normal

5. **Scanner health monitoring** — Emit `SystemHealthEvent` on infrastructure failures. Track: API availability, cache state, degraded mode level, last successful poll.

6. **Trigger logging** — Every trigger: class, level, market ID, data snapshot (price, spread, depth), reason, timestamp, data source (live/cache/secondary), escalation status.

### Deliverables
- Async scanner polling loop
- All trigger detection rules
- Degraded mode escalation ladder
- Scanner health monitoring
- Trigger event logging

### Acceptance Criteria
- Every trigger event logged with class, level, snapshot, timestamp
- Scanner failure degrades safely (no fake signals from stale data)
- Short outages served from cache without degraded mode
- 4+ hours → size reduction enforced
- 8+ hours → position reduction begins
- Scanner health is a distinct monitored status
- No LLM calls in scanner hot path

---

## Phase 6: Risk Governor & Correlation Engine

### Goal
Build the highest-authority capital protection layer. Fully deterministic. No LLM may override it.

### Steps

1. **Capital rules** — Configurable, deterministic:
   - Max daily new deployment (default: 10% of account balance)
   - Max daily drawdown (default: 8% of start-of-day equity, realized + unrealized)
   - Max total open exposure (configurable cap)
   - Max simultaneous positions (configurable cap)

2. **Drawdown defense ladder** — Staged escalation:
   - 3% → Soft Warning: higher evidence threshold, reduced size suggestions
   - 5% → Risk Reduction Mode: new entries materially reduced, low-conviction blocked
   - 6.5% → New Entries Disabled: no new entries, management/reduction only
   - 8% → Hard Kill Switch: all entries blocked, capital preservation

3. **Exposure rules** — Category limits, political/sports/tech cluster limits, correlation caps.

4. **Correlation engine** — Dedicated engine inside Risk Governor. Tag positions by:
   - Event cluster (same underlying event, e.g., two markets on the same election)
   - Narrative cluster (same driving narrative, e.g., "tech regulation crackdown")
   - Source dependency (same resolution source, e.g., same government agency)
   - Domain overlap (same category/sub-domain)
   - Catalyst overlap (same catalyst event, e.g., same court ruling)
   - Enforce: maximum cluster exposure, maximum simultaneous exposure to one catalyst family, maximum overlap of uncertainty sources
   - Prevents fake diversification — multiple markets that appear different but share hidden dependencies

5. **Liquidity-relative sizing** — Hard cap: no order > 12% of visible depth at top 3 levels. Computed from latest depth snapshot.

6. **Entry impact budget** — If entry impact estimate > 25% of gross edge → reduce size or reject.

7. **Operator absence / scanner degraded restrictions** — Enforce mode-specific constraints (no new entries, size reductions).

8. **Position sizing logic** — Size ∝ Edge × Confidence × Evidence Quality × Liquidity Quality × Remaining Budget, with penalties for ambiguity, correlation, weak sources, timing, disagreement. Also considers: model cost burden from Cost Governor, calibration regime confidence, and category-specific historical reliability.

9. **Confidence calibration** — Three distinct fields per position (spec Section 23):
   - **Probability Estimate:** raw model probability assessment
   - **Confidence Estimate:** how confident the system is in that probability
   - **Calibration Confidence:** how well calibrated the system's confidence is based on historical data
   - These are separate fields in the data model. Prevents over-sizing on fragile conviction.

10. **Risk approval output** — Reject, Delay, Watch, Approve Reduced, Approve Normal, Approve with Special Conditions (tighter revalidation, smaller initial size, operator acknowledgment, shortened review interval, staged entry, Sports multiplier reduction). All logged with rule reason and threshold.

11. **No-trade authority** — Explicit power to block all new trades when conditions warrant: positions consume opportunity budget, drawdown elevated, candidate quality insufficient, correlation burden too high, market conditions too noisy, or system confidence inadequate. The ability to do nothing is a required feature.

### Deliverables
- Complete Risk Governor with all rules
- Drawdown defense ladder with state tracking
- Correlation engine with cluster tagging and exposure limits
- Liquidity-relative sizing enforcement
- Position sizing formula with all input factors
- Confidence calibration (three separate fields)
- No-trade authority
- Risk decision logging

### Acceptance Criteria
- No candidate bypasses risk approval
- All reductions/rejections logged with rule reason and threshold
- Drawdown state changes visible in logs and alerts
- No order exceeds configured fraction of visible depth
- Operator-absent restrictions enforced when applicable
- Zero LLM calls in Risk Governor

---

## Phase 7: Cost Governor & Budget System

### Goal
Build the prospective and retrospective cost control system that prevents inference cost from consuming expected edge.

### Steps

1. **Pre-run cost estimation** — Before every investigation:
   - Classify run type (scheduled sweep, trigger-based, operator-forced)
   - Estimate token budget per agent/model
   - Compute `expected_run_cost_min` and `expected_run_cost_max`
   - **Use effective cost profile for position review** (65% Tier D/$0, 25% Tier B, 10% Tier A), not worst-case assigned tier
   - Compare to daily budget remaining AND lifetime budget remaining
   - Decision logic:
     - `expected_run_cost_max` within budget → approve at full tier
     - `expected_run_cost_max` breaches daily but `min` does not → approve at reduced tier ceiling or reduced scope
     - Even `min` breaches daily budget → defer to next window (Level D never deferred)
     - Estimated inference cost exceeds configured fraction of net edge → reject as cost-inefficient
     - Daily budget below 10% AND lifetime budget above 75% consumed → restrict to Tier B maximum

2. **Post-run accounting** — After every run:
   - Track per call: model, provider, input/output tokens, estimated/actual cost, cost class
   - Aggregate: per workflow run, market, position, day, week, model, provider, category
   - Compare estimate vs. actual for feedback loop

3. **Budget enforcement** — Configurable budgets:
   - Daily total inference budget
   - Daily Tier A (Opus) escalation budget
   - Per investigation run budget (max and Tier B ceiling)
   - Per open position per day
   - Per accepted candidate lifecycle
   - Max cumulative review cost per position (default: 8% of position value)
   - Lifetime experiment budget

4. **Cost-of-selectivity tracking** — Daily:
   - Total daily inference spend ÷ trades entered (7-day rolling)
   - Per-closed-trade total cost including rejected investigation allocation
   - Cost-to-edge ratio
   - `COST_SELECTIVITY_WARNING` if exceeds 20% rolling

5. **Cumulative review cost** — Per position:
   - Track across all reviews (every LLM call attributed to position)
   - 8% of position value → flag for cost-inefficiency exit review (mandatory review of whether to continue holding)
   - 15% of remaining expected value → drop to minimum review frequency (deterministic-only, no further LLM invocations)
   - Transition logic: 8% triggers review but does not force exit; 15% forces frequency change and should trigger cost-inefficiency exit consideration

6. **Lifetime budget tracking** — Alerts at 50%, 75%, 100% consumption. Level D never blocked.

7. **Estimate accuracy feedback loop** — Separately for: investigation runs, position reviews (deterministic vs. LLM), full lifecycle.

8. **Cost escalation policy** — When rolling cost-of-selectivity ratio exceeds target (20% of gross edge):
   - Opus escalation still permitted but requires higher minimum net-edge threshold
   - Formula: `threshold = standard_minimum × (1 + selectivity_ratio_excess / target_ratio)`
   - Creates natural feedback: as cost of finding trades increases, system demands higher quality from each investigation
   - This should either improve selectivity or reduce activity to bring costs in line

9. **Cost Governor supplies data to Risk Governor** — Cost Governor output (cost burden, cost-of-selectivity ratio, cumulative review costs) feeds into Risk Governor approval decisions as an input factor.

### Deliverables
- Pre-run cost estimator with approval logic
- Post-run cost accounting
- All budget enforcement
- Cost-of-selectivity tracking
- Lifetime budget with alerts
- Estimate accuracy feedback

### Acceptance Criteria
- Every workflow run has Pre-Run Cost Estimate before start and post-run Cost Snapshot
- Cost-of-selectivity computed and logged daily
- Cumulative review cost per position tracked and capped
- Lifetime budget tracking operational with alerts at thresholds
- No investigation starts without Cost Governor pre-approval

---

## Phase 8: LLM Integration & Agent Framework

### Goal
Build the provider abstraction, agent orchestration framework, and per-call cost tracking that powers all LLM-based workflows.

### Steps

1. **Provider abstraction** — Unified interface over:
   - Anthropic SDK (Opus 4.6 = Tier A, Sonnet 4.6 = Tier B)
   - OpenAI SDK (GPT-5.4 nano = Tier C, GPT-5.4 mini = Tier C alternative)
   - Per-call tracking: model, provider, input/output tokens, estimated cost, cost class
   - Automatic cost class annotation (H/M/L/Z)

2. **Agent base class** — Framework for all agents:
   - Input: structured context (not raw text)
   - Output: structured result (typed, validated)
   - Cost tracking: every call attributed to workflow_run_id, market_id, position_id
   - Escalation logging: reason, rule, Cost Governor approval, actual cost
   - Compression-first rule enforcement: context compressed before Tier A calls

3. **Agent registry** — Register all agent roles with default tier and cost class:

   **Tier A (Premium, Cost Class H):**
   - Investigator Orchestration Agent — final synthesis, adversarial weighing, no-trade decisions
   - Performance Analyzer — weekly strategic synthesis (with compression-first)

   **Tier B (Workhorse, Cost Class M):**
   - Domain Managers × 6 (Politics, Geopolitics, Sports, Technology, Science & Health, Macro/Policy)
   - Counter-Case Agent — strongest structured case against thesis
   - Resolution Review Agent — after deterministic parser runs
   - Tradeability Synthesizer — borderline ambiguity assessment
   - Position Review Orchestration Agent — only invoked on deterministic anomaly
   - Thesis Integrity Agent — only invoked on LLM-escalated review

   **Tier C (Utility, Cost Class L):**
   - Evidence Research Agent — collect/compress/structure evidence
   - Timing/Catalyst Agent — timeline assessment
   - Market Structure Agent (summary portion; metrics are Tier D)
   - Update Evidence Agent — position review sub-agent
   - Opposing Signal Agent (simple updates; complex escalate to Tier B)
   - Catalyst Shift Agent — position review sub-agent
   - Liquidity Deterioration Agent (explanation portion; metrics are Tier D)
   - Journal Writer — grounded in structured logs, not free-form narrative
   - Alert Composer — templated, concise, scannable messages
   - Dashboard Explanation Helper
   - Bias Audit Summary Writer — describes statistical findings (LLM does NOT detect biases)
   - Viability Checkpoint Summary Writer — describes statistical results (determination is Tier D)

   **Tier D (No LLM, Cost Class Z) — Complete list of deterministic-only roles:**
   - Risk Governor (all capital controls)
   - Cost Governor (all arithmetic, budget enforcement, approval decisions)
   - Execution Engine (pre-execution validation, order placement)
   - Trigger Scanner (hot path, polling, detection)
   - Eligibility Gate (category classification, hard rules)
   - Pre-Run Cost Estimator (arithmetic, uses effective cost profile)
   - Calibration Update Processor (all statistical computation)
   - Entry Impact Calculator (order book arithmetic → `estimated_impact_bps`)
   - Friction Model Calibrator (realized vs. estimated slippage comparison)
   - Bias Audit Processor (all 5 statistical checks — directional, clustering, anchoring, narrative, base-rate neglect)
   - Strategy Viability Checkpoint Processor (Brier comparison, viability determination by threshold)
   - Operator Absence Manager (timestamp comparison, escalation, wind-down scheduling)
   - Deterministic Position Review Checks (7 checks before LLM invocation)
   - Liquidity-Relative Sizing Enforcer (depth-based ceiling computation)
   - Shadow-vs-Market Brier Comparator (weekly computation)
   - Base-Rate Reference Lookup (historical resolution rates)
   - Cost-of-Selectivity Calculator (daily ratio computation)
   - Calibration Accumulation Projector (threshold timeline projection)
   - CLOB Cache Manager (cache serving, eviction, freshness)
   - Lifetime Budget Tracker (consumption tracking, alerts)
   - Patience Budget Tracker (9-month default, expiry logic)

4. **Effective position review cost profile** — Critical V4 distinction:
   - ~65% of scheduled reviews complete as Tier D (deterministic only, $0 LLM cost)
   - ~25% escalate to Tier B (Sonnet)
   - ~10% escalate to Tier A (Opus)
   - Weighted average cost per scheduled review: ~$0.005–$0.015 (50-70% reduction vs. V3)
   - Cost Governor MUST use effective profile, not assigned tier, when estimating position review costs

5. **Prompt management** — Structured prompt templates per agent role. System prompts include: calibration regime flags (insufficient/sufficient), viability regime flags (unproven/established), cost-of-selectivity ratio, operator mode context, Sports elevated conservatism flag.

6. **Context compression utilities** — Hard requirement before any Tier A call: deduplicate evidence items, compress logs to decision-critical fields only, remove boilerplate and low-signal text, preserve only state that materially affects the decision.

7. **Escalation policy engine** — Enforce Tier A escalation rules:
   - Escalate ONLY when ALL of: candidate survived deterministic filtering, meaningful net-edge above minimum AFTER entry impact deduction, ambiguity unresolved by Tier B, position size/consequence meaningful, Cost Governor pre-approved Tier A, daily Tier A budget not exhausted, cost-of-selectivity ratio not above target (or candidate justifies)
   - Do NOT escalate when: contract fails hard rules, market quality poor, expected net edge thin/negative, task is only summarization/extraction, position tiny, Cost Governor denied, entry impact > 25% of gross edge, cumulative review cost exceeded cap, position review completed deterministically
   - Every Tier A escalation logged with: reason, triggering rule, Cost Governor approval, actual cost, cost-of-selectivity ratio at decision, cumulative position review cost if applicable

8. **Model behavior by calibration regime** — Adapt agent behavior:
   - **Insufficient calibration:** conservative size caps, "low calibration confidence" flag to agents, more conservative thesis confidence, more willing to issue no-trade
   - **Sufficient calibration:** calibrated estimates replace raw model, relaxed size caps (still subject to Risk Governor)
   - **Sports regime:** higher conservatism until 40 resolved trades, lower size multiplier, "Sports quality-gated — elevated conservatism" flag, no premium Opus unless exceptional
   - **Viability-uncertain regime (V4):** when system Brier not demonstrably better than market (<50 resolved or Brier ≈ market), agents receive "strategy viability unproven" flag, higher evidence threshold for all candidates, Opus requires even stronger justification (candidate must represent market type where system most likely has edge), conservative sizing regardless of calibration

### Deliverables
- Provider abstraction with Anthropic + OpenAI
- Agent base class with structured I/O and cost tracking
- Agent registry with all roles
- Prompt templates
- Compression utilities

### Acceptance Criteria
- LLM calls succeed through both providers
- Every call tracked with tokens, cost, model, cost class
- Compression reduces context before Tier A calls
- Agent outputs are structured and validated
- Escalation logging captures all required fields

---

## Phase 9: Investigation Engine & Thesis Cards

### Goal
Build the full investigation workflow that produces thesis cards with all required fields, including base-rate comparison and entry impact estimation.

### Steps

1. **Investigation orchestration** — Three modes:
   - Scheduled broad sweep (2-3× daily)
   - Trigger-based single candidate (immediate on Level C)
   - Operator-forced (manual)
   - Candidate volume constraint: 0-3 per run (0 is correct most of the time)

2. **Investigation sequence** (spec Section 8.6):
   - Receive trigger or scheduled scope
   - Pre-run cost estimate → Cost Governor approval
   - Fetch candidates from eligible pool
   - Rank by trigger urgency and fit profile
   - Filter by edge discovery focus (deprioritize heavily covered markets)
   - Assign domain manager for top candidates only
   - Run compact sub-agent pack (5 default agents)
   - Build structured domain memo
   - Adversarial synthesis (Orchestration Agent — Opus)
   - Attach base-rate comparison and deviation
   - Compute entry impact estimate
   - Compute net edge after friction AND impact
   - Decide no-trade vs. surviving candidate

3. **Domain managers** — Six category-specific managers (Politics, Geopolitics, Sports, Technology, Science & Health, Macro/Policy). Each runs Tier B (Sonnet).

4. **Default research pack** — Five agents per surviving candidate:
   - Evidence Research Agent (Tier C)
   - Counter-Case Agent (Tier B)
   - Resolution Review Agent (Tier B, after deterministic parser)
   - Timing/Catalyst Agent (Tier C)
   - Market Structure Agent (Tier D metrics + Tier C summary)

5. **Optional sub-agents** — Only when domain manager explicitly justifies cost:
   - Data Cross-Check Agent — verify data consistency across sources
   - Sentiment Drift Agent — detect sentiment shifts relevant to thesis
   - Source Reliability Agent — assess reliability of key evidence sources
   - Invocation requires: domain manager provides written justification, Cost Governor approves additional cost within run budget

6. **Thesis card generation** — All fields from spec Section 14.2:
   - Market identifier, category, category quality tier (standard / quality-gated Sports)
   - Proposed side (Yes / No)
   - Exact resolution interpretation (verbatim source language + system interpretation)
   - Core thesis statement, why mispriced
   - Strongest supporting evidence (top 3, with source and freshness)
   - Strongest opposing evidence (top 3, with source and freshness)
   - Expected catalyst, expected time horizon
   - Invalidation conditions (explicit)
   - Resolution-risk summary, market-structure summary
   - Evidence quality score, evidence diversity score, ambiguity score
   - Calibration source status (no data / insufficient / preliminary / reliable)
   - Raw model probability estimate
   - Calibrated probability estimate (if available, with segment label)
   - **Probability estimate, confidence estimate, calibration confidence** (three separate fields, spec Section 23)
   - Confidence note
   - Expected gross edge
   - Expected friction estimate (spread, slippage)
   - Entry impact estimate in basis points
   - Expected inference cost estimate
   - **Net edge distinction** (spec Section 14.3 — four levels recorded separately):
     - Gross edge: market price vs. estimated probability
     - Friction-adjusted edge: after spread and slippage
     - Impact-adjusted edge: after entry impact estimate
     - Net edge after inference cost: the number the system acts on
   - A candidate with positive gross edge but negative/near-zero impact-adjusted net edge must NOT be entered
   - Recommended size band, urgency of entry
   - Trigger source
   - Sports quality gate result (if Sports)
   - Market-implied probability at forecast time
   - Base-rate for this market type
   - Base-rate deviation (system estimate minus base rate)
   - Liquidity-adjusted maximum position size

7. **Entry impact calculator** — Tier D deterministic:
   - Walk visible order book at top N levels
   - Compute levels consumed by order
   - Estimate mid-price movement → `estimated_impact_bps`

8. **Base-rate system** — Lookup/compute historical resolution rates per market type. Default 50% when no data. Attach base rate and deviation to every thesis card.

9. **Candidate rubric** — Score every candidate on all dimensions (spec Section 8.7):
   - Evidence quality, evidence diversity, evidence freshness
   - Resolution clarity, market structure quality, timing clarity
   - Counter-case strength, ambiguity level
   - Expected gross edge, cluster correlation burden
   - Calibration confidence source class
   - Cost-to-evaluate estimate, expected holding horizon
   - Category quality tier
   - Base-rate for this market type, base-rate deviation
   - Market-implied probability at forecast time
   - Entry impact estimate, liquidity-adjusted maximum position size

10. **Opus escalation gating** — Investigator Orchestration Agent uses Opus only when:
    - Candidate survived deterministic filtering and compact research
    - Net-edge estimate non-trivial above configured minimum
    - Net-edge remains non-trivial AFTER entry impact deduction
    - Evidence quality rubric not clearly poor
    - Cost Governor pre-approved Tier A usage for this run
    - Cost-of-selectivity ratio not already above target (if above, requires stronger justification)
    - Logged field: `model_used`, `escalation_approved_by_cost_governor`, `cost_selectivity_ratio_at_decision`

### Deliverables
- Full investigation workflow with all three modes
- All domain managers and research agents
- Thesis card generation with all required fields
- Entry impact calculator
- Base-rate reference system
- Candidate rubric scoring

### Acceptance Criteria
- No investigation starts without Cost Governor pre-approval
- Each accepted candidate includes all required thesis card fields
- Most low-quality runs terminate with no-trade
- Actual vs. estimated cost recorded per run
- Every thesis card includes market-implied probability, base rate, entry impact
- No-trade is a logged, structured output

---

## Phase 10: Tradeability, Resolution & Execution

### Goal
Build the resolution ambiguity filter, the execution engine with pre-trade validation, and the slippage/friction tracking system.

### Steps

1. **Deterministic resolution parser** — Check every surviving candidate for:
   - Explicit named resolution source
   - Explicit resolution deadline
   - Ambiguous conditional wording ("may", "could", "at the discretion of")
   - Undefined key terms
   - Multi-step dependencies
   - Unclear jurisdiction
   - Counter-intuitive resolution risk
   - Contract wording version changes — fetch and compare current wording against stored version; flag if wording has changed since last check or since position entry

2. **Hard rejection patterns** — Auto-reject:
   - Meaningfully ambiguous wording
   - Unstable/unnamed/discretionary resolution source
   - Counter-intuitive resolution possible
   - Exit conditions unacceptable
   - Spread/depth fails hard limits
   - Extreme manipulation risk
   - Depth below minimum for minimum position size

3. **Tradeability synthesizer** — Agent-assisted (Tier B) for surviving candidates with non-trivial residual ambiguity. Output: Reject (reason code), Watch, Tradable Reduced Size (with liquidity-adjusted max), Tradable Normal (with liquidity-adjusted max).

4. **Execution engine** — Fully deterministic (Tier D):
   - Pre-execution revalidation: market open, side correct, spread within bounds, depth acceptable, drawdown not worsened, exposure budget available, no duplicate, no new ambiguity, approval not stale, liquidity-relative limit check, entry impact within bounds, not in operator absent mode
   - Delay and retry once on failure, then cancel and alert

5. **Controlled entry modes**:
   - Immediate full entry (rare, high-confidence)
   - Staged entry (preferred when > 5% of top-3 depth)
   - Price-improvement wait
   - Cancel if degraded

6. **Realized slippage recording** — Per order:
   - `estimated_slippage_bps`, `realized_slippage_bps`, `slippage_ratio`
   - If ratio > 1.5x across last 20 trades → recalibrate friction model

7. **Friction model** — Track and adjust:
   - Spread estimate, depth assumption, impact coefficient
   - Statistical deviation triggers parameter adjustment
   - Changes logged in weekly review

8. **Execution logging** — Per order: full approval chain, revalidation outcome, forced resize reason, entry impact, realized slippage, links to thesis card and workflow run.

### Deliverables
- Deterministic resolution parser with all checks
- Tradeability synthesizer
- Execution engine with pre-execution revalidation
- Controlled entry modes
- Slippage tracking and friction model
- Execution logging

### Acceptance Criteria
- Every candidate has a Resolution Parse Result record
- Every rejection has explicit reason code
- Severe wording ambiguity cannot pass to Risk Governor
- No order sent without final pre-execution revalidation
- No order exceeds liquidity-relative sizing limit
- Realized vs. estimated slippage logged per trade
- Tradeability output includes liquidity-adjusted max size

---

## Phase 11: Position Management & Review

### Goal
Build the tiered, deterministic-first position review system with all exit classifications and cost-aware review escalation.

### Steps

1. **Review scheduling** — Tiered frequency:
   - Tier 1 (New, first 48hr): every 2-4 hours
   - Tier 2 (Stable): every 6-8 hours (no triggers in 24hr, price in thesis range, held > 48hr)
   - Tier 3 (Low-value): every 12 hours (bottom 20th percentile size, low remaining expected value)
   - Tier override: Level C/D triggers promote to Tier 1 immediately

2. **Deterministic-first review** — At every scheduled review:
   - Step 1 (always, Tier D): Check price vs. entry/thesis range, spread vs. limits, depth vs. minimums, catalyst date proximity, drawdown state, position age vs. horizon, cumulative review cost vs. cap
   - Step 2: ALL pass → `DETERMINISTIC_REVIEW_CLEAR`, no LLM cost (~65% of reviews)
   - Step 3: ANY flags → escalate to LLM review focused on flagged issues

3. **LLM-escalated review** — Position Review Orchestration Agent (Tier B) with sub-agents:
   - Update Evidence Agent (Tier C)
   - Thesis Integrity Agent (Tier B)
   - Opposing Signal Agent (Tier C/B)
   - Liquidity Deterioration Agent (Tier D metrics + Tier C explanation)
   - Catalyst Shift Agent (Tier C)

4. **Premium escalation** — Opus only when: large position, near invalidation, conflicting evidence, interpretation risk, remaining value justifies cost, AND cumulative review cost below cap.

5. **Position actions** — Hold, Trim, Partial Close, Full Close, Forced Risk Reduction, Watch-and-Review, Reduce to Minimum Monitoring.

6. **Exit classification** — All exits explicitly classified:
   - Thesis-invalidated, Resolution-risk, Time-decay, News-shock
   - Profit-protection, Liquidity-collapse, Correlation-risk
   - Portfolio-defense, Cost-inefficiency, Operator-absence, Scanner-degradation

7. **Review modes** — Scheduled, Stress, Profit Protection, Catalyst, Cost-Efficiency.

8. **Cumulative review cost tracking** — Per position across all reviews. 8% of value → flag. 15% of remaining expected value → deterministic-only.

### Deliverables
- Tiered review scheduler
- Deterministic-first review checks
- LLM-escalated review with all sub-agents
- Position action handling
- Exit classification system
- Cumulative cost tracking

### Acceptance Criteria
- Every review produces structured action result with explicit action class
- Exits always have explicit exit class
- Most scheduled reviews complete deterministic-only (no LLM cost)
- Cumulative cost cap triggers cost-inefficiency exit consideration
- Level C/D triggers immediately promote to Tier 1

---

## Phase 12: Calibration & Learning System

### Goal
Build the calibration store, shadow forecast collection, Brier score system, category performance ledger, and learning loops.

### Steps

1. **Calibration store** — Shadow forecasts from day one:
   - Every investigated market produces a shadow forecast entry
   - Stores: all thesis card fields, raw model probability, market-implied probability, resolution outcome (when available)
   - Maintained separately per segment: category, horizon bucket, market type, ambiguity band, evidence quality class

2. **Shadow-vs-market Brier comparison** — Computed weekly:
   - System Brier = (system_probability − actual_outcome)²
   - Market Brier = (market_implied − actual_outcome)²
   - System advantage = Market_Brier − System_Brier
   - Aggregated at: strategy level, per category, per horizon, per time period

3. **Parallel base-rate benchmark** — Base-rate Brier score alongside system and market Brier.

4. **Hard minimum sample thresholds** (spec Section 15.6):
   - Initial calibration correction: 20 resolved in segment
   - Category-level: 30 resolved
   - Horizon-bucket: 25 resolved
   - Sports: 40 resolved
   - Reducing size penalties: 30 AND Brier improvement vs. base rate

5. **Cross-category pooling** — For structurally similar segments (same horizon, similar market structure):
   - Conservative 30% penalty factor applied to pooled calibration
   - Combined pool minimum: 15 trades
   - Individual segment minimum within pool: 5 trades
   - Never across structurally different categories (e.g., Politics and Sports)
   - Logged when used with penalty factor and contributing segments

6. **Calibration accumulation rate** — Weekly update:
   - Resolved trades per week per segment
   - Projected threshold date per segment (when will minimum samples be reached)
   - Bottleneck segment identification (which segments are accumulating slowest)
   - If majority of segments project beyond patience budget: recommend focus on shorter-horizon markets, consider pooling, or adjust thresholds

7. **Sizing under calibration regimes**:
   - Insufficient: hard size caps, conservative penalties
   - Sufficient: calibrated estimates replace raw model probabilities

8. **Category Performance Ledger** — Weekly update per category:
   - Trades, win rate, gross/net PnL, inference cost, average edge, holding time
   - Rejection rates, no-trade rate, Brier score, exit distribution
   - System-vs-market Brier, cost-of-selectivity, slippage ratio, entry impact %

9. **Fast learning loop** (daily) — Update calibration, cost metrics, slippage, budget, absence status.

10. **Slow learning loop** (weekly/biweekly) — Category ledger, domain and category analysis, agent usefulness by role, prompt and evidence source quality, threshold review (too loose? too tight?), policy change proposals with evidence, shadow-vs-market Brier comparison, bias audit report, calibration accumulation projections, strategy viability assessment, friction model accuracy review.

11. **Policy change discipline** — No automatic policy change unless:
    - Minimum sample threshold met for the relevant segment
    - Pattern persistence exists (not a one-time observation)
    - Change documented with evidence and rationale
    - In early deployment, ALL changes require operator review
    - Category suspension requires operator decision — no automatic shutdown
    - If Brier worse than market after 30+ trades in a category, Policy Review must address regardless of PnL

12. **No-trade rate monitoring** — Not a failure metric. Low no-trade rate → potential quality erosion. High → potential over-filtering. Both flagged by fast learning loop. Tracked per run and rolling.

13. **Patience budget** — Default 9 months from shadow mode start. At expiry: comprehensive viability report, operator must explicitly decide (continue/adjust/terminate). Operator silence does NOT extend the budget.

14. **Friction model feedback** — Adjust parameters when realized/estimated diverges > 50% over 20 trades. If below by > 30%, relax slightly. Changes logged in weekly review.

15. **Performance Review workflow** — Weekly, uses Performance Analyzer (Opus Tier A):
    - Produces Category Performance Ledger as mandatory output
    - Produces shadow-vs-market Brier comparison as mandatory output
    - Strategic synthesis over compressed inputs from all Tier D computations
    - Outputs: category-level evidence for scaling decisions, policy change proposals with evidence

16. **Policy Review workflow** — Weekly or biweekly:
    - Proposes changes only when evidence thresholds met
    - All changes documented with evidence and rationale
    - In early deployment, operator review required for all changes

### Deliverables
- Calibration store with shadow forecasts
- Brier score computation (system, market, base-rate)
- Category Performance Ledger
- Calibration segments with thresholds
- Accumulation rate tracking
- Fast and slow learning loops
- Patience budget tracking

### Acceptance Criteria
- Shadow forecasts enter calibration store from day one with market-implied probability
- Shadow-vs-market comparison computed weekly
- Sizing visibly different in insufficient vs. sufficient calibration regimes
- Accumulation projections updated weekly
- Category ledger updated weekly with all required fields

---

## Phase 13: Cross-Cutting Systems

### Goal
Build the bias detection, strategy viability, and operator absence systems that operate across all workflows.

### Steps

1. **Bias Detection System** — All statistical (Tier D), **weekly cadence aligned with Performance Review**:
   - Directional bias: arithmetic mean comparison, average system vs. market probability (flag if persistent > 5pp skew over 3+ weeks)
   - Confidence clustering: histogram computation, flag if > 50% of forecasts within a 20pp band
   - Anchoring: mean absolute difference computation, flag if avg absolute difference from market consistently below 3pp
   - Narrative coherence over-weighting: correlation analysis between evidence quality scores and forecast accuracy — check if high-narrative-quality forecasts are less accurate than weak-narrative ones
   - Base-rate neglect: statistical comparison of system estimates vs. base rates — check if deviations are systematically directional
   - Tier C summary ONLY for producing human-readable audit report — LLM describes what statistics show, does NOT interpret whether bias is a problem or suggest corrections (that's for operator and Performance Analyzer)
   - Alerts: `BIAS_PATTERN_DETECTED` (new pattern), `BIAS_PATTERN_PERSISTENT` (3+ consecutive weeks), `BIAS_PATTERN_RESOLVED` (previously persistent pattern gone)
   - Critical separation: LLM must NOT audit its own reasoning biases — detection is statistical, interpretation may be LLM-assisted via Performance Analyzer only after statistical facts established

2. **Strategy Viability System** — Checkpoints:
   - Week 4: Preliminary (insufficient data likely, no decisions)
   - Week 8: Intermediate (if 20+ resolved, compare system vs. market; `VIABILITY_CONCERN` if worse)
   - Week 12: Decision (if 50+ resolved and system worse → `VIABILITY_WARNING`, operator must acknowledge)
   - Budget checkpoints at 50%, 75%, 100% consumption
   - Viability metrics: all Brier scores, hypothetical PnL, cost-of-selectivity, accumulation rate, budget consumption
   - Determination by deterministic threshold comparison, not LLM

3. **Operator Absence System** — Deterministic (Tier D):
   - Track interactions: login, dashboard view, manual trigger, config change, alert acknowledgment
   - Escalation ladder:
     - 0-48hr: Normal
     - 48-72hr: Absent Level 1 — no new positions, increased review, alerts
     - 72-96hr: Absent Level 2 — 25% size reduction, escalated alert
     - 96-120hr: Absent Level 3 — additional 25% reduction, wind-down prep
     - 120hr+: Graceful Wind-Down — close targets → break-even → scheduled, goal: zero in 72hr
   - May NEVER: enter new positions, increase sizes, change parameters, override Risk/Cost Governor, delay Level D interventions
   - May ONLY: maintain or reduce positions, increase review frequency, close at targets/expiry, execute Risk Governor forced reductions, send alerts
   - Critical alerts via at least two independent channels (Telegram + email recommended), log delivery confirmation per channel
   - Operator return workflow:
     - Explicit acknowledgment required before normal operation resumes
     - System presents summary of all autonomous actions taken during absence
     - Reduced positions NOT automatically re-entered; require new investigation cycle
     - Normal operation resumes only after acknowledgment

4. **Lifetime experiment budget** — Continuous tracking. Alerts at 50%, 75%, 100%. Pause investigations at 100% (Level D never blocked).

### Deliverables
- Bias detection with all five statistical checks
- Weekly bias audit report generation
- Strategy viability checkpoints at weeks 4/8/12
- Budget-triggered viability reviews
- Operator absence manager with full escalation ladder
- Lifetime budget tracking with alerts

### Acceptance Criteria
- All bias detection is statistical, no LLM self-auditing
- Persistent patterns (3+ weeks) trigger alerts
- Viability checkpoints execute at correct schedule
- Absence escalation respects all timing thresholds
- Operator return requires explicit acknowledgment
- Level D interventions never blocked by budget or absence

---

## Phase 14: Operator Notifications (Telegram)

### Goal
Build the event-driven notification layer with Telegram as primary channel, covering all required event types.

### Steps

1. **Event bus** — Internal pub/sub system:
   - Workflows emit typed events (not Telegram messages)
   - Notification service subscribes to event types
   - Decoupled from trading logic

2. **Telegram bot integration** — Async Telegram bot:
   - Send to pre-approved chat IDs only
   - Retry on failure, store failed attempts
   - Deduplicate repeated notifications
   - Persist delivery status locally
   - Audit trail: event ID, type, payload, send attempts, status, Telegram message ID, timestamps
   - Secure credentials, never expose secrets in messages

3. **Required event types** (spec Section 26.3):
   - A: Trade Entry alerts
   - B: Trade Exit alerts
   - C: Risk alerts (drawdown thresholds, kill switch, correlation breach)
   - D: No-Trade alerts (healthy vs. failed distinction)
   - E: Weekly Performance alerts
   - F: System Health alerts (workflow failures, API issues, latency spikes)
   - G: Strategy Viability alerts (checkpoint results, budget warnings, bias patterns)
   - H: Operator Absence alerts (mode activation, escalation, autonomous actions)

4. **Severity levels** — INFO, WARNING, CRITICAL. Format: severity → event type → market/workflow → action → reason → risk impact → timestamp → reference ID.

5. **Alert composer agent** — Tier C utility model for message formatting. Concise, scannable, structured.

6. **Future extensibility** — Design for channel expansion (email, SMS, Discord) without rewriting business logic.

### Deliverables
- Internal event bus
- Telegram bot with delivery tracking
- All 8 event type formatters
- Severity-based routing
- Delivery audit trail
- Alert composer

### Acceptance Criteria
- All required event types implemented
- Messages sent only to pre-approved chat IDs
- Failed deliveries retried and logged
- Deduplication prevents repeated notifications
- No secrets exposed in messages
- Notification outcomes logged as structured entries

---

## Phase 15: Dashboard & System Integration

### Goal
Build the Next.js operational dashboard and integrate all components into end-to-end workflows for Paper Mode and Shadow Mode readiness.

### Sub-Phase 15A: Dashboard

1. **Next.js project setup** — TypeScript, Tailwind CSS, component library.

2. **API layer** — FastAPI endpoints serving dashboard data:
   - Portfolio overview (equity, PnL, exposure, drawdown state)
   - Open positions with thesis summaries
   - Recent workflow runs with outcomes
   - Trigger event feed
   - Risk board (drawdown ladder state, exposure by category, correlation groups)
   - Category Performance Ledger
   - Calibration status (Brier scores, system vs. market, accumulation projections)
   - Cost metrics (daily spend, selectivity ratio, lifetime budget)
   - Bias audit results and pattern tracking
   - Strategy viability status and checkpoint history
   - Operator absence status and action history
   - Scanner health (API status, cache state, degraded mode)
   - Alert center with Telegram delivery status
   - System health dashboard
   - Logs and journal viewer
   - Settings and operator controls

3. **Dashboard pages**:
   - Executive Overview — equity curve, open positions summary, current risk state, system mode
   - Positions — detailed view of each position with thesis card, review history, cost tracking
   - Risk Board — drawdown ladder visualization, exposure breakdown, correlation map
   - Workflows — recent runs, agent activity, cost per run
   - Analytics — Category Ledger, Brier comparison charts, cost-of-selectivity trend
   - Calibration — segment status, accumulation projections, patience budget
   - Viability — checkpoint history, viability signals, budget consumption
   - Bias — audit results, pattern history, directional trends
   - Alerts — notification history, Telegram delivery status
   - System Health — scanner status, API health, cache metrics
   - Settings — configuration management, operator mode controls

### Sub-Phase 15B: Logging, Journals & Explainability

4. **Structured logging completeness** — Every investigation and position review must log ALL required fields (spec Section 28.2):
   - Trigger source, model stack used, pre-run cost estimate, actual cost
   - Top evidence and counter-evidence items
   - Resolution-risk parse result, tradeability outcome
   - Risk Governor decision, Cost Governor decision
   - Net-edge estimate (all four levels), calibration segment and status
   - Final action taken
   - Market-implied probability, base-rate and deviation
   - Entry impact estimate, review tier
   - Whether deterministic-only review, cumulative review cost
   - Operator absence status
   - Every trigger event: class, level, market ID, data snapshot, reason, timestamp, data source, escalation status
   - Every order: entry impact, realized slippage, slippage ratio, liquidity-relative size percentage
   - Viability checkpoints, bias audits, absence events as structured queryable entries

5. **Narrative journal system** — Journal Writer (Tier C):
   - Concise, decision-relevant narrative journals
   - Grounded in structured logs — not free-form essays
   - Explains the decision reasoning in human-readable form
   - Links to underlying structured log entries for drill-down
   - Full trade reconstruction possible from trigger to exit through journals + structured logs

### Sub-Phase 15C: End-to-End Integration

6. **Workflow orchestration** — Wire all 13 workflows together:
   - Eligibility Intake → Trigger Scanner → Investigator → Tradeability → Risk/Cost Approval → Execution → Position Review → Calibration → Performance Review → Policy Review → Viability → Bias Audit → Absence Management

7. **Paper Mode** — Integration testing:
   - Full decision generation, no live execution
   - Cost chain modeling
   - All logging and journals operational
   - Telegram notifications working
   - Absence mode testable
   - Entry impact estimation testable
   - All deterministic rules validated

8. **Shadow Mode readiness** — Verify all deployment guardrails (spec Section 29.1):
   - Eligibility gate tested
   - Scanner with defined data sources, local cache, secondary source tested
   - Structured logging working (all required fields verified)
   - Cost estimation model defined (effective cost profile for position review)
   - Paper mode forecasting operational
   - Operator absence mode tested (full escalation ladder)
   - Entry impact estimation tested
   - Base-rate data loaded
   - Lifetime budget configured
   - Patience budget configured (default 9 months)
   - Full cost chain modeled (if projected cost exceeds 20% of projected edge, adjust tiers)
   - Cost-of-selectivity within acceptable range definition established
   - Redundant alert channels configured and tested (minimum 2 channels)
   - Telegram delivery confirmed

9. **Non-negotiable rules verification** — Verify all 15 non-negotiable system rules (spec Section 30) are implemented and tested:
   1. Max daily new deployment: 10% of account balance
   2. Max daily drawdown: 8% of start-of-day equity (realized + unrealized)
   3. New entries disabled before hard cap, using staged thresholds
   4. No position executed without passing Tradeability Filter
   5. No position executed without Risk Governor approval
   6. No order exceeds 12% of visible depth at top 3 levels
   7. All actions logged in narrative and structured form
   8. No-trade decision is a formal, logged output
   9. Correlated positions limited through cluster exposure controls
   10. Position management is thesis-based, not just price-based
   11. Performance review produces concrete policy updates
   12. No LLM may override Risk Governor, Cost Governor arithmetic, or Execution Engine
   13. No investigation run starts without Cost Governor pre-approval
   14. System must operate safely during 5-day operator absence
   15. Edge must be proven against market accuracy before scaling

### Deliverables
- Full Next.js dashboard with all pages
- FastAPI serving all dashboard data
- End-to-end workflow orchestration
- Paper Mode operational
- Shadow Mode readiness checklist passed

### Acceptance Criteria
- Dashboard answers "what is happening, why, what risk is on the table, should I intervene" within seconds
- All 13 workflows execute in correct sequence
- Paper Mode produces full decision records without live execution
- All spec Section 29.1 guardrails verified
- Category Performance Ledger visible as first-class dashboard section
- Shadow-vs-market Brier visible in dashboard
- Operator can control system mode from dashboard

---

## Post-Phase: Operational Milestones

These are not development phases but operational gates defined in the PRD/spec:

### Shadow Mode (minimum 6 weeks)
- Live monitoring, full generation, no execution
- Calibration data collection from day one
- Shadow-vs-market Brier comparison weekly
- Viability checkpoints at weeks 4, 8, 12
- Bias audit running weekly
- Entry impact simulation
- Telegram notification testing
- Operator absence mode testing in shadow
- Exit gate (spec Section 29.2): 20+ resolved forecasts, scanner stability, Brier not worse than market, cost ratio acceptable, cache/absence/alerts tested

### Live Small Size
- Strict caps, all tracking live
- Slippage tracking, friction model calibration with live data
- Cost-of-selectivity tracking in production
- Exit gate (spec Section 29.2 for shadow exit, 29.3 for live standard):
  - Shadow exit requires: 20+ resolved forecasts in ≥1 category, scanner stability, Brier not worse than market, cost ratio acceptable, cache/absence/alerts tested
  - Live Standard requires: 30+ trades in 2 categories, positive net expectancy evidence, Brier ≥ market in best category, slippage ≤ 1.5x estimated, no persistent bias patterns, cost-of-selectivity within target, friction model accuracy confirmed, calibration projections show reasonable timelines, operator has reviewed and approved

### Live Standard
- Full operation after all Live Small exit gates met
- No remaining unresolved execution or wording failures
- Stable workflow and scanner reliability
- ≥1 category with convincing positive net PnL

---

## Non-Functional Requirements (Cross-Phase)

These NFRs apply across all phases and must be verified throughout development:

- **Reliability:** Safe degradation on data source failure, local CLOB cache for resilience, multi-day operator absence tolerance (5 days minimum)
- **Explainability:** Every action traceable from trigger to exit, rejection as important as approval, cost/base-rate/impact always transparent
- **Cost Efficiency:** Prospective and retrospective cost control, deterministic-first reviews (~65%), lifetime budget enforcement
- **Extensibility:** Category expansion possible (but out of scope now), model changes without system rewrite, notification channel expansion (email, SMS, Discord), future market-making consideration
- **Auditability:** All decisions logged with reasons, operator actions audited, costs archived, notification outcomes tracked
- **Resilience:** 5-day operator absence tolerance, short outage tolerance via cache, degraded-mode escalation, redundant alert channels

## Success Metrics (Cross-Phase)

### Primary Metrics
- Net expectancy after costs (the only metric that matters for strategy viability)
- No-trade rate (high quality indicator — most runs should produce no trade)
- Drawdown adherence (never breach 8% daily)
- Explanation coverage (100% of trades have full structured log + journal)
- Brier score (system vs. market vs. base-rate)
- Cost per candidate / cost per closed trade
- Category net PnL
- Shadow-vs-market Brier comparison
- Cost-of-selectivity ratio (target: < 20% of gross edge)
- Slippage ratio (target: ≤ 1.5x estimated)

### Secondary Metrics
- Rejection rates by reason code, latency, model usage distribution
- Holding time, cost estimate accuracy, calibration accumulation rate
- Base-rate deviation patterns, review cost percentage
- Operator absence frequency, lifetime budget consumption rate
- Bias persistence counts, Telegram delivery rate

### Failure Indicators
- Wording surprises (resolution outcome contradicts thesis interpretation)
- Cost-erased edge (gross edge positive but net edge negative after costs)
- Missed scheduled reviews, reversed policy decisions
- Degraded-mode periods, missed cost estimates
- Excess slippage (> 1.5x), excess depth usage (> 12%)
- Brier underperformance weeks (system worse than market)
- Persistent bias patterns (3+ weeks unresolved)
- Absence events, notification delivery failures

---

## Implementation Notes

### Development Approach
- Build and test each phase before starting the next
- Each phase has unit tests and integration tests
- Deterministic components (Tier D) are tested first — they form the safety foundation
- LLM-based components are built on top of verified deterministic infrastructure
- Use dependency injection for testability (mock LLM providers, mock CLOB API)
- Configuration-driven thresholds everywhere — no magic numbers in code

### Testing Strategy
- Unit tests for all deterministic logic (eligibility rules, risk governor, cost governor, drawdown ladder, sizing, correlation)
- Integration tests for API clients (CLOB, Telegram, LLM providers)
- End-to-end tests for complete workflow paths
- Paper Mode serves as the primary integration validation
- Shadow Mode serves as live validation without capital risk

### Performance Analyzer (Phase 12 — Weekly)
The Performance Analyzer uses Opus (Tier A) for final strategic synthesis. It receives pre-compressed input from Tier D/C:
- Shadow-vs-market Brier comparison data (Tier D)
- Cost-of-selectivity metrics (Tier D)
- Bias audit results (Tier D statistics, Tier C summary)
- Calibration accumulation projections (Tier D)
- Realized vs. estimated slippage analysis (Tier D)
- Strategy viability assessment data (Tier D)
- Category Performance Ledger (Tier D aggregation)
- Compression step required before Opus: Tier C or deterministic summarization compresses raw logs before Opus sees them
- Fallback to Sonnet if weekly Opus budget exhausted

### Key Architectural Decisions
- **Deterministic safety zones are never optional** — Risk Governor, Cost Governor arithmetic, Execution Engine, and all Tier D components must work perfectly before any LLM components are built
- **Phases 6 and 7 (Risk/Cost Governors) can be built in parallel** since they are independent deterministic systems
- **Phase 8 (LLM framework) is the gateway** to all agent-based phases — get it right once
- **The dashboard (Phase 15) is last** because it reads from data that all prior phases produce — but API endpoints can be stubbed early for frontend development to begin in parallel
