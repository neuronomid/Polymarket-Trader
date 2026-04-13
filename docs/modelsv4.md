# Agent Models V4

## Document Status

Draft v4.0

## Relationship to V3 Models

V3 kept all correct V2 patterns (Opus at decision bottlenecks, Sonnet as workhorse, cheap utility for formatting, no LLM for safety zones) and added cost class annotations per role, pre-run cost estimation as Tier D, calibration-regime-aware behavior, Sports category elevated conservatism, estimate accuracy feedback loop, and explicit no secondary challenger model by default.

V4 keeps all of that.

V4 adds the following model-relevant changes based on the critical assessment of V3:

- **Deterministic-first position review:** most scheduled position reviews should complete with deterministic checks only (no LLM cost). LLM-based review is triggered only when deterministic checks flag anomalies. This changes the effective cost profile of position review from "always Tier B" to "usually Tier D, occasionally Tier B, rarely Tier A."
- **New Tier D roles:** entry impact computation, realized slippage computation, liquidity-relative sizing enforcement, operator absence logic, bias audit statistics, cost-of-selectivity computation, calibration accumulation projections, shadow-vs-market Brier comparison, and lifetime budget tracking are all deterministic — no LLM.
- **Bias audit synthesis:** the weekly bias audit requires a Tier C summary of statistical findings, but all bias detection is statistical (Tier D). The audit does not use an LLM to detect biases — that would be asking the LLM to audit itself.
- **Strategy viability checkpoint synthesis:** viability checkpoint reports use Tier C for human-readable summaries of statistical results. The viability determination is based on Brier scores and statistics, not LLM judgment.
- **Cost-of-selectivity awareness in escalation decisions:** the Cost Governor's pre-run approval must now consider cost-of-selectivity ratio when deciding whether to approve Tier A escalation. If the ratio is already above target, Tier A escalation requires stronger justification.

---

## 1. V4 Model Philosophy

### 1.1 General Principles

1. Deterministic checks and hard rules before any LLM call.
2. Pre-run cost estimation before any multi-LLM workflow begins.
3. **Deterministic-first position review before any LLM-based review (V4).**
4. Cheap models for compression, extraction, formatting, and repetitive utility work.
5. Workhorse models for repeated, meaningful reasoning tasks.
6. Premium models only at high-value synthesis or high-risk decision bottlenecks.
7. One primary provider stack for most reasoning. One secondary stack for selective fallback.
8. Every premium escalation must be explainable and logged.
9. No LLM in any deterministic safety or risk control zone.
10. **No LLM for any statistical computation, metric calculation, or bias detection arithmetic (V4).**
11. **No LLM for auditing its own reasoning biases — bias detection is statistical, not introspective (V4).**

### 1.2 Provider Strategy

V4 uses:

- **Primary stack:** Anthropic (Opus 4.6 for premium, Sonnet 4.6 for workhorse)
- **Utility stack:** OpenAI GPT-5.4 nano for formatting, compression, journal writing, and alert composition (GPT-5.4 mini as alternative for higher-capability utility tasks)
- No secondary challenger model by default

### 1.3 Cost Model Requirement

For the Cost Governor's pre-run estimation, every role has an associated cost estimate class:

| Class | Description | Estimated Range Per Call |
|-------|-------------|------------------------|
| **L** (Low) | Utility model calls, short context, high volume | $0.001–$0.005 |
| **M** (Medium) | Workhorse model calls, moderate context | $0.01–$0.05 |
| **H** (High) | Premium model calls, full synthesis context | $0.05–$0.30 |
| **Z** (Zero) | Deterministic, no LLM | $0 |

These are directional ranges for pre-run budgeting. Actual costs are tracked retrospectively and used to calibrate estimates over time.

### 1.4 Effective Cost Profile for Position Review (V4)

V4 introduces a critical distinction between the **assigned model tier** and the **effective cost profile** for position review:

- **Assigned tier:** Tier B (Sonnet) for full LLM-based review, Tier A (Opus) for escalated review
- **Effective cost profile:** ~65% of scheduled reviews complete as Tier D (deterministic only, $0 LLM cost), ~25% escalate to Tier B, ~10% escalate to Tier A

This means the **average cost per position review** is significantly lower than the per-call cost of Tier B, because most reviews don't invoke an LLM at all. The Cost Governor must use the effective cost profile, not the assigned tier cost, when estimating position review costs in pre-run budgeting.

