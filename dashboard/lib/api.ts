/**
 * Dashboard API client — fetches data from FastAPI backend.
 * Falls back to mock data when API is unavailable.
 */

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

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

// ──────────────────────────────────────────────
// Mock Data
// ──────────────────────────────────────────────

function generateEquityHistory(): EquitySnapshot[] {
  const points: EquitySnapshot[] = [];
  let equity = 9500;
  const now = Date.now();
  for (let i = 30; i >= 0; i--) {
    equity += (Math.random() - 0.45) * 120;
    points.push({
      timestamp: new Date(now - i * 86400000).toISOString(),
      equity_usd: Math.round(equity * 100) / 100,
      pnl_usd: Math.round((equity - 9500) * 100) / 100,
    });
  }
  return points;
}

const mockPortfolio: PortfolioOverview = {
  total_equity_usd: 10247.83,
  total_open_exposure_usd: 3420.50,
  daily_pnl_usd: 127.45,
  unrealized_pnl_usd: 89.20,
  realized_pnl_usd: 38.25,
  open_positions_count: 5,
  drawdown_level: "normal",
  drawdown_pct: 1.2,
  operator_mode: "shadow",
  system_status: "running",
  equity_history: generateEquityHistory(),
};

const mockPositions: PositionSummary[] = [
  {
    id: "pos-001", market_id: "mkt-001", market_title: "US 2028 Presidential Election – Republican Nominee",
    side: "yes", entry_price: 0.42, current_price: 0.48, size: 850, remaining_size: 850,
    unrealized_pnl: 51.0, realized_pnl: null, status: "open", review_tier: "stable",
    category: "politics", entered_at: "2026-04-01T10:00:00Z",
  },
  {
    id: "pos-002", market_id: "mkt-002", market_title: "EU AI Act Implementation Full Compliance by 2027",
    side: "no", entry_price: 0.65, current_price: 0.58, size: 720, remaining_size: 720,
    unrealized_pnl: 50.4, realized_pnl: null, status: "open", review_tier: "new",
    category: "technology", entered_at: "2026-04-11T14:30:00Z",
  },
  {
    id: "pos-003", market_id: "mkt-003", market_title: "Fed Rate Cut Before July 2026",
    side: "yes", entry_price: 0.38, current_price: 0.35, size: 600, remaining_size: 600,
    unrealized_pnl: -18.0, realized_pnl: null, status: "open", review_tier: "stable",
    category: "macro_policy", entered_at: "2026-03-28T09:15:00Z",
  },
  {
    id: "pos-004", market_id: "mkt-004", market_title: "WHO Pandemic Treaty Signed by Q3 2026",
    side: "no", entry_price: 0.72, current_price: 0.74, size: 500, remaining_size: 500,
    unrealized_pnl: -10.0, realized_pnl: null, status: "open", review_tier: "low_value",
    category: "geopolitics", entered_at: "2026-03-15T11:00:00Z",
  },
  {
    id: "pos-005", market_id: "mkt-005", market_title: "Champions League Winner – Real Madrid",
    side: "yes", entry_price: 0.22, current_price: 0.28, size: 350, remaining_size: 350,
    unrealized_pnl: 21.0, realized_pnl: null, status: "open", review_tier: "stable",
    category: "sports", entered_at: "2026-04-05T16:00:00Z",
  },
];

const mockRisk: RiskBoard = {
  drawdown_ladder: {
    current_drawdown_pct: 1.2, soft_warning_pct: 3, risk_reduction_pct: 5,
    entries_disabled_pct: 6.5, hard_kill_switch_pct: 8, current_level: "normal",
  },
  total_exposure_usd: 3420.50, max_exposure_usd: 10000,
  exposure_by_category: [
    { category: "politics", exposure_usd: 850, cap_usd: 5000, positions_count: 1, pct_of_cap: 0.17 },
    { category: "technology", exposure_usd: 720, cap_usd: 5000, positions_count: 1, pct_of_cap: 0.144 },
    { category: "macro_policy", exposure_usd: 600, cap_usd: 5000, positions_count: 1, pct_of_cap: 0.12 },
    { category: "geopolitics", exposure_usd: 500, cap_usd: 5000, positions_count: 1, pct_of_cap: 0.10 },
    { category: "sports", exposure_usd: 350, cap_usd: 2000, positions_count: 1, pct_of_cap: 0.175 },
  ],
  correlation_groups_count: 2, daily_deployment_used_pct: 3.4, max_daily_deployment_pct: 10,
};

