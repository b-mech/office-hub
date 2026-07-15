import type { FinancingDashboard, LenderType } from "@/types/financing";

const lenders: LenderType[] = ["SCU", "PRO", "STRIDE", "RSU", "CLIENT", "OTHER"];
const money = new Intl.NumberFormat("en-CA", { style: "currency", currency: "CAD", maximumFractionDigits: 0 });

export function LenderSummaryCards({
  summary,
  active,
  onSelect,
}: {
  summary: FinancingDashboard["summary"];
  active: LenderType | null;
  onSelect: (lender: LenderType | null) => void;
}) {
  return (
    <section className="flex flex-wrap gap-3">
      <button
        onClick={() => onSelect(null)}
        className={`rounded-full border px-4 py-2 text-sm font-medium ${
          active === null
            ? "border-[var(--ch-accent)] bg-[var(--ch-accent)] text-[var(--ch-accent-text)]"
            : "border-[var(--ch-border)] bg-[var(--ch-surface)] text-[var(--ch-text-secondary)]"
        }`}
      >
        All Lenders
      </button>
      {lenders.map((lender) => {
        const item = summary[lender];
        const selected = active === lender;
        return (
          <button
            key={lender}
            onClick={() => onSelect(selected ? null : lender)}
            className={`min-w-36 rounded-lg border p-3 text-left ${
              selected
                ? "border-[var(--ch-accent)] bg-[var(--ch-accent)] text-[var(--ch-accent-text)]"
                : "border-[var(--ch-border)] bg-[var(--ch-surface)] text-[var(--ch-text-primary)] hover:border-[var(--ch-border-strong)]"
            }`}
          >
            <div className="flex items-center justify-between gap-2">
              <span className="text-sm font-semibold">{lender}</span>
              {(lender === "PRO" ? item.properties : item.flagged) > 0 ? (
                <span className="rounded-full bg-[var(--ch-error-bg)] px-2 py-0.5 text-xs text-[var(--ch-error-text)]">{lender === "PRO" ? item.properties : item.flagged}</span>
              ) : null}
            </div>
            <p className="mt-2 text-base font-semibold">
              {item.total_drawable === null ? "Review" : money.format(Number(item.total_drawable))}
            </p>
            <p className={selected ? "text-xs opacity-80" : "text-xs text-[var(--ch-text-muted)]"}>{item.properties} properties</p>
          </button>
        );
      })}
    </section>
  );
}
