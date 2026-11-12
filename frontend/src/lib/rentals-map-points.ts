import type { MapProperty } from "@/lib/api/rentals-map";

export const INSPECTION_COLORS = {
  current: "#2E7D32",
  due: "#D6A700",
  overdue: "#C62828",
  never: "#777777",
} as const;

export const OSM_TILE_URL = "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png";
export const OSM_ATTRIBUTION =
  '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';
export const OSM_MAX_NATIVE_ZOOM = 19;
export const OSM_MAX_ZOOM = 19;

export type LocatedMapProperty = MapProperty & { latitude: number; longitude: number };

export function asCoordinate(value: unknown): number | null {
  if (value === null || value === undefined || value === "") return null;
  const numeric = typeof value === "number" ? value : Number(value);
  return Number.isFinite(numeric) ? numeric : null;
}

export function isLocatedProperty(item: MapProperty): item is LocatedMapProperty {
  return asCoordinate(item.latitude) !== null && asCoordinate(item.longitude) !== null;
}

export function locatedProperties(items: readonly MapProperty[]): LocatedMapProperty[] {
  const located: LocatedMapProperty[] = [];
  for (const item of items) {
    const latitude = asCoordinate(item.latitude);
    const longitude = asCoordinate(item.longitude);
    if (latitude === null || longitude === null) continue;
    located.push({ ...item, latitude, longitude });
  }
  return located;
}
