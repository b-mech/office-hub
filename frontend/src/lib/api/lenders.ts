import type { LenderDetail, LenderListItem, LenderPayload } from "@/types/lenders";

const BASE = process.env.NEXT_PUBLIC_API_URL || "/backend-api";
const LENDERS_PATH = "/api/v1/financing/lenders";

async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    ...options,
    cache: "no-store",
    headers: {
      "Content-Type": "application/json",
      ...(options?.headers || {}),
    },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(typeof body.detail === "string" ? body.detail : `API error ${response.status}`);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export function getLenders(): Promise<LenderListItem[]> {
  return apiFetch<LenderListItem[]>(LENDERS_PATH);
}

export function getLender(id: string): Promise<LenderDetail> {
  return apiFetch<LenderDetail>(`${LENDERS_PATH}/${id}`);
}

export function createLender(payload: LenderPayload): Promise<LenderDetail> {
  return apiFetch<LenderDetail>(LENDERS_PATH, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateLender(id: string, payload: Partial<LenderPayload>): Promise<LenderDetail> {
  return apiFetch<LenderDetail>(`${LENDERS_PATH}/${id}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function deleteLender(id: string): Promise<void> {
  return apiFetch<void>(`${LENDERS_PATH}/${id}`, { method: "DELETE" });
}
