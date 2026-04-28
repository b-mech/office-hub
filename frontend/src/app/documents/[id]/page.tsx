"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import {
  type DocumentDetail,
  type ReviewResponse,
  getDocument,
  getDocumentPdfUrl,
  submitReview,
} from "@/lib/api";

type ScalarValue = string | number | null;
type AgreementFields = Record<string, ScalarValue>;
type SecurityDepositFields = Record<string, ScalarValue>;
type LotFields = Record<string, ScalarValue>;
type ClauseFields = Record<string, ScalarValue>;

type ReviewPayload = {
  agreement: AgreementFields;
  security_deposit: SecurityDepositFields;
  lots: LotFields[];
  notable_clauses: ClauseFields[];
};

const agreementFieldLabels: Array<[string, string]> = [
  ["agreement_date", "Agreement Date"],
  ["vendor_name", "Vendor Name"],
  ["vendor_address", "Vendor Address"],
  ["vendor_attention", "Vendor Attention"],
  ["purchaser_name", "Purchaser Name"],
  ["development_name", "Development Name"],
  ["lot_draw_label", "Lot Draw Label"],
  ["interest_rate", "Interest Rate"],
  ["interest_type", "Interest Type"],
  ["interest_terms_text", "Interest Terms Text"],
  ["balance_due_rule", "Balance Due Rule"],
  ["interest_free_from", "Interest Free From"],
  ["total_purchase_price", "Total Purchase Price"],
  ["municipality", "Municipality"],
  ["gst_registration", "GST Registration"],
];

const securityDepositFields: Array<[string, string]> = [
  ["rate_per_lot", "Rate Per Lot"],
  ["maximum_amount", "Maximum Amount"],
  ["due_trigger", "Due Trigger"],
];

const lotFieldLabels: Array<[string, string]> = [
  ["block", "Block"],
  ["lot_number", "Lot Number"],
  ["plan", "Plan"],
  ["purchase_price", "Purchase Price"],
  ["deposit_1_amount", "Deposit 1 Amount"],
  ["deposit_2_amount", "Deposit 2 Amount"],
  ["deposit_2_due_date", "Deposit 2 Due Date"],
];

function getStatusBadge(status: string): string {
  if (status === "approved") {
    return "bg-emerald-100 text-emerald-800 ring-emerald-200";
  }
  if (status === "rejected") {
    return "bg-rose-100 text-rose-800 ring-rose-200";
  }
  if (status === "in_review") {
    return "bg-amber-100 text-amber-800 ring-amber-200";
  }
  return "bg-slate-100 text-slate-700 ring-slate-200";
}

function createDefaultPayload(detail: DocumentDetail | null): ReviewPayload {
  const payload = detail?.extraction?.extracted_payload;
  return {
    agreement: { ...(payload?.agreement || {}) },
    security_deposit: { ...(payload?.security_deposit || {}) },
    lots: [...(payload?.lots || [])],
    notable_clauses: [...(payload?.notable_clauses || [])],
  };
}

