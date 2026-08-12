import type { FinancingProperty, LenderType } from "@/types/financing";

const money = new Intl.NumberFormat("en-CA", { style: "currency", currency: "CAD", maximumFractionDigits: 0 });

const lenderClass: Record<LenderType, string> = {
  SCU: "bg-[var(--ch-info-bg)] text-[var(--ch-info-text)]",
  PRO: "bg-[var(--ch-success-bg)] text-[var(--ch-success-text)]",
  STRIDE: "bg-[var(--ch-accent-soft)] text-[var(--ch-accent)]",
  RSU: "bg-[var(--ch-warning-bg)] text-[var(--ch-warning-text)]",
  CLIENT: "bg-[var(--ch-status-draft-bg)] text-[var(--ch-status-draft-text)]",
  OTHER: "bg-[var(--ch-surface-muted)] text-[var(--ch-text-muted)]",
};

function num(value: unknown): number {
  const parsed = Number(value ?? 0);
  return Number.isFinite(parsed) ? parsed : 0;
}

function flagClass(flag: string | null) {
  if (flag === "OVER_DRAWN") return "bg-[var(--ch-error-bg)] text-[var(--ch-error-text)]";
  if (flag === "SYNC_CONFLICT") return "bg-[var(--ch-error-bg)] text-[var(--ch-error-text)]";
  if (flag === "CHECK_OTP") return "bg-[var(--ch-status-draft-bg)] text-[var(--ch-status-draft-text)]";
  return "bg-[var(--ch-warning-bg)] text-[var(--ch-warning-text)]";
}

export function MasterPropertyDrawTable({
  properties,
  onSelect,
  selectedIds,
  onToggle,
  onToggleAll,
}: {
  properties: FinancingProperty[];
  onSelect: (property: FinancingProperty) => void;
  selectedIds: Set<string>;
  onToggle: (propertyId: string) => void;
  onToggleAll: () => void;
}) {
  const selectable = properties.filter((item) => item.lender_type === "PRO" && num(item.draw_eligible) > 0);
  const allSelected = selectable.length > 0 && selectable.every((item) => selectedIds.has(item.property_id));
  const totals = properties.reduce(
    (acc, item) => ({
      facility: acc.facility + num(item.total_facility),
      drawn: acc.drawn + num(item.already_drawn),
      accruedInterest: acc.accruedInterest + num(item.accrued_interest),
      entitled: acc.entitled + num(item.cumulative_entitled),
      draw: acc.draw + num(item.draw_eligible),
    }),
    { facility: 0, drawn: 0, accruedInterest: 0, entitled: 0, draw: 0 },
  );

  return (
    <div className="overflow-hidden rounded-lg border border-[var(--ch-border)] bg-[var(--ch-surface)]">
      <div className="overflow-x-auto">
        <table className="min-w-full border-collapse text-sm">
          <thead className="bg-[var(--ch-surface-muted)] text-xs uppercase text-[var(--ch-text-muted)]">
            <tr>
              <th className="px-3 py-3 text-left">
                <input
                  type="checkbox"
                  aria-label="Select all available PRO draws"
                  checked={allSelected}
                  onChange={onToggleAll}
                  className="size-4 accent-[var(--ch-accent)]"
                />
              </th>
              {["Address", "Lender", "S/S", "Stage", "Possession", "Total Facility", "Principal Drawn", "Accrued Interest", "Entitled", "Draw Now", "Flag", "Action"].map((head) => (
                <th key={head} className="px-3 py-3 text-left font-semibold last:text-left">{head}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {properties.map((item) => (
              <tr
                key={`${item.property_id}:${item.facility_id || "property"}`}
                onClick={() => onSelect(item)}
                className="cursor-pointer border-t border-[var(--ch-border)] hover:bg-[var(--ch-surface-hover)]"
              >
                <td className="px-3 py-3" onClick={(event) => event.stopPropagation()}>
                  <input
                    type="checkbox"
                    aria-label={`Select ${item.address}`}
                    disabled={item.lender_type !== "PRO" || num(item.draw_eligible) <= 0}
                    checked={selectedIds.has(item.property_id)}
                    onChange={() => onToggle(item.property_id)}
                    className="size-4 accent-[var(--ch-accent)] disabled:opacity-30"
                  />
                </td>
                <td className="max-w-72 px-3 py-3 font-medium text-[var(--ch-text-primary)]">{item.address}</td>
                <td className="px-3 py-3">
                  <span className={`rounded-full px-2 py-1 text-xs font-semibold ${lenderClass[item.lender_type]}`}>{item.lender_type}</span>
                </td>
                <td className="px-3 py-3 text-[var(--ch-text-secondary)]">{item.sold_or_spec || "-"}</td>
                <td className="px-3 py-3 text-[var(--ch-text-secondary)]">
                  {item.lender_type === "PRO" && !item.stage ? "-" : item.stage || "NA"} {item.stage_is_estimate ? <span className="text-xs text-[var(--ch-warning-text)]">(est.)</span> : null}
                </td>
                <td className="px-3 py-3 text-[var(--ch-text-secondary)]">{item.possession_date || "-"}</td>
                <td className="px-3 py-3 text-right tabular-nums">{money.format(num(item.total_facility))}</td>
                <td className="px-3 py-3 text-right tabular-nums">{money.format(num(item.already_drawn))}</td>
                <td className="px-3 py-3 text-right tabular-nums">
                  {item.accrued_interest == null ? "-" : money.format(num(item.accrued_interest))}
                </td>
                <td className="px-3 py-3 text-right tabular-nums">{item.cumulative_entitled == null ? "-" : money.format(num(item.cumulative_entitled))}</td>
                <td className="px-3 py-3 text-right font-bold tabular-nums text-[var(--ch-accent)]">{item.draw_eligible == null ? "-" : money.format(num(item.draw_eligible))}</td>
                <td className="px-3 py-3">
                  {item.flag ? <span className={`rounded-full px-2 py-1 text-xs font-semibold ${flagClass(item.flag)}`}>{item.flag}</span> : "-"}
                </td>
                <td className="px-3 py-3">
                  {item.lender_type === "CLIENT" ? (
                    <button
                      type="button"
                      onClick={(event) => {
                        event.stopPropagation();
                        onSelect(item);
                      }}
                      className="rounded-md border border-[var(--ch-border)] px-2 py-1 text-xs font-semibold hover:bg-[var(--ch-surface-hover)]"
                    >
                      Prep Draw
                    </button>
                  ) : "-"}
                </td>
              </tr>
            ))}
          </tbody>
          <tfoot className="border-t border-[var(--ch-border-strong)] bg-[var(--ch-surface-muted)] font-semibold">
            <tr>
              <td />
              <td className="px-3 py-3" colSpan={5}>Filtered totals</td>
              <td className="px-3 py-3 text-right">{money.format(totals.facility)}</td>
              <td className="px-3 py-3 text-right">{money.format(totals.drawn)}</td>
              <td className="px-3 py-3 text-right">{money.format(totals.accruedInterest)}</td>
              <td className="px-3 py-3 text-right">{money.format(totals.entitled)}</td>
              <td className="px-3 py-3 text-right text-[var(--ch-accent)]">{money.format(totals.draw)}</td>
              <td />
              <td />
            </tr>
          </tfoot>
        </table>
      </div>
    </div>
  );
}
