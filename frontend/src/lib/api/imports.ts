import { API_BASE } from "@/lib/api";

const OFFICE_HUB_API_KEY =
  process.env.NEXT_PUBLIC_OFFICE_HUB_API_KEY ||
  "b253ca1b038185185289506cd64642a1b8e478d86b09c8c58c8cad7faded8960";

export type ImportDocType = "budget" | "sale_otp" | "land_otp" | "change_order";

export interface ImportResult {
  document_id: string;
  status: string;
  resource_type?: "document" | "budget";
  resource_id?: string;
  budget_id?: string;
  extraction_summary?: string;
}

export interface ImportMatchCandidate {
  id: string;
  address: string;
  lot_number?: string | null;
  community?: string | null;
  land_agreement_id?: string | null;
  sale_agreement_id?: string | null;
}

export interface ImportErrorDetail {
  code?: string;
  message?: string;
  search_text?: string;
  candidates?: ImportMatchCandidate[];
}

export class ImportApiError extends Error {
  status: number;
  detail: ImportErrorDetail | string | undefined;

  constructor(status: number, detail: ImportErrorDetail | string | undefined) {
    const message = typeof detail === "string" ? detail : detail?.message;
    super(message || `Import failed with status ${status}`);
    this.name = "ImportApiError";
    this.status = status;
    this.detail = detail;
  }
}

export interface ImportHistoryItem {
  id: string;
  doc_type: string;
  status: string;
  original_filename?: string | null;
  received_at?: string;
}

export interface BoxStatus {
  configured: boolean;
  authenticated: boolean;
}

export async function processImport(
  file: File,
  docType: ImportDocType,
  options: { matchedLotId?: string } = {}
): Promise<ImportResult> {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("doc_type", docType);
  if (options.matchedLotId) formData.append("matched_lot_id", options.matchedLotId);

  const response = await fetch(`${API_BASE}/ingest`, {
    method: "POST",
    body: formData,
    cache: "no-store",
  });

  if (!response.ok) {
    const errorBody = await response.json().catch(() => ({})) as { detail?: ImportErrorDetail | string };
    throw new ImportApiError(response.status, errorBody.detail);
  }

  return await response.json() as ImportResult;
}

// TODO: Render import history after GET /api/v1/ingest/recent is implemented server-side.
export async function getImportHistory(): Promise<ImportHistoryItem[]> {
  const response = await fetch(`${API_BASE}/ingest/recent`, {
    cache: "no-store",
  });

  if (response.status === 404 || response.status === 405) {
    return [];
  }
  if (!response.ok) {
    const errorBody = await response.json().catch(() => ({})) as { detail?: string };
    throw new Error(errorBody.detail || `Import history failed with status ${response.status}`);
  }

  return await response.json() as ImportHistoryItem[];
}

export async function getBoxStatus(): Promise<BoxStatus> {
  const response = await fetch(`${API_BASE}/box/status`, {
    headers: { "X-API-Key": OFFICE_HUB_API_KEY },
    cache: "no-store",
  });
  if (!response.ok) {
    const errorBody = await response.json().catch(() => ({})) as { detail?: string };
    throw new Error(errorBody.detail || `Box status failed with status ${response.status}`);
  }
  return await response.json() as BoxStatus;
}

export async function getBoxConnectUrl(): Promise<string> {
  const response = await fetch(`${API_BASE}/box/connect`, {
    cache: "no-store",
  });
  if (!response.ok) {
    const errorBody = await response.json().catch(() => ({})) as { detail?: string };
    throw new Error(errorBody.detail || `Box connect failed with status ${response.status}`);
  }
  const data = await response.json() as { auth_url?: string };
  if (!data.auth_url) throw new Error("Box connect did not return an auth URL.");
  return data.auth_url;
}
