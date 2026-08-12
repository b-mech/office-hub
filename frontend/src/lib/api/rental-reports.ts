const BASE = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";
const P = "/api/rentals/reports";

export type Candidate = { inspection_id:number; property_id:number; address:string; unit_label:string|null; inspection_date:string; front_yard_score:number|null; back_yard_score:number|null };
export type ReportPhoto = { id:number; caption:string|null; url:string|null };
export type ReportItem = { id:string; inspection_id:number; address:string; unit_label:string|null; inspection_date:string; inspection_type:string; front_yard_score:number|null; front_yard_notes:string|null; back_yard_score:number|null; back_yard_notes:string|null; building_condition:string|null; building_notes:string|null; occupancy_flag:string|null; general_notes:string|null; notes:string|null; notes_submitted_at:string|null; photos:ReportPhoto[] };
export type Report = { id:string; title:string; status:string; recipient_email:string|null; expires_at:string; sent_at:string|null; items:ReportItem[] };

async function req<T>(path:string,init?:RequestInit):Promise<T>{const response=await fetch(BASE+path,{...init,headers:{"Content-Type":"application/json",...(init?.headers||{})},cache:"no-store"});if(!response.ok){const body=await response.json().catch(()=>({}));throw new Error(body.detail||`API ${response.status}`)}return response.json()}
export const candidates=()=>req<Candidate[]>(`${P}/candidates`);
export const reports=()=>req<Report[]>(P);
export const create=(title:string,inspection_ids:number[],expires_in_days:number)=>req<Report>(P,{method:"POST",body:JSON.stringify({title,inspection_ids,expires_in_days})});
export const send=(id:string,recipient_email:string,public_base_url:string)=>req<{report:Report;public_url:string}>(`${P}/${id}/send`,{method:"POST",body:JSON.stringify({recipient_email,public_base_url})});
export const publicReport=(token:string)=>req<Report>(`${P}/public/${token}`);
export const saveNote=(token:string,itemId:string,notes:string)=>req<{id:string;notes:string|null;notes_submitted_at:string}>(`${P}/public/${token}/items/${itemId}`,{method:"PATCH",body:JSON.stringify({notes})});
export const absolutePhotoUrl=(url:string)=>BASE+url;
