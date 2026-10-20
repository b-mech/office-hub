const BASE = (process.env.NEXT_PUBLIC_API_URL || "/backend-api").replace(/\/+$/, "");
const ROOT = `${BASE}/api/financing/funds-notices`;

export type FundsEntry = {
  id: string; funds_type: string; status: string; property_address: string | null;
  property_id: string | null; lot_id: string | null; facility_id: string | null;
  deposit_ordinal: number | null; amount: string | null; cheque_number: string | null;
  txn_date: string | null; payee: string | null; memo: string | null;
  closing: Record<string, unknown> | null; match: Record<string, unknown> | null;
  flags: string[]; posting_result: Record<string, unknown> | null;
};
export type FundsNotice = {
  id: string; subject: string | null; email_from?: string | null;
  received_at: string | null; status: string; funds_type: string | null;
  classification_reason?: string | null; law_firm: string | null;
  trust_statement_total: string | null; review_flags?: string[];
  entry_total?: string;
  attachments?: { id: string; filename: string; box_file_url: string | null;
    box_filing_status: string; extraction_status: string; extraction_error: string | null }[];
  entries?: FundsEntry[];
};
export type PropertyOption = { id: string; address: string };
export type ReviewOptions = { properties: PropertyOption[];
  lots: { id: string; property_id: string | null; address: string; is_sale: boolean;
    estimated_possession_date: string | null; possession_confirmed_date: string | null;
    tracker_date_locked: boolean }[];
  facilities: { id: string; lot_id: string | null; property_id: string | null; label: string; lender_type: string }[] };
export type FundsTask = { id: string; task_type: string; title: string; lot_id: string | null;
  notice_id: string | null; payload: Record<string, unknown>; due_at: string | null };

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${ROOT}${path}`, {
    ...init, credentials: "include", headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    const detail = error.detail;
    throw new Error(typeof detail === "string" ? detail : detail?.message || `Request failed (${response.status})`);
  }
  return response.json() as Promise<T>;
}

export const fundsApi = {
  list: () => request<FundsNotice[]>(""),
  options: () => request<ReviewOptions>("/options"),
  tasks: () => request<FundsTask[]>("/tasks"),
  possessionTaken: (lotId: string, date: string) => request<Record<string, unknown>>(
    `/lots/${lotId}/possession`, { method: "POST", body: JSON.stringify({ possession_date: date }) }),
  detail: (id: string) => request<FundsNotice>(`/${id}`),
  updateEntry: (noticeId: string, entryId: string, data: Partial<FundsEntry>) =>
    request<FundsEntry>(`/${noticeId}/entries/${entryId}`, { method: "PATCH", body: JSON.stringify(data) }),
  confirmEntry: (noticeId: string, entryId: string) =>
    request<Record<string, unknown>>(`/${noticeId}/entries/${entryId}/confirm`, { method: "POST" }),
  fileToBox: (id: string) => request<{ filed: number; total: number }>(`/${id}/file-to-box`, { method: "POST" }),
  retryPost: (id: string) => request<Record<string, unknown>>(`/${id}/post`, { method: "POST" }),
  pdfUrl: (noticeId: string, attachmentId: string) => `${ROOT}/${noticeId}/attachments/${attachmentId}/pdf`,
};
