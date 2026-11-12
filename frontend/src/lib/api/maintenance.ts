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
  property_id: number;
  unit: string;
  unit_id: number | null;
  category: TicketCategory | null;
  priority: TicketPriority | null;
  status: TicketStatus;
  is_emergency: boolean;
  needs_reply: boolean;
  sla_status: "untriaged" | "on_track" | "warning" | "overdue" | "complete";
  sla_due_at: string | null;
  updated_at: string;
  checklist: { total: number; done: number };
};

export type ChecklistItem = { id: string; text: string; done: boolean; position: number; done_at: string | null };
export type PurchaseStatus = "needed" | "ordered" | "received" | "cancelled";
export type Purchase = {
  id: string; vendor: string; item: string; amount: string | null; status: PurchaseStatus;
  reference: string | null; work_order_id: string | null; logged_at: string; updated_at: string;
};
export type RelatedTicket = {
  id: string; number: string; title: string; status: TicketStatus; category: TicketCategory | null;
  created_at: string; unit: string; same_unit: boolean;
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
  sms: null | {
    id: string;
    status: "held" | "sent" | "failed" | "cancelled" | "received";
    hold_until: string | null;
    cancellable: boolean;
    retryable: boolean;
    error_code: string | null;
    failure_reason: string | null;
  };
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
  scheduled_visit_status: "scheduled" | "completed" | "cancelled" | null;
  cost_estimate: string | null;
  cost_actual: string | null;
  cost_class: "repair" | "capital" | null;
  invoice_url: string | null;
  completion_notes: string | null;
  external_party: boolean;
};

export type ScheduledVisit = {
  work_order_id: string;
  work_order_number: string;
  scheduled_start: string;
  scheduled_end: string | null;
};

export type ScheduleTicketRequest = {
  work_order_id: string;
  start: string;
  end: string;
  access_basis: "routine" | "tenant_consent" | "emergency";
  consent_evidence: string | null;
  reason: string | null;
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
  duplicate_of: string | null;
  checklist_items: ChecklistItem[];
  purchases: Purchase[];
  related_tickets: RelatedTicket[];
};

export type TicketFilters = {
  include_terminal?: boolean;
  status?: TicketStatus | "";
  priority?: TicketPriority | "";
  needs_reply?: boolean;
  property_id?: number;
  assignee_id?: string;
};

export type CalendarVisitType = "routine" | "tenant_consent" | "emergency";
export type CalendarVisit = {
  id: string; ticket_id: string; work_order_id: string; ticket_number: string; work_order_number: string;
  address: string; property: string; property_id: number; unit: string; title: string;
  assignee_id: string | null; assignee_name: string; assignee_type: "staff" | "vendor";
  start: string; end: string; visit_type: CalendarVisitType; visit_status: "scheduled" | "completed";
  ticket_status: TicketStatus; priority: TicketPriority | null;
  notice_status: "queued" | "sent" | "delivered" | "failed" | null; notice_error: string | null;
  draggable: boolean; href: string;
};
export type CalendarUnscheduled = {
  id: string; ticket_id: string; work_order_id: string | null; ticket_number: string; work_order_number?: string;
  address: string; property: string; property_id: number; unit: string; title: string;
  assignee_id: string | null; assignee_name: string; assignee_type: "staff" | "vendor" | null;
  priority: TicketPriority | null; ticket_status: TicketStatus; created_at: string;
  visit_type: CalendarVisitType; is_emergency: boolean; draggable: boolean;
};
export type MaintenanceCalendarResponse = {
  timezone: string;
  visits: CalendarVisit[];
  unscheduled: CalendarUnscheduled[];
  properties: { id: number; name: string }[];
  assignees: { id: string; name: string; type: "staff" | "vendor" }[];
};
export type MaintenanceCalendarFilters = {
  start: string; end: string; property_id?: number; assignee_id?: string;
  visit_type?: CalendarVisitType; status?: TicketStatus;
};

export function getMaintenanceCalendar(filters: MaintenanceCalendarFilters) {
  const query = new URLSearchParams({ start: filters.start, end: filters.end });
  if (filters.property_id) query.set("property_id", String(filters.property_id));
  if (filters.assignee_id) query.set("assignee_id", filters.assignee_id);
  if (filters.visit_type) query.set("visit_type", filters.visit_type);
  if (filters.status) query.set("status", filters.status);
  return request<MaintenanceCalendarResponse>(`/api/maintenance/calendar?${query.toString()}`);
}

