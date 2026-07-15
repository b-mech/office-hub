import { useState } from "react";
import type { UploadResponse } from "@/types/financing";

export function ExtractionReviewCard({
  upload,
  facilityId,
  onConfirm,
  onDiscard,
}: {
  upload: UploadResponse;
  facilityId?: string | null;
  onConfirm: (docId: string, values: Record<string, unknown>) => Promise<void>;
  onDiscard: () => void;
}) {
  const [values, setValues] = useState<Record<string, unknown>>(upload.extracted);
  const [saving, setSaving] = useState(false);
  const entries = Object.entries(values).filter(([, value]) => typeof value !== "object" || value === null);

  async function confirm() {
    setSaving(true);
    try {
      await onConfirm(upload.doc_id, values);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="rounded-lg border border-[var(--ch-border)] bg-[var(--ch-surface)] p-4">
      <div className="mb-3 flex items-center justify-between gap-3">
        <h3 className="text-sm font-semibold">Extraction Review</h3>
        <span className={`rounded-full px-2 py-1 text-xs ${upload.requires_review ? "bg-[var(--ch-warning-bg)] text-[var(--ch-warning-text)]" : "bg-[var(--ch-success-bg)] text-[var(--ch-success-text)]"}`}>
          {upload.requires_review ? "Review needed" : "High confidence"}
        </span>
      </div>
      <div className="grid gap-2">
        {entries.map(([key, value]) => (
          <label key={key} className="text-xs font-medium text-[var(--ch-text-muted)]">
            {key.replaceAll("_", " ")}
            <input
              value={String(value ?? "")}
              onChange={(event) => setValues((current) => ({ ...current, [key]: event.target.value }))}
              className="mt-1 w-full rounded-md border border-[var(--ch-border)] bg-[var(--ch-surface-strong)] px-3 py-2 text-sm"
            />
          </label>
        ))}
      </div>
      {Array.isArray(upload.extracted.items) ? (
        <p className="mt-3 text-xs text-[var(--ch-text-muted)]">Bulk PRO rows were extracted. Confirm bulk values from the PRO review workflow before updating facilities.</p>
      ) : null}
      <div className="mt-4 flex justify-end gap-2">
        <button onClick={onDiscard} className="rounded-md border border-[var(--ch-border)] px-3 py-2 text-sm text-[var(--ch-text-secondary)]">Discard</button>
        <button
          onClick={confirm}
          disabled={saving || !facilityId}
          className="rounded-md bg-[var(--ch-accent)] px-3 py-2 text-sm font-semibold text-[var(--ch-accent-text)] disabled:opacity-60"
        >
          {saving ? "Saving..." : "Confirm & Save"}
        </button>
      </div>
    </div>
  );
}
