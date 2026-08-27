import type {
  ClientDrawRequest,
  ClientDrawSchedule,
  ClientPrepDrawPackage,
  ConstructionMilestone,
  FacilityPayload,
  FacilityAssignmentPayload,
  FacilityRecord,
  FacilityStatementSnapshot,
  FinancingDashboard,
  FinancingProperty,
  LenderStatement,
  LenderStatementDetail,
  ProFacility,
  ProDrawRequest,
  ProLedger,
  UploadResponse,
} from "@/types/financing";

const BASE = process.env.NEXT_PUBLIC_API_URL || "/backend-api";

async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...options,
    headers: {
      ...(options?.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
      ...(options?.headers || {}),
    },
    cache: "no-store",
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(formatApiError(err.detail, res.status));
  }
  return res.json();
}

function formatApiError(detail: unknown, status: number): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        if (!item || typeof item !== "object") return String(item);
        const error = item as { loc?: unknown[]; msg?: string };
        const field = Array.isArray(error.loc) ? error.loc.slice(1).join(".") : "";
        return field && error.msg ? `${field}: ${error.msg}` : error.msg || JSON.stringify(item);
      })
      .join("; ");
  }
  if (detail && typeof detail === "object") return JSON.stringify(detail);
  return `API error ${status}`;
}

export function getFinancingDashboard(): Promise<FinancingDashboard> {
  return apiFetch<FinancingDashboard>("/api/v1/financing/dashboard");
}

export function refreshFinancingFromSheet(): Promise<{ synced: number; created_properties: number; errors: string[] }> {
  return apiFetch("/api/v1/financing/sync-from-sheet", { method: "POST" });
}

export function getFinancingProperty(id: string): Promise<FinancingProperty> {
  return apiFetch<FinancingProperty>(`/api/v1/financing/properties/${id}`);
}

export function getProDrawRequests(propertyId?: string): Promise<ProDrawRequest[]> {
  const query = propertyId ? `?property_id=${propertyId}` : "";
  return apiFetch<ProDrawRequest[]>(`/api/v1/financing/pro-draw-requests${query}`);
}

export function createProDrawRequest(
  propertyId: string,
  amount?: string | number | null,
): Promise<ProDrawRequest> {
  return apiFetch<ProDrawRequest>(`/api/v1/financing/properties/${propertyId}/pro-draw-requests`, {
    method: "POST",
    body: JSON.stringify({ amount: amount ?? null }),
  });
}

export function createProDrawRequestBatch(propertyIds: string[]): Promise<ProDrawRequest[]> {
  return apiFetch<ProDrawRequest[]>("/api/v1/financing/pro-draw-requests/batch", {
    method: "POST",
    body: JSON.stringify({ property_ids: propertyIds }),
  });
}

export function updateProDrawRequest(
  requestId: string,
  status: string,
): Promise<ProDrawRequest> {
  return apiFetch<ProDrawRequest>(`/api/v1/financing/pro-draw-requests/${requestId}`, {
    method: "PATCH",
    body: JSON.stringify({ status }),
  });
}

export function updateProDrawRequestBatch(
  batchId: string,
  status: string,
): Promise<ProDrawRequest[]> {
  return apiFetch<ProDrawRequest[]>(`/api/v1/financing/pro-draw-request-batches/${batchId}`, {
    method: "PATCH",
    body: JSON.stringify({ status }),
  });
}

