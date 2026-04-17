"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  Activity,
  ArrowDownCircle,
  ArrowUpCircle,
  BarChart3,
  Bot,
  Brain,
  ChevronDown,
  DollarSign,
  HeartPulse,
  LayoutDashboard,
  Play,
  Radio,
  RefreshCw,
  Shield,
  Square,
  Target,
  TrendingUp,
  Wallet,
  Zap,
} from "lucide-react";
import {
  fetchPortfolio,
  fetchPositions,
  fetchRisk,
  fetchCost,
  fetchScanner,
  fetchCalibration,
  fetchCategories,
  fetchWorkflows,
  fetchTriggers,
  fetchAgents,
  fetchSystemHealth,
  fetchBias,
  fetchViability,
  fetchAbsence,
  fetchPaperBalance,
  fetchActivityLog,
  depositPaperFunds,
  withdrawPaperFunds,
  controlAgents,
  changeMode,
  isApiAvailable,
  type PortfolioOverview,
  type PositionSummary,
  type RiskBoard,
  type CostMetrics,
  type ScannerHealth,
  type CalibrationOverview,
  type CategoryPerformanceEntry,
  type WorkflowRunSummary,
  type TriggerEventItem,
  type AgentStatus,
  type SystemHealthOverview,
  type BiasAuditOverview,
  type ViabilityOverview,
  type AbsenceStatus,
  type PaperBalanceResponse,
  type ActivityLogEntry,
} from "@/lib/api";
import { OverviewPage } from "@/components/pages/OverviewPage";
import { PositionsPage } from "@/components/pages/PositionsPage";
import { RiskPage } from "@/components/pages/RiskPage";
import { WorkflowsPage } from "@/components/pages/WorkflowsPage";
import { AnalyticsPage } from "@/components/pages/AnalyticsPage";
import { CalibrationPage } from "@/components/pages/CalibrationPage";
import { AgentsPage } from "@/components/pages/AgentsPage";
import { SystemPage } from "@/components/pages/SystemPage";

type Page =
  | "overview"
  | "positions"
  | "risk"
  | "workflows"
  | "analytics"
  | "calibration"
  | "agents"
  | "system";

export interface DashboardData {
  portfolio: PortfolioOverview | null;
  positions: PositionSummary[];
  risk: RiskBoard | null;
  cost: CostMetrics | null;
  scanner: ScannerHealth | null;
  calibration: CalibrationOverview | null;
  categories: CategoryPerformanceEntry[];
  workflows: WorkflowRunSummary[];
  triggers: TriggerEventItem[];
  agents: AgentStatus[];
  health: SystemHealthOverview | null;
  bias: BiasAuditOverview | null;
  viability: ViabilityOverview | null;
  absence: AbsenceStatus | null;
  paperBalance: PaperBalanceResponse | null;
  activityLog: ActivityLogEntry[];
}

const NAV_ITEMS: { page: Page; label: string; icon: React.ReactNode; section: string }[] = [
  { page: "overview", label: "Overview", icon: <LayoutDashboard />, section: "Command" },
  { page: "positions", label: "Positions", icon: <Target />, section: "Command" },
  { page: "risk", label: "Risk Board", icon: <Shield />, section: "Command" },
  { page: "workflows", label: "Workflows", icon: <Zap />, section: "Operations" },
  { page: "analytics", label: "Analytics", icon: <BarChart3 />, section: "Intelligence" },
  { page: "calibration", label: "Calibration", icon: <Brain />, section: "Intelligence" },
  { page: "agents", label: "Agents", icon: <Bot />, section: "System" },
  { page: "system", label: "System Health", icon: <HeartPulse />, section: "System" },
];

const MODES = [
  { value: "shadow", label: "Shadow", color: "var(--purple)", desc: "Simulated — no real trades" },
  { value: "paper", label: "Paper", color: "var(--blue)", desc: "Paper trading mode" },
  { value: "live_small", label: "Live Small", color: "var(--yellow)", desc: "Real trades, small size" },
  { value: "live_standard", label: "Live", color: "var(--green)", desc: "Full live trading" },
];

function formatPercent(value: number): string {
  const percent = value * 100;
  return Number.isInteger(percent) ? `${percent}%` : `${percent.toFixed(1)}%`;
}

