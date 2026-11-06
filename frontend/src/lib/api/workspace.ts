import { tenantHeaders } from "@/lib/tenant";

const BASE = process.env.NEXT_PUBLIC_API_URL || "/backend-api";

export async function workspaceFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    ...init,
    credentials: "include",
    cache: "no-store",
    headers: {
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...tenantHeaders(),
      ...(init?.headers || {}),
    },
  });
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as { detail?: unknown };
    throw new Error(typeof body.detail === "string" ? body.detail : `Request failed with status ${response.status}`);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export interface WorkspaceOrg {
  id: string;
  slug: string;
  name: string;
  member_project_scope: "org" | "assigned";
  land_enabled: boolean;
}

export type Capability = "projects" | "clients" | "manage_clients" | "land" | "rentals" | "legacy_modules" | "settings" | "org_switch";

export interface WorkspaceContext {
  actor: { id: string; full_name: string; email: string; is_superadmin: boolean; is_fallback: boolean };
  org: WorkspaceOrg;
  membership_role: "tenant_admin" | "member" | null;
  available_orgs: WorkspaceOrg[];
  capabilities: Record<Capability, boolean>;
}

export interface DashboardProject {
  id: string;
  address: string;
  community: string;
  status: string;
  lifecycle_status: string;
  possession_date: string | null;
  client_name: string | null;
  construction_stage: string | null;
}

export interface DashboardTender {
  id: string;
  status: string;
  due_date: string | null;
  scope_description: string;
  category: string;
  lot_id: string;
  address: string;
  bids_received: number;
}

export interface DashboardData {
  org: { id: string; name: string };
  projects: { total: number; by_status: Record<string, number>; active: DashboardProject[] };
  tenders: { total: number; items: DashboardTender[] };
  upcoming_possessions: { lot_id: string; address: string; community: string; client_name: string | null; possession_date: string; days_until: number }[];
  otp_milestones: null | {
    overdue: number;
    next_30_days: number;
    items: { id: string; lot_id: string; address: string; client_name: string; event_label: string; event_date: string; days_until: number; urgency: string }[];
  };
  clients: null | {
    by_stage: Record<string, number>;
    recent_stage_changes: { id: string; display_name: string; lifecycle_stage: string; stage_changed_at: string }[];
  };
  rentals: null | {
    properties: number;
    units: number;
    leases_expiring_90_days: number;
    maintenance_open: number;
    lease_agreements_awaiting_signature: number;
  };
}

export interface RentalsOverview {
  scope_note: string;
  properties: number;
  units: number;
  rental_leases_by_status: Record<string, number>;
  lease_agreements_by_status: Record<string, number>;
  lease_agreements_awaiting_signature: number;
  lease_agreement_open_tasks: number;
  leases_expiring_90_days_count: number;
  leases_expiring_90_days: { id: number; unit_id: number; lease_end: string; street_address: string; unit_label: string; days_until: number }[];
  maintenance_open_by_priority: Record<string, number>;
  maintenance_open_tickets: { id: string; number: string; title: string; priority: string; status: string; created_at: string | null; sla_due_at: string | null; street_address: string | null; unit_label: string | null }[];
  occupancy: null;
  rent_collected: null;
  not_tracked: string[];
}

export const getWorkspaceContext = () => workspaceFetch<WorkspaceContext>("/api/v1/workspace/context");
export const getDashboard = () => workspaceFetch<DashboardData>("/api/v1/workspace/dashboard");
export const getRentalsOverview = () => workspaceFetch<RentalsOverview>("/api/v1/workspace/rentals-overview");
