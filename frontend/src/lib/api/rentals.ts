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
export type PreviewRow = { source_row_number:number; property_street_address:string|null; unit_label:string|null; tenant_names:string[]; rent:string|null; lease_start:string|null; lease_end:string|null; property_match:"existing_unit"|"existing_property"|"new_property"|"unknown"; errors:string[]; warnings:string[] };
export type ImportValidation = { dry_run:true; filename:string; ok:boolean; file_errors:string[]; total_rows:number; rows_ready:number; rows_with_errors:number; rows_with_warnings:number; rows:PreviewRow[] };
/** Dry run: the server only checks the file. Nothing is stored and no extraction runs. */
export function validateLeaseImport(file:File) { const body=new FormData(); body.append("file",file); return request<ImportValidation>(`${PATH}/upload?dry_run=true`,{method:"POST",body}); }
export const IMPORT_COLUMNS: { name:string; required?:boolean; format:string }[] = [
  { name:"Property Street Address", required:true, format:"Exactly as in Office Hub, e.g. 166 Clubhouse Drive" },
  { name:"Unit Label", format:"Blank for a single-unit house; e.g. Up, Down, Basement" },
  { name:"Tenant 1 Name", required:true, format:"Primary contact" },
  { name:"Tenant 1 Phone", format:"Any format; normalised on import" },
  { name:"Tenant 1 Email", format:"name@example.com" },
  { name:"Tenant 2 / 3 Name, Phone, Email", format:"Optional additional tenants" },
  { name:"Rent", required:true, format:"Monthly amount, number only (e.g. 1850)" },
  { name:"Rent Discount", format:"Monthly discount, number" },
  { name:"Deposit", format:"Number" },
  { name:"Water Credit", format:"Monthly amount, number" },
  { name:"Lease Start", required:true, format:"Date, YYYY-MM-DD" },
  { name:"Lease End", format:"Date, YYYY-MM-DD; blank = month to month" },
  { name:"Notes", format:"Free text; extra tenants can be listed here" },
];
export function batchSummary(batch:ImportBatch) {
  const count=(status:string)=>batch.rows.filter(r=>r.review_status===status).length;
  return { total:batch.rows.length, approved:count("approved"), rejected:count("rejected"), edited:count("edited"),
    pending:batch.rows.filter(r=>!["approved","rejected"].includes(r.review_status)).length,
    leasesWritten:batch.rows.filter(r=>r.committed_lease_id!==null).length,
    unresolved:batch.rows.filter(r=>r.match_type==="unresolved"&&!["approved","rejected"].includes(r.review_status)).length };
}
export const patchImportRow = (id:number, payload:Record<string,unknown>) => request<ImportRow>(`${PATH}/rows/${id}`,{method:"PATCH",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});
export const approveImportRow = (id:number) => request<ImportRow>(`${PATH}/rows/${id}/approve`,{method:"POST"});
export const rejectImportRow = (id:number) => request<ImportRow>(`${PATH}/rows/${id}/reject`,{method:"POST"});
export const approveAllClean = (id:number) => request<{approved:number;skipped_for_review:number}>(`${PATH}/batches/${id}/approve-all`,{method:"POST"});