const mockCost: CostMetrics = {
  daily_spend_usd: 4.82, daily_budget_usd: 25, daily_budget_remaining_usd: 20.18,
  lifetime_spend_usd: 312.45, lifetime_budget_usd: 5000, lifetime_budget_pct: 6.25,
  selectivity_ratio: 0.14, selectivity_target: 0.20,
  opus_spend_today_usd: 0.85, opus_budget_usd: 5.0,
};

const mockScanner: ScannerHealth = {
  api_status: "healthy", degraded_level: 0, cache_entries_count: 247,
  cache_hit_rate: 94.2, last_successful_poll: new Date().toISOString(),
  consecutive_failures: 0, uptime_pct: 99.7,
};

const mockCalibration: CalibrationOverview = {
  total_shadow_forecasts: 87, total_resolved: 34,
  overall_system_brier: 0.182, overall_market_brier: 0.198, overall_advantage: 0.016,
  patience_budget_months: 9, patience_budget_remaining_days: 218,
  segments: [
    { segment_name: "Politics", resolved_count: 12, required_count: 30, system_brier: 0.165, market_brier: 0.188, advantage: 0.023, projected_threshold_date: "2026-08-15T00:00:00Z", status: "insufficient" },
    { segment_name: "Technology", resolved_count: 8, required_count: 30, system_brier: 0.195, market_brier: 0.201, advantage: 0.006, projected_threshold_date: "2026-10-01T00:00:00Z", status: "insufficient" },
    { segment_name: "Macro/Policy", resolved_count: 6, required_count: 30, system_brier: 0.210, market_brier: 0.215, advantage: 0.005, projected_threshold_date: "2026-11-20T00:00:00Z", status: "insufficient" },
    { segment_name: "Geopolitics", resolved_count: 5, required_count: 30, system_brier: 0.225, market_brier: 0.220, advantage: -0.005, projected_threshold_date: "2027-01-10T00:00:00Z", status: "insufficient" },
    { segment_name: "Sports", resolved_count: 3, required_count: 40, system_brier: 0.240, market_brier: 0.235, advantage: -0.005, projected_threshold_date: "2027-03-01T00:00:00Z", status: "insufficient" },
  ],
};

const mockCategories: CategoryPerformanceEntry[] = [
  { category: "politics", total_trades: 12, win_rate: 0.67, gross_pnl_usd: 245.80, net_pnl_usd: 198.30, inference_cost_usd: 47.50, avg_edge: 0.08, avg_holding_hours: 168, brier_score: 0.165, system_vs_market_brier: 0.023, no_trade_rate: 0.72 },
  { category: "technology", total_trades: 8, win_rate: 0.625, gross_pnl_usd: 152.40, net_pnl_usd: 112.90, inference_cost_usd: 39.50, avg_edge: 0.06, avg_holding_hours: 120, brier_score: 0.195, system_vs_market_brier: 0.006, no_trade_rate: 0.78 },
  { category: "macro_policy", total_trades: 6, win_rate: 0.50, gross_pnl_usd: 42.10, net_pnl_usd: 8.60, inference_cost_usd: 33.50, avg_edge: 0.04, avg_holding_hours: 240, brier_score: 0.210, system_vs_market_brier: 0.005, no_trade_rate: 0.82 },
  { category: "geopolitics", total_trades: 5, win_rate: 0.40, gross_pnl_usd: -28.50, net_pnl_usd: -58.00, inference_cost_usd: 29.50, avg_edge: 0.03, avg_holding_hours: 312, brier_score: 0.225, system_vs_market_brier: -0.005, no_trade_rate: 0.85 },
  { category: "sports", total_trades: 3, win_rate: 0.33, gross_pnl_usd: -15.20, net_pnl_usd: -32.70, inference_cost_usd: 17.50, avg_edge: 0.05, avg_holding_hours: 72, brier_score: 0.240, system_vs_market_brier: -0.005, no_trade_rate: 0.90 },
];

const mockWorkflows: WorkflowRunSummary[] = [
  { id: "wf-001", workflow_type: "investigation", status: "completed", started_at: "2026-04-13T14:00:00Z", completed_at: "2026-04-13T14:05:32Z", cost_usd: 1.24, candidates_reviewed: 12, candidates_accepted: 1, market_title: "EU AI Act" },
  { id: "wf-002", workflow_type: "position_review", status: "completed", started_at: "2026-04-13T12:00:00Z", completed_at: "2026-04-13T12:00:45Z", cost_usd: 0.0, candidates_reviewed: 5, candidates_accepted: 5, market_title: null },
  { id: "wf-003", workflow_type: "investigation", status: "completed", started_at: "2026-04-13T08:00:00Z", completed_at: "2026-04-13T08:04:18Z", cost_usd: 0.92, candidates_reviewed: 15, candidates_accepted: 0, market_title: null },
  { id: "wf-004", workflow_type: "performance_review", status: "completed", started_at: "2026-04-12T22:00:00Z", completed_at: "2026-04-12T22:12:05Z", cost_usd: 3.15, candidates_reviewed: 0, candidates_accepted: 0, market_title: null },
  { id: "wf-005", workflow_type: "trigger_scan", status: "running", started_at: "2026-04-13T19:28:00Z", completed_at: null, cost_usd: 0.0, candidates_reviewed: 0, candidates_accepted: 0, market_title: null },
];

