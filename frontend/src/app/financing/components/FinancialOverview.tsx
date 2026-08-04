import Link from "next/link";
import { useEffect, useState } from "react";
import { Building2, ClipboardCheck, FileSignature, Landmark } from "lucide-react";

import { getPropertyFinancialSummary, type PropertyFinancialSummary } from "@/lib/api/financial-summaries";
import type { FinancingProperty } from "@/types/financing";

const money = new Intl.NumberFormat("en-CA", {
  style: "currency",
  currency: "CAD",
  maximumFractionDigits: 0,
});

function amount(value: string | number | null | undefined): string {
  return value == null ? "—" : money.format(Number(value));
}

export function FinancialOverview({
  property,
  onAssign,
}: {
  property: FinancingProperty;
  onAssign: () => void;
}) {
  const [summary, setSummary] = useState<PropertyFinancialSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    getPropertyFinancialSummary(property.property_id)
      .then((result) => {
        if (active) setSummary(result);
      })
      .catch((loadError) => {
        if (active) setError(loadError instanceof Error ? loadError.message : "Could not load financial overview");
      });
    return () => {
      active = false;
    };
  }, [property.property_id, property.facility_id]);

  return (
    <section className="mb-4 rounded-xl border border-[var(--ch-border)] bg-[var(--ch-surface)] p-4" aria-labelledby="financial-overview-title">
      <div className="mb-3">
        <h3 id="financial-overview-title" className="text-sm font-semibold">Financial Overview</h3>
        <p className="mt-1 text-xs text-[var(--ch-text-muted)]">Current financing, draw, OTP, and change-order status.</p>
      </div>
      {error ? <p className="rounded-md bg-[var(--ch-error-bg)] px-3 py-2 text-sm text-[var(--ch-error-text)]">{error}</p> : null}
      {!summary && !error ? <OverviewSkeleton /> : null}
      {summary ? (
        <div className="grid gap-3 sm:grid-cols-2">
          <OverviewCard icon={<Landmark size={17} />} title="Lender">
            {summary.lender.has_lender ? (
              <Link href={summary.lender.lender_id ? `/financing/lenders/${summary.lender.lender_id}` : `/financing?property_id=${property.property_id}`} className="block focus:outline-none">
                <span className="inline-flex rounded-full bg-[var(--ch-accent-soft)] px-2 py-1 text-xs font-semibold text-[var(--ch-accent)]">{summary.lender.facility_type}</span>
                <p className="mt-2 font-semibold">{summary.lender.lender_name || "Lender name unavailable"}</p>
              </Link>
            ) : (
              <div>
                <p className="text-sm text-[var(--ch-text-secondary)]">No lender assigned yet</p>
                <button type="button" onClick={onAssign} className="mt-3 rounded-md bg-[var(--ch-accent)] px-3 py-2 text-xs font-semibold text-[var(--ch-accent-text)]">Assign lender</button>
              </div>
            )}
          </OverviewCard>

          <OverviewCard icon={<Building2 size={17} />} title="Draw status" href={`/financing?property_id=${property.property_id}#draw-details`}>
            {summary.draw ? (
              <>
                <p className="text-sm font-semibold">{summary.draw.current_stage || "Stage unavailable"}</p>
                <p className="mt-2 text-xs text-[var(--ch-text-muted)]">Next eligible draw</p>
                <p className="font-semibold text-[var(--ch-accent)]">{amount(summary.draw.next_eligible_draw)}</p>
                <BalanceProgress opening={summary.draw.opening_balance} remaining={summary.draw.remaining} />
                <p className="mt-2 text-xs text-[var(--ch-text-muted)]">{summary.draw.facility_document_count ? `${summary.draw.facility_document_count} facility document${summary.draw.facility_document_count === 1 ? "" : "s"} on file` : "No facility documents on file"}</p>
              </>
            ) : <p className="text-sm text-[var(--ch-text-muted)]">Assign a lender to see draw status.</p>}
          </OverviewCard>

          <OverviewCard icon={<ClipboardCheck size={17} />} title="Prep Draw" href="#prep-draw">
            <p className="text-sm font-semibold">{prepLabel(summary.prep_draw.state)}</p>
            <span className={`mt-2 inline-flex rounded-full px-2 py-1 text-xs font-semibold ${summary.prep_draw.ready_to_request ? "bg-[var(--ch-success-bg)] text-[var(--ch-success-text)]" : "bg-[var(--ch-surface-muted)] text-[var(--ch-text-secondary)]"}`}>
              {summary.prep_draw.ready_to_request ? "Ready to request" : "Not ready"}
            </span>
          </OverviewCard>

          <OverviewCard icon={<FileSignature size={17} />} title="Change Orders" href={`/projects/change-orders?property_id=${property.property_id}&address=${encodeURIComponent(property.address)}`}>
            {summary.change_orders.count ? (
              <>
                <p className="text-sm font-semibold">{summary.change_orders.pending_signature_count} pending signature</p>
                <p className="mt-1 text-lg font-bold">{amount(summary.change_orders.total_value)}</p>
                <p className="mt-2 text-xs text-[var(--ch-text-muted)]">{boxLabel(summary.change_orders)}</p>
              </>
            ) : <p className="text-sm text-[var(--ch-text-muted)]">No change orders for this property.</p>}
          </OverviewCard>
        </div>
      ) : null}
    </section>
  );
}

function OverviewCard({ icon, title, href, children }: { icon: React.ReactNode; title: string; href?: string; children: React.ReactNode }) {
  const content = <><div className="mb-3 flex items-center gap-2 text-[var(--ch-text-secondary)]">{icon}<h4 className="text-xs font-semibold uppercase tracking-wide">{title}</h4></div>{children}</>;
  const classes = "rounded-lg border border-[var(--ch-border)] bg-[var(--ch-surface-muted)] p-4 transition hover:border-[var(--ch-accent)]";
  return href ? <Link href={href} className={classes}>{content}</Link> : <div className={classes}>{content}</div>;
}

function BalanceProgress({ opening, remaining }: { opening?: string | number | null; remaining?: string | number | null }) {
  const total = Number(opening || 0);
  const left = Number(remaining || 0);
  const percent = total > 0 ? Math.max(0, Math.min(100, (left / total) * 100)) : 0;
  return <div className="mt-3"><div className="mb-1 flex justify-between text-xs text-[var(--ch-text-muted)]"><span>Remaining</span><span>{amount(remaining)}</span></div><div className="h-2 overflow-hidden rounded-full bg-[var(--ch-border)]"><div className="h-full rounded-full bg-[var(--ch-accent)]" style={{ width: `${percent}%` }} /></div></div>;
}

function prepLabel(state: PropertyFinancialSummary["prep_draw"]["state"]): string {
  if (state === "ready_to_request") return "Ready to request";
  if (state === "pending_review") return "Draw schedule pending review";
  return "No active schedule";
}

function boxLabel(summary: PropertyFinancialSummary["change_orders"]): string {
  if (summary.box_unfiled) return "Filed to Box unfiled folder";
  if (summary.box_filed) return "Filed in Box";
  return "Not filed in Box";
}

function OverviewSkeleton() {
  return <div className="grid gap-3 sm:grid-cols-2" aria-label="Loading financial overview">{Array.from({ length: 4 }).map((_, index) => <div key={index} className="h-36 animate-pulse rounded-lg bg-[var(--ch-surface-muted)]" />)}</div>;
}
