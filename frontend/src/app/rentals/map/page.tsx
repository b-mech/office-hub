"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { getRentalMap, type MapProperty } from "@/lib/api/rentals-map";
import { partitionMapRecords } from "@/lib/map-points";
import { EntityMap, type EntityMapMarker } from "../../components/EntityMap";
import { MapCoverage, UNPLOTTED_LABEL, type UnplottedReason } from "../../components/MapCoverage";
import { Card, Empty, ErrorNote, PageShell, fieldClass, formatDate } from "../../components/WorkspaceUi";

// Rental properties on an OpenStreetMap base map, using the coordinates stored
// on rental_properties (GET /api/rentals/properties/map). Rental records are
// not org-owned yet, so this covers every rental property, as before.

const STATUS_COLOR: Record<MapProperty["inspection_status"], string> = {
  current: "#2E7D32",
  due: "#D6A700",
  overdue: "#C62828",
  never: "#777777",
};

const STATUS_LABEL: Record<MapProperty["inspection_status"], string> = {
  current: "Inspected",
  due: "Inspection due",
  overdue: "Inspection overdue",
  never: "Never inspected",
};

type Row = MapProperty & { id: string; label: string };

const unitsText = (count: number) => `${count} unit${count === 1 ? "" : "s"}`;
const propertyHref = (id: number) => `/rentals/inspections?property_id=${id}`;

export default function RentalsMapPage() {
  const [items, setItems] = useState<MapProperty[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);

  useEffect(() => {
    getRentalMap()
      .then(setItems)
      .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "Rental map unavailable"));
  }, []);

  // Classify the whole portfolio once so a search never changes which points count as approximate.
  const partition = useMemo(() => {
    const rows: Row[] = (items ?? []).map((item) => ({ ...item, id: String(item.property_id), label: item.street_address }));
    return partitionMapRecords(rows);
  }, [items]);

  const reasonById = useMemo(() => {
    const reasons = new Map<string, UnplottedReason>();
    partition.missing.forEach((row) => reasons.set(row.id, "missing"));
    partition.invalid.forEach((row) => reasons.set(row.id, "invalid"));
    partition.shared.forEach((row) => reasons.set(row.id, "shared"));
    return reasons;
  }, [partition]);

  const matches = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (row: MapProperty) => !q || `${row.street_address} ${row.group_name ?? ""}`.toLowerCase().includes(q);
  }, [query]);

  const markers = useMemo<EntityMapMarker[]>(
    () =>
      partition.located
        .filter((point) => matches(point.record))
        .map(({ record, lat, lng }) => ({
          id: record.id,
          lat,
          lng,
          title: record.street_address,
          lines: [
            record.group_name ?? "",
            `${unitsText(record.unit_count)} · ${STATUS_LABEL[record.inspection_status]}`,
            record.last_inspection_date ? `Last inspected ${formatDate(record.last_inspection_date)}` : "",
          ],
          href: propertyHref(record.property_id),
          linkLabel: "View units & inspections",
          color: STATUS_COLOR[record.inspection_status],
        })),
    [partition, matches],
  );

  const listed = (items ?? []).filter(matches);

  return (
    <PageShell
      title="Rentals map"
      subtitle="Rental properties at their stored coordinates"
      actions={<div className="flex gap-2 text-xs"><Link className="rounded-md border border-[var(--ch-border)] px-3 py-2" href="/rentals">Overview</Link><Link className="rounded-md border border-[var(--ch-border)] px-3 py-2" href="/rentals/inspections">Inspections</Link></div>}
    >
      <ErrorNote message={error} />
      {!items && !error ? <p className="text-sm text-[var(--ch-text-muted)]">Loading…</p> : null}
      {items ? (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <MapCoverage
              noun="properties"
              total={items.length}
              located={partition.located.length}
              missing={partition.missing.length}
              invalid={partition.invalid.length}
              shared={partition.shared.length}
            />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              className={`${fieldClass} w-full sm:w-72`}
              placeholder="Search address or group"
              aria-label="Search rental properties"
            />
          </div>
          {partition.located.length > 0 ? (
            <EntityMap markers={markers} selectedId={selectedId} onSelect={setSelectedId} ariaLabel="Rental properties map" />
          ) : (
            <Empty>No rental property has usable stored coordinates yet, so there is nothing to place on the map. The list below shows every property.</Empty>
          )}
          <div className="flex flex-wrap gap-2 text-xs" aria-label="Marker legend">
            {(Object.keys(STATUS_COLOR) as MapProperty["inspection_status"][]).map((status) => (
              <span key={status} className="inline-flex items-center gap-1 rounded-full border border-[var(--ch-border)] px-2 py-1">
                <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: STATUS_COLOR[status] }} aria-hidden />
                {STATUS_LABEL[status]}
              </span>
            ))}
          </div>
          <Card title={`Properties · ${listed.length}`}>
            {listed.length === 0 ? <Empty>No properties match.</Empty> : (
              <ul className="divide-y divide-[var(--ch-border)]">
                {listed.map((item) => {
                  const id = String(item.property_id);
                  const reason = reasonById.get(id);
                  return (
                    <li key={id} className={`flex flex-wrap items-center gap-3 py-2 text-sm ${selectedId === id ? "bg-[var(--ch-accent-soft)]" : ""}`}>
                      <span className="inline-block h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: STATUS_COLOR[item.inspection_status] }} aria-hidden />
                      <div className="min-w-0 flex-1">
                        <Link href={propertyHref(item.property_id)} className="font-medium hover:text-[var(--ch-accent)]">{item.street_address}</Link>
                        <p className="text-xs text-[var(--ch-text-muted)]">
                          {[item.group_name, unitsText(item.unit_count), STATUS_LABEL[item.inspection_status]].filter(Boolean).join(" · ")}
                        </p>
                      </div>
                      {reason ? (
                        <span className="rounded-full border border-[var(--ch-border)] px-2 py-1 text-xs text-[var(--ch-text-muted)]">{UNPLOTTED_LABEL[reason]}</span>
                      ) : (
                        <button type="button" onClick={() => setSelectedId(id)} className="rounded-md border border-[var(--ch-border)] px-2 py-1 text-xs hover:border-[var(--ch-border-strong)]">
                          Show on map
                        </button>
                      )}
                    </li>
                  );
                })}
              </ul>
            )}
          </Card>
        </div>
      ) : null}
    </PageShell>
  );
}
