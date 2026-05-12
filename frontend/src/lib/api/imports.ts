import { API_BASE } from "@/lib/api";

export type ImportDocType = "budget" | "sale_otp" | "land_otp" | "change_order";

export interface ImportResult {
  document_id: string;
  status: string;
  extraction_summary?: string;
}

export interface ImportHistoryItem {
  id: string;
  doc_type: string;
  status: string;
  original_filename?: string | null;
  received_at?: string;
}

export async function processImport(file: File, docType: ImportDocType): Promise<ImportResult> {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("doc_type", docType);

  const response = await fetch(`${API_BASE}/ingest`, {
    method: "POST",
    body: formData,
    cache: "no-store",
  });

  if (!response.ok) {
    const errorBody = await response.json().catch(() => ({})) as { detail?: string };
    throw new Error(errorBody.detail || `Import failed with status ${response.status}`);
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
