"use client";

import Link from "next/link";
import { Download, RefreshCw, Search, Wrench } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { getUnitRoster, type RosterUnit } from "@/lib/api/rental-units";
import { DEFAULT_FILTERS, filterRoster, groups, leaseFlagLabel, rosterCsv, summarize, type LeaseFilter, type Occupancy, type RosterFilters, type SortKey } from "@/lib/rental-units";

const money = (value: string | number | null | undefined) => value === null || value === undefined || value === "" ? "—"
  : new Intl.NumberFormat("en-CA", { style: "currency", currency: "CAD", maximumFractionDigits: 0 }).format(Number(value));
const day = (value: string | null) => value ? new Intl.DateTimeFormat("en-CA", { dateStyle: "medium", timeZone: "UTC" }).format(new Date(`${value}T00:00:00Z`)) : "—";
const control = "min-h-11 rounded-xl border border-[var(--ch-border)] bg-[var(--ch-surface-strong)] px-3 text-sm";

function OccupancyPill({ unit }: { unit: RosterUnit }) {
  const occupied = unit.occupancy === "occupied";
  return <span className={`inline-flex rounded-full border px-2 py-0.5 text-xs font-semibold ${occupied ? "border-[var(--ch-success-border)] bg-[var(--ch-success-bg)] text-[var(--ch-success-text)]" : "border-[var(--ch-warning-border)] bg-[var(--ch-warning-bg)] text-[var(--ch-warning-text)]"}`}>{occupied ? "Occupied" : "Vacant"}</span>;
}

function FlagPill({ unit }: { unit: RosterUnit }) {
  const text = leaseFlagLabel(unit);
  if (!text) return null;
  const bad = unit.lease?.flag === "past_end";
  return <span className={`ml-1 inline-flex rounded-full border px-2 py-0.5 text-xs font-semibold ${bad ? "border-[var(--ch-error-border)] bg-[var(--ch-error-bg)] text-[var(--ch-error-text)]" : "border-[var(--ch-info-border)] bg-[var(--ch-info-bg)] text-[var(--ch-info-text)]"}`}>{text}</span>;
}

function UnitLinks({ unit }: { unit: RosterUnit }) {
  return <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs font-semibold">
    <Link href={`/rentals/units/${unit.unit_id}`} className="text-[var(--ch-accent)]">QR &amp; maintenance</Link>
    <Link href={`/rentals/units/${unit.unit_id}?tab=leases`} className="text-[var(--ch-accent)]">Leases</Link>
    <Link href={`/rentals/maintenance?property_id=${unit.property_id}`} className="inline-flex items-center gap-1 text-[var(--ch-accent)]"><Wrench size={12} />{unit.open_maintenance_tickets ? `${unit.open_maintenance_tickets} open` : "Tickets"}</Link>
  </div>;
}

