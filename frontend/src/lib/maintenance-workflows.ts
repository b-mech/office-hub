// Pure helpers for the maintenance P1/P2 workflows (kept framework-free so node:test can run them).

export type DuplicateCandidateSource = {
  id: string;
  number: string;
  title: string;
  property: string;
  unit: string;
  status: string;
};

const DUPLICATE_TARGET_BLOCKED = new Set(["cancelled", "duplicate"]);

/** Tickets that may be chosen as the canonical ticket, best matches first. */
export function duplicateCandidates<T extends DuplicateCandidateSource>(
  tickets: readonly T[],
  currentId: string,
  query: string,
  limit = 8,
): T[] {
  const needle = query.trim().toLowerCase().replace(/^#/, "");
  const allowed = tickets.filter((ticket) => ticket.id !== currentId && !DUPLICATE_TARGET_BLOCKED.has(ticket.status));
  if (!needle) return allowed.slice(0, limit);
  const scored: { ticket: T; score: number }[] = [];
  for (const ticket of allowed) {
    const number = ticket.number.toLowerCase();
    const digits = number.replace(/\D/g, "");
    const haystack = `${number} ${ticket.title} ${ticket.property} ${ticket.unit}`.toLowerCase();
    let score = -1;
    if (number === needle || (needle.replace(/\D/g, "") && digits.endsWith(needle.replace(/\D/g, "")) && /^\d+$/.test(needle))) score = 0;
    else if (number.startsWith(needle)) score = 1;
    else if (haystack.includes(needle)) score = 2;
    if (score >= 0) scored.push({ ticket, score });
  }
  return scored.sort((a, b) => a.score - b.score).slice(0, limit).map((entry) => entry.ticket);
}

export type ChecklistProgress = { total: number; done: number };

export function checklistLabel(progress: ChecklistProgress | null | undefined): string | null {
  if (!progress || progress.total === 0) return null;
  return progress.done === progress.total ? `Checklist done (${progress.total})` : `${progress.done}/${progress.total} done`;
}

/** Parse a money input ("$1,234.5") into the API's decimal string, or null when blank. Throws on junk. */
export function parseMoney(input: string | null | undefined): string | null {
  const raw = (input ?? "").trim().replace(/[$,\s]/g, "");
  if (!raw) return null;
  if (!/^\d+(\.\d{1,2})?$/.test(raw)) throw new Error("Enter an amount like 125.50");
  return raw;
}

export function formatMoney(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  const numeric = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(numeric)) return "—";
  return new Intl.NumberFormat("en-CA", { style: "currency", currency: "CAD" }).format(numeric);
}

export type ListFilterState = {
  property_id?: number;
  assignee_id?: string;
  status?: string;
  priority?: string;
  needs_reply?: boolean;
  include_terminal?: boolean;
};

/** Read deep-link filters such as /rentals/maintenance?property_id=12 */
export function filtersFromSearch(search: string): ListFilterState {
  const params = new URLSearchParams(search);
  const result: ListFilterState = {};
  const property = Number(params.get("property_id"));
  if (Number.isInteger(property) && property > 0) result.property_id = property;
  const assignee = params.get("assignee_id");
  if (assignee && /^[0-9a-f-]{36}$/i.test(assignee)) result.assignee_id = assignee;
  const status = params.get("status");
  if (status) result.status = status;
  const priority = params.get("priority");
  if (priority) result.priority = priority;
  if (params.get("needs_reply") === "true") result.needs_reply = true;
  if (params.get("include_terminal") === "true") result.include_terminal = true;
  return result;
}

export function filtersToSearch(filters: ListFilterState): string {
  const params = new URLSearchParams();
  if (filters.property_id) params.set("property_id", String(filters.property_id));
  if (filters.assignee_id) params.set("assignee_id", filters.assignee_id);
  if (filters.status) params.set("status", filters.status);
  if (filters.priority) params.set("priority", filters.priority);
  if (filters.needs_reply) params.set("needs_reply", "true");
  if (filters.include_terminal) params.set("include_terminal", "true");
  const text = params.toString();
  return text ? `?${text}` : "";
}

export function maintenanceHrefForProperty(propertyId: number): string {
  return `/rentals/maintenance${filtersToSearch({ property_id: propertyId, include_terminal: false })}`;
}
