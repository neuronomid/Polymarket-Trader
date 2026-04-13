# Polymarket Trader Agent — Product Requirements Document

## Document Status

Draft v4.0

## Product Name

Polymarket Trader Agent

## Document Purpose

This PRD defines the complete product behavior, operator needs, workflows, success metrics, constraints, acceptance criteria, rollout logic, and implementation priorities for the Polymarket Trader Agent trading engine.

This document is self-contained. No external specification documents are required to understand the product requirements, with the exception of the standalone Dashboard Specification (polymarket_dashboard_spec.md) and the Agent Models document (modelsv4.md), which are companions to this PRD.

---

## 1. Product Summary

The Polymarket Trader Agent is a selective, event-driven, cost-aware, empirically-calibrated, viability-accountable market decision system for Polymarket.

It is built for one operator-owner who wants:

- high-quality market selection with honest edge measurement
- strong explainability for every material decision
- disciplined risk control via deterministic rules
- controlled and accountable API spend with pre-run gating
- calibration built from shadow mode data before live sizing is trusted
- a realistic rollout that validates edge before scaling
- clear visibility into which categories are and are not working
- honest, early evidence of whether the strategy has genuine edge over market consensus
- explicit cost-of-selectivity accounting so true cost per closed trade is known
- liquidity-aware sizing that prevents self-inflicted market impact
- autonomous safe behavior when the operator is temporarily unavailable
- systematic detection of LLM reasoning biases before they compound into losses
- real-time operator visibility through a professional dashboard and Telegram notifications

The system is not a generic crawler, an autonomous trading lab, or a system that assumes edge exists. It is a narrower, more deliberate, more economically honest, and more self-aware operating system designed to discover whether real edge exists — and to survive the discovery process regardless of the answer.

---

## 2. Product Vision

Build a trading engine that is:

- safer than a naive AI bot (deterministic risk and cost controls)
- cheaper than an unconstrained agent swarm (pre-run cost gating)
- more responsive than a slow polling system (event-driven scanner)
- more honest about uncertainty than raw LLM forecasting (empirical calibration)
- more selective about where it competes (category exclusions and quality gates)
- more rigorous about measuring real profitability (net edge accounting + category ledger)
- more self-aware about whether it actually has edge (shadow-vs-market Brier comparison)
- more realistic about liquidity constraints (impact-aware sizing)
- more disciplined about total experiment cost (lifetime budget envelope)
- more resilient when the operator is temporarily absent (autonomous safe-mode)
- fully observable through a professional dashboard and real-time Telegram alerts

---

## 3. User

### Primary User

Single operator-owner managing the full system.

### User Needs

The user needs to:

- know whether the system is acting on good contracts only
- avoid high API burn on weak-edge candidates
- preserve the value of premium reasoning where it matters
- understand exactly why trades were entered, resized, or exited
- see net performance after inference cost and execution friction — not just gross PnL
- trust that resolution ambiguity and hidden concentration are actively filtered
- know which categories are performing and which are not
- not be surprised by scanner failures or stale data acting as if it were fresh
- have evidence of real edge before committing to full sizing
- know whether the system's forecasts are actually better than the market's implied probabilities
- understand the full cost of selectivity — not just cost per accepted candidate, but cost per closed trade including all rejected investigations
- trust that the system will not place orders large enough to move the market against itself
- trust that the system will behave safely if the operator is unavailable for several days
- know whether the system has systematic reasoning biases that are eroding performance
- have a clear maximum lifetime experiment budget so the discovery process is bounded
- receive timely, structured Telegram notifications for all material system events
- access a professional dashboard that answers "what is happening, why, what risk is on the table, and should I intervene" within seconds

---

## 4. Product Goals

### 4.1 Business / System Goals

1. Improve the probability of positive net expectancy.
2. Reduce unnecessary model spend through pre-run cost gating.
3. Reduce slow-reaction failure modes through explicit scanner infrastructure.
4. Increase confidence that trades are legally and mechanically understandable.
5. Create honest category-level evidence for whether the strategy deserves scaling.
6. Ensure calibration is built from shadow mode rather than waiting for live trading.
7. Determine strategy viability early through shadow-vs-market comparison.
8. Prevent self-inflicted market impact through liquidity-relative sizing.
9. Bound the total cost of the strategy discovery experiment.
10. Ensure system safety during operator absence periods.

