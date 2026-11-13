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

// ---- Shared display formatters (round 2): one date style everywhere ----
const DATE_ONLY = /^\d{4}-\d{2}-\d{2}$/;
const MONTH_ONLY = /^\d{4}-\d{2}$/;

function toDate(value: string | Date): { date: Date; utc: boolean } | null {
  if (value instanceof Date) return Number.isNaN(value.getTime()) ? null : { date: value, utc: false };
  const text = value.trim();
  // Calendar dates ("2026-08-09") are not instants: format them in UTC so they never shift a day.
  if (DATE_ONLY.test(text)) return { date: new Date(`${text}T00:00:00Z`), utc: true };
  if (MONTH_ONLY.test(text)) return { date: new Date(`${text}-01T00:00:00Z`), utc: true };
  const parsed = new Date(text);
  return Number.isNaN(parsed.getTime()) ? null : { date: parsed, utc: false };
}

/** "Aug 9, 2026". Date-only strings are calendar dates; timestamps use the viewer's zone. */
export function formatDate(value: string | Date | null | undefined, empty = "—"): string {
  const parsed = value ? toDate(value) : null;
  if (!parsed) return empty;
  return new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", year: "numeric", ...(parsed.utc ? { timeZone: "UTC" } : {}) }).format(parsed.date);
}

/** "Aug 9, 2026, 3:40 PM" for timestamps; date-only values fall back to formatDate. */
export function formatDateTime(value: string | Date | null | undefined, empty = "—"): string {
  const parsed = value ? toDate(value) : null;
  if (!parsed) return empty;
  if (parsed.utc) return formatDate(value, empty);
  return new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit" }).format(parsed.date);
}

/** "Oct 2026" from "2026-10", "2026-10-01" or a timestamp. */
export function formatMonth(value: string | Date | null | undefined, empty = "—"): string {
  const parsed = value ? toDate(value) : null;
  if (!parsed) return empty;
  return new Intl.DateTimeFormat("en-US", { month: "short", year: "numeric", ...(parsed.utc ? { timeZone: "UTC" } : {}) }).format(parsed.date);
}

/** "1 property", "3 properties", "1 photo", "0 photos". */
export function plural(count: number, singular: string, pluralForm = `${singular}s`): string {
  return `${count} ${count === 1 ? singular : pluralForm}`;
}

// ---- Phone numbers: display only, storage stays E.164 ----
/** "+14313348018" -> "(431) 334-8018"; non-NANP numbers are returned unchanged. */
export function formatPhone(value: string | null | undefined): string {
  if (!value) return "—";
  const digits = value.replace(/\D/g, "");
  const local = digits.length === 11 && digits.startsWith("1") ? digits.slice(1) : digits.length === 10 ? digits : null;
  if (!local) return value;
  return `(${local.slice(0, 3)}) ${local.slice(3, 6)}-${local.slice(6)}`;
}

// ---- Maintenance wording ----
export const TICKET_CATEGORY_LABELS: Record<string, string> = {
  plumbing: "Plumbing", electrical: "Electrical", heating: "Heating", cooling: "Cooling", appliance: "Appliance",
  doors_locks_windows: "Doors, locks & windows", pests: "Pests", exterior_grounds: "Exterior & grounds",
  structural: "Structural", water_leak: "Water leak", no_heat: "No heat", gas_smell: "Gas smell",
  no_power: "No power", security: "Security", other: "Other",
};
export const categoryLabel = (value: string) => TICKET_CATEGORY_LABELS[value] || value.charAt(0).toUpperCase() + value.slice(1).replaceAll("_", " ");

/** Least to most urgent, the order staff expect in a picker. */
export const PRIORITY_ORDER = ["low", "routine", "urgent", "emergency"] as const;
export const priorityLabel = (value: string) => value.charAt(0).toUpperCase() + value.slice(1);

export const TERMINAL_TICKET_STATUSES: ReadonlySet<string> = new Set(["resolved", "closed", "cancelled", "duplicate"]);
/** "Needs reply" is only actionable on tickets that are still open. */
export function showNeedsReply(ticket: { needs_reply?: boolean | null; status: string }): boolean {
  return Boolean(ticket.needs_reply) && !TERMINAL_TICKET_STATUSES.has(ticket.status);
}

// ---- Navigation: which sidebar entry owns the current path ----
/** Longest matching href wins, so /rentals/maintenance/new highlights Maintenance, not Rentals. */
export function activeNavHref(pathname: string | null | undefined, hrefs: readonly string[]): string | null {
  if (!pathname) return null;
  let best: string | null = null;
  for (const href of hrefs) {
    if ((pathname === href || pathname.startsWith(`${href}/`)) && (!best || href.length > best.length)) best = href;
  }
  return best;
}

// ---- Inspections list: sort ----
export type InspectionSort = "address" | "oldest_inspection" | "recent_inspection";
type InspectionListItem = { street_address: string; unit_label: string | null; last_inspection: { inspection_date: string } | null };
export function sortInspectionUnits<T extends InspectionListItem>(units: readonly T[], sort: InspectionSort): T[] {
  const address = (unit: T) => `${unit.street_address} ${unit.unit_label || ""}`;
  const byAddress = (a: T, b: T) => address(a).localeCompare(address(b), "en", { numeric: true });
  const last = (unit: T) => unit.last_inspection?.inspection_date || "";
  const sorted = [...units];
  if (sort === "address") sorted.sort(byAddress);
  // Never-inspected units count as the most overdue.
  if (sort === "oldest_inspection") sorted.sort((a, b) => last(a).localeCompare(last(b)) || byAddress(a, b));
  if (sort === "recent_inspection") sorted.sort((a, b) => last(b).localeCompare(last(a)) || byAddress(a, b));
  return sorted;
}
