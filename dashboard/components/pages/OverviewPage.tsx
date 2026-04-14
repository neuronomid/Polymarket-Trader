"use client";

import {
  AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer,
  BarChart, Bar, PieChart, Pie, Cell,
} from "recharts";
import {
  TrendingUp, TrendingDown, DollarSign, Target, Shield, Activity,
  Zap, Eye, ArrowUpRight, ArrowDownRight,
} from "lucide-react";
import type {
  PortfolioOverview, PositionSummary, RiskBoard, CostMetrics,
  ScannerHealth, CalibrationOverview, CategoryPerformanceEntry,
  WorkflowRunSummary, TriggerEventItem, AgentStatus,
  SystemHealthOverview, BiasAuditOverview, ViabilityOverview, AbsenceStatus,
} from "@/lib/api";

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

const CHART_COLORS = ["#39FF14", "#00D4FF", "#9B5DE5", "#FFBE0B", "#FF6B35", "#FF3B5C"];

const CustomTooltip = ({ active, payload, label }: any) => {
  if (!active || !payload?.length) return null;
  return (
    <div style={{
      background: "var(--bg-elevated)", border: "1px solid var(--border-glow)",
      borderRadius: "var(--radius-sm)", padding: "0.5rem 0.75rem",
      fontSize: "0.72rem",
    }}>
      <div style={{ color: "var(--text-dim)", marginBottom: "0.25rem" }}>
        {new Date(label).toLocaleDateString()}
      </div>
      {payload.map((p: any, i: number) => (
        <div key={i} style={{ color: p.color, fontWeight: 600 }}>
          ${p.value.toLocaleString(undefined, { minimumFractionDigits: 2 })}
        </div>
      ))}
    </div>
  );
};

