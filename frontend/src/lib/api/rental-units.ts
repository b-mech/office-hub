const BASE = process.env.NEXT_PUBLIC_API_URL || "/backend-api";

export type LeaseFlag = "month_to_month" | "past_end" | "ending_soon" | null;
export type RosterLease = {
  id: number; status: string; rent: string; rent_discount: string | null; net_rent: string; deposit: string | null;
  lease_start: string | null; lease_end: string | null; days_to_end: number | null; flag: LeaseFlag;
};
export type RosterUnit = {
  unit_id: number; unit_label: string; is_basement: boolean; unit_status: string;
  property_id: number; street_address: string; group_name: string | null; city: string | null;
  occupancy: "occupied" | "vacant"; lease: RosterLease | null; tenants: string[]; primary_tenant: string | null;
  last_lease_end: string | null; last_lease_status: string | null; lease_agreement_status: string | null;
  open_maintenance_tickets: number;
};

export async function getUnitRoster(propertyId?: number): Promise<RosterUnit[]> {
  const suffix = propertyId ? `?property_id=${propertyId}` : "";
  const response = await fetch(`${BASE}/api/rentals/units/roster${suffix}`, { cache: "no-store" });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `Rental units API ${response.status}`);
  }
  return response.json() as Promise<RosterUnit[]>;
}