export default function RentalUnitsPage() {
  const [units, setUnits] = useState<RosterUnit[]>([]);
  const [filters, setFilters] = useState<RosterFilters>(DEFAULT_FILTERS);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setBusy(true); setError("");
    try { setUnits(await getUnitRoster()); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Could not load rental units"); }
    finally { setBusy(false); }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      const params = new URLSearchParams(window.location.search);
      const propertyId = Number(params.get("property_id"));
      const occupancy = params.get("occupancy");
      setFilters((current) => ({
        ...current,
        query: params.get("q") || "",
        propertyId: Number.isInteger(propertyId) && propertyId > 0 ? propertyId : undefined,
        occupancy: occupancy === "vacant" || occupancy === "occupied" ? occupancy : "all",
      }));
      void load();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  const visible = useMemo(() => filterRoster(units, filters), [units, filters]);
  const totals = useMemo(() => summarize(visible), [visible]);
  const groupNames = useMemo(() => groups(units), [units]);
  const propertyName = filters.propertyId ? units.find((unit) => unit.property_id === filters.propertyId)?.street_address : null;

  function exportCsv() {
    const blob = new Blob([rosterCsv(visible)], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url; anchor.download = `rental-units-${new Date().toISOString().slice(0, 10)}.csv`; anchor.click();
    URL.revokeObjectURL(url);
  }

  return <main className="min-h-screen bg-[var(--ch-page-bg)] px-4 py-6 sm:px-6 lg:px-8">
    <div className="mx-auto max-w-[1600px]">
      <header className="flex flex-wrap items-end justify-between gap-4 border-b border-[var(--ch-border)] pb-5">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[.2em] text-[var(--ch-text-muted)]">Rentals · Units</p>
          <h1 className="mt-1 text-3xl font-semibold">Rental units</h1>
          <p className="mt-2 text-sm text-[var(--ch-text-muted)]">Every unit with occupancy, current lease, tenants and rent. Read-only — edit leases from a unit page.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Link href="/rentals" className="inline-flex min-h-11 items-center rounded-xl border border-[var(--ch-border)] bg-[var(--ch-surface)] px-4 text-sm font-semibold">Map</Link>
          <button type="button" onClick={exportCsv} disabled={!visible.length} className="inline-flex min-h-11 items-center gap-2 rounded-xl border border-[var(--ch-border)] bg-[var(--ch-surface)] px-4 text-sm font-semibold disabled:opacity-50"><Download size={16} /> CSV</button>
          <button type="button" onClick={() => void load()} disabled={busy} className="inline-flex min-h-11 items-center gap-2 rounded-xl border border-[var(--ch-border)] bg-[var(--ch-surface)] px-4 text-sm font-semibold disabled:opacity-50"><RefreshCw size={16} className={busy ? "animate-spin" : ""} /> Refresh</button>
        </div>
      </header>

      <section className="mt-5 grid gap-3 sm:grid-cols-3 lg:grid-cols-6" aria-label="Summary">
        {[["Units", String(totals.units)], ["Occupied", String(totals.occupied)], ["Vacant", String(totals.vacant)], ["Ending ≤ 60 days", String(totals.endingSoon)], ["Monthly rent (net)", money(totals.monthlyRent)], ["Open tickets", String(totals.openTickets)]].map(([name, value]) => <div key={name} className="rounded-2xl border border-[var(--ch-border)] bg-[var(--ch-surface)] p-4"><p className="text-xs font-semibold uppercase tracking-wide text-[var(--ch-text-muted)]">{name}</p><p className="mt-1 text-2xl font-semibold">{value}</p></div>)}
      </section>

      <section className="mt-5 grid gap-3 rounded-2xl border border-[var(--ch-border)] bg-[var(--ch-surface)] p-4 sm:grid-cols-2 lg:grid-cols-6" aria-label="Unit filters">
        <label className="relative sm:col-span-2">
          <span className="sr-only">Search units</span>
          <Search size={17} className="pointer-events-none absolute left-3 top-3.5 text-[var(--ch-text-muted)]" />
          <input value={filters.query} onChange={(event) => setFilters((current) => ({ ...current, query: event.target.value }))} placeholder="Address, unit, group or tenant" className={`${control} w-full pl-10`} />
        </label>
        <select aria-label="Occupancy" value={filters.occupancy} onChange={(event) => setFilters((current) => ({ ...current, occupancy: event.target.value as Occupancy }))} className={control}><option value="all">Occupied &amp; vacant</option><option value="occupied">Occupied</option><option value="vacant">Vacant</option></select>
        <select aria-label="Group" value={filters.group} onChange={(event) => setFilters((current) => ({ ...current, group: event.target.value }))} className={control}><option value="">All groups</option>{groupNames.map((name) => <option key={name} value={name}>{name}</option>)}</select>
        <select aria-label="Lease" value={filters.leaseFilter} onChange={(event) => setFilters((current) => ({ ...current, leaseFilter: event.target.value as LeaseFilter }))} className={control}><option value="all">Any lease term</option><option value="ending_soon">Ending within 60 days</option><option value="past_end">Past end date</option><option value="month_to_month">Month to month</option></select>
        <select aria-label="Sort" value={filters.sort} onChange={(event) => setFilters((current) => ({ ...current, sort: event.target.value as SortKey }))} className={control}><option value="address">Sort: address</option><option value="lease_end">Sort: lease end</option><option value="rent">Sort: rent (high → low)</option><option value="tenant">Sort: tenant</option></select>
        {filters.propertyId ? <button type="button" onClick={() => setFilters((current) => ({ ...current, propertyId: undefined }))} className="min-h-11 rounded-xl border border-dashed border-[var(--ch-border-strong)] px-3 text-left text-sm font-semibold text-[var(--ch-accent)] sm:col-span-2">Showing {propertyName || `property #${filters.propertyId}`} only · show all</button> : null}
      </section>

      {error ? <p className="mt-4 rounded-xl border border-[var(--ch-error-border)] bg-[var(--ch-error-bg)] p-3 text-sm text-[var(--ch-error-text)]">{error}</p> : null}
      <p className="mt-4 text-sm text-[var(--ch-text-muted)]">{busy && !units.length ? "Loading units…" : `${visible.length} of ${units.length} units`}</p>

      <div className="mt-2 hidden overflow-x-auto rounded-2xl border border-[var(--ch-border)] bg-[var(--ch-surface)] lg:block">
        <table className="min-w-full text-sm">
          <thead className="bg-[var(--ch-surface-muted)] text-left text-xs uppercase tracking-wide text-[var(--ch-text-muted)]"><tr><th className="px-4 py-3">Property</th><th className="px-4 py-3">Unit</th><th className="px-4 py-3">Status</th><th className="px-4 py-3">Tenant(s)</th><th className="px-4 py-3 text-right">Rent</th><th className="px-4 py-3">Lease</th><th className="px-4 py-3">Links</th></tr></thead>
          <tbody>{visible.map((unit) => <tr key={unit.unit_id} className="border-t border-[var(--ch-border)] align-top hover:bg-[var(--ch-surface-strong)]">
            <td className="px-4 py-3"><Link href={`/rentals/units?property_id=${unit.property_id}`} className="font-semibold hover:text-[var(--ch-accent)]">{unit.street_address}</Link><div className="text-xs text-[var(--ch-text-muted)]">{[unit.group_name, unit.city].filter(Boolean).join(" · ")}</div></td>
            <td className="px-4 py-3"><Link href={`/rentals/units/${unit.unit_id}`} className="font-medium hover:text-[var(--ch-accent)]">{unit.unit_label}</Link>{unit.is_basement ? <div className="text-xs text-[var(--ch-text-muted)]">Basement</div> : null}</td>
            <td className="px-4 py-3"><OccupancyPill unit={unit} /><FlagPill unit={unit} />{unit.lease_agreement_status ? <div className="mt-1 text-xs text-[var(--ch-text-muted)]">E-lease: {unit.lease_agreement_status}</div> : null}</td>
            <td className="px-4 py-3">{unit.tenants.length ? unit.tenants.join(", ") : <span className="text-[var(--ch-text-muted)]">{unit.last_lease_end ? `Last lease ended ${day(unit.last_lease_end)}` : "—"}</span>}</td>
            <td className="px-4 py-3 text-right">{unit.lease ? <><span className="font-semibold">{money(unit.lease.net_rent)}</span>{unit.lease.rent_discount ? <div className="text-xs text-[var(--ch-text-muted)]">{money(unit.lease.rent)} − {money(unit.lease.rent_discount)}</div> : null}</> : "—"}</td>
            <td className="px-4 py-3 text-xs">{unit.lease ? <>{day(unit.lease.lease_start)} → {unit.lease.lease_end ? day(unit.lease.lease_end) : "open"}<div className="text-[var(--ch-text-muted)]">{unit.lease.status.replaceAll("_", " ")}</div></> : "—"}</td>
            <td className="px-4 py-3"><UnitLinks unit={unit} /></td>
          </tr>)}
          {!busy && !visible.length ? <tr><td colSpan={7} className="px-4 py-10 text-center text-[var(--ch-text-muted)]">No units match these filters.</td></tr> : null}</tbody>
        </table>
      </div>

      <div className="mt-2 space-y-3 lg:hidden">{visible.map((unit) => <article key={unit.unit_id} className="rounded-2xl border border-[var(--ch-border)] bg-[var(--ch-surface)] p-4">
        <div className="flex items-start justify-between gap-2"><div className="min-w-0"><Link href={`/rentals/units/${unit.unit_id}`} className="font-semibold">{unit.street_address} · {unit.unit_label}</Link><p className="text-xs text-[var(--ch-text-muted)]">{unit.group_name || ""}</p></div><OccupancyPill unit={unit} /></div>
        <p className="mt-2 text-sm">{unit.tenants.length ? unit.tenants.join(", ") : <span className="text-[var(--ch-text-muted)]">No current tenant</span>}</p>
        {unit.lease ? <p className="mt-1 text-sm"><strong>{money(unit.lease.net_rent)}</strong>/mo · ends {unit.lease.lease_end ? day(unit.lease.lease_end) : "open"}<FlagPill unit={unit} /></p> : null}
        <div className="mt-3"><UnitLinks unit={unit} /></div>
      </article>)}{!busy && !visible.length ? <p className="rounded-2xl border border-dashed p-8 text-center text-sm text-[var(--ch-text-muted)]">No units match these filters.</p> : null}</div>
    </div>
  </main>;
}
