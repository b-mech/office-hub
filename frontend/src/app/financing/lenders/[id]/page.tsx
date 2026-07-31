"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ArrowLeft, Building2, Trash2 } from "lucide-react";

import { deleteLender, getLender, updateLender } from "@/lib/api/lenders";
import type { LenderDetail, LenderPayload } from "@/types/lenders";
import { LenderForm } from "../LenderForm";


export default function LenderDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [lender, setLender] = useState<LenderDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    let active = true;
    getLender(id)
      .then((result) => {
        if (active) setLender(result);
      })
      .catch((loadError) => {
        if (active) setError(loadError instanceof Error ? loadError.message : "Could not load lender.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [id]);

  async function save(payload: LenderPayload) {
    const updated = await updateLender(id, payload);
    setLender(updated);
    setNotice("Lender details saved.");
  }

  async function remove() {
    if (!lender || lender.facilities.length > 0) return;
    if (!window.confirm(`Delete ${lender.name}? This cannot be undone.`)) return;
    setDeleting(true);
    setError(null);
    try {
      await deleteLender(lender.id);
      router.push("/financing/lenders");
    } catch (deleteError) {
      setError(deleteError instanceof Error ? deleteError.message : "Could not delete lender.");
      setDeleting(false);
    }
  }

  if (loading) {
    return <main className="min-h-screen bg-[var(--ch-page-bg)] p-8 text-sm text-[var(--ch-text-muted)]">Loading lender...</main>;
  }
  if (error && !lender) {
    return <main className="min-h-screen bg-[var(--ch-page-bg)] p-8 text-sm text-[var(--ch-error-text)]">{error}</main>;
  }
  if (!lender) return null;

  const deleteDisabledReason = lender.facilities.length > 0
    ? `Cannot delete while ${lender.facilities.length} linked facilit${lender.facilities.length === 1 ? "y exists" : "ies exist"}.`
    : null;

  return (
    <main className="min-h-screen bg-[var(--ch-page-bg)] px-6 py-8 text-[var(--ch-text-primary)] lg:px-10">
      <div className="mx-auto max-w-5xl space-y-6">
        <header className="border-b border-[var(--ch-border)] pb-6">
          <Link href="/financing/lenders" className="inline-flex items-center gap-2 text-sm text-[var(--ch-text-muted)] hover:text-[var(--ch-text-primary)]">
            <ArrowLeft className="h-4 w-4" aria-hidden="true" /> Back to lenders
          </Link>
          <h1 className="mt-4 text-3xl font-semibold tracking-tight">{lender.name}</h1>
          <p className="mt-2 text-sm text-[var(--ch-text-muted)]">{lender.active_facility_count} active linked facilit{lender.active_facility_count === 1 ? "y" : "ies"}</p>
        </header>

        {notice ? <p className="rounded-lg border border-[var(--ch-success-border)] bg-[var(--ch-success-bg)] px-3 py-2 text-sm text-[var(--ch-success-text)]">{notice}</p> : null}
        {error ? <p className="rounded-lg border border-[var(--ch-error-border)] bg-[var(--ch-error-bg)] px-3 py-2 text-sm text-[var(--ch-error-text)]">{error}</p> : null}

        <section className="rounded-xl border border-[var(--ch-border)] bg-[var(--ch-surface)] p-5">
          <h2 className="mb-4 text-lg font-semibold">Lender information</h2>
          <LenderForm
            key={lender.updated_at}
            submitLabel="Save changes"
            initialValue={{
              name: lender.name,
              contact_name: lender.contact_name,
              contact_email: lender.contact_email,
              contact_phone: lender.contact_phone,
              notes: lender.notes,
            }}
            onSubmit={save}
          />
        </section>

        <section className="overflow-hidden rounded-xl border border-[var(--ch-border)] bg-[var(--ch-surface)]">
          <div className="border-b border-[var(--ch-border)] px-5 py-4">
            <h2 className="text-lg font-semibold">Linked properties and facilities</h2>
          </div>
          {lender.facilities.length === 0 ? (
            <div className="grid place-items-center gap-2 px-6 py-12 text-center">
              <Building2 className="h-8 w-8 text-[var(--ch-text-muted)]" aria-hidden="true" />
              <p className="font-medium">No facilities are linked to this lender.</p>
            </div>
          ) : (
            <div className="divide-y divide-[var(--ch-border)]">
              {lender.facilities.map((facility) => {
                const content = (
                  <>
                    <div>
                      <p className="font-semibold">{facility.property_address || "Unlinked property"}</p>
                      <p className="mt-1 text-xs text-[var(--ch-text-muted)]">{facility.lender_type} · {facility.status}</p>
                    </div>
                    <div className="text-right text-sm text-[var(--ch-text-secondary)]">
                      <p>{formatMoney(facility.total_facility) || "No facility total"}</p>
                      <p className="mt-1 text-xs text-[var(--ch-text-muted)]">Opening: {formatMoney(facility.opening_balance) || "—"}</p>
                    </div>
                  </>
                );
                return facility.property_id ? (
                  <Link
                    key={facility.facility_id}
                    href={`/financing?property_id=${facility.property_id}`}
                    className="flex items-center justify-between gap-4 px-5 py-4 hover:bg-[var(--ch-surface-muted)]"
                  >
                    {content}
                  </Link>
                ) : (
                  <div key={facility.facility_id} className="flex items-center justify-between gap-4 px-5 py-4">
                    {content}
                  </div>
                );
              })}
            </div>
          )}
        </section>

        <section className="rounded-xl border border-[var(--ch-error-border)] bg-[var(--ch-surface)] p-5">
          <h2 className="font-semibold">Delete lender</h2>
          <p className="mt-1 text-sm text-[var(--ch-text-muted)]">{deleteDisabledReason || "Delete this lender if it is no longer needed."}</p>
          <button
            type="button"
            disabled={Boolean(deleteDisabledReason) || deleting}
            title={deleteDisabledReason || undefined}
            onClick={() => void remove()}
            className="mt-4 inline-flex items-center gap-2 rounded-lg border border-[var(--ch-error-border)] px-4 py-2 text-sm font-semibold text-[var(--ch-error-text)] disabled:cursor-not-allowed disabled:opacity-45"
          >
            <Trash2 className="h-4 w-4" aria-hidden="true" />
            {deleting ? "Deleting..." : "Delete lender"}
          </button>
        </section>
      </div>
    </main>
  );
}

function formatMoney(value?: string | null): string | null {
  if (value == null) return null;
  return new Intl.NumberFormat("en-CA", { style: "currency", currency: "CAD", maximumFractionDigits: 0 }).format(Number(value));
}
