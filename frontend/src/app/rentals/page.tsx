"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { getRentalMap, type MapProperty } from "@/lib/api/rentals-map";
import { RentalsLeafletMap } from "../components/RentalsLeafletMap";
import { INSPECTION_COLORS, isLocatedProperty, locatedProperties } from "@/lib/rentals-map-points";
import { maintenanceHrefForProperty } from "@/lib/maintenance-workflows";
import { DEFAULT_MAP_FILTERS, filterMapItems, mapFiltersActive, type MapFilters } from "@/lib/rentals-ux";

const STATUSES = ["current", "due", "overdue", "never"] as const;
const STATUS_LABEL: Record<(typeof STATUSES)[number], string> = { current: "Inspected ≤ 6 mo", due: "Due", overdue: "Overdue", never: "Never inspected" };
const control = "min-h-11 rounded-xl border border-[var(--ch-border)] bg-[var(--ch-surface-strong)] px-3 text-sm";

function PropertyCard({ property }: { property: MapProperty }) {
  return <div className="mb-2 rounded-xl border bg-[var(--ch-surface)] p-4">
    <a href={`/rentals/inspections?property_id=${property.property_id}`} className="block">
      <div className="flex items-center gap-2">
        <strong>{property.street_address}</strong>
        {property.address_is_shared ? <span className="rounded border border-[var(--ch-warning-border)] bg-[var(--ch-warning-bg)] px-1 text-[10px] font-semibold text-[var(--ch-warning-text)]" title="Another property has the same address">#{property.property_id}</span> : null}
        <span className="ml-auto rounded-full px-2 py-1 text-xs text-white" style={{ background: INSPECTION_COLORS[property.inspection_status] }}>{property.inspection_status}</span>
      </div>
      <div className="text-sm text-[var(--ch-text-muted)]">
        {[property.group_name, property.city].filter(Boolean).join(" · ")} · {property.unit_count} unit{property.unit_count === 1 ? "" : "s"} · {property.last_inspection_date || "never inspected"}
        {property.address_is_shared && property.company_name ? ` · ${property.company_name}` : ""}
        {!isLocatedProperty(property) ? " · not on map (no coordinates)" : ""}
      </div>
    </a>
    <div className="mt-2 flex flex-wrap gap-3 text-sm font-semibold">
      <Link href={`/rentals/units?property_id=${property.property_id}`} className="text-[var(--ch-accent)]">Units</Link>
      <Link href={maintenanceHrefForProperty(property.property_id)} className="text-[var(--ch-accent)]">Maintenance</Link>
      <Link href={`/rentals/inspections?property_id=${property.property_id}`} className="text-[var(--ch-accent)]">Inspections &amp; QR</Link>
    </div>
  </div>;
}

export default function RentalsHome() {
  const [items, setItems] = useState<MapProperty[]>([]);
  const [filters, setFilters] = useState<MapFilters>(DEFAULT_MAP_FILTERS);
  const [view, setView] = useState<"map" | "list">("map");
  const [showUnmapped, setShowUnmapped] = useState(false);
  const [error, setError] = useState("");

  const filtered = useMemo(() => filterMapItems(items, filters), [items, filters]);
  const located = useMemo(() => locatedProperties(filtered), [filtered]);
  const unmapped = useMemo(() => filtered.filter((item) => !isLocatedProperty(item)), [filtered]);
  const groupNames = useMemo(() => Array.from(new Set(items.map((item) => item.group_name).filter((name): name is string => Boolean(name)))).sort(), [items]);
  const statusCounts = useMemo(() => Object.fromEntries(STATUSES.map((status) => [status, filterMapItems(items, { ...filters, status }).length])), [items, filters]);

  useEffect(() => {
    getRentalMap()
      .then(setItems)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Map API failed"));
  }, []);

  return (
    <main className="flex h-screen flex-col">
      <header className="border-b bg-[var(--ch-surface)] p-4">
        <div className="mx-auto flex max-w-6xl flex-wrap gap-2">
          <input value={filters.query} onChange={(event) => setFilters({ ...filters, query: event.target.value })} className="min-w-0 flex-1 rounded-xl border p-3" placeholder="Search rental address or group" aria-label="Search rentals" />
          <select aria-label="Group" value={filters.group} onChange={(event) => setFilters({ ...filters, group: event.target.value })} className={control}><option value="">All groups</option>{groupNames.map((name) => <option key={name} value={name}>{name}</option>)}</select>
          <button type="button" onClick={() => setView(view === "map" ? "list" : "map")} className="rounded-xl border px-4 font-bold">{view === "map" ? "List" : "Map"}</button>
          <Link href="/rentals/units" className="grid place-items-center rounded-xl border px-4 font-bold">Units</Link>
        </div>
        <div className="mx-auto mt-2 flex max-w-6xl flex-wrap items-center gap-2" role="group" aria-label="Inspection status filter">
          {STATUSES.map((status) => <button key={status} type="button" aria-pressed={filters.status === status} onClick={() => setFilters({ ...filters, status: filters.status === status ? "" : status })} className={`inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-semibold ${filters.status === status ? "border-[var(--ch-accent)] bg-[var(--ch-surface-strong)]" : "border-[var(--ch-border)]"}`}><span className="h-3 w-3 rounded-full" style={{ background: INSPECTION_COLORS[status] }} />{STATUS_LABEL[status]} ({statusCounts[status]})</button>)}
          {mapFiltersActive(filters) ? <button type="button" onClick={() => setFilters(DEFAULT_MAP_FILTERS)} className="rounded-full border border-dashed px-3 py-1 text-xs font-semibold text-[var(--ch-accent)]">Reset filters</button> : null}
        </div>
        {error ? <p className="mx-auto mt-2 max-w-6xl text-sm text-[var(--ch-error-text)]">{error}</p> : null}
        {filtered.length > 0 || items.length > 0 ? (
          <p className="mx-auto mt-2 max-w-6xl text-sm text-[var(--ch-text-muted)]">
            {view === "map" ? `${located.length} of ${filtered.length} properties mapped` : `${filtered.length} of ${items.length} properties`}
            {unmapped.length ? <> · <button type="button" onClick={() => setShowUnmapped(!showUnmapped)} className="font-semibold text-[var(--ch-accent)] underline" aria-expanded={showUnmapped}>{unmapped.length} without coordinates</button></> : null}
          </p>
        ) : null}
        {showUnmapped && unmapped.length ? <section aria-label="Properties not on the map" className="mx-auto mt-2 max-w-6xl rounded-xl border border-[var(--ch-warning-border)] bg-[var(--ch-warning-bg)] p-3 text-sm">
          <p className="font-semibold text-[var(--ch-warning-text)]">Not on the map (no coordinates)</p>
          <ul className="mt-1 space-y-1">{unmapped.map((property) => <li key={property.property_id} className="flex flex-wrap gap-x-3">
            <span>{property.street_address} · #{property.property_id}{property.company_name ? ` · ${property.company_name}` : ""} · {property.unit_count} unit{property.unit_count === 1 ? "" : "s"}</span>
            <Link href={`/rentals/units?property_id=${property.property_id}`} className="font-semibold text-[var(--ch-accent)]">Units</Link>
          </li>)}</ul>
        </section> : null}
      </header>
      {view === "map" ? (
        <RentalsLeafletMap items={filtered} />
      ) : (
        <div className="mx-auto w-full max-w-3xl flex-1 overflow-auto p-4">
          {filtered.map((property) => <PropertyCard key={property.property_id} property={property} />)}
          {!filtered.length && items.length ? <p className="rounded-xl border border-dashed p-8 text-center text-sm text-[var(--ch-text-muted)]">No properties match these filters.</p> : null}
        </div>
      )}
    </main>
  );
}
