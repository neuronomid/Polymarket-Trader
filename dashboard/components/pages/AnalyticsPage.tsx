"use client";

import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell,
} from "recharts";
import { BarChart3, DollarSign, Eye, AlertTriangle } from "lucide-react";
import type { CategoryPerformanceEntry, CostMetrics, BiasAuditOverview, ViabilityOverview } from "@/lib/api";

const CHART_COLORS = ["#39FF14", "#00D4FF", "#9B5DE5", "#FFBE0B", "#FF6B35", "#FF3B5C"];

const CustomTooltip = ({ active, payload }: any) => {
  if (!active || !payload?.length) return null;
  return (
    <div style={{
      background: "var(--bg-elevated)", border: "1px solid var(--border-glow)",
      borderRadius: "var(--radius-sm)", padding: "0.5rem 0.75rem", fontSize: "0.72rem",
    }}>
      <div style={{ fontWeight: 600 }}>{payload[0]?.payload?.category}</div>
      {payload.map((p: any, i: number) => (
        <div key={i} style={{ color: p.color || "var(--text)" }}>
          {p.name}: {typeof p.value === "number" ? (p.name.includes("pnl") || p.name.includes("cost") ? `$${p.value.toFixed(2)}` : p.value.toFixed(3)) : p.value}
        </div>
      ))}
    </div>
  );
};

