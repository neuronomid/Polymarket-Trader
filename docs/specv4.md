# Polymarket Trader Agent — System Specification

## Document Status

Draft v4.0

## Document Purpose

This document is the complete technical specification for the Polymarket Trader Agent system. It defines the architecture, workflows, data infrastructure, risk controls, cost controls, calibration system, execution logic, position management, learning architecture, operator modes, data model, deployment guardrails, notification layer, and dashboard integration.

This document is self-contained. It describes the full system as designed. The companion documents are the Product Requirements Document (PRDV4.md), the Agent Models document (modelsv4.md), and the standalone Dashboard Specification (polymarket_dashboard_spec.md).

---

## 1. Core Thesis

The Polymarket Trader Agent is a **selective, event-driven, cost-aware, risk-first, empirically-calibrated, viability-accountable** Polymarket decision system.

It is not designed to beat latency-arbitrage bots or blanket every open market. It is designed to:

- identify tradable mispricings in narrower, better-fit market segments
- avoid structurally bad, ambiguous, or speed-dominated contracts
- deploy capital only when both thesis quality and market quality are sufficient
- manage positions with explicit invalidation logic
- measure real edge after API cost, slippage, and execution friction
- build honest empirical evidence of whether the system's edge is real before scaling
- compare its forecasting accuracy against the market's accuracy, not just against absolute calibration targets
- prevent its own orders from degrading its edge through market impact
- survive operator absence and data source instability without human intervention
- detect and correct its own systematic reasoning biases
- bound the cost of the discovery experiment so failure is survivable

The guiding operating principles are:

> Agents may recommend. Rules may permit, resize, delay, reject, or force reduction.

- Expensive reasoning is earned, not assumed.
- Net edge is the only edge that matters.
- No scaling before calibration.
- Prove edge against the market, not just in isolation.
- Size for the book, not just for conviction.
- The experiment has a budget; discovery is not free.

---

## 2. Strategic Scope

### 2.1 Allowed Market Categories

The system may trade only within these categories unless later expanded by explicit operator decision:

- Politics
- Geopolitics
- Technology
- Science and Health
- Macro / Policy / Institutional Events
- Sports (with quality gate — see Section 2.4)

### 2.2 Excluded Categories

- **News** — Reactive and speed-dominated. A reasoning-heavy system has no structural advantage and will consistently miss the best entry windows.
- **Culture** — Soft, sentiment-driven resolution and weak objective grounding. The cost of deep agentic evaluation is not recoverable.
- **Crypto** — Attracts faster, more technically sophisticated, latency-oriented competition. A thesis-driven multi-agent system is structurally disadvantaged.
- **Weather** — Best addressed by structured meteorological models, not LLM reasoning over text.

### 2.3 Preferred Market Profile

The system should strongly prefer contracts that are:

- objectively resolvable against a named authoritative source
- not reflexive sentiment contests where crowd narrative drives resolution
- not dominated by second-to-minute latency advantages
- supported by verifiable public evidence across independent sources
- suitable for thesis-based holding and reevaluation over days to weeks
- liquid enough to enter and exit at reasonable friction

### 2.4 Sports Category Quality Gate

A Sports market is eligible only if all of the following are true:

- Resolution criteria are fully objective (win/loss, final score, official recorded outcome — not judgmental or administrative decisions)
- Market resolves in more than 48 hours from time of investigation
- Market has adequate liquidity and observable depth
- Resolution does not depend on anything primarily a statistical modeling problem (spreads, exact totals)
- The system has a credible evidential basis beyond available public statistics

Sports markets that pass this gate carry a default lower size multiplier than Standard Tier categories until category-level calibration data establishes otherwise.

### 2.5 Edge Discovery Focus

Investigation effort should concentrate on markets where information asymmetry is structurally plausible:

- Niche political events with limited public coverage where deep synthesis adds value
- Specific policy decisions requiring technical or institutional interpretation
- Scientific outcomes with domain-knowledge barriers
- Timing-sensitive markets where the event-driven architecture creates a speed advantage over manual traders

Heavily covered events (major elections, championship finals, top-line economic releases) should be deprioritized — market prices there are likely already efficient.

---

## 3. Design Goals

### 3.1 Primary Goals

1. Preserve disciplined risk architecture with deterministic safety controls.
2. Reduce structural staleness through event-driven scanning.
3. Keep API costs reasonable without degrading high-value reasoning moments.
4. Use Claude Opus 4.6 selectively where it creates real decision value.
5. Build outcome-based calibration from shadow mode onward.
6. Improve market selection by prioritizing tradeability over idea volume.
7. Measure net profitability after inference cost and execution friction.
8. Define hard calibration thresholds per segment.
9. Ensure the trigger scanner has explicit, reliable data infrastructure with local caching.
10. Make the Cost Governor prospective (pre-run gating) as well as retrospective.
11. Compare system forecast accuracy against market-implied accuracy.
12. Prevent self-inflicted market impact through liquidity-relative sizing.
13. Control position review cost through tiered frequency and deterministic-first reviews.
14. Detect systematic LLM reasoning biases before they compound.
15. Ensure autonomous safe behavior during operator absence.
16. Bound the total cost of the strategy discovery experiment.

### 3.2 Non-Goals

The system is not intended to:

- compete directly with ultra-low-latency arbitrage bots
- trade every interesting market
- maximize agent count or daily activity
- infer edge from social chatter alone
- deploy live sizing before calibration evidence is sufficient
- provide passive liquidity or market-making services (future extension)

---

## 4. Operating Model

### 4.1 High-Level Architecture

The system has seven main operating layers plus three cross-cutting systems:

**Layer 1: Market Intake and Eligibility Gate**
Pulls candidate markets from Polymarket. Immediately filters out contracts outside allowed categories, below quality thresholds, structurally unacceptable, or below minimum liquidity for the system's minimum position size.

**Layer 2: Trigger Scanner**
Runs continuously using lightweight deterministic logic over a well-defined set of data inputs with local caching. Watches eligible markets and held positions. Produces machine-readable trigger events. Resilient to short data source outages.

**Layer 3: Investigation Engine**
Runs only when triggered by schedule, scanner event, or operator action. Produces new trade candidates using a narrow, cost-staged research stack. Includes base-rate comparison and entry impact estimation.

**Layer 4: Tradeability and Resolution Engine**
Performs deterministic and agent-assisted checks on market wording, ambiguity, entry/exit practicality, evidence sufficiency, and liquidity-relative sizing constraints.

**Layer 5: Risk Governor and Cost Governor**
Risk Governor protects capital with deterministic veto authority including liquidity-relative limits. Cost Governor protects net expectancy from excessive inference spend, including pre-run estimation, cost-of-selectivity tracking, cumulative review cost caps, and lifetime experiment budget.

