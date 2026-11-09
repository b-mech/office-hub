export const BASEMAP_STORAGE_KEY = "officehub.map.basemap";
export const BASEMAP_CHOICES = [
  { id: "street", label: "Street" },
  { id: "satellite", label: "Satellite" },
  { id: "hybrid", label: "Hybrid" },
] as const;
export type MapBasemap = typeof BASEMAP_CHOICES[number]["id"];
const isBasemap = (value: unknown): value is MapBasemap => BASEMAP_CHOICES.some((choice) => choice.id === value);
export function resolveBasemap(requested: unknown, saved: unknown): MapBasemap {
  return isBasemap(requested) ? requested : isBasemap(saved) ? saved : "street";
}
export function readBasemap(storage: { getItem(key: string): string | null } | null, requested: string | null = null): MapBasemap {
  try { return resolveBasemap(requested, storage?.getItem(BASEMAP_STORAGE_KEY)); }
  catch { return resolveBasemap(requested, null); }
}
export function saveBasemap(storage: { setItem(key: string, value: string): void } | null, choice: MapBasemap): boolean {
  try { if (!storage) return false; storage.setItem(BASEMAP_STORAGE_KEY, choice); return true; }
  catch { return false; } // Private browsing/storage restrictions must not break the map.
}
export interface BasemapTile {
  id: string; url: string; attribution: string; maxNativeZoom: number; maxZoom: number; zIndex: number;
}
const imagery: BasemapTile = {
  id: "imagery",
  url: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
  attribution: "Tiles © Esri — Source: Esri, Maxar, Earthstar Geographics, and the GIS User Community",
  maxNativeZoom: 19, maxZoom: 20, zIndex: 1,
};
export function basemapTiles(choice: MapBasemap): readonly BasemapTile[] {
  if (choice === "street") return [{ id: "street", url: "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors', maxNativeZoom: 19, maxZoom: 20, zIndex: 1 }];
  if (choice === "satellite") return [imagery];
  return [imagery,
    { id: "roads", url: "https://services.arcgisonline.com/ArcGIS/rest/services/Reference/World_Transportation/MapServer/tile/{z}/{y}/{x}", attribution: "Reference roads © Esri, HERE, Garmin, © OpenStreetMap contributors, and the GIS User Community", maxNativeZoom: 19, maxZoom: 20, zIndex: 2 },
    { id: "labels", url: "https://services.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}", attribution: "Reference labels © Esri, HERE, Garmin, © OpenStreetMap contributors, and the GIS User Community", maxNativeZoom: 19, maxZoom: 20, zIndex: 3 },
  ];
}
