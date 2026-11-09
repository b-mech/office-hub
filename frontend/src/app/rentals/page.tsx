"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { getRentalsOverview, type RentalsOverview } from "@/lib/api/workspace";
import { Card, Empty, ErrorNote, PageShell, Stat, formatDate } from "../components/WorkspaceUi";

const PRIORITY_ORDER = ["emergency", "urgent", "routine", "low"];
const label = (value: string) => value.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());

export default function RentalsOverviewPage() {
  const [data, setData] = useState<RentalsOverview | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    getRentalsOverview().then(setData).catch((err: unknown) => setError(err instanceof Error ? err.message : "Rentals overview unavailable"));
  }, []);

  return (
    <PageShell
      title="Rentals"
      subtitle={data?.scope_note}
      actions={<div className="flex gap-2 text-xs"><Link className="rounded-md border border-[var(--ch-border)] px-3 py-2" href="/rentals/map">Map</Link><Link className="rounded-md border border-[var(--ch-border)] px-3 py-2" href="/rentals/inspections">Inspections</Link><Link className="rounded-md border border-[var(--ch-border)] px-3 py-2" href="/rentals/lease-import">Lease import</Link></div>}
    >
      <ErrorNote message={error} />
      {!data && !error ? <p className="text-sm text-[var(--ch-text-muted)]">Loading…</p> : null}
      {data ? (
        <div className="space-y-6">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Stat label="Properties" value={data.properties} href="/rentals/map" />
            <Stat label="Units" value={data.units} />
            <Stat label="Occupancy" value={data.occupancy} hint="Unit status is not maintained" />
            <Stat label="Rent collected" value={data.rent_collected} hint="No payments data in Office Hub" />
          </div>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Stat label="Leases awaiting signature" value={data.lease_agreements_awaiting_signature} />
            <Stat label="Open lease follow-ups" value={data.lease_agreement_open_tasks} />
            <Stat label="Leases ending in 90 days" value={data.leases_expiring_90_days_count} />
            <Stat label="Open maintenance" value={Object.values(data.maintenance_open_by_priority).reduce((a, b) => a + b, 0)} />
          </div>
          <div className="grid gap-4 lg:grid-cols-2">
            <Card title="Lease records">
              <div className="space-y-3 text-sm">
                <div>
                  <p className="mb-1 text-xs text-[var(--ch-text-muted)]">Imported leases by status</p>
                  {Object.keys(data.rental_leases_by_status).length === 0 ? <Empty>No lease records.</Empty> : (
                    <div className="flex flex-wrap gap-2">{Object.entries(data.rental_leases_by_status).map(([status, count]) => <span key={status} className="rounded-full border border-[var(--ch-border)] px-2 py-1 text-xs">{label(status)} · {count}</span>)}</div>
                  )}
                </div>
                <div>
                  <p className="mb-1 text-xs text-[var(--ch-text-muted)]">Lease agreements (DocuSign) by status</p>
                  {Object.keys(data.lease_agreements_by_status).length === 0 ? <Empty>No lease agreements yet.</Empty> : (
                    <div className="flex flex-wrap gap-2">{Object.entries(data.lease_agreements_by_status).map(([status, count]) => <span key={status} className="rounded-full border border-[var(--ch-border)] px-2 py-1 text-xs">{label(status)} · {count}</span>)}</div>
                  )}
                </div>
              </div>
            </Card>
            <Card title="Leases ending in 90 days">
              {data.leases_expiring_90_days.length === 0 ? <Empty>No active leases end in the next 90 days.</Empty> : (
                <ul className="divide-y divide-[var(--ch-border)]">
                  {data.leases_expiring_90_days.map((lease) => (
                    <li key={lease.id} className="py-2">
                      <Link href={`/rentals/units/${lease.unit_id}`} className="flex justify-between gap-3 text-sm hover:text-[var(--ch-accent)]">
                        <span className="truncate">{lease.street_address} · {lease.unit_label}</span>
                        <span className="shrink-0 text-xs text-[var(--ch-text-muted)]">{formatDate(lease.lease_end)} · {lease.days_until}d</span>
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
            <Card title="Maintenance needing attention" className="lg:col-span-2">
              <div className="mb-3 flex flex-wrap gap-2">
                {PRIORITY_ORDER.map((priority) => <span key={priority} className="rounded-full border border-[var(--ch-border)] px-2 py-1 text-xs">{label(priority)} · {data.maintenance_open_by_priority[priority] ?? 0}</span>)}
              </div>
              {data.maintenance_open_tickets.length === 0 ? <Empty>No open maintenance tickets.</Empty> : (
                <ul className="divide-y divide-[var(--ch-border)]">
                  {data.maintenance_open_tickets.map((ticket) => (
                    <li key={ticket.id} className="flex justify-between gap-3 py-2 text-sm">
                      <span className="min-w-0 truncate">{ticket.number} · {ticket.title}{ticket.street_address ? ` · ${ticket.street_address}` : ""}{ticket.unit_label ? ` ${ticket.unit_label}` : ""}</span>
                      <span className="shrink-0 text-xs text-[var(--ch-text-muted)]">{label(ticket.priority)} · {label(ticket.status)}{ticket.sla_due_at ? ` · SLA ${formatDate(ticket.sla_due_at)}` : ""}</span>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          </div>
        </div>
      ) : null}
    </PageShell>
  );
}