### 4.2 User Goals

1. Keep Opus 4.6 where it adds real value at decision bottlenecks.
2. Avoid cutting costs in ways that damage decision quality at critical moments.
3. Exclude categories that are poor fits.
4. Apply a quality gate to Sports rather than treating it as equivalent to Politics or Macro.
5. Know within 8–12 weeks of shadow mode whether the strategy concept is viable.
6. Never discover after the fact that a trade moved the market against itself.
7. Have confidence the system degrades gracefully during operator absence.
8. Always be able to trace any trade from trigger to exit through structured logs and narrative journals.

### 4.3 Product Principles

- Risk first
- Cost-aware, not cost-obsessed — but cost gating must happen before the run, not after
- Premium reasoning only where earned
- Deterministic checks before agentic analysis
- Narrow scope beats broad ambition
- Net edge is the only edge that matters
- No-trade is not silence — it is a decision, logged and surfaced
- Calibration before scaling
- Prove edge exists before trusting edge exists
- Size relative to liquidity, not just relative to conviction
- The experiment itself has a budget; discovery is not free
- Safe autonomy when unattended is a requirement, not a feature
- Detect your own biases before the market punishes them

---

## 5. Core Design Philosophy

The system is built around a hybrid architecture:

- **Agent-based systems** are used for research, synthesis, debate, interpretation, and adaptive reasoning.
- **Rule-based systems** are used for risk limits, execution permissions, exposure controls, stop conditions, cost enforcement, and all hard portfolio constraints.

This distinction is intentional and non-negotiable. The system must never allow free-form agent reasoning to bypass deterministic capital controls.

The core operating principle:

> Agents may recommend.
> Rules may permit, resize, delay, reject, or force reduction.

---

## 6. Scope Definition

### 6.1 In Scope

- Trigger scanner infrastructure with defined CLOB API polling, local data cache, secondary price source, and optional structured news feeds
- Pre-run cost estimation and prospective Cost Governor
- Sports Quality Gate
- Calibration threshold registry with hard minimum sample thresholds per segment
- Shadow mode calibration data collection and shadow-vs-market Brier comparison
- Category Performance Ledger as a first-class weekly output
- No-trade rate as a primary success metric
- Shadow-vs-market Brier score comparison and strategy viability checkpoints
- Parallel base-rate benchmark strategy tracking
- Cost-of-selectivity metric (total cost per closed trade including rejected investigations)
- Liquidity-relative sizing limits and entry impact modeling
- Tiered position review frequency (new / stable / low-value)
- Deterministic-first position reviews (LLM only on anomaly escalation)
- Cumulative review cost caps per position
- Base-rate comparison on every thesis card
- Weekly bias audit with persistent pattern detection
- Operator Absent Mode with escalating restrictions and graceful wind-down
- Local CLOB data cache for scanner resilience
- Secondary price source fallback for basic monitoring
- Degraded-mode escalation ladder with time-based protective actions
- Calibration accumulation rate tracking and threshold timeline projections
- Cross-category calibration pooling with penalty factor
- Patience budget for conservative-mode duration
- Lifetime experiment budget with consumption alerts and forced viability decisions
- Realized-vs-estimated slippage tracking and friction model feedback
- Operator notification layer with Telegram as primary delivery channel
- Professional operational dashboard (defined in companion dashboard specification)
- Structured logging and narrative journaling for full trade reconstruction
- Eligibility gate with excluded-category enforcement
- Tradeability and resolution engine with deterministic parser and selective agent review
- Deterministic Risk Governor with drawdown defense ladder and veto authority
- Execution engine with stale-approval detection and controlled entry modes
- Position review (scheduled + trigger-based) with all exit classes
- Thesis cards with net-edge fields and calibration source status
- Performance Analyzer with weekly strategic synthesis
- Policy Review workflow with evidence threshold requirements
- Correlation engine for event-cluster and narrative-cluster exposure control

