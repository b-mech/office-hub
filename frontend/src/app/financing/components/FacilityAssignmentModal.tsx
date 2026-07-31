import { X } from "lucide-react";
import { assignPropertyFacility } from "@/lib/api/financing";
import type { FacilityAssignmentPayload, FinancingProperty } from "@/types/financing";
import { LenderFacilityForm } from "./LenderFacilityForm";

export function FacilityAssignmentModal({
  property,
  onClose,
  onAssigned,
}: {
  property: FinancingProperty;
  onClose: () => void;
  onAssigned: () => Promise<void>;
}) {
  async function assign(payload: FacilityAssignmentPayload) {
    await assignPropertyFacility(property.property_id, payload);
    await onAssigned();
    onClose();
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <section
        role="dialog"
        aria-modal="true"
        aria-labelledby="facility-assignment-title"
        className="max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-xl border border-[var(--ch-border)] bg-[var(--ch-page-bg)] p-5 shadow-2xl"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="mb-4 flex items-start justify-between gap-4">
          <div>
            <h2 id="facility-assignment-title" className="text-lg font-semibold">Assign lender facility</h2>
            <p className="mt-1 text-sm text-[var(--ch-text-muted)]">{property.address}</p>
          </div>
          <button type="button" onClick={onClose} aria-label="Close assignment form" className="rounded-md p-2 text-[var(--ch-text-muted)] hover:bg-[var(--ch-surface-hover)]">
            <X size={18} />
          </button>
        </div>
        <LenderFacilityForm
          property={property}
          mode="assignment"
          onAssign={assign}
          onCancel={onClose}
        />
      </section>
    </div>
  );
}
