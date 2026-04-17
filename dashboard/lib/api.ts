/**
 * Dashboard API client — fetches data from FastAPI backend.
 * Auto-detects live API; falls back to mock data when unavailable.
 */

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

let _apiAvailable: boolean | null = null;

async function checkApiAvailability(): Promise<boolean> {
  if (_apiAvailable !== null) return _apiAvailable;
  try {
    const res = await fetch(`${API_BASE}/api/health`, {
      signal: AbortSignal.timeout(2000),
    });
    _apiAvailable = res.ok;
  } catch {
    _apiAvailable = false;
  }
  // Re-check every 30s
  setTimeout(() => { _apiAvailable = null; }, 30000);
  return _apiAvailable;
}

async function apiFetch<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    cache: "no-store",
    headers: { "Content-Type": "application/json" },
  });
  if (!res.ok) throw new Error(`API error: ${res.status} ${res.statusText}`);
  return res.json();
}

async function apiPost<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    cache: "no-store",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new Error(`API error: ${res.status} ${res.statusText}`);
  return res.json();
}

// ──────────────────────────────────────────────
// Types
// ──────────────────────────────────────────────

export interface EquitySnapshot {
  timestamp: string;
  equity_usd: number;
  pnl_usd: number;
}

export interface PortfolioOverview {
  total_equity_usd: number;
  paper_cash_balance_usd: number;
  paper_equity_usd: number;
  paper_reserved_capital_usd: number;
  total_open_exposure_usd: number;
  daily_pnl_usd: number;
  unrealized_pnl_usd: number;
  realized_pnl_usd: number;
  open_positions_count: number;
  drawdown_level: string;
  drawdown_pct: number;
  operator_mode: string;
  system_status: string;
  equity_history: EquitySnapshot[];
}

export interface PositionSummary {
  id: string;
  market_id: string;
  market_title: string;
  side: string;
  entry_price: number;
  current_price: number | null;
  size: number;
  remaining_size: number;
  unrealized_pnl: number | null;
  realized_pnl: number | null;
  status: string;
  review_tier: string;
  category: string | null;
  entered_at: string | null;
}

export interface DrawdownLadder {
  current_drawdown_pct: number;
  soft_warning_pct: number;
  risk_reduction_pct: number;
  entries_disabled_pct: number;
  hard_kill_switch_pct: number;
  current_level: string;
}

export interface ExposureByCategory {
  category: string;
  exposure_usd: number;
  cap_usd: number;
  positions_count: number;
  pct_of_cap: number;
}

export interface RiskBoard {
  drawdown_ladder: DrawdownLadder;
  total_exposure_usd: number;
  max_exposure_usd: number;
  exposure_by_category: ExposureByCategory[];
  correlation_groups_count: number;
  daily_deployment_used_pct: number;
  max_daily_deployment_pct: number;
}

export interface WorkflowRunSummary {
  id: string;
  workflow_type: string;
  status: string;
  started_at: string | null;
  completed_at: string | null;
  cost_usd: number;
  candidates_reviewed: number;
  candidates_accepted: number;
  market_title: string | null;
}

export interface TriggerEventItem {
  id: string;
  trigger_class: string;
  trigger_level: string;
  market_id: string | null;
  market_title: string | null;
  category: string | null;
  reason: string | null;
  price: number | null;
  spread: number | null;
  data_source: string | null;
  timestamp: string;
}

export interface CostMetrics {
  daily_spend_usd: number;
  daily_budget_usd: number;
  daily_budget_remaining_usd: number;
  lifetime_spend_usd: number;
  lifetime_budget_usd: number;
  lifetime_budget_pct: number;
  selectivity_ratio: number;
  selectivity_target: number;
  opus_spend_today_usd: number;
  opus_budget_usd: number;
}

export interface CalibrationSegmentStatus {
  segment_name: string;
  resolved_count: number;
  required_count: number;
  system_brier: number | null;
  market_brier: number | null;
  advantage: number | null;
  projected_threshold_date: string | null;
  status: string;
}

export interface CalibrationOverview {
  total_shadow_forecasts: number;
  total_resolved: number;
  overall_system_brier: number | null;
  overall_market_brier: number | null;
  overall_advantage: number | null;
  patience_budget_months: number;
  patience_budget_remaining_days: number | null;
  segments: CalibrationSegmentStatus[];
}