### 6.2 Out of Scope

- Redesigning the dashboard specification (governed by companion document)
- Building a social or public-facing product
- High-frequency or latency-arbitrage execution systems
- Trading excluded categories (News, Culture, Crypto, Weather)
- Adding new categories beyond the six defined
- Market-making or passive liquidity provision (identified as potential future consideration)
- Multi-operator support
- Remote portfolio control via Telegram (notifications only in current design)

---

## 7. Market Scope Requirements

### 7.1 Allowed Categories

The product must only consider markets in:

- Politics
- Geopolitics
- Technology
- Science and Health
- Macro / Policy / Institutional Events
- Sports (subject to Sports Quality Gate)

### 7.2 Excluded Categories

The product must permanently reject markets in:

- **News** — Generic breaking-news markets are reactive and speed-dominated. A reasoning-heavy system has no structural advantage.
- **Culture** — Culture and entertainment contracts suffer from soft, sentiment-driven resolution and weak objective grounding.
- **Crypto** — Crypto-related prediction markets attract faster, more technically sophisticated, more latency-oriented competition.
- **Weather** — Weather markets are best addressed by structured meteorological models, not by LLM reasoning over text.

Excluded category markets must never reach the investigation layer.

### 7.3 Sports Quality Gate

A Sports market is eligible only if:

- Resolution criteria are fully objective (win/loss, final score, official recorded outcome)
- Market resolves in more than 48 hours from time of investigation
- Market has adequate observable liquidity and depth
- Resolution does not depend primarily on a statistical modeling problem (spreads, exact totals)
- A credible evidential basis exists beyond available public statistics

Sports markets failing this gate are rejected with reason code `SPORTS_GATE_FAIL`.

### 7.4 Category Quality Tiers

For sizing purposes, the system defines two category quality tiers:

- **Standard Tier:** Politics, Geopolitics, Technology, Science and Health, Macro / Policy
- **Quality-Gated Tier:** Sports (lower default size multiplier until category calibration threshold met)

### 7.5 Preferred Market Profile for Edge Discovery

The system should prioritize markets where information asymmetry is plausible:

- Niche political events with limited public coverage
- Specific policy decisions requiring technical interpretation
- Scientific outcomes with domain-knowledge barriers
- Markets where timing of information arrival creates temporary mispricings

The system should deprioritize heavily covered events (major elections, championship finals) where market prices are likely already efficient.

---

## 8. Functional Requirements

### 8.1 Eligibility Intake

The system must:

- fetch markets on a configured schedule (every 30–60 minutes)
- classify category deterministically
- reject excluded categories immediately
- apply Sports Quality Gate for Sports markets
- apply hard market eligibility rules (market status, wording quality, resolution source, horizon, minimum liquidity, maximum spread)
- apply liquidity-relative sizing limits at intake for early rejection of insufficiently liquid markets
- tag remaining markets as Reject, Watchlist, Trigger-Eligible, or Investigate-Now
- log every eligibility decision with a reason code, market identifier, and timestamp

**Acceptance Criteria:**
- excluded categories never reach investigation
- malformed or obviously ambiguous contracts are rejected before any LLM use
- Sports markets carry a Quality Gate result record
- markets with insufficient depth relative to minimum position size are rejected at intake
- all eligibility decisions are logged with reason codes and timestamps

### 8.2 Trigger Scanner

The system must:

- poll Polymarket CLOB API at configured intervals (default: 60 seconds per market batch) for all eligible and held-position markets, collecting best bid/ask, mid-price, visible depth at top levels, spread, last trade price/timestamp, and market status
- maintain a local cache of CLOB data for the last N hours (default: 4 hours) per market
- serve short API outages (< 3 minutes) from cache without triggering degraded mode
- maintain a configured secondary price source (e.g., Polymarket subgraph endpoint) for basic price monitoring when the CLOB API is unavailable
- optionally consume one or more structured news or event feeds for Discovery and Catalyst triggers (RSS feeds, structured event APIs — no open-ended web search or social media firehose in scanner layer)
- detect trigger conditions deterministically in the scanner hot path (no LLM in hot path)
- assign typed trigger classes: Discovery, Repricing, Liquidity, Position Stress, Profit Protection, Catalyst Window, or Operator
- apply escalation level logic: Level A (log only), Level B (lightweight review), Level C (full investigation or position review), Level D (immediate risk intervention, never deferred)
- handle API rate limits with exponential backoff
- enter degraded mode when primary data source is unavailable beyond cache freshness, with escalating protective actions:
  - Level 1 (cache stale): alert emitted, no new discovery triggers, stale data flagged
  - Level 2 (4+ hours continuous): position sizes reduced, review frequency increased
  - Level 3 (8+ hours continuous): graceful position reduction begins
