import { useState } from "react";
import { Upload } from "lucide-react";
import { confirmFacilityDocument, getLenderStatement, uploadFacilityDocument, uploadLenderStatement } from "@/lib/api/financing";
import type { FinancingProperty, LenderStatementDetail, UploadResponse } from "@/types/financing";
import { ExtractionReviewCard } from "./ExtractionReviewCard";
import { inferStatementPeriod } from "./statementPeriod";

export function DocumentUploadPanel({
  property,
  onUpdated,
}: {
  property: FinancingProperty;
  onUpdated: () => Promise<void>;
}) {
  const [upload, setUpload] = useState<UploadResponse | null>(null);
  const [statement, setStatement] = useState<LenderStatementDetail | null>(null);
  const [resultPropertyId, setResultPropertyId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onFile(file?: File) {
    if (!file) return;
    setBusy(true);
    setError(null);
    setUpload(null);
    setStatement(null);
    setResultPropertyId(property.property_id);
    try {
      if (property.lender_type === "PRO") {
        const period = inferStatementPeriod(file.name);
        const created = await uploadLenderStatement({ lender: "PRO", period, file });
        const detail = await getLenderStatement(created.id);
        setStatement(detail);
        await onUpdated();
        return;
      }
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
          <h3 className="text-sm font-semibold">{property.lender_type === "PRO" ? "PRO Portfolio Statement" : "Balance Documents"}</h3>
          {property.lender_type === "PRO" ? (
            <p className="text-xs text-[var(--ch-text-muted)]">Upload once; every matched PRO facility is imported and reconciled.</p>
          ) : null}
        </div>
        <label className="inline-flex cursor-pointer items-center gap-2 rounded-md border border-[var(--ch-border)] bg-[var(--ch-surface)] px-3 py-2 text-sm font-medium">
          <Upload size={16} />
          {busy ? "Uploading..." : "Upload"}
          <input type="file" accept={property.lender_type === "PRO" ? ".pdf,application/pdf" : ".png,.jpg,.jpeg,.pdf"} className="hidden" onChange={(event) => onFile(event.target.files?.[0])} />
        </label>
      </div>
      {error ? <p className="text-sm text-[var(--ch-error-text)]">{error}</p> : null}
      {statement && resultPropertyId === property.property_id ? (
        <div className="rounded-lg border border-[var(--ch-success-border)] bg-[var(--ch-success-bg)] p-3 text-sm text-[var(--ch-success-text)]">
          <p className="font-semibold">PRO {statement.period}: {statement.status}</p>
          <p className="mt-1 text-xs">{statement.snapshots.length} statement rows imported. Rows needing reconciliation are available in Statements.</p>
        </div>
      ) : upload && resultPropertyId === property.property_id ? (
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
        <p className="text-xs text-[var(--ch-text-muted)]">
          {property.lender_type === "PRO"
            ? "The month and year are read from the filename, for example Pro-Aug 2026.pdf."
            : "Upload history will appear here after documents are attached to this facility."}
        </p>
      )}
    </section>
  );
}
