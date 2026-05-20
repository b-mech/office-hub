const BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const OFFICE_HUB_API_KEY =
  process.env.NEXT_PUBLIC_OFFICE_HUB_API_KEY ||
  "b253ca1b038185185289506cd64642a1b8e478d86b09c8c58c8cad7faded8960";

async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      "X-API-Key": OFFICE_HUB_API_KEY,
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

export interface ChangeOrderLineItem {
  description: string;
  amount: number;
  is_credit: boolean;
}

export interface ChangeOrderDraft {
  address: string;
  client_name: string;
  co_number?: string;
  date?: string;
  line_items: ChangeOrderLineItem[];
  payment_method: PaymentMethod;
  notes: string;
}

export interface ChangeOrder extends ChangeOrderDraft {
  id: string;
  status?: "draft" | "approved" | "sent";
  box_file_id?: string | null;
  box_file_url?: string | null;
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

export async function getChangeOrders(): Promise<ChangeOrder[]> {
  return apiFetch<ChangeOrder[]>("/api/v1/change-orders");
}

export async function getChangeOrder(id: string): Promise<ChangeOrder> {
  return apiFetch<ChangeOrder>(`/api/v1/change-orders/${id}`);
}

export async function downloadChangeOrderPdf(id: string): Promise<Blob> {
  const res = await fetch(`${BASE}/api/v1/change-orders/${id}/pdf`, {
    headers: {
      "X-API-Key": OFFICE_HUB_API_KEY,
    },
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `API error ${res.status}`);
  }
  return res.blob();
}

export async function sendChangeOrderForSignature(id: string): Promise<{
  id: string;
  status: string;
  docusign_envelope_id?: string | null;
  message: string;
}> {
  return apiFetch(`/api/v1/change-orders/${id}/send-signature`, {
    method: "POST",
  });
}