**Layer 6: Execution Engine**
Executes only approved actions after final pre-trade revalidation including entry impact check and liquidity-relative sizing enforcement. Fully deterministic. Records realized slippage for friction model calibration.

**Layer 7: Position Review, Calibration, and Learning Engine**
Manages open positions with tiered review frequency (deterministic-first). Records outcomes. Updates calibration data. Generates fast and slow feedback loops. Produces category performance ledger. Runs bias audits. Tracks strategy viability.

**Cross-Cutting System A: Strategy Viability System**
Compares system forecasts against market accuracy. Runs parallel base-rate benchmark. Produces viability checkpoints. Tracks lifetime experiment budget.

**Cross-Cutting System B: Bias Detection System**
Requires base-rate comparison on all thesis cards. Runs weekly bias audit. Detects persistent reasoning patterns. All detection is statistical — no LLM self-auditing.

**Cross-Cutting System C: Operator Absence System**
Monitors operator interaction. Manages autonomous safe-mode. Executes graceful wind-down when needed.

---

## 5. Workflow Architecture

### 5.1 Workflow Set

1. Eligibility Intake Workflow
2. Trigger Scanner Workflow
3. Investigator Workflow
4. Tradeability & Resolution Workflow
5. Risk & Cost Approval Workflow
6. Execution Workflow
7. Position Review Workflow
8. Calibration Update Workflow
9. Performance Review Workflow
10. Policy Review Workflow
11. Strategy Viability Assessment Workflow
12. Bias Audit Workflow
13. Operator Absence Management Workflow

### 5.2 Workflow Cadence

**Eligibility Intake:** every 30–60 minutes.

**Trigger Scanner:** every 1–5 minutes. Cheap, mostly deterministic polling loop with local cache.

**Investigator:** Three modes — scheduled broad sweep (2–3× daily), trigger-based (immediate on Level C), operator-forced (manual).

**Position Review:** Tiered:
- New positions (first 48 hours): every 2–4 hours
- Stable positions: every 6–8 hours
- Low-value positions: every 12 hours
- Trigger-based: immediate when conditions trip configured rules (any tier)

**Calibration Update:** daily after new resolution data is available.

**Performance Review:** weekly. Produces Category Performance Ledger and shadow-vs-market comparison as mandatory outputs.

**Policy Review:** weekly or biweekly. Proposes changes only when evidence thresholds are met.

**Strategy Viability Assessment:** at weeks 4, 8, and 12 of shadow mode; then monthly during live operation. Also triggered at lifetime budget consumption thresholds.

**Bias Audit:** weekly, aligned with Performance Review.

**Operator Absence Check:** continuous (checked at every workflow execution).

---

## 6. Market Intake and Eligibility Gate

### 6.1 Purpose

Before any expensive reasoning occurs, the system performs a deterministic market eligibility screen.

### 6.2 Eligibility Rules

A market is immediately rejected if any of the following is true:

- category is excluded
- market is closed, suspended, or non-tradable
- wording is obviously malformed or unresolvable
- resolution source is missing or undefined
- contract horizon is outside the configured range
- market is below minimum observable liquidity threshold
- spread is beyond the configured hard limit
- for Sports markets: any Sports Quality Gate criterion fails
- market duplicates a currently held event cluster in a blocked way
- visible depth at top 3 levels is below the minimum required for the system's minimum position size divided by the liquidity fraction limit

### 6.3 Eligibility Output

Each market receives one of: **Reject** (with reason code), **Watchlist**, **Trigger-Eligible**, **Investigate-Now**.

Only Trigger-Eligible and Investigate-Now markets may reach the trigger scanner and investigation layers.

### 6.4 Eligibility Logging

Every decision logged with: market identifier, outcome, rejection reason code, timestamp, eligibility rule version, visible depth snapshot.

---

## 7. Trigger Scanner

### 7.1 Mission

The Trigger Scanner provides event-driven responsiveness. It replaces overdependence on slow scheduled discovery.

### 7.2 Data Infrastructure

#### 7.2.1 Primary Data Source: Polymarket CLOB API

Required polling targets per eligible market: best bid/ask prices, mid-market price, visible bid/ask depth at top levels, spread, last trade price/timestamp, market status field.

Polling interval: configurable, default 60 seconds per market batch.

Rate limit handling: respect API rate limits, exponential backoff on 429 responses, log every rate-limit event. If API unavailable for more than configured threshold (default: 5 consecutive failures per market), emit System Health event.

#### 7.2.2 Local CLOB Data Cache

The scanner maintains a local cache with the following properties:

- **Cache depth:** last N hours of data per market (default: 4 hours)
- **Cache granularity:** every successful poll result stored with timestamp
- **Cache serving:** when API poll fails, scanner serves most recent cached data, flagged with cache age
- **Cache freshness threshold:** cached data older than configured threshold (default: 3 minutes) is considered stale
- **Short outage handling:** if API unavailable but cached data younger than freshness threshold, scanner continues normal operation without entering degraded mode
- **Degraded mode trigger:** API unavailable AND all cached data exceeds freshness threshold
- **Cache storage:** lightweight in-memory or on-disk key-value store

#### 7.2.3 Secondary Data Source: News and Event Feed

Acceptable: RSS feeds from pre-approved sources, structured event data from configured APIs (sports results, government data endpoints), any deterministically parseable feed.

Unacceptable in scanner layer: open-ended web search, social media firehose, feeds requiring LLM interpretation.

The scanner must not call an LLM to process raw news text. Unparseable items are logged and passed to the Investigator as hints.

#### 7.2.4 Secondary Price Source

A configured secondary price source (e.g., Polymarket subgraph/GraphQL endpoint) for basic price monitoring when CLOB API is unavailable. Used ONLY for: basic price monitoring, detecting large adverse moves on held positions, triggering Level D risk interventions. NOT used for depth analysis, trigger detection beyond price/status, or any decision requiring full order book data.

#### 7.2.5 Scanner Failure Behavior and Degraded Mode Escalation

**Level 0 — Cache Served (No degradation):**
API temporarily unavailable, cached data within freshness threshold. Normal operation from cache. Logged as INFO.

**Level 1 — Degraded Mode Entry:**
API unavailable AND cache exceeds freshness threshold. System Health alert. Stale data flagged. No new Discovery Triggers. Operator notified.

**Level 2 — Extended Degraded Mode (4+ hours):**
Position sizes reduced by configured percentage (default: 15%). Review frequency increased. Escalated alert.