export interface ScannerHealth {
  api_status: string;
  degraded_level: number;
  cache_entries_count: number;
  cache_hit_rate: number;
  last_successful_poll: string | null;
  consecutive_failures: number;
  uptime_pct: number;
}

export interface CategoryPerformanceEntry {
  category: string;
  total_trades: number;
  win_rate: number;
  gross_pnl_usd: number;
  net_pnl_usd: number;
  inference_cost_usd: number;
  avg_edge: number;
  avg_holding_hours: number;
  brier_score: number | null;
  system_vs_market_brier: number | null;
  no_trade_rate: number;
}

export interface BiasPatternItem {
  pattern_type: string;
  severity: string;
  description: string;
  weeks_active: number;
  is_persistent: boolean;
  first_detected: string | null;
}

export interface BiasAuditOverview {
  last_audit_at: string | null;
  active_patterns: BiasPatternItem[];
  persistent_pattern_count: number;
  resolved_pattern_count: number;
}

export interface ViabilityCheckpointItem {
  checkpoint_week: number;
  assessed_at: string;
  signal: string;
  system_brier: number | null;
  market_brier: number | null;
  resolved_count: number;
  recommendation: string | null;
}

export interface ViabilityOverview {
  current_signal: string;
  checkpoints: ViabilityCheckpointItem[];
  lifetime_budget_pct: number;
  patience_budget_remaining_days: number | null;
}

export interface AbsenceStatus {
  is_absent: boolean;
  absence_level: number;
  hours_since_activity: number;
  last_activity: string | null;
  restrictions_active: string[];
  autonomous_actions_count: number;
}

export interface SystemHealthItem {
  component: string;
  status: string;
  last_check: string | null;
  details: string | null;
}

export interface SystemHealthOverview {
  overall_status: string;
  components: SystemHealthItem[];
  active_alerts_count: number;
}

export interface AgentStatus {
  name: string;
  role: string;
  tier: string;
  is_active: boolean;
  last_invoked: string | null;
  total_invocations: number;
  total_cost_usd: number;
}

export interface SystemControlResponse {
  success: boolean;
  message: string;
  current_mode: string;
  timestamp: string;
}

export interface PaperBalanceResponse {
  balance_usd: number;
  start_of_day_equity_usd: number;
  operator_mode: string;
  transactions: PaperTransaction[];
}

export interface PaperTransaction {
  type: "deposit" | "withdraw";
  amount_usd: number;
  reason: string;
  timestamp: string;
  balance_after: number;
}

export interface ActivityLogEntry {
  id: string;
  timestamp: string;
  event_type: string;
  component: string;
  message: string;
  detail: string | null;
  severity: string;
}

// ──────────────────────────────────────────────
// Mock Data (fallback when backend unavailable)
// ──────────────────────────────────────────────

function generateEquityHistory(): EquitySnapshot[] {
  const points: EquitySnapshot[] = [];
  let equity = 480;
  const now = Date.now();
  for (let i = 30; i >= 0; i--) {
    equity += (Math.random() - 0.45) * 8;
    points.push({
      timestamp: new Date(now - i * 86400000).toISOString(),
      equity_usd: Math.round(equity * 100) / 100,
      pnl_usd: Math.round((equity - 500) * 100) / 100,
    });
  }
  return points;
}

function getPersistedMode(): string {
  if (typeof window !== "undefined") {
    return localStorage.getItem("polymarket_operator_mode") || "shadow";
  }
  return "shadow";
}

function getPersistedSystemStatus(): string {
  if (typeof window !== "undefined") {
    return localStorage.getItem("polymarket_system_status") || "stopped";
  }
  return "stopped";
}

const mockPortfolio: PortfolioOverview = {
  total_equity_usd: 500.0,
  paper_cash_balance_usd: 500.0,
  paper_equity_usd: 500.0,
  paper_reserved_capital_usd: 0.0,
  total_open_exposure_usd: 0,
  daily_pnl_usd: 0,
  unrealized_pnl_usd: 0,
  realized_pnl_usd: 0,
  open_positions_count: 0,
  drawdown_level: "normal",
  drawdown_pct: 0,
  operator_mode: getPersistedMode(),
  system_status: getPersistedSystemStatus(),
  equity_history: generateEquityHistory(),
};

