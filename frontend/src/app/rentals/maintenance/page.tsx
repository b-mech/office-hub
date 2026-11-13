"use client";

import Link from "next/link";
import { AlertTriangle, CalendarDays, ChevronRight, ListChecks, List, MessageCircleMore, RefreshCw, Search } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { getMaintenanceFilterOptions, listTickets, type MaintenanceFilterOptions, type TicketFilters, type TicketListItem, type TicketPriority, type TicketStatus } from "@/lib/api/maintenance";
import { checklistLabel, filtersFromSearch, filtersToSearch } from "@/lib/maintenance-workflows";
import MaintenanceCalendar from "@/components/maintenance/MaintenanceCalendar";
import { categoryLabel, duplicateKeys, PRIORITY_ORDER, propertyOptionLabel, queueEmptyMessage, queueFiltersActive, showNeedsReply } from "@/lib/rentals-ux";

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
  const [view, setView] = useState<"list" | "calendar">("list");
  const [ready, setReady] = useState(false);
  const [options, setOptions] = useState<MaintenanceFilterOptions>({ properties: [], assignees: [] });

  useEffect(() => {
    const timer = window.setTimeout(() => {
      const fromUrl = filtersFromSearch(window.location.search);
      setFilters(fromUrl as TicketFilters);
      if (!fromUrl.property_id && window.localStorage.getItem("maintenance-open-tickets-view") === "calendar") setView("calendar");
      setReady(true);
    }, 0);
    getMaintenanceFilterOptions().then(setOptions).catch(() => setOptions({ properties: [], assignees: [] }));
    return () => window.clearTimeout(timer);
  }, []);

  useEffect(() => {
    if (!ready) return;
    const next = `${window.location.pathname}${filtersToSearch(filters)}`;
    if (next !== `${window.location.pathname}${window.location.search}`) window.history.replaceState(null, "", next);
  }, [filters, ready]);

  const sharedAddresses = useMemo(() => duplicateKeys(options.properties, (item) => item.address), [options.properties]);
  const filtersOn = queueFiltersActive(filters, query);
  const empty = queueEmptyMessage(filters, query);
  const resetFilters = () => { setQuery(""); setFilters((current) => ({ include_terminal: current.include_terminal })); };

  const changeView = (next: "list" | "calendar") => {
    setView(next);
    window.localStorage.setItem("maintenance-open-tickets-view", next);
  };

  const load = useCallback(async () => {
    setBusy(true);
    setError("");
    try { setTickets(await listTickets(filters)); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Could not load maintenance tickets"); }
    finally { setBusy(false); }
  }, [filters]);

  useEffect(() => {
    if (view !== "list" || !ready) return;
    const initial = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(initial);
  }, [load, view, ready]);

  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return needle ? tickets.filter((ticket) => `${ticket.number} ${ticket.title} ${ticket.property} ${ticket.unit}`.toLowerCase().includes(needle)) : tickets;
  }, [query, tickets]);

  return (
    <div className="min-h-screen bg-[var(--ch-page-bg)] px-4 py-6 sm:px-6 lg:px-8">
      <div className="mx-auto max-w-[1600px]">
        <header className="flex flex-wrap items-end justify-between gap-4 border-b border-[var(--ch-border)] pb-5">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[.2em] text-[var(--ch-text-muted)]">Rentals · Maintenance</p>
            <h1 className="mt-1 text-3xl font-semibold">{filters.include_terminal ? "All tickets" : "Open tickets"}</h1>
            <p className="mt-2 text-sm text-[var(--ch-text-muted)]">Conversations, SLA risk, and field work in one queue.</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Link href="/rentals/maintenance/spend" className="rounded-xl border border-[var(--ch-border)] px-4 py-3 text-sm font-semibold">Spend report</Link>
            <Link href="/rentals/maintenance/vendors" className="rounded-xl border border-[var(--ch-border)] px-4 py-3 text-sm font-semibold">Vendors</Link>
            <Link href="/rentals/maintenance/new" className="rounded-xl bg-[var(--ch-accent)] px-4 py-3 text-sm font-semibold text-white">+ New ticket</Link>
            <div className="flex rounded-xl border border-[var(--ch-border)] bg-[var(--ch-surface)] p-1" aria-label="Open ticket view">
              <button type="button" onClick={() => changeView("list")} className={`inline-flex min-h-9 items-center gap-2 rounded-lg px-3 text-sm font-semibold ${view === "list" ? "bg-[var(--ch-accent)] text-white" : ""}`}><List size={16} /> List</button>
              <button type="button" onClick={() => changeView("calendar")} className={`inline-flex min-h-9 items-center gap-2 rounded-lg px-3 text-sm font-semibold ${view === "calendar" ? "bg-[var(--ch-accent)] text-white" : ""}`}><CalendarDays size={16} /> Calendar</button>
            </div>
            {view === "list" ? <button type="button" onClick={() => void load()} disabled={busy} className="inline-flex min-h-11 items-center gap-2 rounded-xl border border-[var(--ch-border)] bg-[var(--ch-surface)] px-4 text-sm font-semibold disabled:opacity-50">
              <RefreshCw size={16} className={busy ? "animate-spin" : ""} /> Refresh
            </button> : null}
          </div>
        </header>

        {view === "calendar" ? <MaintenanceCalendar /> : <><section className="mt-5 grid gap-3 rounded-2xl border border-[var(--ch-border)] bg-[var(--ch-surface)] p-4 sm:grid-cols-2 lg:grid-cols-6" aria-label="Ticket filters">
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
            {PRIORITY_ORDER.map((priority) => <option key={priority} value={priority}>{labels(priority)}</option>)}
          </select>
          <select aria-label="Property" value={filters.property_id ? String(filters.property_id) : ""} onChange={(event) => setFilters((current) => ({ ...current, property_id: event.target.value ? Number(event.target.value) : undefined }))} className="min-h-11 rounded-xl border border-[var(--ch-border)] bg-[var(--ch-surface-strong)] px-3 text-sm">
            <option value="">All properties</option>
            {filters.property_id && !options.properties.some((item) => item.id === filters.property_id) ? <option value={String(filters.property_id)}>Property #{filters.property_id}</option> : null}
            {options.properties.map((item) => <option key={item.id} value={String(item.id)}>{propertyOptionLabel(item, sharedAddresses)}</option>)}
          </select>
          <select aria-label="Assignee" value={filters.assignee_id || ""} onChange={(event) => setFilters((current) => ({ ...current, assignee_id: event.target.value || undefined }))} className="min-h-11 rounded-xl border border-[var(--ch-border)] bg-[var(--ch-surface-strong)] px-3 text-sm">
            <option value="">Any assignee</option>
            {options.assignees.filter((item) => item.type === "staff").length ? <optgroup label="Staff">{options.assignees.filter((item) => item.type === "staff").map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</optgroup> : null}
            {options.assignees.filter((item) => item.type === "vendor").length ? <optgroup label="Vendors">{options.assignees.filter((item) => item.type === "vendor").map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</optgroup> : null}
          </select>
          <label className="flex min-h-11 items-center gap-3 rounded-xl border border-[var(--ch-border)] px-3 text-sm font-medium">
            <input type="checkbox" checked={Boolean(filters.needs_reply)} onChange={(event) => setFilters((current) => ({ ...current, needs_reply: event.target.checked }))} className="h-4 w-4 accent-[var(--ch-accent)]" /> Needs reply
          </label>
          <label className="flex min-h-11 items-center gap-3 rounded-xl border border-[var(--ch-border)] px-3 text-sm font-medium">
            <input type="checkbox" checked={Boolean(filters.include_terminal)} onChange={(event) => setFilters((current) => ({ ...current, include_terminal: event.target.checked }))} className="h-4 w-4 accent-[var(--ch-accent)]" /> Include closed
          </label>
          {filtersOn ? <button type="button" onClick={resetFilters} className="min-h-11 rounded-xl border border-dashed border-[var(--ch-border-strong)] px-3 text-sm font-semibold text-[var(--ch-accent)]">Reset filters</button> : null}
        </section>

        {error ? <p className="mt-4 rounded-xl border border-[var(--ch-error-border)] bg-[var(--ch-error-bg)] p-3 text-sm text-[var(--ch-error-text)]">{error}</p> : null}
        <div className="mt-5 space-y-3">
          {busy && visible.length === 0 ? <div className="rounded-2xl border border-[var(--ch-border)] p-10 text-center text-sm text-[var(--ch-text-muted)]">Loading tickets…</div> : null}
          {!busy && !error && visible.length === 0 ? <div className="rounded-2xl border border-dashed border-[var(--ch-border-strong)] p-10 text-center text-sm text-[var(--ch-text-muted)]"><p className="text-base font-semibold text-[var(--ch-text-primary)]">{empty.title}</p><p className="mt-1">{empty.detail}</p>{empty.canReset ? <button type="button" onClick={resetFilters} className="mt-4 rounded-xl border border-[var(--ch-border)] bg-[var(--ch-surface)] px-4 py-2 text-sm font-semibold text-[var(--ch-accent)]">Reset filters</button> : !filters.include_terminal ? <button type="button" onClick={() => setFilters((current) => ({ ...current, include_terminal: true }))} className="mt-4 rounded-xl border border-[var(--ch-border)] bg-[var(--ch-surface)] px-4 py-2 text-sm font-semibold text-[var(--ch-accent)]">Include closed tickets</button> : null}</div> : null}
          {visible.map((ticket) => (
            <Link key={ticket.id} href={`/rentals/maintenance/${ticket.id}`} className="group block rounded-2xl border border-[var(--ch-border)] bg-[var(--ch-surface)] p-4 shadow-sm hover:border-[var(--ch-border-strong)] hover:bg-[var(--ch-surface-strong)] sm:p-5">
              <div className="flex items-start gap-3">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-xs font-semibold text-[var(--ch-accent)]">{ticket.number}</span>
                    {ticket.is_emergency ? <span className="inline-flex items-center gap-1 rounded-full border border-[var(--ch-error-border)] bg-[var(--ch-error-bg)] px-2 py-0.5 text-xs font-semibold text-[var(--ch-error-text)]"><AlertTriangle size={12} /> Emergency</span> : null}
                    {showNeedsReply(ticket) ? <span className="inline-flex items-center gap-1 rounded-full border border-[var(--ch-info-border)] bg-[var(--ch-info-bg)] px-2 py-0.5 text-xs font-semibold text-[var(--ch-info-text)]"><MessageCircleMore size={12} /> Needs reply</span> : null}
                  </div>
                  <h2 className="mt-2 truncate text-base font-semibold sm:text-lg">{ticket.title}</h2>
                  <p className="mt-1 text-sm text-[var(--ch-text-secondary)]">{ticket.property} · {ticket.unit}</p>
                  <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
                    <span className="rounded-full border border-[var(--ch-border)] px-2 py-1">{ticket.category ? categoryLabel(ticket.category) : "Untriaged"}</span>
                    <span className="rounded-full border border-[var(--ch-border)] px-2 py-1">{labels(ticket.priority)}</span>
                    <span className="rounded-full border border-[var(--ch-border)] px-2 py-1">{labels(ticket.status)}</span>
                    <span className={`rounded-full border px-2 py-1 font-semibold ${slaClass[ticket.sla_status]}`}>SLA {labels(ticket.sla_status)}</span>
                    {checklistLabel(ticket.checklist) ? <span className="inline-flex items-center gap-1 rounded-full border border-[var(--ch-border)] px-2 py-1 font-semibold"><ListChecks size={12} /> {checklistLabel(ticket.checklist)}</span> : null}
                  </div>
                </div>
                <ChevronRight size={20} className="mt-2 shrink-0 text-[var(--ch-text-muted)] group-hover:text-[var(--ch-accent)]" />
              </div>
            </Link>
          ))}
        </div>
        </>}
      </div>
    </div>
  );
}
