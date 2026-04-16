"use client";

import { Zap } from "lucide-react";
import type { WorkflowRunSummary, TriggerEventItem } from "@/lib/api";

const TABLE_EVENT_LIMIT = 10;
const WORKFLOW_TIME_ZONE = "America/Edmonton";

function parseApiDate(value: string | null): Date | null {
  if (!value) return null;

  // The dashboard API currently emits UTC datetimes without a timezone suffix.
  // Treat naive timestamps as UTC so the browser does not interpret them as local time.
  const normalized = /[zZ]|[+-]\d{2}:\d{2}$/.test(value) ? value : `${value}Z`;
  const date = new Date(normalized);

  return Number.isNaN(date.getTime()) ? null : date;
}

function toTimestamp(value: string | null): number {
  const date = parseApiDate(value);
  return date ? date.getTime() : 0;
}

function formatEventTime(value: string | null): string {
  if (!value) return "—";

  const date = parseApiDate(value);
  if (!date) return "—";

  return date.toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: WORKFLOW_TIME_ZONE,
  });
}

function formatCategory(value: string | null): string {
  if (!value) return "—";

  return value
    .replace(/_/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

export function WorkflowsPage({ workflows, triggers }: { workflows: WorkflowRunSummary[]; triggers: TriggerEventItem[] }) {
  const recentWorkflows = [...workflows]
    .sort((left, right) => toTimestamp(right.completed_at ?? right.started_at) - toTimestamp(left.completed_at ?? left.started_at))
    .slice(0, TABLE_EVENT_LIMIT);

  const recentTriggers = [...triggers]
    .sort((left, right) => toTimestamp(right.timestamp) - toTimestamp(left.timestamp))
    .slice(0, TABLE_EVENT_LIMIT);

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-title">Workflows & Triggers</h1>
          <div className="page-subtitle">Recent workflow runs and scanner trigger events</div>
        </div>
      </div>

      <div className="content-grid">
        {/* Workflows */}
        <div className="card fade-in">
          <div className="card-header">
            <span className="card-title">Workflow Runs</span>
            <Zap size={14} color="var(--purple)" />
          </div>
          <table className="data-table">
            <thead><tr><th>Time</th><th>Type</th><th>Status</th><th>Candidates</th><th>Cost</th><th>Duration</th></tr></thead>
            <tbody>
              {recentWorkflows.map((wf) => {
                const duration = wf.started_at && wf.completed_at
                  ? Math.round((new Date(wf.completed_at).getTime() - new Date(wf.started_at).getTime()) / 1000)
                  : null;
                const eventTime = wf.completed_at ?? wf.started_at;

                return (
                  <tr key={wf.id}>
                    <td style={{ color: "var(--text-dim)", fontVariantNumeric: "tabular-nums" }}>
                      {formatEventTime(eventTime)}
                    </td>
                    <td style={{ fontWeight: 500 }}>{wf.workflow_type.replace(/_/g, " ")}</td>
                    <td>
                      <span className={`badge ${wf.status === "completed" ? "green" : wf.status === "running" ? "blue" : "red"}`}>
                        {wf.status}
                      </span>
                    </td>
                    <td>
                      {wf.candidates_reviewed > 0
                        ? `${wf.candidates_reviewed} → ${wf.candidates_accepted}`
                        : "—"}
                    </td>
                    <td style={{ color: wf.cost_usd > 0 ? "var(--purple)" : "var(--text-dim)" }}>
                      ${wf.cost_usd.toFixed(2)}
                    </td>
                    <td style={{ color: "var(--text-dim)" }}>
                      {duration !== null ? `${duration}s` : "running…"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {/* Triggers */}
        <div className="card fade-in">
          <div className="card-header">
            <span className="card-title">Trigger Events</span>
            <Zap size={14} color="var(--yellow)" />
          </div>
          <table className="data-table">
            <thead><tr><th>Time</th><th>Level</th><th>Class</th><th>Market</th><th>Category</th><th>Reason</th><th>Source</th></tr></thead>
            <tbody>
              {recentTriggers.map((t) => (
                <tr key={t.id}>
                  <td style={{ color: "var(--text-dim)", fontVariantNumeric: "tabular-nums" }}>
                    {formatEventTime(t.timestamp)}
                  </td>
                  <td>
                    <span className={`badge ${t.trigger_level === "D" ? "red" : t.trigger_level === "C" ? "red" : t.trigger_level === "B" ? "yellow" : "muted"}`}>
                      {t.trigger_level}
                    </span>
                  </td>
                  <td style={{ fontSize: "0.72rem" }}>{t.trigger_class.replace(/_/g, " ")}</td>
                  <td style={{ maxWidth: 150, overflow: "hidden", textOverflow: "ellipsis" }}>
                    {t.market_title || t.market_id || "—"}
                  </td>
                  <td>
                    <span className="badge muted" style={{ fontSize: "0.6rem" }}>
                      {formatCategory(t.category)}
                    </span>
                  </td>
                  <td style={{ maxWidth: 160, overflow: "hidden", textOverflow: "ellipsis", color: "var(--text-dim)" }}>
                    {t.reason}
                  </td>
                  <td><span className={`badge ${t.data_source === "live" ? "green" : "yellow"}`}>{t.data_source}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