- emit System Health alerts on scanner infrastructure failures

**Acceptance Criteria:**
- every trigger event is logged with class, level, market state snapshot, and timestamp
- scanner data source configuration is explicit and documented
- scanner failure degrades safely (no fake signals from stale data)
- short outages are served from cache without degraded mode
- degraded mode beyond 4 hours triggers position size reduction
- degraded mode beyond 8 hours triggers graceful position reduction
- scanner infrastructure health is a distinct monitored status

### 8.3 Investigator

The system must:

- request pre-run cost estimate and Cost Governor pre-approval before any LLM calls
- investigate only a narrow top-candidate set (zero to three candidates maximum per run)
- use compact research packs: Evidence Research Agent, Counter-Case Agent, Resolution Review Agent, Timing/Catalyst Agent, Market Structure Agent (default), plus optional Data Cross-Check, Sentiment Drift, Source Reliability agents when justified
- use premium synthesis selectively (Opus 4.6 for final orchestration synthesis; Sonnet 4.6 for domain managers and analytical work)
- generate structured thesis cards with net-edge fields, base-rate comparison, market-implied probability, and entry impact estimate
- compute entry impact estimate for every surviving candidate and subtract from net edge calculation

**Acceptance Criteria:**
- no investigation run starts without a Pre-Run Cost Estimate record and Cost Governor approval
- each accepted candidate includes all required thesis card fields including base-rate comparison
- most low-quality runs terminate with no-trade
- actual vs. estimated cost is recorded after each run for model improvement
- every thesis card includes market-implied probability, base rate, and entry impact estimate

### 8.4 Tradeability & Resolution Engine

The system must:

- run a deterministic resolution parser on every surviving candidate, checking for: explicit named resolution source, explicit deadline, ambiguous conditional wording, undefined key terms, multi-step dependencies, unclear jurisdiction, counter-intuitive resolution risk, and contract wording version changes
- reject severe ambiguity patterns before any agent-assisted review
- apply Sports Quality Gate result to tradeability logic
- apply liquidity-relative sizing constraints to tradeability output
- output one of: Reject (with reason code), Watch (recheck later), Tradable with Reduced Size, or Tradable at Normal Size Range — each including liquidity-adjusted maximum size

**Acceptance Criteria:**
- every candidate has a Resolution Parse Result record
- every rejection has an explicit reason code
- contracts with severe wording ambiguity cannot pass to Risk Governor
- tradeability output includes liquidity-adjusted maximum position size

### 8.5 Risk Governor

The Risk Governor is the highest authority for capital protection. It is fully deterministic. No LLM may override it.

The system must:

- enforce max daily new deployment cap (default: 10% of account balance)
- enforce max daily drawdown cap (default: 8% of start-of-day equity, measured on total equity including unrealized PnL)
- enforce staged drawdown defense ladder:
  - Soft Warning at 3%: higher evidence threshold, size suggestions reduced
  - Risk Reduction Mode at 5%: new entries materially reduced, lower-conviction blocked
  - New Entries Disabled at 6.5%: no new entries, position management and risk reduction only
  - Hard Kill Switch at 8%: all entries blocked, capital preservation mode
