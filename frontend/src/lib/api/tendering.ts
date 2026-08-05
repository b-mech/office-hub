import type { Contractor, ContractorCategory, ContractorPayload, MarkupDocumentState, TenderAward, TenderBid, TenderDocument, TenderDocumentMarkup, TenderDocumentMarkupSummary, TenderDocumentType, TenderLineItem, TenderMarkupCalibration, TenderPackage, TenderStatus } from "@/types/tendering";

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
export const getTenderDocumentMarkups = (id: string) => request<TenderDocumentMarkupSummary[]>(`/api/tender-documents/${id}/markups`);
export const getTenderDocumentMarkup = (id: string) => request<TenderDocumentMarkup>(`/api/tender-document-markups/${id}`);
export const saveTenderDocumentMarkup = (id: string, annotationData: MarkupDocumentState, calibration: TenderMarkupCalibration | null) => request<TenderDocumentMarkup>(`/api/tender-documents/${id}/markups`, { method: "POST", body: JSON.stringify({ annotation_data: annotationData, calibration }) });
export const tenderDocumentMarkupPdfUrl = (id: string) => `${BASE}/api/tender-document-markups/${id}/flattened`;
export const createTenderBid = (packageId: string, contractorId: string) => request<TenderBid>(`/api/tender-packages/${packageId}/bids`, { method: "POST", body: JSON.stringify({ contractor_id: contractorId }) });
export const getTenderBids = (packageId: string) => request<TenderBid[]>(`/api/tender-packages/${packageId}/bids`);
export function uploadTenderBidDocument(id: string, file: File) { const body = new FormData(); body.set("file", file); return request<TenderBid>(`/api/tender-bids/${id}/documents`, { method: "POST", body }); }
export const updateTenderBid = (id: string, payload: Partial<{ quote_amount: string; extracted_line_items: TenderLineItem[]; excluded_scope_notes: string | null; reviewer_notes: string | null }>) => request<TenderBid>(`/api/tender-bids/${id}`, { method: "PATCH", body: JSON.stringify(payload) });
export const cancelTenderBid = (id: string) => request<void>(`/api/tender-bids/${id}`, { method: "DELETE" });
export const tenderBidDocumentUrl = (id: string) => `${BASE}/api/tender-bid-documents/${id}/content`;
export const awardTenderPackage = (packageId: string, payload: { winning_bid_id: string; budget_id: string; budget_line_id: string; award_instructions: string; project_start_date: string; contractor_start_date: string }) => request<TenderAward>(`/api/tender-packages/${packageId}/award`, { method: "POST", body: JSON.stringify(payload) });