---

## 2. Model Tiers in V4

**Tier A: Premium Reasoning**
Use rarely. Only at decision bottlenecks where synthesis quality has real trading value.
Primary model: Claude Opus 4.6. Cost class: H.

**Tier B: Workhorse Reasoning**
Use for repeated but meaningful reasoning. The main analytical engine.
Primary model: Claude Sonnet 4.6. Cost class: M.

**Tier C: Utility / Compression**
Use for structured extraction, summarization, log compression, journal drafting, alert formatting, bias audit summaries, viability checkpoint summaries.
Primary model: GPT-5.4 nano (cheapest, fastest current utility model — optimized for classification, data extraction, ranking, and simple supporting tasks). Cost class: L.
Alternative: GPT-5.4 mini when a Tier C task requires slightly more capability (e.g., complex evidence compression from technical domains). Still cost-efficient but more capable than nano.
Specific model within Tier C may change based on cost and capability without requiring a full model config update, as long as it remains a low-cost utility-grade model.

**Tier D: No LLM**
Always deterministic. Never delegated to a language model.

Examples:
- Risk Governor
- Cost Governor arithmetic and budget enforcement
- Execution permission checks
- Drawdown enforcement
- Exposure limits
- Kill switch logic
- Eligibility hard gates
- Calibration statistics computation
- Resolution parser core rules
- Sports Quality Gate deterministic checks
- **Entry impact computation (V4)**
- **Realized slippage computation (V4)**
- **Liquidity-relative sizing enforcement (V4)**
- **Operator absence logic and escalation (V4)**
- **Bias detection statistics (V4)**
- **Cost-of-selectivity computation (V4)**
- **Calibration accumulation rate projection (V4)**
- **Shadow-vs-market Brier score computation (V4)**
- **Lifetime experiment budget tracking (V4)**
- **Patience budget tracking (V4)**
- **CLOB cache management (V4)**
- **Friction model parameter updates (V4)**
- **Deterministic position review checks (V4)**
- **Base-rate lookup and deviation computation (V4)**

---

## 3. Role-by-Role Assignments

### 3.1 Eligibility Intake Classifier

**Model:** Tier D (No LLM) by default. Cost class: Z.

Category classification and hard eligibility rules are deterministic. Pattern matching on market metadata is sufficient. **Liquidity-relative minimum depth checks are deterministic (V4).**

Escalation: Tier C only when market wording is genuinely unclear for category classification. Rare.

### 3.2 Trigger Scanner

**Model:** Tier D (No LLM) — fully deterministic in hot path. Cost class: Z.

The scanner must not call any LLM in its main polling and detection loop. All trigger detection must be computable from structured market data. **CLOB cache management and secondary source fallback are deterministic (V4).**

Optional: Tier C for generating human-readable trigger summary text in alerts. Presentation-only.

### 3.3 Pre-Run Cost Estimator

**Model:** Tier D (No LLM) — deterministic arithmetic. Cost class: Z.

**V4 addition:** The cost estimator must use the effective cost profile for position review (see Section 1.4), not the assigned tier cost, when estimating ongoing position monitoring costs.

### 3.4 Investigator Orchestration Agent

**Default model:** Claude Opus 4.6 (Tier A). Cost class: H. **Fallback:** Claude Sonnet 4.6 (Tier B).

Role: Final synthesis of domain memos, adversarial weighing of evidence, deciding whether thesis quality is sufficient for capital consideration, deciding no-trade when evidence is weak.

**When Opus applies:**
- Candidate has survived deterministic filtering and compact research
- Net-edge estimate is non-trivial (above configured minimum)
- **Net-edge estimate remains non-trivial AFTER entry impact deduction (V4)**
- Evidence quality rubric is not clearly poor
- Cost Governor pre-approval has been granted for Tier A usage this run
- **Cost-of-selectivity ratio is not already above target (V4)**

**When fallback to Sonnet applies:**
- Cost Governor pre-approval was granted only for Tier B ceiling
- Candidate appears low-quality after domain memo
- Daily Opus escalation budget is exhausted
- **Cost-of-selectivity ratio is above target — Opus escalation requires stronger justification (V4)**

Logged field: `model_used`, `escalation_approved_by_cost_governor`, **`cost_selectivity_ratio_at_decision` (V4)**

