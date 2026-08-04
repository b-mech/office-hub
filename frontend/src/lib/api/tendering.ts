import type { Contractor, ContractorCategory, ContractorPayload, TenderDocument, TenderDocumentType, TenderPackage, TenderStatus } from "@/types/tendering";

const BASE = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";
async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, { ...options, cache: "no-store", headers: { ...(options?.body instanceof FormData ? {} : { "Content-Type": "application/json" }), ...(options?.headers || {}) } });
  if (!response.ok) { const body = await response.json().catch(() => ({})); throw new Error(typeof body.detail === "string" ? body.detail : `API error ${response.status}`); }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}
export const getContractorCategories = () => request<ContractorCategory[]>("/api/contractor-categories");
export function getContractors(categoryId?: string, active?: boolean) {
  const params = new URLSearchParams(); if (categoryId) params.set("category_id", categoryId); if (active != null) params.set("active", String(active));
  return request<Contractor[]>(`/api/contractors${params.size ? `?${params}` : ""}`);
}
export const createContractor = (payload: ContractorPayload) => request<Contractor>("/api/contractors", { method: "POST", body: JSON.stringify(payload) });
export const updateContractor = (id: string, payload: Partial<ContractorPayload>) => request<Contractor>(`/api/contractors/${id}`, { method: "PATCH", body: JSON.stringify(payload) });
export const deactivateContractor = (id: string) => request<Contractor>(`/api/contractors/${id}`, { method: "DELETE" });
export const getTenderPackages = (propertyId: string) => request<TenderPackage[]>(`/api/properties/${propertyId}/tender-packages`);
export const createTenderPackage = (propertyId: string, payload: { category_id: string; scope_description: string; due_date?: string | null }) => request<TenderPackage>(`/api/properties/${propertyId}/tender-packages`, { method: "POST", body: JSON.stringify(payload) });
export const updateTenderPackage = (id: string, payload: Partial<{ category_id: string; scope_description: string; due_date: string | null; status: TenderStatus }>) => request<TenderPackage>(`/api/tender-packages/${id}`, { method: "PATCH", body: JSON.stringify(payload) });
export function uploadTenderDocument(id: string, type: TenderDocumentType, file: File) { const body = new FormData(); body.set("document_type", type); body.set("file", file); return request<TenderDocument>(`/api/tender-packages/${id}/documents`, { method: "POST", body }); }
export const deleteTenderDocument = (id: string) => request<void>(`/api/tender-documents/${id}`, { method: "DELETE" });
export const tenderDocumentUrl = (id: string) => `${BASE}/api/tender-documents/${id}/content`;
