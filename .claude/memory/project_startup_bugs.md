---
name: Startup bugs fixed and remaining issues
description: Bugs found and fixed during first real startup of the trading system (April 2026), plus remaining known issues
type: project
---

All fixed during first startup session (2026-04-14):

1. **Run command** — `python -m polymarket_trader` doesn't work. Correct: `PYTHONPATH=src .venv/bin/python src/__main__.py`
2. **Gamma API field names** — camelCase in API, code used snake_case. Fixed: `liquidityNum`, `volume24hr`, `endDateIso`, `conditionId`, `clobTokenIds`, `resolutionSource`
3. **`MarketInfo` missing fields** — added `spread` and `resolution_source`
4. **`market.question`** → `market.title` (AttributeError in sweep)
5. **Naive datetime** — `endDateIso` bare date string parsed without timezone; fixed to force UTC
6. **`BudgetState` field names** — `daily_spend_usd` → `daily_spent_usd`, `lifetime_spend_usd` → `lifetime_spent_usd`
7. **`SystemHealthPayload`** — emitted with wrong keys; fixed to `health_event`, `service`, `summary`
8. **Sweep sampled wrong markets** — first 50 API results are short-horizon sports; added 24h–90d horizon pre-filter + liquidity sort
9. **`TRIGGER_ELIGIBLE` markets** never reached watch list — fixed to add both `INVESTIGATE_NOW` and `TRIGGER_ELIGIBLE` outcomes
10. **`NoTradeMonitor.record()`** → `record_run(had_no_trade=...)` (wrong method name)

**Remaining known bugs (non-blocking):**
- `slow_loop` error: `'CalibrationConfig' object has no attribute 'compute_all_segment_states'`
- `SystemHealthPayload` notification validation (was fixed but the `system_started` event still had the old format at startup once)

**Why:** `resolution_source` was empty for most markets; defaulted to `"polymarket.com"` since all Polymarket markets resolve via Polymarket's oracle regardless.

**How to apply:** When starting the system fresh, expect these to be fixed. If startup errors appear, check orchestrator field name mismatches first.