export function AnalyticsPage({ categories, cost, bias, viability }: {
  categories: CategoryPerformanceEntry[];
  cost: CostMetrics | null;
  bias: BiasAuditOverview | null;
  viability: ViabilityOverview | null;
}) {
  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-title">Analytics</h1>
          <div className="page-subtitle">Category performance, cost analysis, bias audit, and viability</div>
        </div>
      </div>

      {/* Category Performance Table */}
      <div className="card fade-in" style={{ marginBottom: "1rem" }}>
        <div className="card-header">
          <span className="card-title">Category Performance Ledger</span>
          <BarChart3 size={14} color="var(--neon)" />
        </div>
        <div style={{ overflowX: "auto" }}>
          <table className="data-table">
            <thead>
              <tr>
                <th>Category</th><th>Trades</th><th>Win Rate</th><th>Gross P&L</th>
                <th>Net P&L</th><th>Cost</th><th>Avg Edge</th><th>Brier</th>
                <th>vs Market</th><th>No-Trade Rate</th>
              </tr>
            </thead>
            <tbody>
              {categories.map((c, i) => (
                <tr key={c.category}>
                  <td style={{ fontWeight: 500, color: CHART_COLORS[i % CHART_COLORS.length] }}>{c.category}</td>
                  <td>{c.total_trades}</td>
                  <td style={{ color: c.win_rate >= 0.5 ? "var(--green)" : "var(--red)" }}>
                    {(c.win_rate * 100).toFixed(0)}%
                  </td>
                  <td style={{ color: c.gross_pnl_usd >= 0 ? "var(--green)" : "var(--red)" }}>
                    ${c.gross_pnl_usd.toFixed(2)}
                  </td>
                  <td style={{ color: c.net_pnl_usd >= 0 ? "var(--green)" : "var(--red)", fontWeight: 600 }}>
                    ${c.net_pnl_usd.toFixed(2)}
                  </td>
                  <td style={{ color: "var(--purple)" }}>${c.inference_cost_usd.toFixed(2)}</td>
                  <td>{(c.avg_edge * 100).toFixed(1)}%</td>
                  <td>{c.brier_score?.toFixed(3) || "—"}</td>
                  <td style={{ color: (c.system_vs_market_brier || 0) > 0 ? "var(--green)" : "var(--red)" }}>
                    {c.system_vs_market_brier !== null ? (c.system_vs_market_brier > 0 ? "+" : "") + c.system_vs_market_brier.toFixed(3) : "—"}
                  </td>
                  <td>{(c.no_trade_rate * 100).toFixed(0)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Net P&L Chart */}
      <div className="content-grid">
        <div className="card fade-in">
          <div className="card-header">
            <span className="card-title">Net P&L by Category</span>
          </div>
          <div style={{ height: 220 }}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={categories}>
                <XAxis dataKey="category" tick={{ fill: "var(--text-dim)", fontSize: 10 }} stroke="transparent" />
                <YAxis tick={{ fill: "var(--text-dim)", fontSize: 10 }} stroke="transparent" tickFormatter={(v) => `$${v}`} />
                <Tooltip content={<CustomTooltip />} />
                <Bar dataKey="net_pnl_usd" radius={[4, 4, 0, 0]} barSize={28}>
                  {categories.map((c, i) => (
                    <Cell key={i} fill={c.net_pnl_usd >= 0 ? "#39FF14" : "#FF3B5C"} fillOpacity={0.8} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Cost Metrics */}
        <div className="card fade-in">
          <div className="card-header">
            <span className="card-title">Cost Governor</span>
            <DollarSign size={14} color="var(--purple)" />
          </div>
          {cost && (
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem" }}>
              <div>
                <div className="stat-label">Daily Spend</div>
                <div style={{ fontSize: "1.1rem", fontWeight: 700, color: "var(--purple)" }}>${cost.daily_spend_usd.toFixed(2)}</div>
                <div className="progress-track" style={{ marginTop: "0.5rem" }}>
                  <div className="progress-fill blue" style={{ width: `${(cost.daily_spend_usd / cost.daily_budget_usd) * 100}%` }} />
                </div>
                <div className="stat-label" style={{ marginTop: "0.2rem" }}>of ${cost.daily_budget_usd} budget</div>
              </div>
              <div>
                <div className="stat-label">Lifetime Budget</div>
                <div style={{ fontSize: "1.1rem", fontWeight: 700, color: "var(--blue)" }}>{cost.lifetime_budget_pct.toFixed(1)}%</div>
                <div className="progress-track" style={{ marginTop: "0.5rem" }}>
                  <div className="progress-fill green" style={{ width: `${cost.lifetime_budget_pct}%` }} />
                </div>
                <div className="stat-label" style={{ marginTop: "0.2rem" }}>${cost.lifetime_spend_usd.toFixed(0)} / ${cost.lifetime_budget_usd.toLocaleString()}</div>
              </div>
              <div>
                <div className="stat-label">Selectivity Ratio</div>
                <div style={{ fontSize: "1.1rem", fontWeight: 700, color: cost.selectivity_ratio < cost.selectivity_target ? "var(--green)" : "var(--yellow)" }}>
                  {(cost.selectivity_ratio * 100).toFixed(1)}%
                </div>
                <div className="stat-label">target: {(cost.selectivity_target * 100).toFixed(0)}%</div>
              </div>
              <div>
                <div className="stat-label">Opus Today</div>
                <div style={{ fontSize: "1.1rem", fontWeight: 700, color: "var(--yellow)" }}>${cost.opus_spend_today_usd.toFixed(2)}</div>
                <div className="progress-track" style={{ marginTop: "0.5rem" }}>
                  <div className="progress-fill yellow" style={{ width: `${(cost.opus_spend_today_usd / cost.opus_budget_usd) * 100}%` }} />
                </div>
                <div className="stat-label" style={{ marginTop: "0.2rem" }}>of ${cost.opus_budget_usd} budget</div>
              </div>
            </div>
          )}
        </div>
      </div>

      <div className="content-grid" style={{ marginTop: "1rem" }}>
        {/* Bias Audit */}
        <div className="card fade-in">
          <div className="card-header">
            <span className="card-title">Bias Audit</span>
            <AlertTriangle size={14} color="var(--yellow)" />
          </div>
          {bias && (
            <div>
              <div style={{ display: "flex", gap: "1rem", marginBottom: "1rem" }}>
                <div>
                  <div className="stat-label">Active Patterns</div>
                  <div style={{ fontSize: "1.1rem", fontWeight: 700, color: bias.active_patterns.length > 0 ? "var(--yellow)" : "var(--green)" }}>
                    {bias.active_patterns.length}
                  </div>
                </div>
                <div>
                  <div className="stat-label">Persistent</div>
                  <div style={{ fontSize: "1.1rem", fontWeight: 700, color: bias.persistent_pattern_count > 0 ? "var(--red)" : "var(--green)" }}>
                    {bias.persistent_pattern_count}
                  </div>
                </div>
                <div>
                  <div className="stat-label">Resolved</div>
                  <div style={{ fontSize: "1.1rem", fontWeight: 700, color: "var(--green)" }}>
                    {bias.resolved_pattern_count}
                  </div>
                </div>
              </div>
              {bias.active_patterns.map((p, i) => (
                <div key={i} style={{ padding: "0.5rem", borderBottom: "1px solid var(--border)" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                    <span className={`badge ${p.is_persistent ? "red" : "yellow"}`}>{p.pattern_type.replace(/_/g, " ")}</span>
                    <span style={{ fontSize: "0.65rem", color: "var(--text-dim)" }}>Week {p.weeks_active}</span>
                  </div>
                  <div style={{ fontSize: "0.72rem", color: "var(--text-dim)", marginTop: "0.25rem" }}>{p.description}</div>
                </div>
              ))}
              {bias.active_patterns.length === 0 && (
                <div style={{ color: "var(--green)", fontSize: "0.78rem" }}>✓ No active bias patterns detected</div>
              )}
            </div>
          )}
        </div>

        {/* Viability */}
        <div className="card fade-in">
          <div className="card-header">
            <span className="card-title">Strategy Viability</span>
            <Eye size={14} color="var(--blue)" />
          </div>
          {viability && (
            <div>
              <div style={{ display: "flex", alignItems: "center", gap: "0.75rem", marginBottom: "1rem" }}>
                <span className={`badge ${viability.current_signal === "positive" ? "green" : viability.current_signal === "neutral" ? "blue" : viability.current_signal === "negative" ? "yellow" : "muted"}`}>
                  {viability.current_signal}
                </span>
                <span style={{ fontSize: "0.72rem", color: "var(--text-dim)" }}>
                  Patience: {viability.patience_budget_remaining_days ?? "—"} days remaining
                </span>
              </div>
              <div style={{ marginBottom: "1rem" }}>
                <div className="stat-label">Lifetime Budget Used</div>
                <div className="progress-track" style={{ marginTop: "0.25rem" }}>
                  <div className="progress-fill blue" style={{ width: `${viability.lifetime_budget_pct}%` }} />
                </div>
                <div className="stat-label" style={{ marginTop: "0.15rem" }}>{viability.lifetime_budget_pct.toFixed(1)}%</div>
              </div>
              {viability.checkpoints.map((cp, i) => (
                <div key={i} style={{ padding: "0.5rem 0", borderBottom: "1px solid var(--border)" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                    <span className={`badge ${cp.signal === "positive" ? "green" : cp.signal === "neutral" ? "blue" : "yellow"}`}>
                      Week {cp.checkpoint_week}
                    </span>
                    <span style={{ fontSize: "0.7rem", color: "var(--text-dim)" }}>{cp.resolved_count} resolved</span>
                  </div>
                  {cp.recommendation && (
                    <div style={{ fontSize: "0.7rem", color: "var(--text-dim)", marginTop: "0.25rem" }}>{cp.recommendation}</div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
