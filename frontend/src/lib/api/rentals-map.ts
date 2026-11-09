import { tenantHeaders } from "@/lib/tenant";
export type MapProperty = { property_id:number;street_address:string;group_name:string|null;city:string|null;municipality:string|null;latitude:number|null;longitude:number|null;geocode_precision:"manual"|"house"|"street"|"locality"|"not_found"|null;geocode_source:string|null;geocoded_at:string|null;location_set_by:string|null;can_reset_location:boolean;unit_count:number;last_inspection_date:string|null;inspection_status:"current"|"due"|"overdue"|"never" };
export async function getRentalMap(): Promise<MapProperty[]> {
 const response = await fetch("/backend-api/api/rentals/properties/map", { credentials:"include",cache:"no-store",headers:tenantHeaders() });
 if(!response.ok) throw new Error(`Map API ${response.status}`);
 return response.json();
}
