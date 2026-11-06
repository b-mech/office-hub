"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { getLots, type Lot } from "@/lib/api/costbook";
import { getOtpTimeline, type TimelineEvent } from "@/lib/api/lots";
import { Card, Empty, ErrorNote, PageShell, Stat, formatDate } from "../components/WorkspaceUi";

// Land overview: lot counts and the OTP pipeline, from /api/v1/lots and
// /api/v1/lots/timeline (both tenant-enforced). Detail lives under /lots.

const LIFECYCLE: { key: Lot["lifecycle_status"]; label: string }[] = [
  { key: "land_contracted", label: "Land contracted" },
  { key: "land_purchased", label: "Land purchased" },
  { key: "serviced", label: "Serviced" },
  { key: "sale_signed", label: "Sale signed" },
  { key: "build_active", label: "Build active" },
  { key: "possession", label: "Possession" },
  { key: "warranty", label: "Warranty" },
];

const URGENCY_CLASS: Record<TimelineEvent["urgency"], string> = {
  overdue: "text-[var(--ch-error-text)]",
  soon: "text-[var(--ch-warning-text)]",
  upcoming: "text-[var(--ch-text-muted)]",
};

const errorMessage = (reason: unknown, fallback: string) => (reason instanceof Error ? reason.message : fallback);

export default function LandOverviewPage() {
  const [lots, setLots] = useState<Lot[] | null>(null);
  const [events, setEvents] = useState<TimelineEvent[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [timelineError, setTimelineError] = useState<string | null>(null);

  useEffect(() => {
    Promise.allSettled([getLots(), getOtpTimeline()]).then(([lotsResult, timelineResult]) => {
      if (lotsResult.status === "fulfilled") setLots(lotsResult.value);
      else setError(errorMessage(lotsResult.reason, "Land overview unavailable"));
      if (timelineResult.status === "fulfilled") setEvents(timelineResult.value);
      else setTimelineError(errorMessage(timelineResult.reason, "OTP timeline unavailable"));
    });
  }, []);

  const open = lots?.filter((lot) => !lot.cancelled) ?? [];
  const count = (predicate: (lot: Lot) => boolean) => open.filter(predicate).length;
  const upcoming = (events ?? []).slice().sort((a, b) => a.days_until - b.days_until).slice(0, 8);
  const overdue = (events ?? []).filter((event) => event.urgency === "overdue").length;

  return (
    <PageShell
      title="Land"
      subtitle="Lots, OTP milestones and the sales pipeline"
      actions={<div className="flex gap-2 text-xs"><Link className="rounded-md border border-[var(--ch-border)] px-3 py-2" href="/lots">Lots</Link><Link className="rounded-md border border-[var(--ch-border)] px-3 py-2" href="/lots/map">Map</Link><Link className="rounded-md border border-[var(--ch-border)] px-3 py-2" href="/lots/timeline">OTP timeline</Link></div>}
    >
      <ErrorNote message={error} />
      {!lots && !error ? <p className="text-sm text-[var(--ch-text-muted)]">Loading…</p> : null}
      {lots ? (
        <div className="space-y-6">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Stat label="Lots" value={open.length} href="/lots" hint={lots.length !== open.length ? `${lots.length - open.length} cancelled not counted` : undefined} />
            <Stat label="Inventory" value={count((lot) => lot.status === "inventory")} />
            <Stat label="Active" value={count((lot) => lot.status === "active")} />
            <Stat label="On hold" value={count((lot) => lot.on_hold || lot.status === "hold")} />
          </div>
          <div className="grid gap-4 lg:grid-cols-2">
            <Card title="Pipeline">
              {open.length === 0 ? <Empty>No lots.</Empty> : (
                <ul className="divide-y divide-[var(--ch-border)]">
                  {LIFECYCLE.map((stage) => (
                    <li key={stage.key} className="flex justify-between py-2 text-sm">
                      <span>{stage.label}</span>
                      <span className="font-semibold">{count((lot) => lot.lifecycle_status === stage.key)}</span>
                    </li>
                  ))}
                </ul>
              )}
              <div className="mt-3 flex flex-wrap gap-2 text-xs">
                {(["presale", "spec", "showhome"] as const).map((type) => (
                  <span key={type} className="rounded-full border border-[var(--ch-border)] px-2 py-1">
                    {type === "showhome" ? "Show home" : type === "presale" ? "Presale" : "Spec"} · {count((lot) => lot.sale_type === type)}
                  </span>
                ))}
              </div>
            </Card>
            <Card
              title={overdue > 0 ? `OTP milestones · ${overdue} overdue` : "OTP milestones"}
              action={<Link href="/lots/timeline" className="text-xs text-[var(--ch-accent)]">Timeline</Link>}
            >
              {timelineError ? <ErrorNote message={timelineError} /> : null}
              {!events && !timelineError ? <p className="text-sm text-[var(--ch-text-muted)]">Loading…</p> : null}
              {events && upcoming.length === 0 ? <Empty>No upcoming OTP milestones.</Empty> : null}
              {upcoming.length > 0 ? (
                <ul className="divide-y divide-[var(--ch-border)]">
                  {upcoming.map((event) => (
                    <li key={event.id} className="py-2">
                      <Link href={`/lots/${event.lot_id}`} className="flex justify-between gap-3 text-sm hover:text-[var(--ch-accent)]">
                        <span className="min-w-0 truncate">{event.address} · {event.event_label}</span>
                        <span className={`shrink-0 text-xs ${URGENCY_CLASS[event.urgency]}`}>
                          {formatDate(event.event_date)} · {event.days_until < 0 ? `${-event.days_until}d overdue` : `${event.days_until}d`}
                        </span>
                      </Link>
                    </li>
                  ))}
                </ul>
              ) : null}
            </Card>
          </div>
        </div>
      ) : null}
    </PageShell>
  );
}
