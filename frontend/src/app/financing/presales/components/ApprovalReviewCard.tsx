"use client";

import { useMemo, useState } from "react";

import {
  CONDITION_CATEGORIES,
  presaleFileUrl,
  presalesApi,
  type ApprovalCondition,
  type ApprovalLetter,
  type LotOption,
  type ReadinessResult,
} from "@/lib/api/presales";

const FIELD_DEFINITIONS = [
  ["document_type", "Document type", "select"],
  ["lender_name", "Lender", "text"],
  ["broker_name", "Broker", "text"],
  ["broker_email", "Broker email", "email"],
  ["property_address", "Property address", "text"],
  ["approved_amount", "Approved amount", "number"],
  ["purchase_price", "Purchase price", "number"],
  ["expiry_date", "Expiry date", "date"],
] as const;

const REVIEW_FIELD_NAMES = new Set<string>([
  ...FIELD_DEFINITIONS.map(([name]) => name),
  "purchaser_names",
  "signed",
  "conditions",
]);

export function ApprovalReviewCard({
  initialLetter,
  lots,
  readiness,
  onChanged,
}: {
  initialLetter: ApprovalLetter;
  lots: LotOption[];
  readiness?: ReadinessResult;
  onChanged: () => Promise<void>;
}) {
  const [letter, setLetter] = useState(initialLetter);
  const [extracted, setExtracted] = useState<Record<string, unknown>>({ ...initialLetter.extracted });
  const [qualityScore, setQualityScore] = useState(initialLetter.quality_score?.toString() || "");
  const [lotId, setLotId] = useState(
    initialLetter.lot_id || findExactLotId(lots, initialLetter.extracted.property_address) || "",
  );
  const [contactNotes, setContactNotes] = useState(initialLetter.lender_contact_notes || "");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const selectedLot = useMemo(() => lots.find((lot) => lot.id === lotId), [lotId, lots]);
  const willMarkAsPresale = Boolean(selectedLot && !selectedLot.is_presale);

  const conditions = useMemo(
    () => Array.isArray(extracted.conditions) ? extracted.conditions as ApprovalCondition[] : [],
    [extracted.conditions],
  );
  const disqualifiedCategories = useMemo(
    () => new Set(Object.values(readiness?.partners || {}).flatMap((partner) => partner.disqualified_by.map((item) => item.category))),
    [readiness],
  );
  const visibleLowConfidenceCount = letter.low_confidence_fields.filter((field) => REVIEW_FIELD_NAMES.has(field)).length;
  const approvalBlocker = !lotId
    ? "Select a lot above before approving."
    : !qualityScore
      ? "Enter a quality score before approving."
      : null;

  function setField(name: string, value: unknown) {
    setExtracted((current) => ({ ...current, [name]: value }));
  }

  function updateCondition(index: number, update: Partial<ApprovalCondition>) {
    setField("conditions", conditions.map((condition, itemIndex) => itemIndex === index ? { ...condition, ...update } : condition));
  }

  async function run(action: string, operation: () => Promise<unknown>) {
    setBusy(action);
    setError(null);
    try {
      await operation();
      await onChanged();
    } catch (actionError) {
      setError(actionError instanceof Error ? actionError.message : "Action failed");
    } finally {
      setBusy(null);
    }
  }

  async function save() {
    await run("save", async () => {
      const updated = await presalesApi.updateLetter(letter.id, {
        lot_id: lotId || null,
        mark_as_presale: willMarkAsPresale,
        extracted,
        quality_score: qualityScore ? Number(qualityScore) : null,
      });
      setLetter(updated);
    });
  }

  return (
    <article className="overflow-hidden rounded-xl border border-[var(--ch-border)] bg-[var(--ch-surface)]">
      <header className="flex flex-wrap items-start justify-between gap-3 border-b border-[var(--ch-border)] px-5 py-4">
        <div>
          <h2 className="font-semibold text-[var(--ch-text-primary)]">
            Presale approval letter — {lots.find((lot) => lot.id === lotId)?.address || "Unmatched"}
          </h2>
          <p className="mt-1 text-xs text-[var(--ch-text-muted)]">
            {letter.email_from || "Unknown sender"} · {letter.original_filename || "approval.pdf"} · version {letter.version}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {letter.needs_manual_entry ? <Badge tone="warning">Needs manual entry</Badge> : null}
          {visibleLowConfidenceCount ? <Badge tone="warning">{visibleLowConfidenceCount} low-confidence</Badge> : null}
          <Badge tone="neutral">{conditions.length} conditions</Badge>
        </div>
      </header>

      <div className="grid min-h-[560px] lg:grid-cols-[minmax(320px,0.9fr)_minmax(480px,1.1fr)]">
        <div className="border-b border-[var(--ch-border)] bg-[var(--ch-page-bg)] lg:border-b-0 lg:border-r">
          {letter.preview_url ? (
            <iframe title="Approval letter PDF" src={`${presaleFileUrl(letter)}#view=FitH`} className="h-[560px] w-full" />
          ) : (
            <div className="grid h-[560px] place-items-center text-sm text-[var(--ch-text-muted)]">PDF unavailable</div>
          )}
        </div>

        <div className="space-y-5 p-5">
          <label className="block text-xs font-medium text-[var(--ch-text-secondary)]">
            Lot
            <select value={lotId} onChange={(event) => setLotId(event.target.value)} className="mt-1.5 w-full rounded-lg border border-[var(--ch-border)] bg-[var(--ch-page-bg)] px-3 py-2 text-sm">
              <option value="">Unmatched — hold for review</option>
              {lots.map((lot) => <option key={lot.id} value={lot.id}>{lot.address} · {lot.purchaser_names.join(", ") || "No purchaser"}{lot.is_presale ? "" : " · Not marked presale"}</option>)}
            </select>
            {willMarkAsPresale ? <span className="mt-1.5 block text-[var(--ch-warning-text)]">This will link the letter and mark the lot as presale.</span> : null}
          </label>

          <div className="grid gap-3 sm:grid-cols-2">
            {FIELD_DEFINITIONS.map(([name, label, type]) => {
              const low = letter.low_confidence_fields.includes(name) || Number(letter.extraction_confidence[name] ?? 1) < 0.75;
              return (
                <label key={name} className={`block rounded-lg border p-2 ${low ? "border-[var(--ch-warning-border)] bg-[var(--ch-warning-bg)]" : "border-transparent"}`}>
                  <span className="text-xs font-medium text-[var(--ch-text-secondary)]">{label}{low ? " · check" : ""}</span>
                  {type === "select" ? (
                    <select value={String(extracted[name] ?? "other")} onChange={(event) => setField(name, event.target.value)} className="mt-1 w-full rounded-md border border-[var(--ch-border)] bg-[var(--ch-page-bg)] px-2 py-1.5 text-sm">
                      <option value="pre_approval">Pre-approval</option><option value="firm_commitment">Firm commitment</option><option value="other">Other</option>
                    </select>
                  ) : (
                    <input type={type} value={String(extracted[name] ?? "")} onChange={(event) => setField(name, event.target.value)} className="mt-1 w-full rounded-md border border-[var(--ch-border)] bg-[var(--ch-page-bg)] px-2 py-1.5 text-sm" />
                  )}
                </label>
              );
            })}
            <label className="block rounded-lg border border-transparent p-2">
              <span className="text-xs font-medium text-[var(--ch-text-secondary)]">Purchasers (comma separated)</span>
              <input value={Array.isArray(extracted.purchaser_names) ? extracted.purchaser_names.join(", ") : ""} onChange={(event) => setField("purchaser_names", event.target.value.split(",").map((value) => value.trim()).filter(Boolean))} className="mt-1 w-full rounded-md border border-[var(--ch-border)] bg-[var(--ch-page-bg)] px-2 py-1.5 text-sm" />
            </label>
            <label className="flex items-center gap-2 self-end rounded-lg p-2 text-sm text-[var(--ch-text-secondary)]">
              <input type="checkbox" checked={Boolean(extracted.signed)} onChange={(event) => setField("signed", event.target.checked)} /> Signed
            </label>
          </div>

          <section>
            <div className="mb-2 flex items-center justify-between">
              <h3 className="text-sm font-semibold">Conditions</h3>
              <button type="button" onClick={() => setField("conditions", [...conditions, { text: "", category: "other", deadline: null }])} className="text-xs font-semibold text-[var(--ch-accent)]">Add condition</button>
            </div>
            <div className="space-y-2">
              {conditions.length === 0 ? <p className="text-xs text-[var(--ch-text-muted)]">No conditions extracted.</p> : null}
              {conditions.map((condition, index) => {
                const disqualifying = disqualifiedCategories.has(condition.category);
                return (
                  <div key={index} className={`grid gap-2 rounded-lg border p-3 md:grid-cols-[1fr_190px_135px_auto] ${disqualifying ? "border-[var(--ch-error-border)] bg-[var(--ch-error-bg)]" : condition.category === "other" ? "border-[var(--ch-warning-border)] bg-[var(--ch-warning-bg)]" : "border-[var(--ch-border)]"}`}>
                    <textarea value={condition.text} onChange={(event) => updateCondition(index, { text: event.target.value })} rows={2} className="rounded-md border border-[var(--ch-border)] bg-[var(--ch-page-bg)] px-2 py-1.5 text-sm" />
                    <select value={condition.category} onChange={(event) => updateCondition(index, { category: event.target.value as ApprovalCondition["category"] })} className="rounded-md border border-[var(--ch-border)] bg-[var(--ch-page-bg)] px-2 py-1.5 text-xs">
                      {CONDITION_CATEGORIES.map((category) => <option key={category} value={category}>{category.replaceAll("_", " ")}</option>)}
                    </select>
                    <input type="date" value={condition.deadline || ""} onChange={(event) => updateCondition(index, { deadline: event.target.value || null })} className="rounded-md border border-[var(--ch-border)] bg-[var(--ch-page-bg)] px-2 py-1.5 text-xs" />
                    <button type="button" onClick={() => setField("conditions", conditions.filter((_, itemIndex) => itemIndex !== index))} className="text-xs text-[var(--ch-error-text)]">Remove</button>
                  </div>
                );
              })}
            </div>
          </section>

          <div className="grid gap-3 sm:grid-cols-2">
            <label className="block text-xs font-semibold text-[var(--ch-text-secondary)]">Quality score /10 (required)
              <input type="number" min={1} max={10} value={qualityScore} onChange={(event) => setQualityScore(event.target.value)} className="mt-1.5 w-full rounded-lg border border-[var(--ch-border)] bg-[var(--ch-page-bg)] px-3 py-2 text-sm" />
            </label>
            <label className="block text-xs font-semibold text-[var(--ch-text-secondary)]">Lender contact notes
              <input value={contactNotes} onChange={(event) => setContactNotes(event.target.value)} className="mt-1.5 w-full rounded-lg border border-[var(--ch-border)] bg-[var(--ch-page-bg)] px-3 py-2 text-sm" />
            </label>
          </div>

          {readiness ? <ReadinessPreview readiness={readiness} /> : null}
          {error ? <p className="rounded-lg border border-[var(--ch-error-border)] bg-[var(--ch-error-bg)] px-3 py-2 text-sm text-[var(--ch-error-text)]">{error}</p> : null}

          <div className="flex flex-wrap justify-end gap-2 border-t border-[var(--ch-border)] pt-4">
            {approvalBlocker ? <p className="mr-auto self-center text-xs font-medium text-[var(--ch-warning-text)]">{approvalBlocker}</p> : null}
            <button type="button" disabled={Boolean(busy)} onClick={() => run("contact", async () => { const updated = await presalesApi.contactLender(letter.id, contactNotes); setLetter(updated); })} className="rounded-lg border border-[var(--ch-border)] px-3 py-2 text-sm disabled:opacity-50">{busy === "contact" ? "Saving…" : letter.lender_contacted_at ? "Update lender note" : "Contacted lender"}</button>
            <button type="button" disabled={Boolean(busy)} onClick={() => { const reason = window.prompt("Reason for rejecting this letter?"); if (reason) void run("reject", () => presalesApi.rejectLetter(letter.id, reason)); }} className="rounded-lg border border-[var(--ch-error-border)] px-3 py-2 text-sm text-[var(--ch-error-text)] disabled:opacity-50">Reject</button>
            <button type="button" disabled={Boolean(busy)} onClick={() => void save()} className="rounded-lg border border-[var(--ch-border-strong)] px-4 py-2 text-sm disabled:opacity-50">{busy === "save" ? "Saving…" : willMarkAsPresale ? "Link and mark as presale" : "Save edits"}</button>
            <button type="button" title={approvalBlocker || undefined} disabled={Boolean(busy) || Boolean(approvalBlocker)} onClick={() => run("approve", async () => { await presalesApi.updateLetter(letter.id, { lot_id: lotId, mark_as_presale: willMarkAsPresale, extracted, quality_score: Number(qualityScore) }); await presalesApi.approveLetter(letter.id); })} className="rounded-lg bg-[var(--ch-accent)] px-4 py-2 text-sm font-semibold text-[var(--ch-accent-text)] disabled:cursor-not-allowed disabled:opacity-45">{busy === "approve" ? "Approving…" : willMarkAsPresale ? "Mark presale & approve" : "Approve"}</button>
          </div>
        </div>
      </div>
    </article>
  );
}