- enforce category exposure limits
- enforce correlation and event-cluster exposure controls (event cluster, narrative cluster, source dependency, domain overlap, catalyst overlap)
- maintain explicit no-trade authority
- enforce liquidity-relative sizing limit: no order may exceed a configured fraction (default: 12%) of visible depth at the top 3 price levels
- enforce entry impact budget: reject or reduce size when entry impact estimate exceeds a configured fraction (default: 25%) of expected gross edge
- enforce operator-absent mode restrictions when applicable
- enforce degraded scanner restrictions when applicable
- consider model cost burden, calibration regime confidence, and category-specific historical reliability in approval decisions
- output one of: Reject, Delay, Watch, Approve Reduced Size, Approve Normal Size, or Approve with Special Conditions

**Acceptance Criteria:**
- no candidate bypasses risk approval
- all reductions or rejections are logged with rule reason and threshold value
- drawdown state changes are visible in logs and alerts
- no order exceeds the configured fraction of visible depth
- operator-absent restrictions are enforced when applicable

### 8.6 Cost Governor

The Cost Governor stops inference cost from silently consuming expected edge. It operates both prospectively (pre-run gating) and retrospectively (post-run accounting).

The system must:

- produce a Pre-Run Cost Estimate before every investigation run, computing expected_run_cost_min and expected_run_cost_max based on run type, candidate count, model tiers, and estimated tokens
- apply pre-run approval decisions: approve at full tier, approve at reduced tier ceiling, reduce candidate scope, defer to next window (never defer Level D triggers), or reject on cost-inefficiency grounds
- enforce daily and per-run spend ceilings
- block candidates where estimated inference cost exceeds a configured fraction of net edge
- track all model costs retrospectively per workflow run, market, position, day, week, model, provider, and category
- track cost-of-selectivity daily: total daily inference spend ÷ trades entered, with 7-day smoothing
- track per-closed-trade total cost including attributed share of rejected investigations
- track cumulative review cost per position and enforce cumulative cost cap (default: 8% of position value)
- track cumulative spend against lifetime experiment budget and emit alerts at 50%, 75%, and 100% consumption
- supply cost data to the Risk Governor as an input

**Acceptance Criteria:**
- every workflow run has a Pre-Run Cost Estimate record before start and a post-run Cost Snapshot
- cost-of-selectivity metric is computed and logged daily
- cumulative review cost per position is tracked and capped
- lifetime experiment budget tracking is operational with alerts at thresholds

### 8.7 Execution Engine

The system must:

- re-check all conditions immediately before order placement (market open, side, spread, depth, drawdown, exposure, duplicates, ambiguity, stale approval, liquidity-relative limit, entry impact, operator-absent status)
- compute and record entry impact estimate (projected mid-price movement from order)
- support controlled entry modes: immediate full entry, staged entry (preferred when order exceeds 5% of top-3-level depth), price-improvement wait, cancel if degraded
- record realized slippage and compare to estimated; recalibrate friction model if ratio exceeds 1.5x over recent trades
- log full approval chain, entry impact, realized slippage, and link to thesis card

**Acceptance Criteria:**
- no order sent without passing final pre-execution revalidation
- no order exceeds liquidity-relative sizing limit
- realized vs. estimated slippage logged per trade

### 8.8 Position Review

The system must:

- use tiered review frequency:
  - New positions (first 48 hours): every 2–4 hours
  - Stable positions (no triggers, price within thesis range): every 6–8 hours
  - Low-value positions (small size, low remaining value): every 12 hours
- run deterministic checks first at every scheduled review; only escalate to LLM when anomalies detected
- review on trigger immediately (Level C/D events bypass tiers)
- evaluate thesis integrity comprehensively
- support all position actions: Hold, Trim, Partial Close, Full Close, Forced Risk Reduction, Watch-and-Review, Reduce to Minimum Monitoring
- classify all exits: Thesis-invalidated, Resolution-risk, Time-decay, News-shock, Profit-protection, Liquidity-collapse, Correlation-risk, Portfolio-defense, Cost-inefficiency, Operator-absence, Scanner-degradation
- escalate to Opus only when position is large/near invalidation/conflicting evidence AND cumulative review cost below cap AND remaining value justifies it

**Acceptance Criteria:**
- every review produces structured action result with explicit action class
- exits always have explicit exit class
- most scheduled reviews complete with deterministic checks only (no LLM cost)
- cumulative cost cap triggers cost-inefficiency exit consideration

