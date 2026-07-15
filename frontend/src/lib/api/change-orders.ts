const BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...options,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...options?.headers,
    },
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `API error ${res.status}`);
  }
  return res.json();
}

export type PaymentMethod = "add_to_mortgage" | "due_upon_receipt";
export type ChangeOrderStatus = "draft" | "sent" | "signed" | "complete";

export interface ChangeOrderLineItem {
  description: string;
  amount: number;
  is_credit: boolean;
}

export interface ChangeOrderDraft {
  address: string;
  client_name: string;
  customer_email?: string;
  co_number?: string;
  date?: string;
  line_items: ChangeOrderLineItem[];
  payment_method: PaymentMethod;
  notes: string;
}

export interface ChangeOrder extends ChangeOrderDraft {
  id: string;
  status: ChangeOrderStatus;
  docusign_envelope_id?: string | null;
  box_file_id?: string | null;
  box_file_url?: string | null;
  box_unfiled?: boolean;
  archived_at?: string | null;
  created_at?: string;
  updated_at?: string;
}

export async function extractChangeOrder(emailBody: string): Promise<ChangeOrderDraft> {
  return apiFetch<ChangeOrderDraft>("/api/v1/change-orders/extract", {
    method: "POST",
    body: JSON.stringify({ email_body: emailBody }),
  });
}

export async function saveDraft(draft: ChangeOrderDraft): Promise<{ id: string }> {
  return apiFetch<{ id: string }>("/api/v1/change-orders/draft", {
    method: "POST",
    body: JSON.stringify(draft),
  });
}

export async function getChangeOrders(includeArchived = false): Promise<ChangeOrder[]> {
  return apiFetch<ChangeOrder[]>(`/api/v1/change-orders${includeArchived ? "?include_archived=true" : ""}`);
}

export async function getChangeOrder(id: string): Promise<ChangeOrder> {
  return apiFetch<ChangeOrder>(`/api/v1/change-orders/${id}`);
}

export async function updateChangeOrderStatus(
  id: string,
  status: ChangeOrder["status"],
): Promise<ChangeOrder> {
  return apiFetch<ChangeOrder>(`/api/v1/change-orders/${id}/status`, {
    method: "PATCH",
    body: JSON.stringify({ status }),
  });
}

export async function updateChangeOrder(id: string, draft: Partial<ChangeOrderDraft>): Promise<ChangeOrder> {
  return apiFetch<ChangeOrder>(`/api/v1/change-orders/${id}`, {
    method: "PATCH",
    body: JSON.stringify(draft),
  });
}

export async function downloadChangeOrderPdf(id: string): Promise<Blob> {
  const res = await fetch(`${BASE}/api/v1/change-orders/${id}/pdf`, {
    credentials: "include",
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `API error ${res.status}`);
  }
  return res.blob();
}

export async function archiveChangeOrder(id: string): Promise<ChangeOrder> {
  return apiFetch<ChangeOrder>(`/api/v1/change-orders/${id}`, {
    method: "DELETE",
  });
}

export async function sendChangeOrderForSignature(
  id: string,
  signer?: { signer_email?: string; signer_name?: string },
): Promise<{
  id: string;
  status: string;
  docusign_envelope_id?: string | null;
  box_file_id?: string | null;
  box_file_url?: string | null;
  box_unfiled?: boolean;
  message: string;
}> {
  return apiFetch(`/api/v1/change-orders/${id}/send-signature`, {
    method: "POST",
    body: JSON.stringify(signer || {}),
  });
}

export async function syncSignedChangeOrder(id: string): Promise<{
  id: string;
  status: string;
  docusign_envelope_id?: string | null;
  box_file_id?: string | null;
  box_file_url?: string | null;
  box_unfiled?: boolean;
  message: string;
}> {
  return apiFetch(`/api/v1/change-orders/${id}/sync-signed`, {
    method: "POST",
  });
}
