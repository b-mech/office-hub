"use client";

import { useState } from "react";

import type { LenderPayload } from "@/types/lenders";


const emptyLender: LenderPayload = {
  name: "",
  contact_name: "",
  contact_email: "",
  contact_phone: "",
  notes: "",
};

export function LenderForm({
  initialValue,
  submitLabel,
  onSubmit,
  onCancel,
}: {
  initialValue?: LenderPayload;
  submitLabel: string;
  onSubmit: (payload: LenderPayload) => Promise<void>;
  onCancel?: () => void;
}) {
  const [value, setValue] = useState<LenderPayload>(initialValue || emptyLender);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await onSubmit(cleanPayload(value));
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "Could not save lender.");
    } finally {
      setSaving(false);
    }
  }

  function setField(field: keyof LenderPayload, fieldValue: string) {
    setValue((current) => ({ ...current, [field]: fieldValue }));
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      <div className="grid gap-4 md:grid-cols-2">
        <Field
          label="Lender name"
          required
          value={value.name}
          onChange={(next) => setField("name", next)}
        />
        <Field
          label="Contact name"
          value={value.contact_name || ""}
          onChange={(next) => setField("contact_name", next)}
        />
        <Field
          label="Contact email"
          type="email"
          value={value.contact_email || ""}
          onChange={(next) => setField("contact_email", next)}
        />
        <Field
          label="Contact phone"
          type="tel"
          value={value.contact_phone || ""}
          onChange={(next) => setField("contact_phone", next)}
        />
      </div>
      <label className="block text-sm font-medium text-[var(--ch-text-secondary)]">
        Notes
        <textarea
          value={value.notes || ""}
          onChange={(event) => setField("notes", event.target.value)}
          rows={4}
          className="mt-1.5 w-full rounded-lg border border-[var(--ch-border)] bg-[var(--ch-surface)] px-3 py-2.5 text-[var(--ch-text-primary)] outline-none focus:border-[var(--ch-accent)] focus:ring-2 focus:ring-[var(--ch-focus-ring)]"
        />
      </label>
      {error ? (
        <p className="rounded-lg border border-[var(--ch-error-border)] bg-[var(--ch-error-bg)] px-3 py-2 text-sm text-[var(--ch-error-text)]">
          {error}
        </p>
      ) : null}
      <div className="flex justify-end gap-3">
        {onCancel ? (
          <button
            type="button"
            onClick={onCancel}
            className="rounded-lg border border-[var(--ch-border)] px-4 py-2 text-sm font-semibold text-[var(--ch-text-secondary)]"
          >
            Cancel
          </button>
        ) : null}
        <button
          type="submit"
          disabled={saving || !value.name.trim()}
          className="rounded-lg bg-[var(--ch-accent)] px-4 py-2 text-sm font-semibold text-[var(--ch-accent-text)] disabled:cursor-not-allowed disabled:opacity-50"
        >
          {saving ? "Saving..." : submitLabel}
        </button>
      </div>
    </form>
  );
}

function Field({
  label,
  value,
  onChange,
  type = "text",
  required = false,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  type?: string;
  required?: boolean;
}) {
  return (
    <label className="text-sm font-medium text-[var(--ch-text-secondary)]">
      {label}
      <input
        type={type}
        required={required}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="mt-1.5 w-full rounded-lg border border-[var(--ch-border)] bg-[var(--ch-surface)] px-3 py-2.5 text-[var(--ch-text-primary)] outline-none focus:border-[var(--ch-accent)] focus:ring-2 focus:ring-[var(--ch-focus-ring)]"
      />
    </label>
  );
}

function cleanPayload(value: LenderPayload): LenderPayload {
  return {
    name: value.name.trim(),
    contact_name: value.contact_name?.trim() || null,
    contact_email: value.contact_email?.trim() || null,
    contact_phone: value.contact_phone?.trim() || null,
    notes: value.notes?.trim() || null,
  };
}
