"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import {
  type DocumentDetail,
  type ReviewResponse,
  getDocument,
  getDocumentPdfUrl,
  submitReview,
} from "@/lib/api";

type ScalarValue = string | number | boolean | null;
type ReviewValue = unknown;
interface ReviewObject {
  [key: string]: ReviewValue;
}
type ReviewPayload = ReviewObject & {
  agreement: ReviewObject;
  security_deposit: ReviewObject;
  development_guidelines: ReviewObject;
  lots: ReviewObject[];
  notable_clauses: ReviewObject[];
  payment_schedule: ReviewObject[];
  construction_summary: ReviewObject;
  conditions: ReviewObject;
  standard_specs: ReviewObject;
  upgrades: ReviewObject[];
  landscaping: ReviewObject;
  financial: ReviewObject;
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

const saleAgreementFieldLabels: Array<[string, string]> = [
  ["agreement_date", "Agreement Date"],
  ["purchaser_names", "Purchaser Names"],
  ["purchaser_address", "Purchaser Address"],
  ["builder_name", "Builder Name"],
  ["builder_address", "Builder Address"],
  ["buyers_realtor_name", "Buyer's Realtor"],
  ["buyers_brokerage", "Buyer's Brokerage"],
  ["sellers_realtor_name", "Seller's Realtor"],
  ["sellers_brokerage", "Seller's Brokerage"],
  ["civic_address", "Civic Address"],
  ["legal_description.block", "Legal Block"],
  ["legal_description.lot", "Legal Lot"],
  ["legal_description.plan", "Legal Plan"],
  ["estimated_occupancy_date", "Estimated Occupancy Date"],
  ["purchase_price_total", "Purchase Price Total"],
  ["commission_rate", "Commission Rate"],
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

const paymentScheduleFieldLabels: Array<[string, string]> = [
  ["stage", "Stage"],
  ["percent", "Percent"],
  ["amount", "Amount"],
  ["due_date", "Due Date"],
  ["trigger", "Trigger"],
  ["payable_to", "Payable To"],
];

const clauseFieldLabels: Array<[string, string]> = [
  ["label", "Label"],
  ["clause_ref", "Clause Ref"],
  ["category", "Category"],
  ["text", "Text"],
];

const constructionSummaryFields: Array<[string, string]> = [
  ["house_sqft", "House Sqft"],
  ["house_plan_type", "House Plan Type"],
  ["lot_type_feature", "Lot Type Feature"],
  ["bedrooms", "Bedrooms"],
  ["bathrooms", "Bathrooms"],
  ["garage_size", "Garage Size"],
  ["lower_level_development", "Lower Level Development"],
];

const standardSpecFields: Array<[string, string]> = [
  ["foundation", "Foundation"],
  ["exterior_finishes", "Exterior Finishes"],
  ["cabinets", "Cabinets"],
  ["framing_insulation", "Framing / Insulation"],
  ["interior_finishes", "Interior Finishes"],
  ["electrical", "Electrical"],
  ["mechanical", "Mechanical"],
  ["plumbing", "Plumbing"],
  ["exterior_yard", "Exterior Yard"],
];

const upgradeFieldLabels: Array<[string, string]> = [
  ["item_number", "Item Number"],
  ["description", "Description"],
];

const conditionFields: Array<[string, string]> = [
  ["financing_condition_date", "Financing Condition Date"],
  ["lawyer_approval_date", "Lawyer Approval Date"],
  ["design_meeting_date", "Design Meeting Date"],
  ["acceptance_date", "Acceptance Date"],
];

const financialFields: Array<[string, string]> = [
  ["land_value", "Land Value"],
  ["builders_lien_holdback_percent", "Builders Lien Holdback Percent"],
  ["interest_rate_on_late_payments", "Interest Rate On Late Payments"],
  ["materials_escalation_cap", "Materials Escalation Cap"],
];

const landscapingFields: Array<[string, string]> = [
  ["landscaping_requirements", "Landscaping Requirements"],
  ["landscaping_deadline", "Landscaping Deadline"],
  ["security_deposit_amount", "Security Deposit Amount"],
  ["security_deposit_return_condition", "Security Deposit Return Condition"],
];

const developmentGuidelineFields: Array<[string, string]> = [
  ["architectural_controls", "Architectural Controls"],
  ["exterior_materials", "Exterior Materials"],
  ["roof_requirements", "Roof Requirements"],
  ["driveway_requirements", "Driveway Requirements"],
  ["landscaping_requirements", "Landscaping Requirements"],
  ["fencing_requirements", "Fencing Requirements"],
  ["construction_start_deadline", "Construction Start Deadline"],
  ["construction_completion_deadline", "Construction Completion Deadline"],
  ["deposit_return_conditions", "Deposit Return Conditions"],
  ["developer_approval_requirements", "Developer Approval Requirements"],
  ["municipal_or_utility_requirements", "Municipal / Utility Requirements"],
  ["other_restrictions", "Other Restrictions"],
];

function getStatusBadge(status: string): string {
  if (status === "approved") {
    return "bg-[var(--ch-success-bg)] text-[var(--ch-success-text)] ring-[var(--ch-success-border)]";
  }
  if (status === "rejected") {
    return "bg-rose-100 text-rose-800 ring-rose-200";
  }
  if (status === "in_review") {
    return "bg-[var(--ch-warning-bg)] text-[var(--ch-warning-text)] ring-[var(--ch-warning-border)]";
  }
  return "bg-[var(--ch-surface)] text-[var(--ch-text-secondary)] ring-[var(--ch-border)]";
}

function formatDocType(docType: string): string {
  if (docType === "sale_otp") {
    return "OTP SALE";
  }
  if (docType === "land_otp") {
    return "OTP LAND";
  }
  return docType.replaceAll("_", " ");
}

function createDefaultPayload(detail: DocumentDetail | null): ReviewPayload {
  const payload = detail?.extraction?.extracted_payload as ReviewObject | undefined;
  return {
    ...(payload || {}),
    agreement: { ...((payload?.agreement as ReviewObject | undefined) || {}) },
    security_deposit: { ...((payload?.security_deposit as ReviewObject | undefined) || {}) },
    development_guidelines: {
      ...((payload?.["development_guidelines"] as ReviewObject | undefined) || {}),
    },
    lots: [...((payload?.lots as ReviewObject[] | undefined) || [])],
    payment_schedule: [...((payload?.["payment_schedule"] as ReviewObject[] | undefined) || [])],
    construction_summary: {
      ...((payload?.["construction_summary"] as ReviewObject | undefined) || {}),
    },
    conditions: { ...((payload?.["conditions"] as ReviewObject | undefined) || {}) },
    standard_specs: {
      ...((payload?.["standard_specs"] as ReviewObject | undefined) || {}),
    },
    upgrades: [...((payload?.["upgrades"] as ReviewObject[] | undefined) || [])],
    landscaping: { ...((payload?.["landscaping"] as ReviewObject | undefined) || {}) },
    financial: { ...((payload?.["financial"] as ReviewObject | undefined) || {}) },
    notable_clauses: [...((payload?.notable_clauses as ReviewObject[] | undefined) || [])],
  };
}

function getNestedValue(source: ReviewObject | undefined, path: string): ReviewValue | undefined {
  let current: ReviewValue | undefined = source;
  for (const segment of path.split(".")) {
    if (!current || Array.isArray(current) || typeof current !== "object") {
      return undefined;
    }
    current = (current as ReviewObject)[segment];
  }
  return current;
}

function formatInputValue(value: ReviewValue | undefined): string {
  if (value == null) {
    return "";
  }
  if (Array.isArray(value)) {
    return value
      .map((item) =>
        item && typeof item === "object"
          ? Object.values(item).filter(Boolean).join(": ")
          : String(item ?? ""),
      )
      .filter(Boolean)
      .join("; ");
  }
  if (typeof value === "object") {
    return JSON.stringify(value);
  }
  return String(value);
}

function parseInputValue(value: string): ScalarValue {
  return value || null;
}

function updateNestedObject(source: ReviewObject, path: string, value: ScalarValue): ReviewObject {
  const [head, ...rest] = path.split(".");
  if (rest.length === 0) {
    return { ...source, [head]: value };
  }

  const existing = source[head];
  return {
    ...source,
    [head]: updateNestedObject(
      !Array.isArray(existing) && existing && typeof existing === "object"
        ? (existing as ReviewObject)
        : {},
      rest.join("."),
      value,
    ),
  };
}

function getValueByPath(source: ReviewValue, path: string): ReviewValue | undefined {
  let current: ReviewValue = source;
  for (const segment of path.split(".")) {
    if (Array.isArray(current)) {
      const index = Number(segment);
      current = Number.isInteger(index) ? current[index] : undefined;
    } else if (current && typeof current === "object") {
      current = (current as ReviewObject)[segment];
    } else {
      return undefined;
    }
  }
  return current;
}

function isBlankValue(value: ReviewValue | undefined): boolean {
  if (value == null) {
    return true;
  }
  if (typeof value === "string") {
    return value.trim() === "";
  }
  return false;
}

export default function DocumentReviewPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
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
    if (typeof score === "number") {
      return score;
    }

    return isBlankValue(getValueByPath(reviewedPayload, path)) ? 0 : 1;
  }

  function isLowConfidence(path: string): boolean {
    return getConfidence(path) < 0.7;
  }

  function updateAgreementField(field: string, value: string) {
    setReviewedPayload((current) => ({
      ...current,
      agreement: updateNestedObject(current.agreement, field, parseInputValue(value)),
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

  function updateObjectField(section: keyof ReviewPayload, field: string, value: string) {
    setReviewedPayload((current) => {
      const currentSection = current[section];
      return {
        ...current,
        [section]: updateNestedObject(
          !Array.isArray(currentSection) && currentSection && typeof currentSection === "object"
            ? (currentSection as ReviewObject)
            : {},
          field,
          parseInputValue(value),
        ),
      };
    });
    markEdited(`${String(section)}.${field}`);
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

  function updateArrayField(
    section: "payment_schedule" | "upgrades" | "notable_clauses",
    index: number,
    field: string,
    value: string,
  ) {
    setReviewedPayload((current) => {
      const rows = Array.isArray(current[section]) ? current[section] : [];
      return {
        ...current,
        [section]: rows.map((row, rowIndex) =>
          rowIndex === index ? updateNestedObject(row, field, parseInputValue(value)) : row,
        ),
      };
    });
    markEdited(`${section}.${index}.${field}`);
  }

  function addArrayRow(section: "payment_schedule" | "upgrades" | "notable_clauses") {
    const defaults: Record<typeof section, ReviewObject> = {
      payment_schedule: {
        stage: null,
        percent: null,
        amount: null,
        due_date: null,
        trigger: null,
        payable_to: null,
      },
      upgrades: {
        item_number: null,
        description: null,
      },
      notable_clauses: {
        label: null,
        clause_ref: null,
        category: null,
        text: null,
      },
    };

    setReviewedPayload((current) => ({
      ...current,
      [section]: [...current[section], defaults[section]],
    }));
    markEdited(section);
  }

  function addLotRow() {
    const index = reviewedPayload.lots.length;
    setReviewedPayload((current) => ({
      ...current,
      lots: [
        ...current.lots,
        {
          civic_address: null,
          block: null,
          lot_number: null,
          plan: null,
          purchase_price: null,
          deposit_1_amount: null,
          deposit_2_amount: null,
          deposit_2_due_date: null,
        },
      ],
    }));
    setOpenLots((current) => ({ ...current, [index]: true }));
    markEdited("lots");
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
      if (decision === "approved" && response.promotion) {
        const [projectId] = response.promotion.project_ids;
        router.push(projectId ? `/projects?project=${projectId}` : "/projects");
        return;
      }
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
      <main className="flex min-h-screen items-center justify-center bg-[var(--ch-page-bg)]">
        <div className="flex items-center gap-3 rounded-full border border-[var(--ch-border)] bg-[var(--ch-surface)] px-5 py-3 text-sm font-medium text-[var(--ch-text-secondary)] shadow-lg backdrop-blur">
          <span className="h-4 w-4 animate-spin rounded-full border-2 border-[var(--ch-border)] border-t-[var(--ch-accent)]" />
          Loading review workspace
        </div>
      </main>
    );
  }

  if (error && !detail) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-[var(--ch-page-bg)] px-6">
        <div className="max-w-xl rounded-[2rem] border border-rose-200 bg-white px-6 py-8 shadow-xl">
          <p className="text-sm font-semibold uppercase tracking-[0.2em] text-rose-500">
            Review Error
          </p>
          <h1 className="mt-3 text-2xl font-semibold text-[var(--ch-text-primary)]">
            Could not open this document.
          </h1>
          <p className="mt-3 text-sm leading-6 text-[var(--ch-text-secondary)]">{error}</p>
          <Link
            href="/documents"
            className="mt-6 inline-flex rounded-full bg-[var(--ch-surface)] px-5 py-3 text-sm font-semibold text-[var(--ch-text-primary)] transition hover:bg-[var(--ch-accent-hover)]"
          >
            Back to documents
          </Link>
        </div>
      </main>
    );
  }

  const filename = detail?.document.original_filename || "Untitled document";
  const pdfUrl = getDocumentPdfUrl(documentId);
  const isSaleOtp = detail?.document.doc_type === "sale_otp";
  const activeAgreementFields = isSaleOtp ? saleAgreementFieldLabels : agreementFieldLabels;

  return (
    <main className="h-screen bg-[var(--ch-page-bg)] p-3 text-[var(--ch-text-primary)] sm:p-4">
      <div className="grid h-full gap-3 lg:grid-cols-[1.1fr_0.9fr]">
        <section className="min-h-[42vh] min-w-0 overflow-hidden rounded-[2rem] border border-[var(--ch-border)] bg-[var(--ch-surface)] shadow-lg">
          <div className="flex h-full flex-col">
            <div className="flex items-center justify-between border-b border-[var(--ch-border)] px-5 py-4 text-[var(--ch-text-primary)]">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.22em] text-[var(--ch-text-muted)]">
                  Source PDF
                </p>
                <h2 className="mt-1 text-lg font-semibold">{filename}</h2>
              </div>
              <Link
                href="/documents"
                className="rounded-full border border-[var(--ch-border)] px-4 py-2 text-xs font-semibold uppercase tracking-[0.18em] text-[var(--ch-text-secondary)] transition hover:border-[var(--ch-border-strong)] hover:bg-[var(--ch-surface)]"
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

        <section className="flex h-full min-h-[52vh] flex-col overflow-hidden rounded-[2rem] border border-[var(--ch-border)] bg-[var(--ch-surface)] shadow-lg backdrop-blur">
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
            <div className="border-b border-[var(--ch-border)] px-6 py-6">
              <p className="text-xs font-semibold uppercase tracking-[0.24em] text-[var(--ch-text-muted)]">
                Review Workspace
              </p>
              <div className="mt-3 flex flex-wrap items-center gap-3">
                <h1 className="text-2xl font-semibold tracking-tight text-[var(--ch-text-primary)]">
                  {filename}
                </h1>
                <span
                  className={`inline-flex rounded-full px-3 py-1 text-xs font-semibold ring-1 ${getStatusBadge(detail?.document.status || "received")}`}
                >
                  {detail?.document.status.replaceAll("_", " ")}
                </span>
                <span className="rounded-full bg-[var(--ch-surface-muted)] px-3 py-1 text-xs font-semibold uppercase tracking-[0.18em] text-[var(--ch-text-secondary)]">
                  {formatDocType(detail?.document.doc_type || "")}
                </span>
              </div>
              <div className="mt-4 grid gap-2 text-sm text-[var(--ch-text-secondary)] sm:grid-cols-2">
                <p>OCR method: {detail?.ingestion?.ocr_method || "Not available"}</p>
                <p>
                  OCR confidence:{" "}
                  {detail?.ingestion?.ocr_confidence != null
                    ? Number(detail.ingestion.ocr_confidence).toFixed(3)
                    : "Not available"}
                </p>
              </div>
              {success?.promotion ? (
                <div className="mt-5 rounded-[1.4rem] border border-[var(--ch-success-border)] bg-[var(--ch-success-bg)] px-5 py-4 text-sm text-[var(--ch-success-text)]">
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
                    className="mt-4 inline-flex rounded-full bg-[var(--ch-success-text)] px-4 py-2 text-xs font-semibold uppercase tracking-[0.18em] text-[var(--ch-text-primary)] transition hover:brightness-110"
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
              <section className="rounded-[1.6rem] border border-[var(--ch-border)] bg-[var(--ch-surface)] p-5">
                <div className="mb-4 flex items-center justify-between">
                  <div>
                    <p className="text-xs font-semibold uppercase tracking-[0.22em] text-[var(--ch-text-muted)]">
                      1. Agreement Fields
                    </p>
                    <h2 className="mt-1 text-lg font-semibold text-[var(--ch-text-primary)]">
                      Agreement-level extraction
                    </h2>
                  </div>
                </div>
                <div className="grid gap-4">
                  {activeAgreementFields.map(([field, label]) => {
                    const path = `agreement.${field}`;
                    const lowConfidence = isLowConfidence(path);
                    return (
                      <label
                        key={field}
                        className={`rounded-[1.2rem] border px-4 py-3 ${lowConfidence ? "border-amber-300 bg-amber-50" : "border-[var(--ch-border)] bg-white"}`}
                      >
                        <div className="mb-2 flex items-center justify-between gap-4">
                          <span className="text-sm font-semibold text-[var(--ch-text-primary)]">
                            {label}
                          </span>
                          <span
                            className={`text-xs font-semibold ${lowConfidence ? "text-[var(--ch-warning-text)]" : "text-[var(--ch-text-muted)]"}`}
                          >
                            {lowConfidence
                              ? `Warning ${Math.round(getConfidence(path) * 100)}% confidence`
                              : `${Math.round(getConfidence(path) * 100)}% confidence`}
                          </span>
                        </div>
                        <input
                          value={formatInputValue(getNestedValue(reviewedPayload.agreement, field))}
                          onChange={(event) =>
                            updateAgreementField(field, event.target.value)
                          }
                          className="w-full rounded-xl border border-[var(--ch-border)] bg-white px-3 py-2 text-sm text-[var(--ch-text-primary)] outline-none transition focus:border-[var(--ch-accent)]"
                        />
                      </label>
                    );
                  })}
                </div>
              </section>

              {!isSaleOtp ? (
                <>
              <section className="rounded-[1.6rem] border border-[var(--ch-border)] bg-[var(--ch-surface)] p-5">
                <p className="text-xs font-semibold uppercase tracking-[0.22em] text-[var(--ch-text-muted)]">
                  2. Security Deposit
                </p>
                <div className="mt-4 grid gap-4 sm:grid-cols-3">
                  {securityDepositFields.map(([field, label]) => {
                    const path = `security_deposit.${field}`;
                    const lowConfidence = isLowConfidence(path);
                    return (
                      <label
                        key={field}
                        className={`rounded-[1.2rem] border px-4 py-3 ${lowConfidence ? "border-amber-300 bg-amber-50" : "border-[var(--ch-border)] bg-white"}`}
                      >
                        <div className="mb-2 flex items-center justify-between gap-4">
                          <span className="text-sm font-semibold text-[var(--ch-text-primary)]">
                            {label}
                          </span>
                          <span
                            className={`text-xs font-semibold ${lowConfidence ? "text-[var(--ch-warning-text)]" : "text-[var(--ch-text-muted)]"}`}
                          >
                            {Math.round(getConfidence(path) * 100)}%
                          </span>
                        </div>
                        <input
                          value={String(reviewedPayload.security_deposit[field] ?? "")}
                          onChange={(event) =>
                            updateSecurityDepositField(field, event.target.value)
                          }
                          className="w-full rounded-xl border border-[var(--ch-border)] bg-white px-3 py-2 text-sm text-[var(--ch-text-primary)] outline-none transition focus:border-[var(--ch-accent)]"
                        />
                      </label>
                    );
                  })}
                </div>
              </section>

              <section className="rounded-[1.6rem] border border-[var(--ch-border)] bg-[var(--ch-surface)] p-5">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-xs font-semibold uppercase tracking-[0.22em] text-[var(--ch-text-muted)]">
                      3. Lots
                    </p>
                    <h2 className="mt-1 text-lg font-semibold text-[var(--ch-text-primary)]">
                      Lot schedule review
                    </h2>
                  </div>
                  <span className="rounded-full bg-[var(--ch-surface)] px-3 py-1 text-xs font-semibold text-[var(--ch-text-primary)]">
                    {reviewedPayload.lots.length} lot
                    {reviewedPayload.lots.length === 1 ? "" : "s"}
                  </span>
                </div>
                <button
                  type="button"
                  onClick={addLotRow}
                  className="mt-4 rounded-full border border-[var(--ch-border)] bg-white px-4 py-2 text-xs font-semibold uppercase tracking-[0.16em] text-[var(--ch-text-secondary)] transition hover:bg-[var(--ch-surface-muted)]"
                >
                  Add lot
                </button>
                <div className="mt-4 space-y-4">
                  {reviewedPayload.lots.map((lot, index) => {
                    const isOpen = openLots[index] ?? true;
                    return (
                      <article
                        key={`${lot.civic_address || "lot"}-${index}`}
                        className="overflow-hidden rounded-[1.4rem] border border-[var(--ch-border)] bg-white"
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
                            <p className="text-lg font-semibold text-[var(--ch-text-primary)]">
                              {String(lot.civic_address || `Lot ${index + 1}`)}
                            </p>
                            <p className="mt-1 text-sm text-[var(--ch-text-muted)]">
                              Block {String(lot.block || "—")} | Lot{" "}
                              {String(lot.lot_number || "—")} | Plan{" "}
                              {String(lot.plan || "—")}
                            </p>
                          </div>
                          <span className="text-sm font-semibold text-[var(--ch-text-muted)]">
                            {isOpen ? "Hide" : "Show"}
                          </span>
                        </button>
                        {isOpen ? (
                          <div className="grid gap-4 border-t border-[var(--ch-border)] bg-[var(--ch-surface)] p-4">
                            <label className="rounded-[1.1rem] border border-[var(--ch-border)] bg-white px-4 py-3">
                              <span className="mb-2 block text-sm font-semibold text-[var(--ch-text-primary)]">
                                Civic Address
                              </span>
                              <input
                                value={String(lot.civic_address ?? "")}
                                onChange={(event) =>
                                  updateLotField(index, "civic_address", event.target.value)
                                }
                                className="w-full rounded-xl border border-[var(--ch-border)] bg-white px-3 py-2 text-sm text-[var(--ch-text-primary)] outline-none transition focus:border-[var(--ch-accent)]"
                              />
                            </label>
                            <div className="grid gap-4 sm:grid-cols-2">
                              {lotFieldLabels.map(([field, label]) => {
                                const path = `lots.${index}.${field}`;
                                const lowConfidence = isLowConfidence(path);
                                return (
                                  <label
                                    key={field}
                                    className={`rounded-[1.1rem] border px-4 py-3 ${lowConfidence ? "border-amber-300 bg-amber-50" : "border-[var(--ch-border)] bg-white"}`}
                                  >
                                    <div className="mb-2 flex items-center justify-between gap-4">
                                      <span className="text-sm font-semibold text-[var(--ch-text-primary)]">
                                        {label}
                                      </span>
                                      <span
                                        className={`text-xs font-semibold ${lowConfidence ? "text-[var(--ch-warning-text)]" : "text-[var(--ch-text-muted)]"}`}
                                      >
                                        {Math.round(getConfidence(path) * 100)}%
                                      </span>
                                    </div>
                                    <input
                                      value={String(lot[field] ?? "")}
                                      onChange={(event) =>
                                        updateLotField(index, field, event.target.value)
                                      }
                                      className="w-full rounded-xl border border-[var(--ch-border)] bg-white px-3 py-2 text-sm text-[var(--ch-text-primary)] outline-none transition focus:border-[var(--ch-accent)]"
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

              <section className="rounded-[1.6rem] border border-[var(--ch-border)] bg-[var(--ch-surface)] p-5">
                <p className="text-xs font-semibold uppercase tracking-[0.22em] text-[var(--ch-text-muted)]">
                  4. Development Guidelines
                </p>
                <h2 className="mt-1 text-lg font-semibold text-[var(--ch-text-primary)]">
                  Community-level requirements
                </h2>
                <div className="mt-4 grid gap-4 sm:grid-cols-2">
                  {developmentGuidelineFields.map(([field, label]) => {
                    const path = `development_guidelines.${field}`;
                    const lowConfidence = isLowConfidence(path);
                    const value = reviewedPayload.development_guidelines?.[field];
                    const isLongField =
                      Array.isArray(value) ||
                      field === "architectural_controls" ||
                      field === "developer_approval_requirements" ||
                      field === "other_restrictions";
                    return (
                      <label
                        key={field}
                        className={`rounded-[1.2rem] border px-4 py-3 ${lowConfidence ? "border-amber-300 bg-amber-50" : "border-[var(--ch-border)] bg-white"} ${isLongField ? "sm:col-span-2" : ""}`}
                      >
                        <div className="mb-2 flex items-center justify-between gap-4">
                          <span className="text-sm font-semibold text-[var(--ch-text-primary)]">
                            {label}
                          </span>
                          <span
                            className={`text-xs font-semibold ${lowConfidence ? "text-[var(--ch-warning-text)]" : "text-[var(--ch-text-muted)]"}`}
                          >
                            {Math.round(getConfidence(path) * 100)}%
                          </span>
                        </div>
                        {isLongField ? (
                          <textarea
                            value={formatInputValue(value)}
                            onChange={(event) =>
                              updateObjectField("development_guidelines", field, event.target.value)
                            }
                            rows={3}
                            className="w-full rounded-xl border border-[var(--ch-border)] bg-white px-3 py-2 text-sm text-[var(--ch-text-primary)] outline-none transition focus:border-[var(--ch-accent)]"
                          />
                        ) : (
                          <input
                            value={formatInputValue(value)}
                            onChange={(event) =>
                              updateObjectField("development_guidelines", field, event.target.value)
                            }
                            className="w-full rounded-xl border border-[var(--ch-border)] bg-white px-3 py-2 text-sm text-[var(--ch-text-primary)] outline-none transition focus:border-[var(--ch-accent)]"
                          />
                        )}
                      </label>
                    );
                  })}
                </div>
              </section>
                </>
              ) : null}

              {isSaleOtp ? (
                <>
                  <section className="rounded-[1.6rem] border border-[var(--ch-border)] bg-[var(--ch-surface)] p-5">
                    <div className="flex items-center justify-between gap-4">
                      <p className="text-xs font-semibold uppercase tracking-[0.22em] text-[var(--ch-text-muted)]">
                        2. Payment Schedule
                      </p>
                      <button
                        type="button"
                        onClick={() => addArrayRow("payment_schedule")}
                        className="rounded-full border border-[var(--ch-border)] bg-white px-4 py-2 text-xs font-semibold uppercase tracking-[0.16em] text-[var(--ch-text-secondary)] transition hover:bg-[var(--ch-surface-muted)]"
                      >
                        Add payment
                      </button>
                    </div>
                    <div className="mt-4 space-y-4">
                      {(reviewedPayload.payment_schedule || []).map((payment, index) => (
                        <article
                          key={`payment-${index}`}
                          className="grid gap-4 rounded-[1.2rem] border border-[var(--ch-border)] bg-white p-4 sm:grid-cols-2"
                        >
                          {paymentScheduleFieldLabels.map(([field, label]) => {
                            const path = `payment_schedule.${index}.${field}`;
                            const lowConfidence = isLowConfidence(path);
                            return (
                              <label key={field}>
                                <div className="mb-2 flex items-center justify-between gap-4">
                                  <span className="text-sm font-semibold text-[var(--ch-text-primary)]">
                                    {label}
                                  </span>
                                  <span
                                    className={`text-xs font-semibold ${lowConfidence ? "text-[var(--ch-warning-text)]" : "text-[var(--ch-text-muted)]"}`}
                                  >
                                    {Math.round(getConfidence(path) * 100)}%
                                  </span>
                                </div>
                                <input
                                  value={formatInputValue(payment[field])}
                                  onChange={(event) =>
                                    updateArrayField("payment_schedule", index, field, event.target.value)
                                  }
                                  className="w-full rounded-xl border border-[var(--ch-border)] bg-white px-3 py-2 text-sm text-[var(--ch-text-primary)] outline-none transition focus:border-[var(--ch-accent)]"
                                />
                              </label>
                            );
                          })}
                        </article>
                      ))}
                    </div>
                  </section>

                  <section className="rounded-[1.6rem] border border-[var(--ch-border)] bg-[var(--ch-surface)] p-5">
                    <p className="text-xs font-semibold uppercase tracking-[0.22em] text-[var(--ch-text-muted)]">
                      3. Conditions
                    </p>
                    <div className="mt-4 grid gap-4 sm:grid-cols-2">
                      {conditionFields.map(([field, label]) => {
                        const path = `conditions.${field}`;
                        const lowConfidence = isLowConfidence(path);
                        return (
                          <label
                            key={field}
                            className={`rounded-[1.2rem] border px-4 py-3 ${lowConfidence ? "border-amber-300 bg-amber-50" : "border-[var(--ch-border)] bg-white"}`}
                          >
                            <div className="mb-2 flex items-center justify-between gap-4">
                              <span className="text-sm font-semibold text-[var(--ch-text-primary)]">
                                {label}
                              </span>
                              <span
                                className={`text-xs font-semibold ${lowConfidence ? "text-[var(--ch-warning-text)]" : "text-[var(--ch-text-muted)]"}`}
                              >
                                {Math.round(getConfidence(path) * 100)}%
                              </span>
                            </div>
                            <input
                              value={formatInputValue(reviewedPayload.conditions?.[field])}
                              onChange={(event) =>
                                updateObjectField("conditions", field, event.target.value)
                              }
                              className="w-full rounded-xl border border-[var(--ch-border)] bg-white px-3 py-2 text-sm text-[var(--ch-text-primary)] outline-none transition focus:border-[var(--ch-accent)]"
                            />
                          </label>
                        );
                      })}
                    </div>
                  </section>

                  <section className="rounded-[1.6rem] border border-[var(--ch-border)] bg-[var(--ch-surface)] p-5">
                    <p className="text-xs font-semibold uppercase tracking-[0.22em] text-[var(--ch-text-muted)]">
                      4. Build Summary
                    </p>
                    <div className="mt-4 grid gap-4 sm:grid-cols-2">
                      {constructionSummaryFields.map(([field, label]) => {
                        const path = `construction_summary.${field}`;
                        const lowConfidence = isLowConfidence(path);
                        return (
                          <label
                            key={field}
                            className={`rounded-[1.2rem] border px-4 py-3 ${lowConfidence ? "border-amber-300 bg-amber-50" : "border-[var(--ch-border)] bg-white"}`}
                          >
                            <div className="mb-2 flex items-center justify-between gap-4">
                              <span className="text-sm font-semibold text-[var(--ch-text-primary)]">
                                {label}
                              </span>
                              <span
                                className={`text-xs font-semibold ${lowConfidence ? "text-[var(--ch-warning-text)]" : "text-[var(--ch-text-muted)]"}`}
                              >
                                {Math.round(getConfidence(path) * 100)}%
                              </span>
                            </div>
                            <input
                              value={formatInputValue(reviewedPayload.construction_summary?.[field])}
                              onChange={(event) =>
                                updateObjectField("construction_summary", field, event.target.value)
                              }
                              className="w-full rounded-xl border border-[var(--ch-border)] bg-white px-3 py-2 text-sm text-[var(--ch-text-primary)] outline-none transition focus:border-[var(--ch-accent)]"
                            />
                          </label>
                        );
                      })}
                    </div>
                  </section>

                  <section className="rounded-[1.6rem] border border-[var(--ch-border)] bg-[var(--ch-surface)] p-5">
                    <p className="text-xs font-semibold uppercase tracking-[0.22em] text-[var(--ch-text-muted)]">
                      5. Standard Specs
                    </p>
                    <div className="mt-4 grid gap-4 sm:grid-cols-2">
                      {standardSpecFields.map(([field, label]) => {
                        const path = `standard_specs.${field}`;
                        const lowConfidence = isLowConfidence(path);
                        return (
                          <label
                            key={field}
                            className={`rounded-[1.2rem] border px-4 py-3 ${lowConfidence ? "border-amber-300 bg-amber-50" : "border-[var(--ch-border)] bg-white"}`}
                          >
                            <div className="mb-2 flex items-center justify-between gap-4">
                              <span className="text-sm font-semibold text-[var(--ch-text-primary)]">
                                {label}
                              </span>
                              <span
                                className={`text-xs font-semibold ${lowConfidence ? "text-[var(--ch-warning-text)]" : "text-[var(--ch-text-muted)]"}`}
                              >
                                {Math.round(getConfidence(path) * 100)}%
                              </span>
                            </div>
                            <input
                              value={formatInputValue(reviewedPayload.standard_specs?.[field])}
                              onChange={(event) =>
                                updateObjectField("standard_specs", field, event.target.value)
                              }
                              className="w-full rounded-xl border border-[var(--ch-border)] bg-white px-3 py-2 text-sm text-[var(--ch-text-primary)] outline-none transition focus:border-[var(--ch-accent)]"
                            />
                          </label>
                        );
                      })}
                    </div>
                  </section>

                  <section className="rounded-[1.6rem] border border-[var(--ch-border)] bg-[var(--ch-surface)] p-5">
                    <div className="flex items-center justify-between gap-4">
                      <p className="text-xs font-semibold uppercase tracking-[0.22em] text-[var(--ch-text-muted)]">
                        6. Upgrades
                      </p>
                      <button
                        type="button"
                        onClick={() => addArrayRow("upgrades")}
                        className="rounded-full border border-[var(--ch-border)] bg-white px-4 py-2 text-xs font-semibold uppercase tracking-[0.16em] text-[var(--ch-text-secondary)] transition hover:bg-[var(--ch-surface-muted)]"
                      >
                        Add upgrade
                      </button>
                    </div>
                    <div className="mt-4 space-y-4">
                      {reviewedPayload.upgrades.map((upgrade, index) => (
                        <article
                          key={`upgrade-${index}`}
                          className="grid gap-4 rounded-[1.2rem] border border-[var(--ch-border)] bg-white p-4 sm:grid-cols-2"
                        >
                          {upgradeFieldLabels.map(([field, label]) => {
                            const path = `upgrades.${index}.${field}`;
                            const lowConfidence = isLowConfidence(path);
                            return (
                              <label key={field}>
                                <div className="mb-2 flex items-center justify-between gap-4">
                                  <span className="text-sm font-semibold text-[var(--ch-text-primary)]">
                                    {label}
                                  </span>
                                  <span
                                    className={`text-xs font-semibold ${lowConfidence ? "text-[var(--ch-warning-text)]" : "text-[var(--ch-text-muted)]"}`}
                                  >
                                    {Math.round(getConfidence(path) * 100)}%
                                  </span>
                                </div>
                                <input
                                  value={formatInputValue(upgrade[field])}
                                  onChange={(event) =>
                                    updateArrayField("upgrades", index, field, event.target.value)
                                  }
                                  className="w-full rounded-xl border border-[var(--ch-border)] bg-white px-3 py-2 text-sm text-[var(--ch-text-primary)] outline-none transition focus:border-[var(--ch-accent)]"
                                />
                              </label>
                            );
                          })}
                        </article>
                      ))}
                    </div>
                  </section>

                  <section className="rounded-[1.6rem] border border-[var(--ch-border)] bg-[var(--ch-surface)] p-5">
                    <p className="text-xs font-semibold uppercase tracking-[0.22em] text-[var(--ch-text-muted)]">
                      7. Financial and Landscaping
                    </p>
                    <div className="mt-4 grid gap-4 sm:grid-cols-2">
                      {[...financialFields.map((field) => ["financial", ...field] as const), ...landscapingFields.map((field) => ["landscaping", ...field] as const)].map(
                        ([section, field, label]) => {
                          const path = `${section}.${field}`;
                          const lowConfidence = isLowConfidence(path);
                          const sectionPayload = reviewedPayload[section];
                          const sectionObject =
                            !Array.isArray(sectionPayload) && typeof sectionPayload === "object"
                              ? sectionPayload
                              : {};
                          return (
                            <label
                              key={path}
                              className={`rounded-[1.2rem] border px-4 py-3 ${lowConfidence ? "border-amber-300 bg-amber-50" : "border-[var(--ch-border)] bg-white"}`}
                            >
                              <div className="mb-2 flex items-center justify-between gap-4">
                                <span className="text-sm font-semibold text-[var(--ch-text-primary)]">
                                  {label}
                                </span>
                                <span
                                  className={`text-xs font-semibold ${lowConfidence ? "text-[var(--ch-warning-text)]" : "text-[var(--ch-text-muted)]"}`}
                                >
                                  {Math.round(getConfidence(path) * 100)}%
                                </span>
                              </div>
                              <input
                                value={formatInputValue(sectionObject[field])}
                                onChange={(event) =>
                                  updateObjectField(section, field, event.target.value)
                                }
                                className="w-full rounded-xl border border-[var(--ch-border)] bg-white px-3 py-2 text-sm text-[var(--ch-text-primary)] outline-none transition focus:border-[var(--ch-accent)]"
                              />
                            </label>
                          );
                        },
                      )}
                    </div>
                  </section>
                </>
              ) : null}

              <section className="rounded-[1.6rem] border border-[var(--ch-border)] bg-[var(--ch-surface)] p-5">
                <div className="flex items-center justify-between gap-4">
                  <p className="text-xs font-semibold uppercase tracking-[0.22em] text-[var(--ch-text-muted)]">
                    {isSaleOtp ? "8. Notable Clauses" : "5. Notable Clauses"}
                  </p>
                  <button
                    type="button"
                    onClick={() => addArrayRow("notable_clauses")}
                    className="rounded-full border border-[var(--ch-border)] bg-white px-4 py-2 text-xs font-semibold uppercase tracking-[0.16em] text-[var(--ch-text-secondary)] transition hover:bg-[var(--ch-surface-muted)]"
                  >
                    Add clause
                  </button>
                </div>
                <div className="mt-4 space-y-3">
                  {reviewedPayload.notable_clauses.length === 0 ? (
                    <div className="rounded-[1.2rem] border border-dashed border-[var(--ch-border)] bg-white px-4 py-6 text-sm text-[var(--ch-text-muted)]">
                      No notable clauses extracted.
                    </div>
                  ) : (
                    reviewedPayload.notable_clauses.map((clause, index) => (
                      <article
                        key={`${clause.clause_ref || "clause"}-${index}`}
                        className="grid gap-4 rounded-[1.2rem] border border-[var(--ch-border)] bg-white px-4 py-4 sm:grid-cols-2"
                      >
                        {clauseFieldLabels.map(([field, label]) => {
                          const path = `notable_clauses.${index}.${field}`;
                          const lowConfidence = isLowConfidence(path);
                          const isTextField = field === "text";
                          return (
                            <label
                              key={field}
                              className={isTextField ? "sm:col-span-2" : undefined}
                            >
                              <div className="mb-2 flex items-center justify-between gap-4">
                                <span className="text-sm font-semibold text-[var(--ch-text-primary)]">
                                  {label}
                                </span>
                                <span
                                  className={`text-xs font-semibold ${lowConfidence ? "text-[var(--ch-warning-text)]" : "text-[var(--ch-text-muted)]"}`}
                                >
                                  {Math.round(getConfidence(path) * 100)}%
                                </span>
                              </div>
                              {isTextField ? (
                                <textarea
                                  value={formatInputValue(clause[field])}
                                  onChange={(event) =>
                                    updateArrayField("notable_clauses", index, field, event.target.value)
                                  }
                                  rows={4}
                                  className="w-full rounded-xl border border-[var(--ch-border)] bg-white px-3 py-2 text-sm text-[var(--ch-text-primary)] outline-none transition focus:border-[var(--ch-accent)]"
                                />
                              ) : (
                                <input
                                  value={formatInputValue(clause[field])}
                                  onChange={(event) =>
                                    updateArrayField("notable_clauses", index, field, event.target.value)
                                  }
                                  className="w-full rounded-xl border border-[var(--ch-border)] bg-white px-3 py-2 text-sm text-[var(--ch-text-primary)] outline-none transition focus:border-[var(--ch-accent)]"
                                />
                              )}
                            </label>
                          );
                        })}
                      </article>
                    ))
                  )}
                </div>
              </section>
            </div>
          </div>

          <div className="border-t border-[var(--ch-border)] bg-[var(--ch-surface)] px-4 py-4 shadow-lg sm:px-5">
            <div className="flex flex-col gap-4">
              {!hasScrolledToEnd ? (
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[var(--ch-warning-text)]">
                  Scroll through all sections to enable approval.
                </p>
              ) : (
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[var(--ch-success-text)]">
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
                    className="mt-2 w-full rounded-xl border border-rose-200 bg-white px-3 py-2 text-sm text-[var(--ch-text-primary)] outline-none transition focus:border-rose-400"
                    placeholder="Explain what blocked review approval."
                  />
                  <div className="mt-3 flex flex-wrap gap-3">
                    <button
                      type="button"
                      onClick={() => void handleSubmit("rejected")}
                      disabled={submitting}
                      className="rounded-full bg-rose-700 px-5 py-3 text-sm font-semibold text-[var(--ch-text-primary)] transition hover:bg-rose-600 disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      {submitting ? "Submitting..." : "Submit rejection"}
                    </button>
                    <button
                      type="button"
                      onClick={() => setShowRejectForm(false)}
                      className="rounded-full border border-[var(--ch-border)] px-5 py-3 text-sm font-semibold text-[var(--ch-text-secondary)] transition hover:bg-[var(--ch-surface-muted)]"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              ) : null}

              <div className="flex flex-wrap items-center justify-between gap-3">
                <p className="text-sm text-[var(--ch-text-muted)]">
                  Edited fields: <span className="font-semibold text-[var(--ch-text-primary)]">{editedFields.length}</span>
                </p>
                <div className="flex flex-wrap gap-3">
                  <button
                    type="button"
                    onClick={() => {
                      setShowRejectForm(true);
                      setError(null);
                    }}
                    disabled={submitting}
                    className="rounded-full bg-rose-700 px-5 py-3 text-sm font-semibold text-[var(--ch-text-primary)] transition hover:bg-rose-600 disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    Reject
                  </button>
                  <button
                    type="button"
                    onClick={() => void handleSubmit("approved")}
                    disabled={submitting || !hasScrolledToEnd || !!success?.promotion}
                    className="rounded-full bg-[var(--ch-success-text)] px-5 py-3 text-sm font-semibold text-[var(--ch-text-primary)] transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-60"
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
