import Link from "next/link";

import type { AllocationRequest, ProgramDetail } from "@/types/program-allocations";


interface ProgramCapacityPanelProps {
  programs: ProgramDetail[];
  loading: boolean;
  error?: string | null;
}


export function ProgramCapacityPanel({ programs, loading, error }: ProgramCapacityPanelProps) {
  if (loading) {
    return (
      <section className="animate-pulse rounded-xl border border-[var(--ch-border)] bg-[var(--ch-surface)] p-5">
        <div className="h-6 w-48 rounded bg-[var(--ch-surface-muted)]" />
        <div className="mt-5 h-24 rounded bg-[var(--ch-surface-muted)]" />
      </section>
    );
  }
  if (error) {
    return <section className="rounded-xl border border-[var(--ch-error-border)] bg-[var(--ch-error-bg)] p-5 text-sm text-[var(--ch-error-text)]">{error}</section>;
  }
  if (programs.length === 0) {
    return (
      <section className="rounded-xl border border-[var(--ch-border)] bg-[var(--ch-surface)] p-5">
        <h2 className="text-lg font-semibold">Programs and capacity</h2>
        <p className="mt-2 text-sm text-[var(--ch-text-muted)]">No lender programs are configured yet.</p>
      </section>
    );
  }
  return (
    <section className="space-y-5">
      <div>
        <h2 className="text-xl font-semibold">Programs and capacity</h2>
        <p className="mt-1 text-sm text-[var(--ch-text-muted)]">Program limits are warnings for planning; tier slots are advisory only.</p>
      </div>
      {programs.map((program) => {
        const percent = progress(program.consumed, program.umbrella_limit);
        return (
          <article key={program.id} className="overflow-hidden rounded-xl border border-[var(--ch-border)] bg-[var(--ch-surface)]">
            <div className="border-b border-[var(--ch-border)] p-5">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <div className="flex items-center gap-2">
                    <h3 className="text-lg font-semibold">{program.name}</h3>
                    <span className="rounded-full border border-[var(--ch-border)] px-2 py-0.5 text-xs text-[var(--ch-text-muted)]">{program.active ? "Active" : "Inactive"}</span>
                  </div>
                  {program.notes ? <p className="mt-1 text-sm text-[var(--ch-text-muted)]">{program.notes}</p> : null}
                </div>
                <div className="text-right text-sm">
                  <p className="font-semibold">{money(program.remaining)} remaining</p>
                  <p className="text-[var(--ch-text-muted)]">{money(program.consumed)} of {money(program.umbrella_limit)}</p>
                </div>
              </div>
              <div className="mt-4 h-2 overflow-hidden rounded-full bg-[var(--ch-surface-muted)]" role="progressbar" aria-valuenow={percent} aria-valuemin={0} aria-valuemax={100}>
                <div className="h-full rounded-full bg-[var(--ch-accent)]" style={{ width: `${percent}%` }} />
              </div>
            </div>

            <div className="grid gap-4 p-5 lg:grid-cols-2">
              {program.allocations.map((allocation) => (
                <div key={allocation.id} className="rounded-lg border border-[var(--ch-border)] p-4">
                  <div className="flex justify-between gap-3">
                    <div>
                      <h4 className="font-semibold">{allocation.name}</h4>
                      <p className="mt-1 text-xs text-[var(--ch-text-muted)]">{allocation.units_used} of {allocation.max_units} units used</p>
                    </div>
                    <div className="text-right text-sm">
                      <p className="font-medium">{money(allocation.remaining)} remaining</p>
                      <p className="text-xs text-[var(--ch-text-muted)]">{money(allocation.consumed)} / {money(allocation.allocation_limit)}</p>
                    </div>
                  </div>
                  <div className="mt-3 h-2 overflow-hidden rounded-full bg-[var(--ch-surface-muted)]">
                    <div className="h-full bg-[var(--ch-accent)]" style={{ width: `${progress(allocation.consumed, allocation.allocation_limit)}%` }} />
                  </div>
                  {allocation.max_per_unit != null ? <p className="mt-3 text-xs text-[var(--ch-text-muted)]">Maximum per unit: {money(allocation.max_per_unit)}</p> : null}
                  {allocation.tiers.length > 0 ? (
                    <div className="mt-4 overflow-x-auto">
                      <div className="mb-2 flex items-center gap-2">
                        <p className="text-xs font-semibold uppercase tracking-wide text-[var(--ch-text-muted)]">Tier reference</p>
                        <span className="rounded bg-[var(--ch-surface-muted)] px-1.5 py-0.5 text-[10px] font-semibold uppercase text-[var(--ch-text-muted)]">Advisory</span>
                      </div>
                      <table className="w-full text-left text-xs">
                        <thead className="text-[var(--ch-text-muted)]"><tr><th className="pb-2">Tier</th><th className="pb-2">Slots</th><th className="pb-2">Remaining</th></tr></thead>
                        <tbody className="divide-y divide-[var(--ch-border)]">
                          {allocation.tiers.map((tier) => <tr key={tier.id}><td className="py-2">{money(tier.face_value)}{tier.label ? ` · ${tier.label}` : ""}</td><td className="py-2">{tier.slots_occupied}/{tier.slot_count}</td><td className="py-2">{tier.slots_remaining}</td></tr>)}
                        </tbody>
                      </table>
                    </div>
                  ) : null}
                </div>
              ))}
            </div>

            <div className="border-t border-[var(--ch-border)]">
              <div className="px-5 py-3"><h4 className="font-semibold">Current allocation requests</h4></div>
              {program.requests.length === 0 ? (
                <p className="px-5 pb-5 text-sm text-[var(--ch-text-muted)]">No allocation requests yet.</p>
              ) : (
                <div className="divide-y divide-[var(--ch-border)]">
                  {program.requests.map((request) => <RequestRow key={request.id} request={request} />)}
                </div>
              )}
            </div>
          </article>
        );
      })}
    </section>
  );
}


