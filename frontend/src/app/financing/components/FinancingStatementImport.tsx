import { useRef, useState } from "react";
import { Upload } from "lucide-react";
import { getLenderStatement, uploadLenderStatement } from "@/lib/api/financing";
import type { LenderStatementDetail, LenderType } from "@/types/financing";
import { defaultStatementPeriod, inferStatementPeriod } from "./statementPeriod";

const lenders: LenderType[] = ["PRO"];

export function FinancingStatementImport({
  onImported,
  onStatement,
}: {
  onImported: () => Promise<void>;
  onStatement: (statement: LenderStatementDetail) => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [lender, setLender] = useState<LenderType>("PRO");
  const [period, setPeriod] = useState(defaultStatementPeriod());
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function onFile(file?: File, inferredPeriod?: string) {
    if (!file) return;
    setBusy(true);
    setError(null);
    setStatus("uploading");
    const uploadPeriod = inferredPeriod || period || inferStatementPeriod(file.name);
    setPeriod(uploadPeriod);
    try {
      setStatus("parsing");
      const statement = await uploadLenderStatement({ lender, period: uploadPeriod, file });
      const detail = await getLenderStatement(statement.id);
      setStatus(detail.status);
      onStatement(detail);
      await onImported();
    } catch (err) {
      setStatus("failed");
      setError(err instanceof Error ? err.message : "Statement import failed");
    } finally {
      setBusy(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  }

  return (
    <div className="flex flex-col items-end gap-2">
      <div className="flex flex-wrap items-center justify-end gap-2">
        <select
          value={lender}
          onChange={(event) => setLender(event.target.value as LenderType)}
          className="h-10 rounded-md border border-[var(--ch-border)] bg-[var(--ch-surface)] px-3 text-sm font-medium"
          aria-label="Lender"
        >
          {lenders.map((item) => (
            <option key={item} value={item}>{item}</option>
          ))}
        </select>
        <input
          value={period}
          onChange={(event) => setPeriod(event.target.value)}
          placeholder="YYYY-MM"
          className="h-10 w-28 rounded-md border border-[var(--ch-border)] bg-[var(--ch-surface)] px-3 text-sm"
          aria-label="Statement period"
        />
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          disabled={busy || !period}
          className="inline-flex h-10 items-center gap-2 rounded-md border border-[var(--ch-border)] bg-[var(--ch-surface)] px-3 text-sm font-semibold hover:bg-[var(--ch-surface-hover)] disabled:opacity-60"
        >
          <Upload size={16} />
          {busy ? "Importing..." : "Import PDF"}
        </button>
        <input
          ref={inputRef}
          type="file"
          accept=".pdf,application/pdf"
          className="hidden"
          onChange={(event) => {
            const file = event.target.files?.[0];
            const inferred = file ? inferStatementPeriod(file.name) : period;
            setPeriod(inferred);
            onFile(file, inferred);
          }}
        />
      </div>
      {status ? <p className="text-xs text-[var(--ch-text-muted)]">Statement status: {status}</p> : null}
      {error ? <p className="max-w-sm text-right text-xs text-[var(--ch-error-text)]">{error}</p> : null}
    </div>
  );
}
