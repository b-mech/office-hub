import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Copy, Upload } from "lucide-react";
import {
  confirmClientPrepDraw,
  getClientDrawRequests,
  getClientOtpSchedule,
  prepClientDraw,
  prepareOfficialOtpReview,
  reviewClientOtp,
  updateClientDrawRequestStatus,
  uploadClientOtp,
} from "@/lib/api/financing";
import type { ClientDrawRequest, ClientDrawSchedule, ClientPrepDrawPackage, FinancingProperty } from "@/types/financing";

const money = new Intl.NumberFormat("en-CA", { style: "currency", currency: "CAD", maximumFractionDigits: 0 });
const stageOptions = ["", "FOUNDATION", "LOCKUP", "DRYWALL", "CABINETRY", "COMPLETED"];

function num(value: unknown): number {
  const parsed = Number(value ?? 0);
  return Number.isFinite(parsed) ? parsed : 0;
}

function text(value: unknown): string {
  return value == null ? "" : String(value);
}

export function ClientOtpPanel({ property, onUpdated }: { property: FinancingProperty; onUpdated: () => Promise<void> }) {
  const router = useRouter();
  const [schedule, setSchedule] = useState<ClientDrawSchedule | null>(null);
  const [requests, setRequests] = useState<ClientDrawRequest[]>([]);
  const [prep, setPrep] = useState<ClientPrepDrawPackage | null>(null);
  const [reviewRows, setReviewRows] = useState<Array<Record<string, unknown>>>([]);
  const [purchasePrice, setPurchasePrice] = useState("");
  const [clientName, setClientName] = useState("");
  const [otpDate, setOtpDate] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [nowMs, setNowMs] = useState(() => Date.now());

  const reviewed = Boolean(schedule?.reviewed_at);
  const requestableTotal = num(prep?.requestable_total);
  const extractionStale = Boolean(
    schedule &&
    ["uploaded", "extracting"].includes(schedule.extraction_status) &&
    nowMs - new Date(schedule.created_at).getTime() > 10 * 60 * 1000,
  );

  const applySchedule = useCallback((next: ClientDrawSchedule | null) => {
    setSchedule(next);
    setReviewRows(next?.schedule ? next.schedule.map((row) => ({ ...row })) : []);
    setPurchasePrice(text(next?.purchase_price));
    setClientName(next?.client_name || property.client_name || "");
    setOtpDate(next?.otp_date || "");
  }, [property.client_name]);

  useEffect(() => {
    let active = true;
    Promise.all([getClientOtpSchedule(property.property_id), getClientDrawRequests(property.property_id)])
      .then(([nextSchedule, nextRequests]) => {
        if (!active) return;
        applySchedule(nextSchedule);
        setRequests(nextRequests);
        setPrep(null);
        setError(null);
      })
      .catch((err) => {
        if (active) setError(err instanceof Error ? err.message : "Could not load OTP schedule");
      });
    return () => {
      active = false;
    };
  }, [applySchedule, property.property_id]);

  useEffect(() => {
    if (!schedule || !["uploaded", "extracting"].includes(schedule.extraction_status)) return;
    if (Date.now() - new Date(schedule.created_at).getTime() > 10 * 60 * 1000) return;
    const timer = window.setTimeout(() => {
      setNowMs(Date.now());
      getClientOtpSchedule(property.property_id)
        .then((nextSchedule) => {
          applySchedule(nextSchedule);
        })
        .catch((err) => setError(err instanceof Error ? err.message : "Could not refresh OTP extraction status"));
    }, 3000);
    return () => window.clearTimeout(timer);
  }, [applySchedule, property.property_id, schedule]);

  async function upload(file: File | null) {
    if (!file) return;
    setBusy("upload");
    setError(null);
    try {
      applySchedule(await uploadClientOtp(property.property_id, file));
      setRequests(await getClientDrawRequests(property.property_id));
      await onUpdated();
    } catch (err) {
      setError(err instanceof Error ? err.message : "OTP upload failed");
    } finally {
      setBusy(null);
    }
  }

  async function saveReview() {
    if (!schedule) return;
    setBusy("review");
    setError(null);
    try {
      applySchedule(await reviewClientOtp(schedule.id, {
        purchase_price: purchasePrice || null,
        client_name: clientName || null,
        otp_date: otpDate || null,
        schedule: reviewRows,
        deposits: schedule.deposits,
      }));
      await onUpdated();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Review save failed");
    } finally {
      setBusy(null);
    }
  }

  async function prepDraw() {
    setBusy("prep");
    setError(null);
    try {
      const pkg = await prepClientDraw(property.property_id);
      setPrep(pkg);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not prep draw");
    } finally {
      setBusy(null);
    }
  }

  async function confirmPrep() {
    if (!prep || requestableTotal <= 0) return;
    setBusy("confirm");
    setError(null);
    try {
      await confirmClientPrepDraw(property.property_id, {
        draw_items: prep.requestable_items,
        amount: requestableTotal,
      });
      setRequests(await getClientDrawRequests(property.property_id));
      setPrep(await prepClientDraw(property.property_id));
      await onUpdated();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not mark prepared");
    } finally {
      setBusy(null);
    }
  }

  async function changeStatus(requestId: string, status: string) {
    setBusy(requestId);
    try {
      await updateClientDrawRequestStatus(requestId, status);
      setRequests(await getClientDrawRequests(property.property_id));
      setPrep(await prepClientDraw(property.property_id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not update draw request");
    } finally {
      setBusy(null);
    }
  }

  async function openOfficialReview() {
    if (!schedule) return;
    setBusy("official-review");
    setError(null);
    try {
      const result = await prepareOfficialOtpReview(schedule.id);
      router.push(`/documents/${result.document_id}`);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Could not prepare the official OTP review",
      );
      setBusy(null);
    }
  }

  function updateRow(index: number, key: string, value: string) {
    setReviewRows((rows) => rows.map((row, rowIndex) => rowIndex === index ? { ...row, [key]: value } : row));
  }

  const status = useMemo(() => {
    if (!schedule) return "OTP NEEDED";
    if (!reviewed) return "REVIEW NEEDED";
    if (prep?.status === "stage_unavailable") return "STAGE UNKNOWN";
    if (requestableTotal > 0) return "DRAW READY";
    return "NO DRAW DUE";
  }, [schedule, reviewed, prep?.status, requestableTotal]);

  return (
    <section id="prep-draw" className={`mb-4 scroll-mt-4 rounded-lg border p-4 ${property.lender_type === "CLIENT" ? "border-[var(--ch-warning-border)] bg-[var(--ch-surface)]" : "border-[var(--ch-border)] bg-[var(--ch-surface)]"}`}>
      <div className="mb-3 flex items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold">OTP Sale Draw Schedule</h3>
          <p className="mt-1 text-xs text-[var(--ch-text-muted)]">Upload, review, then prepare a lawyer draw note. Nothing is sent automatically.</p>
        </div>
        <span className="rounded-full bg-[var(--ch-surface-muted)] px-2 py-1 text-xs font-semibold text-[var(--ch-text-secondary)]">{status}</span>
      </div>

      {error ? <p className="mb-3 rounded-md bg-[var(--ch-error-bg)] px-3 py-2 text-sm text-[var(--ch-error-text)]">{error}</p> : null}

      <label className="mb-3 inline-flex cursor-pointer items-center gap-2 rounded-md border border-[var(--ch-border)] px-3 py-2 text-sm font-semibold hover:bg-[var(--ch-surface-hover)]">
        <Upload size={16} />
        {busy === "upload" ? "Uploading..." : schedule ? "Re-upload OTP" : "Upload OTP"}
        <input type="file" accept="application/pdf" className="hidden" onChange={(event) => upload(event.target.files?.[0] || null)} disabled={busy != null} />
      </label>

      {schedule ? (
        <div className="space-y-3">
          <div className="grid gap-3 sm:grid-cols-3">
            <Input label="Purchase price" value={purchasePrice} onChange={setPurchasePrice} />
            <Input label="Purchaser" value={clientName} onChange={setClientName} />
            <Input label="OTP date" value={otpDate} onChange={setOtpDate} />
          </div>
          <p className="text-xs text-[var(--ch-text-muted)]">
            Source: {schedule.original_filename || schedule.minio_object_key} · {schedule.extraction_status}
            {schedule.extraction_notes ? ` · ${schedule.extraction_notes}` : ""}
          </p>
          {["uploaded", "extracting"].includes(schedule.extraction_status) && !extractionStale ? (
            <p className="rounded-md bg-[var(--ch-info-bg)] px-3 py-2 text-sm text-[var(--ch-info-text)]">Extraction is running. You can keep working; this panel will refresh.</p>
          ) : null}
          {extractionStale ? (
            <p className="rounded-md bg-[var(--ch-warning-bg)] px-3 py-2 text-sm text-[var(--ch-warning-text)]">Extraction has not completed. Re-upload the OTP to retry; Office Hub will keep the prior record for history.</p>
          ) : null}
          <div className="overflow-x-auto">
            <table className="min-w-full text-xs">
              <thead className="text-[var(--ch-text-muted)]">
                <tr>{["#", "Milestone", "Stage", "Amount", "Page"].map((head) => <th key={head} className="px-2 py-2 text-left">{head}</th>)}</tr>
              </thead>
              <tbody>
                {reviewRows.map((row, index) => (
                  <tr key={index} className="border-t border-[var(--ch-border)]">
                    <td className="px-2 py-2">{text(row.seq || index + 1)}</td>
                    <td className="px-2 py-2">
                      <input value={text(row.label_raw)} onChange={(event) => updateRow(index, "label_raw", event.target.value)} className="w-56 rounded border border-[var(--ch-border)] bg-[var(--ch-surface)] px-2 py-1" />
                    </td>
                    <td className="px-2 py-2">
                      <select value={text(row.stage_key)} onChange={(event) => updateRow(index, "stage_key", event.target.value)} className="rounded border border-[var(--ch-border)] bg-[var(--ch-surface)] px-2 py-1">
                        {stageOptions.map((stage) => <option key={stage || "blank"} value={stage}>{stage || "Unmapped"}</option>)}
                      </select>
                    </td>
                    <td className="px-2 py-2"><input value={text(row.amount)} onChange={(event) => updateRow(index, "amount", event.target.value)} className="w-24 rounded border border-[var(--ch-border)] bg-[var(--ch-surface)] px-2 py-1 text-right" /></td>
                    <td className="px-2 py-2"><input value={text(row.source_page)} onChange={(event) => updateRow(index, "source_page", event.target.value)} className="w-16 rounded border border-[var(--ch-border)] bg-[var(--ch-surface)] px-2 py-1 text-right" /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <button type="button" onClick={saveReview} disabled={!schedule || busy != null} className="rounded-md bg-[var(--ch-accent)] px-3 py-2 text-sm font-semibold text-white disabled:opacity-50">
            {busy === "review" ? "Saving..." : reviewed ? "Update reviewed schedule" : "Confirm reviewed schedule"}
          </button>
          {reviewed ? (
            <div className="rounded-md border border-[var(--ch-warning-border)] bg-[var(--ch-warning-bg)] px-3 py-3 text-sm text-[var(--ch-warning-text)]">
              <p className="font-semibold">Official OTP approval required</p>
              <p className="mt-1 text-xs">
                Approve the staged OTP to create or update its Project, sale agreement,
                buyers, dates, and deposits across Office Hub.
              </p>
              <button
                type="button"
                onClick={openOfficialReview}
                disabled={busy != null}
                className="mt-2 inline-flex rounded-md bg-[var(--ch-accent)] px-3 py-2 text-xs font-semibold text-white"
              >
                {busy === "official-review"
                  ? "Preparing official review..."
                  : "Review & update Office Hub"}
              </button>
            </div>
          ) : null}
        </div>
      ) : null}

      <div className="mt-4 flex flex-wrap gap-2">
        <button type="button" onClick={prepDraw} disabled={busy != null} className="rounded-md border border-[var(--ch-border)] px-3 py-2 text-sm font-semibold hover:bg-[var(--ch-surface-hover)]">
          {busy === "prep" ? "Preparing..." : "Prep Draw"}
        </button>
        {prep?.requestable_items.length ? (
          <button type="button" onClick={confirmPrep} disabled={busy != null} className="rounded-md bg-[var(--ch-accent)] px-3 py-2 text-sm font-semibold text-white disabled:opacity-50">
            {busy === "confirm" ? "Marking..." : "Mark as prepared"}
          </button>
        ) : null}
      </div>

      {prep ? <PrepPackage prep={prep} /> : null}
      {prep?.lawyer_note ? <LawyerNote note={prep.lawyer_note} /> : null}

      {requests.length ? (
        <div className="mt-4">
          <h4 className="mb-2 text-xs font-semibold uppercase text-[var(--ch-text-muted)]">Prepared History</h4>
          <div className="space-y-2">
            {requests.map((request) => (
              <div key={request.id} className="rounded-md border border-[var(--ch-border)] p-3 text-xs">
                <div className="flex items-center justify-between gap-3">
                  <span>{money.format(num(request.amount))} · {request.status} · {new Date(request.prepared_at).toLocaleDateString()}</span>
                  <select value={request.status} onChange={(event) => changeStatus(request.id, event.target.value)} disabled={busy === request.id} className="rounded border border-[var(--ch-border)] bg-[var(--ch-surface)] px-2 py-1">
                    {["prepared", "sent_to_lawyer", "funded", "cancelled"].map((statusValue) => <option key={statusValue} value={statusValue}>{statusValue}</option>)}
                  </select>
                </div>
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </section>
  );
}

function Input({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  return (
    <label className="block text-xs text-[var(--ch-text-muted)]">
      {label}
      <input value={value} onChange={(event) => onChange(event.target.value)} className="mt-1 w-full rounded-md border border-[var(--ch-border)] bg-[var(--ch-surface)] px-2 py-1 text-sm text-[var(--ch-text-primary)]" />
    </label>
  );
}

function PrepPackage({ prep }: { prep: ClientPrepDrawPackage }) {
  return (
    <div className="mt-4 rounded-md bg-[var(--ch-surface-muted)] p-3">
      <div className="mb-2 flex items-center justify-between gap-3 text-sm">
        <span>Current stage: {prep.current_stage || "-"}</span>
        <strong>Requestable: {prep.requestable_total == null ? "-" : money.format(num(prep.requestable_total))}</strong>
      </div>
      {prep.eligibility_unavailable_reason ? <p className="mb-2 text-sm text-[var(--ch-warning-text)]">Eligibility unavailable: {prep.eligibility_unavailable_reason}</p> : null}
      <div className="overflow-x-auto">
        <table className="min-w-full text-xs">
          <thead className="text-[var(--ch-text-muted)]">
            <tr>{["Milestone", "Stage", "Amount", "Page", "Status"].map((head) => <th key={head} className="px-2 py-2 text-left">{head}</th>)}</tr>
          </thead>
          <tbody>
            {prep.schedule_table.map((row, index) => (
              <tr key={index} className="border-t border-[var(--ch-border)]">
                <td className="px-2 py-2">{text(row.label_raw)}</td>
                <td className="px-2 py-2">{text(row.stage_key) || "-"}</td>
                <td className="px-2 py-2 text-right">{money.format(num(row.amount))}</td>
                <td className="px-2 py-2 text-right">{text(row.source_page) || "-"}</td>
                <td className="px-2 py-2 font-semibold">{text(row.status)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function LawyerNote({ note }: { note: string }) {
  return (
    <div className="mt-3 rounded-md border border-[var(--ch-border)] p-3">
      <div className="mb-2 flex items-center justify-between gap-3">
        <h4 className="text-xs font-semibold uppercase text-[var(--ch-text-muted)]">Lawyer Note</h4>
        <button type="button" onClick={() => navigator.clipboard.writeText(note)} className="inline-flex items-center gap-1 rounded-md border border-[var(--ch-border)] px-2 py-1 text-xs font-semibold">
          <Copy size={13} /> Copy
        </button>
      </div>
      <p className="whitespace-pre-wrap text-sm text-[var(--ch-text-secondary)]">{note}</p>
    </div>
  );
}