const mockRisk: RiskBoard = {
  drawdown_ladder: {
    current_drawdown_pct: 0, soft_warning_pct: 0.01, risk_reduction_pct: 0.02,
    entries_disabled_pct: 0.035, hard_kill_switch_pct: 0.04, current_level: "normal",
  },
  total_exposure_usd: 0, max_exposure_usd: 250,
  exposure_by_category: [],
  correlation_groups_count: 0, daily_deployment_used_pct: 0, max_daily_deployment_pct: 0.10,
};

const mockCost: CostMetrics = {
  daily_spend_usd: 0, daily_budget_usd: 5, daily_budget_remaining_usd: 5,
  lifetime_spend_usd: 0, lifetime_budget_usd: 500, lifetime_budget_pct: 0,
  selectivity_ratio: 0, selectivity_target: 0.20,
  opus_spend_today_usd: 0, opus_budget_usd: 1.0,
};

const mockScanner: ScannerHealth = {
  api_status: "healthy", degraded_level: 0, cache_entries_count: 0,
  cache_hit_rate: 0, last_successful_poll: null,
  consecutive_failures: 0, uptime_pct: 100,
};

const mockCalibration: CalibrationOverview = {
  total_shadow_forecasts: 0, total_resolved: 0,
  overall_system_brier: null, overall_market_brier: null, overall_advantage: null,
  patience_budget_months: 9, patience_budget_remaining_days: 270,
  segments: [],
};

const mockSystemHealth: SystemHealthOverview = {
  overall_status: "healthy",
  components: [
    { component: "Database", status: "healthy", last_check: new Date().toISOString(), details: null },
    { component: "Scanner", status: "healthy", last_check: null, details: null },
    { component: "Risk Governor", status: "healthy", last_check: new Date().toISOString(), details: null },
    { component: "Cost Governor", status: "healthy", last_check: new Date().toISOString(), details: null },
  ],
  active_alerts_count: 0,
};

const mockBias: BiasAuditOverview = {
  last_audit_at: null, active_patterns: [],
  persistent_pattern_count: 0, resolved_pattern_count: 0,
};

const mockViability: ViabilityOverview = {
  current_signal: "unassessed", checkpoints: [],
  lifetime_budget_pct: 0, patience_budget_remaining_days: 270,
};

const mockAbsence: AbsenceStatus = {
  is_absent: false, absence_level: 0, hours_since_activity: 0,
  last_activity: new Date().toISOString(),
  restrictions_active: [], autonomous_actions_count: 0,
};

const mockAgents: AgentStatus[] = [
  { name: "Investigator Orchestrator", role: "investigator_orchestration", tier: "A", is_active: false, last_invoked: null, total_invocations: 0, total_cost_usd: 0 },
  { name: "Domain Manager", role: "domain_manager", tier: "B", is_active: false, last_invoked: null, total_invocations: 0, total_cost_usd: 0 },
  { name: "Evidence Research", role: "evidence_research", tier: "C", is_active: false, last_invoked: null, total_invocations: 0, total_cost_usd: 0 },
  { name: "Trigger Scanner", role: "trigger_scanner", tier: "D", is_active: false, last_invoked: null, total_invocations: 0, total_cost_usd: 0 },
  { name: "Risk Governor", role: "risk_governor", tier: "D", is_active: false, last_invoked: null, total_invocations: 0, total_cost_usd: 0 },
  { name: "Cost Governor", role: "cost_governor", tier: "D", is_active: false, last_invoked: null, total_invocations: 0, total_cost_usd: 0 },
];

// ──────────────────────────────────────────────
// Fetchers — try live API, fall back to mock
// ──────────────────────────────────────────────

async function liveOrMock<T>(path: string, mock: T): Promise<T> {
  const live = await checkApiAvailability();
  if (live) {
    try {
      return await apiFetch<T>(path);
    } catch {
      return mock;
    }
  }
  return mock;
}

export async function fetchPortfolio(): Promise<PortfolioOverview> {
  return liveOrMock("/api/portfolio", mockPortfolio);
}