**Level 3 — Severe Degraded Mode (8+ hours):**
Graceful position reduction begins — close profit-target positions, reduce break-even positions, hold loss positions only if thesis strong. Critical alert.

**Recovery:** API availability → refill cache → return to normal. Positions reduced during degradation not automatically re-entered; require new investigation cycle.

### 7.3 Scanner Signal Types

Price move beyond threshold, spread widening/narrowing, sudden depth change, catalyst window approach, held position sharp adverse move, held position sharp favorable move near profit-protection conditions, status changes, structured external event hooks.

### 7.4 Scanner Properties

Mostly deterministic, low-cost (no LLM in hot path), explainable, producing machine-readable trigger events with typed reasons.

### 7.5 Trigger Classes

Discovery Trigger, Repricing Trigger, Liquidity Trigger, Position Stress Trigger, Profit Protection Trigger, Catalyst Window Trigger, Operator Trigger.

### 7.6 Trigger Escalation Levels

- **Level A:** log only, no workflow action
- **Level B:** lightweight model or rules-based quick review
- **Level C:** full investigation or full position review
- **Level D:** immediate risk intervention without waiting for LLM review — never deferred by cost budget, operator absence mode, or degraded scanner mode

---

## 8. Investigator Workflow

### 8.1 Mission

The Investigator is a selective escalation engine, not a broad batch collector.

### 8.2 Core Principle

Seek a small number of high-quality opportunities. Producing no trade is the correct output most of the time.

### 8.3 Pre-Run Cost Estimation

Before any investigation run, the Cost Governor must approve.

**Step 1:** Classify run type — scheduled broad sweep (higher cost), trigger-based single candidate (lower cost), operator-forced (variable).

**Step 2:** Estimate token budget — candidate count × tokens per domain manager, expected sub-agent spawns × tokens per type, one Orchestration Agent synthesis (Opus if escalated), one Tradeability pass per survivor.

**Step 3:** Compute expected dollar estimate — expected_run_cost_min (no escalation) and expected_run_cost_max (full escalation, multiple candidates).

**Step 4:** Compare to Cost Governor budgets — daily budget remaining AND lifetime experiment budget remaining.

### 8.4 Candidate Volume Constraint

Per run: zero (correct most of the time), one (most common non-zero), two (only when clearly independent and high quality), never more than three.

### 8.5 Structure

**Orchestration Agent:** Claude Opus 4.6 for final synthesis, adversarial weighing, no-trade decisions. Not for routine summarization or low-quality candidates.

**Domain Managers:** Politics, Geopolitics, Sports (under Quality Gate), Technology, Science & Health, Macro / Policy.

**Default Research Pack** (always spawned for surviving candidates):
1. Evidence Research Agent
2. Counter-Case Agent
3. Resolution Review Agent
4. Timing / Catalyst Agent
5. Market Structure Agent

**Optional Sub-Agents** (only when domain manager explicitly justifies cost):
- Data Cross-Check Agent
- Sentiment Drift Agent
- Source Reliability Agent

### 8.6 Investigation Sequence

1. Receive trigger or scheduled scope
2. Pre-run cost estimate → Cost Governor pre-approval
3. Fetch candidate markets from eligible pool
4. Rank by trigger urgency and fit profile
5. Filter by edge discovery focus — deprioritize heavily covered markets
6. Assign domain manager for top candidates only
7. Run compact sub-agent pack
8. Build structured domain memo
9. Run adversarial synthesis (Orchestration Agent)
10. Attach base-rate comparison and base-rate deviation to thesis card
11. Compute entry impact estimate using current depth data
12. Compute net edge after friction AND entry impact
13. Decide no trade vs. surviving candidate
14. Forward surviving candidate to Tradeability & Resolution Workflow

### 8.7 Required Candidate Rubric

Every candidate must be scored on: evidence quality, evidence diversity, evidence freshness, resolution clarity, market structure quality, timing clarity, counter-case strength, ambiguity level, expected gross edge, cluster correlation burden, calibration confidence source class, cost-to-evaluate estimate, expected holding horizon, category quality tier, base-rate for this market type, base-rate deviation, market-implied probability at forecast time, entry impact estimate, liquidity-adjusted maximum position size.

---

## 9. Tradeability and Resolution Workflow

### 9.1 Mission

Determine whether a thesis-worthy market is actually tradable and whether its wording is sufficiently unambiguous.

### 9.2 Design Principle

Deterministic checks run first. Agent-assisted interpretation runs only for surviving candidates with non-trivial residual ambiguity.

### 9.3 Deterministic Resolution Parser

Checks for: explicit named resolution source, explicit resolution deadline, ambiguous conditional wording ("may", "could", "at the discretion of"), undefined key terms, multi-step dependencies, unclear jurisdiction, counter-intuitive resolution risk, contract wording version changes.

### 9.4 Hard Rejection Patterns

Auto-reject if: wording meaningfully ambiguous, resolution source unstable/unnamed/discretionary, contract can resolve contrary to common-sense thesis interpretation, practical exit conditions unacceptable, spread/depth fails hard limits, manipulation risk extreme, visible depth below minimum for minimum position size.

### 9.5 Tradeability Output

One of: **Reject** (with reason code), **Watch** (recheck later), **Tradable with Reduced Size** (includes liquidity-adjusted max), **Tradable at Normal Size Range** (includes liquidity-adjusted max).

---

## 10. Risk Governor

### 10.1 Mission

The Risk Governor is the highest authority for capital protection. Fully deterministic. No LLM may override it.

### 10.2 Core Philosophy

The Investigator is opportunity-seeking. The Position Manager is stability-seeking. The Risk Governor is loss-preventing. When priorities conflict, the Risk Governor wins.

### 10.3 Capital Rules

- **Max daily new deployment:** 10% of account balance
- **Max daily drawdown:** 8% of start-of-day equity (realized + unrealized PnL)
- **Max total open exposure:** configurable hard cap
- **Max simultaneous positions:** configurable cap

### 10.4 Drawdown Defense Ladder

| Level | Trigger | Action |
|-------|---------|--------|
| Soft Warning | 3% daily drawdown | Higher evidence threshold; size suggestions reduced |
| Risk Reduction Mode | 5% daily drawdown | New entries materially reduced; lower-conviction blocked |
| New Entries Disabled | 6.5% daily drawdown | No new entries; position management and risk reduction only |
| Hard Kill Switch | 8% daily drawdown | All entries blocked; capital preservation mode |

### 10.5 Exposure Rules

