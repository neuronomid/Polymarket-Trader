"use client";

import { HeartPulse, Radio, UserX } from "lucide-react";
import type { SystemHealthOverview, ScannerHealth, AbsenceStatus } from "@/lib/api";

const statusColors: Record<string, string> = {
  healthy: "var(--green)",
  warning: "var(--yellow)",
  degraded: "var(--orange)",
  critical: "var(--red)",
  down: "var(--red)",
};

const statusDotClass: Record<string, string> = {
  healthy: "live",
  warning: "warning",
  degraded: "degraded",
  critical: "stopped",
  down: "stopped",
};

export function SystemPage({ health, scanner, absence }: {
  health: SystemHealthOverview | null;
  scanner: ScannerHealth | null;
  absence: AbsenceStatus | null;
}) {
  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-title">System Health</h1>
          <div className="page-subtitle">Infrastructure, scanner status, and operator presence</div>
        </div>
        {health && (
          <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
            <span className={`status-dot ${statusDotClass[health.overall_status] || "live"}`} />
            <span style={{ fontSize: "0.8rem", fontWeight: 700, color: statusColors[health.overall_status] || "var(--text)", textTransform: "uppercase" }}>
              {health.overall_status}
            </span>
          </div>
        )}
      </div>

      <div className="content-grid three">
        {/* Component Health */}
        <div className="card fade-in" style={{ gridColumn: "span 2" }}>
          <div className="card-header">
            <span className="card-title">Component Status</span>
            <HeartPulse size={14} color="var(--green)" />
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: "0.75rem" }}>
            {health?.components.map((c) => (
              <div key={c.component} style={{
                display: "flex", alignItems: "center", gap: "0.75rem",
                padding: "0.75rem", background: "var(--bg-elevated)", borderRadius: "var(--radius-sm)",
                border: "1px solid var(--border)",
              }}>
                <span className={`status-dot ${statusDotClass[c.status] || "live"}`} />
                <div>
                  <div style={{ fontSize: "0.78rem", fontWeight: 600 }}>{c.component}</div>
                  <div style={{ fontSize: "0.65rem", color: statusColors[c.status] || "var(--text-dim)", textTransform: "uppercase" }}>
                    {c.status}
                  </div>
                  {c.details && <div style={{ fontSize: "0.6rem", color: "var(--text-dim)", marginTop: "0.15rem" }}>{c.details}</div>}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Active Alerts */}
        <div className="card fade-in">
          <div className="card-header">
            <span className="card-title">Alerts</span>
          </div>
          <div style={{ textAlign: "center", padding: "1rem" }}>
            <div className="stat-value" style={{ color: (health?.active_alerts_count || 0) > 0 ? "var(--yellow)" : "var(--green)" }}>
              {health?.active_alerts_count || 0}
            </div>
            <div className="stat-label">Active alerts</div>
          </div>
        </div>
      </div>

      <div className="content-grid" style={{ marginTop: "1rem" }}>
        {/* Scanner Health */}
        <div className="card fade-in">
          <div className="card-header">
            <span className="card-title">Scanner Infrastructure</span>
            <Radio size={14} color={statusColors[scanner?.api_status || "healthy"]} />
          </div>
          {scanner && (
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem" }}>
              <div>
                <div className="stat-label">API Status</div>
                <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", marginTop: "0.25rem" }}>
                  <span className={`status-dot ${statusDotClass[scanner.api_status] || "live"}`} />
                  <span style={{ fontSize: "0.85rem", fontWeight: 600, color: statusColors[scanner.api_status] }}>
                    {scanner.api_status.toUpperCase()}
                  </span>
                </div>
              </div>
              <div>
                <div className="stat-label">Degraded Level</div>
                <div style={{
                  fontSize: "1.2rem", fontWeight: 700,
                  color: scanner.degraded_level === 0 ? "var(--green)" : scanner.degraded_level <= 1 ? "var(--yellow)" : "var(--red)",
                }}>
                  {scanner.degraded_level}
                </div>
              </div>
              <div>
                <div className="stat-label">Cache Entries</div>
                <div style={{ fontSize: "1.2rem", fontWeight: 700, color: "var(--blue)" }}>{scanner.cache_entries_count}</div>
              </div>
              <div>
                <div className="stat-label">Cache Hit Rate</div>
                <div style={{ fontSize: "1.2rem", fontWeight: 700, color: "var(--neon)" }}>{scanner.cache_hit_rate.toFixed(1)}%</div>
              </div>
              <div>
                <div className="stat-label">Consecutive Failures</div>
                <div style={{
                  fontSize: "1.2rem", fontWeight: 700,
                  color: scanner.consecutive_failures > 0 ? "var(--red)" : "var(--green)",
                }}>
                  {scanner.consecutive_failures}
                </div>
              </div>
              <div>
                <div className="stat-label">Uptime</div>
                <div style={{ fontSize: "1.2rem", fontWeight: 700, color: "var(--neon)" }}>{scanner.uptime_pct.toFixed(1)}%</div>
              </div>
            </div>
          )}
        </div>

        {/* Operator Absence */}
        <div className="card fade-in">
          <div className="card-header">
            <span className="card-title">Operator Presence</span>
            <UserX size={14} color={absence?.is_absent ? "var(--red)" : "var(--green)"} />
          </div>
          {absence && (
            <div>
              <div style={{ display: "flex", alignItems: "center", gap: "0.75rem", marginBottom: "1rem" }}>
                <span className={`status-dot ${absence.is_absent ? "stopped" : "live"}`} style={{ width: 12, height: 12 }} />
                <div>
                  <div style={{ fontSize: "0.85rem", fontWeight: 700, color: absence.is_absent ? "var(--red)" : "var(--green)" }}>
                    {absence.is_absent ? `ABSENT — Level ${absence.absence_level}` : "PRESENT"}
                  </div>
                  <div style={{ fontSize: "0.7rem", color: "var(--text-dim)" }}>
                    Last activity: {absence.hours_since_activity < 1
                      ? `${Math.round(absence.hours_since_activity * 60)} min ago`
                      : `${absence.hours_since_activity.toFixed(1)}h ago`
                    }
                  </div>
                </div>
              </div>
              {absence.restrictions_active.length > 0 && (
                <div style={{ marginBottom: "0.75rem" }}>
                  <div className="stat-label" style={{ marginBottom: "0.35rem" }}>Active Restrictions</div>
                  {absence.restrictions_active.map((r, i) => (
                    <span key={i} className="badge red" style={{ marginRight: "0.35rem", marginBottom: "0.25rem" }}>
                      {r}
                    </span>
                  ))}
                </div>
              )}
              <div style={{ display: "flex", gap: "1.5rem" }}>
                <div>
                  <div className="stat-label">Autonomous Actions</div>
                  <div style={{ fontSize: "1.1rem", fontWeight: 700, color: absence.autonomous_actions_count > 0 ? "var(--yellow)" : "var(--text-dim)" }}>
                    {absence.autonomous_actions_count}
                  </div>
                </div>
                <div>
                  <div className="stat-label">Absence Level</div>
                  <div style={{ fontSize: "1.1rem", fontWeight: 700, color: absence.absence_level > 0 ? "var(--red)" : "var(--green)" }}>
                    {absence.absence_level}
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