export function listTickets(filters: TicketFilters = {}) {
  const query = new URLSearchParams();
  if (filters.include_terminal) query.set("include_terminal", "true");
  if (filters.status) query.set("status", filters.status);
  if (filters.priority) query.set("priority", filters.priority);
  if (filters.needs_reply) query.set("needs_reply", "true");
  if (filters.property_id) query.set("property_id", String(filters.property_id));
  if (filters.assignee_id) query.set("assignee_id", filters.assignee_id);
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
export const retryTicketMessage = (ticketId: string, messageId: string) => jsonRequest<{ ok: true }>(`/api/maintenance/tickets/${ticketId}/messages/${messageId}/retry`, "POST");
export const triageTicket = (ticketId: string, body: object) => jsonRequest<{ ok: true }>(`/api/maintenance/tickets/${ticketId}/triage`, "POST", body);
export const assignTicket = (ticketId: string, body: object) => jsonRequest<{ ok: true; work_order_id: string }>(`/api/maintenance/tickets/${ticketId}/assign`, "POST", body);
export const scheduleTicket = (ticketId: string, body: object) => jsonRequest<{ ok: true }>(`/api/maintenance/tickets/${ticketId}/schedule`, "POST", body);
export const previewScheduledVisit = (ticketId: string, body: ScheduleTicketRequest) => jsonRequest<{ message: string }>(`/api/maintenance/tickets/${ticketId}/schedule-preview`, "POST", body);
export const completeWorkOrder = (ticketId: string, workOrderId: string, body: object) => jsonRequest<{ ok: true; all_work_orders_complete: boolean; future_scheduled_visits: ScheduledVisit[] }>(`/api/maintenance/tickets/${ticketId}/work-orders/${workOrderId}/complete`, "POST", body);
export const updateScheduledVisit = (ticketId: string, workOrderId: string, status: "completed" | "cancelled") => jsonRequest<{ ok: true }>(`/api/maintenance/tickets/${ticketId}/work-orders/${workOrderId}/scheduled-visit`, "POST", { status });
export const resolveTicket = (ticketId: string, note: string, cancelScheduledVisitIds: string[] = []) => jsonRequest<{ ok: true }>(`/api/maintenance/tickets/${ticketId}/resolve`, "POST", { note, cancel_scheduled_visit_ids: cancelScheduledVisitIds });
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


export type StaffTicketOptions = {
  properties: { id: number; name: string; address: string }[];
  units: { id: number; property_id: number; label: string }[];
};
export type StaffTicketInput = {
  property_id: number; unit_id: number | null; title: string; description: string;
  category: TicketCategory; priority: TicketPriority; is_emergency: boolean;
  reporter_name: string | null; reporter_phone: string | null; sms_opt_in: boolean;
  entry_permission: "granted" | "denied" | "not_asked"; entry_notes: string | null;
};
export const getStaffTicketOptions = () => request<StaffTicketOptions>("/api/maintenance/create-options");
export async function createStaffTicket(data: StaffTicketInput, photos: File[]) {
  const body = new FormData(); body.set("data", JSON.stringify(data));
  photos.forEach((photo) => body.append("photos", photo));
  return request<{ id: string; number: string; status: string; sla_due_at: string; confirmation: string }>(
    "/api/maintenance/tickets", { method: "POST", body });
}


export type VendorPortalOrder = {
  number: string; status: string; vendor_name: string; scope: string; address: string; unit: string|null;
  entry_notes: string|null; entry_permission: string; scheduled_start: string|null; scheduled_end: string|null;
  cost_estimate: string|null; completion_notes: string|null; is_emergency: boolean; emergency_acknowledged: boolean;
  photos: {id:string;label:string}[];
};
export type VendorPortalAction = "accept"|"decline"|"propose_schedule"|"confirm_schedule"|"start"|"complete";
const vendorPath = (token:string) => `/api/public/work-orders/${encodeURIComponent(token)}`;
export const getVendorPortal = (token:string) => request<VendorPortalOrder>(vendorPath(token));
export const actOnVendorOrder = (token:string,body:{action:VendorPortalAction;notes?:string;start?:string;end?:string}) => jsonRequest<{status:string;link_revoked:boolean}>(`${vendorPath(token)}/actions`,"POST",body);
export const vendorPhotoUrl = (token:string,id:string) => `${BASE}${vendorPath(token)}/photos/${encodeURIComponent(id)}`;
export function uploadVendorPhotos(token:string,photos:File[]){ const body=new FormData();photos.forEach(p=>body.append("photos",p));return request<{uploaded:number}>(`${vendorPath(token)}/photos`,{method:"POST",body});}


export type MaintenanceVendor={id:string;name:string;phone_e164:string;trades:TicketCategory[];insurance_expiry:string|null;wcb_expiry:string|null;notes:string|null;is_active:boolean;sms_opted_out:boolean};
export type MaintenanceVendorInput=Omit<MaintenanceVendor,"id"|"sms_opted_out">;
export const listMaintenanceVendors=(includeInactive=false)=>request<MaintenanceVendor[]>(`/api/maintenance/vendors?include_inactive=${includeInactive}`);
export const createMaintenanceVendor=(body:MaintenanceVendorInput)=>jsonRequest<MaintenanceVendor>("/api/maintenance/vendors","POST",body);
export const updateMaintenanceVendor=(id:string,body:Partial<MaintenanceVendorInput>)=>jsonRequest<MaintenanceVendor>(`/api/maintenance/vendors/${id}`,"PATCH",body);


export type MaintenanceFilterOptions = {
  properties: { id: number; name: string; address: string }[];
  assignees: { id: string; name: string; type: "staff" | "vendor" }[];
};
export const getMaintenanceFilterOptions = () => request<MaintenanceFilterOptions>("/api/maintenance/filter-options");

export type CompleteWorkOrderInput = { completion_notes: string; cost_actual: string | null; cost_class: "repair" | "capital" | null };
export async function uploadWorkOrderInvoice(ticketId: string, workOrderId: string, invoice: File) {
  const body = new FormData(); body.set("invoice", invoice);
  return request<{ ok: true; attachment_id: string; url: string }>(`/api/maintenance/tickets/${ticketId}/work-orders/${workOrderId}/invoice`, { method: "POST", body });
}
export const recordWorkOrderCosts = (ticketId: string, workOrderId: string, body: { cost_actual: string | null; cost_class: "repair" | "capital" | null }) =>
  jsonRequest<{ ok: true }>(`/api/maintenance/tickets/${ticketId}/work-orders/${workOrderId}/costs`, "POST", body);

type ChecklistResponse = { items: ChecklistItem[]; progress: { total: number; done: number } };
export const addChecklistItems = (ticketId: string, body: { items?: string[]; text?: string }) =>
  jsonRequest<ChecklistResponse>(`/api/maintenance/tickets/${ticketId}/checklist`, "POST", body);
export const updateChecklistItem = (ticketId: string, itemId: string, body: { done?: boolean; remove?: boolean }) =>
  jsonRequest<ChecklistResponse>(`/api/maintenance/tickets/${ticketId}/checklist/${itemId}`, "POST", body);

export type PurchaseInput = { vendor: string; item: string; amount: string | null; status: PurchaseStatus; reference: string | null; work_order_id: string | null };
export const logPurchase = (ticketId: string, body: PurchaseInput) =>
  jsonRequest<{ purchases: Purchase[] }>(`/api/maintenance/tickets/${ticketId}/purchases`, "POST", body);
export const setPurchaseStatus = (ticketId: string, purchaseId: string, status: PurchaseStatus) =>
  jsonRequest<{ purchases: Purchase[] }>(`/api/maintenance/tickets/${ticketId}/purchases/${purchaseId}`, "POST", { status });

export type SpendRow = {
  month: string; property_id: number; property: string; unit_id: number | null; unit: string | null; work_orders: number;
  cost_estimate: string; cost_actual: string; repair_actual: string; capital_actual: string; unclassified_actual: string;
};
export type SpendReport = { rows: SpendRow[]; totals: { work_orders: number; cost_estimate: string; cost_actual: string; repair_actual: string; capital_actual: string }; basis: string };
export type SpendQuery = { start?: string; end?: string; group_by?: "property" | "unit"; property_id?: number };
function spendQuery(filters: SpendQuery, format: "json" | "csv") {
  const query = new URLSearchParams({ format });
  if (filters.start) query.set("start", filters.start);
  if (filters.end) query.set("end", filters.end);
  if (filters.group_by) query.set("group_by", filters.group_by);
  if (filters.property_id) query.set("property_id", String(filters.property_id));
  return `/api/maintenance/reports/spend?${query.toString()}`;
}
export const getSpendReport = (filters: SpendQuery) => request<SpendReport>(spendQuery(filters, "json"));
export async function downloadSpendCsv(filters: SpendQuery) {
  const response = await fetch(`${BASE}${spendQuery(filters, "csv")}`, { cache: "no-store" });
  if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail || "Could not export CSV");
  download(await response.blob(), `maintenance-spend-${filters.start || "all"}-${filters.end || "all"}.csv`);
}
