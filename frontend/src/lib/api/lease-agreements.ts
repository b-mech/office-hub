const BASE = process.env.NEXT_PUBLIC_API_URL || "/backend-api";
const PATH = "/api/rentals/leases";

export type Tenant = { name: string; email: string; phone?: string | null };
export type Lease = {
  id: string; unit_id: number; tenancy_id: number | null; status: string; display_status: string;
  context: Record<string, unknown>; tenants: Tenant[]; draft_pdf_key: string | null;
  docusign_envelope_id: string | null; signed_pdf_box_url: string | null;
  contact_form_data: { tenants?: Record<string, string>[]; occupants?: Record<string, string>[];
    emergency_contacts?: Record<string, string>[]; vehicles?: Record<string, string>[]; pets?: Record<string, string>[] } | null;
  created_at: string; sent_at: string | null; completed_at: string | null;
};
export type Property = { id: number; street_address: string; municipality: string | null;
  is_multiplex: boolean; is_condo: boolean; lease_utility_override: Record<string, string | null> | null };
export type UnitLeases = { unit: { id: number; unit_label: string | null }; property: Property;
  has_imported_lease: boolean; leases: Lease[] };

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${PATH}${path}`, { ...init, credentials: "include", cache: "no-store" });
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    throw new Error(detail.detail || `Lease request failed (${response.status})`);
  }
  return response.json() as Promise<T>;
}
const json = (data: unknown): RequestInit => ({ headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) });
export const unitLeases = (unitId: number) => request<UnitLeases>(`/units/${unitId}`);
export const getLease = (id: string) => request<Lease>(`/${id}`);
export const tenantRecords = (id: string) => request<{id: number; name: string; phone: string | null; email: string | null}[]>(`/${id}/tenant-records`);
export const leaseTask = (id: string) => request<{id: string; title: string; status: string; created_at: string} | null>(`/${id}/task`);
export const completeLeaseTask = (id: string) => request<{status: string}>(`/${id}/task/complete`, { method: "POST" });
export type LeaseStartFrom = "blank" | "tenancy";
export const createLease = (unitId: number, copyId?: string, startFrom?: LeaseStartFrom) => request<Lease>("", { method: "POST", ...json({ unit_id: unitId, copy_id: copyId, start_from: copyId ? undefined : startFrom }) });
export const saveLease = (id: string, context: Record<string, unknown>) => request<Lease>(`/${id}`, { method: "PATCH", ...json({ context }) });
export const sendLease = (id: string) => request<Lease>(`/${id}/send`, { method: "POST" });
export const voidLease = (id: string, reason: string) => request<Lease>(`/${id}/void`, { method: "POST", ...json({ reason }) });
export const resendLease = (id: string) => request<{ status: string }>(`/${id}/resend`, { method: "POST" });
export const updateProperty = (id: number, value: Omit<Property, "id" | "street_address">) => request<{id: number}>(`/properties/${id}`, { method: "PATCH", ...json(value) });
export const applyContacts = (id: string, updates: Record<string, unknown>[]) => request<{status: string}>(`/${id}/apply-contacts`, { method: "POST", ...json({ updates }) });
export const pdfUrl = (id: string) => `${BASE}${PATH}/${id}/pdf`;
export async function preview(id: string): Promise<Blob> {
  const response = await fetch(`${BASE}${PATH}/${id}/preview`, { method: "POST", credentials: "include" });
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    throw new Error(detail.detail || `Preview failed (${response.status})`);
  }
  return response.blob();
}
