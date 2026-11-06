"use client";

import { useCallback, useEffect, useState } from "react";
import * as leases from "@/lib/api/lease-agreements";

export default function LeasesPanel({ unitId }: { unitId: number }) {
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

  async function create(copyId?: string) {
    setBusy(true); setError("");
    try {
      const lease = await leases.createLease(unitId, copyId);
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

  return <section className="mt-6 space-y-5">
    {error && <p role="alert" className="rounded-xl bg-red-50 p-3 text-red-800">{error}</p>}
    {data && <>
      <div className="rounded-2xl border bg-[var(--ch-surface)] p-5">
        <h2 className="text-lg font-bold">{data.property.street_address}{data.unit.unit_label ? ` · ${data.unit.unit_label}` : ""}</h2>
        <p className="mt-1 text-sm text-[var(--ch-text-muted)]">Confirm the municipality and property type before creating a lease. These set utility wording.</p>
        <div className="mt-4 flex flex-wrap items-end gap-4">
          <label className="text-sm font-semibold">Municipality <input className="mt-1 block rounded-lg border p-2" value={municipality} onChange={e => setMunicipality(e.target.value)} /></label>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={multiplex} onChange={e => setMultiplex(e.target.checked)} />Multiplex</label>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={condo} onChange={e => setCondo(e.target.checked)} />Condominium</label>
          <button disabled={busy || !municipality.trim()} onClick={() => void updateProperty()} className="rounded-lg border px-3 py-2 font-semibold disabled:opacity-50">Save property settings</button>
        </div>
      </div>
      <div className="rounded-2xl border bg-[var(--ch-surface)] p-5">
        <div className="flex flex-wrap items-center justify-between gap-3"><h2 className="text-xl font-bold">Lease agreements</h2><div className="flex flex-wrap gap-2"><button disabled={busy} onClick={() => void create()} className="rounded-lg bg-[var(--ch-accent)] px-4 py-2 font-bold text-white">New lease</button>{(data.leases.length > 0 || data.has_imported_lease) && <button disabled={busy} onClick={() => void create(data.leases[0]?.id)} className="rounded-lg border px-4 py-2 font-semibold">Start from last lease</button>}</div></div>
        <div className="mt-4 divide-y">{data.leases.length === 0 ? <p className="py-6 text-sm text-[var(--ch-text-muted)]">No lease agreements for this unit yet.</p> : data.leases.map(lease => <div key={lease.id} className="flex flex-wrap items-center gap-3 py-4 text-sm">
          <div className="min-w-48 flex-1"><strong>{(lease.tenants || []).map(t => t.name).join(" & ") || "Draft lease"}</strong><p className="text-[var(--ch-text-muted)]">{new Date(lease.created_at).toLocaleDateString()} · {String(lease.context.fixed_start || lease.context.periodic_start || "Term pending")}{lease.context.fixed_end ? ` – ${lease.context.fixed_end}` : ""}</p></div>
          <span className="rounded-full bg-slate-100 px-3 py-1 font-semibold">{lease.display_status}</span>
          <a className="font-semibold underline" href={`/rentals/leases/${lease.id}`}>Open</a>
          {lease.draft_pdf_key && <a className="font-semibold underline" href={leases.pdfUrl(lease.id)} target="_blank" rel="noreferrer">View PDF</a>}
          {(lease.status === "sent" || lease.status === "delivered") && <><button disabled={busy} className="underline" onClick={() => void resend(lease.id)}>Resend</button><button disabled={busy} className="text-red-700 underline" onClick={() => void voidLease(lease.id)}>Void</button></>}
          {lease.signed_pdf_box_url && <a className="font-semibold underline" href={lease.signed_pdf_box_url} target="_blank" rel="noreferrer">Signed copy in Box</a>}
        </div>)}</div>
      </div>
    </>}
  </section>;
}