const mockTriggers: TriggerEventItem[] = [
  { id: "trg-001", trigger_class: "repricing", trigger_level: "B", market_id: "mkt-002", market_title: "EU AI Act", reason: "Price moved 7% in 2h", price: 0.58, spread: 0.03, data_source: "live", timestamp: "2026-04-13T18:45:00Z" },
  { id: "trg-002", trigger_class: "discovery", trigger_level: "C", market_id: "mkt-006", market_title: "UK General Election Date Before 2027", reason: "New eligible market detected", price: 0.35, spread: 0.04, data_source: "live", timestamp: "2026-04-13T16:20:00Z" },
  { id: "trg-003", trigger_class: "profit_protection", trigger_level: "B", market_id: "mkt-001", market_title: "US 2028 Presidential", reason: "Position up 14% from entry", price: 0.48, spread: 0.02, data_source: "live", timestamp: "2026-04-13T14:10:00Z" },
  { id: "trg-004", trigger_class: "catalyst_window", trigger_level: "A", market_id: "mkt-003", market_title: "Fed Rate Cut", reason: "FOMC meeting in 72h", price: 0.35, spread: 0.05, data_source: "live", timestamp: "2026-04-13T10:00:00Z" },
];

const mockAgents: AgentStatus[] = [
  { name: "Investigator Orchestrator", role: "investigator_orchestration", tier: "A", is_active: true, last_invoked: "2026-04-13T14:00:00Z", total_invocations: 23, total_cost_usd: 18.40 },
  { name: "Performance Analyzer", role: "performance_analyzer", tier: "A", is_active: true, last_invoked: "2026-04-12T22:00:00Z", total_invocations: 4, total_cost_usd: 12.60 },
  { name: "Domain Mgr (Politics)", role: "domain_manager_politics", tier: "B", is_active: true, last_invoked: "2026-04-13T14:02:00Z", total_invocations: 18, total_cost_usd: 8.20 },
  { name: "Domain Mgr (Tech)", role: "domain_manager_technology", tier: "B", is_active: true, last_invoked: "2026-04-13T14:02:00Z", total_invocations: 12, total_cost_usd: 5.40 },
  { name: "Counter-Case Agent", role: "counter_case", tier: "B", is_active: true, last_invoked: "2026-04-13T14:03:00Z", total_invocations: 15, total_cost_usd: 6.80 },
  { name: "Evidence Research", role: "evidence_research", tier: "C", is_active: true, last_invoked: "2026-04-13T14:01:00Z", total_invocations: 42, total_cost_usd: 4.20 },
  { name: "Alert Composer", role: "alert_composer", tier: "C", is_active: true, last_invoked: "2026-04-13T18:45:00Z", total_invocations: 67, total_cost_usd: 2.10 },
  { name: "Trigger Scanner", role: "trigger_scanner", tier: "D", is_active: true, last_invoked: "2026-04-13T19:30:00Z", total_invocations: 1440, total_cost_usd: 0.0 },
  { name: "Risk Governor", role: "risk_governor", tier: "D", is_active: true, last_invoked: "2026-04-13T14:04:00Z", total_invocations: 312, total_cost_usd: 0.0 },
  { name: "Cost Governor", role: "cost_governor", tier: "D", is_active: true, last_invoked: "2026-04-13T14:00:00Z", total_invocations: 245, total_cost_usd: 0.0 },
  { name: "Execution Engine", role: "execution_engine", tier: "D", is_active: true, last_invoked: "2026-04-11T14:30:00Z", total_invocations: 34, total_cost_usd: 0.0 },
];