export default function DocumentReviewPage() {
  const params = useParams<{ id: string }>();
  const documentId = params.id;
  const panelRef = useRef<HTMLDivElement | null>(null);

  const [detail, setDetail] = useState<DocumentDetail | null>(null);
  const [reviewedPayload, setReviewedPayload] = useState<ReviewPayload>(
    createDefaultPayload(null),
  );
  const [editedFields, setEditedFields] = useState<string[]>([]);
  const [openLots, setOpenLots] = useState<Record<number, boolean>>({});
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<ReviewResponse | null>(null);
  const [showRejectForm, setShowRejectForm] = useState(false);
  const [rejectionReason, setRejectionReason] = useState("");
  const [hasScrolledToEnd, setHasScrolledToEnd] = useState(false);

  useEffect(() => {
    let cancelled = false;

    async function loadDocument() {
      setLoading(true);
      setError(null);
      setSuccess(null);
      try {
        const result = await getDocument(documentId);
        if (cancelled) {
          return;
        }

        setDetail(result);
        setReviewedPayload(createDefaultPayload(result));
        setEditedFields([]);
        setOpenLots(
          Object.fromEntries((result.extraction?.extracted_payload.lots || []).map((_, index) => [index, true])),
        );
      } catch (loadError) {
        if (!cancelled) {
          setError(
            loadError instanceof Error ? loadError.message : "Failed to load document.",
          );
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    void loadDocument();
    return () => {
      cancelled = true;
    };
  }, [documentId]);

  useEffect(() => {
    const element = panelRef.current;
    if (!element) {
      return;
    }

    const checkScrollState = () => {
      setHasScrolledToEnd(
        element.scrollHeight <= element.clientHeight + element.scrollTop + 24,
      );
    };

    checkScrollState();
  }, [detail, reviewedPayload]);

  function markEdited(path: string) {
    setEditedFields((current) =>
      current.includes(path) ? current : [...current, path],
    );
  }

  function getConfidence(path: string): number {
    const score = detail?.extraction?.field_confidences[path];
    return typeof score === "number" ? score : 1;
  }

  function isLowConfidence(path: string): boolean {
    return getConfidence(path) < 0.7;
  }

  function updateAgreementField(field: string, value: string) {
    setReviewedPayload((current) => ({
      ...current,
      agreement: {
        ...current.agreement,
        [field]: value || null,
      },
    }));
    markEdited(`agreement.${field}`);
  }

  function updateSecurityDepositField(field: string, value: string) {
    setReviewedPayload((current) => ({
      ...current,
      security_deposit: {
        ...current.security_deposit,
        [field]: value || null,
      },
    }));
    markEdited(`security_deposit.${field}`);
  }

  function updateLotField(index: number, field: string, value: string) {
    setReviewedPayload((current) => ({
      ...current,
      lots: current.lots.map((lot, lotIndex) =>
        lotIndex === index
          ? {
              ...lot,
              [field]: value || null,
            }
          : lot,
      ),
    }));
    markEdited(`lots.${index}.${field}`);
  }

  async function handleSubmit(decision: "approved" | "rejected" | "deferred") {
    if (!detail) {
      return;
    }

    if (decision === "rejected" && !rejectionReason.trim()) {
      setError("Rejection reason is required.");
      return;
    }

    setSubmitting(true);
    setError(null);

    try {
      const response = await submitReview(detail.document.id, {
        reviewed_payload: reviewedPayload,
        edited_fields: editedFields,
        decision,
        rejection_reason:
          decision === "rejected" ? rejectionReason.trim() : undefined,
      });

      setSuccess(response);
      setDetail((current) =>
        current
          ? {
              ...current,
              document: {
                ...current.document,
                status:
                  decision === "approved"
                    ? "approved"
                    : decision === "rejected"
                      ? "rejected"
                      : "in_review",
              },
            }
          : current,
      );
      if (decision === "rejected") {
        setShowRejectForm(false);
      }
    } catch (submitError) {
      setError(
        submitError instanceof Error ? submitError.message : "Failed to submit review.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  if (loading) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-[linear-gradient(135deg,_#f2ede6,_#e4ddd0)]">
        <div className="flex items-center gap-3 rounded-full border border-stone-300 bg-white/80 px-5 py-3 text-sm font-medium text-stone-700 shadow-lg backdrop-blur">
          <span className="h-4 w-4 animate-spin rounded-full border-2 border-stone-300 border-t-stone-700" />
          Loading review workspace
        </div>
      </main>
    );
  }

  if (error && !detail) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-[linear-gradient(135deg,_#f2ede6,_#e4ddd0)] px-6">
        <div className="max-w-xl rounded-[2rem] border border-rose-200 bg-white px-6 py-8 shadow-xl">
          <p className="text-sm font-semibold uppercase tracking-[0.2em] text-rose-500">
            Review Error
          </p>
          <h1 className="mt-3 text-2xl font-semibold text-stone-950">
            Could not open this document.
          </h1>
          <p className="mt-3 text-sm leading-6 text-stone-600">{error}</p>
          <Link
            href="/documents"
            className="mt-6 inline-flex rounded-full bg-stone-900 px-5 py-3 text-sm font-semibold text-white transition hover:bg-stone-700"
          >
            Back to documents
          </Link>
        </div>
      </main>
    );
  }

  const filename = detail?.document.original_filename || "Untitled document";
  const pdfUrl = getDocumentPdfUrl(documentId);

  return (
    <main className="h-screen bg-[linear-gradient(135deg,_#efe9df,_#dad0c1)] p-3 text-stone-900 sm:p-4">
      <div className="grid h-full gap-3 lg:grid-cols-[1.1fr_0.9fr]">
        <section className="min-h-[42vh] min-w-0 overflow-hidden rounded-[2rem] border border-stone-300/70 bg-stone-950 shadow-[0_30px_80px_rgba(44,28,15,0.35)]">
          <div className="flex h-full flex-col">
            <div className="flex items-center justify-between border-b border-white/10 px-5 py-4 text-white">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.22em] text-stone-400">
                  Source PDF
                </p>
                <h2 className="mt-1 text-lg font-semibold">{filename}</h2>
              </div>
              <Link
                href="/documents"
                className="rounded-full border border-white/15 px-4 py-2 text-xs font-semibold uppercase tracking-[0.18em] text-stone-200 transition hover:border-white/40 hover:bg-white/10"
              >
                Back
              </Link>
            </div>
            <div className="min-h-0 min-w-0 flex-1 overflow-auto">
              <iframe
                title="Document PDF Viewer"
                src={pdfUrl}
                className="h-full w-full bg-white"
                style={{ minHeight: "100%", minWidth: 0, display: "block" }}
              />
            </div>
          </div>
        </section>

        <section className="flex h-full min-h-[52vh] flex-col overflow-hidden rounded-[2rem] border border-stone-300/70 bg-white/92 shadow-[0_30px_80px_rgba(73,56,36,0.16)] backdrop-blur">
          <div
            ref={panelRef}
            onScroll={(event) => {
              const target = event.currentTarget;
              setHasScrolledToEnd(
                target.scrollHeight <= target.clientHeight + target.scrollTop + 24,
              );
            }}
            className="min-h-0 flex-1 overflow-y-auto"
          >
            <div className="border-b border-stone-200/80 px-6 py-6">
              <p className="text-xs font-semibold uppercase tracking-[0.24em] text-stone-500">
                Review Workspace
              </p>
              <div className="mt-3 flex flex-wrap items-center gap-3">
                <h1 className="text-2xl font-semibold tracking-tight text-stone-950">
                  {filename}
                </h1>
                <span
                  className={`inline-flex rounded-full px-3 py-1 text-xs font-semibold ring-1 ${getStatusBadge(detail?.document.status || "received")}`}
                >
                  {detail?.document.status.replaceAll("_", " ")}
                </span>
                <span className="rounded-full bg-stone-100 px-3 py-1 text-xs font-semibold uppercase tracking-[0.18em] text-stone-600">
                  {detail?.document.doc_type.replaceAll("_", " ")}
                </span>
              </div>
              <div className="mt-4 grid gap-2 text-sm text-stone-600 sm:grid-cols-2">
                <p>OCR method: {detail?.ingestion?.ocr_method || "Not available"}</p>
                <p>
                  OCR confidence:{" "}
                  {detail?.ingestion?.ocr_confidence != null
                    ? Number(detail.ingestion.ocr_confidence).toFixed(3)
                    : "Not available"}
                </p>
              </div>
              {success?.promotion ? (
                <div className="mt-5 rounded-[1.4rem] border border-emerald-200 bg-emerald-50 px-5 py-4 text-sm text-emerald-800">
                  <p className="font-semibold">Promotion completed successfully.</p>
                  <p className="mt-2">
                    Lots created: {success.promotion.lots_created} | Lots matched:{" "}
                    {success.promotion.lots_matched}
                  </p>
                  <p className="mt-1 break-all">
                    Agreement ID: {success.promotion.agreement_id}
                  </p>
                  <Link
                    href="/documents"
                    className="mt-4 inline-flex rounded-full bg-emerald-700 px-4 py-2 text-xs font-semibold uppercase tracking-[0.18em] text-white transition hover:bg-emerald-600"
                  >
                    Return to queue
                  </Link>
                </div>
              ) : null}
              {error ? (
                <div className="mt-5 rounded-[1.4rem] border border-rose-200 bg-rose-50 px-5 py-4 text-sm text-rose-700">
                  {error}
                </div>
              ) : null}
            </div>

            <div className="space-y-5 px-4 py-5 sm:px-5">
              <section className="rounded-[1.6rem] border border-stone-200 bg-stone-50/80 p-5">
                <div className="mb-4 flex items-center justify-between">
                  <div>
                    <p className="text-xs font-semibold uppercase tracking-[0.22em] text-stone-500">
                      1. Agreement Fields
                    </p>
                    <h2 className="mt-1 text-lg font-semibold text-stone-950">
                      Agreement-level extraction
                    </h2>
                  </div>
                </div>
                <div className="grid gap-4">
                  {agreementFieldLabels.map(([field, label]) => {
                    const path = `agreement.${field}`;
                    const lowConfidence = isLowConfidence(path);
                    return (
                      <label
                        key={field}
                        className={`rounded-[1.2rem] border px-4 py-3 ${lowConfidence ? "border-amber-300 bg-amber-50" : "border-stone-200 bg-white"}`}
                      >
                        <div className="mb-2 flex items-center justify-between gap-4">
                          <span className="text-sm font-semibold text-stone-800">
                            {label}
                          </span>
                          <span
                            className={`text-xs font-semibold ${lowConfidence ? "text-amber-700" : "text-stone-400"}`}
                          >
                            {lowConfidence
                              ? `Warning ${Math.round(getConfidence(path) * 100)}% confidence`
                              : `${Math.round(getConfidence(path) * 100)}% confidence`}
                          </span>
                        </div>
                        <input
                          value={String(reviewedPayload.agreement[field] ?? "")}
                          onChange={(event) =>
                            updateAgreementField(field, event.target.value)
                          }
                          className="w-full rounded-xl border border-stone-200 bg-white px-3 py-2 text-sm text-stone-900 outline-none transition focus:border-stone-500"
                        />
                      </label>
                    );
                  })}
                </div>
              </section>

              <section className="rounded-[1.6rem] border border-stone-200 bg-stone-50/80 p-5">
                <p className="text-xs font-semibold uppercase tracking-[0.22em] text-stone-500">
                  2. Security Deposit
                </p>
                <div className="mt-4 grid gap-4 sm:grid-cols-3">
                  {securityDepositFields.map(([field, label]) => {
                    const path = `security_deposit.${field}`;
                    const lowConfidence = isLowConfidence(path);
                    return (
                      <label
                        key={field}
                        className={`rounded-[1.2rem] border px-4 py-3 ${lowConfidence ? "border-amber-300 bg-amber-50" : "border-stone-200 bg-white"}`}
                      >
                        <div className="mb-2 flex items-center justify-between gap-4">
                          <span className="text-sm font-semibold text-stone-800">
                            {label}
                          </span>
                          <span
                            className={`text-xs font-semibold ${lowConfidence ? "text-amber-700" : "text-stone-400"}`}
                          >
                            {Math.round(getConfidence(path) * 100)}%
                          </span>
                        </div>
                        <input
                          value={String(reviewedPayload.security_deposit[field] ?? "")}
                          onChange={(event) =>
                            updateSecurityDepositField(field, event.target.value)
                          }
                          className="w-full rounded-xl border border-stone-200 bg-white px-3 py-2 text-sm text-stone-900 outline-none transition focus:border-stone-500"
                        />
                      </label>
                    );
                  })}
                </div>
              </section>

              <section className="rounded-[1.6rem] border border-stone-200 bg-stone-50/80 p-5">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-xs font-semibold uppercase tracking-[0.22em] text-stone-500">
                      3. Lots
                    </p>
                    <h2 className="mt-1 text-lg font-semibold text-stone-950">
                      Lot schedule review
                    </h2>
                  </div>
                  <span className="rounded-full bg-stone-900 px-3 py-1 text-xs font-semibold text-white">
                    {reviewedPayload.lots.length} lot
                    {reviewedPayload.lots.length === 1 ? "" : "s"}
                  </span>
                </div>
                <div className="mt-4 space-y-4">
                  {reviewedPayload.lots.map((lot, index) => {
                    const isOpen = openLots[index] ?? true;
                    return (
                      <article
                        key={`${lot.civic_address || "lot"}-${index}`}
                        className="overflow-hidden rounded-[1.4rem] border border-stone-200 bg-white"
                      >
                        <button
                          type="button"
                          onClick={() =>
                            setOpenLots((current) => ({
                              ...current,
                              [index]: !isOpen,
                            }))
                          }
                          className="flex w-full items-center justify-between px-4 py-4 text-left"
                        >
                          <div>
                            <p className="text-lg font-semibold text-stone-950">
                              {String(lot.civic_address || `Lot ${index + 1}`)}
                            </p>
                            <p className="mt-1 text-sm text-stone-500">
                              Block {String(lot.block || "—")} | Lot{" "}
                              {String(lot.lot_number || "—")} | Plan{" "}
                              {String(lot.plan || "—")}
                            </p>
                          </div>
                          <span className="text-sm font-semibold text-stone-500">
                            {isOpen ? "Hide" : "Show"}
                          </span>
                        </button>
                        {isOpen ? (
                          <div className="grid gap-4 border-t border-stone-200 bg-stone-50/70 p-4">
                            <label className="rounded-[1.1rem] border border-stone-200 bg-white px-4 py-3">
                              <span className="mb-2 block text-sm font-semibold text-stone-800">
                                Civic Address
                              </span>
                              <input
                                value={String(lot.civic_address ?? "")}
                                onChange={(event) =>
                                  updateLotField(index, "civic_address", event.target.value)
                                }
                                className="w-full rounded-xl border border-stone-200 bg-white px-3 py-2 text-sm text-stone-900 outline-none transition focus:border-stone-500"
                              />
                            </label>
                            <div className="grid gap-4 sm:grid-cols-2">
                              {lotFieldLabels.map(([field, label]) => {
                                const path = `lots.${index}.${field}`;
                                const lowConfidence = isLowConfidence(path);
                                return (
                                  <label
                                    key={field}
                                    className={`rounded-[1.1rem] border px-4 py-3 ${lowConfidence ? "border-amber-300 bg-amber-50" : "border-stone-200 bg-white"}`}
                                  >
                                    <div className="mb-2 flex items-center justify-between gap-4">
                                      <span className="text-sm font-semibold text-stone-800">
                                        {label}
                                      </span>
                                      <span
                                        className={`text-xs font-semibold ${lowConfidence ? "text-amber-700" : "text-stone-400"}`}
                                      >
                                        {Math.round(getConfidence(path) * 100)}%
                                      </span>
                                    </div>
                                    <input
                                      value={String(lot[field] ?? "")}
                                      onChange={(event) =>
                                        updateLotField(index, field, event.target.value)
                                      }
                                      className="w-full rounded-xl border border-stone-200 bg-white px-3 py-2 text-sm text-stone-900 outline-none transition focus:border-stone-500"
                                    />
                                  </label>
                                );
                              })}
                            </div>
                          </div>
                        ) : null}
                      </article>
                    );
                  })}
                </div>
              </section>

              <section className="rounded-[1.6rem] border border-stone-200 bg-stone-50/80 p-5">
                <p className="text-xs font-semibold uppercase tracking-[0.22em] text-stone-500">
                  4. Notable Clauses
                </p>
                <div className="mt-4 space-y-3">
                  {reviewedPayload.notable_clauses.length === 0 ? (
                    <div className="rounded-[1.2rem] border border-dashed border-stone-300 bg-white px-4 py-6 text-sm text-stone-500">
                      No notable clauses extracted.
                    </div>
                  ) : (
                    reviewedPayload.notable_clauses.map((clause, index) => (
                      <article
                        key={`${clause.clause_ref || "clause"}-${index}`}
                        className="rounded-[1.2rem] border border-stone-200 bg-white px-4 py-4"
                      >
                        <div className="flex flex-wrap items-center gap-3">
                          <span className="rounded-full bg-stone-900 px-3 py-1 text-xs font-semibold uppercase tracking-[0.16em] text-white">
                            {String(clause.label || `Clause ${index + 1}`)}
                          </span>
                          <span className="text-xs font-semibold uppercase tracking-[0.18em] text-stone-500">
                            {String(clause.clause_ref || "No ref")}
                          </span>
                          <span className="rounded-full bg-stone-100 px-3 py-1 text-xs font-semibold text-stone-600">
                            {String(clause.category || "uncategorized")}
                          </span>
                        </div>
                        <p className="mt-3 text-sm leading-6 text-stone-700">
                          {String(clause.text || "No clause text extracted.")}
                        </p>
                      </article>
                    ))
                  )}
                </div>
              </section>
            </div>
          </div>

          <div className="border-t border-stone-200 bg-white/96 px-4 py-4 shadow-[0_-18px_35px_rgba(45,32,18,0.08)] sm:px-5">
            <div className="flex flex-col gap-4">
              {!hasScrolledToEnd ? (
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-amber-700">
                  Scroll through all sections to enable approval.
                </p>
              ) : (
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-emerald-700">
                  Review complete. Approval is enabled.
                </p>
              )}

              {showRejectForm ? (
                <div className="rounded-[1.2rem] border border-rose-200 bg-rose-50 p-4">
                  <label className="block text-sm font-semibold text-rose-800">
                    Rejection reason
                  </label>
                  <textarea
                    value={rejectionReason}
                    onChange={(event) => setRejectionReason(event.target.value)}
                    rows={3}
                    className="mt-2 w-full rounded-xl border border-rose-200 bg-white px-3 py-2 text-sm text-stone-900 outline-none transition focus:border-rose-400"
                    placeholder="Explain what blocked review approval."
                  />
                  <div className="mt-3 flex flex-wrap gap-3">
                    <button
                      type="button"
                      onClick={() => void handleSubmit("rejected")}
                      disabled={submitting}
                      className="rounded-full bg-rose-700 px-5 py-3 text-sm font-semibold text-white transition hover:bg-rose-600 disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      {submitting ? "Submitting..." : "Submit rejection"}
                    </button>
                    <button
                      type="button"
                      onClick={() => setShowRejectForm(false)}
                      className="rounded-full border border-stone-300 px-5 py-3 text-sm font-semibold text-stone-700 transition hover:bg-stone-100"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              ) : null}

              <div className="flex flex-wrap items-center justify-between gap-3">
                <p className="text-sm text-stone-500">
                  Edited fields: <span className="font-semibold text-stone-800">{editedFields.length}</span>
                </p>
                <div className="flex flex-wrap gap-3">
                  <button
                    type="button"
                    onClick={() => {
                      setShowRejectForm(true);
                      setError(null);
                    }}
                    disabled={submitting}
                    className="rounded-full bg-rose-700 px-5 py-3 text-sm font-semibold text-white transition hover:bg-rose-600 disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    Reject
                  </button>
                  <button
                    type="button"
                    onClick={() => void handleSubmit("approved")}
                    disabled={submitting || !hasScrolledToEnd || !!success?.promotion}
                    className="rounded-full bg-emerald-700 px-5 py-3 text-sm font-semibold text-white transition hover:bg-emerald-600 disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {submitting ? "Submitting..." : "Approve and promote to database"}
                  </button>
                </div>
              </div>
            </div>
          </div>
        </section>
      </div>
    </main>
  );
}
