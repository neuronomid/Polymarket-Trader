"use client";

import { useState, useMemo } from "react";
import {
  AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer,
  BarChart, Bar, Cell,
} from "recharts";
import type { TooltipContentProps, TooltipValueType } from "recharts";
import {
  TrendingUp, DollarSign, Target, Shield, Activity,
  Zap, ArrowUpRight, ArrowDownRight,
  Radio, AlertTriangle, CheckCircle, XCircle, Info,
} from "lucide-react";
import type { DashboardData } from "@/app/page";

const CHART_COLORS = ["#01796f", "#0ea5e9", "#8b5cf6", "#f59e0b", "#f97316", "#f43f5e"];

function formatTooltipValue(value: TooltipValueType | undefined): string {
  if (Array.isArray(value)) return value.join(", ");

  const numericValue = Number(value);
  if (!Number.isNaN(numericValue)) {
    return numericValue.toLocaleString(undefined, { minimumFractionDigits: 2 });
  }

  return String(value ?? "");
}

const CustomTooltip = ({
  active,
  payload,
  label,
}: TooltipContentProps<TooltipValueType, string>) => {
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
      {payload.map((entry, i: number) => (
        <div key={i} style={{ color: entry.color, fontWeight: 600 }}>
          ${formatTooltipValue(entry.value)}
        </div>
      ))}
    </div>
  );
};

const SEVERITY_ICONS: Record<string, React.ReactNode> = {
  success: <CheckCircle size={12} color="var(--green)" />,
  warning: <AlertTriangle size={12} color="var(--yellow)" />,
  error: <XCircle size={12} color="var(--red)" />,
  info: <Info size={12} color="var(--blue)" />,
};

const SEVERITY_COLORS: Record<string, string> = {
  success: "var(--green)",
  warning: "var(--yellow)",
  error: "var(--red)",
  info: "var(--blue)",
};

const EVENT_BADGE_COLOR: Record<string, string> = {
  system: "purple",
  scan: "blue",
  trigger: "yellow",
  investigation: "blue",
  trade: "green",
  risk: "red",
  cost: "yellow",
};