export async function fetchPositions(): Promise<PositionSummary[]> {
  return liveOrMock("/api/positions", []);
}

export async function fetchRisk(): Promise<RiskBoard> {
  return liveOrMock("/api/risk", mockRisk);
}

export async function fetchCost(): Promise<CostMetrics> {
  return liveOrMock("/api/cost", mockCost);
}

export async function fetchScanner(): Promise<ScannerHealth> {
  return liveOrMock("/api/scanner", mockScanner);
}

export async function fetchCalibration(): Promise<CalibrationOverview> {
  return liveOrMock("/api/calibration", mockCalibration);
}

export async function fetchCategories(): Promise<CategoryPerformanceEntry[]> {
  return liveOrMock("/api/categories", []);
}

export async function fetchWorkflows(): Promise<WorkflowRunSummary[]> {
  return liveOrMock("/api/workflows?limit=50", []);
}

export async function fetchTriggers(): Promise<TriggerEventItem[]> {
  return liveOrMock("/api/triggers?limit=100", []);
}

export async function fetchAgents(): Promise<AgentStatus[]> {
  return liveOrMock("/api/agents", mockAgents);
}

export async function fetchSystemHealth(): Promise<SystemHealthOverview> {
  return liveOrMock("/api/system-health", mockSystemHealth);
}

export async function fetchBias(): Promise<BiasAuditOverview> {
  return liveOrMock("/api/bias", mockBias);
}

export async function fetchViability(): Promise<ViabilityOverview> {
  return liveOrMock("/api/viability", mockViability);
}

export async function fetchAbsence(): Promise<AbsenceStatus> {
  return liveOrMock("/api/absence", mockAbsence);
}

// ──────────────────────────────────────────────
// Paper Balance
// ──────────────────────────────────────────────

export async function fetchPaperBalance(): Promise<PaperBalanceResponse> {
  const mock: PaperBalanceResponse = {
    balance_usd: 500, start_of_day_equity_usd: 500,
    operator_mode: getPersistedMode(), transactions: [],
  };
  return liveOrMock("/api/paper-balance", mock);
}

export async function depositPaperFunds(amount: number, reason?: string): Promise<PaperBalanceResponse> {
  return apiPost("/api/paper-balance/deposit", { amount_usd: amount, reason });
}

export async function withdrawPaperFunds(amount: number, reason?: string): Promise<PaperBalanceResponse> {
  return apiPost("/api/paper-balance/withdraw", { amount_usd: amount, reason });
}

// ──────────────────────────────────────────────
// Activity Log
// ──────────────────────────────────────────────

export async function fetchActivityLog(limit = 40): Promise<ActivityLogEntry[]> {
  return liveOrMock(`/api/activity?limit=${limit}`, []);
}

// ──────────────────────────────────────────────
// Controls
// ──────────────────────────────────────────────

export async function controlAgents(action: "start" | "stop"): Promise<SystemControlResponse> {
  const live = await checkApiAvailability();
  if (live) {
    return apiPost(`/api/control/agents/${action}`);
  }
  // Update mock state so subsequent fetches reflect the change
  const newStatus = action === "start" ? "running" : "stopped";
  mockPortfolio.system_status = newStatus;
  if (typeof window !== "undefined") {
    localStorage.setItem("polymarket_system_status", newStatus);
  }
  return {
    success: true, message: `Agents ${action}ed (mock)`,
    current_mode: mockPortfolio.operator_mode, timestamp: new Date().toISOString(),
  };
}

export async function changeMode(mode: string, reason?: string): Promise<SystemControlResponse> {
  const live = await checkApiAvailability();
  if (live) {
    const result = await apiPost<SystemControlResponse>("/api/control/mode", { mode, reason });
    // Also persist locally for instant availability on next load
    if (result.success && typeof window !== "undefined") {
      localStorage.setItem("polymarket_operator_mode", mode);
    }
    return result;
  }
  mockPortfolio.operator_mode = mode;
  if (typeof window !== "undefined") {
    localStorage.setItem("polymarket_operator_mode", mode);
  }
  return {
    success: true, message: `Mode changed to ${mode} (mock)`,
    current_mode: mode, timestamp: new Date().toISOString(),
  };
}

export function isApiAvailable(): boolean | null {
  return _apiAvailable;
}