**Category Exposure:** max per domain, per political cluster, per sports cluster, per tech cluster.
**Correlation Rules:** max to correlated positions, same event cluster, same source narrative.
**Quality Rules:** no entry below minimum evidence/liquidity quality, above ambiguity threshold, or with weak calibration at full size.
**Regime Rules:** drawdown state reduces multipliers, heavy exposure blocks similar bets.

### 10.6 Liquidity-Relative Sizing

No order may exceed a configured fraction (default: 12%) of visible depth at the top 3 price levels. This is a hard cap. The Risk Governor computes from latest depth snapshot and applies as a ceiling on approved size.

If entry impact estimate exceeds a configured fraction (default: 25%) of expected gross edge, the Risk Governor must reduce size or reject.

### 10.7 Operator Absence and Scanner Restrictions

During Operator Absent Mode: no new entries, size reduction schedule enforced.
During Level 2/3 scanner degraded mode: corresponding size reductions enforced.

### 10.8 Position Sizing Logic

Size is determined from: estimated edge, calibration confidence, evidence quality/diversity, liquidity quality, ambiguity level, correlation burden, remaining daily risk budget, remaining domain budget, liquidity-relative ceiling, entry impact budget.

Conceptually: **Size ∝ Edge × Confidence × Evidence Quality × Liquidity Quality × Remaining Budget** with downward penalties for ambiguity, correlation, weak sources, unclear timing, and disagreement.

### 10.9 Risk Approval Outputs

Reject, Delay, Watch, Approve Reduced Size, Approve Normal Size, Approve with Special Conditions (tighter revalidation, smaller initial size, operator acknowledgment, shortened review interval, staged entry, Sports multiplier reduction).

### 10.10 No-Trade Authority

The Risk Governor may declare no new trades when: positions consume the opportunity budget, drawdown is elevated, candidate quality insufficient, correlation burden too high, market conditions too noisy, or system confidence is inadequate. The ability to do nothing is a required feature.

---

## 11. Cost Governor

### 11.1 Mission

Stop inference cost from silently consuming expected edge. Operate prospectively (pre-run gating) and retrospectively (post-run accounting). Track total experiment cost against lifetime budget.

### 11.2 Core Principle

A trade with gross edge but poor net edge after cost and friction is not a good trade.

### 11.3 Prospective Function: Pre-Run Cost Estimation

Decision logic:

- `expected_run_cost_max` within budget → approve at full tier
- `expected_run_cost_max` breaches daily but `min` does not → approve at reduced tier ceiling or reduced scope
- even `min` breaches daily budget → defer to next window (exception: Level D never deferred)
- estimated inference cost exceeds configured fraction of net edge → reject as cost-inefficient
- daily budget below 10% AND lifetime budget above 75% consumed → restrict to Tier B maximum

### 11.4 Retrospective Function: Post-Run Accounting

After every run: workflow type, run ID, model/provider per call, tokens per call, request count, estimated and actual cost per call, total run cost, candidate count, cost per accepted/rejected candidate, lifecycle cost attribution.

### 11.5 Cost-of-Selectivity Tracking

- **Daily:** total inference spend ÷ trades entered (7-day rolling average)
- **Per-closed-trade:** total lifecycle inference cost including allocated share of rejected investigations from same period
- **Cost-to-edge ratio:** per-trade inference cost ÷ realized gross edge
- **Target monitoring:** if cost-to-edge exceeds 20% rolling, emit `COST_SELECTIVITY_WARNING`

Allocated share of rejected investigations: (rejected count that day ÷ accepted count that day) × average rejected investigation cost.

### 11.6 Cumulative Position Review Cost Tracking

Cumulative inference cost per position tracked across all reviews. When exceeds 8% of position value → flag for cost-inefficiency exit review. When exceeds 15% of remaining expected value → drop to minimum review frequency (deterministic-only).

### 11.7 Lifetime Experiment Budget

Configured before shadow mode. Tracked daily.

- 50% consumed → `LIFETIME_BUDGET_50PCT` alert, trigger viability checkpoint
- 75% consumed → mandatory viability review requiring operator decision
- 100% consumed → pause all new investigations until operator provides additional budget
- Level D interventions never blocked by budget exhaustion

### 11.8 Cost Buckets

Track at: per workflow run, per market, per position lifecycle, per day, per week, per model/provider, per category, per-closed-trade (including selectivity allocation).

### 11.9 Budget Definitions

Required configurable budgets: max daily total, max per investigation run, max per accepted candidate, max per open position per day, max Opus escalation per day, max cumulative review cost per position (% of value, default: 8%), lifetime experiment budget.

### 11.10 Cost Escalation Policy

1. Deterministic checks first (no cost)
2. Cheap compression and extraction (utility model)
3. Workhorse reasoning (Sonnet)
4. Premium synthesis (Opus) only when earned

When cost-of-selectivity ratio exceeds target, Opus escalation requires higher minimum net-edge threshold: standard minimum × (1 + selectivity_ratio_excess / target_ratio).

### 11.11 Estimate Accuracy Feedback Loop

After every run: compare Pre-Run Cost Estimate to Actual Run Cost. Log difference. Recalibrate if consistently inaccurate.

---

## 12. Execution Engine

### 12.1 Mission

Translate approved, validated trade decisions into actual Polymarket orders. Fully deterministic.

### 12.2 Pre-Execution Revalidation

Immediately before entry, re-check: market open and accepting orders, side correct, spread within bounds, depth acceptable, drawdown state not worsened, exposure budget available, no duplicate order, no new ambiguity, approval not stale, order does not exceed liquidity-relative limit (12% of top-3 depth), entry impact within bounds (< 25% of gross edge), system not in Operator Absent Mode (exception: pre-approved wind-down actions).

If any check fails: delay and retry once, then cancel and alert.

### 12.3 Entry Impact Estimation

Before every order: walk through visible order book at top N levels, compute how many levels consumed, estimate mid-price movement, output `estimated_impact_bps`. If exceeds threshold (default: 50 bps), reduce size or switch to staged entry.

### 12.4 Controlled Entry Modes

- **Immediate full entry:** rare, high-confidence, low-friction, time-sensitive
- **Staged entry:** split across multiple orders (preferred when order exceeds 5% of top-3 depth)
- **Price-improvement wait:** hold pending better fill within configured window
- **Cancel if degraded:** cancel if conditions don't improve within timeout

### 12.5 Realized Slippage Recording

After every order: record estimated_slippage_bps, realized_slippage_bps (actual fill vs. mid-price at submission), slippage_ratio. If ratio consistently exceeds 1.5 across last 20 trades, recalibrate friction model.

### 12.6 Execution Logging

Each order logs: full approval chain (workflow → tradeability → risk → cost), revalidation outcome, any forced resize and reason, entry impact estimate, realized slippage, trade ID linked to thesis card and workflow run.

