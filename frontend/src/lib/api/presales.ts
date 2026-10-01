const BASE = (process.env.NEXT_PUBLIC_API_URL || "/backend-api").replace(/\/+$/, "");

export const CONDITION_CATEGORIES = [
  "sale_of_existing_home",
  "subject_to_appraisal",
  "income_verification",
  "down_payment_verification",
  "credit_review",
  "insurer_approval",
  "builder_docs",
  "rate_hold_expiry",
  "other",
] as const;

export type ConditionCategory = (typeof CONDITION_CATEGORIES)[number];

export interface ApprovalCondition {
  text: string;
  category: ConditionCategory;
  deadline: string | null;
}

export interface ApprovalLetter {
  id: string;
  lot_id: string | null;
  status: string;
  version: number;
  requested_at: string | null;
  requested_from: string | null;
  original_filename: string | null;
  email_from: string | null;
  email_subject: string | null;
  email_received_at: string | null;
  extracted: Record<string, unknown> & { conditions?: ApprovalCondition[] };
  extraction_confidence: Record<string, number>;
  low_confidence_fields: string[];
  needs_manual_entry: boolean;
  quality_score: number | null;
  lender_contacted_at: string | null;
  lender_contact_notes: string | null;
  rejection_reason: string | null;
  reviewed_by: string | null;
  reviewed_at: string | null;
  created_at: string;
  updated_at: string;
  preview_url: string | null;
}

export interface PackageItem {
  requested_at: string | null;
  ordered_at: string | null;
  received_at: string | null;
  present: boolean;
  filename: string | null;
  metadata: Record<string, unknown>;
}

export interface PartnerReadiness {
  display_name: string;
  state: "disqualified" | "blocked_by_quality" | "not_ready" | "ready";
  ready: boolean;
  disqualified_by: ApprovalCondition[];
  missing: string[];
  min_quality_score: number | null;
  package_recipient: string | null;
  package_docs: string[];
  capacity_ok?: boolean;
  advance?: number;
  sale_price?: number;
  approved_mortgage?: number;
  equity_gap?: number;
}

export interface ReadinessResult {
  computed_at: string;
  status: string;
  suggested: string | null;
  partners: Record<string, PartnerReadiness>;
}

