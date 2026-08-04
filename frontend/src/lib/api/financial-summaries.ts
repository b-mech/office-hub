export interface PropertyFinancialSummary {
  property_id: string;
  lender: {
    has_lender: boolean;
    lender_id?: string | null;
    lender_name?: string | null;
    facility_type?: string | null;
  };
  draw?: {
    opening_balance?: string | number | null;
    drawn_to_date?: string | number | null;
    remaining?: string | number | null;
    current_stage?: string | null;
    next_eligible_draw?: string | number | null;
    last_draw_date?: string | null;
    facility_document_count: number;
  } | null;
  prep_draw: {
    state: "no_active_schedule" | "pending_review" | "ready_to_request";
    ready_to_request: boolean;
  };
  change_orders: {
    count: number;
    pending_signature_count: number;
    total_value: string | number;
    last_signed_at?: string | null;
    box_filed?: boolean | null;
    box_unfiled: boolean;
  };
}

const BASE = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

export async function getPropertyFinancialSummary(propertyId: string): Promise<PropertyFinancialSummary> {
  const response = await fetch(`${BASE}/api/v1/financing/properties/${propertyId}/financial-summary`, {
    cache: "no-store",
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(typeof body.detail === "string" ? body.detail : `API error ${response.status}`);
  }
  return response.json() as Promise<PropertyFinancialSummary>;
}
