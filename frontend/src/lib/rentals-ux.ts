// Pure display helpers for the Rentals UX fixes (no I/O). Covered by rentals-ux.test.ts.

// ---- Lease status (derived from dates on the server; mirrored here for labels/tone) ----
export type LeaseDisplayStatus = "active" | "expired" | "upcoming" | "month_to_month" | string;
export type Tone = "success" | "error" | "info" | "warning" | "muted";

export function leaseStatusLabel(status: LeaseDisplayStatus | null | undefined): string {
  if (!status) return "—";
  if (status === "month_to_month") return "Month to month";
  return status.charAt(0).toUpperCase() + status.slice(1).replaceAll("_", " ");
}

export function leaseStatusTone(status: LeaseDisplayStatus | null | undefined): Tone {
  if (status === "active" || status === "month_to_month") return "success";
  if (status === "expired") return "error";
  if (status === "upcoming") return "info";
  return "muted";
}

export const TONE_CLASS: Record<Tone, string> = {
  success: "border-[var(--ch-success-border)] bg-[var(--ch-success-bg)] text-[var(--ch-success-text)]",
  error: "border-[var(--ch-error-border)] bg-[var(--ch-error-bg)] text-[var(--ch-error-text)]",
  info: "border-[var(--ch-info-border)] bg-[var(--ch-info-bg)] text-[var(--ch-info-text)]",
  warning: "border-[var(--ch-warning-border)] bg-[var(--ch-warning-bg)] text-[var(--ch-warning-text)]",
  muted: "border-[var(--ch-border)] bg-[var(--ch-surface-muted)] text-[var(--ch-text-muted)]",
};

/** Client-side mirror of the server rule, for places that only have raw dates. */
export function deriveLeaseStatus(recorded: string, start: string | null, end: string | null, today: string): LeaseDisplayStatus {
  if (recorded !== "active" && recorded !== "month_to_month") return recorded;
  if (start && start > today) return "upcoming";
  if (recorded === "month_to_month") return "month_to_month";
  if (end && end < today) return "expired";
  return "active";
}

// ---- Duplicate addresses: add a distinguishing ID wherever an address repeats ----
const norm = (value: string | null | undefined) => (value || "").trim().toLowerCase();

export function duplicateKeys<T>(items: readonly T[], key: (item: T) => string | null | undefined): Set<string> {
  const seen = new Map<string, number>();
  for (const item of items) seen.set(norm(key(item)), (seen.get(norm(key(item))) || 0) + 1);
  return new Set([...seen].filter(([name, count]) => name && count > 1).map(([name]) => name));
}

/** "166 Clubhouse Drive · Lorette · #12" (ID only appended when the address is not unique). */
export function propertyOptionLabel(
  item: { id: number; address?: string | null; name?: string | null },
  duplicates: Set<string>,
): string {
  const address = item.address || item.name || `Property ${item.id}`;
  const parts = [address];
  if (item.name && item.address && item.name !== item.address) parts.push(item.name);
  if (duplicates.has(norm(item.address || item.name))) parts.push(`#${item.id}`);
  return parts.join(" · ");
}

// ---- Rental map filters ----
export type MapFilterItem = { street_address: string; group_name: string | null; inspection_status: string; company_name?: string | null };
export type MapFilters = { query: string; group: string; status: string };
export const DEFAULT_MAP_FILTERS: MapFilters = { query: "", group: "", status: "" };

export function filterMapItems<T extends MapFilterItem>(items: readonly T[], filters: MapFilters): T[] {
  const needle = filters.query.trim().toLowerCase();
  return items.filter((item) =>
    (!needle || `${item.street_address} ${item.group_name || ""} ${item.company_name || ""}`.toLowerCase().includes(needle))
    && (!filters.group || (item.group_name || "") === filters.group)
    && (!filters.status || item.inspection_status === filters.status));
}

export function mapFiltersActive(filters: MapFilters): boolean {
  return Boolean(filters.query.trim() || filters.group || filters.status);
}

// ---- Inspection reports: expired status, search, sort ----
export type ReportLike = { id: string; title: string; status: string; expires_at: string; created_at?: string | null; sent_at?: string | null; recipient_email?: string | null; items: { address: string }[] };
export type ReportSort = "newest" | "oldest" | "expires" | "title";

export function reportStatus(report: Pick<ReportLike, "status" | "expires_at">, now: Date = new Date()): string {
  return new Date(report.expires_at).getTime() <= now.getTime() ? "expired" : report.status;
}

export function shortId(id: string): string {
  return id.replaceAll("-", "").slice(0, 8);
}

export function filterReports<T extends ReportLike>(reports: readonly T[], query: string, sort: ReportSort, status = "", now: Date = new Date()): T[] {
  const tokens = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  const filtered = reports.filter((report) => {
    const hay = [report.title, report.id, shortId(report.id), report.recipient_email || "", ...report.items.map((item) => item.address)].join(" ").toLowerCase();
    return tokens.every((token) => hay.includes(token)) && (!status || reportStatus(report, now) === status);
  });
  const created = (report: ReportLike) => report.created_at || report.sent_at || report.expires_at;
  const sorted = [...filtered];
  if (sort === "newest") sorted.sort((a, b) => created(b).localeCompare(created(a)));
  if (sort === "oldest") sorted.sort((a, b) => created(a).localeCompare(created(b)));
  if (sort === "expires") sorted.sort((a, b) => a.expires_at.localeCompare(b.expires_at));
  if (sort === "title") sorted.sort((a, b) => a.title.localeCompare(b.title, "en", { numeric: true }) || created(b).localeCompare(created(a)));
  return sorted;
}

// ---- Maintenance queue empty state ----
export type QueueFilterState = { status?: string; priority?: string; property_id?: number; assignee_id?: string; needs_reply?: boolean; include_terminal?: boolean };

export function queueFiltersActive(filters: QueueFilterState, query: string): boolean {
  return Boolean(query.trim() || filters.status || filters.priority || filters.property_id || filters.assignee_id || filters.needs_reply);
}

export function queueEmptyMessage(filters: QueueFilterState, query: string): { title: string; detail: string; canReset: boolean } {
  if (queueFiltersActive(filters, query)) {
    return { title: "No tickets match these filters.", detail: "Tickets exist that are hidden by the current search or filters.", canReset: true };
  }
  if (filters.include_terminal) return { title: "No maintenance tickets yet.", detail: "Nothing has been reported for any property.", canReset: false };
  return { title: "No open tickets right now.", detail: "Every ticket is resolved or closed. Tick “Include closed” to see history.", canReset: false };
}

// ---- Inspections ----
export function todayIso(now: Date = new Date()): string {
  const local = new Date(now.getTime() - now.getTimezoneOffset() * 60000);
  return local.toISOString().slice(0, 10);
}

export function inspectionStatusLabel(status: string): string {
  return status === "submitted" ? "Submitted" : status === "draft" ? "Draft" : leaseStatusLabel(status);
}