export function OverviewPage({ data }: { data: DashboardData }) {
  const p = data.portfolio;
  if (!p) return null;

  const equityData = p.equity_history.map((e) => ({
    date: e.timestamp,
    equity: e.equity_usd,
  }));

  const exposureData = data.risk?.exposure_by_category.map((e) => ({
    name: e.category,
    value: e.exposure_usd,
  })) || [];

  const triggerLevels = data.triggers.reduce<Record<string, number>>((acc, t) => {
    acc[t.trigger_level] = (acc[t.trigger_level] || 0) + 1;
    return acc;
  }, {});

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-title">Executive Overview</h1>
          <div className="page-subtitle">Real-time portfolio intelligence and system state</div>
        </div>
      </div>

      {/* Stats Grid */}
      <div className="stats-grid">
        <div className="card fade-in stagger-1">
          <div className="card-header">
            <span className="card-title">Total Equity</span>
            <DollarSign size={14} color="var(--neon)" />
          </div>
          <div className="stat-value glow-green" style={{ color: "var(--neon)" }}>
            ${p.total_equity_usd.toLocaleString(undefined, { minimumFractionDigits: 2 })}
          </div>
          <div className="stat-label">Account balance</div>
        </div>

        <div className="card fade-in stagger-2">
          <div className="card-header">
            <span className="card-title">Daily P&L</span>
            {p.daily_pnl_usd >= 0 ? <ArrowUpRight size={14} color="var(--green)" /> : <ArrowDownRight size={14} color="var(--red)" />}
          </div>
          <div className="stat-value" style={{ color: p.daily_pnl_usd >= 0 ? "var(--green)" : "var(--red)" }}>
            {p.daily_pnl_usd >= 0 ? "+" : ""}${p.daily_pnl_usd.toFixed(2)}
          </div>
          <div style={{ display: "flex", gap: "1rem", marginTop: "0.25rem" }}>
            <span className="stat-label">Unrealized: <span style={{ color: p.unrealized_pnl_usd >= 0 ? "var(--green)" : "var(--red)" }}>${p.unrealized_pnl_usd.toFixed(2)}</span></span>
            <span className="stat-label">Realized: <span style={{ color: p.realized_pnl_usd >= 0 ? "var(--green)" : "var(--red)" }}>${p.realized_pnl_usd.toFixed(2)}</span></span>
          </div>
        </div>

        <div className="card fade-in stagger-3">
          <div className="card-header">
            <span className="card-title">Open Exposure</span>
            <Target size={14} color="var(--blue)" />
          </div>
          <div className="stat-value" style={{ color: "var(--blue)" }}>
            ${p.total_open_exposure_usd.toLocaleString(undefined, { minimumFractionDigits: 2 })}
          </div>
          <div className="stat-label">{p.open_positions_count} positions open</div>
        </div>

        <div className="card fade-in stagger-4">
          <div className="card-header">
            <span className="card-title">Risk State</span>
            <Shield size={14} color={p.drawdown_pct > 3 ? "var(--yellow)" : "var(--green)"} />
          </div>
          <div className="stat-value" style={{ color: p.drawdown_pct > 3 ? "var(--yellow)" : "var(--text)" }}>
            {p.drawdown_pct.toFixed(1)}%
          </div>
          <div style={{ marginTop: "0.5rem" }}>
            <span className={`badge ${p.drawdown_level === "normal" ? "green" : p.drawdown_level === "soft_warning" ? "yellow" : "red"}`}>
              {p.drawdown_level.replace(/_/g, " ")}
            </span>
          </div>
        </div>

        <div className="card fade-in stagger-5">
          <div className="card-header">
            <span className="card-title">Daily Cost</span>
            <Activity size={14} color="var(--purple)" />
          </div>
          <div className="stat-value" style={{ color: "var(--purple)" }}>
            ${data.cost?.daily_spend_usd.toFixed(2) || "0.00"}
          </div>
          <div style={{ marginTop: "0.5rem" }}>
            <div className="progress-track">
              <div className="progress-fill blue" style={{ width: `${((data.cost?.daily_spend_usd || 0) / (data.cost?.daily_budget_usd || 25)) * 100}%` }} />
            </div>
            <div className="stat-label" style={{ marginTop: "0.35rem" }}>of ${data.cost?.daily_budget_usd || 25} budget</div>
          </div>
        </div>

        <div className="card fade-in stagger-6">
          <div className="card-header">
            <span className="card-title">Selectivity</span>
            <Eye size={14} color="var(--yellow)" />
          </div>
          <div className="stat-value" style={{ color: (data.cost?.selectivity_ratio || 0) < (data.cost?.selectivity_target || 0.2) ? "var(--green)" : "var(--yellow)" }}>
            {((data.cost?.selectivity_ratio || 0) * 100).toFixed(1)}%
          </div>
          <div className="stat-label">Target: {((data.cost?.selectivity_target || 0.2) * 100).toFixed(0)}%</div>
        </div>
      </div>

      {/* Charts Grid */}
      <div className="content-grid" style={{ marginTop: "1rem" }}>
        {/* Equity Curve */}
        <div className="card fade-in" style={{ gridColumn: "span 2" }}>
          <div className="card-header">
            <span className="card-title">Equity Curve — 30 Days</span>
            <TrendingUp size={14} color="var(--neon)" />
          </div>
          <div style={{ height: 250 }}>
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={equityData}>
                <defs>
                  <linearGradient id="equityGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#39FF14" stopOpacity={0.3} />
                    <stop offset="100%" stopColor="#39FF14" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <XAxis dataKey="date" tick={false} stroke="transparent" />
                <YAxis
                  domain={["dataMin - 100", "dataMax + 100"]}
                  tick={{ fill: "var(--text-dim)", fontSize: 11 }}
                  stroke="transparent"
                  tickFormatter={(v) => `$${v.toLocaleString()}`}
                />
                <Tooltip content={<CustomTooltip />} />
                <Area
                  type="monotone" dataKey="equity" stroke="#39FF14"
                  fill="url(#equityGrad)" strokeWidth={2}
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      <div className="content-grid">
        {/* Recent Positions */}
        <div className="card fade-in">
          <div className="card-header">
            <span className="card-title">Open Positions</span>
            <Target size={14} color="var(--blue)" />
          </div>
          <div style={{ maxHeight: 280, overflowY: "auto" }}>
            <table className="data-table">
              <thead><tr><th>Market</th><th>Side</th><th>P&L</th><th>Status</th></tr></thead>
              <tbody>
                {data.positions.slice(0, 5).map((pos) => (
                  <tr key={pos.id}>
                    <td style={{ maxWidth: 180, overflow: "hidden", textOverflow: "ellipsis" }}>{pos.market_title}</td>
                    <td><span className={`badge ${pos.side === "yes" ? "green" : "red"}`}>{pos.side}</span></td>
                    <td style={{ color: (pos.unrealized_pnl || 0) >= 0 ? "var(--green)" : "var(--red)" }}>
                      {(pos.unrealized_pnl || 0) >= 0 ? "+" : ""}${(pos.unrealized_pnl || 0).toFixed(2)}
                    </td>
                    <td><span className={`badge ${pos.review_tier === "new" ? "blue" : pos.review_tier === "stable" ? "green" : "muted"}`}>{pos.review_tier}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* Recent Triggers */}
        <div className="card fade-in">
          <div className="card-header">
            <span className="card-title">Recent Triggers</span>
            <Zap size={14} color="var(--yellow)" />
          </div>
          <div style={{ maxHeight: 280, overflowY: "auto" }}>
            {data.triggers.slice(0, 5).map((t) => (
              <div key={t.id} style={{
                display: "flex", alignItems: "center", gap: "0.75rem",
                padding: "0.5rem 0", borderBottom: "1px solid var(--border)",
              }}>
                <span className={`badge ${t.trigger_level === "C" || t.trigger_level === "D" ? "red" : t.trigger_level === "B" ? "yellow" : "muted"}`}>
                  {t.trigger_level}
                </span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: "0.75rem", fontWeight: 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {t.market_title || t.market_id}
                  </div>
                  <div style={{ fontSize: "0.65rem", color: "var(--text-dim)" }}>{t.reason}</div>
                </div>
                <span className={`badge ${t.trigger_class === "profit_protection" ? "green" : t.trigger_class === "discovery" ? "blue" : "muted"}`} style={{ fontSize: "0.6rem" }}>
                  {t.trigger_class.replace(/_/g, " ")}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="content-grid">
        {/* Exposure Breakdown */}
        <div className="card fade-in">
          <div className="card-header">
            <span className="card-title">Exposure by Category</span>
            <Shield size={14} color="var(--blue)" />
          </div>
          <div style={{ height: 220 }}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={data.risk?.exposure_by_category || []} layout="vertical">
                <XAxis type="number" tick={{ fill: "var(--text-dim)", fontSize: 10 }} stroke="transparent" tickFormatter={(v) => `$${v}`} />
                <YAxis type="category" dataKey="category" tick={{ fill: "var(--text-dim)", fontSize: 11 }} stroke="transparent" width={80} />
                <Tooltip content={<CustomTooltip />} />
                <Bar dataKey="exposure_usd" fill="#39FF14" radius={[0, 4, 4, 0]} barSize={16}>
                  {(data.risk?.exposure_by_category || []).map((_, i) => (
                    <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} fillOpacity={0.8} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Workflows Recent */}
        <div className="card fade-in">
          <div className="card-header">
            <span className="card-title">Recent Workflows</span>
            <Zap size={14} color="var(--purple)" />
          </div>
          <div style={{ maxHeight: 220, overflowY: "auto" }}>
            {data.workflows.slice(0, 5).map((wf) => (
              <div key={wf.id} style={{
                display: "flex", alignItems: "center", gap: "0.75rem",
                padding: "0.5rem 0", borderBottom: "1px solid var(--border)",
              }}>
                <span className={`badge ${wf.status === "completed" ? "green" : wf.status === "running" ? "blue" : "red"}`}>
                  {wf.status === "running" ? "●" : "✓"} {wf.status}
                </span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: "0.75rem", fontWeight: 500 }}>
                    {wf.workflow_type.replace(/_/g, " ")}
                  </div>
                  <div style={{ fontSize: "0.65rem", color: "var(--text-dim)" }}>
                    {wf.candidates_reviewed > 0 && `${wf.candidates_reviewed} reviewed → ${wf.candidates_accepted} accepted`}
                    {wf.candidates_reviewed === 0 && wf.market_title}
                  </div>
                </div>
                <div style={{ fontSize: "0.7rem", color: wf.cost_usd > 0 ? "var(--purple)" : "var(--text-dim)" }}>
                  ${wf.cost_usd.toFixed(2)}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
