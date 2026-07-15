import type { UploadResponse } from "@/types/financing";

export function ProBulkExtractionModal({
  upload,
  onClose,
}: {
  upload: UploadResponse | null;
  onClose: () => void;
}) {
  if (!upload || !Array.isArray(upload.extracted.items)) return null;
  return (
    <div className="fixed inset-0 z-50 bg-black/30 p-6" onClick={onClose}>
      <div className="mx-auto max-w-5xl rounded-lg border border-[var(--ch-border)] bg-[var(--ch-page-bg)] p-5" onClick={(event) => event.stopPropagation()}>
        <h2 className="text-lg font-semibold">PRO Bulk Extraction Review</h2>
        <p className="mt-1 text-sm text-[var(--ch-text-muted)]">Review and confirm extracted PRO rows after matching each address to a property.</p>
        <div className="mt-4 max-h-[60vh] overflow-auto rounded-lg border border-[var(--ch-border)] bg-[var(--ch-surface)]">
          <table className="min-w-full text-sm">
            <thead className="bg-[var(--ch-surface-muted)] text-xs uppercase text-[var(--ch-text-muted)]">
              <tr>
                <th className="px-3 py-2 text-left">Address</th>
                <th className="px-3 py-2 text-right">Commitment</th>
                <th className="px-3 py-2 text-right">Drawn</th>
                <th className="px-3 py-2 text-right">Opening</th>
                <th className="px-3 py-2 text-left">Match</th>
              </tr>
            </thead>
            <tbody>
              {(upload.extracted.items as Record<string, unknown>[]).map((item, index) => (
                <tr key={index} className="border-t border-[var(--ch-border)]">
                  <td className="px-3 py-2">{String(item.address || "")}</td>
                  <td className="px-3 py-2 text-right">{String(item.total_commitment || "")}</td>
                  <td className="px-3 py-2 text-right">{String(item.already_drawn || "")}</td>
                  <td className="px-3 py-2 text-right">{String(item.opening_balance || "")}</td>
                  <td className="px-3 py-2 text-[var(--ch-warning-text)]">Needs link</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="mt-4 flex justify-end">
          <button onClick={onClose} className="rounded-md bg-[var(--ch-accent)] px-4 py-2 text-sm font-semibold text-[var(--ch-accent-text)]">Close</button>
        </div>
      </div>
    </div>
  );
}