### 3.5 Domain Manager Agents

**Default model:** Claude Sonnet 4.6 (Tier B). Cost class: M.

Roles covered: Politics Manager, Geopolitics Manager, Sports Manager, Technology Manager, Science & Health Manager, Macro / Policy Manager.

Note on Sports Manager: operates same model tier as others. Sports Quality Gate is deterministic upstream.

### 3.6 Evidence Research Agent

**Default model:** Tier C (utility / fast model). Cost class: L.

Role: Collect, compress, and structure high-signal evidence items.

Escalation: Tier B (Sonnet) only when evidence is highly complex, contradictory, or from technical domains. Must be explicitly justified.

### 3.7 Counter-Case Agent

**Default model:** Claude Sonnet 4.6 (Tier B). Cost class: M.

Role: Generate the strongest structured case against the thesis. Counter-case quality is important enough to justify a workhorse model.

Escalation to Opus (Tier A): Only when candidate size/risk is high, thesis is highly ambiguous, or counter-case directly contradicts strong evidence on a large expected position.

### 3.8 Resolution Review Agent

**Default model:** Claude Sonnet 4.6 (Tier B), but only after deterministic resolution parser has run. Cost class: M.

Escalation to Opus (Tier A): When wording ambiguity survives both deterministic parser and Sonnet review, and contract is still valuable enough to justify premium interpretation.

### 3.9 Timing / Catalyst Agent

**Default model:** Tier C (utility / fast model). Cost class: L.

Escalation: Tier B when timing depends on complex conditional chains or regulatory calendars.

### 3.10 Market Structure Agent

**Default model:** Tier D (No LLM) for raw metric computation; Tier C for synthesis summary text. Cost class: Z for metrics; L for summary.

**V4 addition:** Entry impact estimation is part of market structure analysis and is always Tier D (deterministic computation from order book data). The go/no-go on market structure, including liquidity-relative sizing limits, is always deterministic.

### 3.11 Tradeability Synthesizer

**Default model:** Claude Sonnet 4.6 (Tier B). Cost class: M.

Escalation to Opus (Tier A): Only for rare high-value borderline cases where deterministic checks pass, resolution wording is non-trivially ambiguous but not auto-rejected, and net edge is meaningful.

### 3.12 Risk Governor

**Model:** Tier D (No LLM). Cost class: Z.

Hard capital controls must remain deterministic, auditable, and not subject to language model reasoning. **Liquidity-relative sizing enforcement is part of the Risk Governor and is always deterministic (V4).**

### 3.13 Cost Governor

**Model:** Tier D (No LLM) for all arithmetic, budget enforcement, and approval decisions. Cost class: Z.

**V4 additions:** Cost-of-selectivity computation, cumulative review cost tracking, lifetime budget tracking, and patience budget tracking are all Tier D deterministic operations.

### 3.14 Execution Engine

**Model:** Tier D (No LLM). Cost class: Z.

**V4 additions:** Entry impact computation at execution time and realized slippage recording are Tier D deterministic operations.

### 3.15 Position Review Orchestration Agent

**Assigned model:** Claude Sonnet 4.6 (Tier B). Cost class: M.

**V4 critical change — Deterministic-First Review:**

The Position Review Orchestration Agent is only invoked when deterministic checks flag an anomaly. The review sequence is:

**Step 1 (always, Tier D):** Run deterministic review checks:
- Current price vs. entry price and thesis range
- Current spread vs. limits
- Current depth vs. minimums
- Catalyst date proximity
- Portfolio drawdown state
- Position age vs. expected horizon
- Cumulative review cost vs. cap

**Step 2 (conditional):** If ALL deterministic checks pass → log `DETERMINISTIC_REVIEW_CLEAR`, schedule next review at current tier interval. No LLM cost. **This should be the outcome ~65% of the time.**

**Step 3 (conditional):** If ANY check flags an anomaly → invoke Position Review Orchestration Agent (Tier B). The agent receives the specific anomaly flags and focuses its review on the flagged issues, not a full open-ended review.

**Escalation to Opus (Tier A):** Apply when one or more of these is true:
- position size is large relative to current allowed risk
- position is near invalidation but genuinely ambiguous
- new evidence materially conflicts with thesis
- resolution wording creates non-trivial interpretation risk
- the remaining expected value justifies premium review cost
- **cumulative review cost is below the cap (V4)**

