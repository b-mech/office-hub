import { useState } from "react";
import { Upload } from "lucide-react";
import { confirmFacilityDocument, uploadFacilityDocument } from "@/lib/api/financing";
import type { FinancingProperty, UploadResponse } from "@/types/financing";
import { ExtractionReviewCard } from "./ExtractionReviewCard";

export function DocumentUploadPanel({
  property,
  onUpdated,
}: {
  property: FinancingProperty;
  onUpdated: () => Promise<void>;
}) {
  const [upload, setUpload] = useState<UploadResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onFile(file?: File) {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      setUpload(await uploadFacilityDocument({ lenderType: property.lender_type, propertyId: property.property_id, file }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="space-y-3 rounded-lg border border-[var(--ch-border)] bg-[var(--ch-surface-muted)] p-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold">Balance Documents</h3>
          {property.lender_type === "PRO" ? (
            <p className="text-xs text-[var(--ch-text-muted)]">This PDF covers all PRO properties; upload once from any PRO property.</p>
          ) : null}
        </div>
        <label className="inline-flex cursor-pointer items-center gap-2 rounded-md border border-[var(--ch-border)] bg-[var(--ch-surface)] px-3 py-2 text-sm font-medium">
          <Upload size={16} />
          {busy ? "Uploading..." : "Upload"}
          <input type="file" accept=".png,.jpg,.jpeg,.pdf" className="hidden" onChange={(event) => onFile(event.target.files?.[0])} />
        </label>
      </div>
      {error ? <p className="text-sm text-[var(--ch-error-text)]">{error}</p> : null}
      {upload ? (
        <ExtractionReviewCard
          upload={upload}
          facilityId={property.facility_id}
          onDiscard={() => setUpload(null)}
          onConfirm={async (docId, values) => {
            if (!property.facility_id) return;
            await confirmFacilityDocument(docId, property.facility_id, values);
            setUpload(null);
            await onUpdated();
          }}
        />
      ) : (
        <p className="text-xs text-[var(--ch-text-muted)]">Upload history will appear here after documents are attached to this facility.</p>
      )}
    </section>
  );
}