function timeAgo(timestamp: string): string {
  const diff = Date.now() - new Date(timestamp).getTime();
  const seconds = Math.floor(diff / 1000);
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

function formatPercent(value: number): string {
  const percent = value * 100;
  return Number.isInteger(percent) ? `${percent}%` : `${percent.toFixed(1)}%`;
}

function formatSignedUsd(value: number | null | undefined): string {
  const amount = Number(value ?? 0);
  if (!Number.isFinite(amount) || amount === 0) {
    return "$0.00";
  }
  if (amount > 0 && amount < 0.01) {
    return "<$0.01";
  }
  if (amount < 0 && amount > -0.01) {
    return "-$0.01";
  }
  if (amount > 0) {
    return `+$${amount.toFixed(2)}`;
  }
  return `-$${Math.abs(amount).toFixed(2)}`;
}

export function OverviewPage({ data }: { data: DashboardData }) {
  const p = data.portfolio;
  const [timeframe, setTimeframe] = useState<"D" | "W" | "M" | "All">("D");

  const recentActivity = useMemo(() => data.activityLog.slice(0, 40), [data.activityLog]);

  const equityData = useMemo(() => {
    if (!p) return [];
    return p.equity_history.map((e) => ({
      date: e.timestamp,
      equity: e.equity_usd,
    }));
  }, [p]);

  const filteredEquityData = useMemo(() => {
    if (!equityData.length) return [];
    if (timeframe === "All") return equityData;
    
    // Assume chronological, so end is latest
    const now = new Date(equityData[equityData.length - 1].date).getTime();
    
    const cutoff =
      timeframe === "D" ? now - 24 * 60 * 60 * 1000 :
      timeframe === "W" ? now - 7 * 24 * 60 * 60 * 1000 :
      now - 30 * 24 * 60 * 60 * 1000; // "M"
      
    return equityData.filter(d => new Date(d.date).getTime() >= cutoff);
  }, [equityData, timeframe]);

  if (!p) return null;

  const riskColor =
    p.drawdown_level === "normal"
      ? "var(--green)"
      : p.drawdown_level === "soft_warning"
        ? "var(--yellow)"
        : "var(--red)";

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
          <div className="stat-label">
            {p.operator_mode === "shadow" || p.operator_mode === "paper" ? "Paper equity" : "Account equity"}
          </div>
          <div className="stat-label" style={{ marginTop: "0.25rem" }}>
            Cash: ${p.paper_cash_balance_usd.toFixed(2)}  Reserved: ${p.paper_reserved_capital_usd.toFixed(2)}
          </div>
        </div>

        <div className="card fade-in stagger-2">
          <div className="card-header">
            <span className="card-title">Daily P&L</span>
            {p.daily_pnl_usd >= 0 ? <ArrowUpRight size={14} color="var(--green)" /> : <ArrowDownRight size={14} color="var(--red)" />}
          </div>
          <div className="stat-value" style={{ color: p.daily_pnl_usd >= 0 ? "var(--green)" : "var(--red)" }}>
            {formatSignedUsd(p.daily_pnl_usd)}
          </div>
          <div style={{ display: "flex", gap: "1rem", marginTop: "0.25rem" }}>
            <span className="stat-label">Unrealized: <span style={{ color: p.unrealized_pnl_usd >= 0 ? "var(--green)" : "var(--red)" }}>{formatSignedUsd(p.unrealized_pnl_usd)}</span></span>
            <span className="stat-label">Realized: <span style={{ color: p.realized_pnl_usd >= 0 ? "var(--green)" : "var(--red)" }}>{formatSignedUsd(p.realized_pnl_usd)}</span></span>
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
            <Shield size={14} color={riskColor} />
          </div>
          <div className="stat-value" style={{ color: riskColor }}>
            {formatPercent(p.drawdown_pct)}
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
              <div className="progress-fill blue" style={{ width: (data.cost?.daily_budget_usd || 0) > 0 ? `${((data.cost?.daily_spend_usd || 0) / data.cost!.daily_budget_usd) * 100}%` : "0%" }} />
            </div>
            <div className="stat-label" style={{ marginTop: "0.35rem" }}>
              {(data.cost?.daily_budget_usd || 0) > 0 ? `of $${data.cost?.daily_budget_usd.toFixed(2)} budget` : "dynamic budget"}
            </div>
          </div>
        </div>

      </div>

      {/* Charts Grid */}
      <div className="content-grid" style={{ marginTop: "1rem" }}>
          <div className="card fade-in" style={{ gridColumn: "span 2" }}>
            <div className="card-header" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                <span className="card-title">Equity Curve</span>
                <TrendingUp size={14} color="var(--neon)" />
              </div>
              <div style={{ display: "flex", gap: "0.25rem" }}>
                {("D W M All".split(" ") as ("D" | "W" | "M" | "All")[]).map((tf) => (
                  <button
                    key={tf}
                    onClick={() => setTimeframe(tf)}
                    style={{
                      background: tf === timeframe ? "var(--neon-soft)" : "transparent",
                      border: tf === timeframe ? "1px solid var(--neon)" : "1px solid var(--border)",
                      color: tf === timeframe ? "var(--neon)" : "var(--text-dim)",
                      padding: "0.15rem 0.5rem",
                      fontSize: "0.65rem",
                      borderRadius: "var(--radius-sm)",
                      cursor: "pointer",
                      boxSizing: "border-box",
                    }}
                  >
                    {tf}
                  </button>
                ))}
              </div>
            </div>
            <div style={{ height: 220 }}>
              {filteredEquityData.length === 0 ? (
                <div style={{ height: "100%", display: "flex", alignItems: "center", justifyContent: "center", flexDirection: "column", gap: "0.5rem" }}>
                  <TrendingUp size={24} color="var(--text-dim)" />
                  <span style={{ color: "var(--text-dim)", fontSize: "0.75rem" }}>Collecting equity data — updates every 5 minutes</span>
                </div>
              ) : (
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={filteredEquityData}>
                  <defs>
                    <linearGradient id="equityGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#01796f" stopOpacity={0.3} />
                      <stop offset="100%" stopColor="#01796f" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <XAxis dataKey="date" tick={false} stroke="transparent" />
                  <YAxis
                    domain={["dataMin - 20", "dataMax + 20"]}
                    tick={{ fill: "var(--text-dim)", fontSize: 11 }}
                    stroke="transparent"
                    tickFormatter={(v) => `$${v.toLocaleString()}`}
                  />
                  <Tooltip content={<CustomTooltip />} />
                  <Area
                    type="monotone" dataKey="equity" stroke="#01796f"
                    fill="url(#equityGrad)" strokeWidth={2}
                  />
                </AreaChart>
              </ResponsiveContainer>
              )}
            </div>
          </div>
        </div>

      <div className="content-grid">
        {/* Activity Feed */}
        <div className="card fade-in" style={{ gridColumn: "span 2" }}>
          <div className="card-header">
            <span className="card-title">Live Activity Feed</span>
            <Activity size={14} color="var(--neon)" />
          </div>
          <div style={{ maxHeight: 380, overflowY: "auto" }}>
            {recentActivity.length === 0 ? (
              <div style={{ padding: "2rem", textAlign: "center", color: "var(--text-dim)" }}>
                <Radio size={20} style={{ marginBottom: "0.5rem", opacity: 0.5 }} />
                <div style={{ fontSize: "0.8rem" }}>Waiting for system activity…</div>
                <div style={{ fontSize: "0.65rem", color: "var(--text-muted)", marginTop: "0.25rem" }}>
                  Activity will appear here when the backend is running
                </div>
              </div>
            ) : (
              recentActivity.map((entry) => (
                <div key={entry.id} style={{
                  display: "flex", alignItems: "flex-start", gap: "0.6rem",
                  padding: "0.5rem 0", borderBottom: "1px solid rgba(255,255,255,0.03)",
                }}>
                  <div style={{ paddingTop: "0.15rem" }}>
                    {SEVERITY_ICONS[entry.severity] || SEVERITY_ICONS.info}
                  </div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: "0.4rem" }}>
                      <span className={`badge ${EVENT_BADGE_COLOR[entry.event_type] || "muted"}`} style={{ fontSize: "0.55rem", padding: "0.12rem 0.4rem" }}>
                        {entry.component}
                      </span>
                      <span style={{ fontSize: "0.6rem", color: "var(--text-muted)" }}>
                        {timeAgo(entry.timestamp)}
                      </span>
                    </div>
                    <div style={{ fontSize: "0.75rem", fontWeight: 500, marginTop: "0.15rem", color: SEVERITY_COLORS[entry.severity] || "var(--text)" }}>
                      {entry.message}
                    </div>
                    {entry.detail && (
                      <div style={{ fontSize: "0.65rem", color: "var(--text-dim)", marginTop: "0.1rem" }}>
                        {entry.detail}
                      </div>
                    )}
                  </div>
                </div>
              ))
            )}
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
            {data.positions.filter(p => p.status === "open").length === 0 ? (
              <div style={{ padding: "1.5rem", textAlign: "center", color: "var(--text-dim)", fontSize: "0.75rem" }}>
                No open positions yet
              </div>
            ) : (
              <table className="data-table">
                <thead><tr><th>Market</th><th>Side</th><th>P&L</th><th>Status</th></tr></thead>
                <tbody>
                  {data.positions.filter(p => p.status === "open").slice(0, 5).map((pos) => (
                    <tr key={pos.id}>
                      <td style={{ maxWidth: 180, overflow: "hidden", textOverflow: "ellipsis" }}>{pos.market_title}</td>
                      <td><span className={`badge ${pos.side === "yes" ? "green" : "red"}`}>{pos.side}</span></td>
                      <td style={{ color: (pos.unrealized_pnl || 0) >= 0 ? "var(--green)" : "var(--red)" }}>
                        {formatSignedUsd(pos.unrealized_pnl)}
                      </td>
                      <td><span className={`badge ${pos.review_tier === "new" ? "blue" : pos.review_tier === "stable" ? "green" : "muted"}`}>{pos.review_tier}</span></td>
                    </tr>
                  ))}
                </tbody>
                <tfoot>
                  <tr style={{ borderTop: "1px solid var(--border)", fontWeight: "bold", fontSize: "0.7rem", backgroundColor: "rgba(255,255,255,0.01)" }}>
                    <td colSpan={2} style={{ textAlign: "right", padding: "0.8rem 1rem" }}>TOTAL</td>
                    <td style={{
                      padding: "0.8rem 1rem",
                      color: data.positions.filter(p => p.status === "open").reduce((sum, p) => sum + (p.unrealized_pnl || 0), 0) >= 0 ? "var(--green)" : "var(--red)",
                    }}>
                      {formatSignedUsd(data.positions.filter(p => p.status === "open").reduce((sum, p) => sum + (p.unrealized_pnl || 0), 0))}
                    </td>
                    <td style={{ padding: "0.8rem 1rem" }}></td>
                  </tr>
                </tfoot>
              </table>
            )}
          </div>
        </div>

        {/* Recent Triggers */}
        <div className="card fade-in">
          <div className="card-header">
            <span className="card-title">Recent Triggers</span>
            <Zap size={14} color="var(--yellow)" />
          </div>
          <div style={{ maxHeight: 280, overflowY: "auto" }}>
            {data.triggers.length === 0 ? (
              <div style={{ padding: "1.5rem", textAlign: "center", color: "var(--text-dim)", fontSize: "0.75rem" }}>
                No triggers yet — scanner will report here
              </div>
            ) : (
              data.triggers.slice(0, 5).map((t) => (
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
              ))
            )}
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
            {(data.risk?.exposure_by_category?.length || 0) > 0 ? (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={data.risk?.exposure_by_category || []} layout="vertical">
                  <XAxis type="number" tick={{ fill: "var(--text-dim)", fontSize: 10 }} stroke="transparent" tickFormatter={(v) => `$${v}`} />
                  <YAxis type="category" dataKey="category" tick={{ fill: "var(--text-dim)", fontSize: 11 }} stroke="transparent" width={80} />
                  <Tooltip content={<CustomTooltip />} />
                  <Bar dataKey="exposure_usd" fill="#01796f" radius={[0, 4, 4, 0]} barSize={16}>
                    {(data.risk?.exposure_by_category || []).map((_, i) => (
                      <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} fillOpacity={0.8} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100%", color: "var(--text-dim)", fontSize: "0.75rem" }}>
                No exposure yet — positions will appear after trades
              </div>
            )}
          </div>
        </div>

        {/* Workflows Recent */}
        <div className="card fade-in">
          <div className="card-header">
            <span className="card-title">Recent Workflows</span>
            <Zap size={14} color="var(--purple)" />
          </div>
          <div style={{ maxHeight: 220, overflowY: "auto" }}>
            {data.workflows.length === 0 ? (
              <div style={{ padding: "1.5rem", textAlign: "center", color: "var(--text-dim)", fontSize: "0.75rem" }}>
                No workflow runs yet
              </div>
            ) : (
              data.workflows.slice(0, 5).map((wf) => (
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
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