**Effective cost class for budgeting:** weighted average of Z (65%), M (25%), H (10%) ≈ significantly lower than M.

### 3.16 Position Review Sub-Agents

**Update Evidence Agent**
Default: Tier C. Cost class: L. Only invoked when LLM-based review is triggered.

**Thesis Integrity Agent**
Default: Claude Sonnet 4.6 (Tier B). Cost class: M. Only invoked when LLM-based review is triggered. **Not invoked on deterministic-clear reviews (V4).**

**Opposing Signal Agent**
Default: Tier C for simple updates; Tier B when evidence complexity is high. Only invoked when LLM-based review is triggered.

**Liquidity Deterioration Agent**
Default: Tier D for metric computation; Tier C for explanation text. **Liquidity metrics are always computed deterministically even during deterministic-only reviews (V4).**

**Catalyst Shift Agent**
Default: Tier C. Cost class: L. Only invoked when LLM-based review is triggered.

### 3.17 Calibration Update Processor

**Model:** Tier D (No LLM) for all statistical computation. Cost class: Z.

**V4 additions:** Shadow-vs-market Brier score computation, cross-category pooling calculations, calibration accumulation rate projections, and base-rate benchmark tracking are all Tier D statistical operations.

Optional Tier C usage: Human-readable calibration summary for weekly Performance Review report.

### 3.18 Performance Analyzer

**Default model:** Claude Opus 4.6 (Tier A) for final strategic synthesis. Cost class: H.

Compression step required before Opus: Tier C or deterministic summarization must compress raw logs before sending to Opus.

**V4 additions to Performance Analyzer input:**
- Shadow-vs-market Brier comparison data (computed by Tier D)
- Cost-of-selectivity metrics (computed by Tier D)
- Bias audit results (computed by Tier D, summarized by Tier C)
- Calibration accumulation projections (computed by Tier D)
- Realized vs. estimated slippage analysis (computed by Tier D)
- Strategy viability assessment data (computed by Tier D)

Category Performance Ledger compilation: Tier D (deterministic aggregation).

Fallback: Claude Sonnet 4.6 if weekly Opus budget is exhausted.

Why keep Opus here: Weekly strategic review is one of the few legitimate places where deep synthesis over a large structured context may materially improve future decisions.

### 3.19 Journal Writer

**Default model:** Tier C (utility / cheap model). Cost class: L.

Journals must be grounded in structured logs. Not a free-form narrative generator.

### 3.20 Alert Composer

**Default model:** Tier C (utility / cheap model). Cost class: L.

**V4 note:** Operator absence alerts, degraded mode alerts, viability warnings, and bias pattern alerts all use the same Tier C alert composer. Alert content is templated and short.

### 3.21 Dashboard Explanation Helper

**Default model:** Tier C (utility / cheap model). Cost class: L.

### 3.22 Bias Audit Processor (V4 — New)

**Model:** Tier D (No LLM) for all statistical analysis. Cost class: Z.

The bias audit is entirely statistical:
- Directional bias: arithmetic mean comparison
- Confidence clustering: histogram computation
- Anchoring detection: mean absolute difference computation
- Narrative coherence bias: correlation analysis between evidence quality scores and forecast accuracy
- Base-rate neglect: statistical comparison of system estimates vs. base rates

**Tier C (utility model)** is used only for producing the human-readable bias audit summary. The summary describes what the statistics show. The LLM does not interpret whether the bias is a problem or suggest corrections — that judgment belongs to the operator and the Performance Analyzer.

This separation is critical: an LLM must not audit its own reasoning biases. The detection is statistical; the interpretation may be LLM-assisted (via Performance Analyzer) but only after statistical facts are established.

### 3.23 Strategy Viability Checkpoint Processor (V4 — New)

**Model:** Tier D (No LLM) for all viability metric computation. Cost class: Z.

Viability metrics (system Brier vs. market Brier vs. base-rate Brier, hypothetical PnL, cost-of-selectivity, accumulation rate) are all computed deterministically.

**Tier C (utility model)** for producing the human-readable viability checkpoint report.

The viability determination (positive/neutral/negative/strongly negative) is made by deterministic threshold comparison, not LLM judgment.

### 3.24 Entry Impact Calculator (V4 — New)

**Model:** Tier D (No LLM). Cost class: Z.

