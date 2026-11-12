"use client";

import "leaflet/dist/leaflet.css";
import "leaflet.markercluster/dist/MarkerCluster.css";
import "leaflet.markercluster/dist/MarkerCluster.Default.css";
import { useEffect, useRef, useState } from "react";
import type { Map as LeafletMap, MarkerClusterGroup } from "leaflet";
import type { MapProperty } from "@/lib/api/rentals-map";
import {
  INSPECTION_COLORS,
  OSM_ATTRIBUTION,
  OSM_MAX_NATIVE_ZOOM,
  OSM_MAX_ZOOM,
  OSM_TILE_URL,
  locatedProperties,
} from "@/lib/rentals-map-points";

function markerHtml(color: string): string {
  return `<span style="display:block;width:20px;height:20px;border-radius:9999px;background:${color};border:3px solid #fff;box-shadow:0 0 0 2px #fff,0 2px 8px #000b"></span>`;
}

function popupContent(property: MapProperty): HTMLElement {
  const root = document.createElement("div");
  root.style.minWidth = "210px";

  const title = document.createElement("strong");
  title.textContent = property.street_address;
  root.appendChild(title);

  const group = document.createElement("div");
  group.textContent = property.group_name || "";
  root.appendChild(group);

  const units = document.createElement("p");
  const unitLabel = property.unit_count === 1 ? "unit" : "units";
  units.textContent = `${property.unit_count} ${unitLabel} · ${property.inspection_status}`;
  root.appendChild(units);

  const inspected = document.createElement("p");
  inspected.textContent = property.last_inspection_date
    ? `Last inspected ${property.last_inspection_date}`
    : "Never inspected";
  root.appendChild(inspected);

  const link = document.createElement("a");
  link.href = `/rentals/inspections?property_id=${property.property_id}`;
  link.textContent = "View Units";
  link.style.color = "#1A527A";
  link.style.fontWeight = "bold";
  root.appendChild(link);

  const maintenance = document.createElement("a");
  maintenance.href = `/rentals/maintenance?property_id=${property.property_id}`;
  maintenance.textContent = "Maintenance";
  maintenance.style.color = "#1A527A";
  maintenance.style.fontWeight = "bold";
  maintenance.style.marginLeft = "12px";
  root.appendChild(maintenance);
  return root;
}

export function RentalsLeafletMap({ items }: { items: MapProperty[] }) {
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<LeafletMap | null>(null);
  const groupRef = useRef<MarkerClusterGroup | null>(null);
  const leafletRef = useRef<typeof import("leaflet") | null>(null);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tileErrors, setTileErrors] = useState(0);

  useEffect(() => {
    let cancelled = false;
    import("leaflet")
      .then(async (module) => {
        const L = (module as unknown as { default?: typeof import("leaflet") }).default ?? module;
        await import("leaflet.markercluster");
        if (cancelled || !container.current || mapRef.current) return;
        leafletRef.current = L;
        const map = L.map(container.current, {
          zoomControl: false,
          attributionControl: true,
          keyboard: true,
        }).setView([49.895, -97.138], 9);
        L.control.zoom({ position: "bottomleft" }).addTo(map);
        L.tileLayer(OSM_TILE_URL, {
          attribution: OSM_ATTRIBUTION,
          maxNativeZoom: OSM_MAX_NATIVE_ZOOM,
          maxZoom: OSM_MAX_ZOOM,
        }).on("tileerror", () => {
          if (!cancelled) setTileErrors((count) => count + 1);
        }).addTo(map);
        const group = L.markerClusterGroup({
          animate: true,
          maxClusterRadius: 48,
          showCoverageOnHover: false,
          spiderfyOnMaxZoom: true,
        });
        group.addTo(map);
        groupRef.current = group;
        mapRef.current = map;
        setReady(true);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Map failed to load");
      });
    return () => {
      cancelled = true;
      mapRef.current?.remove();
      mapRef.current = null;
      groupRef.current = null;
    };
  }, []);

  useEffect(() => {
    const L = leafletRef.current;
    const map = mapRef.current;
    const group = groupRef.current;
    if (!ready || !L || !map || !group) return;
    group.clearLayers();
    const located = locatedProperties(items);
    for (const property of located) {
      const color = INSPECTION_COLORS[property.inspection_status];
      const marker = L.marker([property.latitude, property.longitude], {
        title: property.street_address,
        icon: L.divIcon({
          className: "",
          html: markerHtml(color),
          iconSize: [20, 20],
          iconAnchor: [10, 10],
          popupAnchor: [0, -12],
        }),
      });
      marker.bindPopup(() => popupContent(property));
      group.addLayer(marker);
    }
    if (located.length) {
      const bounds = L.latLngBounds(located.map((property) => [property.latitude, property.longitude]));
      map.fitBounds(bounds, { padding: [60, 60], maxZoom: 16 });
    }
  }, [ready, items]);

  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map || !container.current) return;
    const resize = () => map.invalidateSize({ pan: false, animate: false });
    const observer = new ResizeObserver(resize);
    observer.observe(container.current);
    window.addEventListener("resize", resize);
    const frame = requestAnimationFrame(resize);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", resize);
      cancelAnimationFrame(frame);
    };
  }, [ready]);

  return (
    <div className="relative min-h-0 flex-1 bg-[var(--ch-page-bg)]">
      <style>{`
        .leaflet-control-attribution {
          max-width: calc(100vw - 3.5rem);
          font-size: 10px;
          line-height: 1.3;
          background: rgba(255, 255, 255, 0.92);
        }
      `}</style>
      <div
        ref={container}
        role="region"
        aria-label="Rental properties map"
        className="absolute inset-0 z-0"
      />
      {error || tileErrors ? (
        <p role="alert" className="absolute bottom-8 left-14 z-10 rounded-lg bg-white/95 p-2 text-xs text-[var(--ch-error-text)]">
          {error ?? `${tileErrors} map tiles failed to load`}
        </p>
      ) : null}
    </div>
  );
}
