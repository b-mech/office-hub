// Pure filtering/sorting/summary helpers for the read-only Rental Units page.
import type { RosterUnit } from "./api/rental-units";

export type Occupancy = "all" | "occupied" | "vacant";
export type LeaseFilter = "all" | "ending_soon" | "past_end" | "month_to_month";
export type SortKey = "address" | "lease_end" | "rent" | "tenant";
export type RosterFilters = {
  query: string; occupancy: Occupancy; group: string; leaseFilter: LeaseFilter; propertyId?: number; sort: SortKey;
};

export const DEFAULT_FILTERS: RosterFilters = { query: "", occupancy: "all", group: "", leaseFilter: "all", sort: "address" };

export function matchesQuery(unit: RosterUnit, query: string): boolean {
  const tokens = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  if (!tokens.length) return true;
  const haystack = [unit.street_address, unit.unit_label, unit.group_name, unit.city, ...unit.tenants]
    .filter(Boolean).join(" ").toLowerCase();
  return tokens.every((token) => haystack.includes(token));
}

function compareText(a: string, b: string) {
  return a.localeCompare(b, "en", { numeric: true, sensitivity: "base" });
}

export function filterRoster(units: readonly RosterUnit[], filters: RosterFilters): RosterUnit[] {
  const result = units.filter((unit) =>
    matchesQuery(unit, filters.query)
    && (filters.occupancy === "all" || unit.occupancy === filters.occupancy)
    && (!filters.group || (unit.group_name || "") === filters.group)
    && (!filters.propertyId || unit.property_id === filters.propertyId)
    && (filters.leaseFilter === "all" || unit.lease?.flag === filters.leaseFilter));
  const byAddress = (a: RosterUnit, b: RosterUnit) => compareText(a.street_address, b.street_address) || compareText(a.unit_label, b.unit_label);
  const sorted = [...result];
  if (filters.sort === "address") sorted.sort(byAddress);
  if (filters.sort === "tenant") sorted.sort((a, b) => compareText(a.primary_tenant || "\uffff", b.primary_tenant || "\uffff") || byAddress(a, b));
  if (filters.sort === "rent") sorted.sort((a, b) => Number(b.lease?.net_rent ?? -1) - Number(a.lease?.net_rent ?? -1) || byAddress(a, b));
  if (filters.sort === "lease_end") sorted.sort((a, b) => (a.lease?.lease_end || "9999-12-31").localeCompare(b.lease?.lease_end || "9999-12-31") || byAddress(a, b));
  return sorted;
}

export type RosterSummary = { units: number; occupied: number; vacant: number; endingSoon: number; monthlyRent: number; openTickets: number };

export function summarize(units: readonly RosterUnit[]): RosterSummary {
  return units.reduce<RosterSummary>((total, unit) => ({
    units: total.units + 1,
    occupied: total.occupied + (unit.occupancy === "occupied" ? 1 : 0),
    vacant: total.vacant + (unit.occupancy === "vacant" ? 1 : 0),
    endingSoon: total.endingSoon + (unit.lease?.flag === "ending_soon" ? 1 : 0),
    monthlyRent: total.monthlyRent + (unit.lease ? Number(unit.lease.net_rent) || 0 : 0),
    openTickets: total.openTickets + unit.open_maintenance_tickets,
  }), { units: 0, occupied: 0, vacant: 0, endingSoon: 0, monthlyRent: 0, openTickets: 0 });
}

export function groups(units: readonly RosterUnit[]): string[] {
  return Array.from(new Set(units.map((unit) => unit.group_name).filter((name): name is string => Boolean(name)))).sort(compareText);
}

const csvCell = (value: unknown) => {
  let text = value === null || value === undefined ? "" : String(value);
  if (/^[=+\-@]/.test(text)) text = `'${text}`;
  return /[",\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
};

export function rosterCsv(units: readonly RosterUnit[]): string {
  const header = ["Address", "Unit", "Group", "Occupancy", "Tenants", "Lease status", "Rent", "Discount", "Net rent", "Lease start", "Lease end", "Open tickets"];
  const lines = units.map((unit) => [
    unit.street_address, unit.unit_label, unit.group_name, unit.occupancy, unit.tenants.join("; "), unit.lease?.status,
    unit.lease?.rent, unit.lease?.rent_discount, unit.lease?.net_rent, unit.lease?.lease_start, unit.lease?.lease_end,
    unit.open_maintenance_tickets,
  ].map(csvCell).join(","));
  return [header.join(","), ...lines].join("\n") + "\n";
}

export function leaseFlagLabel(unit: RosterUnit): string | null {
  const lease = unit.lease;
  if (!lease?.flag) return null;
  if (lease.flag === "month_to_month") return "Month to month";
  if (lease.flag === "past_end") return "Past end date";
  return `Ends in ${lease.days_to_end} days`;
}
