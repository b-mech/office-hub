import { tenantHeaders } from "@/lib/tenant";
export type LocationResult = {
  latitude: number | null; longitude: number | null; geocode_precision: string | null;
  geocode_source: string | null; geocoded_at: string | null; location_set_by: string | null;
  can_reset_location: boolean; warnings: string[]; actor_is_fallback: boolean;
};
export async function patchLocation(kind: "lot" | "project" | "rental", id: string, data: {action: "set" | "reset" | "clear";latitude?:number;longitude?:number}): Promise<LocationResult> {
  const path = kind === "rental" ? `/api/rentals/properties/${encodeURIComponent(id)}/location` : `/api/v1/lots/${encodeURIComponent(id)}/location`;
  const response = await fetch(`/backend-api${path}`, { method: "PATCH", credentials: "include", headers: { "Content-Type": "application/json", ...tenantHeaders() }, body: JSON.stringify(data) });
  const result = await response.json().catch(()=>({}));
  if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : `Location update failed (${response.status})`);
  return result as LocationResult;
}