export default function Dashboard() {
  const [page, setPage] = useState<Page>("overview");
  const [data, setData] = useState<DashboardData>({
    portfolio: null, positions: [], risk: null, cost: null, scanner: null,
    calibration: null, categories: [], workflows: [], triggers: [],
    agents: [], health: null, bias: null, viability: null, absence: null,
    paperBalance: null, activityLog: [],
  });
  const [agentsRunning, setAgentsRunning] = useState(false);
  const [loading, setLoading] = useState(true);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);
  const [showModePanel, setShowModePanel] = useState(false);
  const [balanceInput, setBalanceInput] = useState("");
  const [apiConnected, setApiConnected] = useState<boolean | null>(null);
  const refreshTimer = useRef<ReturnType<typeof setInterval> | null>(null);

  const loadData = useCallback(async () => {
    try {
      const [portfolio, positions, risk, cost, scanner, calibration, categories,
        workflows, triggers, agents, health, bias, viability, absence,
        paperBalance, activityLog] = await Promise.all([
        fetchPortfolio(), fetchPositions(), fetchRisk(), fetchCost(),
        fetchScanner(), fetchCalibration(), fetchCategories(),
        fetchWorkflows(), fetchTriggers(), fetchAgents(),
        fetchSystemHealth(), fetchBias(), fetchViability(), fetchAbsence(),
        fetchPaperBalance(), fetchActivityLog(),
      ]);
      setData({ portfolio, positions, risk, cost, scanner, calibration, categories,
        workflows, triggers, agents, health, bias, viability, absence,
        paperBalance, activityLog });
      setAgentsRunning(portfolio?.system_status === "running");
      setApiConnected(isApiAvailable());
      setLastRefresh(new Date());
    } catch (err) {
      console.error("Failed to load dashboard data:", err);
    } finally {
      setLoading(false);
    }
  }, []);

  // Initial load + auto-refresh every 10s
  useEffect(() => {
    loadData();
    refreshTimer.current = setInterval(loadData, 10000);
    return () => { if (refreshTimer.current) clearInterval(refreshTimer.current); };
  }, [loadData]);

  const handleToggleAgents = async () => {
    const action = agentsRunning ? "stop" : "start";
    const result = await controlAgents(action);
    if (result.success) {
      setAgentsRunning(!agentsRunning);
      await loadData();
    }
  };

  const handleChangeMode = async (mode: string) => {
    const result = await changeMode(mode, `Dashboard mode switch to ${mode}`);
    if (result.success) {
      setShowModePanel(false);
      await loadData();
    }
  };

  const handleDeposit = async () => {
    const amount = parseFloat(balanceInput);
    if (!amount || amount <= 0) return;
    try {
      await depositPaperFunds(amount, "Dashboard deposit");
      setBalanceInput("");
      await loadData();
    } catch (err) {
      console.error("Deposit failed:", err);
    }
  };

  const handleWithdraw = async () => {
    const amount = parseFloat(balanceInput);
    if (!amount || amount <= 0) return;
    try {
      await withdrawPaperFunds(amount, "Dashboard withdrawal");
      setBalanceInput("");
      await loadData();
    } catch (err) {
      console.error("Withdrawal failed:", err);
    }
  };

  const currentMode = data.portfolio?.operator_mode || "shadow";
  const modeInfo = MODES.find((m) => m.value === currentMode) || MODES[0];
  const isShadowOrPaper = currentMode === "shadow" || currentMode === "paper";
  const drawdownLevel = data.risk?.drawdown_ladder.current_level || "normal";
  const drawdownColor =
    drawdownLevel === "normal"
      ? "var(--text)"
      : drawdownLevel === "soft_warning"
        ? "var(--yellow)"
        : "var(--red)";

  // Group nav items by section
  const sections = NAV_ITEMS.reduce<Record<string, typeof NAV_ITEMS>>((acc, item) => {
    if (!acc[item.section]) acc[item.section] = [];
    acc[item.section].push(item);
    return acc;
  }, {});

  return (
    <div className="dashboard-layout">
      {/* Sidebar */}
      <aside className="sidebar">
        <div className="sidebar-brand">
          <div className="sidebar-brand-icon">
            <TrendingUp size={16} color="#0a0e14" strokeWidth={2.5} />
          </div>
          <div>
            <div className="sidebar-brand-text">POLYMARKET</div>
            <div className="sidebar-brand-sub">Trading System</div>
          </div>
        </div>

        {Object.entries(sections).map(([section, items]) => (
          <div className="nav-section" key={section}>
            <div className="nav-section-title">{section}</div>
            {items.map((item) => (
              <button
                key={item.page}
                className={`nav-item ${page === item.page ? "active" : ""}`}
                onClick={() => setPage(item.page)}
              >
                {item.icon}
                {item.label}
              </button>
            ))}
          </div>
        ))}

        {/* Mode Switcher */}
        <div style={{ padding: "0.5rem 1rem", marginTop: "auto" }}>
          <div className="card" style={{ padding: "0.75rem" }}>
            {/* Current Mode Header */}
            <button
              onClick={() => setShowModePanel(!showModePanel)}
              style={{
                display: "flex", alignItems: "center", gap: "0.5rem", width: "100%",
                background: "none", border: "none", cursor: "pointer", padding: "0.25rem 0",
                color: "var(--text)", fontFamily: "inherit",
              }}
            >
              <Radio size={14} color={modeInfo.color} />
              <div style={{ flex: 1, textAlign: "left" }}>
                <div style={{ fontSize: "0.7rem", fontWeight: 600, color: modeInfo.color, textTransform: "uppercase", letterSpacing: "0.08em" }}>
                  {modeInfo.label} Mode
                </div>
                <div style={{ fontSize: "0.6rem", color: "var(--text-dim)" }}>{modeInfo.desc}</div>
              </div>
              <ChevronDown size={12} color="var(--text-muted)" style={{ transform: showModePanel ? "rotate(180deg)" : "none", transition: "transform 0.2s" }} />
            </button>

            {/* Mode Options — in-flow expansion (no absolute positioning) */}
            {showModePanel && (
              <div style={{
                marginTop: "0.5rem", paddingTop: "0.5rem",
                borderTop: "1px solid var(--border)",
                display: "flex", flexDirection: "column", gap: "0.25rem",
              }}>
                {MODES.map((m) => (
                  <button
                    key={m.value}
                    onClick={() => handleChangeMode(m.value)}
                    style={{
                      display: "flex", alignItems: "center", gap: "0.5rem", width: "100%",
                      padding: "0.5rem 0.5rem",
                      background: currentMode === m.value ? "var(--neon-soft)" : "transparent",
                      border: currentMode === m.value ? "1px solid var(--neon)" : "1px solid transparent",
                      borderRadius: "var(--radius-sm)",
                      cursor: "pointer", color: "var(--text)", fontFamily: "inherit",
                      transition: "all 0.15s ease",
                    }}
                    onMouseEnter={(e) => {
                      if (currentMode !== m.value) {
                        e.currentTarget.style.background = "rgba(255,255,255,0.04)";
                      }
                    }}
                    onMouseLeave={(e) => {
                      if (currentMode !== m.value) {
                        e.currentTarget.style.background = "transparent";
                      }
                    }}
                  >
                    <span style={{ width: 8, height: 8, borderRadius: "50%", background: m.color, flexShrink: 0 }} />
                    <div style={{ textAlign: "left" }}>
                      <div style={{ fontSize: "0.72rem", fontWeight: 600 }}>{m.label}</div>
                      <div style={{ fontSize: "0.58rem", color: "var(--text-dim)" }}>{m.desc}</div>
                    </div>
                    {currentMode === m.value && (
                      <span style={{ marginLeft: "auto", fontSize: "0.6rem", color: "var(--neon)", fontWeight: 600 }}>✓</span>
                    )}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Paper Balance Panel (shadow/paper only) */}
        {isShadowOrPaper && (
          <div style={{ padding: "0 1rem 0.5rem" }}>
            <div className="card" style={{ padding: "0.75rem" }}>
              <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", marginBottom: "0.5rem" }}>
                <Wallet size={14} color="var(--neon)" />
                <span style={{ fontSize: "0.68rem", fontWeight: 600, color: "var(--text-dim)", textTransform: "uppercase", letterSpacing: "0.08em" }}>Paper Balance</span>
              </div>
              <div style={{ fontSize: "1.5rem", fontWeight: 700, color: "var(--neon)", fontFamily: "var(--font-display), 'Space Grotesk', sans-serif", letterSpacing: "-0.03em" }}>
                ${(data.paperBalance?.balance_usd ?? data.portfolio?.paper_cash_balance_usd ?? 500).toFixed(2)}
              </div>

              {/* Always-visible deposit/withdraw controls */}
              <div style={{ marginTop: "0.75rem", display: "flex", flexDirection: "column", gap: "0.5rem" }}>
                <input
                  type="number"
                  value={balanceInput}
                  onChange={(e) => setBalanceInput(e.target.value)}
                  placeholder="Enter amount (USD)"
                  min="0"
                  step="10"
                  style={{
                    width: "100%", padding: "0.55rem 0.65rem", fontSize: "0.8rem",
                    background: "var(--bg-input, rgba(255,255,255,0.04))", border: "1px solid var(--border)",
                    borderRadius: "var(--radius-sm)", color: "var(--text)",
                    fontFamily: "inherit", outline: "none",
                  }}
                  onFocus={(e) => { e.currentTarget.style.borderColor = "var(--neon)"; }}
                  onBlur={(e) => { e.currentTarget.style.borderColor = "var(--border)"; }}
                />
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.5rem" }}>
                  <button
                    onClick={handleDeposit}
                    style={{
                      display: "flex", alignItems: "center", justifyContent: "center", gap: "0.4rem",
                      width: "100%", padding: "0.55rem 0", fontSize: "0.78rem", fontWeight: 600,
                      background: "rgba(1, 121, 111, 0.15)", color: "var(--neon)",
                      border: "1px solid var(--neon)", borderRadius: "var(--radius-sm)",
                      cursor: "pointer", fontFamily: "inherit",
                      transition: "all 0.15s ease",
                      boxSizing: "border-box", minWidth: 0,
                    }}
                    onMouseEnter={(e) => { e.currentTarget.style.background = "rgba(1, 121, 111, 0.30)"; }}
                    onMouseLeave={(e) => { e.currentTarget.style.background = "rgba(1, 121, 111, 0.15)"; }}
                  >
                    <ArrowDownCircle size={15} /> Deposit
                  </button>
                  <button
                    onClick={handleWithdraw}
                    style={{
                      display: "flex", alignItems: "center", justifyContent: "center", gap: "0.4rem",
                      width: "100%", padding: "0.55rem 0", fontSize: "0.78rem", fontWeight: 600,
                      background: "rgba(244, 63, 94, 0.12)", color: "var(--red, #f43f5e)",
                      border: "1px solid var(--red, #f43f5e)", borderRadius: "var(--radius-sm)",
                      cursor: "pointer", fontFamily: "inherit",
                      transition: "all 0.15s ease",
                      boxSizing: "border-box", minWidth: 0,
                    }}
                    onMouseEnter={(e) => { e.currentTarget.style.background = "rgba(244, 63, 94, 0.25)"; }}
                    onMouseLeave={(e) => { e.currentTarget.style.background = "rgba(244, 63, 94, 0.12)"; }}
                  >
                    <ArrowUpCircle size={15} /> Withdraw
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* System Status */}
        <div style={{ padding: "0 1rem 1rem" }}>
          <div className="card" style={{ padding: "0.75rem" }}>
            <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", marginBottom: "0.5rem" }}>
              <span className={`status-dot ${agentsRunning ? "live" : "stopped"}`} />
              <span style={{ fontSize: "0.72rem", fontWeight: 600, color: agentsRunning ? "var(--green)" : "var(--red)" }}>
                {agentsRunning ? "SYSTEM LIVE" : "SYSTEM OFF"}
              </span>
            </div>
            <div style={{ display: "flex", gap: "0.5rem" }}>
              <button
                className={`btn-neon ${agentsRunning ? "active" : ""}`}
                style={{ flex: 1, fontSize: "0.65rem", padding: "0.35rem 0.5rem", justifyContent: "center" }}
                onClick={handleToggleAgents}
                disabled={agentsRunning}
              >
                <Play size={12} /> Start
              </button>
              <button
                className="btn-neon danger"
                style={{ flex: 1, fontSize: "0.65rem", padding: "0.35rem 0.5rem", justifyContent: "center" }}
                onClick={handleToggleAgents}
                disabled={!agentsRunning}
              >
                <Square size={12} /> Stop
              </button>
            </div>
          </div>
        </div>
      </aside>

      {/* Main Content */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
        {/* Top Bar */}
        <header className="topbar">
          <div className="topbar-status">
            <div className="topbar-item">
              <span className={`status-dot ${agentsRunning ? "live" : "stopped"}`} />
              <span className="label">Status</span>
              <span className="value" style={{ color: agentsRunning ? "var(--green)" : "var(--red)" }}>
                {agentsRunning ? "Running" : "Stopped"}
              </span>
            </div>
            <div className="topbar-item">
              <Radio size={12} color={modeInfo.color} />
              <span className="label">Mode</span>
              <span className="value" style={{ color: modeInfo.color, textTransform: "uppercase" }}>
                {modeInfo.label}
              </span>
            </div>
            <div className="topbar-item">
              <Shield size={12} />
              <span className="label">Drawdown</span>
              <span className="value" style={{ color: drawdownColor }}>
                {formatPercent(data.risk?.drawdown_ladder.current_drawdown_pct || 0)}
              </span>
            </div>
            <div className="topbar-item">
              <DollarSign size={12} />
              <span className="label">Balance</span>
              <span className="value" style={{ color: "var(--neon)" }}>
                ${(data.paperBalance?.balance_usd ?? data.portfolio?.paper_cash_balance_usd ?? 0).toFixed(2)}
              </span>
            </div>
            <div className="topbar-item">
              <Activity size={12} />
              <span className="label">Positions</span>
              <span className="value">{data.portfolio?.open_positions_count || 0}</span>
            </div>
          </div>
          <div className="topbar-controls">
            <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
              {/* API Status Indicator */}
              <span style={{
                display: "inline-flex", alignItems: "center", gap: "0.3rem",
                fontSize: "0.6rem", color: apiConnected ? "var(--green)" : "var(--text-muted)",
                padding: "0.2rem 0.5rem", border: "1px solid var(--border)",
                borderRadius: "var(--radius-sm)", background: apiConnected ? "rgba(var(--green-rgb), 0.08)" : "transparent",
              }}>
                <span style={{ width: 5, height: 5, borderRadius: "50%", background: apiConnected ? "var(--green)" : "var(--text-muted)", display: "inline-block" }} />
                {apiConnected ? "LIVE" : "MOCK"}
              </span>
              {/* Auto-refresh indicator */}
              <button
                onClick={loadData}
                style={{
                  display: "inline-flex", alignItems: "center", gap: "0.3rem",
                  fontSize: "0.6rem", color: "var(--text-dim)", background: "none",
                  border: "1px solid var(--border)", borderRadius: "var(--radius-sm)",
                  padding: "0.2rem 0.5rem", cursor: "pointer", fontFamily: "inherit",
                }}
                title="Refresh now"
              >
                <RefreshCw size={10} />
                {lastRefresh ? lastRefresh.toLocaleTimeString() : "--:--:--"}
              </button>
            </div>
          </div>
        </header>

        {/* Page Content */}
        <main className="dashboard-main">
          {loading ? (
            <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "60vh" }}>
              <div style={{ textAlign: "center" }}>
                <div className="status-dot live" style={{ width: 16, height: 16, margin: "0 auto 1rem" }} />
                <div style={{ color: "var(--text-dim)", fontSize: "0.8rem" }}>Connecting to system…</div>
              </div>
            </div>
          ) : (
            <>
              {page === "overview" && <OverviewPage data={data} />}
              {page === "positions" && <PositionsPage positions={data.positions} />}
              {page === "risk" && <RiskPage risk={data.risk} />}
              {page === "workflows" && <WorkflowsPage workflows={data.workflows} triggers={data.triggers} />}
              {page === "analytics" && <AnalyticsPage categories={data.categories} cost={data.cost} bias={data.bias} viability={data.viability} />}
              {page === "calibration" && <CalibrationPage calibration={data.calibration} />}
              {page === "agents" && <AgentsPage agents={data.agents} agentsRunning={agentsRunning} onToggle={handleToggleAgents} />}
              {page === "system" && <SystemPage health={data.health} scanner={data.scanner} absence={data.absence} />}
            </>
          )}
        </main>
      </div>
    </div>
  );
}