---

## 13. Position Review Workflow

### 13.1 Mission

Monitor and manage open positions. Thesis-based. Responsive to scheduled windows and live triggers. Cost-efficient through tiered frequency and deterministic-first approach.

### 13.2 Tiered Review Frequency

**Tier 1 — New Positions (first 48 hours):** full review every 2–4 hours. All sub-agents available.

**Tier 2 — Stable Positions:** every 6–8 hours. Qualifies when: no trigger events in 24 hours, price within thesis range, no material evidence from scanner, held >48 hours.

**Tier 3 — Low-Value Positions:** every 12 hours. Qualifies when: size below configured threshold (bottom 20th percentile) AND remaining expected value below threshold.

**Tier Override:** Level C or D trigger immediately promotes to Tier 1.

### 13.3 Deterministic-First Review

At every scheduled review, deterministic checks run FIRST:

1. Current price vs. entry price and thesis target
2. Current spread vs. limits
3. Current depth vs. minimums
4. Thesis catalyst date — passed? Imminent?
5. Portfolio drawdown state
6. Position age vs. expected horizon
7. Cumulative review cost vs. cap

**All pass:** review completes as `DETERMINISTIC_REVIEW_CLEAR`, no LLM cost. Estimated ~65% of scheduled reviews.

**Any flags anomaly:** escalate to LLM review with appropriate sub-agents focused on flagged issues.

### 13.4 Review Modes

**Scheduled Review:** tiered frequency as above.
**Stress Review:** triggered by sharp adverse price move, liquidity deterioration, news shock.
**Profit Protection Review:** market reprices materially in favor.
**Catalyst Review:** approaching expected catalyst window.
**Cost-Efficiency Review:** cumulative review cost reaches cap.

### 13.5 Position Review Questions

Is the thesis intact? Has contract wording risk become relevant? Has the market repriced most edge? Has timing moved against us? Has liquidity deteriorated? Has new evidence weakened the thesis? Does this position still deserve capital? Has net edge after review cost deteriorated? Is remaining expected value sufficient for continued monitoring? Has liquidity dropped below minimum for orderly exit?

### 13.6 Position Actions

Hold, Trim, Partial Close, Full Close, Forced Risk Reduction (Risk Governor), Convert to Watch-and-Review State, Reduce to Minimum Monitoring (deterministic-only reviews, triggered by cost cap).

### 13.7 Exit Classes

All exits explicitly classified: Thesis-invalidated, Resolution-risk, Time-decay, News-shock, Profit-protection, Liquidity-collapse, Correlation-risk, Portfolio-defense, Cost-inefficiency, Operator-absence, Scanner-degradation.

### 13.8 Position Review Sub-Agents

**Update Evidence Agent:** gather/compress new developments. Tier C.
**Thesis Integrity Agent:** check whether thesis holds. Tier B.
**Opposing Signal Agent:** Tier C for simple updates, Tier B for complex evidence.
**Liquidity Deterioration Agent:** Tier D for metrics, Tier C for explanation.
**Catalyst Shift Agent:** summarize catalyst timeline changes. Tier C.

All sub-agents only invoked when LLM review is triggered by deterministic anomaly detection.

### 13.9 Premium Escalation

Opus for position review only when: position large relative to risk, near invalidation but ambiguous, new evidence conflicts with thesis, interpretation risk, remaining value justifies premium cost, AND cumulative review cost below cap.

---

## 14. Thesis Card

### 14.1 Purpose

The atomic decision unit. One per surviving candidate. Updated at each Position Review.

### 14.2 Required Fields

- market identifier, category, category quality tier (standard / quality-gated Sports)
- proposed side (Yes / No)
- exact resolution interpretation (verbatim source language + system interpretation)
- core thesis statement, why mispriced
- strongest supporting evidence (top 3, with source and freshness)
- strongest opposing evidence (top 3, with source and freshness)
- expected catalyst, expected time horizon
- invalidation conditions (explicit)
- resolution-risk summary, market-structure summary
- evidence quality score, evidence diversity score, ambiguity score
- calibration source status (no data / insufficient / preliminary / reliable)
- raw model probability estimate
- calibrated probability estimate (if available, with segment label)
- confidence note
- expected gross edge
- expected friction estimate (spread, slippage)
- entry impact estimate in basis points
- expected inference cost estimate
- expected net edge estimate (after friction AND impact)
- recommended size band, urgency of entry
- trigger source
- sports quality gate result (if Sports)
- market-implied probability at forecast time
- base-rate for this market type
- base-rate deviation (system estimate minus base rate)
- liquidity-adjusted maximum position size

### 14.3 Net Edge Distinction

The system explicitly distinguishes and records separately:

- **Gross edge:** market price vs. estimated probability
- **Friction-adjusted edge:** after spread and slippage
- **Impact-adjusted edge:** after entry impact estimate
- **Net edge after inference cost:** the number the system acts on

A candidate with positive gross edge but negative or near-zero impact-adjusted net edge must not be entered.

---

## 15. Calibration System

### 15.1 Mission

Build empirical forecast accuracy record. Correct raw LLM probability estimates. Control sizing discipline. Determine whether the system actually has edge over market consensus.

### 15.2 Core Principle

Raw LLM probabilities are advisory inputs, not sizing truth. System calibration measured in isolation is necessary but not sufficient — the system must outperform the market's own accuracy to have genuine edge.

### 15.3 Data Collection — Starting in Shadow Mode

Every market investigated during Shadow Mode produces a shadow forecast entry with all thesis card fields, raw model probability, market-implied probability at forecast time, tracked through to resolution.

### 15.4 Shadow-vs-Market Comparison

For every resolved forecast: System Brier = (system_probability − actual_outcome)², Market Brier = (market_implied − actual_outcome)², System advantage = Market_Brier − System_Brier (positive = system better).

Aggregated at: strategy level, per category, per horizon bucket, per time period.

### 15.5 Parallel Base-Rate Benchmark

Maintain historical base rate per market type. Compute base-rate strategy Brier score. Compare: system vs. market vs. base-rate. If system underperforms both market AND base-rate after 50+ resolved forecasts, system is subtracting value.

### 15.6 Hard Minimum Sample Thresholds

| Use Case | Minimum Resolved Trades |
|----------|------------------------|
| Initial calibration correction | 20 in segment |
| Category-level trusted | 30 in category |
| Horizon-bucket trusted | 25 in bucket |
| Sports trusted | 40 |
| Reducing size penalties | 30 AND Brier improvement vs. base rate |

Below thresholds: maximum shrinkage toward base rates, conservative size caps.

### 15.7 Cross-Category Pooling