Entry impact is computed from order book data:
- Walk through the visible order book at the top N levels
- Compute how many levels the order would consume
- Estimate mid-price movement from the order
- Output: `estimated_impact_bps`

This is arithmetic over structured data. No LLM involvement.

### 3.25 Friction Model Calibrator (V4 — New)

**Model:** Tier D (No LLM). Cost class: Z.

Compares realized slippage to estimated slippage across recent trades. Adjusts friction model parameters (spread estimate, depth assumption, impact coefficient) based on statistical deviation. No LLM involvement.

### 3.26 Operator Absence Manager (V4 — New)

**Model:** Tier D (No LLM). Cost class: Z.

All operator absence logic is deterministic: timestamp comparison, escalation level determination, size reduction computation, wind-down scheduling. No LLM involvement.

---

## 4. Escalation Policy

### 4.1 When to Escalate to Tier A (Opus)

Escalate only when ALL of the following are true:

- candidate has survived deterministic filtering
- a meaningful net-edge estimate exists above configured minimum
- **net-edge estimate remains meaningful AFTER entry impact deduction (V4)**
- ambiguity is non-trivial and unresolved by Tier B reasoning
- position size or portfolio consequence is meaningful
- Cost Governor has pre-approved Tier A usage for this run
- daily Tier A escalation budget is not exhausted
- **cost-of-selectivity ratio is not already above target, OR the specific candidate justifies the cost (V4)**

### 4.2 When Not to Escalate

Do not escalate when:

- contract already fails hard rules
- market quality is clearly too poor
- expected net edge is thin or negative
- the task is only summarization, extraction, or formatting
- the position is tiny and low consequence
- Cost Governor has denied Tier A escalation for this run
- **entry impact would consume more than 25% of gross edge (V4) — the opportunity itself is questionable**
- **cumulative review cost for this position has already exceeded the cap (V4)**
- **the position review completed deterministically with no anomalies (V4)**

### 4.3 Escalation Logging Requirement

Every Tier A escalation must be logged with:

- reason for escalation
- which rule or condition triggered it
- whether Cost Governor pre-approved it
- actual cost of the Tier A call
- **cost-of-selectivity ratio at time of decision (V4)**
- **cumulative position review cost if position-related (V4)**

---

## 5. Cost Discipline Rules

### 5.1 Hard Requirements

Every model call must be attributable to: workflow run ID, market or position ID, provider and model name, input and output tokens, estimated dollar cost, cost class (L / M / H / Z).

### 5.2 Budget Requirements

Required configurable budgets:

- daily total inference budget
- daily Tier A (Opus) escalation budget (sub-budget within daily total)
- per investigation run budget (max and Tier B-ceiling variants)
- per open position per day budget
- per accepted candidate lifecycle budget
- **max cumulative review cost per position as % of position value (default: 8%) (V4)**
- **lifetime experiment budget (V4)**

### 5.3 Compression-First Rule

Before sending any large context to Opus or another Tier A model: deduplicate evidence items, compress logs to decision-critical fields only, remove boilerplate and low-signal text, preserve only state that materially affects the decision. Hard requirement.

### 5.4 Position Lifecycle Cost Discipline

No position should be monitored with unlimited repeated premium calls.

**V4 Enhancement:** The system tracks cumulative review cost per position. When cumulative cost reaches 8% of position value, review frequency drops to minimum (deterministic-only). When cumulative cost reaches 15% of remaining expected value, a cost-inefficiency exit review is mandatory.

### 5.5 Estimate Accuracy Feedback Loop

After every workflow run, compare Pre-Run Cost Estimate to Actual Run Cost. Log the difference. Recalibrate if estimates are consistently inaccurate.

**V4 Enhancement:** The estimate accuracy feedback loop must separately track accuracy for:
- investigation runs (scheduled sweep vs. trigger-based)
- position reviews (deterministic-only vs. LLM-escalated)
- full lifecycle estimates vs. actual lifecycle costs

### 5.6 Cost-of-Selectivity Awareness in Escalation (V4)

When the rolling cost-of-selectivity ratio exceeds the target (20% of gross edge), the Cost Governor must apply additional scrutiny to Tier A escalation requests:

