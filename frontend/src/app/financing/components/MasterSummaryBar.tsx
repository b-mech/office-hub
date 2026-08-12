import type { FinancingProperty } from "@/types/financing";

const money = new Intl.NumberFormat("en-CA", { style: "currency", currency: "CAD", maximumFractionDigits: 0 });

function num(value: unknown): number {
  const parsed = Number(value ?? 0);
  return Number.isFinite(parsed) ? parsed : 0;
}

export function MasterSummaryBar({ properties }: { properties: FinancingProperty[] }) {
  const nonPro = properties.filter((property) => property.lender_type !== "PRO");
  const clean = nonPro.filter((property) => !property.flag);
  const totalDrawable = clean.reduce((sum, item) => sum + num(item.draw_eligible), 0);
  const committed = nonPro.reduce((sum, item) => sum + num(item.total_facility), 0);
  const drawn = properties.reduce((sum, item) => sum + num(item.already_drawn), 0);
  const accruedInterest = properties.reduce((sum, item) => sum + num(item.accrued_interest), 0);
  const nonProDrawn = nonPro.reduce((sum, item) => sum + num(item.already_drawn), 0);
  const flagged = properties.filter((item) => item.flag).length;

  const items = [
    ["Total Drawable Now", totalDrawable, "Excludes PRO (no commitment data)"],
    ["Total Committed", committed],
    ["Total Drawn to Date", drawn],
    ["Accrued Unpaid Interest", accruedInterest],
    ["Total Remaining Facility", committed - nonProDrawn, "Excludes PRO (no commitment data)"],
  ];

  return (
    <section className="grid gap-3 rounded-lg border border-[var(--ch-border)] bg-[var(--ch-surface)] p-4 md:grid-cols-6">
      {items.map(([label, value, title]) => (
        <div key={label as string}>
          <p className="text-xs text-[var(--ch-text-muted)]" title={title as string | undefined}>{label}</p>
          <p className="mt-1 text-lg font-semibold text-[var(--ch-text-primary)]">{money.format(value as number)}</p>
        </div>
      ))}
      <div>
        <p className="text-xs text-[var(--ch-text-muted)]">Flagged Properties</p>
        <p className="mt-1 inline-flex rounded-full bg-[var(--ch-error-bg)] px-2 py-1 text-sm font-semibold text-[var(--ch-error-text)]">
          {flagged}
        </p>
      </div>
    </section>
  );
}