Permitted for structurally similar segments (same horizon, similar market structure). Conservative 30% penalty factor. Combined pool minimum 15 trades, individual segment minimum 5. Never across structurally different categories (e.g., Politics and Sports). Logged when used.

### 15.8 Calibration Accumulation Rate Tracking

Track: resolved trades per week per segment, projected threshold date, bottleneck segments. Updated weekly in Performance Review. If majority of segments project beyond patience budget, recommend: focus on shorter-horizon markets, consider pooling, or adjust thresholds.

### 15.9 Calibration Segments

Maintained separately for: category, contract horizon bucket (same-day / 1–7 days / 1–4 weeks / 1–3 months / 3+ months), market type, ambiguity band (low / medium / high), evidence quality class.

### 15.10 Sizing Under Calibration Regimes

**Insufficient calibration:** hard size caps, evidence quality scoring, ambiguity penalties, liquidity scoring, correlation burden, liquidity-relative limits.

**Sufficient calibration:** calibrated estimates replace raw model probabilities. Liquidity-relative limits still apply.

### 15.11 Patience Budget

Maximum duration in conservative mode before requiring operator viability decision. Default: 9 months from shadow mode start. At expiry: comprehensive viability report, operator must explicitly decide (continue/adjust/terminate). Operator silence does not extend.

---

## 16. Category Performance Ledger

### 16.1 Purpose

Track performance by category. Identify which generate real edge and which consume costs.

### 16.2 Fields (per category, per time window)

Total trades entered/closed, win rate, gross PnL, inference cost attributed, net PnL, average gross/net edge at entry, average holding time, tradeability rejection rate, no-trade rate, calibration Brier score, exit class distribution, system-vs-market Brier comparison, cost-of-selectivity, average realized vs. estimated slippage, average entry impact as percentage of gross edge.

### 16.3 Update and Visibility

Updated weekly by Performance Review. Visible in dashboard as first-class section.

### 16.4 Category Actions

Persistent negative net PnL → Policy Review must address. Operator decides: pause, reduce multiplier, or continue with higher thresholds. No automatic shutdown. If system Brier consistently worse than market after 30+ trades in category, Policy Review must address regardless of PnL.

---

## 17. Strategy Viability System

### 17.1 Viability Checkpoints

- **Week 4:** Preliminary signal. Likely insufficient data. No decisions required.
- **Week 8:** Intermediate. If 20+ resolved, compare system vs. market. `VIABILITY_CONCERN` if system significantly worse.
- **Week 12:** Decision. If 50+ resolved and system worse than market, `VIABILITY_WARNING`. Operator must acknowledge.

Additional checkpoints at lifetime budget 50%, 75%, 100%.

### 17.2 Viability Metrics

System Brier (overall + per category), market Brier, base-rate Brier, system advantage, hypothetical shadow PnL, cost-of-selectivity, accumulation rate, lifetime budget consumption.

### 17.3 Decision Framework

| Condition | Signal | Action |
|-----------|--------|--------|
| System Brier < Market Brier after 50+ trades | Positive | Continue |
| System Brier ≈ Market Brier | Neutral | Continue with caution |
| System Brier > Market Brier | Negative | Operator review, consider pivot |
| System Brier > Base-Rate Brier | Strongly negative | LLM subtracting value; serious review |

---

## 18. Bias Detection System

### 18.1 Base-Rate Requirement

Every thesis card includes base rate (historical resolution rate for market type) and deviation (system estimate minus base rate). Sources: historical Polymarket data, analogous real-world rates, or default 50%.

### 18.2 Weekly Bias Audit

Checks for:

- **Directional bias:** average system probability vs. average market probability. Flag if persistent >5pp skew over 3+ weeks.
- **Confidence clustering:** flag if >50% of forecasts within a 20pp band.
- **Anchoring:** flag if average absolute difference from market price consistently below 3pp.
- **Narrative coherence over-weighting:** check if high-narrative-quality forecasts are less accurate than weak-narrative ones.
- **Base-rate neglect:** check if system deviations from base rates are systematically directional.

### 18.3 Alerting

`BIAS_PATTERN_DETECTED` → new pattern. `BIAS_PATTERN_PERSISTENT` → 3+ consecutive weeks. `BIAS_PATTERN_RESOLVED` → previously persistent pattern gone.

All detection is statistical. No LLM self-auditing.

---

## 19. Operator Absence System

### 19.1 Interaction Tracking

Login, dashboard view, manual trigger, config change, alert acknowledgment, any direct command.

### 19.2 Absence Escalation Ladder

| Duration | Status | Actions |
|----------|--------|---------|
| 0–48 hours | Normal | Standard operation |
| 48–72 hours | Absent Level 1 | No new positions. Review frequency increased. Alerts via all channels. |
| 72–96 hours | Absent Level 2 | Sizes reduced 25%. Escalated alert. |
| 96–120 hours | Absent Level 3 | Additional 25% reduction (~44% total). Wind-down prep. |
| 120+ hours | Graceful Wind-Down | Close profit targets → break-even → scheduled/expiry. Goal: zero exposure within 72 hours. |

### 19.3 Alert Channels

Critical alerts via at least two independent channels (Telegram + email recommended). Log delivery confirmation per channel.

### 19.4 Operator Return

Explicit acknowledgment required. System presents summary of autonomous actions. Normal operation resumes only after acknowledgment. Reduced positions not automatically re-entered.

### 19.5 Constraints

May NEVER: enter new positions, increase sizes, change parameters, override Risk/Cost Governor, delay Level D interventions. May ONLY: maintain or reduce positions, increase review frequency, close at targets/expiry, execute Risk Governor forced reductions, send alerts.

---

## 20. Learning Architecture

### 20.1 Fast Learning Loop (Daily)

- update resolved outcomes in calibration store
- refresh calibration tables
- detect recurring error classes
- flag underperforming market types
- update watchlists/blocklists
- update cost-of-selectivity, cumulative review costs
- update lifetime budget consumption
- update realized-vs-estimated slippage
- check operator absence status

### 20.2 Slow Learning Loop (Weekly / Biweekly)

- Category Performance Ledger
- domain and category analysis
- agent usefulness by role
- prompt and evidence source quality
- threshold review (too loose? too tight?)
- policy change proposals with evidence
- shadow-vs-market Brier comparison
- bias audit report
- calibration accumulation projections
- strategy viability assessment
- friction model accuracy review

### 20.3 Policy Change Discipline

No automatic policy change unless: minimum sample met, pattern persistence exists, change documented with evidence. In early deployment, all changes require operator review.

### 20.4 No-Trade Rate

