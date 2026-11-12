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

export function isLocatedProperty(item: MapProperty): item is LocatedMapProperty {
  return Number.isFinite(item.latitude) && Number.isFinite(item.longitude);
}

export function locatedProperties(items: readonly MapProperty[]): LocatedMapProperty[] {
  return items.filter(isLocatedProperty);
}
