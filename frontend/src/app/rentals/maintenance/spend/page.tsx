"use client";

import Link from "next/link";
import { ArrowLeft, Download, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { downloadSpendCsv, getMaintenanceFilterOptions, getSpendReport, type MaintenanceFilterOptions, type SpendQuery, type SpendReport } from "@/lib/api/maintenance";
import { formatMoney } from "@/lib/maintenance-workflows";

function monthBounds(offset: number) {
  const now = new Date();
  const start = new Date(now.getFullYear(), now.getMonth() + offset, 1);
  const end = new Date(now.getFullYear(), now.getMonth() + offset + 1, 0);
  const iso = (value: Date) => `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, "0")}-${String(value.getDate()).padStart(2, "0")}`;
  return { start: iso(start), end: iso(end) };
}

export default function MaintenanceSpendPage() {
  const [filters, setFilters] = useState<SpendQuery>(() => ({ ...monthBounds(-11), end: monthBounds(0).end, group_by: "property" }));
  const [report, setReport] = useState<SpendReport | null>(null);
  const [options, setOptions] = useState<MaintenanceFilterOptions>({ properties: [], assignees: [] });
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setBusy(true); setError("");
    try { setReport(await getSpendReport(filters)); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Could not load the spend report"); }
    finally { setBusy(false); }
  }, [filters]);
  useEffect(() => { const timer = window.setTimeout(() => void load(), 0); return () => window.clearTimeout(timer); }, [load]);
  useEffect(() => { getMaintenanceFilterOptions().then(setOptions).catch(() => undefined); }, []);

  const months = useMemo(() => Array.from(new Set(report?.rows.map((row) => row.month) || [])), [report]);
  const input = "min-h-11 rounded-xl border border-[var(--ch-border)] bg-[var(--ch-surface-strong)] px-3 text-sm";

  return <main className="min-h-screen bg-[var(--ch-page-bg)] px-4 py-6 sm:px-6 lg:px-8">
    <div className="mx-auto max-w-[1400px]">
      <header className="flex flex-wrap items-end justify-between gap-4 border-b border-[var(--ch-border)] pb-5">
        <div><Link href="/rentals/maintenance" className="inline-flex items-center gap-1 text-sm font-semibold text-[var(--ch-accent)]"><ArrowLeft size={15} /> Tickets</Link><h1 className="mt-2 text-3xl font-semibold">Maintenance spend</h1><p className="mt-2 text-sm text-[var(--ch-text-muted)]">Work-order estimates and actuals by month and address, split repair vs capital. Read-only.</p></div>
        <div className="flex gap-2"><button type="button" onClick={() => void load()} disabled={busy} className="inline-flex min-h-11 items-center gap-2 rounded-xl border border-[var(--ch-border)] bg-[var(--ch-surface)] px-4 text-sm font-semibold disabled:opacity-50"><RefreshCw size={16} className={busy ? "animate-spin" : ""} /> Refresh</button><button type="button" onClick={() => void downloadSpendCsv(filters).catch((caught) => setError(caught instanceof Error ? caught.message : "Export failed"))} className="inline-flex min-h-11 items-center gap-2 rounded-xl bg-[var(--ch-accent)] px-4 text-sm font-semibold text-white"><Download size={16} /> Export CSV</button></div>
      </header>
      <section className="mt-5 grid gap-3 rounded-2xl border border-[var(--ch-border)] bg-[var(--ch-surface)] p-4 sm:grid-cols-2 lg:grid-cols-5" aria-label="Report filters">
        <label className="text-xs font-semibold text-[var(--ch-text-muted)]">From<input type="date" value={filters.start || ""} onChange={(event) => setFilters((current) => ({ ...current, start: event.target.value || undefined }))} className={`${input} mt-1 w-full font-normal`} /></label>
        <label className="text-xs font-semibold text-[var(--ch-text-muted)]">To<input type="date" value={filters.end || ""} onChange={(event) => setFilters((current) => ({ ...current, end: event.target.value || undefined }))} className={`${input} mt-1 w-full font-normal`} /></label>
        <label className="text-xs font-semibold text-[var(--ch-text-muted)]">Group by<select value={filters.group_by} onChange={(event) => setFilters((current) => ({ ...current, group_by: event.target.value as "property" | "unit" }))} className={`${input} mt-1 w-full font-normal`}><option value="property">Property</option><option value="unit">Unit</option></select></label>
        <label className="text-xs font-semibold text-[var(--ch-text-muted)] lg:col-span-2">Property<select value={filters.property_id ? String(filters.property_id) : ""} onChange={(event) => setFilters((current) => ({ ...current, property_id: event.target.value ? Number(event.target.value) : undefined }))} className={`${input} mt-1 w-full font-normal`}><option value="">All properties</option>{options.properties.map((item) => <option key={item.id} value={String(item.id)}>{item.address}</option>)}</select></label>
      </section>
      {error ? <p className="mt-4 rounded-xl border border-[var(--ch-error-border)] bg-[var(--ch-error-bg)] p-3 text-sm text-[var(--ch-error-text)]">{error}</p> : null}
      {report ? <section className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-5" aria-label="Totals">{[["Work orders", String(report.totals.work_orders)], ["Estimated", formatMoney(report.totals.cost_estimate)], ["Actual", formatMoney(report.totals.cost_actual)], ["Repair (opex)", formatMoney(report.totals.repair_actual)], ["Capital (capex)", formatMoney(report.totals.capital_actual)]].map(([name, amount]) => <div key={name} className="rounded-2xl border border-[var(--ch-border)] bg-[var(--ch-surface)] p-4"><p className="text-xs font-semibold uppercase tracking-wide text-[var(--ch-text-muted)]">{name}</p><p className="mt-1 text-2xl font-semibold">{amount}</p></div>)}</section> : null}
      <div className="mt-5 overflow-x-auto rounded-2xl border border-[var(--ch-border)] bg-[var(--ch-surface)]">
        <table className="min-w-full text-sm">
          <thead className="bg-[var(--ch-surface-muted)] text-left text-xs uppercase tracking-wide text-[var(--ch-text-muted)]"><tr><th className="px-4 py-3">Month</th><th className="px-4 py-3">Property</th>{filters.group_by === "unit" ? <th className="px-4 py-3">Unit</th> : null}<th className="px-4 py-3 text-right">WOs</th><th className="px-4 py-3 text-right">Estimate</th><th className="px-4 py-3 text-right">Actual</th><th className="px-4 py-3 text-right">Repair</th><th className="px-4 py-3 text-right">Capital</th><th className="px-4 py-3 text-right">Unclassified</th></tr></thead>
          <tbody>{months.map((month) => report!.rows.filter((row) => row.month === month).map((row, index) => <tr key={`${month}-${row.property_id}-${row.unit_id ?? "all"}`} className="border-t border-[var(--ch-border)]">
            <td className="px-4 py-2 font-semibold">{index === 0 ? month : ""}</td>
            <td className="px-4 py-2"><Link href={`/rentals/maintenance?property_id=${row.property_id}&include_terminal=true`} className="hover:text-[var(--ch-accent)]">{row.property}</Link></td>
            {filters.group_by === "unit" ? <td className="px-4 py-2">{row.unit}</td> : null}
            <td className="px-4 py-2 text-right">{row.work_orders}</td><td className="px-4 py-2 text-right">{formatMoney(row.cost_estimate)}</td><td className="px-4 py-2 text-right font-semibold">{formatMoney(row.cost_actual)}</td><td className="px-4 py-2 text-right">{formatMoney(row.repair_actual)}</td><td className="px-4 py-2 text-right">{formatMoney(row.capital_actual)}</td><td className="px-4 py-2 text-right">{formatMoney(row.unclassified_actual)}</td>
          </tr>))}
          {!busy && report && report.rows.length === 0 ? <tr><td colSpan={9} className="px-4 py-10 text-center text-[var(--ch-text-muted)]">No work-order costs in this range yet. Costs appear once work orders have an estimate or an actual cost.</td></tr> : null}</tbody>
        </table>
      </div>
      {report ? <p className="mt-3 text-xs text-[var(--ch-text-muted)]">{report.basis} Purchase notes are tracked on tickets but are not added here, so invoices are not double counted.</p> : null}
    </div>
  </main>;
}
