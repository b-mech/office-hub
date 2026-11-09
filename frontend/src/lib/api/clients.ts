import { workspaceFetch } from "@/lib/api/workspace";

export type ClientStage = "lead" | "qualified" | "active" | "possession" | "warranty" | "closed" | "lost";
export type ClientType = "individual" | "company";

export const CLIENT_STAGES: { value: ClientStage; label: string }[] = [
  { value: "lead", label: "Lead" },
  { value: "qualified", label: "Qualified" },
  { value: "active", label: "Active project" },
  { value: "possession", label: "Possession" },
  { value: "warranty", label: "Warranty" },
  { value: "closed", label: "Closed" },
  { value: "lost", label: "Lost" },
];

export const stageLabel = (stage: string) => CLIENT_STAGES.find((item) => item.value === stage)?.label || stage;

export interface ContactSummary {
  id: string;
  full_name: string;
  company_name: string | null;
  email: string | null;
  phone: string | null;
  contact_type: string;
}

export interface ClientProject {
  id: string;
  address: string;
  community: string;
  lifecycle_status: string;
  trigger_type: string | null;
  on_hold: boolean;
  possession_date: string | null;
}

export interface Client {
  id: string;
  org_id: string;
  display_name: string;
  client_type: ClientType;
  lifecycle_stage: ClientStage;
  stage_changed_at: string;
  primary_contact: ContactSummary | null;
  external_ref: string | null;
  notes: string | null;
  project_count: number;
  created_at: string;
  updated_at: string;
}

export interface ClientDetail extends Client {
  projects: ClientProject[];
  duplicate_name_count: number;
}

export interface ClientPayload {
  display_name?: string;
  client_type?: ClientType;
  lifecycle_stage?: ClientStage;
  primary_contact_id?: string | null;
  external_ref?: string | null;
  notes?: string | null;
}

export function listClients(params: { q?: string; stage?: string; limit?: number; offset?: number } = {}) {
  const search = new URLSearchParams();
  if (params.q) search.set("q", params.q);
  if (params.stage) search.set("stage", params.stage);
  if (params.limit) search.set("limit", String(params.limit));
  if (params.offset) search.set("offset", String(params.offset));
  const query = search.toString();
  return workspaceFetch<{ items: Client[]; total: number; limit: number; offset: number }>(`/api/v1/clients${query ? `?${query}` : ""}`);
}

export const getClient = (id: string) => workspaceFetch<ClientDetail>(`/api/v1/clients/${id}`);
export const createClient = (payload: ClientPayload & { display_name: string }) =>
  workspaceFetch<ClientDetail>("/api/v1/clients", { method: "POST", body: JSON.stringify(payload) });
export const updateClient = (id: string, payload: ClientPayload) =>
  workspaceFetch<ClientDetail>(`/api/v1/clients/${id}`, { method: "PATCH", body: JSON.stringify(payload) });
export const getContactOptions = (q?: string) =>
  workspaceFetch<ContactSummary[]>(`/api/v1/clients/contact-options${q ? `?q=${encodeURIComponent(q)}` : ""}`);
export const setProjectClient = (lotId: string, clientId: string | null) =>
  workspaceFetch<{ client_id: string | null }>(`/api/v1/projects/${lotId}/client`, {
    method: "PUT",
    body: JSON.stringify({ client_id: clientId }),
  });
