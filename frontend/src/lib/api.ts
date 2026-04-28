export const API_BASE =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";

export interface Document {
  id: string;
  doc_type: string;
  status: string;
  original_filename: string | null;
  received_at: string;
  received_from_email: string | null;
}

export interface DocumentDetail {
  document: Document & {
    org_id: string;
    minio_bucket: string;
    minio_key: string;
    file_size_bytes: number | null;
    checksum_sha256: string | null;
  };
  ingestion: {
    id: string;
    ocr_method: string;
    ocr_confidence: number | null;
  } | null;
  extraction: {
    id: string;
    extracted_payload: {
      agreement?: Record<string, string | number | null>;
      security_deposit?: Record<string, string | number | null>;
      lots?: Array<Record<string, string | number | null>>;
      notable_clauses?: Array<Record<string, string | number | null>>;
    };
    field_confidences: Record<string, number>;
    low_confidence_fields: string[];
  } | null;
}

export interface ReviewRequest {
  reviewed_payload: Record<string, unknown>;
  edited_fields: string[];
  decision: "approved" | "rejected" | "deferred";
  rejection_reason?: string;
}

export interface ReviewResponse {
  id: string;
  decision: string;
  promotion?: {
    agreement_id: string;
    lots_created: number;
    lots_matched: number;
    promoted_at: string;
  };
}

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {}),
    },
    cache: "no-store",
  });

  if (!response.ok) {
    let message = `Request failed with status ${response.status}`;
    try {
      const errorBody = (await response.json()) as { detail?: string };
      if (errorBody.detail) {
        message = errorBody.detail;
      }
    } catch {
      // Keep the fallback status message when the response is not JSON.
    }
    throw new Error(message);
  }

  return (await response.json()) as T;
}

export async function listDocuments(
  status?: string,
  docType?: string,
): Promise<Document[]> {
  const params = new URLSearchParams();
  if (status) {
    params.set("status", status);
  }
  if (docType) {
    params.set("doc_type", docType);
  }

  const query = params.toString();
  return apiFetch<Document[]>(`/documents${query ? `?${query}` : ""}`);
}

export async function getDocument(id: string): Promise<DocumentDetail> {
  return apiFetch<DocumentDetail>(`/documents/${id}`);
}

export function getDocumentPdfUrl(id: string): string {
  return `${API_BASE}/documents/${id}/pdf#view=FitH&pagemode=none&navpanes=0`;
}

export async function submitReview(
  id: string,
  payload: ReviewRequest,
): Promise<ReviewResponse> {
  return apiFetch<ReviewResponse>(`/documents/${id}/review`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