- Tier A escalation is still permitted but requires that the specific candidate's expected net edge (after all costs including the Tier A call) exceeds a higher minimum threshold
- The higher threshold is: standard minimum × (1 + selectivity_ratio_excess / target_ratio)
- This creates natural feedback: as the cost of finding trades increases, the system demands higher quality from each investigation, which should either improve selectivity or reduce activity to bring costs in line

---

## 6. Model Behavior by Calibration Regime

### 6.1 Insufficient Calibration Regime

When a category or segment has fewer resolved trades than the hard threshold:

- Conservative size caps apply
- Investigator Orchestration Agent receives a "low calibration confidence" flag
- Agent should be more conservative about thesis confidence and more willing to issue no-trade
- Opus usage for borderline decisions is permitted only when net edge is clearly meaningful despite uncertainty

### 6.2 Sufficient Calibration Regime

When a category or segment has met its minimum sample threshold:

- Calibrated probability estimates replace raw model estimates
- Agents receive calibrated probability context
- Size caps relax from conservative to standard (still subject to Risk Governor)

### 6.3 Sports Category Regime

Sports operates at higher conservatism until its calibration threshold (40 resolved trades) is met:

- Sports positions carry a lower size multiplier
- Investigator receives "Sports quality-gated — elevated conservatism" flag
- No premium Opus escalation for Sports unless genuinely exceptional

### 6.4 Viability-Uncertain Regime (V4)

When the system's Brier score is not yet demonstrably better than the market's (fewer than 50 resolved forecasts, or system Brier ≈ market Brier):

- Investigator Orchestration Agent receives a "strategy viability unproven" flag
- Agent should apply higher evidence threshold for all candidates
- Opus escalation requires even stronger justification: the candidate must not only be high-quality but must represent the type of market where the system is most likely to have edge (niche, under-covered, thesis-amenable)
- Size recommendations should be conservative regardless of calibration regime

When the system's Brier score is demonstrably better than the market's in a specific category:

- That category's viability is considered established
- Normal escalation and sizing rules apply for that category
- The system can recommend increased focus on that category

---

## 7. V4 Model Stack Summary

### Primary Stack

| Tier | Model | Use |
|------|-------|-----|
| Tier A | Claude Opus 4.6 | Final synthesis, adversarial review, weekly performance analysis |
| Tier B | Claude Sonnet 4.6 | Domain managers, counter-case, tradeability synthesis, position review (when escalated) |
| Tier C | GPT-5.4 nano (or GPT-5.4 mini for complex utility tasks) | Journals, alerts, evidence extraction, summaries, explanations, bias audit summaries, viability reports |
| Tier D | No LLM | Risk Governor, Cost Governor, Execution, Scanner, Calibration math, entry impact, slippage, bias statistics, viability metrics, operator absence, deterministic position review, liquidity sizing, friction model, CLOB cache, base-rate lookup |

### Cost Class Summary

| Role | Tier | Cost Class |
|------|------|------------|
| Investigator Orchestration | A | H |
| Domain Managers | B | M |
| Counter-Case Agent | B | M |
| Resolution Review Agent | B | M |
| Tradeability Synthesizer | B | M |
| Position Review Orchestration | B (when invoked) | M |
| Thesis Integrity Agent | B (when invoked) | M |
| Performance Analyzer final synthesis | A | H |
| Evidence Research Agent | C | L |
| Timing / Catalyst Agent | C | L |
| Market Structure summary | C | L |
| Journal Writer | C | L |
| Alert Composer | C | L |
| Dashboard Explanation Helper | C | L |
| **Bias Audit Summary (V4)** | **C** | **L** |
| **Viability Checkpoint Summary (V4)** | **C** | **L** |
| Risk Governor | D | Z |
| Cost Governor | D | Z |
| Execution Engine | D | Z |
| Trigger Scanner | D | Z |
| Calibration Processor | D | Z |
| Eligibility Gate | D | Z |
| Pre-Run Cost Estimator | D | Z |
| **Deterministic Position Review Checks (V4)** | **D** | **Z** |
| **Entry Impact Calculator (V4)** | **D** | **Z** |
| **Friction Model Calibrator (V4)** | **D** | **Z** |
| **Bias Audit Statistics (V4)** | **D** | **Z** |
| **Viability Metrics Computation (V4)** | **D** | **Z** |
| **Operator Absence Manager (V4)** | **D** | **Z** |
| **Cost-of-Selectivity Calculator (V4)** | **D** | **Z** |
| **Calibration Accumulation Projector (V4)** | **D** | **Z** |
| **CLOB Cache Manager (V4)** | **D** | **Z** |
| **Liquidity-Relative Sizing Enforcer (V4)** | **D** | **Z** |
| **Shadow-vs-Market Comparator (V4)** | **D** | **Z** |
| **Base-Rate Reference Lookup (V4)** | **D** | **Z** |
| **Lifetime Budget Tracker (V4)** | **D** | **Z** |

