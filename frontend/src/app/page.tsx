"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { getDashboard, type DashboardData } from "@/lib/api/workspace";
import { stageLabel } from "@/lib/api/clients";
import { Card, Empty, ErrorNote, PageShell, Stat, formatDate } from "./components/WorkspaceUi";

const TENDER_STATUS: Record<string, string> = { draft: "Draft", sent: "Sent", bids_in: "Bids in", compared: "Compared" };

export default function DashboardPage() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    getDashboard().then(setData).catch((err: unknown) => setError(err instanceof Error ? err.message : "Dashboard unavailable"));
  }, []);

  return (
    <PageShell title="Dashboard" subtitle={data ? data.org.name : undefined}>
      <ErrorNote message={error} />
      {!data && !error ? <p className="text-sm text-[var(--ch-text-muted)]">Loading…</p> : null}
      {data ? (
        <div className="space-y-6">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Stat label="Projects" value={data.projects.total} href="/projects" />
            <Stat label="Active" value={data.projects.by_status.active ?? 0} href="/projects" />
            <Stat label="Tenders needing action" value={data.tenders.total} />
            <Stat label="Possessions in 90 days" value={data.upcoming_possessions.length} />
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <Card title="Active projects" action={<Link href="/projects" className="text-xs text-[var(--ch-accent)]">All projects</Link>}>
              {data.projects.active.length === 0 ? <Empty>No active projects.</Empty> : (
                <ul className="divide-y divide-[var(--ch-border)]">
                  {data.projects.active.map((project) => (
                    <li key={project.id} className="py-2">
                      <Link href={`/projects/${project.id}`} className="flex items-start justify-between gap-3 text-sm hover:text-[var(--ch-accent)]">
                        <span className="min-w-0">
                          <span className="block truncate font-medium">{project.address}</span>
                          <span className="block truncate text-xs text-[var(--ch-text-muted)]">{project.community}{project.client_name ? ` · ${project.client_name}` : ""}</span>
                        </span>
                        <span className="shrink-0 text-xs text-[var(--ch-text-muted)]">{project.possession_date ? `Possession ${formatDate(project.possession_date)}` : project.status}</span>
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </Card>

            <Card title="Tenders needing action">
              {data.tenders.items.length === 0 ? <Empty>No open tender packages.</Empty> : (
                <ul className="divide-y divide-[var(--ch-border)]">
                  {data.tenders.items.map((tender) => (
                    <li key={tender.id} className="py-2">
                      <Link href={`/projects/${tender.lot_id}?tab=tendering`} className="flex items-start justify-between gap-3 text-sm hover:text-[var(--ch-accent)]">
                        <span className="min-w-0">
                          <span className="block truncate font-medium">{tender.category} · {tender.address}</span>
                          <span className="block truncate text-xs text-[var(--ch-text-muted)]">{tender.scope_description}</span>
                        </span>
                        <span className="shrink-0 text-right text-xs text-[var(--ch-text-muted)]">
                          {TENDER_STATUS[tender.status] || tender.status} · {tender.bids_received}/3 bids
                          <span className="block">Due {formatDate(tender.due_date)}</span>
                        </span>
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </Card>

            <Card title="Upcoming possessions (90 days)">
              {data.upcoming_possessions.length === 0 ? <Empty>No possessions scheduled in the next 90 days.</Empty> : (
                <ul className="divide-y divide-[var(--ch-border)]">
                  {data.upcoming_possessions.map((item) => (
                    <li key={item.lot_id} className="py-2">
                      <Link href={`/projects/${item.lot_id}`} className="flex justify-between gap-3 text-sm hover:text-[var(--ch-accent)]">
                        <span className="min-w-0 truncate">{item.address}{item.client_name ? ` · ${item.client_name}` : ""}</span>
                        <span className="shrink-0 text-xs text-[var(--ch-text-muted)]">{formatDate(item.possession_date)} · {item.days_until}d</span>
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </Card>

            {data.otp_milestones ? (
              <Card title="OTP milestones (next 30 days)" action={<Link href="/lots/timeline" className="text-xs text-[var(--ch-accent)]">Timeline</Link>}>
                <p className="mb-2 text-xs text-[var(--ch-text-muted)]">{data.otp_milestones.overdue} overdue · {data.otp_milestones.next_30_days} upcoming</p>
                {data.otp_milestones.items.length === 0 ? <Empty>No OTP milestones due.</Empty> : (
                  <ul className="divide-y divide-[var(--ch-border)]">
                    {data.otp_milestones.items.map((event) => (
                      <li key={event.id} className="flex justify-between gap-3 py-2 text-sm">
                        <span className="min-w-0 truncate">{event.event_label} · {event.address}</span>
                        <span className={`shrink-0 text-xs ${event.urgency === "overdue" ? "text-[var(--ch-error-text)]" : "text-[var(--ch-text-muted)]"}`}>{formatDate(event.event_date)}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </Card>
            ) : null}

            {data.clients ? (
              <Card title="Clients" action={<Link href="/clients" className="text-xs text-[var(--ch-accent)]">All clients</Link>}>
                {Object.keys(data.clients.by_stage).length === 0 ? <Empty>No client records yet.</Empty> : (
                  <>
                    <div className="mb-3 flex flex-wrap gap-2">
                      {Object.entries(data.clients.by_stage).map(([stage, count]) => (
                        <span key={stage} className="rounded-full border border-[var(--ch-border)] px-2 py-1 text-xs">{stageLabel(stage)} · {count}</span>
                      ))}
                    </div>
                    <ul className="divide-y divide-[var(--ch-border)]">
                      {data.clients.recent_stage_changes.map((client) => (
                        <li key={client.id} className="py-2">
                          <Link href={`/clients/${client.id}`} className="flex justify-between gap-3 text-sm hover:text-[var(--ch-accent)]">
                            <span className="truncate">{client.display_name}</span>
                            <span className="shrink-0 text-xs text-[var(--ch-text-muted)]">{stageLabel(client.lifecycle_stage)} · {formatDate(client.stage_changed_at)}</span>
                          </Link>
                        </li>
                      ))}
                    </ul>
                  </>
                )}
              </Card>
            ) : null}

            {data.rentals ? (
              <Card title="Rentals" action={<Link href="/rentals" className="text-xs text-[var(--ch-accent)]">Overview</Link>}>
                <div className="grid grid-cols-2 gap-2 text-sm">
                  <p>{data.rentals.properties} properties · {data.rentals.units} units</p>
                  <p>{data.rentals.maintenance_open} open maintenance tickets</p>
                  <p>{data.rentals.leases_expiring_90_days} leases ending in 90 days</p>
                  <p>{data.rentals.lease_agreements_awaiting_signature} leases awaiting signature</p>
                </div>
              </Card>
            ) : null}
          </div>
        </div>
      ) : null}
    </PageShell>
  );
}
