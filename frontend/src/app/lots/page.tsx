"use client";

import { getLots } from "@/lib/api/costbook";
import { LotWorkspace } from "./components/LotWorkspace";

export default function LotsPage() {
  return (
    <LotWorkspace
      title="Lots"
      loadingText="Loading lots..."
      emptyText="No lots found"
      loadLots={getLots}
    />
  );
}
