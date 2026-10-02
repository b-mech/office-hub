const BASE = process.env.NEXT_PUBLIC_API_URL || "/backend-api";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, { ...options, cache: "no-store" });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `API error ${response.status}`);
  }
  return response.json() as Promise<T>;
}

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
