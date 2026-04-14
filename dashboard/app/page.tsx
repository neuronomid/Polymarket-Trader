"use client";

import { useCallback, useEffect, useState } from "react";
import {
  Activity,
  AlertTriangle,
  BarChart3,
  Bot,
  Brain,
  ChevronRight,
  DollarSign,
  Eye,
  Gauge,
  HeartPulse,
  LayoutDashboard,
  Play,
  Power,
  Radio,
  Shield,
  Square,
  Target,
  TrendingUp,
  UserX,
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
  controlAgents,
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

interface DashboardData {
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

export default function Dashboard() {
  const [page, setPage] = useState<Page>("overview");
  const [data, setData] = useState<DashboardData>({
    portfolio: null, positions: [], risk: null, cost: null, scanner: null,
    calibration: null, categories: [], workflows: [], triggers: [],
    agents: [], health: null, bias: null, viability: null, absence: null,
  });
  const [agentsRunning, setAgentsRunning] = useState(true);
  const [loading, setLoading] = useState(true);

  const loadData = useCallback(async () => {
    try {
      const [portfolio, positions, risk, cost, scanner, calibration, categories,
        workflows, triggers, agents, health, bias, viability, absence] = await Promise.all([
        fetchPortfolio(), fetchPositions(), fetchRisk(), fetchCost(),
        fetchScanner(), fetchCalibration(), fetchCategories(),
        fetchWorkflows(), fetchTriggers(), fetchAgents(),
        fetchSystemHealth(), fetchBias(), fetchViability(), fetchAbsence(),
      ]);
      setData({ portfolio, positions, risk, cost, scanner, calibration, categories,
        workflows, triggers, agents, health, bias, viability, absence });
      setAgentsRunning(portfolio.system_status === "running");
    } catch (err) {
      console.error("Failed to load dashboard data:", err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadData(); }, [loadData]);

  const handleToggleAgents = async () => {
    const action = agentsRunning ? "stop" : "start";
    const result = await controlAgents(action);
    if (result.success) {
      setAgentsRunning(!agentsRunning);
      await loadData();
    }
  };

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

        {/* System Status at bottom */}
        <div style={{ marginTop: "auto", padding: "1rem" }}>
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
                className={`btn-neon danger ${!agentsRunning ? "" : ""}`}
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
              <Radio size={12} />
              <span className="label">Mode</span>
              <span className="value" style={{ color: "var(--blue)", textTransform: "uppercase" }}>
                {data.portfolio?.operator_mode || "—"}
              </span>
            </div>
            <div className="topbar-item">
              <Shield size={12} />
              <span className="label">Drawdown</span>
              <span className="value" style={{ color: (data.risk?.drawdown_ladder.current_drawdown_pct || 0) > 3 ? "var(--yellow)" : "var(--text)" }}>
                {data.risk?.drawdown_ladder.current_drawdown_pct.toFixed(1) || "0.0"}%
              </span>
            </div>
            <div className="topbar-item">
              <DollarSign size={12} />
              <span className="label">Daily P&L</span>
              <span className="value" style={{ color: (data.portfolio?.daily_pnl_usd || 0) >= 0 ? "var(--green)" : "var(--red)" }}>
                {(data.portfolio?.daily_pnl_usd || 0) >= 0 ? "+" : ""}${data.portfolio?.daily_pnl_usd.toFixed(2) || "0.00"}
              </span>
            </div>
            <div className="topbar-item">
              <Activity size={12} />
              <span className="label">Positions</span>
              <span className="value">{data.portfolio?.open_positions_count || 0}</span>
            </div>
          </div>
          <div className="topbar-controls">
            <span style={{ fontSize: "0.65rem", color: "var(--text-muted)" }}>
              {new Date().toLocaleTimeString()}
            </span>
          </div>
        </header>

        {/* Page Content */}
        <main className="dashboard-main">
          {loading ? (
            <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "60vh" }}>
              <div style={{ textAlign: "center" }}>
                <div className="status-dot live" style={{ width: 16, height: 16, margin: "0 auto 1rem" }} />
                <div style={{ color: "var(--text-dim)", fontSize: "0.8rem" }}>Loading dashboard data…</div>
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
