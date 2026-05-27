"use client";

// app/costbook/page.tsx
// Standalone costbook page accessible from the main nav.
// Shows all budgets, not scoped to a specific lot.

import { useEffect, useState } from "react";
import Link from "next/link";
import { getBudgets, type Budget } from "@/lib/api/costbook";

function fmt(n: number) {
  return new Intl.NumberFormat("en-CA", { style: "currency", currency: "CAD", maximumFractionDigits: 0 }).format(n);
}

export default function CostbookIndexPage() {
  const [budgets, setBudgets] = useState<Budget[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getBudgets().then(setBudgets).finally(() => setLoading(false));
  }, []);

  return (
    <div className="min-h-screen bg-[var(--ch-page-bg)] text-[var(--ch-text-primary)] px-8 py-8">
      <div className="max-w-5xl mx-auto">
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-xl font-semibold text-[var(--ch-text-primary)]">Costbook</h1>
            <p className="text-sm text-[var(--ch-text-muted)] mt-0.5">All lot budgets</p>
          </div>
          <Link
            href="/lots"
            className="text-sm text-[var(--ch-text-muted)] hover:text-[var(--ch-text-primary)] transition-colors"
          >
            View Lots →
          </Link>
        </div>

        {loading ? (
          <div className="text-[var(--ch-text-muted)] text-sm py-16 text-center">Loading…</div>
        ) : budgets.length === 0 ? (
          <div className="text-center py-16">
            <p className="text-[var(--ch-text-muted)] text-sm">No budgets yet. Open a lot to create one.</p>
            <Link href="/lots" className="mt-4 inline-block text-[var(--ch-warning-text)] text-sm hover:underline">
              Go to Lots
            </Link>
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-4">
            {budgets.map((b) => {
              const pct = b.total_estimate > 0
                ? Math.min((b.total_actual / b.total_estimate) * 100, 100)
                : 0;
              const over = b.total_variance > 0;

              return (
                <Link
                  key={b.id}
                  href={b.lot_agreement_id ? `/lots/${b.lot_agreement_id}/costbook` : `/costbook/budgets/${b.id}`}
                  className="block rounded-xl border border-[var(--ch-border)] bg-[var(--ch-surface)] p-5 hover:bg-[var(--ch-surface)] hover:border-[var(--ch-border-strong)] transition-all group"
                >
                  <div className="flex items-start justify-between gap-4 mb-4">
                    <div>
                      <h2 className="text-base font-medium text-[var(--ch-text-primary)] group-hover:text-[var(--ch-warning-text)] transition-colors">
                        {b.label}
                      </h2>
                      <span className={`text-xs font-medium px-2 py-0.5 rounded-full mt-1 inline-block ${
                        b.status === "active" ? "bg-blue-500/15 text-blue-300"
                        : b.status === "locked" ? "bg-[var(--ch-surface)] text-[var(--ch-text-muted)]"
                        : "bg-[var(--ch-surface)] text-[var(--ch-text-muted)]"
                      }`}>
                        {b.status}
                      </span>
                    </div>
                    <div className="text-right">
                      <p className="text-xs text-[var(--ch-text-muted)] mb-0.5">Estimate</p>
                      <p className="text-base font-semibold text-[var(--ch-text-primary)]">{fmt(b.total_estimate)}</p>
                    </div>
                  </div>

                  <div className="grid grid-cols-3 gap-3 mb-4 text-sm">
                    <div>
                      <p className="text-xs text-[var(--ch-text-muted)] mb-0.5">Actual</p>
                      <p className="text-[var(--ch-text-secondary)]">{fmt(b.total_actual)}</p>
                    </div>
                    <div>
                      <p className="text-xs text-[var(--ch-text-muted)] mb-0.5">Variance</p>
                      <p className={over ? "text-red-400" : b.total_variance < 0 ? "text-[var(--ch-success-text)]" : "text-[var(--ch-text-muted)]"}>
                        {b.total_actual > 0 ? fmt(b.total_variance) : "—"}
                      </p>
                    </div>
                    <div>
                      <p className="text-xs text-[var(--ch-text-muted)] mb-0.5">Lines</p>
                      <p className="text-[var(--ch-text-secondary)]">{b.lines.length}</p>
                    </div>
                  </div>

                  {/* Progress bar */}
                  <div className="h-1.5 bg-[var(--ch-surface)] rounded-full overflow-hidden">
                    <div
                      className={`h-full rounded-full transition-all ${over ? "bg-red-400" : "bg-amber-400"}`}
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                </Link>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
