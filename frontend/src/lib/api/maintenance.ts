const BASE = process.env.NEXT_PUBLIC_API_URL || "/backend-api";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, { ...options, cache: "no-store" });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `API error ${response.status}`);
  }
  return response.json() as Promise<T>;
}

async function jsonRequest<T>(path: string, method: string, body?: object): Promise<T> {
  return request<T>(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

export type TicketStatus = "new" | "triaged" | "assigned" | "scheduled" | "in_progress" | "awaiting_parts" | "awaiting_tenant" | "resolved" | "closed" | "cancelled" | "duplicate";
export type TicketPriority = "emergency" | "urgent" | "routine" | "low";
export type TicketCategory = "plumbing" | "electrical" | "heating" | "cooling" | "appliance" | "doors_locks_windows" | "pests" | "exterior_grounds" | "structural" | "water_leak" | "no_heat" | "gas_smell" | "no_power" | "security" | "other";

export type TicketListItem = {
  id: string;
  number: string;
  title: string;
  property: string;
  unit: string;
  category: TicketCategory | null;
  priority: TicketPriority | null;
  status: TicketStatus;
  is_emergency: boolean;
  needs_reply: boolean;
  sla_status: "untriaged" | "on_track" | "warning" | "overdue" | "complete";
  sla_due_at: string | null;
  updated_at: string;
};

export type TimelineAttachment = { id: string; filename: string | null; content_type: string; url: string };
export type TimelineItem = {
  id: string;
  event_type: string;
  channel: string;
  visibility: "internal" | "external";
  direction: "inbound" | "outbound" | "none";
  party: string;
  actor_name: string | null;
  body: string | null;
  payload: Record<string, unknown>;
  created_at: string;
  attachments: TimelineAttachment[];
  sms: null | { id: string; status: "held" | "sent" | "failed" | "cancelled" | "received"; hold_until: string | null; cancellable: boolean; error_code: string | null };
};

export type WorkOrder = {
  id: string;
  number: string;
  assignee_type: "staff" | "vendor";
  assignee_name: string;
  status: string;
  scope: string;
  scheduled_start: string | null;
  scheduled_end: string | null;
  cost_estimate: string | null;
  cost_actual: string | null;
  completion_notes: string | null;
  external_party: boolean;
};

export type TicketDetail = TicketListItem & {
  description: string;
  emergency_acked_at: string | null;
  entry_permission: "granted" | "denied" | "not_asked";
  entry_notes: string | null;
  chargeback_flag: boolean;
  messaging_allowed: boolean;
  work_orders: WorkOrder[];
  timeline: TimelineItem[];
  staff_options: { id: string; name: string }[];
  vendor_options: { id: string; name: string }[];
};

export type TicketFilters = {
  include_terminal?: boolean;
  status?: TicketStatus | "";
  priority?: TicketPriority | "";
  needs_reply?: boolean;
};

export function listTickets(filters: TicketFilters = {}) {
  const query = new URLSearchParams();
  if (filters.include_terminal) query.set("include_terminal", "true");
  if (filters.status) query.set("status", filters.status);
  if (filters.priority) query.set("priority", filters.priority);
  if (filters.needs_reply) query.set("needs_reply", "true");
  const suffix = query.size ? `?${query.toString()}` : "";
  return request<TicketListItem[]>(`/api/maintenance/tickets${suffix}`);
}

export const getTicket = (ticketId: string) => request<TicketDetail>(`/api/maintenance/tickets/${ticketId}`);

export async function sendTicketMessage(ticketId: string, values: { target: "tenant" | "vendor" | "internal"; body: string; workOrderId?: string; attachments: File[] }) {
  const form = new FormData();
  form.set("target", values.target);
  form.set("body", values.body);
  if (values.workOrderId) form.set("work_order_id", values.workOrderId);
  for (const attachment of values.attachments) form.append("attachments", attachment);
  return request<{ ok: true; message_id: string | null }>(`/api/maintenance/tickets/${ticketId}/messages`, { method: "POST", body: form });
}

export const cancelTicketMessage = (ticketId: string, messageId: string) => jsonRequest<{ ok: true }>(`/api/maintenance/tickets/${ticketId}/messages/${messageId}/cancel`, "POST");
export const triageTicket = (ticketId: string, body: object) => jsonRequest<{ ok: true }>(`/api/maintenance/tickets/${ticketId}/triage`, "POST", body);
export const assignTicket = (ticketId: string, body: object) => jsonRequest<{ ok: true; work_order_id: string }>(`/api/maintenance/tickets/${ticketId}/assign`, "POST", body);
export const scheduleTicket = (ticketId: string, body: object) => jsonRequest<{ ok: true }>(`/api/maintenance/tickets/${ticketId}/schedule`, "POST", body);
export const completeWorkOrder = (ticketId: string, workOrderId: string, body: object) => jsonRequest<{ ok: true; all_work_orders_complete: boolean }>(`/api/maintenance/tickets/${ticketId}/work-orders/${workOrderId}/complete`, "POST", body);
export const resolveTicket = (ticketId: string, note: string) => jsonRequest<{ ok: true }>(`/api/maintenance/tickets/${ticketId}/resolve`, "POST", { note });
export const ticketMoreAction = (ticketId: string, body: object) => jsonRequest<{ ok: true }>(`/api/maintenance/tickets/${ticketId}/more`, "POST", body);
export const acknowledgeEmergency = (ticketId: string) => jsonRequest<{ ok: true; acknowledged: boolean }>(`/api/maintenance/tickets/${ticketId}/acknowledge`, "POST");
export const attachmentUrl = (path: string) => `${BASE}${path}`;

export type QrStatus = {
  unit_id: number;
  property_id: number;
  active: boolean;
  created_at: string | null;
  rotation_recommended: boolean;
};

export const qrStatus = (unitId: number) => request<QrStatus>(`/api/maintenance/units/${unitId}/qr`);
export const rotateQr = (unitId: number) => request<{token:string;url:string}>(`/api/maintenance/units/${unitId}/qr`, { method: "POST" });

export async function printQr(unitId: number, token: string): Promise<Blob> {
  const response = await fetch(`${BASE}/api/maintenance/units/${unitId}/qr/print`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token }),
  });
  if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail || "Could not build PDF");
  return response.blob();
}

export async function printProperty(propertyId: number): Promise<Blob> {
  const response = await fetch(`${BASE}/api/maintenance/properties/${propertyId}/qr/print`, { method: "POST" });
  if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail || "Could not build PDF");
  return response.blob();
}

export function download(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}
