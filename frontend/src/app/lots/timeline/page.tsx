"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { getOtpTimeline, type TimelineEvent } from "@/lib/api/lots";

type TimelineFilter = "deposits" | "conditionals" | "possession" | "other";

const FILTERS: Array<{ id: TimelineFilter; label: string; types: string[] }> = [
  { id: "deposits", label: "Deposits", types: ["deposit_1", "deposit_2", "deposit_3"] },
  { id: "conditionals", label: "Conditionals", types: ["conditional_removal", "firm_sale"] },
  { id: "possession", label: "Possession", types: ["possession"] },
  { id: "other", label: "Other", types: ["other"] },
];

const urgencyStyles = {
  overdue: {
    card: "border border-red-400/20 border-l-4 border-l-red-400 bg-[var(--ch-error-bg)]",
    badge: "bg-[var(--ch-error-bg)] text-[var(--ch-error-text)] border-[var(--ch-error-border)]",
  },
  soon: {
    card: "border border-amber-400/20 border-l-4 border-l-amber-400 bg-[var(--ch-warning-bg)]",
    badge: "bg-[var(--ch-warning-bg)] text-[var(--ch-warning-text)] border-[var(--ch-warning-border)]",
  },
  upcoming: {
    card: "border border-[var(--ch-border)] border-l-4 border-l-white/10 bg-[var(--ch-surface)]",
    badge: "bg-[var(--ch-surface)] text-[var(--ch-text-muted)] border-[var(--ch-border)]",
  },
} satisfies Record<TimelineEvent["urgency"], { card: string; badge: string }>;

function parseDateParts(value: string) {
  const [year, month, day] = value.split("-").map(Number);
  return { year, month, day };
}

