"use client";

import { use, useEffect, useState } from "react";
import * as maintenance from "@/lib/api/maintenance";
import LeasesPanel from "./LeasesPanel";

export default function UnitMaintenancePage({ params }: { params: Promise<{unitId:string}> }) {
  const { unitId: rawUnitId } = use(params);
  const unitId = Number(rawUnitId);
  const [status, setStatus] = useState<maintenance.QrStatus | null>(null);
  const [generated, setGenerated] = useState<{token:string;url:string} | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [tab, setTab] = useState<"maintenance" | "leases">("maintenance");
  useEffect(() => { if (new URLSearchParams(window.location.search).get("tab") === "leases") setTab("leases"); }, []);

  useEffect(() => { maintenance.qrStatus(unitId).then(setStatus).catch((cause) => setError(cause.message)); }, [unitId]);

  async function rotate() {
    if (status?.active && !window.confirm("Rotate this QR? The previous printed code will stop working.")) return;
    setBusy(true); setError("");
    try {
      const result = await maintenance.rotateQr(unitId);
      setGenerated(result);
      setStatus(await maintenance.qrStatus(unitId));
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not generate QR"); }
    finally { setBusy(false); }
  }

  return <main className="mx-auto max-w-2xl p-6">
    <a href="/rentals/units" className="text-sm text-[var(--ch-accent)]">← Rental units</a>
    <h1 className="mt-3 text-3xl font-bold">Rental unit</h1>
    {status ? <p className="mt-2 flex flex-wrap gap-3 text-sm font-semibold"><a href={`/rentals/maintenance?property_id=${status.property_id}`} className="text-[var(--ch-accent)]">Open maintenance tickets</a><a href={`/rentals/maintenance/new?property_id=${status.property_id}&unit_id=${unitId}`} className="text-[var(--ch-accent)]">+ New ticket for this unit</a></p> : null}
    <nav className="mt-5 flex gap-2" aria-label="Unit tabs"><button onClick={() => setTab("maintenance")} className={`rounded-lg px-4 py-2 font-semibold ${tab === "maintenance" ? "bg-[var(--ch-accent)] text-white" : "border"}`}>Maintenance</button><button onClick={() => setTab("leases")} className={`rounded-lg px-4 py-2 font-semibold ${tab === "leases" ? "bg-[var(--ch-accent)] text-white" : "border"}`}>Leases</button></nav>
    {tab === "leases" ? <LeasesPanel unitId={unitId} /> : <>
    <section className="mt-6 rounded-2xl border bg-[var(--ch-surface)] p-5">
      <div className="flex items-start justify-between gap-4"><div><h2 className="text-xl font-bold">Maintenance QR</h2><p className="mt-1 text-sm text-[var(--ch-text-muted)]">{status?.active ? "An active code exists for this unit." : "No active code exists."}</p></div>{status?.rotation_recommended ? <span className="rounded-full bg-amber-100 px-3 py-1 text-xs font-bold text-amber-900">Consider rotating QR</span> : null}</div>
      {error ? <p className="mt-4 text-[var(--ch-error-text)]">{error}</p> : null}
      {generated ? <div className="mt-4 rounded-xl bg-[var(--ch-page-bg)] p-4"><p className="text-sm font-bold">New link — shown only now</p><p className="mt-2 break-all text-sm">{generated.url}</p><button className="mt-3 rounded-lg border px-3 py-2 font-semibold" onClick={() => navigator.clipboard.writeText(generated.url)}>Copy link</button></div> : null}
      <div className="mt-5 flex flex-wrap gap-3"><button disabled={busy} onClick={() => void rotate()} className="rounded-xl bg-[var(--ch-accent)] px-4 py-3 font-bold text-white disabled:opacity-50">{status?.active ? "Rotate" : "Generate"}</button>{generated ? <button disabled={busy} onClick={() => void maintenance.printQr(unitId, generated.token).then((blob) => maintenance.download(blob, `maintenance-unit-${unitId}.pdf`)).catch((cause) => setError(cause.message))} className="rounded-xl border px-4 py-3 font-bold">Download printable</button> : null}{status ? <button disabled={busy} onClick={() => { if (window.confirm("Generate and rotate QR codes for every unit at this property?")) void maintenance.printProperty(status.property_id).then((blob) => maintenance.download(blob, `maintenance-property-${status.property_id}.pdf`)).catch((cause) => setError(cause.message)); }} className="rounded-xl border px-4 py-3 font-bold">Bulk property PDF</button> : null}</div>
      {status?.active && !generated ? <p className="mt-4 text-xs text-[var(--ch-text-muted)]">Because tokens are stored only as secure hashes, rotate to reveal a new printable link.</p> : null}
    </section>
    </>}
  </main>;
}