Not a failure metric. Low no-trade rate → potential quality erosion. High → potential over-filtering. Both flagged by fast loop.

### 20.5 Friction Model Feedback

Every trade contributes slippage data. If realized exceeds estimated by >50% over 20 trades, adjust friction parameters upward. If below by >30%, relax slightly. Changes logged in weekly review.

---

## 21. Operator Modes

| Mode | Description |
|------|-------------|
| Paper Mode | Full decision generation, no live market data, no calibration |
| Shadow Mode | Live monitoring, full generation, calibration collected, no execution |
| Live Small Size | Live trading, strict caps, calibration ongoing |
| Live Standard | Full operation after all go-live gates met |
| Risk Reduction | Active drawdown defense, new entries restricted |
| Emergency Halt | All execution blocked, position management only |
| Operator Absent | Autonomous safe-mode, escalating restrictions, wind-down |
| Scanner Degraded | Escalating protective actions per outage duration |

### Recommended Launch Path

1. **Paper Mode:** Integration testing, log validation, cost chain modeling, liquidity logic testing, absence mode testing, Telegram testing
2. **Shadow Mode (min 6 weeks):** Live monitoring, calibration bootstrapping, Brier comparison, viability checkpoints, bias audit, entry impact simulation
3. **Live Small Size:** Strict caps, all tracking live, slippage tracking, cost-of-selectivity
4. **Live Standard:** Only after all Phase 3 gates met

---

## 22. Correlation Engine

A dedicated correlation engine inside the Risk Governor. Multiple markets can appear different while depending on the same hidden event cluster.

Tags positions by: event cluster, narrative cluster, source dependency, domain overlap, catalyst overlap.

Applies: maximum cluster exposure, maximum simultaneous exposure to one catalyst family, maximum overlap of uncertainty sources. Prevents fake diversification.

---

## 23. Confidence Calibration

The system distinguishes between:

- **Probability Estimate:** the raw model's probability assessment
- **Confidence Estimate:** how confident the system is in that probability
- **Calibration Confidence:** how well calibrated the system's confidence is based on historical data

Three separate fields. Prevents over-sizing on fragile conviction.

---

## 24. Provider and Model Strategy

Fully defined in modelsv4.md. Operating principles:

- Deterministic checks before any LLM call
- Cheap compression where possible (GPT-5.4 nano)
- Workhorse reasoning (Sonnet 4.6) for repeated analysis
- Premium orchestration (Opus 4.6) for final high-value synthesis
- No LLM for Risk Governor, Cost Governor arithmetic, Execution Engine, drawdown enforcement, calibration statistics, entry impact, slippage, bias statistics, viability metrics, operator absence, deterministic position review, liquidity sizing, friction model, CLOB cache, base-rate lookup

---

## 25. Data Model

### 25.1 Core Entities

Agent, Workflow, Workflow Run, Market, Position, Order, Trade, Thesis Card, Rule, Rule Decision, Risk Snapshot, Journal Entry, Structured Log Entry, Alert, Category, Event Cluster, Correlation Group, Policy Update Recommendation, System Health Snapshot, Trigger Event, Eligibility Decision, Resolution Parse Result, Cost Snapshot, Calibration Record, Calibration Segment, Net Edge Estimate, Cost Governor Decision, Market Quality Snapshot, Pre-Run Cost Estimate, Sports Quality Gate Result, Calibration Threshold Registry, Category Performance Ledger Entry, Shadow Forecast Record, Scanner Data Snapshot, Scanner Infrastructure Health Event, Market-Implied Probability Snapshot, Shadow-vs-Market Comparison Record, Base-Rate Reference, Entry Impact Estimate, Realized Slippage Record, Friction Model Parameters, Cost-of-Selectivity Record, Cumulative Review Cost Record, Bias Audit Report, Bias Pattern Record, Operator Interaction Event, Operator Absence Event, Strategy Viability Checkpoint, Lifetime Budget Status, Patience Budget Status, CLOB Cache Entry, Calibration Accumulation Projection, Notification Event, Notification Delivery Record.

### 25.2 Key Relationships

- one Workflow → many Workflow Runs
- one Workflow Run → many Agents
- one Position → many logs, journals, reviews
- one Pre-Run Cost Estimate → one Workflow Run (must exist before run starts)
- one Sports Quality Gate Result → one Market and one Eligibility Decision
- one Shadow Forecast Record → one Thesis Card → eventually one resolution outcome
- one Category Performance Ledger Entry → many closed Trades in that category/week
- one Scanner Data Snapshot → one Trigger Event
- one Market-Implied Probability Snapshot → one Calibration Record
- one Entry Impact Estimate → one Order
- one Realized Slippage Record → one Trade
- one Cumulative Review Cost Record → one Position (accumulates across reviews)
- one Bias Audit Report → many Bias Pattern Records
- one Operator Absence Event → many autonomous actions
- one Strategy Viability Checkpoint → Calibration Records + Comparison Records + Budget Status
- one Notification Event → one or more Notification Delivery Records (per channel)

---

## 26. Operator Notification Layer (Telegram)

### 26.1 Mission

Ensure the operator remains aware of important system actions, portfolio changes, risk events, workflow outcomes, and operational failures. Telegram is the first delivery channel.

### 26.2 Design Principle

Event-driven service, decoupled from trading logic:

- Investigator, Risk Governor, Execution Engine, Position Manager, Performance Analyzer, system health monitors → emit events
- Telegram Notification Service → subscribes, formats, delivers

### 26.3 Required Event Types

**A. Trade Entry Alerts:** event type, market title, identifier, side, entry price, allocated capital, portfolio percentage, confidence, estimated edge, thesis summary, timestamp, workflow source, trade ID.

**B. Trade Exit Alerts:** event type, market title, identifier, side, exit type (full/partial), exit reason, exit price, realized PnL, remaining size, timestamp, workflow source, trade ID.

**C. Risk Alerts:** threshold reached type (soft warning, risk reduction, entries disabled, kill switch, correlation breach, category limit, deployment cap), current equity, start-of-day equity, current drawdown, deployed capital, risk state, timestamp, position IDs.

**D. No-Trade Alerts:** workflow run time, reason, candidates reviewed, top rejected, rejection reasons, timestamp. Distinguishes healthy no-trade from failed workflow or stalled scheduler.

**E. Weekly Performance Alerts:** realized PnL, unrealized PnL, wins/losses, best/worst categories, strengths/weaknesses, policy recommendations, timestamp.

**F. System Health Alerts:** workflow started/completed/failed, scheduler missed, API failure, data source down, logging failure, latency spike, execution mismatch — severity, service, summary, timestamp, run ID.

