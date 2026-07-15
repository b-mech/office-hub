import type { LenderType } from "@/types/financing";

export interface FinancingFilters {
  lender: LenderType | null;
  soldOrSpec: string;
  stages: string[];
  possessionFrom: string;
  possessionTo: string;
  search: string;
}

const stages = ["FOUNDATION", "LOCKUP", "DRYWALL", "CABINETRY", "COMPLETED"];

export function FilterBar({
  filters,
  onChange,
  onClear,
}: {
  filters: FinancingFilters;
  onChange: (filters: FinancingFilters) => void;
  onClear: () => void;
}) {
  const activeCount = [
    filters.lender,
    filters.soldOrSpec !== "ALL",
    filters.stages.length,
    filters.possessionFrom,
    filters.possessionTo,
    filters.search,
  ].filter(Boolean).length;

  return (
    <section className="grid gap-3 rounded-lg border border-[var(--ch-border)] bg-[var(--ch-surface-muted)] p-3 lg:grid-cols-[1fr_auto_auto_auto_auto]">
      <input
        value={filters.search}
        onChange={(event) => onChange({ ...filters, search: event.target.value })}
        placeholder="Search address"
        className="rounded-md border border-[var(--ch-border)] bg-[var(--ch-surface-strong)] px-3 py-2 text-sm outline-none focus:border-[var(--ch-accent)]"
      />
      <select
        value={filters.soldOrSpec}
        onChange={(event) => onChange({ ...filters, soldOrSpec: event.target.value })}
        className="rounded-md border border-[var(--ch-border)] bg-[var(--ch-surface-strong)] px-3 py-2 text-sm"
      >
        <option value="ALL">Sold / Spec</option>
        <option value="SOLD">Sold</option>
        <option value="SPEC">Spec</option>
      </select>
      <select
        value={filters.stages[0] || ""}
        onChange={(event) => onChange({ ...filters, stages: event.target.value ? [event.target.value] : [] })}
        className="rounded-md border border-[var(--ch-border)] bg-[var(--ch-surface-strong)] px-3 py-2 text-sm"
      >
        <option value="">All stages</option>
        {stages.map((stage) => (
          <option key={stage} value={stage}>{stage}</option>
        ))}
      </select>
      <input
        type="date"
        value={filters.possessionFrom}
        onChange={(event) => onChange({ ...filters, possessionFrom: event.target.value })}
        className="rounded-md border border-[var(--ch-border)] bg-[var(--ch-surface-strong)] px-3 py-2 text-sm"
      />
      <input
        type="date"
        value={filters.possessionTo}
        onChange={(event) => onChange({ ...filters, possessionTo: event.target.value })}
        className="rounded-md border border-[var(--ch-border)] bg-[var(--ch-surface-strong)] px-3 py-2 text-sm"
      />
      <div className="flex items-center gap-3 lg:col-span-5">
        <span className="rounded-full bg-[var(--ch-accent-soft)] px-2 py-1 text-xs font-medium text-[var(--ch-accent)]">
          {activeCount} active
        </span>
        <button onClick={onClear} className="text-xs font-medium text-[var(--ch-text-muted)] hover:text-[var(--ch-text-primary)]">
          Clear all
        </button>
      </div>
    </section>
  );
}
