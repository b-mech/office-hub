const BASE=process.env.NEXT_PUBLIC_API_URL||"/backend-api";
export type MapProperty={property_id:number;street_address:string;group_name:string|null;latitude:number|null;longitude:number|null;unit_count:number;last_inspection_date:string|null;inspection_status:"current"|"due"|"overdue"|"never"};
export async function getRentalMap():Promise<MapProperty[]>{const r=await fetch(`${BASE}/api/rentals/properties/map`,{cache:"no-store"});if(!r.ok)throw new Error(`Map API ${r.status}`);return r.json()}
