"use client";

import "leaflet/dist/leaflet.css";
import { useEffect, useRef, useState } from "react";
import type { LayerGroup, Map as LeafletMap, Marker } from "leaflet";
import { planView } from "@/lib/map-points";

// Reusable OpenStreetMap (Leaflet) map. Leaflet touches `window`, so it is
// imported inside an effect and never runs during server rendering. Markers
// are only ever drawn at coordinates the caller passes in; there is no
// geocoding and no default location.

export interface EntityMapMarker {
  id: string;
  lat: number;
  lng: number;
  title: string;
  /** Extra plain-text lines shown in the popup. */
  lines?: string[];
  href: string;
  linkLabel: string;
  color?: string;
  approximate?: boolean;
}

const OSM_TILE_URL = "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png";
const OSM_ATTRIBUTION = '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap</a> contributors';
const SINGLE_MARKER_ZOOM = 16;
const MAX_FIT_ZOOM = 16;
const DEFAULT_COLOR = "rgb(23 105 140)";

function popupContent(marker: EntityMapMarker): HTMLElement {
  const root = document.createElement("div");
  root.style.minWidth = "200px";
  const title = document.createElement("strong");
  title.textContent = marker.title;
  if (marker.approximate) {
    const note = document.createElement("div");
    note.textContent = "Approximate street location — not the parcel. Manual pin needed.";
    note.style.fontWeight = "600";
    root.appendChild(note);
  }
  root.appendChild(title);
  for (const line of marker.lines ?? []) {
    if (!line) continue;
    const row = document.createElement("div");
    row.style.fontSize = "12px";
    row.textContent = line;
    root.appendChild(row);
  }
  const link = document.createElement("a");
  link.href = marker.href;
  link.textContent = marker.linkLabel;
  link.style.display = "inline-block";
  link.style.marginTop = "6px";
  link.style.fontWeight = "600";
  link.style.color = DEFAULT_COLOR;
  root.appendChild(link);
  return root;
}

function markerHtml(color: string, approximate = false): string {
  // Colour is chosen by the caller from a fixed palette, never from record data.
  return `<span style="display:block;width:18px;height:18px;border-radius:9999px;background:${approximate ? "#fff" : color};border:3px ${approximate ? "dashed" : "solid"} ${approximate ? color : "#fff"};box-shadow:0 0 0 1px rgba(0,0,0,.35)"></span>`;
}

export function EntityMap({
  markers,
  selectedId,
  onSelect,
  ariaLabel,
}: {
  markers: EntityMapMarker[];
  selectedId?: string | null;
  onSelect?: (id: string) => void;
  ariaLabel: string;
}) {
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<LeafletMap | null>(null);
  const layerRef = useRef<LayerGroup | null>(null);
  const markerRefs = useRef(new Map<string, Marker>());
  const leafletRef = useRef<typeof import("leaflet") | null>(null);
  const onSelectRef = useRef(onSelect);
  const [ready, setReady] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [tileErrors, setTileErrors] = useState(0);

  useEffect(() => {
    onSelectRef.current = onSelect;
  }, [onSelect]);

  // Create the map once.
  useEffect(() => {
    let cancelled = false;
    import("leaflet")
      .then((module) => {
        const L = (module as unknown as { default?: typeof import("leaflet") }).default ?? module;
        if (cancelled || !container.current || mapRef.current) return;
        leafletRef.current = L;
        const map = L.map(container.current, { keyboard: true, zoomControl: true, scrollWheelZoom: true, worldCopyJump: true });
        L.tileLayer(OSM_TILE_URL, { maxZoom: 19, attribution: OSM_ATTRIBUTION })
          .on("tileerror", () => setTileErrors((count) => count + 1))
          .addTo(map);
        layerRef.current = L.layerGroup().addTo(map);
        mapRef.current = map;
        setReady(true);
      })
      .catch((error: unknown) => {
        if (!cancelled) setLoadError(error instanceof Error ? error.message : "Map library failed to load");
      });
    const markersById = markerRefs.current;
    return () => {
      cancelled = true;
      mapRef.current?.remove();
      mapRef.current = null;
      layerRef.current = null;
      markersById.clear();
    };
  }, []);

  // Draw markers and fit the view whenever the marker set changes.
  useEffect(() => {
    const L = leafletRef.current;
    const map = mapRef.current;
    const layer = layerRef.current;
    if (!ready || !L || !map || !layer) return;
    layer.clearLayers();
    markerRefs.current.clear();
    for (const item of markers) {
      const marker = L.marker([item.lat, item.lng], {
        title: item.title,
        alt: item.title,
        keyboard: true,
        riseOnHover: true,
        icon: L.divIcon({ className: "", html: markerHtml(item.color ?? DEFAULT_COLOR, item.approximate), iconSize: [18, 18], iconAnchor: [9, 9], popupAnchor: [0, -10] }),
      });
      marker.bindPopup(() => popupContent(item));
      marker.on("click", () => onSelectRef.current?.(item.id));
      marker.addTo(layer);
      markerRefs.current.set(item.id, marker);
    }
    const plan = planView(markers);
    if (plan.kind === "center") map.setView([plan.lat, plan.lng], SINGLE_MARKER_ZOOM);
    else if (plan.kind === "bounds") map.fitBounds([[plan.south, plan.west], [plan.north, plan.east]], { padding: [40, 40], maxZoom: MAX_FIT_ZOOM });
  }, [ready, markers]);

  // Focus a marker chosen from the list.
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map || !selectedId) return;
    const marker = markerRefs.current.get(selectedId);
    if (!marker) return;
    map.setView(marker.getLatLng(), Math.max(map.getZoom(), 15));
    marker.openPopup();
  }, [ready, selectedId]);

  return (
    <div>
      <div
        ref={container}
        role="region"
        aria-label={ariaLabel}
        className="relative isolate z-0 h-[60vh] min-h-[320px] w-full overflow-hidden rounded-xl border border-[var(--ch-border)] bg-[var(--ch-surface-muted)]"
      />
      {loadError ? <p className="mt-2 text-sm text-[var(--ch-error-text)]">Map failed to load: {loadError}</p> : null}
      {tileErrors > 0 ? (
        <p className="mt-2 text-sm text-[var(--ch-warning-text)]">
          {tileErrors} map tile{tileErrors === 1 ? "" : "s"} failed to load from OpenStreetMap. Markers and the list below remain available; dashed markers are approximate.
        </p>
      ) : null}
    </div>
  );
}
