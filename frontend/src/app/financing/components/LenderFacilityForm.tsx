import { useEffect, useMemo, useState } from "react";
import { createLender, getLenders } from "@/lib/api/lenders";
import type { FacilityAssignmentPayload, FacilityPayload, FinancingProperty, LenderType } from "@/types/financing";
import type { LenderListItem } from "@/types/lenders";

const lenders: LenderType[] = ["SCU", "PRO", "STRIDE", "RSU", "CLIENT", "OTHER"];
const money = new Intl.NumberFormat("en-CA", { style: "currency", currency: "CAD", maximumFractionDigits: 0 });

function numeric(value: unknown): string {
  return value == null ? "" : String(value);
}

export function LenderFacilityForm({
  property,
  onSave,
  mode = "edit",
  onAssign,
  onCancel,
}: {
  property: FinancingProperty;
  onSave?: (payload: FacilityPayload) => Promise<void>;
  mode?: "edit" | "assignment";
  onAssign?: (payload: FacilityAssignmentPayload) => Promise<void>;
  onCancel?: () => void;
}) {
  const isAssignment = mode === "assignment";
  const [values, setValues] = useState<FacilityPayload>({
    property_id: property.property_id,
    lender_type: property.lender_type,
    lender_name: property.lender_name || "",
    total_facility: numeric(property.total_facility),
    opening_balance: numeric(property.opening_balance),
    rate: numeric(property.rate),
    already_drawn: numeric(property.already_drawn ?? 0),
    draw_eligible_override: "",
    requested_draw_amount: numeric(property.requested_draw_amount),
    requested_draw_as_of: property.requested_draw_as_of || "",
    commitment_source: property.commitment_source || "",
    commitment_confirmed_at: property.commitment_confirmed_at?.slice(0, 16) || "",
    last_draw_date: property.last_draw_date || "",
    last_draw_amount: numeric(property.last_draw_amount),
    account_number: property.account_number || "",
    account_title: property.account_title || "",
    account_type: property.account_type || "",
    current_balance: numeric(property.current_balance),
    outstanding_balance: numeric(property.outstanding_balance),
    account_currency: property.account_currency || "CAD",
    maturity_date: property.maturity_date || "",
    member_number: property.member_number || "",
    next_interest_payment_date: property.next_interest_payment_date || "",
    next_payment_date: property.next_payment_date || "",
    account_nickname: property.account_nickname || "",
    open_date: property.open_date || "",
    original_loan_amount: numeric(property.original_loan_amount),
    payment_schedule: property.payment_schedule || "",
    term_length_days: property.term_length_days == null ? "" : String(property.term_length_days),
    notes: property.notes || "",
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [availableLenders, setAvailableLenders] = useState<LenderListItem[]>([]);
  const [lenderId, setLenderId] = useState("");
  const [lenderSearch, setLenderSearch] = useState("");
  const [addingLender, setAddingLender] = useState(false);
  const [newLenderName, setNewLenderName] = useState("");
  const [creatingLender, setCreatingLender] = useState(false);

  useEffect(() => {
    if (!isAssignment) return;
    let active = true;
    getLenders()
      .then((result) => {
        if (active) setAvailableLenders(result);
      })
      .catch((loadError) => {
        if (active) setError(loadError instanceof Error ? loadError.message : "Failed to load lenders");
      });
    return () => {
      active = false;
    };
  }, [isAssignment]);

  const filteredLenders = useMemo(() => {
    const query = lenderSearch.trim().toLowerCase();
    return query
      ? availableLenders.filter((lender) => lender.name.toLowerCase().includes(query))
      : availableLenders;
  }, [availableLenders, lenderSearch]);

  const derived = useMemo(() => {
    const opening = Number(values.opening_balance || 0);
    const drawn = Number(values.already_drawn || 0);
    return { remaining: opening - drawn };
  }, [values]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      const cleaned = cleanPayload(values);
      if (isAssignment) {
        if (!lenderId) throw new Error("Select a lender before assigning the facility.");
        if (!onAssign) throw new Error("Assignment is not configured.");
        await onAssign(toAssignmentPayload(cleaned, lenderId));
      } else {
        if (!onSave) throw new Error("Facility editing is not configured.");
        await onSave(cleaned);
      }
      setSaved(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save facility");
    } finally {
      setSaving(false);
    }
  }

  function setField<K extends keyof FacilityPayload>(key: K, value: FacilityPayload[K]) {
    setSaved(false);
    setValues((current) => ({ ...current, [key]: value }));
  }

  async function addLender() {
    const name = newLenderName.trim();
    if (!name) return;
    setCreatingLender(true);
    setError(null);
    try {
      const lender = await createLender({ name });
      setAvailableLenders((current) => [...current, lender].sort((a, b) => a.name.localeCompare(b.name)));
      setLenderId(lender.id);
      setLenderSearch(lender.name);
      setNewLenderName("");
      setAddingLender(false);
    } catch (createError) {
      setError(createError instanceof Error ? createError.message : "Failed to create lender");
    } finally {
      setCreatingLender(false);
    }
  }

  const facilityType = values.lender_type;
  const requiresOpeningBalance = ["SCU", "STRIDE", "RSU"].includes(facilityType);

  return (
    <form onSubmit={submit} className="space-y-3 rounded-lg border border-[var(--ch-border)] bg-[var(--ch-surface-muted)] p-4">
      <div className="grid gap-3 md:grid-cols-2">
        <label className="text-xs font-medium text-[var(--ch-text-muted)]">
          Lender type
          <select value={values.lender_type} onChange={(event) => setField("lender_type", event.target.value as LenderType)} className="mt-1 w-full rounded-md border border-[var(--ch-border)] bg-[var(--ch-surface-strong)] px-3 py-2 text-sm">
            {lenders.map((lender) => <option key={lender} value={lender}>{lender}</option>)}
          </select>
        </label>
        {isAssignment ? (
          <div className="space-y-2 md:col-span-2">
            <label className="block text-xs font-medium text-[var(--ch-text-muted)]">
              Search lenders
              <input
                value={lenderSearch}
                onChange={(event) => setLenderSearch(event.target.value)}
                placeholder="Type a lender name"
                className="mt-1 w-full rounded-md border border-[var(--ch-border)] bg-[var(--ch-surface-strong)] px-3 py-2 text-sm"
              />
            </label>
            <select
              value={lenderId}
              onChange={(event) => setLenderId(event.target.value)}
              className="w-full rounded-md border border-[var(--ch-border)] bg-[var(--ch-surface-strong)] px-3 py-2 text-sm"
            >
              <option value="">Select lender</option>
              {filteredLenders.map((lender) => (
                <option key={lender.id} value={lender.id}>{lender.name}</option>
              ))}
            </select>
            {!addingLender ? (
              <button type="button" onClick={() => setAddingLender(true)} className="text-xs font-semibold text-[var(--ch-accent)] hover:underline">
                + Add new lender
              </button>
            ) : (
              <div className="flex gap-2">
                <input
                  value={newLenderName}
                  onChange={(event) => setNewLenderName(event.target.value)}
                  placeholder="New lender name"
                  className="min-w-0 flex-1 rounded-md border border-[var(--ch-border)] bg-[var(--ch-surface-strong)] px-3 py-2 text-sm"
                />
                <button type="button" disabled={!newLenderName.trim() || creatingLender} onClick={() => void addLender()} className="rounded-md bg-[var(--ch-accent)] px-3 py-2 text-xs font-semibold text-[var(--ch-accent-text)] disabled:opacity-50">
                  {creatingLender ? "Adding..." : "Add"}
                </button>
                <button type="button" onClick={() => setAddingLender(false)} className="rounded-md border border-[var(--ch-border)] px-3 py-2 text-xs">Cancel</button>
              </div>
            )}
          </div>
        ) : (
          <Field label="Lender name" value={values.lender_name || ""} onChange={(value) => setField("lender_name", value)} />
        )}

        {isAssignment && requiresOpeningBalance ? (
          <Field label="Opening balance" required type="number" value={String(values.opening_balance || "")} onChange={(value) => setField("opening_balance", value)} />
        ) : null}
        {isAssignment && facilityType === "PRO" ? (
          <>
            <Field label="Total commitment" type="number" value={String(values.total_facility || "")} onChange={(value) => setField("total_facility", value)} />
            <Field label="Rate" type="number" step="0.0001" value={String(values.rate || "")} onChange={(value) => setField("rate", value)} />
            <Field label="Already drawn" type="number" value={String(values.already_drawn || "")} onChange={(value) => setField("already_drawn", value)} />
            <Field label="Eligible override" type="number" value={String(values.draw_eligible_override || "")} onChange={(value) => setField("draw_eligible_override", value)} />
            <Field label="Requested draw" type="number" value={String(values.requested_draw_amount || "")} onChange={(value) => setField("requested_draw_amount", value)} />
            <Field label="Requested as of" type="date" value={values.requested_draw_as_of || ""} onChange={(value) => setField("requested_draw_as_of", value)} />
            <Field label="Commitment source" value={values.commitment_source || ""} onChange={(value) => setField("commitment_source", value)} />
            <Field label="Commitment confirmed" type="datetime-local" value={values.commitment_confirmed_at || ""} onChange={(value) => setField("commitment_confirmed_at", value)} />
          </>
        ) : null}
        {!isAssignment ? (
          <>
            <Field label="Total facility" type="number" value={String(values.total_facility || "")} onChange={(value) => setField("total_facility", value)} />
            <Field label="Opening balance" type="number" value={String(values.opening_balance || "")} onChange={(value) => setField("opening_balance", value)} />
            <Field label="Rate" type="number" step="0.0001" value={String(values.rate || "")} onChange={(value) => setField("rate", value)} />
            <Field label="Already drawn" type="number" value={String(values.already_drawn || "")} onChange={(value) => setField("already_drawn", value)} />
            <Field label="Last draw date" type="date" value={values.last_draw_date || ""} onChange={(value) => setField("last_draw_date", value)} />
            <Field label="Last draw amount" type="number" value={String(values.last_draw_amount || "")} onChange={(value) => setField("last_draw_amount", value)} />
          </>
        ) : null}
      </div>
      {isAssignment && facilityType === "CLIENT" ? (
        <p className="rounded-md border border-[var(--ch-border)] bg-[var(--ch-surface)] px-3 py-2 text-sm text-[var(--ch-text-secondary)]">
          Assign the CLIENT facility first. Then use the existing OTP panel in this drawer to upload and review the draw schedule.
        </p>
      ) : null}
      {!isAssignment ? <div className="border-t border-[var(--ch-border)] pt-3">
        <h3 className="mb-3 text-sm font-semibold text-[var(--ch-text-primary)]">Account details</h3>
        <div className="grid gap-3 md:grid-cols-2">
          <Field label="Account number" value={values.account_number || ""} onChange={(value) => setField("account_number", value)} />
          <Field label="Member number" value={values.member_number || ""} onChange={(value) => setField("member_number", value)} />
          <Field label="Account title" value={values.account_title || ""} onChange={(value) => setField("account_title", value)} />
          <Field label="Account type" value={values.account_type || ""} onChange={(value) => setField("account_type", value)} />
          <Field label="Current balance" type="number" value={String(values.current_balance || "")} onChange={(value) => setField("current_balance", value)} />
          <Field label="Outstanding balance" type="number" value={String(values.outstanding_balance || "")} onChange={(value) => setField("outstanding_balance", value)} />
          <Field label="Currency" value={values.account_currency || ""} onChange={(value) => setField("account_currency", value)} />
          <Field label="Original loan amount" type="number" value={String(values.original_loan_amount || "")} onChange={(value) => setField("original_loan_amount", value)} />
          <Field label="Maturity date" type="date" value={values.maturity_date || ""} onChange={(value) => setField("maturity_date", value)} />
          <Field label="Open date" type="date" value={values.open_date || ""} onChange={(value) => setField("open_date", value)} />
          <Field label="Next interest payment date" type="date" value={values.next_interest_payment_date || ""} onChange={(value) => setField("next_interest_payment_date", value)} />
          <Field label="Next payment date" type="date" value={values.next_payment_date || ""} onChange={(value) => setField("next_payment_date", value)} />
          <Field label="Payment schedule" value={values.payment_schedule || ""} onChange={(value) => setField("payment_schedule", value)} />
          <Field label="Term length days" type="number" value={String(values.term_length_days || "")} onChange={(value) => setField("term_length_days", value)} />
          <label className="text-xs font-medium text-[var(--ch-text-muted)] md:col-span-2">
            Account nickname
            <input
              value={values.account_nickname || ""}
              onChange={(event) => setField("account_nickname", event.target.value)}
              className="mt-1 w-full rounded-md border border-[var(--ch-border)] bg-[var(--ch-surface-strong)] px-3 py-2 text-sm"
            />
          </label>
        </div>
      </div> : null}
      <label className="block text-xs font-medium text-[var(--ch-text-muted)]">
        Notes
        <textarea
          value={values.notes || ""}
          onChange={(event) => setField("notes", event.target.value)}
          className="mt-1 min-h-20 w-full rounded-md border border-[var(--ch-border)] bg-[var(--ch-surface-strong)] px-3 py-2 text-sm"
        />
      </label>
      {error ? (
        <p className="rounded-md border border-[var(--ch-error-border)] bg-[var(--ch-error-bg)] px-3 py-2 text-sm text-[var(--ch-error-text)]">
          {error}
        </p>
      ) : null}
      {saved ? (
        <p
          className="rounded-md border border-[var(--ch-success-border)] bg-[var(--ch-success-bg)] px-3 py-2 text-sm text-[var(--ch-success-text)]"
          role="status"
        >
          Facility saved successfully.
        </p>
      ) : null}
      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-[var(--ch-border)] pt-3">
        <div className="text-xs text-[var(--ch-text-muted)]">
          {!isAssignment ? <>
          Funds remaining <span className="font-semibold text-[var(--ch-text-primary)]">{money.format(derived.remaining)}</span>
          <span className="ml-3">Draw eligible now <span className="font-semibold text-[var(--ch-accent)]">{property.draw_eligible == null ? "-" : money.format(Number(property.draw_eligible))}</span></span>
          </> : <span>One active facility is allowed per property.</span>}
        </div>
        <div className="flex gap-2">
          {isAssignment && onCancel ? <button type="button" onClick={onCancel} className="rounded-md border border-[var(--ch-border)] px-4 py-2 text-sm font-semibold">Cancel</button> : null}
          <button disabled={saving || (isAssignment && !lenderId)} className="rounded-md bg-[var(--ch-accent)] px-4 py-2 text-sm font-semibold text-[var(--ch-accent-text)] disabled:opacity-60">
            {saving ? "Saving..." : saved ? "Saved" : isAssignment ? "Assign facility" : "Save facility"}
          </button>
        </div>
      </div>
    </form>
  );
}

function cleanPayload(values: FacilityPayload): FacilityPayload {
  return {
    ...values,
    lender_name: optionalString(values.lender_name),
    total_facility: optionalValue(values.total_facility),
    opening_balance: optionalValue(values.opening_balance),
    rate: optionalValue(values.rate),
    already_drawn: optionalValue(values.already_drawn) ?? 0,
    draw_eligible_override: optionalValue(values.draw_eligible_override),
    requested_draw_amount: optionalValue(values.requested_draw_amount),
    requested_draw_as_of: optionalValue(values.requested_draw_as_of) as string | null,
    commitment_source: optionalString(values.commitment_source),
    commitment_confirmed_at: optionalValue(values.commitment_confirmed_at) as string | null,
    last_draw_date: optionalValue(values.last_draw_date) as string | null,
    last_draw_amount: optionalValue(values.last_draw_amount),
    account_number: optionalString(values.account_number),
    account_title: optionalString(values.account_title),
    account_type: optionalString(values.account_type),
    current_balance: optionalValue(values.current_balance),
    outstanding_balance: optionalValue(values.outstanding_balance),
    account_currency: optionalString(values.account_currency),
    maturity_date: optionalValue(values.maturity_date) as string | null,
    member_number: optionalString(values.member_number),
    next_interest_payment_date: optionalValue(values.next_interest_payment_date) as string | null,
    next_payment_date: optionalValue(values.next_payment_date) as string | null,
    account_nickname: optionalString(values.account_nickname),
    open_date: optionalValue(values.open_date) as string | null,
    original_loan_amount: optionalValue(values.original_loan_amount),
    payment_schedule: optionalString(values.payment_schedule),
    term_length_days: optionalInteger(values.term_length_days),
    notes: optionalString(values.notes),
  };
}

function toAssignmentPayload(values: FacilityPayload, lenderId: string): FacilityAssignmentPayload {
  return {
    facility_type: values.lender_type,
    lender_id: lenderId,
    total_facility: values.total_facility,
    opening_balance: values.opening_balance,
    rate: values.rate,
    already_drawn: values.already_drawn,
    draw_eligible_override: values.draw_eligible_override,
    requested_draw_amount: values.requested_draw_amount,
    requested_draw_as_of: values.requested_draw_as_of,
    commitment_source: values.commitment_source,
    commitment_confirmed_at: values.commitment_confirmed_at,
    notes: values.notes,
  };
}

function optionalValue(value: string | number | null | undefined): string | number | null {
  return value === "" || value == null ? null : value;
}

function optionalString(value: string | null | undefined): string | null {
  const trimmed = value?.trim();
  return trimmed ? trimmed : null;
}

function optionalInteger(value: string | number | null | undefined): number | null {
  if (value === "" || value == null) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? Math.trunc(parsed) : null;
}

function Field({
  label,
  value,
  onChange,
  type = "text",
  step,
  required = false,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  type?: string;
  step?: string;
  required?: boolean;
}) {
  return (
    <label className="text-xs font-medium text-[var(--ch-text-muted)]">
      {label}
      <input
        type={type}
        step={step}
        required={required}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="mt-1 w-full rounded-md border border-[var(--ch-border)] bg-[var(--ch-surface-strong)] px-3 py-2 text-sm"
      />
    </label>
  );
}
