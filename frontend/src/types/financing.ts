export type LenderType = "SCU" | "PRO" | "STRIDE" | "RSU" | "CLIENT" | "OTHER";
export type DrawFlag = "OVER_DRAWN" | "FACILITY_NOT_SET" | "NOT_STARTED" | "CHECK_OTP" | "NO_PROGRESS_REPORT" | "NEEDS_LINK" | "SYNC_CONFLICT" | null;

export interface LenderSummary {
  total_drawable: string | number | null;
  properties: number;
  flagged: number;
}

export interface FinancingProperty {
  property_id: string;
  address: string;
  lender_type: LenderType;
  sold_or_spec?: string | null;
  stage?: string | null;
  stage_is_estimate: boolean;
  possession_date?: string | null;
  build_start?: string | null;
  client_name?: string | null;
  banker_raw?: string | null;
  lender_name?: string | null;
  total_facility?: string | number | null;
  opening_balance?: string | number | null;
  already_drawn?: string | number | null;
  last_draw_date?: string | null;
  last_draw_amount?: string | number | null;
  requested_draw_amount?: string | number | null;
  requested_draw_as_of?: string | null;
  commitment_source?: string | null;
  commitment_confirmed_at?: string | null;
  rate?: string | number | null;
  account_number?: string | null;
  account_title?: string | null;
  account_type?: string | null;
  current_balance?: string | number | null;
  outstanding_balance?: string | number | null;
  account_currency?: string | null;
  maturity_date?: string | null;
  member_number?: string | null;
  next_interest_payment_date?: string | null;
  next_payment_date?: string | null;
  account_nickname?: string | null;
  open_date?: string | null;
  original_loan_amount?: string | number | null;
  payment_schedule?: string | null;
  term_length_days?: number | null;
  daily_interest_estimate?: string | number | null;
  monthly_interest_estimate?: string | number | null;
  annual_interest_estimate?: string | number | null;
  notes?: string | null;
  draw_eligible?: string | number | null;
  cumulative_entitled?: string | number | null;
  funds_remaining?: string | number | null;
  flag: DrawFlag;
  formula: string;
  facility_id?: string | null;
}

export interface ClientDrawSchedule {
  id: string;
  property_id: string;
  document_id: string;
  minio_object_key: string;
  original_filename?: string | null;
  purchase_price?: string | number | null;
  client_name?: string | null;
  otp_date?: string | null;
  schedule: Array<Record<string, unknown>>;
  deposits: Array<Record<string, unknown>>;
  extraction_confidence: "high" | "needs_review" | string;
  extraction_status: string;
  extraction_notes?: string | null;
  reviewed_at?: string | null;
  superseded_at?: string | null;
  created_at: string;
  updated_at: string;
}

export interface ClientDrawRequest {
  id: string;
  property_id: string;
  schedule_id: string;
  draw_items: Array<Record<string, unknown>>;
  amount: string | number;
  stage_at_prep?: string | null;
  prepared_at: string;
  status: "prepared" | "sent_to_lawyer" | "funded" | "cancelled" | string;
  notes?: string | null;
}

export interface ClientPrepDrawPackage {
  status: "needs_otp" | "stage_unavailable" | "ready" | string;
  property: Record<string, unknown>;
  current_stage?: string | null;
  current_stage_synced_at?: string | null;
  schedule?: ClientDrawSchedule | null;
  schedule_table: Array<Record<string, unknown>>;
  requestable_items: Array<Record<string, unknown>>;
  already_requested_items: Array<Record<string, unknown>>;
  unmapped_items: Array<Record<string, unknown>>;
  next_upcoming_item?: Record<string, unknown> | null;
  requestable_total?: string | number | null;
  eligibility_unavailable_reason?: string | null;
  lawyer_note?: string | null;
}

export interface FinancingDashboard {
  last_synced_at?: string | null;
  summary: Record<LenderType, LenderSummary>;
  properties: FinancingProperty[];
}

export interface FacilityPayload {
  property_id: string;
  lender_type: LenderType;
  lender_name?: string | null;
  total_facility?: string | number | null;
  opening_balance?: string | number | null;
  rate?: string | number | null;
  already_drawn?: string | number | null;
  draw_eligible_override?: string | number | null;
  requested_draw_amount?: string | number | null;
  requested_draw_as_of?: string | null;
  commitment_source?: string | null;
  commitment_confirmed_at?: string | null;
  last_draw_date?: string | null;
  last_draw_amount?: string | number | null;
  account_number?: string | null;
  account_title?: string | null;
  account_type?: string | null;
  current_balance?: string | number | null;
  outstanding_balance?: string | number | null;
  account_currency?: string | null;
  maturity_date?: string | null;
  member_number?: string | null;
  next_interest_payment_date?: string | null;
  next_payment_date?: string | null;
  account_nickname?: string | null;
  open_date?: string | null;
  original_loan_amount?: string | number | null;
  payment_schedule?: string | null;
  term_length_days?: number | string | null;
  notes?: string | null;
}

export interface FacilityAssignmentPayload {
  facility_type: LenderType;
  lender_id: string;
  total_facility?: string | number | null;
  opening_balance?: string | number | null;
  rate?: string | number | null;
  already_drawn?: string | number | null;
  draw_eligible_override?: string | number | null;
  requested_draw_amount?: string | number | null;
  requested_draw_as_of?: string | null;
  commitment_source?: string | null;
  commitment_confirmed_at?: string | null;
  notes?: string | null;
}

export interface FacilityRecord extends FacilityPayload {
  id: string;
  lender_id?: string | null;
  created_at: string;
  updated_at: string;
}

export interface UploadResponse {
  doc_id: string;
  review_document_id?: string | null;
  lender_type: LenderType;
  minio_key: string;
  extracted: Record<string, unknown>;
  requires_review: boolean;
}

export interface ProFacility {
  id: string;
  facility_key: string;
  property_name: string;
  borrower?: string | null;
  facility_scope: "lot" | "development" | string;
  instrument?: string | null;
  annual_rate?: string | number | null;
  original_advance_date?: string | null;
  original_advance_amount?: string | number | null;
  status: string;
  balance_as_of?: string | number | null;
  last_statement_status?: string | null;
  last_statement_delta?: string | number | null;
}

export interface ProLedgerEvent {
  event_date: string;
  days: number;
  interest: string | number;
  draw: string | number;
  repayment: string | number;
  balance: string | number;
  accrued_interest_running_total: string | number;
  reference?: string | null;
  event_type: string;
}

export interface ProLedger {
  facility_id: string;
  facility_key: string;
  property_name: string;
  as_of: string;
  balance_as_of: string | number;
  events: ProLedgerEvent[];
}

export interface LenderStatement {
  id: string;
  lender: string;
  period: string;
  minio_object_key: string;
  original_filename?: string | null;
  uploaded_at: string;
  parsed_at?: string | null;
  status: string;
}

export interface FacilityStatementSnapshot {
  id: string;
  statement_id: string;
  facility_id?: string | null;
  matched_property_name: string;
  reported_period_end_date: string;
  reported_period_end_balance: string | number;
  computed_balance?: string | number | null;
  delta?: string | number | null;
  reconciliation_status: string;
  canonical_address_key?: string | null;
  parse_payload?: Record<string, unknown> | null;
  new_draws_detected?: Array<Record<string, unknown>> | null;
}

export interface LenderStatementDetail extends LenderStatement {
  parse_payload?: Record<string, unknown> | null;
  snapshots: FacilityStatementSnapshot[];
}
