const BASE = process.env.NEXT_PUBLIC_API_URL || "/backend-api";

export type LeaseFlag = "month_to_month" | "past_end" | "ending_soon" | null;
export type RosterLease = {
  id: number; status: string; display_status?: string; rent: string; rent_discount: string | null; net_rent: string; deposit: string | null;
  lease_start: string | null; lease_end: string | null; days_to_end: number | null; flag: LeaseFlag;
};
export type RosterUnit = {
  unit_id: number; unit_label: string; is_basement: boolean; unit_status: string;
  property_id: number; street_address: string; group_name: string | null; city: string | null;
  occupancy: "occupied" | "vacant"; lease: RosterLease | null; tenants: string[]; primary_tenant: string | null;
  last_lease_end: string | null; last_lease_status: string | null; lease_agreement_status: string | null;
  open_maintenance_tickets: number;
};

export type UnitLeaseHistoryEntry = {
  id: number; status: string; display_status: string; is_current: boolean;
  lease_start: string | null; lease_end: string | null; rent: string | null; rent_discount: string | null;
  net_rent: string | null; deposit: string | null; tenants: string[];
};
export type UnitOverview = {
  unit: { id: number; unit_label: string | null; display_label: string; is_basement: boolean; status: string };
  property: { id: number; street_address: string; group_name: string | null; city: string | null; address_is_shared: boolean };
  current_lease_id: number | null; leases: UnitLeaseHistoryEntry[]; lease_agreement_count: number;
};

export async function getUnitOverview(unitId: number): Promise<UnitOverview> {
  const response = await fetch(`${BASE}/api/rentals/units/${unitId}/overview`, { cache: "no-store" });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `Rental unit API ${response.status}`);
  }
  return response.json() as Promise<UnitOverview>;
}

export async function getUnitRoster(propertyId?: number): Promise<RosterUnit[]> {
  const suffix = propertyId ? `?property_id=${propertyId}` : "";
  const response = await fetch(`${BASE}/api/rentals/units/roster${suffix}`, { cache: "no-store" });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `Rental units API ${response.status}`);
  }
  return response.json() as Promise<RosterUnit[]>;
}