function ReadinessPreview({ readiness }: { readiness: ReadinessResult }) {
  return (
    <section className="rounded-lg border border-[var(--ch-border)] p-3">
      <div className="flex items-center justify-between"><h3 className="text-sm font-semibold">Readiness preview</h3><span className="text-xs text-[var(--ch-text-muted)]">Suggested: {readiness.suggested || "Not fundable yet"}</span></div>
      <div className="mt-2 grid gap-2 sm:grid-cols-2">
        {Object.entries(readiness.partners).map(([code, partner]) => (
          <div key={code} className="rounded-md bg-[var(--ch-page-bg)] p-2 text-xs">
            <div className="flex justify-between"><strong>{code}</strong><span>{partner.state.replaceAll("_", " ")}</span></div>
            {partner.missing.length ? <p className="mt-1 text-[var(--ch-text-muted)]">Missing: {partner.missing.join(", ")}</p> : null}
            {partner.disqualified_by.length ? <p className="mt-1 text-[var(--ch-error-text)]">{partner.disqualified_by.map((item) => item.text).join("; ")}</p> : null}
          </div>
        ))}
      </div>
    </section>
  );
}

function Badge({ children, tone }: { children: React.ReactNode; tone: "warning" | "neutral" }) {
  return <span className={`rounded-full border px-2 py-1 text-[11px] font-semibold ${tone === "warning" ? "border-[var(--ch-warning-border)] bg-[var(--ch-warning-bg)] text-[var(--ch-warning-text)]" : "border-[var(--ch-border)] text-[var(--ch-text-muted)]"}`}>{children}</span>;
}

function normalizeAddress(value: string) {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
}

function findExactLotId(lots: LotOption[], address: unknown) {
  const propertyAddress = normalizeAddress(String(address || ""));
  if (!propertyAddress) return undefined;
  return lots.find((lot) => normalizeAddress(lot.address) === propertyAddress)?.id;
}
