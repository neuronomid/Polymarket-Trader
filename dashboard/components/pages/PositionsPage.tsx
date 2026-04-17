"use client";

import { Target} from "lucide-react";
import type { PositionSummary } from "@/lib/api";

function formatPrice(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  const decimals = Math.abs(value) < 1 ? 4 : 2;
  return `$${value.toFixed(decimals)}`;
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
                  <td>{formatPrice(pos.entry_price)}</td>
                  <td style={{ color: pos.current_price == null ? "var(--text)" : pos.current_price > pos.entry_price ? "var(--green)" : pos.current_price < pos.entry_price ? "var(--red)" : "var(--text)" }}>
                    {formatPrice(pos.current_price)}
                  </td>
                  <td>${pos.size.toFixed(2)}</td>
                  <td style={{
                    color: (pos.unrealized_pnl || 0) >= 0 ? "var(--green)" : "var(--red)",
                    fontWeight: 600,
                  }}>
                    {formatSignedUsd(pos.unrealized_pnl)}
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
            {open.length > 0 && (
              <tfoot>
                <tr style={{ borderTop: "2px solid var(--border)", fontWeight: "bold", backgroundColor: "rgba(255,255,255,0.02)" }}>
                  <td colSpan={5} style={{ textAlign: "right", padding: "0.8rem 1rem" }}>TOTAL</td>
                  <td style={{ padding: "0.8rem 1rem" }}>${open.reduce((sum, p) => sum + p.size, 0).toFixed(2)}</td>
                  <td style={{
                    padding: "0.8rem 1rem",
                    color: open.reduce((sum, p) => sum + (p.unrealized_pnl || 0), 0) >= 0 ? "var(--green)" : "var(--red)",
                  }}>
                    {formatSignedUsd(open.reduce((sum, p) => sum + (p.unrealized_pnl || 0), 0))}
                  </td>
                  <td colSpan={2} style={{ padding: "0.8rem 1rem" }}></td>
                </tr>
              </tfoot>
            )}
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
