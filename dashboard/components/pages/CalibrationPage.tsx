"use client";

import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
} from "recharts";
import { Brain } from "lucide-react";
import type { CalibrationOverview } from "@/lib/api";

const CHART_COLORS = ["#39FF14", "#00D4FF", "#9B5DE5", "#FFBE0B", "#FF6B35"];

export function CalibrationPage({ calibration }: { calibration: CalibrationOverview | null }) {
  if (!calibration) return <div style={{ color: "var(--text-dim)" }}>Loading calibration data…</div>;

  const brierData = calibration.segments
    .filter((s) => s.system_brier !== null && s.market_brier !== null)
    .map((s) => ({
      name: s.segment_name,
      system: s.system_brier,
      market: s.market_brier,
    }));

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-title">Calibration</h1>
          <div className="page-subtitle">Shadow forecasts, Brier scores, and segment progress</div>
        </div>
      </div>

      {/* Summary Stats */}
      <div className="stats-grid" style={{ marginBottom: "1rem" }}>
        <div className="card fade-in stagger-1">
          <div className="stat-label">Shadow Forecasts</div>
          <div className="stat-value" style={{ color: "var(--blue)" }}>{calibration.total_shadow_forecasts}</div>
          <div className="stat-label">{calibration.total_resolved} resolved</div>
        </div>
        <div className="card fade-in stagger-2">
          <div className="stat-label">System Brier</div>
          <div className="stat-value" style={{ color: "var(--neon)" }}>
            {calibration.overall_system_brier?.toFixed(3) || "—"}
          </div>
          <div className="stat-label">Lower is better</div>
        </div>
        <div className="card fade-in stagger-3">
          <div className="stat-label">Market Brier</div>
          <div className="stat-value" style={{ color: "var(--yellow)" }}>
            {calibration.overall_market_brier?.toFixed(3) || "—"}
          </div>
          <div className="stat-label">Benchmark</div>
        </div>
        <div className="card fade-in stagger-4">
          <div className="stat-label">System Advantage</div>
          <div className="stat-value" style={{
            color: (calibration.overall_advantage || 0) > 0 ? "var(--green)" :
              (calibration.overall_advantage || 0) < 0 ? "var(--red)" : "var(--text-dim)",
          }}>
            {calibration.overall_advantage !== null
              ? (calibration.overall_advantage > 0 ? "+" : "") + calibration.overall_advantage.toFixed(3)
              : "—"}
          </div>
          <div className="stat-label">Positive = system better</div>
        </div>
        <div className="card fade-in stagger-5">
          <div className="stat-label">Patience Budget</div>
          <div className="stat-value" style={{ color: "var(--blue)" }}>
            {calibration.patience_budget_remaining_days ?? "—"}
          </div>
          <div className="stat-label">days remaining</div>
        </div>
      </div>

      <div className="content-grid">
        {/* Brier Comparison Chart */}
        <div className="card fade-in">
          <div className="card-header">
            <span className="card-title">System vs Market Brier by Segment</span>
            <Brain size={14} color="var(--neon)" />
          </div>
          <div style={{ height: 250 }}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={brierData}>
                <XAxis dataKey="name" tick={{ fill: "var(--text-dim)", fontSize: 10 }} stroke="transparent" />
                <YAxis tick={{ fill: "var(--text-dim)", fontSize: 10 }} stroke="transparent" />
                <Tooltip
                  contentStyle={{
                    background: "var(--bg-elevated)", border: "1px solid var(--border-glow)",
                    borderRadius: "var(--radius-sm)", fontSize: "0.72rem",
                  }}
                />
                <Bar dataKey="system" name="System" fill="#39FF14" fillOpacity={0.8} radius={[4, 4, 0, 0]} barSize={20} />
                <Bar dataKey="market" name="Market" fill="#FFBE0B" fillOpacity={0.6} radius={[4, 4, 0, 0]} barSize={20} />
              </BarChart>
            </ResponsiveContainer>
          </div>
          <div style={{ display: "flex", gap: "1rem", marginTop: "0.5rem", justifyContent: "center" }}>
            <div style={{ display: "flex", alignItems: "center", gap: "0.35rem", fontSize: "0.7rem" }}>
              <div style={{ width: 10, height: 10, borderRadius: 2, background: "#39FF14" }} />
              <span style={{ color: "var(--text-dim)" }}>System</span>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: "0.35rem", fontSize: "0.7rem" }}>
              <div style={{ width: 10, height: 10, borderRadius: 2, background: "#FFBE0B" }} />
              <span style={{ color: "var(--text-dim)" }}>Market</span>
            </div>
          </div>
        </div>

        {/* Segment Progress */}
        <div className="card fade-in">
          <div className="card-header">
            <span className="card-title">Segment Accumulation Progress</span>
          </div>
          {calibration.segments.map((seg, i) => (
            <div key={seg.segment_name} style={{ marginBottom: "1rem" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.25rem" }}>
                <span style={{ fontSize: "0.78rem", fontWeight: 500, color: CHART_COLORS[i % CHART_COLORS.length] }}>
                  {seg.segment_name}
                </span>
                <span style={{ fontSize: "0.7rem", color: "var(--text-dim)" }}>
                  {seg.resolved_count} / {seg.required_count}
                </span>
              </div>
              <div className="progress-track">
                <div
                  className="progress-fill"
                  style={{
                    width: `${Math.min((seg.resolved_count / seg.required_count) * 100, 100)}%`,
                    background: CHART_COLORS[i % CHART_COLORS.length],
                    boxShadow: `0 0 8px ${CHART_COLORS[i % CHART_COLORS.length]}40`,
                  }}
                />
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", marginTop: "0.15rem" }}>
                <span className={`badge ${seg.status === "reliable" ? "green" : seg.status === "preliminary" ? "yellow" : "muted"}`}>
                  {seg.status}
                </span>
                <span style={{ fontSize: "0.65rem", color: "var(--text-dim)" }}>
                  {seg.advantage !== null
                    ? `Advantage: ${seg.advantage > 0 ? "+" : ""}${seg.advantage.toFixed(3)}`
                    : ""}
                </span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
