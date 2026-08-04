export interface ContractorCategory { id: string; name: string; slug: string }
export interface Contractor {
  id: string; name: string; contact_name?: string | null; email?: string | null; phone?: string | null;
  address?: string | null; notes?: string | null; active: boolean; categories: ContractorCategory[];
  created_at: string; updated_at: string;
}
export interface ContractorPayload {
  name: string; contact_name?: string | null; email?: string | null; phone?: string | null;
  address?: string | null; notes?: string | null; active?: boolean; category_ids: string[];
}
export type TenderStatus = "draft" | "sent" | "bids_in" | "compared" | "awarded" | "cancelled";
export type TenderDocumentType = "plan" | "markup" | "spec";
export interface TenderDocument { id: string; tender_package_id: string; document_type: TenderDocumentType; file_path: string; original_filename: string; uploaded_at: string }
export interface TenderPackage {
  id: string; property_id: string; category_id: string; category: ContractorCategory; scope_description: string;
  status: TenderStatus; due_date?: string | null; documents: TenderDocument[]; created_at: string; updated_at: string;
}
