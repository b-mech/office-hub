import { useEffect, useMemo, useState } from "react";
import { X } from "lucide-react";
import { createFacility, getProLedger, updateFacility } from "@/lib/api/financing";
import type { FacilityPayload, FinancingProperty, ProLedger } from "@/types/financing";
import { ClientOtpPanel } from "./ClientOtpPanel";
import { DocumentUploadPanel } from "./DocumentUploadPanel";
import { LenderFacilityForm } from "./LenderFacilityForm";

const money = new Intl.NumberFormat("en-CA", { style: "currency", currency: "CAD", maximumFractionDigits: 0 });

function num(value: unknown): number {
  const parsed = Number(value ?? 0);
  return Number.isFinite(parsed) ? parsed : 0;
}

export function PropertyDetailDrawer({
  property,
  properties,
  onClose,
  onUpdated,
}: {
  property: FinancingProperty | null;
  properties: FinancingProperty[];
  onClose: () => void;
  onUpdated: () => Promise<void>;
}) {
  const [ledger, setLedger] = useState<ProLedger | null>(null);
  const [ledgerError, setLedgerError] = useState<string | null>(null);
  const [linkPropertyId, setLinkPropertyId] = useState("");
  const [linking, setLinking] = useState(false);

  const linkOptions = useMemo(() => {
    const seen = new Set<string>();
    return properties.filter((item) => {
      if (item.lender_type === "PRO") return false;
      if (seen.has(item.property_id)) return false;
      seen.add(item.property_id);
      return true;
    });
  }, [properties]);

  useEffect(() => {
    let active = true;
    if (!property?.facility_id || property.lender_type !== "PRO") return;
    getProLedger(property.facility_id)
      .then((data) => {
        if (active) setLedger(data);
      })
      .catch((err) => {
        if (active) setLedgerError(err instanceof Error ? err.message : "Failed to load PRO ledger");
      });
    return () => {
      active = false;
    };
  }, [property?.facility_id, property?.lender_type]);

  if (!property) return null;
  const currentLedger = ledger?.facility_id === property.facility_id ? ledger : null;
  const currentLedgerError = currentLedger ? null : ledgerError;

  async function saveFacility(payload: FacilityPayload) {
    if (property?.facility_id) {
      await updateFacility(property.facility_id, payload);
    } else {
      await createFacility(payload);
    }
    await onUpdated();
  }

  async function linkFacility() {
    if (!property?.facility_id || !linkPropertyId) return;
    setLinking(true);
    try {
      await updateFacility(property.facility_id, { property_id: linkPropertyId });
      await onUpdated();
    } finally {
      setLinking(false);
    }
  }

  return (
    <div className="fixed inset-0 z-40 bg-black/20" onClick={onClose}>
      <aside
        className="absolute right-0 top-0 h-full w-full max-w-2xl overflow-y-auto border-l border-[var(--ch-border)] bg-[var(--ch-page-bg)] p-6 shadow-xl"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="mb-5 flex items-start justify-between gap-4">
          <div>
            <h2 className="text-xl font-semibold">{property.address}</h2>
            <p className="mt-1 text-sm text-[var(--ch-text-muted)]">
              {property.client_name || "No client"} · {property.banker_raw || property.lender_type}
            </p>
          </div>
          <button onClick={onClose} className="rounded-md p-2 text-[var(--ch-text-muted)] hover:bg-[var(--ch-surface-hover)]" aria-label="Close drawer">
            <X size={18} />
          </button>
        </div>

        <div className="mb-4 grid gap-3 rounded-lg border border-[var(--ch-border)] bg-[var(--ch-surface)] p-4 sm:grid-cols-2">
          <Info label="Stage" value={`${property.stage || "NA"}${property.stage_is_estimate ? " (est.)" : ""}`} />
          <Info label="Possession" value={property.possession_date || "-"} />
          <Info label="Build start" value={property.build_start || "-"} />
          <Info label="Sold / Spec" value={property.sold_or_spec || "-"} />
        </div>

        <div className="mb-4 rounded-lg border border-[var(--ch-border)] bg-[var(--ch-surface)] p-4">
          <h3 className="mb-3 text-sm font-semibold">Draw Calculation</h3>
          <div className="grid gap-3 sm:grid-cols-3">
            <Info label="Entitled" value={property.cumulative_entitled == null ? "-" : money.format(num(property.cumulative_entitled))} />
            <Info label="Already drawn" value={money.format(num(property.already_drawn))} />
            <Info label="Eligible now" value={property.draw_eligible == null ? "-" : money.format(num(property.draw_eligible))} strong />
          </div>
          <p className="mt-3 rounded-md bg-[var(--ch-surface-muted)] px-3 py-2 text-xs text-[var(--ch-text-secondary)]">{property.formula}</p>
          {property.flag ? <p className="mt-3 text-sm font-medium text-[var(--ch-warning-text)]">{explainFlag(property.flag)}</p> : null}
          {property.lender_type === "CLIENT" ? <p className="mt-3 text-sm text-[var(--ch-text-secondary)]">CLIENT — use Prep Draw to match the reviewed OTP schedule to the current stage.</p> : null}
        </div>

        <ClientOtpPanel property={property} onUpdated={onUpdated} />

        {property.flag === "NEEDS_LINK" && property.facility_id ? (
          <div className="mb-4 rounded-lg border border-[var(--ch-warning-border)] bg-[var(--ch-surface)] p-4">
            <h3 className="mb-3 text-sm font-semibold">Link Property</h3>
            <div className="flex gap-2">
              <select
                value={linkPropertyId}
                onChange={(event) => setLinkPropertyId(event.target.value)}
                className="min-w-0 flex-1 rounded-md border border-[var(--ch-border)] bg-[var(--ch-surface)] px-3 py-2 text-sm"
              >
                <option value="">Select property</option>
                {linkOptions.map((item) => (
                  <option key={item.property_id} value={item.property_id}>{item.address}</option>
                ))}
              </select>
              <button
                type="button"
                onClick={linkFacility}
                disabled={!linkPropertyId || linking}
                className="rounded-md bg-[var(--ch-accent)] px-3 py-2 text-sm font-semibold text-white disabled:opacity-50"
              >
                {linking ? "Linking" : "Link"}
              </button>
            </div>
          </div>
        ) : null}

        {property.lender_type === "PRO" ? (
          <div className="mb-4 rounded-lg border border-[var(--ch-border)] bg-[var(--ch-surface)] p-4">
            <h3 className="mb-3 text-sm font-semibold">PRO Ledger</h3>
            {currentLedgerError ? <p className="text-sm text-[var(--ch-error-text)]">{currentLedgerError}</p> : null}
            {!currentLedger && !currentLedgerError ? <p className="text-sm text-[var(--ch-text-muted)]">Loading ledger...</p> : null}
            {currentLedger ? (
              <div className="overflow-x-auto">
                <table className="min-w-full text-xs">
                  <thead className="text-[var(--ch-text-muted)]">
                    <tr>
                      {["Date", "Days", "Interest", "Draw", "Reference", "Balance"].map((head) => (
                        <th key={head} className="px-2 py-2 text-left font-semibold">{head}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {currentLedger.events.map((event, index) => (
                      <tr key={`${event.event_date}-${index}`} className="border-t border-[var(--ch-border)]">
                        <td className="px-2 py-2">{event.event_date}</td>
                        <td className="px-2 py-2 text-right tabular-nums">{event.days}</td>
                        <td className="px-2 py-2 text-right tabular-nums">{money.format(num(event.interest))}</td>
                        <td className="px-2 py-2 text-right tabular-nums">{num(event.draw) ? money.format(num(event.draw)) : "-"}</td>
                        <td className="px-2 py-2 text-[var(--ch-text-secondary)]">{event.reference || "-"}</td>
                        <td className="px-2 py-2 text-right font-semibold tabular-nums">{money.format(num(event.balance))}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : null}
          </div>
        ) : null}

        <div className="mb-4 rounded-lg border border-[var(--ch-border)] bg-[var(--ch-surface)] p-4">
          <h3 className="mb-3 text-sm font-semibold">Interest Projection</h3>
          <div className="grid gap-3 sm:grid-cols-3">
            <Info label="Outstanding balance" value={property.outstanding_balance == null ? "-" : money.format(num(property.outstanding_balance))} />
            <Info label="Rate" value={property.rate == null ? "-" : `${property.rate}%`} />
            <Info label="Next payment" value={property.next_payment_date || property.next_interest_payment_date || "-"} />
            <Info label="Daily estimate" value={property.daily_interest_estimate == null ? "-" : money.format(num(property.daily_interest_estimate))} strong />
            <Info label="Monthly estimate" value={property.monthly_interest_estimate == null ? "-" : money.format(num(property.monthly_interest_estimate))} strong />
            <Info label="Annual estimate" value={property.annual_interest_estimate == null ? "-" : money.format(num(property.annual_interest_estimate))} />
          </div>
          {property.account_nickname || property.account_number ? (
            <p className="mt-3 rounded-md bg-[var(--ch-surface-muted)] px-3 py-2 text-xs text-[var(--ch-text-secondary)]">
              {[property.account_nickname, property.account_number, property.account_title].filter(Boolean).join(" · ")}
            </p>
          ) : null}
        </div>

        <div className="mb-4">
          <LenderFacilityForm property={property} onSave={saveFacility} />
        </div>
        <DocumentUploadPanel property={property} onUpdated={onUpdated} />
      </aside>
    </div>
  );
}

function Info({ label, value, strong = false }: { label: string; value: string; strong?: boolean }) {
  return (
    <div>
      <p className="text-xs text-[var(--ch-text-muted)]">{label}</p>
      <p className={`mt-1 text-sm ${strong ? "font-bold text-[var(--ch-accent)]" : "font-medium text-[var(--ch-text-primary)]"}`}>{value}</p>
    </div>
  );
}

function explainFlag(flag: string): string {
  const map: Record<string, string> = {
    OVER_DRAWN: "Already drawn exceeds the cumulative stage entitlement. No new draw is available.",
    FACILITY_NOT_SET: "Facility values are missing. Add total facility and opening balance.",
    NOT_STARTED: "Stage is blank or NA, so no draw is available.",
    CHECK_OTP: "Client lender terms vary by property. Upload/review the OTP and use Prep Draw.",
    NO_PROGRESS_REPORT: "Calculation uses the stage estimate because no Red River progress report is recorded.",
    NEEDS_LINK: "This lender facility is visible but has not been linked to a master property yet.",
    SYNC_CONFLICT: "The stage sync has a conflicting Sheet row for this property.",
  };
  return map[flag] || flag;
}
