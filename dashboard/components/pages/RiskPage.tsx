"use client";

import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from "recharts";
import { Shield, AlertTriangle, TrendingDown } from "lucide-react";
import type { RiskBoard } from "@/lib/api";

const CHART_COLORS = ["#39FF14", "#00D4FF", "#9B5DE5", "#FFBE0B", "#FF6B35"];

const CustomTooltip = ({ active, payload }: any) => {
  if (!active || !payload?.length) return null;
  return (
    <div style={{
      background: "var(--bg-elevated)", border: "1px solid var(--border-glow)",
      borderRadius: "var(--radius-sm)", padding: "0.5rem 0.75rem", fontSize: "0.72rem",
    }}>
      <div style={{ fontWeight: 600 }}>{payload[0]?.payload?.category}</div>
      <div style={{ color: "var(--neon)" }}>${payload[0]?.value?.toFixed(2)}</div>
    </div>
  );
};

function getDrawdownColor(pct: number, thresholds: { soft: number; risk: number; disabled: number; kill: number }) {
  if (pct >= thresholds.kill) return "var(--red)";
  if (pct >= thresholds.disabled) return "#FF3B5C";
  if (pct >= thresholds.risk) return "var(--orange)";
  if (pct >= thresholds.soft) return "var(--yellow)";
  return "var(--green)";
}

