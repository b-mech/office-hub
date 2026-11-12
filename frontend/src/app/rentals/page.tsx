"use client";

import { useEffect, useMemo, useState } from "react";
import { getRentalMap, type MapProperty } from "@/lib/api/rentals-map";
import { RentalsLeafletMap } from "../components/RentalsLeafletMap";
import { INSPECTION_COLORS, locatedProperties } from "@/lib/rentals-map-points";

export default function RentalsHome() {
  const [items, setItems] = useState<MapProperty[]>([]);
  const [query, setQuery] = useState("");
  const [view, setView] = useState<"map" | "list">("map");
  const [error, setError] = useState("");

  const filtered = useMemo(
    () =>
      items.filter((item) =>
        `${item.street_address} ${item.group_name || ""}`.toLowerCase().includes(query.toLowerCase()),
      ),
    [items, query],
  );
  const located = useMemo(() => locatedProperties(filtered), [filtered]);
  const missing = filtered.length - located.length;

  useEffect(() => {
    getRentalMap()
      .then(setItems)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Map API failed"));
  }, []);

  return (
    <main className="flex h-screen flex-col">
      <header className="border-b bg-[var(--ch-surface)] p-4">
        <div className="mx-auto flex max-w-6xl gap-2">
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            className="min-w-0 flex-1 rounded-xl border p-3"
            placeholder="Search rental address or group"
          />
          <button
            type="button"
            onClick={() => setView(view === "map" ? "list" : "map")}
            className="rounded-xl border px-4 font-bold"
          >
            {view === "map" ? "List" : "Map"}
          </button>
        </div>
        {error ? (
          <p className="mx-auto mt-2 max-w-6xl text-sm text-[var(--ch-error-text)]">{error}</p>
        ) : null}
        {view === "map" && filtered.length > 0 ? (
          <p className="mx-auto mt-2 max-w-6xl text-sm text-[var(--ch-text-muted)]">
            {located.length} of {filtered.length} properties mapped
            {missing ? ` · ${missing} without coordinates` : ""}
          </p>
        ) : null}
      </header>
      {view === "map" ? (
        <RentalsLeafletMap items={filtered} />
      ) : (
        <div className="mx-auto w-full max-w-3xl flex-1 overflow-auto p-4">
          {filtered.map((property) => (
            <a
              key={property.property_id}
              href={`/rentals/inspections?property_id=${property.property_id}`}
              className="mb-2 block rounded-xl border bg-[var(--ch-surface)] p-4"
            >
              <div className="flex items-center">
                <strong>{property.street_address}</strong>
                <span
                  className="ml-auto rounded-full px-2 py-1 text-xs text-white"
                  style={{ background: INSPECTION_COLORS[property.inspection_status] }}
                >
                  {property.inspection_status}
                </span>
              </div>
              <div className="text-sm text-[var(--ch-text-muted)]">
                {property.group_name} · {property.unit_count} units · {property.last_inspection_date || "never inspected"}
              </div>
            </a>
          ))}
        </div>
      )}
    </main>
  );
}
