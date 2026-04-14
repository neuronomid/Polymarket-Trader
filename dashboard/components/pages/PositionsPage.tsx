"use client";

import { Target} from "lucide-react";
import type { PositionSummary } from "@/lib/api";

export function PositionsPage({ positions }: { positions: PositionSummary[] }) {
  const open = positions.filter((p) => p.status === "open");
  const closed = positions.filter((p) => p.status === "closed");

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-title">Positions</h1>
          <div className="page-subtitle">{open.length} open · {closed.length} closed</div>
        </div>
      </div>

      <div className="card fade-in">
        <div className="card-header">
          <span className="card-title">Open Positions</span>
          <Target size={14} color="var(--blue)" />
        </div>
        <div style={{ overflowX: "auto" }}>
          <table className="data-table">
            <thead>
              <tr>
                <th>Market</th>
                <th>Category</th>
                <th>Side</th>
                <th>Entry</th>
                <th>Current</th>
                <th>Size</th>
                <th>P&L</th>
                <th>Review Tier</th>
                <th>Entered</th>
              </tr>
            </thead>
            <tbody>
              {open.map((pos) => (
                <tr key={pos.id}>
                  <td style={{ maxWidth: 250, overflow: "hidden", textOverflow: "ellipsis" }}>
                    {pos.market_title}
                  </td>
                  <td>
                    <span className="badge blue">{pos.category || "—"}</span>
                  </td>
                  <td>
                    <span className={`badge ${pos.side === "yes" ? "green" : "red"}`}>
                      {pos.side.toUpperCase()}
                    </span>
                  </td>
                  <td>${pos.entry_price.toFixed(2)}</td>
                  <td style={{ color: (pos.current_price || 0) > pos.entry_price ? "var(--green)" : (pos.current_price || 0) < pos.entry_price ? "var(--red)" : "var(--text)" }}>
                    ${(pos.current_price || 0).toFixed(2)}
                  </td>
                  <td>${pos.size.toFixed(0)}</td>
                  <td style={{
                    color: (pos.unrealized_pnl || 0) >= 0 ? "var(--green)" : "var(--red)",
                    fontWeight: 600,
                  }}>
                    {(pos.unrealized_pnl || 0) >= 0 ? "+" : ""}${(pos.unrealized_pnl || 0).toFixed(2)}
                  </td>
                  <td>
                    <span className={`badge ${pos.review_tier === "new" ? "blue" : pos.review_tier === "stable" ? "green" : "muted"}`}>
                      {pos.review_tier}
                    </span>
                  </td>
                  <td style={{ color: "var(--text-dim)", fontSize: "0.7rem" }}>
                    {pos.entered_at ? new Date(pos.entered_at).toLocaleDateString() : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {open.length === 0 && (
          <div style={{ padding: "2rem", textAlign: "center", color: "var(--text-dim)" }}>
            No open positions
          </div>
        )}
      </div>
    </div>
  );
}
