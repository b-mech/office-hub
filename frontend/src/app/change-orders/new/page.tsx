"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { getLots, type Lot } from "@/lib/api/costbook";
import {
  saveDraft,
  type ChangeOrderDraft,
  type ChangeOrderLineItem,
  type PaymentMethod,
} from "@/lib/api/change-orders";

const emptyLineItem: ChangeOrderLineItem = {
  description: "",
  amount: 0,
  is_credit: false,
};

const today = new Date().toISOString().slice(0, 10);

function suggestCoNumber() {
  const compactDate = today.replaceAll("-", "");
  return `CO-${compactDate}-001`;
}

function emptyDraft(): ChangeOrderDraft {
  return {
    address: "",
    client_name: "",
    customer_email: "",
    co_number: suggestCoNumber(),
    date: today,
    line_items: [{ ...emptyLineItem }],
    payment_method: "due_upon_receipt",
    notes: "",
  };
}

function parseDraftParam(value: string | null): ChangeOrderDraft | null {
  if (!value) return null;
  try {
    const parsed = JSON.parse(value) as Partial<ChangeOrderDraft>;
    return {
      address: parsed.address || "",
      client_name: parsed.client_name || "",
      customer_email: parsed.customer_email || "",
      co_number: parsed.co_number || suggestCoNumber(),
      date: parsed.date || today,
      line_items: Array.isArray(parsed.line_items) && parsed.line_items.length > 0
        ? parsed.line_items.map((item) => ({
            description: item.description || "",
            amount: Number(item.amount) || 0,
            is_credit: Boolean(item.is_credit),
          }))
        : [{ ...emptyLineItem }],
      payment_method: normalizePaymentMethod(parsed.payment_method),
      notes: parsed.notes || "",
    };
  } catch {
    return null;
  }
}

function normalizePaymentMethod(value: unknown): PaymentMethod {
  return value === "add_to_mortgage" ? "add_to_mortgage" : "due_upon_receipt";
}

function money(value: number) {
  return new Intl.NumberFormat("en-CA", {
    style: "currency",
    currency: "CAD",
  }).format(value);
}

function saveErrorMessage(saveError: unknown) {
  if (saveError instanceof TypeError && saveError.message === "Failed to fetch") {
    return "Could not reach the Office Hub API. Check that the backend and Postgres are running.";
  }
  return saveError instanceof Error ? saveError.message : "Could not save change order draft.";
}

function lineItemTotal(item: ChangeOrderLineItem) {
  return item.is_credit ? -Math.abs(item.amount || 0) : Math.abs(item.amount || 0);
}

function NewChangeOrderForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const parsedDraft = useMemo(() => parseDraftParam(searchParams.get("draft")), [searchParams]);
  const [draft, setDraft] = useState<ChangeOrderDraft>(() => parsedDraft || emptyDraft());
  const [lots, setLots] = useState<Lot[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedDraftId, setSavedDraftId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getLots()
      .then((result) => {
        if (!cancelled) setLots(result);
      })
      .catch(() => {
        if (!cancelled) setLots([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const subtotal = useMemo(
    () => draft.line_items.reduce((sum, item) => sum + lineItemTotal(item), 0),
    [draft.line_items],
  );
  const gst = subtotal * 0.05;
  const grandTotal = subtotal + gst;
  const canSave = draft.address.trim() && draft.client_name.trim() && !saving;

  function updateField<K extends keyof ChangeOrderDraft>(field: K, value: ChangeOrderDraft[K]) {
    setSavedDraftId(null);
    setDraft((current) => ({ ...current, [field]: value }));
  }

  function updateLineItem(index: number, patch: Partial<ChangeOrderLineItem>) {
    setSavedDraftId(null);
    setDraft((current) => ({
      ...current,
      line_items: current.line_items.map((item, itemIndex) =>
        itemIndex === index ? { ...item, ...patch } : item,
      ),
    }));
  }

  function addLineItem() {
    setSavedDraftId(null);
    setDraft((current) => ({
      ...current,
      line_items: [...current.line_items, { ...emptyLineItem }],
    }));
  }

  function removeLineItem(index: number) {
    setSavedDraftId(null);
    setDraft((current) => ({
      ...current,
      line_items: current.line_items.length === 1
        ? [{ ...emptyLineItem }]
        : current.line_items.filter((_, itemIndex) => itemIndex !== index),
    }));
  }

  async function handleSave() {
    if (!canSave) return;
    setSaving(true);
    setError(null);
    setSavedDraftId(null);
    try {
      const payload = {
        ...draft,
        line_items: draft.line_items.filter((item) => item.description.trim() || item.amount),
      };
      const result = await saveDraft(payload);
      setSavedDraftId(result.id);
      setSaving(false);
    } catch (saveError) {
      setError(saveErrorMessage(saveError));
      setSaving(false);
    }
  }

  return (
    <main
      className="change-order-page min-h-screen pb-28 text-[var(--ch-text-primary)]"
      style={{ backgroundColor: "var(--ch-page-bg)" }}
    >
      <div className="mx-auto flex max-w-6xl flex-col gap-6 px-6 py-8 lg:px-10">
        <header className="flex flex-col gap-2 border-b border-[var(--ch-border)] pb-6">
          <p className="text-xs font-semibold uppercase tracking-[0.24em] text-[var(--ch-text-muted)]">
            Office Hub
          </p>
          <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
            <div>
              <h1 className="text-3xl font-semibold tracking-tight text-[var(--ch-text-primary)]">
                New Change Order
              </h1>
              <p className="mt-2 text-sm text-[var(--ch-text-muted)]">
                Review the extracted email details before saving this change order draft.
              </p>
            </div>
            <div className="rounded-full border border-[var(--ch-accent)] bg-[var(--ch-accent-soft)] px-4 py-2 text-sm text-[var(--ch-accent)]">
              Draft
            </div>
          </div>
        </header>

        {parsedDraft && (
          <section className="rounded-xl border border-[var(--ch-accent)] bg-[var(--ch-accent-soft)] px-4 py-3 text-sm text-[var(--ch-accent)]">
            Pre-filled from Kristy&apos;s email — please review before saving
          </section>
        )}

        {error && (
          <section className="rounded-xl border border-red-400/30 bg-red-500/10 px-4 py-3 text-sm text-red-200">
            {error}
          </section>
        )}

        {savedDraftId && (
          <section className="rounded-xl border border-emerald-400/30 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-100">
            Draft saved. Reference: {savedDraftId}
          </section>
        )}

        <section className="rounded-2xl border border-[var(--ch-border)] bg-[var(--ch-surface)] p-5">
          <div className="mb-5 flex items-center justify-between gap-4">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.2em] text-[var(--ch-text-muted)]">
                Header
              </p>
              <h2 className="mt-1 text-lg font-semibold text-[var(--ch-text-primary)]">Change order details</h2>
            </div>
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <label className="flex flex-col gap-2 text-sm text-[var(--ch-text-secondary)]">
              Address
              <input
                required
                list="change-order-lot-options"
                value={draft.address}
                onChange={(event) => updateField("address", event.target.value)}
                placeholder="Search lots or enter an address"
                className="rounded-lg border border-[var(--ch-border)] bg-[var(--ch-surface)] px-3 py-2.5 text-[var(--ch-text-primary)] outline-none placeholder:text-[var(--ch-text-muted)] focus:border-[var(--ch-accent)] focus:ring-2 focus:ring-[var(--ch-focus-ring)]"
              />
              <datalist id="change-order-lot-options">
                {lots.map((lot) => (
                  <option key={lot.id} value={lot.address}>
                    {lot.community}
                  </option>
                ))}
              </datalist>
            </label>

            <label className="flex flex-col gap-2 text-sm text-[var(--ch-text-secondary)]">
              Client Name
              <input
                required
                value={draft.client_name}
                onChange={(event) => updateField("client_name", event.target.value)}
                className="rounded-lg border border-[var(--ch-border)] bg-[var(--ch-surface)] px-3 py-2.5 text-[var(--ch-text-primary)] outline-none placeholder:text-[var(--ch-text-muted)] focus:border-[var(--ch-accent)] focus:ring-2 focus:ring-[var(--ch-focus-ring)]"
              />
            </label>

            <label className="flex flex-col gap-2 text-sm text-[var(--ch-text-secondary)]">
              Client Email
              <input
                type="email"
                value={draft.customer_email || ""}
                onChange={(event) => updateField("customer_email", event.target.value)}
                placeholder="client@email.com"
                className="rounded-lg border border-[var(--ch-border)] bg-[var(--ch-surface)] px-3 py-2.5 text-[var(--ch-text-primary)] outline-none placeholder:text-[var(--ch-text-muted)] focus:border-[var(--ch-accent)] focus:ring-2 focus:ring-[var(--ch-focus-ring)]"
              />
            </label>

            <label className="flex flex-col gap-2 text-sm text-[var(--ch-text-secondary)]">
              CO Number
              <input
                value={draft.co_number || ""}
                onChange={(event) => updateField("co_number", event.target.value)}
                className="rounded-lg border border-[var(--ch-border)] bg-[var(--ch-surface)] px-3 py-2.5 text-[var(--ch-text-primary)] outline-none focus:border-[var(--ch-accent)] focus:ring-2 focus:ring-[var(--ch-focus-ring)]"
              />
            </label>

            <label className="flex flex-col gap-2 text-sm text-[var(--ch-text-secondary)]">
              Date
              <input
                type="date"
                value={draft.date || today}
                onChange={(event) => updateField("date", event.target.value)}
                className="rounded-lg border border-[var(--ch-border)] bg-[var(--ch-surface)] px-3 py-2.5 text-[var(--ch-text-primary)] outline-none focus:border-[var(--ch-accent)] focus:ring-2 focus:ring-[var(--ch-focus-ring)]"
              />
            </label>
          </div>

          <div className="mt-5">
            <p className="mb-2 text-sm text-[var(--ch-text-secondary)]">Payment Method</p>
            <div className="inline-flex rounded-lg border border-[var(--ch-border)] bg-[var(--ch-surface)] p-1">
              {[
                ["add_to_mortgage", "Add to Mortgage"],
                ["due_upon_receipt", "Due upon receipt"],
              ].map(([value, label]) => (
                <button
                  key={value}
                  type="button"
                  onClick={() => updateField("payment_method", value as PaymentMethod)}
                  className={`rounded-md px-4 py-2 text-sm font-medium ${
                    draft.payment_method === value
                      ? "bg-[var(--ch-accent)] text-[var(--ch-accent-text)]"
                      : "text-[var(--ch-text-secondary)] hover:text-[var(--ch-text-primary)]"
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
        </section>

        <section className="rounded-2xl border border-[var(--ch-border)] bg-[var(--ch-surface)] p-5">
          <div className="mb-5 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.2em] text-[var(--ch-text-muted)]">
                Line Items
              </p>
              <h2 className="mt-1 text-lg font-semibold text-[var(--ch-text-primary)]">Charges and credits</h2>
            </div>
            <button
              type="button"
              onClick={addLineItem}
              className="rounded-lg border border-[var(--ch-accent)] bg-[var(--ch-accent-soft)] px-4 py-2 text-sm font-semibold text-[var(--ch-accent)] hover:bg-[var(--ch-accent-hover)]"
            >
              Add row
            </button>
          </div>

          <div className="overflow-x-auto">
            <div className="min-w-[760px] space-y-3">
              {draft.line_items.map((item, index) => (
                <div
                  key={index}
                  className="grid grid-cols-[1fr_150px_180px_44px] gap-3 rounded-xl border border-[var(--ch-border)] bg-[var(--ch-surface)] p-3"
                >
                  <input
                    value={item.description}
                    onChange={(event) => updateLineItem(index, { description: event.target.value })}
                    placeholder="Description"
                    className="rounded-lg border border-[var(--ch-border)] bg-[var(--ch-surface)] px-3 py-2.5 text-[var(--ch-text-primary)] outline-none placeholder:text-[var(--ch-text-muted)] focus:border-[var(--ch-accent)] focus:ring-2 focus:ring-[var(--ch-focus-ring)]"
                  />
                  <input
                    type="number"
                    min="0"
                    step="0.01"
                    value={item.amount || ""}
                    onChange={(event) => updateLineItem(index, { amount: Number(event.target.value) || 0 })}
                    placeholder="0.00"
                    className="rounded-lg border border-[var(--ch-border)] bg-[var(--ch-surface)] px-3 py-2.5 text-right text-[var(--ch-text-primary)] outline-none placeholder:text-[var(--ch-text-muted)] focus:border-[var(--ch-accent)] focus:ring-2 focus:ring-[var(--ch-focus-ring)]"
                  />
                  <div className="flex rounded-lg border border-[var(--ch-border)] bg-[var(--ch-surface)] p-1">
                    <button
                      type="button"
                      onClick={() => updateLineItem(index, { is_credit: false })}
                      className={`flex-1 rounded-md px-3 py-2 text-xs font-semibold ${
                        !item.is_credit ? "bg-[var(--ch-accent)] text-[var(--ch-accent-text)]" : "text-[var(--ch-text-secondary)]"
                      }`}
                    >
                      Charge
                    </button>
                    <button
                      type="button"
                      onClick={() => updateLineItem(index, { is_credit: true })}
                      className={`flex-1 rounded-md px-3 py-2 text-xs font-semibold ${
                        item.is_credit ? "bg-[var(--ch-accent)] text-[var(--ch-accent-text)]" : "text-[var(--ch-text-secondary)]"
                      }`}
                    >
                      Credit
                    </button>
                  </div>
                  <button
                    type="button"
                    onClick={() => removeLineItem(index)}
                    aria-label="Remove line item"
                    className="rounded-lg border border-[var(--ch-border)] text-xl leading-none text-[var(--ch-text-muted)] hover:border-red-400/35 hover:text-red-200"
                  >
                    ×
                  </button>
                </div>
              ))}
            </div>
          </div>

          <div className="mt-5 ml-auto grid max-w-sm gap-2 rounded-xl border border-[var(--ch-border)] bg-[var(--ch-surface)] p-4 text-sm">
            <div className="flex justify-between text-[var(--ch-text-secondary)]">
              <span>Subtotal</span>
              <span>{money(subtotal)}</span>
            </div>
            <div className="flex justify-between text-[var(--ch-text-secondary)]">
              <span>GST (5%)</span>
              <span>{money(gst)}</span>
            </div>
            <div className="flex justify-between border-t border-[var(--ch-border)] pt-2 text-base font-semibold text-[var(--ch-text-primary)]">
              <span>Grand Total</span>
              <span>{money(grandTotal)}</span>
            </div>
          </div>
        </section>

        <section className="rounded-2xl border border-[var(--ch-border)] bg-[var(--ch-surface)] p-5">
          <label className="flex flex-col gap-2 text-sm text-[var(--ch-text-secondary)]">
            Notes
            <textarea
              value={draft.notes}
              onChange={(event) => updateField("notes", event.target.value)}
              rows={6}
              className="resize-y rounded-lg border border-[var(--ch-border)] bg-[var(--ch-surface)] px-3 py-2.5 text-[var(--ch-text-primary)] outline-none placeholder:text-[var(--ch-text-muted)] focus:border-[var(--ch-accent)] focus:ring-2 focus:ring-[var(--ch-focus-ring)]"
            />
          </label>
        </section>
      </div>

      <footer className="fixed inset-x-0 bottom-0 border-t border-[var(--ch-border)] bg-[color:var(--ch-page-bg)]/95 px-6 py-4 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-3">
          <button
            type="button"
            onClick={() => router.back()}
            className="rounded-lg border border-[var(--ch-border)] px-4 py-2 text-sm font-semibold text-[var(--ch-text-secondary)] hover:text-[var(--ch-text-primary)]"
          >
            Cancel
          </button>
          <div className="flex items-center gap-3">
            {savedDraftId && (
              <p className="text-sm font-medium text-emerald-200" role="status">
                Draft saved: {savedDraftId}
              </p>
            )}
            <button
              type="button"
              disabled={!canSave}
              onClick={handleSave}
              className="rounded-lg bg-[var(--ch-accent)] px-5 py-2.5 text-sm font-bold text-[var(--ch-accent-text)] hover:brightness-105 disabled:cursor-not-allowed disabled:opacity-45"
            >
              {saving ? "Saving..." : savedDraftId ? "Saved" : "Save Draft"}
            </button>
          </div>
        </div>
      </footer>
    </main>
  );
}

export default function NewChangeOrderPage() {
  return (
    <Suspense
      fallback={
        <main className="min-h-screen bg-[var(--ch-page-bg)] px-6 py-8 text-[var(--ch-text-primary)]">
          <div className="mx-auto max-w-6xl text-sm text-[var(--ch-text-muted)]">
            Loading change order...
          </div>
        </main>
      }
    >
      <NewChangeOrderForm />
    </Suspense>
  );
}
