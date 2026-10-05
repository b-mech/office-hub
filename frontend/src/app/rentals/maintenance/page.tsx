"use client";

import Link from "next/link";
import { AlertTriangle, ChevronRight, MessageCircleMore, RefreshCw, Search } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { listTickets, type TicketFilters, type TicketListItem, type TicketPriority, type TicketStatus } from "@/lib/api/maintenance";

const labels = (value: string | null) => value ? value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase()) : "Untriaged";

const slaClass: Record<TicketListItem["sla_status"], string> = {
  untriaged: "border-[var(--ch-border)] bg-[var(--ch-surface-muted)] text-[var(--ch-text-muted)]",
  on_track: "border-[var(--ch-success-border)] bg-[var(--ch-success-bg)] text-[var(--ch-success-text)]",
  warning: "border-[var(--ch-warning-border)] bg-[var(--ch-warning-bg)] text-[var(--ch-warning-text)]",
  overdue: "border-[var(--ch-error-border)] bg-[var(--ch-error-bg)] text-[var(--ch-error-text)]",
  complete: "border-[var(--ch-border)] bg-[var(--ch-surface-muted)] text-[var(--ch-text-muted)]",
};

export default function MaintenanceTicketsPage() {
  const [tickets, setTickets] = useState<TicketListItem[]>([]);
  const [filters, setFilters] = useState<TicketFilters>({});
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setBusy(true);
    setError("");
    try { setTickets(await listTickets(filters)); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Could not load maintenance tickets"); }
    finally { setBusy(false); }
  }, [filters]);

  useEffect(() => { const initial = window.setTimeout(() => void load(), 0); return () => window.clearTimeout(initial); }, [load]);

  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return needle ? tickets.filter((ticket) => `${ticket.number} ${ticket.title} ${ticket.property} ${ticket.unit}`.toLowerCase().includes(needle)) : tickets;
  }, [query, tickets]);

  return (
    <main className="min-h-screen bg-[var(--ch-page-bg)] px-4 py-6 sm:px-6 lg:px-8">
      <div className="mx-auto max-w-6xl">
        <header className="flex flex-wrap items-end justify-between gap-4 border-b border-[var(--ch-border)] pb-5">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[.2em] text-[var(--ch-text-muted)]">Rentals · Maintenance</p>
            <h1 className="mt-1 text-3xl font-semibold">Open tickets</h1>
            <p className="mt-2 text-sm text-[var(--ch-text-muted)]">Conversations, SLA risk, and field work in one queue.</p>
          </div>
          <button type="button" onClick={() => void load()} disabled={busy} className="inline-flex min-h-11 items-center gap-2 rounded-xl border border-[var(--ch-border)] bg-[var(--ch-surface)] px-4 text-sm font-semibold disabled:opacity-50">
            <RefreshCw size={16} className={busy ? "animate-spin" : ""} /> Refresh
          </button>
        </header>

        <section className="mt-5 grid gap-3 rounded-2xl border border-[var(--ch-border)] bg-[var(--ch-surface)] p-4 sm:grid-cols-2 lg:grid-cols-5" aria-label="Ticket filters">
          <label className="relative sm:col-span-2">
            <span className="sr-only">Search tickets</span>
            <Search size={17} className="pointer-events-none absolute left-3 top-3.5 text-[var(--ch-text-muted)]" />
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Ticket, property, or unit" className="min-h-11 w-full rounded-xl border border-[var(--ch-border)] bg-[var(--ch-surface-strong)] pl-10 pr-3 text-sm outline-none focus:ring-4 focus:ring-[var(--ch-focus-ring)]" />
          </label>
          <select aria-label="Status" value={filters.status || ""} onChange={(event) => setFilters((current) => ({ ...current, status: event.target.value as TicketStatus | "" }))} className="min-h-11 rounded-xl border border-[var(--ch-border)] bg-[var(--ch-surface-strong)] px-3 text-sm">
            <option value="">All open statuses</option>
            {["new", "triaged", "assigned", "scheduled", "in_progress", "awaiting_parts", "awaiting_tenant", "resolved", "closed", "cancelled", "duplicate"].map((status) => <option key={status} value={status}>{labels(status)}</option>)}
          </select>
          <select aria-label="Priority" value={filters.priority || ""} onChange={(event) => setFilters((current) => ({ ...current, priority: event.target.value as TicketPriority | "" }))} className="min-h-11 rounded-xl border border-[var(--ch-border)] bg-[var(--ch-surface-strong)] px-3 text-sm">
            <option value="">All priorities</option>
            {["emergency", "urgent", "routine", "low"].map((priority) => <option key={priority} value={priority}>{labels(priority)}</option>)}
          </select>
          <label className="flex min-h-11 items-center gap-3 rounded-xl border border-[var(--ch-border)] px-3 text-sm font-medium">
            <input type="checkbox" checked={Boolean(filters.needs_reply)} onChange={(event) => setFilters((current) => ({ ...current, needs_reply: event.target.checked }))} className="h-4 w-4 accent-[var(--ch-accent)]" /> Needs reply
          </label>
          <label className="flex min-h-11 items-center gap-3 rounded-xl border border-[var(--ch-border)] px-3 text-sm font-medium lg:col-start-5">
            <input type="checkbox" checked={Boolean(filters.include_terminal)} onChange={(event) => setFilters((current) => ({ ...current, include_terminal: event.target.checked }))} className="h-4 w-4 accent-[var(--ch-accent)]" /> Include closed
          </label>
        </section>

        {error ? <p className="mt-4 rounded-xl border border-[var(--ch-error-border)] bg-[var(--ch-error-bg)] p-3 text-sm text-[var(--ch-error-text)]">{error}</p> : null}
        <div className="mt-5 space-y-3">
          {!busy && visible.length === 0 ? <div className="rounded-2xl border border-dashed border-[var(--ch-border-strong)] p-10 text-center text-sm text-[var(--ch-text-muted)]">No tickets match these filters.</div> : null}
          {visible.map((ticket) => (
            <Link key={ticket.id} href={`/rentals/maintenance/${ticket.id}`} className="group block rounded-2xl border border-[var(--ch-border)] bg-[var(--ch-surface)] p-4 shadow-sm hover:border-[var(--ch-border-strong)] hover:bg-[var(--ch-surface-strong)] sm:p-5">
              <div className="flex items-start gap-3">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-xs font-semibold text-[var(--ch-accent)]">{ticket.number}</span>
                    {ticket.is_emergency ? <span className="inline-flex items-center gap-1 rounded-full border border-[var(--ch-error-border)] bg-[var(--ch-error-bg)] px-2 py-0.5 text-xs font-semibold text-[var(--ch-error-text)]"><AlertTriangle size={12} /> Emergency</span> : null}
                    {ticket.needs_reply ? <span className="inline-flex items-center gap-1 rounded-full border border-[var(--ch-info-border)] bg-[var(--ch-info-bg)] px-2 py-0.5 text-xs font-semibold text-[var(--ch-info-text)]"><MessageCircleMore size={12} /> Needs reply</span> : null}
                  </div>
                  <h2 className="mt-2 truncate text-base font-semibold sm:text-lg">{ticket.title}</h2>
                  <p className="mt-1 text-sm text-[var(--ch-text-secondary)]">{ticket.property} · {ticket.unit}</p>
                  <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
                    <span className="rounded-full border border-[var(--ch-border)] px-2 py-1">{labels(ticket.category)}</span>
                    <span className="rounded-full border border-[var(--ch-border)] px-2 py-1">{labels(ticket.priority)}</span>
                    <span className="rounded-full border border-[var(--ch-border)] px-2 py-1">{labels(ticket.status)}</span>
                    <span className={`rounded-full border px-2 py-1 font-semibold ${slaClass[ticket.sla_status]}`}>SLA {labels(ticket.sla_status)}</span>
                  </div>
                </div>
                <ChevronRight size={20} className="mt-2 shrink-0 text-[var(--ch-text-muted)] group-hover:text-[var(--ch-accent)]" />
              </div>
            </Link>
          ))}
        </div>
      </div>
    </main>
  );
}