const mockSystemHealth: SystemHealthOverview = {
  overall_status: "healthy",
  components: [
    { component: "Database", status: "healthy", last_check: new Date().toISOString(), details: null },
    { component: "Scanner", status: "healthy", last_check: new Date().toISOString(), details: null },
    { component: "Risk Governor", status: "healthy", last_check: new Date().toISOString(), details: null },
    { component: "Cost Governor", status: "healthy", last_check: new Date().toISOString(), details: null },
    { component: "Telegram", status: "healthy", last_check: new Date().toISOString(), details: null },
    { component: "CLOB Cache", status: "healthy", last_check: new Date().toISOString(), details: "247 entries, 94.2% hit rate" },
  ],
  active_alerts_count: 0,
};

const mockBias: BiasAuditOverview = {
  last_audit_at: "2026-04-12T22:00:00Z",
  active_patterns: [
    { pattern_type: "directional_bias", severity: "info", description: "Slight bullish skew on politics markets (+3.2pp avg)", weeks_active: 1, is_persistent: false, first_detected: "2026-04-12T22:00:00Z" },
  ],
  persistent_pattern_count: 0, resolved_pattern_count: 2,
};

const mockViability: ViabilityOverview = {
  current_signal: "neutral",
  checkpoints: [
    { checkpoint_week: 4, assessed_at: "2026-03-20T00:00:00Z", signal: "neutral", system_brier: 0.195, market_brier: 0.200, resolved_count: 14, recommendation: "Insufficient data. Continue shadow collection." },
  ],
  lifetime_budget_pct: 6.25, patience_budget_remaining_days: 218,
};

const mockAbsence: AbsenceStatus = {
  is_absent: false, absence_level: 0, hours_since_activity: 0.2,
  last_activity: new Date().toISOString(),
  restrictions_active: [], autonomous_actions_count: 0,
};

// ──────────────────────────────────────────────
// Export — Use mock data (API integration ready)
// ──────────────────────────────────────────────

let useMock = true;

export async function fetchPortfolio(): Promise<PortfolioOverview> {
  if (useMock) return mockPortfolio;
  return apiFetch("/api/portfolio");
}

export async function fetchPositions(): Promise<PositionSummary[]> {
  if (useMock) return mockPositions;
  return apiFetch("/api/positions");
}

export async function fetchRisk(): Promise<RiskBoard> {
  if (useMock) return mockRisk;
  return apiFetch("/api/risk");
}

export async function fetchCost(): Promise<CostMetrics> {
  if (useMock) return mockCost;
  return apiFetch("/api/cost");
}

export async function fetchScanner(): Promise<ScannerHealth> {
  if (useMock) return mockScanner;
  return apiFetch("/api/scanner");
}

export async function fetchCalibration(): Promise<CalibrationOverview> {
  if (useMock) return mockCalibration;
  return apiFetch("/api/calibration");
}

export async function fetchCategories(): Promise<CategoryPerformanceEntry[]> {
  if (useMock) return mockCategories;
  return apiFetch("/api/categories");
}

export async function fetchWorkflows(): Promise<WorkflowRunSummary[]> {
  if (useMock) return mockWorkflows;
  return apiFetch("/api/workflows");
}

export async function fetchTriggers(): Promise<TriggerEventItem[]> {
  if (useMock) return mockTriggers;
  return apiFetch("/api/triggers");
}

export async function fetchAgents(): Promise<AgentStatus[]> {
  if (useMock) return mockAgents;
  return apiFetch("/api/agents");
}

export async function fetchSystemHealth(): Promise<SystemHealthOverview> {
  if (useMock) return mockSystemHealth;
  return apiFetch("/api/system-health");
}

export async function fetchBias(): Promise<BiasAuditOverview> {
  if (useMock) return mockBias;
  return apiFetch("/api/bias");
}

export async function fetchViability(): Promise<ViabilityOverview> {
  if (useMock) return mockViability;
  return apiFetch("/api/viability");
}

export async function fetchAbsence(): Promise<AbsenceStatus> {
  if (useMock) return mockAbsence;
  return apiFetch("/api/absence");
}

export async function controlAgents(action: "start" | "stop"): Promise<SystemControlResponse> {
  if (useMock) {
    const running = action === "start";
    mockAgents.forEach(a => a.is_active = running);
    mockPortfolio.system_status = running ? "running" : "stopped";
    return { success: true, message: `Agents ${action}ed`, current_mode: mockPortfolio.operator_mode, timestamp: new Date().toISOString() };
  }
  return apiPost(`/api/control/agents/${action}`);
}

export async function changeMode(mode: string, reason?: string): Promise<SystemControlResponse> {
  if (useMock) {
    mockPortfolio.operator_mode = mode;
    return { success: true, message: `Mode changed to ${mode}`, current_mode: mode, timestamp: new Date().toISOString() };
  }
  return apiPost("/api/control/mode", { mode, reason });
}