### Effective Position Review Cost Profile (V4)

| Review Outcome | Tier | Frequency | Cost Class |
|----------------|------|-----------|------------|
| Deterministic clear — no anomalies | D | ~65% of scheduled reviews | Z |
| LLM review — standard | B | ~25% of scheduled reviews | M |
| LLM review — premium escalation | A | ~10% of scheduled reviews | H |
| Trigger-based review (always full) | B or A | variable | M or H |

**Weighted average cost per scheduled review:** approximately $0.005–$0.015 (vs. $0.01–$0.05 per review in V3).

This represents a **50–70% reduction in position review cost** relative to V3 with no reduction in safety, because deterministic checks catch all the conditions that require urgent attention.

---

## 8. What Changed from V3 Models

### V3 Patterns (unchanged in V4)

- Opus at decision bottlenecks
- Sonnet as workhorse
- Cheap utility model for formatting/journals/alerts
- No LLM for Risk Governor, Execution, Cost Governor arithmetic, Calibration math
- Cost class annotation per role
- Pre-Run Cost Estimator as Tier D
- Calibration-regime-aware behavior
- Sports category elevated conservatism
- Estimate accuracy feedback loop
- No secondary challenger model by default

### V4 Additions to Model Document

- **Deterministic-first position review** — most scheduled reviews complete as Tier D, dramatically reducing ongoing monitoring cost
- **Effective cost profile for position review** — Cost Governor uses weighted average, not worst-case tier, for budgeting
- **New Tier D roles** — entry impact, slippage, liquidity sizing, bias statistics, viability metrics, operator absence, cost-of-selectivity, calibration projections, friction model, CLOB cache, base-rate lookup, lifetime budget tracking
- **Bias audit processor** — Tier D statistics + Tier C summary; LLM never audits its own biases
- **Strategy viability checkpoint processor** — Tier D computation + Tier C summary; viability is determined by statistics, not LLM judgment
- **Cost-of-selectivity awareness in escalation** — high selectivity cost ratio increases Opus escalation threshold
- **Viability-uncertain regime** — model behavior adapts when strategy viability is unproven
- **Cumulative review cost as escalation gate** — positions that have exceeded review cost cap cannot trigger Opus escalation

---

## 9. Final V4 Model View

The model strategy for V4 is:

**Keep Opus 4.6** where superior reasoning may materially improve a trade decision. Gate every Opus call through the Cost Governor, with additional scrutiny when cost-of-selectivity is elevated.

**Keep Sonnet 4.6** as the main serious workhorse for all repeated analytical work, but invoke it only when deterministic checks indicate it's needed for position review.

**Use a cheap utility model** for summaries, journals, alerts, evidence extraction, bias audit summaries, and viability checkpoint reports.

**Remove LLMs entirely** from risk control, cost arithmetic, execution permission, calibration statistics, entry impact computation, slippage computation, bias detection arithmetic, viability metric computation, operator absence logic, liquidity sizing enforcement, friction model calibration, and all deterministic safety zones.

**Make position reviews deterministic-first** so that ~65% of scheduled reviews cost nothing in LLM spend while maintaining full safety through deterministic anomaly detection.

**Annotate every role** with a cost class so the Cost Governor can estimate run cost before a single LLM call is made, using effective cost profiles where applicable.

**Adapt model behavior** to calibration regime, viability regime, and cost-of-selectivity ratio — conservative under insufficient data, conservative when viability is unproven, higher escalation bar when selectivity cost is elevated, standard only under sufficient evidence.

**Never use an LLM to audit itself.** Bias detection is statistical. Viability determination is statistical. The LLM may synthesize findings (via Performance Analyzer) but does not judge its own reasoning quality.

This gives V4 a model architecture that is sophisticated where it needs to be, cheap where it can be, self-aware about its own costs and biases, and economically honest from the first workflow run to the last.
