const BASE = process.env.NEXT_PUBLIC_API_URL || "/backend-api";
const PATH = "/api/rentals/lease-import";

export type ImportRow = { id:number; batch_id:number; source_row_number:number; raw_data:Record<string,unknown>; parsed_data:Record<string,unknown>|null; confidence:Record<string,unknown>|null; match_type:string|null; matched_unit_id:number|null; suggested_action:string|null; existing_lease_id:number|null; review_status:string; reviewed_at:string|null; committed_lease_id:number|null; created_at:string };
export type ImportBatch = { id:number; source_filename:string; uploaded_at:string; status:string; total_rows:number; rows_pending:number; rows:ImportRow[] };
export type RentalUnit = { id:number; street_address:string; unit_label:string|null };

async function request<T>(path:string, options?:RequestInit):Promise<T> {
  const response = await fetch(`${BASE}${path}`, { ...options, cache:"no-store" });
  if (!response.ok) { const body = await response.json().catch(()=>({})); throw new Error(body.detail || `API error ${response.status}`); }
  return response.json() as Promise<T>;
}
export const templateUrl = `${BASE}${PATH}/template`;
export const listBatches = () => request<ImportBatch[]>(`${PATH}/batches`);
export const getBatch = (id:number) => request<ImportBatch>(`${PATH}/batches/${id}`);
export const listRentalUnits = () => request<RentalUnit[]>(`${PATH}/units`);
export function uploadLeaseImport(file:File) { const body=new FormData(); body.append("file",file); return request<ImportBatch>(`${PATH}/upload`,{method:"POST",body}); }
export const patchImportRow = (id:number, payload:Record<string,unknown>) => request<ImportRow>(`${PATH}/rows/${id}`,{method:"PATCH",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});
export const approveImportRow = (id:number) => request<ImportRow>(`${PATH}/rows/${id}/approve`,{method:"POST"});
export const rejectImportRow = (id:number) => request<ImportRow>(`${PATH}/rows/${id}/reject`,{method:"POST"});
export const approveAllClean = (id:number) => request<{approved:number;skipped_for_review:number}>(`${PATH}/batches/${id}/approve-all`,{method:"POST"});