export function updateConstructionMilestone(
  id: string,
  payload: { achieved_on: string; note?: string | null },
): Promise<ConstructionMilestone> {
  return apiFetch<ConstructionMilestone>(`/api/v1/financing/milestones/${id}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function getClientOtpSchedule(propertyId: string): Promise<ClientDrawSchedule | null> {
  return apiFetch<ClientDrawSchedule | null>(`/api/v1/financing/properties/${propertyId}/otp`);
}

export function uploadClientOtp(propertyId: string, file: File): Promise<ClientDrawSchedule> {
  const data = new FormData();
  data.set("file", file);
  return apiFetch<ClientDrawSchedule>(`/api/v1/financing/properties/${propertyId}/otp`, { method: "POST", body: data });
}

export function reviewClientOtp(scheduleId: string, values: {
  purchase_price?: string | number | null;
  client_name?: string | null;
  otp_date?: string | null;
  schedule: Array<Record<string, unknown>>;
  deposits?: Array<Record<string, unknown>>;
  extraction_notes?: string | null;
}): Promise<ClientDrawSchedule> {
  return apiFetch<ClientDrawSchedule>(`/api/v1/financing/otp/${scheduleId}/review`, { method: "PATCH", body: JSON.stringify(values) });
}

export function prepareOfficialOtpReview(
  scheduleId: string,
): Promise<{ document_id: string }> {
  return apiFetch<{ document_id: string }>(
    `/api/v1/financing/otp/${scheduleId}/prepare-official-review`,
    { method: "POST" },
  );
}

export function prepClientDraw(propertyId: string): Promise<ClientPrepDrawPackage> {
  return apiFetch<ClientPrepDrawPackage>(`/api/v1/financing/properties/${propertyId}/prep-draw`, { method: "POST" });
}

export function confirmClientPrepDraw(propertyId: string, payload: {
  draw_items: Array<Record<string, unknown>>;
  amount: string | number;
  notes?: string | null;
}): Promise<ClientDrawRequest> {
  return apiFetch<ClientDrawRequest>(`/api/v1/financing/properties/${propertyId}/prep-draw/confirm`, { method: "POST", body: JSON.stringify(payload) });
}

export function getClientDrawRequests(propertyId: string): Promise<ClientDrawRequest[]> {
  return apiFetch<ClientDrawRequest[]>(`/api/v1/financing/properties/${propertyId}/draw-requests`);
}

export function updateClientDrawRequestStatus(requestId: string, status: string, notes?: string): Promise<ClientDrawRequest> {
  return apiFetch<ClientDrawRequest>(`/api/v1/financing/prep-draw/requests/${requestId}/status`, {
    method: "PATCH",
    body: JSON.stringify({ status, notes }),
  });
}

export function createFacility(payload: FacilityPayload): Promise<unknown> {
  return apiFetch("/api/v1/financing/facilities", { method: "POST", body: JSON.stringify(payload) });
}

export function assignPropertyFacility(
  propertyId: string,
  payload: FacilityAssignmentPayload,
): Promise<FacilityRecord> {
  return apiFetch<FacilityRecord>(`/api/v1/financing/properties/${propertyId}/facilities`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateFacility(id: string, payload: Partial<FacilityPayload>): Promise<unknown> {
  return apiFetch(`/api/v1/financing/facilities/${id}`, { method: "PATCH", body: JSON.stringify(payload) });
}

export function uploadFacilityDocument(params: {
  lenderType: string;
  propertyId?: string;
  file: File;
}): Promise<UploadResponse> {
  const data = new FormData();
  data.set("lender_type", params.lenderType);
  if (params.propertyId) data.set("property_id", params.propertyId);
  data.set("file", params.file);
  return apiFetch<UploadResponse>("/api/v1/financing/documents/upload", { method: "POST", body: data });
}

export function uploadLenderStatement(params: {
  lender: string;
  period: string;
  file: File;
}): Promise<LenderStatement> {
  const data = new FormData();
  data.set("lender", params.lender);
  data.set("period", params.period);
  data.set("file", params.file);
  return apiFetch<LenderStatement>("/api/v1/financing/statements", { method: "POST", body: data });
}

export function getLenderStatements(lender?: string): Promise<LenderStatement[]> {
  return apiFetch<LenderStatement[]>(`/api/v1/financing/statements${lender ? `?lender=${encodeURIComponent(lender)}` : ""}`);
}

export function getLenderStatement(id: string): Promise<LenderStatementDetail> {
  return apiFetch<LenderStatementDetail>(`/api/v1/financing/statements/${id}`);
}

export function retryLenderStatement(id: string): Promise<LenderStatementDetail> {
  return apiFetch<LenderStatementDetail>(
    `/api/v1/financing/statements/${id}/retry`,
    { method: "POST" },
  );
}

export function createManualStatementSnapshot(
  statementId: string,
  payload: {
    facility_id: string;
    reported_period_end_date: string;
    reported_period_end_balance: string;
    draws: Array<{
      txn_date: string;
      amount: string;
      reference?: string | null;
    }>;
    note?: string | null;
  },
): Promise<LenderStatementDetail> {
  return apiFetch<LenderStatementDetail>(
    `/api/v1/financing/statements/${statementId}/manual-snapshots`,
    { method: "POST", body: JSON.stringify(payload) },
  );
}

export function approveStatementDraws(snapshotId: string): Promise<FacilityStatementSnapshot> {
  return apiFetch<FacilityStatementSnapshot>(`/api/v1/financing/statements/snapshots/${snapshotId}/approve-draws`, { method: "POST" });
}

export function linkStatementFacility(snapshotId: string, facilityId: string): Promise<FacilityStatementSnapshot> {
  return apiFetch<FacilityStatementSnapshot>(`/api/v1/financing/statements/snapshots/${snapshotId}/link-facility`, {
    method: "POST",
    body: JSON.stringify({ facility_id: facilityId }),
  });
}

export function confirmFacilityDocument(docId: string, facilityId: string, values: Record<string, unknown>): Promise<unknown> {
  return apiFetch(`/api/v1/financing/documents/${docId}/confirm`, {
    method: "POST",
    body: JSON.stringify({ facility_id: facilityId, values }),
  });
}

export function getProFacilities(): Promise<ProFacility[]> {
  return apiFetch<ProFacility[]>("/api/v1/financing/facilities?lender=PRO");
}

export function getProLedger(facilityId: string): Promise<ProLedger> {
  return apiFetch<ProLedger>(`/api/v1/financing/facilities/${facilityId}/ledger`);
}
