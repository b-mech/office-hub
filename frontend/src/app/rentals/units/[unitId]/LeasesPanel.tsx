"use client";

import { useCallback, useEffect, useState } from "react";
import * as leases from "@/lib/api/lease-agreements";
import type { UnitOverview } from "@/lib/api/rental-units";
import { formatDate, leaseStatusLabel, leaseStatusTone, TONE_CLASS } from "@/lib/rentals-ux";

const money = (value: string | null) => value === null ? "—"
  : new Intl.NumberFormat("en-CA", { style: "currency", currency: "CAD", maximumFractionDigits: 0 }).format(Number(value));
const day = (value: string | null) => formatDate(value, "open");

function StatusPill({ status }: { status: string }) {
  return <span className={`inline-flex rounded-full border px-2 py-0.5 text-xs font-semibold ${TONE_CLASS[leaseStatusTone(status)]}`}>{leaseStatusLabel(status)}</span>;
}

/** Rent-roll lease records (rental_leases): the same source the Rental Units list uses. */
function LeaseHistory({ overview }: { overview: UnitOverview | null }) {
  if (!overview) return <p className="text-sm text-[var(--ch-text-muted)]">Loading lease history…</p>;
  const recordedMismatch = overview.leases.filter((lease) => lease.status === "active" && lease.display_status !== "active");
  return <div className="rounded-2xl border bg-[var(--ch-surface)] p-5">
    <div className="flex flex-wrap items-baseline justify-between gap-2"><h2 className="text-xl font-bold">Lease history</h2><p className="text-xs text-[var(--ch-text-muted)]">From the rent roll · status shown from lease dates</p></div>
    {overview.leases.length === 0 ? <p className="py-6 text-sm text-[var(--ch-text-muted)]">No lease records for this unit yet.</p> : <div className="mt-3 overflow-x-auto"><table className="min-w-full text-sm">
      <thead className="text-left text-xs uppercase tracking-wide text-[var(--ch-text-muted)]"><tr><th className="py-2 pr-4">Term</th><th className="py-2 pr-4">Tenant(s)</th><th className="py-2 pr-4 text-right">Net rent</th><th className="py-2 pr-4">Status</th></tr></thead>
      <tbody>{overview.leases.map((lease) => <tr key={lease.id} className={`border-t align-top ${lease.is_current ? "bg-[var(--ch-surface-strong)]" : ""}`}>
        <td className="py-2 pr-4">{day(lease.lease_start)} → {day(lease.lease_end)}{lease.is_current ? <div className="text-xs font-semibold text-[var(--ch-accent)]">Current lease</div> : null}</td>
        <td className="py-2 pr-4">{lease.tenants.length ? lease.tenants.join(", ") : <span className="text-[var(--ch-text-muted)]">—</span>}</td>
        <td className="py-2 pr-4 text-right">{money(lease.net_rent)}</td>
        <td className="py-2 pr-4"><StatusPill status={lease.display_status} />{lease.display_status !== lease.status ? <div className="mt-1 text-xs text-[var(--ch-text-muted)]">Recorded as {leaseStatusLabel(lease.status).toLowerCase()} · #{lease.id}</div> : <div className="mt-1 text-xs text-[var(--ch-text-muted)]">#{lease.id}</div>}</td>
      </tr>)}</tbody></table></div>}
    {recordedMismatch.length ? <p className="mt-3 rounded-lg border border-[var(--ch-warning-border)] bg-[var(--ch-warning-bg)] p-2 text-xs text-[var(--ch-warning-text)]">{recordedMismatch.length} record{recordedMismatch.length > 1 ? "s are" : " is"} still marked active but {recordedMismatch.length > 1 ? "have" : "has"} ended or not started. Nothing was changed; update the rent roll to fix the recorded status.</p> : null}
  </div>;
}

export default function LeasesPanel({ unitId, overview }: { unitId: number; overview: UnitOverview | null }) {
  const [data, setData] = useState<leases.UnitLeases | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [municipality, setMunicipality] = useState("");
  const [multiplex, setMultiplex] = useState(false);
  const [condo, setCondo] = useState(false);
  const refresh = useCallback(() => leases.unitLeases(unitId).then(result => {
    setData(result); setMunicipality(result.property.municipality || "");
    setMultiplex(result.property.is_multiplex); setCondo(result.property.is_condo);
  }).catch(cause => setError(cause.message)), [unitId]);
  useEffect(() => { void refresh(); }, [refresh]);

  async function create(copyId?: string, startFrom?: leases.LeaseStartFrom) {
    setBusy(true); setError("");
    try {
      const lease = await leases.createLease(unitId, copyId, startFrom);
      window.location.href = `/rentals/leases/${lease.id}`;
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not create lease"); }
    finally { setBusy(false); }
  }

  async function updateProperty() {
    if (!data) return;
    setBusy(true); setError("");
    try {
      await leases.updateProperty(data.property.id, { municipality, is_multiplex: multiplex,
        is_condo: condo, lease_utility_override: data.property.lease_utility_override });
      await refresh();
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not save property settings"); }
    finally { setBusy(false); }
  }

  async function voidLease(id: string) {
    const reason = window.prompt("Reason for voiding this lease (required):");
    if (!reason?.trim()) return;
    setBusy(true); setError("");
    try { await leases.voidLease(id, reason); await refresh(); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Could not void lease"); }
    finally { setBusy(false); }
  }

  async function resend(id: string) {
    setBusy(true); setError("");
    try { await leases.resendLease(id); await refresh(); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Could not resend lease"); }
    finally { setBusy(false); }
  }

  const hasTenancy = Boolean(overview?.leases.length || data?.has_imported_lease);
  return <section className="mt-6 space-y-5">
    {error && <p role="alert" className="rounded-xl bg-red-50 p-3 text-red-800">{error}</p>}
    <LeaseHistory overview={overview} />
    {data && <>
      <div className="rounded-2xl border bg-[var(--ch-surface)] p-5">
        <div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="text-xl font-bold">E-lease agreements</h2><p className="text-xs text-[var(--ch-text-muted)]">Leases drafted and signed in Office Hub (DocuSign)</p></div><div className="flex flex-wrap gap-2">
          <button disabled={busy} onClick={() => void create(undefined, "blank")} className="rounded-lg bg-[var(--ch-accent)] px-4 py-2 font-bold text-white disabled:opacity-50" title="Blank form with a one-year term starting next month">New blank lease</button>
          {data.leases.length > 0 ? <button disabled={busy} onClick={() => void create(data.leases[0].id)} className="rounded-lg border px-4 py-2 font-semibold disabled:opacity-50">Copy last e-lease</button>
            : hasTenancy ? <button disabled={busy} onClick={() => void create(undefined, "tenancy")} className="rounded-lg border px-4 py-2 font-semibold disabled:opacity-50" title="Tenants and rent from the current lease; the term is reset to a new one-year term">Renew current tenancy</button> : null}
        </div></div>
        <div className="mt-4 divide-y">{data.leases.length === 0 ? <p className="py-6 text-sm text-[var(--ch-text-muted)]">No e-lease agreements for this unit yet.{overview?.leases.length ? " The lease history above comes from the rent roll." : ""}</p> : data.leases.map(lease => <div key={lease.id} className="flex flex-wrap items-center gap-3 py-4 text-sm">
          <div className="min-w-48 flex-1"><strong>{(lease.tenants || []).map(t => t.name).join(" & ") || "Draft lease"}</strong><p className="text-[var(--ch-text-muted)]">{formatDate(lease.created_at)} · {lease.context.fixed_start || lease.context.periodic_start ? formatDate(String(lease.context.fixed_start || lease.context.periodic_start)) : "Term pending"}{lease.context.fixed_end ? ` – ${formatDate(String(lease.context.fixed_end))}` : ""}</p></div>
          <span className="rounded-full bg-slate-100 px-3 py-1 font-semibold">{lease.display_status}</span>
          <a className="font-semibold underline" href={`/rentals/leases/${lease.id}`}>Open</a>
          {lease.draft_pdf_key && <a className="font-semibold underline" href={leases.pdfUrl(lease.id)} target="_blank" rel="noreferrer">View PDF</a>}
          {(lease.status === "sent" || lease.status === "delivered") && <><button disabled={busy} className="underline" onClick={() => void resend(lease.id)}>Resend</button><button disabled={busy} className="text-red-700 underline" onClick={() => void voidLease(lease.id)}>Void</button></>}
          {lease.signed_pdf_box_url && <a className="font-semibold underline" href={lease.signed_pdf_box_url} target="_blank" rel="noreferrer">Signed copy in Box</a>}
        </div>)}</div>
      </div>
      <details className="rounded-2xl border bg-[var(--ch-surface)] p-5">
        <summary className="cursor-pointer font-semibold">Property lease settings · {data.property.municipality || "municipality not set"}{data.property.is_multiplex ? " · multiplex" : ""}{data.property.is_condo ? " · condo" : ""}</summary>
        <p className="mt-2 text-sm text-[var(--ch-text-muted)]">Confirm the municipality and property type before creating a lease. These set utility wording.</p>
        <div className="mt-4 flex flex-wrap items-end gap-4">
          <label className="text-sm font-semibold">Municipality <input className="mt-1 block rounded-lg border p-2" value={municipality} onChange={e => setMunicipality(e.target.value)} /></label>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={multiplex} onChange={e => setMultiplex(e.target.checked)} />Multiplex</label>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={condo} onChange={e => setCondo(e.target.checked)} />Condominium</label>
          <button disabled={busy || !municipality.trim()} onClick={() => void updateProperty()} className="rounded-lg border px-3 py-2 font-semibold disabled:opacity-50">Save property settings</button>
        </div>
      </details>
    </>}
  </section>;
}
