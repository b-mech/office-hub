import type { MapRecord } from "./map-points";

export interface PinRecord extends MapRecord {
  address: string;
  kind: "lot" | "project" | "rental";
  community: string;
  municipality?: string | null;
  development_id?: string | null;
  lot_number?: string | null;
  status?: string | null;
  client?: string | null;
  href: string;
  color: string;
  details?: string[];
  geocode_source?: string | null;
  geocoded_at?: string | null;
  location_set_by?: string | null;
  can_reset_location?: boolean;
}
export type PinDraft = { id: string; lat: number; lng: number; moved: boolean; startLabel: string };
export const needsPin = (row: Pick<MapRecord, "geocode_precision">) => !["house", "manual"].includes(row.geocode_precision ?? "");
export const outsideManitoba = (lat: number, lng: number) => !(lat >= 49 && lat <= 60 && lng >= -102 && lng <= -88.8);
export function storedPoint(row: MapRecord): { lat: number; lng: number } | null {
  if (!["house", "street", "manual"].includes(row.geocode_precision ?? "") || row.latitude == null || row.longitude == null || row.latitude === "" || row.longitude === "") return null;
  const lat = Number(row.latitude), lng = Number(row.longitude);
  return Number.isFinite(lat) && Number.isFinite(lng) && Math.abs(lat) <= 90 && Math.abs(lng) <= 180 ? { lat, lng } : null;
}
const CENTRES: [string, number, number][] = [
  ["lorette",49.74,-96.88],["landmark",49.672,-96.82],["grande pointe",49.777,-97.005],
  ["garson",50.076,-96.704],["brokenhead",50.076,-96.704],["west st. paul",49.99,-97.08],
  ["parkview pointe",49.982,-97.085],["headingley",49.86,-97.35],["forest grove",49.856,-97.333],
  ["dugald",49.88,-96.835],["wheatland",49.88,-96.835],["oakbank",49.94,-96.843],
  ["la salle",49.687,-97.261],["prairie view",49.687,-97.261],["macdonald",49.687,-97.261],
  ["ile des chenes",49.71,-96.986],["oak river",49.71,-96.986],["stony mountain",50.087,-97.219],
  ["mountain ridge",50.087,-97.219],["rockwood",50.087,-97.219],["new bothwell",49.59,-96.902],
  ["sunset acres",49.59,-96.902],["hanover",49.59,-96.902],["morden",49.191,-98.101],
  ["ste anne",49.67,-96.65],["ste. anne",49.67,-96.65],["finnigan",49.67,-96.65],
  ["ritchot",49.77,-97.0],["springfield",49.9,-96.84],["winnipeg",49.895,-97.138],
];
const normalize = (s: string) => s.normalize("NFD").replace(/[\u0300-\u036f]/g, "").replaceAll("-", " ").toLowerCase();
export function pinStart(row: PinRecord, records: readonly PinRecord[]): PinDraft {
  const own = storedPoint(row);
  if (own) return { id: row.id, ...own, moved: false, startLabel: row.geocode_precision === "street" ? "Approximate street starting point — not saved as manual" : "Existing pin — changes are unsaved" };
  const peers = records.filter((r) => r.id !== row.id && (row.development_id ? r.development_id === row.development_id : r.community === row.community && r.municipality === row.municipality)).map(storedPoint).filter((p): p is {lat:number;lng:number} => p !== null && !outsideManitoba(p.lat,p.lng));
  if (peers.length) return { id: row.id, lat: peers.reduce((n,p)=>n+p.lat,0)/peers.length, lng: peers.reduce((n,p)=>n+p.lng,0)/peers.length, moved: false, startLabel: "Unplaced — development starting area, not a saved pin" };
  const area = normalize(`${row.community} ${row.municipality ?? ""}`);
  const centre = CENTRES.find(([name])=>area.includes(name));
  return { id: row.id, lat: centre?.[1] ?? 49.895, lng: centre?.[2] ?? -97.138, moved: false, startLabel: centre ? "Unplaced — community starting area, not a saved pin" : "Unplaced — regional starting view; locate the community first" };
}
export function nextNeedsPin(records: readonly PinRecord[], currentId: string): PinRecord | undefined {
  const start = records.findIndex((r)=>r.id===currentId);
  return [...records.slice(start+1),...records.slice(0,start)].find(needsPin);
}
