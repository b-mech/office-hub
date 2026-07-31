export interface LenderListItem {
  id: string;
  name: string;
  contact_name?: string | null;
  contact_email?: string | null;
  contact_phone?: string | null;
  notes?: string | null;
  active_facility_count: number;
  created_at: string;
  updated_at: string;
}

export interface LenderFacilityLink {
  facility_id: string;
  property_id?: string | null;
  property_address?: string | null;
  lender_type: string;
  status: string;
  total_facility?: string | null;
  opening_balance?: string | null;
}

export interface LenderDetail extends LenderListItem {
  facilities: LenderFacilityLink[];
}

export interface LenderPayload {
  name: string;
  contact_name?: string | null;
  contact_email?: string | null;
  contact_phone?: string | null;
  notes?: string | null;
}
