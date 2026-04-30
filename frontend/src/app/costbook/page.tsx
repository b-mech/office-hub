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
    <div className="min-h-screen bg-[#0f1117] text-white px-8 py-8">
      <div className="max-w-5xl mx-auto">
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-xl font-semibold text-white">Costbook</h1>
            <p className="text-sm text-white/40 mt-0.5">All lot budgets</p>
          </div>
          <Link
            href="/lots"
            className="text-sm text-white/40 hover:text-white transition-colors"
          >
            View Lots →
          </Link>
        </div>

        {loading ? (
          <div className="text-white/30 text-sm py-16 text-center">Loading…</div>
        ) : budgets.length === 0 ? (
          <div className="text-center py-16">
            <p className="text-white/30 text-sm">No budgets yet. Open a lot to create one.</p>
            <Link href="/lots" className="mt-4 inline-block text-amber-300 text-sm hover:underline">
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
                  href={`/lots/${b.lot_agreement_id || b.id}/costbook`}
                  className="block rounded-xl border border-white/10 bg-white/3 p-5 hover:bg-white/5 hover:border-white/20 transition-all group"
                >
                  <div className="flex items-start justify-between gap-4 mb-4">
                    <div>
                      <h2 className="text-base font-medium text-white group-hover:text-amber-300 transition-colors">
                        {b.label}
                      </h2>
                      <span className={`text-xs font-medium px-2 py-0.5 rounded-full mt-1 inline-block ${
                        b.status === "active" ? "bg-blue-500/15 text-blue-300"
                        : b.status === "locked" ? "bg-white/10 text-white/40"
                        : "bg-white/5 text-white/30"
                      }`}>
                        {b.status}
                      </span>
                    </div>
                    <div className="text-right">
                      <p className="text-xs text-white/40 mb-0.5">Estimate</p>
                      <p className="text-base font-semibold text-white">{fmt(b.total_estimate)}</p>
                    </div>
                  </div>

                  <div className="grid grid-cols-3 gap-3 mb-4 text-sm">
                    <div>
                      <p className="text-xs text-white/30 mb-0.5">Actual</p>
                      <p className="text-white/70">{fmt(b.total_actual)}</p>
                    </div>
                    <div>
                      <p className="text-xs text-white/30 mb-0.5">Variance</p>
                      <p className={over ? "text-red-400" : b.total_variance < 0 ? "text-emerald-400" : "text-white/30"}>
                        {b.total_actual > 0 ? fmt(b.total_variance) : "—"}
                      </p>
                    </div>
                    <div>
                      <p className="text-xs text-white/30 mb-0.5">Lines</p>
                      <p className="text-white/70">{b.lines.length}</p>
                    </div>
                  </div>

                  {/* Progress bar */}
                  <div className="h-1.5 bg-white/10 rounded-full overflow-hidden">
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
