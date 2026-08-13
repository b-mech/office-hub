const BASE = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";
const P = "/api/rentals";

export type Photo = { id: number; preview_url: string | null; caption: string | null };
export type Inspection = { id:number; unit_id:number; inspection_type:string; inspection_date:string; inspector_name:string|null; front_yard_score:number|null; front_yard_notes:string|null; back_yard_score:number|null; back_yard_notes:string|null; building_condition:string|null; building_notes:string|null; occupancy_flag:string|null; general_notes:string|null; status:string; photos:Photo[] };
export type Unit = { id:number; street_address:string; group_name:string|null; unit_label:string|null; last_inspection:{id:number;inspection_date:string;inspection_type:string;status:string}|null };

async function req<T>(path:string, options?:RequestInit):Promise<T> {
  const response = await fetch(BASE + path, { ...options, cache:"no-store" });
  if (!response.ok) { const body = await response.json().catch(() => ({})); throw new Error(body.detail || `API ${response.status}`); }
  return response.status === 204 ? undefined as T : response.json();
}

export function units(q=""):Promise<Unit[]> {
  const propertyId = typeof window === "undefined" ? null : new URLSearchParams(window.location.search).get("property_id");
  return req<Unit[]>(`${P}/units?q=${encodeURIComponent(q)}${propertyId ? `&property_id=${encodeURIComponent(propertyId)}` : ""}`);
}
export const history=(id:number)=>req<Inspection[]>(`${P}/units/${id}/inspections`);
export const detail=(id:number)=>req<Inspection>(`${P}/inspections/${id}`);
export const create=(unit_id:number)=>req<Inspection>(`${P}/inspections`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({unit_id})});
export const patch=(id:number,data:Partial<Inspection>)=>req<Inspection>(`${P}/inspections/${id}`,{method:"PATCH",headers:{"Content-Type":"application/json"},body:JSON.stringify(data)});
export const submit=(id:number)=>req<Inspection>(`${P}/inspections/${id}/submit`,{method:"POST"});
export const deleteInspection=(id:number)=>req<void>(`${P}/inspections/${id}`,{method:"DELETE"});
export const upload=(id:number,file:File)=>{const body=new FormData();body.append("files",file);return req<Photo[]>(`${P}/inspections/${id}/photos`,{method:"POST",body})};
export const remove=(id:number,photoId:number)=>req<void>(`${P}/inspections/${id}/photos/${photoId}`,{method:"DELETE"});