export function RiskPage({ risk }: { risk: RiskBoard | null }) {
  if (!risk) return <div style={{ color: "var(--text-dim)" }}>Loading risk data…</div>;

  const dd = risk.drawdown_ladder;
  const ddColor = getDrawdownColor(dd.current_drawdown_pct, {
    soft: dd.soft_warning_pct, risk: dd.risk_reduction_pct,
    disabled: dd.entries_disabled_pct, kill: dd.hard_kill_switch_pct,
  });

  const ddPctOfMax = Math.min((dd.current_drawdown_pct / dd.hard_kill_switch_pct) * 100, 100);

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-title">Risk Board</h1>
          <div className="page-subtitle">Drawdown defense, exposure limits, and capital protection</div>
        </div>
      </div>

      {/* Drawdown Ladder */}
      <div className="card fade-in stagger-1" style={{ marginBottom: "1rem" }}>
        <div className="card-header">
          <span className="card-title">Drawdown Defense Ladder</span>
          <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
            <span className={`badge ${dd.current_level === "normal" ? "green" : dd.current_level === "soft_warning" ? "yellow" : "red"}`}>
              {dd.current_level.replace(/_/g, " ")}
            </span>
          </div>
        </div>

        <div style={{ display: "flex", alignItems: "baseline", gap: "0.75rem", marginBottom: "0.5rem" }}>
          <span className="stat-value" style={{ color: ddColor }}>{dd.current_drawdown_pct.toFixed(1)}%</span>
          <span className="stat-label">current daily drawdown</span>
        </div>

        {/* Visual Ladder */}
        <div className="ladder-track">
          <div className="ladder-fill" style={{
            width: `${ddPctOfMax}%`,
            background: `linear-gradient(90deg, var(--green) 0%, var(--yellow) 40%, var(--orange) 70%, var(--red) 100%)`,
            boxShadow: `0 0 12px ${ddColor}`,
          }} />
          {/* Threshold markers */}
          {[
            { pct: dd.soft_warning_pct, label: `${dd.soft_warning_pct}% Warn`, color: "var(--yellow)" },
            { pct: dd.risk_reduction_pct, label: `${dd.risk_reduction_pct}% Reduce`, color: "var(--orange)" },
            { pct: dd.entries_disabled_pct, label: `${dd.entries_disabled_pct}% Disable`, color: "#FF3B5C" },
            { pct: dd.hard_kill_switch_pct, label: `${dd.hard_kill_switch_pct}% Kill`, color: "var(--red)" },
          ].map((m) => (
            <div key={m.label} className="ladder-marker" style={{
              left: `${(m.pct / dd.hard_kill_switch_pct) * 100}%`,
              background: m.color,
            }}>
              <div className="ladder-marker-label">{m.label}</div>
            </div>
          ))}
        </div>
      </div>

      <div className="content-grid">
        {/* Exposure Stats */}
        <div className="card fade-in stagger-2">
          <div className="card-header">
            <span className="card-title">Exposure Summary</span>
            <Shield size={14} color="var(--blue)" />
          </div>
          <div className="stats-grid" style={{ gridTemplateColumns: "repeat(2, 1fr)" }}>
            <div>
              <div className="stat-label">Total Exposure</div>
              <div style={{ fontSize: "1.2rem", fontWeight: 700, color: "var(--blue)" }}>
                ${risk.total_exposure_usd.toLocaleString()}
              </div>
              <div style={{ marginTop: "0.5rem" }}>
                <div className="progress-track">
                  <div className="progress-fill blue" style={{ width: `${(risk.total_exposure_usd / risk.max_exposure_usd) * 100}%` }} />
                </div>
                <div className="stat-label" style={{ marginTop: "0.25rem" }}>of ${risk.max_exposure_usd.toLocaleString()} max</div>
              </div>
            </div>
            <div>
              <div className="stat-label">Daily Deployment</div>
              <div style={{ fontSize: "1.2rem", fontWeight: 700, color: "var(--purple)" }}>
                {risk.daily_deployment_used_pct.toFixed(1)}%
              </div>
              <div style={{ marginTop: "0.5rem" }}>
                <div className="progress-track">
                  <div className="progress-fill green" style={{ width: `${(risk.daily_deployment_used_pct / (risk.max_daily_deployment_pct * 100)) * 100}%` }} />
                </div>
                <div className="stat-label" style={{ marginTop: "0.25rem" }}>of {(risk.max_daily_deployment_pct * 100).toFixed(0)}% max</div>
              </div>
            </div>
          </div>
          <div style={{ marginTop: "1rem" }}>
            <div className="stat-label">Correlation Groups: <span style={{ color: "var(--text)" }}>{risk.correlation_groups_count}</span></div>
          </div>
        </div>

        {/* Exposure by Category Chart */}
        <div className="card fade-in stagger-3">
          <div className="card-header">
            <span className="card-title">Exposure by Category</span>
          </div>
          <div style={{ height: 240 }}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={risk.exposure_by_category} layout="vertical">
                <XAxis type="number" tick={{ fill: "var(--text-dim)", fontSize: 10 }} stroke="transparent" tickFormatter={(v) => `$${v}`} />
                <YAxis type="category" dataKey="category" tick={{ fill: "var(--text-dim)", fontSize: 11 }} stroke="transparent" width={85} />
                <Tooltip content={<CustomTooltip />} />
                <Bar dataKey="exposure_usd" radius={[0, 4, 4, 0]} barSize={18}>
                  {risk.exposure_by_category.map((_, i) => (
                    <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} fillOpacity={0.8} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      {/* Category Exposure Table */}
      <div className="card fade-in" style={{ marginTop: "1rem" }}>
        <div className="card-header">
          <span className="card-title">Category Exposure Detail</span>
        </div>
        <table className="data-table">
          <thead>
            <tr><th>Category</th><th>Exposure</th><th>Cap</th><th>Usage</th><th>Positions</th></tr>
          </thead>
          <tbody>
            {risk.exposure_by_category.map((e, i) => (
              <tr key={e.category}>
                <td style={{ fontWeight: 500 }}>{e.category}</td>
                <td>${e.exposure_usd.toLocaleString()}</td>
                <td style={{ color: "var(--text-dim)" }}>${e.cap_usd.toLocaleString()}</td>
                <td>
                  <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                    <div className="progress-track" style={{ flex: 1 }}>
                      <div className="progress-fill green" style={{
                        width: `${e.pct_of_cap * 100}%`,
                        background: CHART_COLORS[i % CHART_COLORS.length],
                        boxShadow: "none",
                      }} />
                    </div>
                    <span style={{ fontSize: "0.7rem", color: "var(--text-dim)", minWidth: 35 }}>
                      {(e.pct_of_cap * 100).toFixed(1)}%
                    </span>
                  </div>
                </td>
                <td>{e.positions_count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
