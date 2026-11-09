// Pure helpers for turning stored record coordinates into map markers.
// No geocoding and no defaults: a record without valid stored coordinates is
// counted as missing, never placed at a guessed location.

export type CoordinateValue = number | string | null | undefined;

export interface MapRecord {
  id: string;
  label: string;
  latitude?: CoordinateValue;
  longitude?: CoordinateValue;
  geocode_precision?: string | null;
}

export interface LocatedPoint<T extends MapRecord> {
  record: T;
  lat: number;
  lng: number;
  approximate: boolean;
}

export type ExclusionReason = "missing" | "invalid" | "shared";

export interface PartitionedPoints<T extends MapRecord> {
  located: LocatedPoint<T>[];
  approximate: LocatedPoint<T>[];
  /** No stored latitude/longitude. */
  missing: T[];
  /** Stored values that are not usable: non-numeric, out of range, or the 0,0 sentinel. */
  invalid: T[];
  /** Identical coordinates stored for several different addresses: an approximate (city/street-level) geocode, not a real location. */
  shared: T[];
}

/** Minimum number of distinct records on exactly the same point before the point is treated as an approximate geocode. */
export const SHARED_COORDINATE_THRESHOLD = 2;

/** Parses one stored coordinate. Returns null for missing values and NaN for present-but-unusable ones. */
export function parseCoordinate(value: CoordinateValue): number | null {
  if (value === null || value === undefined) return null;
  if (typeof value === "string" && value.trim() === "") return null;
  const numeric = typeof value === "number" ? value : Number(value.trim());
  return Number.isFinite(numeric) ? numeric : Number.NaN;
}

export function isValidLatLng(lat: number, lng: number): boolean {
  if (!Number.isFinite(lat) || !Number.isFinite(lng)) return false;
  if (lat < -90 || lat > 90 || lng < -180 || lng > 180) return false;
  // 0,0 ("Null Island") is the usual placeholder for "no coordinates".
  if (lat === 0 && lng === 0) return false;
  return true;
}

const coordinateKey = (lat: number, lng: number) => `${lat.toFixed(6)},${lng.toFixed(6)}`;

/**
 * Splits records into plottable points and the reasons the rest are not plotted.
 * Records whose stored coordinates are shared, to six decimals, by
 * SHARED_COORDINATE_THRESHOLD or more labels are approximate, never exact.
 * Only validated house/street precision can plot; legacy/locality points cannot.
 */
export function partitionMapRecords<T extends MapRecord>(
  records: readonly T[],
  sharedThreshold: number = SHARED_COORDINATE_THRESHOLD,
): PartitionedPoints<T> {
  const missing: T[] = [];
  const invalid: T[] = [];
  const candidates: LocatedPoint<T>[] = [];
  for (const record of records) {
    const lat = parseCoordinate(record.latitude);
    const lng = parseCoordinate(record.longitude);
    if (lat === null && lng === null) missing.push(record);
    else if (lat === null || lng === null || !isValidLatLng(lat, lng)) invalid.push(record);
    else if (!["house", "street"].includes(record.geocode_precision ?? "")) invalid.push(record);
    else candidates.push({ record, lat, lng, approximate: record.geocode_precision === "street" });
  }

  const labelsByKey = new Map<string, Set<string>>();
  for (const point of candidates) {
    const key = coordinateKey(point.lat, point.lng);
    const labels = labelsByKey.get(key) ?? new Set<string>();
    labels.add(point.record.label.trim().toLowerCase());
    labelsByKey.set(key, labels);
  }

  const located: LocatedPoint<T>[] = [];
  const shared: T[] = [];
  const approximate: LocatedPoint<T>[] = [];
  for (const point of candidates) {
    const labels = labelsByKey.get(coordinateKey(point.lat, point.lng));
    if (sharedThreshold > 1 && labels && labels.size >= sharedThreshold) point.approximate = true;
    located.push(point);
    if (point.approximate) approximate.push(point);
  }
  return { located, approximate, missing, invalid, shared };
}

export type ViewPlan =
  | { kind: "none" }
  | { kind: "center"; lat: number; lng: number }
  | { kind: "bounds"; south: number; west: number; north: number; east: number };

/** One point centres the map; several points fit their bounds; none means there is nothing to show. */
export function planView(points: readonly { lat: number; lng: number }[]): ViewPlan {
  if (points.length === 0) return { kind: "none" };
  const first = points[0];
  let south = first.lat, north = first.lat, west = first.lng, east = first.lng;
  for (const { lat, lng } of points) {
    south = Math.min(south, lat);
    north = Math.max(north, lat);
    west = Math.min(west, lng);
    east = Math.max(east, lng);
  }
  if (south === north && west === east) return { kind: "center", lat: first.lat, lng: first.lng };
  return { kind: "bounds", south, west, north, east };
}
