import { API_BASE } from "@/lib/api";

const LOTS_API_BASE = API_BASE.endsWith("/api/v1") ? API_BASE : `${API_BASE}/api/v1`;

export interface TimelineEvent {
  id: string;
  lot_id: string;
  address: string;
  client_name: string;
  event_type: string;
  event_label: string;
  event_date: string;
  amount: number | null;
  days_until: number;
  urgency: "overdue" | "soon" | "upcoming";
}

export async function getOtpTimeline(): Promise<TimelineEvent[]> {
  const response = await fetch(`${LOTS_API_BASE}/lots/timeline`, {
    credentials: "include",
    cache: "no-store",
  });

  if (!response.ok) {
    const errorBody = await response.json().catch(() => ({})) as { detail?: string };
    throw new Error(errorBody.detail || `Timeline request failed with status ${response.status}`);
  }

  return await response.json() as TimelineEvent[];
}
