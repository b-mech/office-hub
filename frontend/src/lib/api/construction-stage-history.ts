const BASE = process.env.NEXT_PUBLIC_API_URL || "/backend-api";

export interface ConstructionStageHistoryEvent {
  id: string;
  property_id: string;
  previous_stage?: string | null;
  new_stage: string;
  changed_at: string;
  synced_at: string;
}

export async function getConstructionStageHistory(propertyId: string): Promise<ConstructionStageHistoryEvent[]> {
  const response = await fetch(
    `${BASE}/api/v1/financing/properties/${propertyId}/construction-stage-history`,
    { cache: "no-store" },
  );
  if (!response.ok) throw new Error(`Unable to load construction stage history (${response.status})`);
  return response.json() as Promise<ConstructionStageHistoryEvent[]>;
}