### 8.9 Calibration System

The system must:

- begin collecting forecasts in Shadow Mode from day one, storing market-implied probability alongside each
- apply hard minimum sample thresholds:
  - Initial calibration correction: 20 resolved trades in segment
  - Category-level: 30 resolved trades
  - Horizon-bucket: 25 resolved trades
  - Sports: 40 resolved trades
  - Reducing size penalties: 30 trades AND Brier improvement vs. base rate
- support cross-category pooling for similar segments (30% penalty factor, pool minimum 15 trades, segment minimum 5)
- compute shadow-vs-market Brier score comparison weekly
- maintain parallel base-rate benchmark
- track accumulation rate and project threshold timelines weekly
- enforce patience budget (default: 9 months)

**Acceptance Criteria:**
- shadow forecasts enter calibration store from day one with market-implied probability
- shadow-vs-market comparison computed weekly
- sizing logic visibly different in insufficient vs. sufficient calibration regimes
- accumulation projections updated weekly

### 8.10 Category Performance Ledger

Updated weekly. Per category: total trades, win rate, gross PnL, inference cost, net PnL, average edge, holding time, rejection rates, no-trade rate, Brier score, exit distribution, system-vs-market Brier, cost-of-selectivity, slippage ratio, entry impact percentage. Visible in dashboard as first-class section.

### 8.11 Strategy Viability System

Checkpoints at weeks 4 (preliminary), 8 (intermediate), 12 (decision). Each compares system Brier vs. market Brier vs. base-rate benchmark. If system worse than market after 50+ resolved forecasts, `VIABILITY_WARNING` emitted. Lifetime budget tracked with alerts at 50/75/100%.

### 8.12 Bias Detection System

Base-rate and deviation on every thesis card. Weekly audit: directional bias, confidence clustering, anchoring, narrative coherence over-weighting, base-rate neglect. All detection is statistical (no LLM self-auditing). Persistent patterns (3+ weeks) trigger alerts.

### 8.13 Operator Absence System

Tracks last operator interaction. Escalation: 48hr → no new entries + alerts; 72hr → 25% size reduction; 96hr → additional 25%; 120hr+ → graceful wind-down to zero exposure. Alerts via redundant channels. Operator return requires explicit acknowledgment.

### 8.14 Operator Notification Layer (Telegram)

Event-driven service: workflows emit events, Telegram Notification Service subscribes and delivers. Required events: Trade Entry, Trade Exit, Risk Alerts, No-Trade, Weekly Performance, System Health, Strategy Viability, Operator Absence. Severity levels: INFO, WARNING, CRITICAL. Messages are concise, scannable, timestamped. Retry on failure, deduplicate, persist status, audit trail. Send only to pre-approved chat IDs. Designed for future channel expansion (email, SMS, Discord).

### 8.15 Dashboard

Defined in companion Dashboard Specification. Serves as command, observability, and intelligence center. Surfaces: executive overview, workflows, agents, positions, risk board, analytics, logs/journals, alerts, system health, settings, operator controls. Also surfaces: Category Performance Ledger, Brier comparison, cost-of-selectivity, bias audit, viability status, calibration projections, lifetime budget, absence status, scanner health.

### 8.16 Logging and Explainability

Full trade reconstruction from trigger to exit. Narrative journals grounded in structured logs. Every investigation and review logs: trigger source, models used, cost estimates, evidence, decisions, calibration status, base-rate, entry impact, review tier, absence status. Viability, bias, and absence data queryable as structured entries.

---

## 9. Non-Functional Requirements

**Reliability:** Safe degradation, local CLOB cache, multi-day operator absence resilience.
**Explainability:** Every action traceable, rejection as important as approval, cost/base-rate/impact transparent.
**Cost Efficiency:** Prospective and retrospective control, deterministic-first reviews, lifetime budget.
**Extensibility:** Category expansion, model changes, notification channels, future market-making.
**Auditability:** All decisions logged with reasons, operator actions audited, costs archived.
**Resilience:** 5-day operator absence tolerance, short outage tolerance, degraded-mode escalation, redundant alerts.

---

