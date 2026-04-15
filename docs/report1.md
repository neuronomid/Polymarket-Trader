# Report 1: Zero-Trade Rate Investigation
**Date:** 2026-04-14  
**System:** Polymarket Trader Agent — Paper Mode  
**Symptom:** 0 trades placed after 6+ hours of continuous operation  

---

## Executive Summary

The system has processed 185 trigger events and run 13 investigation workflows but placed zero trades. The pipeline has four compounding issues that together guarantee a 0% trade rate. The most critical single blocker is a missing `SportsDomainManager` — sports markets (the most common eligible category) are immediately rejected because no domain manager is registered for them.

---

## Database State at Time of Investigation

| Table | Count | Meaning |
|-------|-------|---------|
| `markets` | 67 | Markets discovered and stored |
| `trigger_events` | 185 | Price/liquidity triggers fired |
| `eligibility_decisions` | 100 | Markets evaluated for eligibility |
| `workflow_runs` | 13 | Full investigation workflows executed |
| `thesis_cards` | 0 | No candidates survived investigation |
| `trades` | 0 | No trades placed |
| `orders` | 0 | No orders submitted |
| `positions` | 0 | No positions held |
| `net_edge_estimates` | 0 | No edge calculations reached |
| `cost_governor_decisions` | 0 | Cost governor never consulted |
| `risk_snapshots` | 0 | Risk governor never consulted |

---

## Issue 1: Missing Sports Domain Manager (CRITICAL — Primary Blocker)

### What happens
When `_investigate_candidate` runs, its first step is assigning a domain manager for the candidate's category ([src/investigation/orchestrator.py:459](../src/investigation/orchestrator.py#L459)):

```python
manager_class = get_domain_manager_class(candidate.category)
if manager_class is None:
    return None, "domain_manager_unknown", 0.0
```