export interface PresaleTask {
  id: string;
  lot_id: string | null;
  approval_letter_id: string | null;
  task_type: string;
  title: string;
  status: string;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface PresaleDetail {
  lot: {
    id: string;
    property_id: string | null;
    address: string;
    sale_type: string | null;
    building_type: string | null;
    realtor_name: string | null;
    realtor_email: string | null;
    realtor_brokerage: string | null;
    funding_partner_suggested: string | null;
    package_sent_to: string | null;
    package_sent_at: string | null;
  };
  buyer_names: string[];
  active_letter: ApprovalLetter | null;
  letter_history: ApprovalLetter[];
  package_items: Record<string, PackageItem>;
  readiness: ReadinessResult;
  quality_flags: Array<{ code: string; label: string }>;
  tasks: PresaleTask[];
}

export interface FundingPartnerRule {
  partner_code: string;
  display_name: string;
  priority: number;
  required_docs: string[];
  required_fields: string[];
  disqualifying_conditions: string[];
  min_quality_score: number | null;
  formula: Record<string, unknown> | null;
  max_advance_rule: Record<string, unknown> | null;
  package_recipient: string | null;
  package_docs: string[];
  active: boolean;
  updated_at?: string;
}

export interface LotOption {
  id: string;
  address: string;
  purchaser_names: string[];
  created_at: string;
  is_presale: boolean;
}

export interface PresaleNotification {
  id: string;
  lot_id: string | null;
  type: string;
  message: string;
  payload: Record<string, unknown>;
  read_at: string | null;
  created_at: string;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}/api/presales${path}`, {
    ...init,
    headers: init?.body instanceof FormData
      ? init.headers
      : { "Content-Type": "application/json", ...(init?.headers || {}) },
    cache: "no-store",
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({})) as { detail?: string | { message?: string } };
    const detail = typeof error.detail === "string" ? error.detail : error.detail?.message;
    throw new Error(detail || `Request failed (${response.status})`);
  }
  if (response.status === 204) return undefined as T;
  return await response.json() as T;
}

export const presalesApi = {
  board: () => request<PresaleDetail[]>("/board"),
  queue: () => request<{ letters: ApprovalLetter[]; tasks: PresaleTask[] }>("/queue"),
  unmatched: () => request<ApprovalLetter[]>("/unmatched"),
  lot: (id: string) => request<PresaleDetail>(`/lots/${id}`),
  lots: () => request<LotOption[]>("/lot-options"),
  updateLot: (id: string, data: Record<string, unknown>) => request<PresaleDetail>(`/lots/${id}`, { method: "PATCH", body: JSON.stringify(data) }),
  markLetterRequested: (id: string) => request<ApprovalLetter>(`/lots/${id}/approval-letter/requested`, { method: "POST", body: "{}" }),
  updateLetter: (id: string, data: Record<string, unknown>) => request<ApprovalLetter>(`/approval-letters/${id}`, { method: "PATCH", body: JSON.stringify(data) }),
  approveLetter: (id: string) => request<PresaleDetail>(`/approval-letters/${id}/approve`, { method: "POST" }),
  rejectLetter: (id: string, reason: string) => request<ApprovalLetter>(`/approval-letters/${id}/reject`, { method: "POST", body: JSON.stringify({ reason }) }),
  contactLender: (id: string, notes: string) => request<ApprovalLetter>(`/approval-letters/${id}/contacted`, { method: "POST", body: JSON.stringify({ notes }) }),
  markItem: (lotId: string, item: string, action: "requested" | "ordered") => request<PresaleDetail>(`/lots/${lotId}/package-items/${item}/action`, { method: "POST", body: JSON.stringify({ action }) }),
  uploadItem: (lotId: string, item: string, file: File, metadata: Record<string, unknown> = {}) => {
    const body = new FormData();
    body.append("file", file);
    body.append("metadata_json", JSON.stringify(metadata));
    return request<PresaleDetail>(`/lots/${lotId}/package-items/${item}/upload`, { method: "POST", body });
  },
  completeTask: (id: string, notes?: string) => request<PresaleTask>(`/tasks/${id}/complete`, { method: "POST", body: JSON.stringify({ notes }) }),
  draftPackage: (lotId: string, partner: string) => request<{ mode: string; gmail_url?: string; download_url?: string; reason?: string }>(`/lots/${lotId}/packages/${partner}/draft`, { method: "POST" }),
  markPackageSent: (lotId: string, partner: string) => request<PresaleDetail>(`/lots/${lotId}/packages/sent`, { method: "POST", body: JSON.stringify({ partner_code: partner }) }),
  rules: () => request<FundingPartnerRule[]>("/partner-rules"),
  createRule: (data: FundingPartnerRule) => request<FundingPartnerRule>("/partner-rules", { method: "POST", body: JSON.stringify(data) }),
  updateRule: (code: string, data: Partial<FundingPartnerRule>) => request<FundingPartnerRule>(`/partner-rules/${code}`, { method: "PATCH", body: JSON.stringify(data) }),
  deleteRule: (code: string) => request<void>(`/partner-rules/${code}`, { method: "DELETE" }),
  notifications: (unreadOnly = false) => request<PresaleNotification[]>(`/notifications${unreadOnly ? "?unread_only=true" : ""}`),
  markNotificationRead: (id: string) => request<void>(`/notifications/${id}/read`, { method: "POST" }),
};

export function presaleFileUrl(letter: ApprovalLetter): string {
  return letter.preview_url ? `${BASE}${letter.preview_url}` : "";
}

export function presaleDownloadUrl(path: string): string {
  return `${BASE}${path}`;
}