## 10. Metrics and Success Criteria

### Primary

Net expectancy after costs, no-trade rate, drawdown adherence, explanation coverage, Brier score, cost per candidate, cost per trade, category net PnL, shadow-vs-market Brier, cost-of-selectivity ratio, slippage ratio.

### Secondary

Rejection rates, latency, model usage, holding time, cost estimate accuracy, accumulation rate, base-rate deviation, review cost percentage, absence frequency, budget consumption, bias persistence, Telegram delivery rate.

### Failure

Wording surprises, cost-erased edge, missed reviews, reversed policies, degraded-mode periods, missed cost estimates, excess slippage, excess depth usage, Brier underperformance weeks, persistent bias, absence events, notification failures.

---

## 11. Launch and Rollout

**Phase 1 — Paper Mode:** Integration testing, cost chain modeling, all logic validated. If projected cost exceeds 20% of projected edge, adjust tiers.

**Phase 2 — Shadow Mode (minimum 6 weeks):** Live monitoring, no execution. Brier comparison, base-rate benchmark, viability checkpoints, bias audit, entry impact simulation, Telegram testing. Exit requires: 20+ resolved forecasts, scanner stability, Brier not worse than market, cost ratio acceptable, cache/absence/alerts tested.

**Phase 3 — Live Small Size:** Strict caps, all tracking live. Exit requires: 30+ trades in 2 categories, positive net expectancy evidence, Brier ≥ market in best category, slippage ≤ 1.5x, no persistent bias, operator approval.

**Phase 4 — Live Standard:** Full operation after all Phase 3 gates met.

---

## 12. Policy Governance

**Daily:** Calibration updates, error detection, watchlists, cost-of-selectivity, review costs, budget, absence check.

**Weekly:** Category ledger, domain analysis, agent evaluation, threshold review, Brier comparison, bias audit, calibration projections, viability assessment, friction model review.

**Evidence Rule:** No policy change below minimum sample. Operator review required in early deployment.

**Category Suspension:** Operator decision required. No automatic shutdown. If Brier worse than market after 30+ trades, Policy Review must address.

**Patience Budget:** At expiry (default 9 months), operator must explicitly decide.

---

## 13. Product Decisions

1. Hybrid rule + agent philosophy
2. Thesis-based position management
3. Opus at high-value synthesis points
4. Exclude News, Culture, Crypto, Weather
5. Quality gate for Sports
6. Event-driven scanner with cache and fallback
7. Prospective + retrospective Cost Governor
8. Calibration starts in Shadow Mode with hard thresholds
9. No-trade rate is primary metric
10. Category Performance Ledger mandatory weekly
11. Minimum 6 weeks Shadow Mode
12. Compare against market accuracy, not just absolute calibration
13. Track full cost-of-selectivity
14. Liquidity-relative sizing on all orders
15. Entry impact deducted from net edge
16. Deterministic-first position reviews
17. Base-rate comparison on every thesis card
18. Weekly bias audits
19. Operator-absent autonomous safe-mode
20. Lifetime experiment budget
21. Local CLOB cache
22. Calibration projections and patience budget
23. Telegram as primary notification channel
24. Dashboard as standalone companion spec

---

## 14. MVP Definition

### Must Ship

Eligibility gate, trigger scanner with cache/fallback/escalation, investigator with cost gating, tradeability engine, risk governor with liquidity limits, cost governor with selectivity/review caps/lifetime budget, execution engine with impact/slippage tracking, tiered deterministic-first position review, thesis cards with full fields, calibration store with shadow-vs-market, calibration projections, category ledger, viability checkpoints, bias audit, operator absent mode, friction model, Telegram notifications, dashboard.

### Can Wait

Advanced policy automation, additional categories, extra model families, agent visualizations, prompt mutation, market-making, sentiment divergence, contrarian signals, multi-operator, remote Telegram control.

---

## 15. Final Product Statement

This system should feel like a system ready to honestly discover whether it has real edge — and designed to survive regardless of the answer.

> Opportunity discovery should be agentic.
> Capital protection should be rule-based.
> System improvement should be evidence-driven.
> Edge should be proven, not assumed.