If no manager exists, `_run_domain_manager` returns `(None, "domain_manager_unknown", 0.0)`.  
The caller immediately checks ([src/investigation/orchestrator.py:294](../src/investigation/orchestrator.py#L294)):

```python
if domain_memo is None or not domain_memo.recommended_proceed:
    return None
```

`domain_memo is None` → candidate is rejected. No research runs. No rubric score. No thesis card.

### The registry gap
`DOMAIN_MANAGERS` in [src/investigation/domain_managers.py:293-298](../src/investigation/domain_managers.py#L293):

```python
DOMAIN_MANAGERS = {
    "politics": PoliticsDomainManager,
    "geopolitics": GeopoliticsDomainManager,
    "technology": TechnologyDomainManager,
    "science_health": ScienceHealthDomainManager,
    "macro_policy": MacroPolicyDomainManager,
    # ← "sports" is missing
}
```

`get_domain_manager_class("sports")` returns `None`.

### Impact
18 of 67 stored markets are classified as `sports`. All sports candidates — including MLB, NFL, soccer, IPL, Premier League — are killed at step 1. Given that sports markets are the most active and liquid on Polymarket, this is the primary trade blocker.

### Fix
Implement `SportsDomainManager` and register it:

```python
# In src/investigation/domain_managers.py

class SportsDomainManager(BaseDomainManager):
    role_name = "sports_domain_manager"
    tier = ModelTier.B  # Sonnet 4.6

    system_prompt = """You are a sports market domain expert for prediction markets.
Analyze the market and provide structured assessment.

Output JSON with these fields:
- summary: string
- key_findings: list of strings
- concerns: list of strings  
- recommended_proceed: boolean (true if there is exploitable edge)
- confidence_level: "low" | "medium" | "high"
- optional_agents_justified: list of agent names (empty if none needed)
- domain_specific_data: dict with:
    - match_type: "game" | "season" | "tournament" | "award"
    - teams_or_players: list of strings
    - sport: string
    - competition: string
    - estimated_market_efficiency: float (0-1, lower = more inefficient)
"""

DOMAIN_MANAGERS = {
    "politics": PoliticsDomainManager,
    "geopolitics": GeopoliticsDomainManager,
    "technology": TechnologyDomainManager,
    "science_health": ScienceHealthDomainManager,
    "macro_policy": MacroPolicyDomainManager,
    "sports": SportsDomainManager,  # ← add this
}
```

---

## Issue 2: 56% of Eligibility Decisions Rejected as `unknown_category` (HIGH)

### What happens
100 eligibility decisions were recorded:
- `reject | unknown_category` → **56** (56%)
- `trigger_eligible | eligible` → 24
- `investigate_now | eligible` → 16
- `reject | excluded_category` → 4

More than half of all markets the system sees are rejected before any meaningful evaluation because the classifier can't place them into a category.

### Root cause A: 36 markets stored with numeric IDs as titles

Of 67 stored markets, 36 have titles that are just numeric strings like `1823769`, `1807967`, etc. These arise from `_ensure_market_row` in [src/workflows/orchestrator.py:1709-1712](../src/workflows/orchestrator.py#L1709):

```python
title = (
    (watch_entry.title if watch_entry else None)
    or getattr(card, "core_thesis", None)
    or external_market_id  # ← falls back to the numeric ID
)
```

When a market row is first created during the sweep's eligibility persistence phase, `watch_entry` may not yet exist (it's only added for eligible markets). So the market gets persisted with its numeric `market_id` as its title. With no real title, no tags, and no slug, the category classifier has nothing to match on.

### Root cause B: Gamma API returns non-standard category strings

`_API_CATEGORY_MAP` in [src/eligibility/category_classifier.py:204-216](../src/eligibility/category_classifier.py#L204) only maps 10 category strings:

```python
_API_CATEGORY_MAP = {
    "politics": Category.POLITICS,
    "us-politics": Category.POLITICS,
    "world-politics": Category.GEOPOLITICS,
    "geopolitics": Category.GEOPOLITICS,
    "technology": Category.TECHNOLOGY,
    "science": Category.SCIENCE_HEALTH,
    "health": Category.SCIENCE_HEALTH,
    "science-health": Category.SCIENCE_HEALTH,
    "economics": Category.MACRO_POLICY,
    "macro": Category.MACRO_POLICY,
    "sports": Category.SPORTS,
}
```

Polymarket's Gamma API uses many more category identifiers. Any category string not in this exact list falls through to tag/slug/title matching, then ultimately to `unknown`.

### Root cause C: Classifier is invoked with empty data

When the eligibility engine evaluates a market from the sweep, it constructs `MarketEligibilityInput` at [src/workflows/orchestrator.py:885-896](../src/workflows/orchestrator.py#L885):

```python
elig_input = MarketEligibilityInput(
    market_id=market.market_id or str(uuid.uuid4()),
    title=market.title or "",           # ← MarketInfo.title from Gamma API
    description=market.description or "",
    category_raw=market.category or "", # ← MarketInfo.category from Gamma API
    slug=market.slug or "",
    tags=market.tags or [],
    ...
)
```

If the Gamma API response is missing these fields (or returns them under different key names), the classifier receives empty strings and can match nothing.

### Fix A: Expand `_API_CATEGORY_MAP`

Add all known Polymarket category variants:

```python
_API_CATEGORY_MAP = {
    # Politics
    "politics": Category.POLITICS,
    "us-politics": Category.POLITICS,
    "us politics": Category.POLITICS,
    "american politics": Category.POLITICS,
    "trump": Category.POLITICS,
    # Geopolitics
    "world-politics": Category.GEOPOLITICS,
    "geopolitics": Category.GEOPOLITICS,
    "world politics": Category.GEOPOLITICS,
    "international": Category.GEOPOLITICS,
    "middle east": Category.GEOPOLITICS,
    "ukraine": Category.GEOPOLITICS,
    "russia": Category.GEOPOLITICS,
    "iran": Category.GEOPOLITICS,
    "china": Category.GEOPOLITICS,
    "taiwan": Category.GEOPOLITICS,
    # Technology
    "technology": Category.TECHNOLOGY,
    "tech": Category.TECHNOLOGY,
    "ai": Category.TECHNOLOGY,
    "artificial intelligence": Category.TECHNOLOGY,
    # Science & Health
    "science": Category.SCIENCE_HEALTH,
    "health": Category.SCIENCE_HEALTH,
    "science-health": Category.SCIENCE_HEALTH,
    "science & health": Category.SCIENCE_HEALTH,
    "medicine": Category.SCIENCE_HEALTH,
    "biotech": Category.SCIENCE_HEALTH,
    # Macro / Policy
    "economics": Category.MACRO_POLICY,
    "macro": Category.MACRO_POLICY,
    "finance": Category.MACRO_POLICY,
    "economy": Category.MACRO_POLICY,
    "markets": Category.MACRO_POLICY,
    "federal reserve": Category.MACRO_POLICY,
    "crypto-economy": Category.MACRO_POLICY,
    # Sports
    "sports": Category.SPORTS,
    "sport": Category.SPORTS,
    "baseball": Category.SPORTS,
    "basketball": Category.SPORTS,
    "football": Category.SPORTS,
    "soccer": Category.SPORTS,
    "tennis": Category.SPORTS,
    "golf": Category.SPORTS,
    "hockey": Category.SPORTS,
    "mma": Category.SPORTS,
    "boxing": Category.SPORTS,
    "cricket": Category.SPORTS,
    "f1": Category.SPORTS,
    "formula 1": Category.SPORTS,
    "nba": Category.SPORTS,
    "nfl": Category.SPORTS,
    "mlb": Category.SPORTS,
    "nhl": Category.SPORTS,
    "epl": Category.SPORTS,
    "premier-league": Category.SPORTS,
    "champions-league": Category.SPORTS,
    "ipl": Category.SPORTS,
}
```

### Fix B: Lenient fallback for truly unclassifiable markets

Instead of hard-rejecting unclassified markets, consider a fallback that allows them to proceed with a `"unknown"` quality tier that gets penalized in the rubric score rather than being hard-rejected at the eligibility gate. For now, the minimum fix is expanding the keyword maps.

### Fix C: Ensure market title is available before eligibility

The sweep should evaluate eligibility using the `MarketInfo` data directly (which has `title`, `tags`, `slug`, `category`) before persisting to DB, not after. The eligibility input at line 885 already uses `market.title` (from `MarketInfo`), so the title should be correct there — the problem is that DB persistence fallback uses `external_market_id`. This is a display issue but doesn't affect real-time eligibility.

---

## Issue 3: Misclassified Markets Due to Tag/Category Precedence (MEDIUM)

### What happens
Several markets are stored in the DB with wrong categories:
- "Will Iran strike Kuwait by April 30, 2026?" → stored as `technology`
- "Military action against Iran ends by April 17, 2026?" → stored as `technology`
- "Indian Premier League: Chennai Super Kings vs Kolkata Knight Riders" → stored as `technology`

### Root cause

The classifier's Step 0 (title override) fires **before** Step 1 (API category), but the **DB stored category** is set from the eligibility result's `category_classification.category`, which comes from whichever step matched first. If the Gamma API returns `"technology"` as the category for these markets, Step 1 fires and returns `technology` before Step 0's title override patterns can match.

Wait — Step 0 actually fires first in `classify_category()`. But the title override patterns only cover:
- Geopolitics military patterns: requires both a country AND a military keyword in proximity
- Sports patterns: only IPL/NBA/NFL/etc. major leagues with "playoffs/finals/championship"

The IPL pattern at [category_classifier.py:43](../src/eligibility/category_classifier.py#L43):
```python
re.compile(r'\b(?:nba|nfl|mlb|nhl|ufc|mma)\s+(?:playoffs?|finals?|championship)\b', re.IGNORECASE),
```
This requires `NBA playoffs` format — "Indian Premier League: Chennai Super Kings vs Kolkata Knight Riders" doesn't match because there's no `playoffs|finals|championship` suffix. The IPL-specific pattern at line 42 only matches the abbreviation `ipl` or `indian premier league` alone, not with additional content after the colon.

Actually looking again at line 42:
```python
re.compile(r'\b(?:ipl|indian\s+premier\s+league)\b', re.IGNORECASE),
```
This should match "Indian Premier League: Chennai Super Kings..." — `\b` word boundary + `indian\s+premier\s+league` would match. But `\b` after `league` requires a non-word character, and the colon `:` satisfies that. So this pattern *should* match. The fact it's stored as `technology` suggests this was classified before the title override patterns were added, or the pattern didn't fire for another reason.

The real issue is that misclassified market rows in the DB don't get re-evaluated. The `_ensure_market_row` at line 1741+ only updates certain fields on existing rows:

```python
if market is not None:
    if title and market.title in (None, market.market_id):
        market.title = title
    if category and market.category is None:
        market.category = category  # ← only updates if currently NULL
```

Markets already stored with a wrong category never get corrected.

### Fix
In `_ensure_market_row`, update category if the current value looks wrong (e.g., if it's `"technology"` but the title strongly signals geopolitics or sports). Alternatively, re-run eligibility classification on every sweep and update the DB category when confidence is higher.

---

## Issue 4: Domain Manager `recommended_proceed` Defaults to `False` (HIGH)

### What happens
`DomainMemo` at [src/investigation/types.py:220](../src/investigation/types.py#L220):

```python
class DomainMemo(BaseModel):
    ...
    recommended_proceed: bool = False  # ← default is False (conservative)
```

The domain manager runs an LLM call and tries to parse the result as `DomainMemo(**result.result)`. If:
- The LLM response fails to parse correctly
- The LLM response is missing `recommended_proceed`
- The result dict has unexpected structure

Then `recommended_proceed` stays `False` and the candidate is immediately rejected at [src/investigation/orchestrator.py:294](../src/investigation/orchestrator.py#L294).

This is compounded by the fact that when `result.success` is `False`, the entire domain memo is `None` ([src/investigation/orchestrator.py:484-485](../src/investigation/orchestrator.py#L484)):
```python
if result.success and result.result:
    return DomainMemo(**result.result), manager.role_name, cost
return None, manager.role_name, cost  # ← None → immediate reject
```

Any LLM call failure, timeout, or parse error kills the candidate entirely.

### Fix
When no domain manager exists for a category, or when the domain manager call fails, fall through to the research pack with a default `DomainMemo` that has `recommended_proceed=True`:

```python
if manager_class is None:
    _log.warning("no_domain_manager_for_category", category=candidate.category)
    # Fall through with a permissive default memo instead of hard reject
    default_memo = DomainMemo(
        category=candidate.category,
        market_id=candidate.market_id,
        summary="No domain manager available — proceeding with research pack",
        recommended_proceed=True,  # ← allow investigation to continue
        confidence_level="low",
    )
    return default_memo, "domain_manager_fallback", 0.0
```

And when the LLM call fails:
```python
if result.success and result.result:
    return DomainMemo(**result.result), manager.role_name, cost
# LLM failed — use conservative but not blocking default
fallback_memo = DomainMemo(
    category=candidate.category,
    market_id=candidate.market_id,
    summary="Domain manager LLM call failed",
    recommended_proceed=True,   # allow research to continue
    confidence_level="low",
)
return fallback_memo, manager.role_name, cost
```

---

## Issue 5: Rubric Score Threshold May Be Too High (MEDIUM)

### What happens
The composite score must exceed `MIN_COMPOSITE_FOR_ACCEPTANCE = 0.25` at [src/investigation/rubric.py:28](../src/investigation/rubric.py#L28). The score computation at [src/investigation/types.py:158-188](../src/investigation/types.py#L158):

```python
weights = {
    "evidence_quality": 0.15,
    "evidence_diversity": 0.05,
    "evidence_freshness": 0.05,
    "resolution_clarity": 0.15,
    "market_structure_quality": 0.10,
    "timing_clarity": 0.05,
    "edge_score": 0.20,      # edge * 10, capped at 1.0
    "ambiguity_penalty": -0.10,
    "counter_case_penalty": -0.10,
    "correlation_penalty": -0.05,
}
```

For a candidate to score ≥ 0.25, it needs good evidence quality, decent resolution clarity, some edge, and not too many penalties. In the early paper trading phase with no calibration data and Tier D edge estimates, gross edge is computed as:

```python
market_implied = candidate.mid_price or candidate.price or 0.5
domain_prob = self._estimate_probability_from_domain(domain_memo, market_implied)
gross_edge = abs(domain_prob - market_implied)
```

If `domain_prob` is close to `market_implied` (i.e., the domain manager doesn't have strong conviction), `gross_edge` will be near 0, making `edge_score = 0`. Without edge, even perfect evidence quality only yields:

```
0.15 + 0.05 + 0.05 + 0.15 + 0.10 + 0.05 = 0.55 max (before penalties)
```

But with a typical `ambiguity_level` of 0.3 and `counter_case_strength` of 0.3:
```
- 0.10 * 0.3 = -0.03
- 0.10 * 0.3 = -0.03
total penalty = -0.06
```

Maximum achievable score without edge: ~0.49. With moderate evidence (0.6 avg quality): ~0.29.
This means edge is critical — if gross_edge = 0, even a good market can barely squeak past 0.25.

### Fix
Either:
1. Lower `MIN_COMPOSITE_FOR_ACCEPTANCE` to `0.15` temporarily during paper mode calibration
2. Ensure `_estimate_probability_from_domain` actually derives a probability divergent from 0.5 when the domain manager has findings

---

## Issue 6: `MarketInfo` Has No `price` Attribute — 2 Workflow Crashes (LOW)

### What happens
2 scheduled sweep workflow runs failed with:
```
'MarketInfo' object has no attribute 'price'
```

`MarketInfo` at [src/market_data/types.py:96-112](../src/market_data/types.py#L96) has these fields:
```python
market_id, condition_id, token_ids, title, description, category, tags,
slug, end_date, is_active, volume_24h, liquidity, spread, resolution_source
```
No `price` field.

The sweep code at [src/workflows/orchestrator.py:927-928](../src/workflows/orchestrator.py#L927) safely uses `getattr`:
```python
market_price = getattr(market, 'price', None) or getattr(market, 'mid_price', None)
```

But the error occurs elsewhere. Likely somewhere in the markets filtering or eligibility building phase that was added later and doesn't use `getattr`.

### Fix
Search for any direct `market.price` or `market_info.price` access (without `getattr`) and replace with `getattr(market, 'price', None)`. A targeted grep:

```bash
grep -n "\.price" src/workflows/orchestrator.py
grep -n "market\.price\|market_info\.price" src/
```

Lines 927-938 already use `getattr` safely. The bug is in a different code path that hits `MarketInfo` objects — likely in the `markets_filtered` loop before those safe lines.

---

## Issue 7: Sports Markets Fail the Sports Quality Gate (MEDIUM)

### What happens
Even for sports markets that get correctly classified, they must pass the `evaluate_sports_gate()` check at [src/eligibility/engine.py:122-146](../src/eligibility/engine.py#L122). The sports gate evaluates:
- Liquidity thresholds (higher bar for sports)
- Resolution source reliability
- End date proximity (too close or too far)
- Spread constraints

Many MLB game-day markets ("Miami Marlins vs. Atlanta Braves") are short-term binary outcomes with limited liquidity, and may fail the sports gate even if they pass initial classification.

Looking at the DB: we have 18 sports markets and 16 `investigate_now` eligibility decisions — but 0 of those produce thesis cards, because sports candidates die at the domain manager step before reaching the gate's protection anyway.

---

## Pipeline Failure Flow (Visual)

```
185 trigger events
    ↓
100 eligibility evaluations
    ├── 56 → REJECT (unknown_category)  ← Issue 1 & 2
    ├── 4  → REJECT (excluded_category)
    ├── 24 → trigger_eligible (on watchlist, not investigated)
    └── 16 → investigate_now
                ↓
           13 workflows run
               ↓
           Sports candidates → domain manager = None → REJECT  ← Issue 1
           Non-sports candidates → domain manager runs (LLM)
               ↓
           domain_memo.recommended_proceed = False → REJECT  ← Issue 4
           OR rubric_score < 0.25 → REJECT  ← Issue 5
               ↓
           0 thesis cards
               ↓
           0 trades
```

---

## Priority Fixes (Ordered by Impact)

### Fix 1: Add `SportsDomainManager` to registry
**File:** `src/investigation/domain_managers.py`  
**Impact:** Unblocks all sports candidates (largest eligible category)  
**Effort:** Medium (implement new class + system prompt + register)

### Fix 2: Expand `_API_CATEGORY_MAP` 
**File:** `src/eligibility/category_classifier.py`  
**Impact:** Reduces `unknown_category` rejection from ~56% to ~15%  
**Effort:** Low (add string mappings)

### Fix 3: Make domain manager failure non-fatal
**File:** `src/investigation/orchestrator.py` — `_run_domain_manager`  
**Impact:** Ensures LLM failures don't silently kill candidates  
**Effort:** Low (add fallback DomainMemo)

### Fix 4: Fix `MarketInfo.price` AttributeError
**File:** Unknown (somewhere in sweep path) — find with grep  
**Impact:** Stops 2 workflow crashes per sweep  
**Effort:** Low (replace `.price` with `getattr(market, 'price', None)`)

### Fix 5: Lower rubric threshold in paper mode
**File:** `src/investigation/rubric.py`  
**Impact:** More candidates survive to thesis building  
**Effort:** Very low (change constant `0.25` → `0.15`)

### Fix 6: Log rubric score breakdown for every rejection
**File:** `src/investigation/orchestrator.py` — around line 354  
**Impact:** Enables fast diagnosis of which dimensions are failing  
**Effort:** Very low (add structured log fields)

---

## Additional Observations

### Trigger event escalation_status is always empty
All 185 trigger events have `escalation_status = NULL`. This means no trigger has ever been escalated to an investigation workflow via the trigger path. The 13 workflow runs are either `trigger_based` (from batch processing) or `scheduled_sweep`. The escalation logic in `_process_trigger_batch` may not be connecting trigger events to the `escalation_status` field correctly.

### The scanner is active but not generating INVESTIGATE_NOW candidates
Only 16 out of 100 eligibility outcomes are `investigate_now`, and only 24 are `trigger_eligible`. The remaining 60% are rejected at the eligibility gate. This means the scanner's watch list is smaller than it should be, reducing the candidate pool for trigger-based investigation.

### No calibration data exists
`calibration_records` table is empty. The system enters every investigation with `calibration_source_class = "no_data"`, which gives no edge advantage to the rubric score. This is expected in early paper trading, but it means the rubric's `edge_score` contribution is near zero, making the 0.25 threshold harder to clear.

### Paper balance unchanged at $500
`paper_balance_usd = 500.0` exactly, `start_of_day_equity_usd = 500.0`. Confirms no trades have executed.

---

## Files Referenced

| File | Relevant Lines | Issue |
|------|---------------|-------|
| `src/investigation/domain_managers.py` | 293-303 | Missing sports manager |
| `src/investigation/orchestrator.py` | 294, 459-465 | Domain manager None path |
| `src/investigation/orchestrator.py` | 354-361 | Rubric rejection |
| `src/investigation/orchestrator.py` | 927-938 | Safe MarketInfo.price access |
| `src/investigation/types.py` | 158-188 | Composite score computation |
| `src/investigation/types.py` | 220 | `recommended_proceed` default |
| `src/investigation/types.py` | 315-317 | `is_viable` threshold (0.5%) |
| `src/investigation/rubric.py` | 27-29 | Score thresholds |
| `src/eligibility/category_classifier.py` | 204-216 | `_API_CATEGORY_MAP` (too few entries) |
| `src/eligibility/category_classifier.py` | 385-393 | Unknown category fallback |
| `src/eligibility/engine.py` | 91-101 | Unknown category rejection |
| `src/eligibility/engine.py` | 122-146 | Sports quality gate |
| `src/market_data/types.py` | 96-112 | `MarketInfo` (no `price` field) |
| `src/workflows/orchestrator.py` | 885-946 | Sweep eligibility + candidate building |
| `src/workflows/orchestrator.py` | 1709-1712 | `_ensure_market_row` title fallback |