function RequestRow({ request }: { request: AllocationRequest }) {
  const content = (
    <>
      <div>
        <p className="font-medium">{request.address}</p>
        <div className="mt-1 flex flex-wrap gap-1.5">
          <span className="rounded-full bg-[var(--ch-surface-muted)] px-2 py-0.5 text-xs capitalize">{request.status}</span>
          {request.flags.map((flag) => <span key={flag} className="rounded-full border border-[var(--ch-warning-border)] bg-[var(--ch-warning-bg)] px-2 py-0.5 text-xs text-[var(--ch-warning-text)]">{flagLabel(flag)}</span>)}
        </div>
      </div>
      <div className="text-right text-sm">
        <p className="font-semibold">{money(request.actual_amount ?? request.suggested_amount)}</p>
        <p className="text-xs text-[var(--ch-text-muted)]">Suggested {money(request.suggested_amount)}</p>
      </div>
    </>
  );
  return request.property_id ? (
    <Link href={`/financing?property_id=${request.property_id}`} className="flex items-start justify-between gap-4 px-5 py-4 hover:bg-[var(--ch-surface-muted)]">{content}</Link>
  ) : (
    <div className="flex items-start justify-between gap-4 px-5 py-4">{content}</div>
  );
}


function money(value: string | number | null | undefined): string {
  return new Intl.NumberFormat("en-CA", { style: "currency", currency: "CAD", maximumFractionDigits: 0 }).format(Number(value || 0));
}


function progress(consumed: string | number, limit: string | number): number {
  const denominator = Number(limit);
  if (denominator <= 0) return 0;
  return Math.min(100, Math.max(0, Math.round((Number(consumed) / denominator) * 100)));
}


function flagLabel(flag: string): string {
  return flag.replaceAll("_", " ");
}
