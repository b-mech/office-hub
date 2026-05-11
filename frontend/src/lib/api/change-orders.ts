const BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
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

export async function getChangeOrder(id: string): Promise<ChangeOrder> {
  return apiFetch<ChangeOrder>(`/api/v1/change-orders/${id}`);
}
