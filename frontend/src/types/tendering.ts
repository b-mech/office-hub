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
export type TenderBidStatus = "invited" | "received" | "reviewed" | "cancelled";
export interface TenderLineItem { description: string; amount: string }
export interface TenderBidDocument { id: string; tender_bid_id: string; file_path: string; original_filename: string; uploaded_at: string }
export interface TenderBid {
  id: string; tender_package_id: string; contractor_id: string; contractor: Contractor; status: TenderBidStatus;
  quote_amount?: string | null; extracted_amount?: string | null; extracted_line_items?: TenderLineItem[] | null;
  excluded_scope_notes?: string | null; reviewer_notes?: string | null; invited_at?: string | null; received_at?: string | null;
  documents: TenderBidDocument[]; created_at: string; updated_at: string;
}
export interface TenderAward {
  id: string; tender_package_id: string; winning_bid_id: string; po_id: string; award_instructions: string;
  project_start_date: string; contractor_start_date: string; awarded_at: string;
  purchase_order?: { id: string; po_number: string; budget_id: string; budget_line_id: string; description: string; amount: string; status: string } | null;
}
export interface TenderPackage {
  id: string; property_id: string; category_id: string; category: ContractorCategory; scope_description: string;
  status: TenderStatus; due_date?: string | null; documents: TenderDocument[]; bids: TenderBid[]; award?: TenderAward | null; created_at: string; updated_at: string;
}
