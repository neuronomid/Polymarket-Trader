"use client";

import { Zap } from "lucide-react";
import type { WorkflowRunSummary, TriggerEventItem } from "@/lib/api";

export function WorkflowsPage({ workflows, triggers }: { workflows: WorkflowRunSummary[]; triggers: TriggerEventItem[] }) {
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
            <thead><tr><th>Type</th><th>Status</th><th>Candidates</th><th>Cost</th><th>Duration</th></tr></thead>
            <tbody>
              {workflows.map((wf) => {
                const duration = wf.started_at && wf.completed_at
                  ? Math.round((new Date(wf.completed_at).getTime() - new Date(wf.started_at).getTime()) / 1000)
                  : null;
                return (
                  <tr key={wf.id}>
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
            <thead><tr><th>Level</th><th>Class</th><th>Market</th><th>Reason</th><th>Source</th></tr></thead>
            <tbody>
              {triggers.map((t) => (
                <tr key={t.id}>
                  <td>
                    <span className={`badge ${t.trigger_level === "D" ? "red" : t.trigger_level === "C" ? "red" : t.trigger_level === "B" ? "yellow" : "muted"}`}>
                      {t.trigger_level}
                    </span>
                  </td>
                  <td style={{ fontSize: "0.72rem" }}>{t.trigger_class.replace(/_/g, " ")}</td>
                  <td style={{ maxWidth: 160, overflow: "hidden", textOverflow: "ellipsis" }}>
                    {t.market_title || t.market_id || "—"}
                  </td>
                  <td style={{ maxWidth: 180, overflow: "hidden", textOverflow: "ellipsis", color: "var(--text-dim)" }}>
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
