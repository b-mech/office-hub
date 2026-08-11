export type AllocationRequestStatus = "draft" | "requested" | "approved" | "released";

export interface TierCapacity {
  id: string;
  face_value: string | number;
  slot_count: number;
  label?: string | null;
  slots_occupied: number;
  slots_remaining: number;
}

export interface AllocationCapacity {
  id: string;
  name: string;
  allocation_limit: string | number;
  consumed: string | number;
  remaining: string | number;
  max_units: number;
  units_used: number;
  units_remaining: number;
  max_per_unit?: string | number | null;
  funding_percentage: string | number;
  notes?: string | null;
  tiers: TierCapacity[];
}

export interface AllocationRequest {
  id: string;
  allocation_id: string;
  lot_id: string;
  property_id?: string | null;
  address: string;
  appraisal_value?: string | number | null;
  estimated_sale_price?: string | number | null;
  basis_value: string | number;
  basis_source: string;
  suggested_amount: string | number;
  actual_amount?: string | number | null;
  nearest_tier_id?: string | null;
  nearest_tier_face_value?: string | number | null;
  status: AllocationRequestStatus;
  flags: string[];
}

export interface ProgramCapacity {
  id: string;
  lender_id: string;
  lender_name: string;
  name: string;
  umbrella_limit: string | number;
  consumed: string | number;
  remaining: string | number;
  notes?: string | null;
  active: boolean;
  allocations: AllocationCapacity[];
}

export interface ProgramDetail extends ProgramCapacity {
  requests: AllocationRequest[];
}
