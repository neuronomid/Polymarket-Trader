"use client";

import { Play, Square } from "lucide-react";
import type { AgentStatus } from "@/lib/api";

const tierColors: Record<string, string> = {
  A: "var(--yellow)",
  B: "var(--blue)",
  C: "var(--purple)",
  D: "var(--green)",
};

const tierLabels: Record<string, string> = {
  A: "Premium (Opus)",
  B: "Workhorse (Sonnet)",
  C: "Utility (GPT-5.4)",
  D: "Deterministic",
};

export function AgentsPage({ agents, agentsRunning, onToggle }: {
  agents: AgentStatus[];
  agentsRunning: boolean;
  onToggle: () => void;
}) {
  const byTier = agents.reduce<Record<string, AgentStatus[]>>((acc, a) => {
    if (!acc[a.tier]) acc[a.tier] = [];
    acc[a.tier].push(a);
    return acc;
  }, {});

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-title">Agents</h1>
          <div className="page-subtitle">{agents.length} registered agents across 4 tiers</div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: "1rem" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
            <span className={`status-dot ${agentsRunning ? "live" : "stopped"}`} />
            <span style={{ fontSize: "0.78rem", fontWeight: 600, color: agentsRunning ? "var(--green)" : "var(--red)" }}>
              {agentsRunning ? "AGENTS LIVE" : "AGENTS STOPPED"}
            </span>
          </div>
          <button className={`btn-neon ${agentsRunning ? "danger" : ""}`} onClick={onToggle}>
            {agentsRunning ? <><Square size={14} /> Stop All</> : <><Play size={14} /> Start All</>}
          </button>
        </div>
      </div>

      {["A", "B", "C", "D"].map((tier) => (
        <div key={tier} style={{ marginBottom: "1.25rem" }}>
          <div style={{
            display: "flex", alignItems: "center", gap: "0.5rem",
            marginBottom: "0.5rem", padding: "0.25rem 0",
          }}>
            <span style={{
              fontSize: "0.65rem", fontWeight: 700, padding: "0.15rem 0.5rem",
              borderRadius: "var(--radius-sm)", border: `1px solid ${tierColors[tier]}`,
              color: tierColors[tier],
            }}>
              TIER {tier}
            </span>
            <span style={{ fontSize: "0.72rem", color: "var(--text-dim)" }}>
              {tierLabels[tier]}
            </span>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: "0.75rem" }}>
            {(byTier[tier] || []).map((agent) => (
              <div key={agent.role} className="card" style={{ padding: "0.75rem 1rem" }}>
                <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", marginBottom: "0.5rem" }}>
                  <span className={`status-dot ${agent.is_active ? "live" : "stopped"}`} />
                  <span style={{ fontSize: "0.78rem", fontWeight: 600 }}>{agent.name}</span>
                </div>
                <div style={{ display: "flex", gap: "1.25rem", fontSize: "0.7rem" }}>
                  <div>
                    <span style={{ color: "var(--text-dim)" }}>Invocations: </span>
                    <span style={{ color: "var(--text)", fontWeight: 500 }}>{agent.total_invocations.toLocaleString()}</span>
                  </div>
                  <div>
                    <span style={{ color: "var(--text-dim)" }}>Cost: </span>
                    <span style={{ color: agent.total_cost_usd > 0 ? tierColors[tier] : "var(--text-dim)", fontWeight: 500 }}>
                      ${agent.total_cost_usd.toFixed(2)}
                    </span>
                  </div>
                </div>
                {agent.last_invoked && (
                  <div style={{ fontSize: "0.65rem", color: "var(--text-muted)", marginTop: "0.35rem" }}>
                    Last: {new Date(agent.last_invoked).toLocaleString()}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