function formatDate(value: string) {
  const { year, month, day } = parseDateParts(value);
  return new Date(year, month - 1, day).toLocaleDateString("en-CA", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function monthLabel(value: string) {
  const { year, month } = parseDateParts(value);
  return new Date(year, month - 1, 1).toLocaleDateString("en-CA", {
    month: "long",
    year: "numeric",
  }).toUpperCase();
}

function relativeLabel(event: TimelineEvent) {
  if (event.days_until < 0) return `${Math.abs(event.days_until)} DAYS OVERDUE`;
  if (event.days_until === 0) return "TODAY";
  if (event.days_until <= 14) return `IN ${event.days_until} DAYS`;
  return "";
}

function badgeText(event: TimelineEvent) {
  if (event.urgency === "overdue") return "OVERDUE";
  if (event.urgency === "soon") return event.days_until === 0 ? "TODAY" : `IN ${event.days_until} DAYS`;
  return formatDate(event.event_date);
}

function formatCurrency(value: number | null) {
  if (value == null) return "";
  return new Intl.NumberFormat("en-CA", {
    style: "currency",
    currency: "CAD",
    maximumFractionDigits: 0,
  }).format(Number(value));
}

function isActiveFilterMatch(event: TimelineEvent, filters: TimelineFilter[]) {
  if (filters.length === 0) return true;
  return filters.some((filter) => {
    const config = FILTERS.find((item) => item.id === filter);
    return config ? config.types.includes(event.event_type) : false;
  });
}

function SkeletonMonth() {
  return (
    <section>
      <div className="mb-3 flex items-center gap-4">
        <div className="h-3 w-24 rounded bg-[var(--ch-surface)]" />
        <div className="h-px flex-1 bg-[var(--ch-surface)]" />
      </div>
      <div className="space-y-3">
        {Array.from({ length: 3 }).map((_, index) => (
          <div key={index} className="h-24 animate-pulse rounded-xl border border-[var(--ch-border)] bg-[var(--ch-surface)]" />
        ))}
      </div>
    </section>
  );
}

function TimelineCard({ event }: { event: TimelineEvent }) {
  const router = useRouter();
  const relative = relativeLabel(event);

  return (
    <button
      type="button"
      onClick={() => router.push(`/lots/${event.lot_id}`)}
      className={`w-full rounded-xl p-4 text-left transition hover:brightness-110 ${urgencyStyles[event.urgency].card}`}
    >
      <div className="mb-3 flex flex-wrap items-center gap-2 text-xs">
        <span className={`rounded-full border px-2.5 py-1 font-bold tracking-wider ${urgencyStyles[event.urgency].badge}`}>
          {badgeText(event)}
        </span>
        {relative && <span className="font-semibold tracking-wider text-[var(--ch-text-muted)]">{relative}</span>}
        <span className="text-[var(--ch-text-muted)]">·</span>
        <span className="text-[var(--ch-text-muted)]">{formatDate(event.event_date)}</span>
      </div>

      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="truncate text-base font-semibold text-[var(--ch-text-primary)]">
            {event.address} <span className="text-[var(--ch-text-muted)]">—</span> {event.event_label}
          </p>
          <p className="mt-2 truncate text-sm text-[var(--ch-text-muted)]">{event.client_name || "No client recorded"}</p>
        </div>
        {event.amount != null && (
          <p className="shrink-0 text-right text-sm font-bold text-[var(--ch-accent)]">
            {formatCurrency(event.amount)}
          </p>
        )}
      </div>
    </button>
  );
}

export default function OtpTimelinePage() {
  const [events, setEvents] = useState<TimelineEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeFilters, setActiveFilters] = useState<TimelineFilter[]>([]);
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");

  useEffect(() => {
    const timer = window.setTimeout(() => setSearch(searchInput.trim().toLowerCase()), 300);
    return () => window.clearTimeout(timer);
  }, [searchInput]);

  useEffect(() => {
    let cancelled = false;
    getOtpTimeline()
      .then((timelineEvents) => {
        if (!cancelled) setEvents(timelineEvents);
      })
      .catch((loadError) => {
        if (!cancelled) setError(loadError instanceof Error ? loadError.message : "Could not load OTP timeline.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const filteredEvents = useMemo(() => {
    return events.filter((event) => {
      const matchesType = isActiveFilterMatch(event, activeFilters);
      const searchable = `${event.address} ${event.client_name}`.toLowerCase();
      return matchesType && (!search || searchable.includes(search));
    });
  }, [activeFilters, events, search]);

  const groupedEvents = useMemo(() => {
    return filteredEvents.reduce<Record<string, TimelineEvent[]>>((groups, event) => {
      const label = monthLabel(event.event_date);
      (groups[label] = groups[label] || []).push(event);
      return groups;
    }, {});
  }, [filteredEvents]);

  function toggleFilter(filter: TimelineFilter) {
    setActiveFilters((current) =>
      current.includes(filter)
        ? current.filter((item) => item !== filter)
        : [...current, filter]
    );
  }

  return (
    <div className="min-h-screen bg-[var(--ch-page-bg)] px-8 py-8 text-[var(--ch-text-primary)]">
      <header className="mb-8 flex flex-wrap items-start justify-between gap-6">
        <div>
          <div className="mb-3 flex items-center gap-2 text-sm text-[var(--ch-text-muted)]">
            <Link href="/lots" className="hover:text-[var(--ch-text-primary)]">Lots</Link>
            <span>&gt;</span>
            <span>OTP Timeline</span>
          </div>
          <h1 className="text-3xl font-semibold tracking-tight">OTP Timeline</h1>
          <p className="mt-2 text-sm text-[var(--ch-text-muted)]">
            All upcoming and overdue key dates across active lots
          </p>
        </div>

        <div className="flex flex-col items-stretch gap-3 lg:items-end">
          <div className="flex flex-wrap justify-end gap-2">
            <button
              type="button"
              onClick={() => setActiveFilters([])}
              className={`rounded-full border px-3 py-1.5 text-xs font-semibold transition ${
                activeFilters.length === 0
                  ? "border-[var(--ch-accent)] bg-[var(--ch-accent-soft)] text-[var(--ch-accent)]"
                  : "border-[var(--ch-border)] bg-[var(--ch-surface)] text-[var(--ch-text-muted)] hover:text-[var(--ch-text-primary)]"
              }`}
            >
              All
            </button>
            {FILTERS.map((filter) => (
              <button
                key={filter.id}
                type="button"
                onClick={() => toggleFilter(filter.id)}
                className={`rounded-full border px-3 py-1.5 text-xs font-semibold transition ${
                  activeFilters.includes(filter.id)
                    ? "border-[var(--ch-accent)] bg-[var(--ch-accent-soft)] text-[var(--ch-accent)]"
                    : "border-[var(--ch-border)] bg-[var(--ch-surface)] text-[var(--ch-text-muted)] hover:text-[var(--ch-text-primary)]"
                }`}
              >
                {filter.label}
              </button>
            ))}
          </div>
          <input
            type="text"
            value={searchInput}
            onChange={(event) => setSearchInput(event.target.value)}
            placeholder="Search address or client"
            className="w-full rounded-lg border border-[var(--ch-border)] bg-[var(--ch-surface)] px-3 py-2 text-sm text-[var(--ch-text-primary)] placeholder:text-[var(--ch-text-muted)] outline-none focus:border-[var(--ch-accent)] lg:w-80"
          />
        </div>
      </header>

      {error && (
        <div className="mb-6 rounded-xl border border-[var(--ch-error-border)] bg-[var(--ch-error-bg)] p-4 text-sm text-[var(--ch-error-text)]">
          {error}
        </div>
      )}

      {loading ? (
        <div className="space-y-8">
          <SkeletonMonth />
          <SkeletonMonth />
        </div>
      ) : error ? null : Object.keys(groupedEvents).length === 0 ? (
        <div className="flex min-h-[360px] items-center justify-center text-sm text-[var(--ch-text-muted)]">
          No upcoming dates match your filters.
        </div>
      ) : (
        <div className="space-y-8">
          {Object.entries(groupedEvents).map(([month, monthEvents]) => (
            <section key={month}>
              <div className="mb-3 flex items-center gap-4">
                <h2 className="text-xs font-bold uppercase tracking-widest text-[var(--ch-text-muted)]">{month}</h2>
                <div className="h-px flex-1 bg-[var(--ch-surface)]" />
              </div>
              <div className="space-y-3">
                {monthEvents.map((event) => (
                  <TimelineCard key={event.id} event={event} />
                ))}
              </div>
            </section>
          ))}
        </div>
      )}
    </div>
  );
}