**G. Strategy Viability Alerts:** checkpoint results, budget warnings, bias patterns.

**H. Operator Absence Alerts:** mode activation, escalation changes, autonomous actions.

### 26.4 Severity Levels

- **INFO:** routine actions, completed workflows, no-trade, weekly summaries
- **WARNING:** drawdown thresholds, partial closes, degraded quality, entries disabled, viability concerns, bias patterns
- **CRITICAL:** kill switch, execution failure, persistent outage, reconciliation error, budget exhausted

### 26.5 Message Format

Concise, scannable, structured, timestamped. Severity → event type → market/workflow → action → reason → risk impact → timestamp → reference ID. Compact default message; optional detailed follow-up for critical/weekly events.

### 26.6 Delivery Requirements

Retry on Telegram failure. Store failed attempts. Deduplicate repeated notifications. Persist status locally. Audit trail per notification: event ID, type, payload, send attempts, status, Telegram message ID, timestamps.

### 26.7 Security

Send only to pre-approved chat IDs. Reject unknown recipients. Secure bot credentials. Never expose trading credentials, API keys, or secrets in messages.

### 26.8 Relationship to Logging

Telegram does not replace structured logs or journals. It sits on top. Trading workflows → structured events → logged locally → journals written → Telegram receives notification-ready representation. Notification outcomes are themselves logged.

### 26.9 Future Extensions

Designed for channel expansion (email, SMS, Discord, dashboard push) without rewriting business logic.

---

## 27. Dashboard

The system includes a professional operational dashboard defined in the companion Dashboard Specification (polymarket_dashboard_spec.md).

The dashboard is the command, observability, and intelligence center. It answers: What is the system doing? Why? How much risk is on the table? Should I intervene?

It surfaces: executive overview, workflow visibility, agent visibility, open positions, risk board with drawdown ladder visualization, order/trade history, trading analytics, logs/journals, alert center with Telegram delivery status, system health, settings, operator controls.

Additionally, the dashboard surfaces as first-class sections:
- Category Performance Ledger
- Shadow-vs-market Brier comparison
- Cost-of-selectivity metrics
- Bias audit results and pattern tracking
- Strategy viability status and checkpoint history
- Calibration accumulation projections
- Lifetime experiment budget consumption
- Operator absence status and action history
- Scanner infrastructure health with cache and degraded-mode status
- Correlation and concentration visualization

---

## 28. Journaling and Logging

### 28.1 Narrative Journals

Concise and decision-relevant. Written by cheap utility model grounded in structured logs. Explain the decision — not free-form essays.

### 28.2 Required Structured Log Fields

Every investigation and position review: trigger source, model stack, pre-run cost estimate, actual cost, top evidence/counter-evidence, resolution-risk parse, tradeability outcome, risk decision, cost governor decision, net-edge estimate, calibration segment/status, final action, market-implied probability, base-rate and deviation, entry impact, review tier, whether deterministic-only, cumulative review cost, operator absence status.

Every trigger event: class, level, market identifier, data snapshot (price, spread, depth), reason, timestamp, data source (live/cache/secondary), whether escalated.

Every order: entry impact, realized slippage, slippage ratio, liquidity-relative size percentage.

Viability checkpoints, bias audits, absence events: structured queryable entries.

---

## 29. Deployment Guardrails

### 29.1 Before Shadow Mode

- eligibility gate tested
- scanner with defined data sources, local cache, secondary source tested
- structured logging working
- cost estimation model defined
- paper mode forecasting operational
- operator absence mode tested
- entry impact estimation tested
- base-rate data loaded
- lifetime budget configured
- patience budget configured
- full cost chain modeled
- redundant alert channels configured and tested
- Telegram delivery confirmed

### 29.2 Before Live Small Size

- shadow mode ≥ 6 weeks
- 20+ resolved shadow forecasts in ≥ 1 category
- scanner demonstrated stability
- tradeability and resolution engine tested
- risk governor tested
- cost governor (both functions) tested
- execution engine tested in paper/sandbox
- thesis cards and net-edge fields working
- no unresolved execution or wording failures
- shadow-vs-market Brier not significantly worse than market
- cost-of-selectivity within range
- entry impact model calibrated
- bias audit run ≥ 4 weeks with no persistent patterns
- operator absence mode tested in shadow
- lifetime budget not exhausted
- friction model calibrated against simulated data

### 29.3 Before Live Standard

- calibration baseline in ≥ 2 categories with 30+ trades each
- modest positive net expectancy evidence
- no severe unresolved failures
- stable workflow and scanner reliability
- ≥ 1 category with convincing positive net PnL
- system Brier ≥ market Brier in best category
- realized slippage ≤ 1.5× estimated on average
- no persistent bias patterns
- cost-of-selectivity within target
- friction model accuracy confirmed with live data
- calibration projections show reasonable remaining timelines
- operator has reviewed and approved

---

## 30. Non-Negotiable System Rules

1. Max daily new deployment: 10% of account balance.
2. Max daily drawdown: 8% of start-of-day equity (realized + unrealized).
3. New entries disabled before hard cap, using staged thresholds.
4. No position executed without passing Tradeability Filter.
5. No position executed without Risk Governor approval.
6. No order exceeds 12% of visible depth at top 3 levels.
7. All actions logged in narrative and structured form.
8. No-trade decision is a formal, logged output.
9. Correlated positions limited through cluster exposure controls.
10. Position management is thesis-based, not just price-based.
11. Performance review produces concrete policy updates.
12. No LLM may override Risk Governor, Cost Governor arithmetic, or Execution Engine.
13. No investigation run starts without Cost Governor pre-approval.
14. System must operate safely during 5-day operator absence.
15. Edge must be proven against market accuracy before scaling.

---

## 31. Final Philosophy

This system should not be understood as a single trading bot. It should be understood as a **layered market intelligence and portfolio control architecture**.

Its power comes from combining: domain-specific investigation, adversarial synthesis, thesis-driven position management, deterministic portfolio controls, structured learning from outcomes, honest self-measurement against market accuracy, and bounded experiment cost.

The most important architectural principles:

> Opportunity discovery should be agentic.
> Capital protection should be rule-based.
> System improvement should be evidence-driven.
> Edge should be proven, not assumed.

If implemented correctly, the system will not merely search for bets. It will search for mispriced opportunities, reject untradable markets, allocate capital carefully, defend the account under stress, compare itself honestly against the market, detect its own biases, survive operator absence, bound the cost of discovery, and refine its own operating policies over time.

You cannot know if the edge is real until you measure it honestly. This system is built to measure honestly, compare against the right benchmark, bound the cost of discovery, and protect capital throughout the process.
