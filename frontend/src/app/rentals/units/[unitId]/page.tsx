"use client";

import Link from "next/link";
import { use, useCallback, useEffect, useState } from "react";
import * as maintenance from "@/lib/api/maintenance";
import { getUnitOverview, type UnitOverview } from "@/lib/api/rental-units";
import LeasesPanel from "./LeasesPanel";

type Tab = "maintenance" | "leases";

function UnitHeader({ unitId, overview, tab, onTab }: { unitId: number; overview: UnitOverview | null; tab: Tab; onTab: (tab: Tab) => void }) {
  const address = overview?.property.street_address;
  const unitName = overview?.unit.display_label;
  const propertyHref = overview ? `/rentals/units?property_id=${overview.property.id}` : "/rentals/units";
  return <header className="border-b border-[var(--ch-border)] pb-4">
    <nav aria-label="Breadcrumb" className="flex flex-wrap items-center gap-1 text-sm text-[var(--ch-text-muted)]">
      <Link href="/rentals" className="hover:text-[var(--ch-accent)]">Rentals</Link><span aria-hidden>/</span>
      <Link href="/rentals/units" className="hover:text-[var(--ch-accent)]">Units</Link><span aria-hidden>/</span>
      {address ? <><Link href={propertyHref} className="hover:text-[var(--ch-accent)]">{address}</Link><span aria-hidden>/</span></> : null}
      <span className="font-semibold text-[var(--ch-text-primary)]" aria-current="page">{unitName || `Unit #${unitId}`}</span>
    </nav>
    <Link href={propertyHref} className="mt-3 inline-block text-sm font-semibold text-[var(--ch-accent)]">← Back to {address ? `${address} units` : "rental units"}</Link>
    <h1 className="mt-2 text-3xl font-bold">{address ? <>{address} <span className="text-[var(--ch-text-muted)]">·</span> {unitName}</> : "Loading unit…"}</h1>
    {overview ? <p className="mt-1 text-sm text-[var(--ch-text-muted)]">
      {[overview.property.group_name, overview.property.city].filter(Boolean).join(" · ")}
      {" · "}Property #{overview.property.id} · Unit #{overview.unit.id}{overview.unit.is_basement ? " · Basement" : ""}
      {overview.property.address_is_shared ? <span className="ml-2 rounded-full border border-[var(--ch-warning-border)] bg-[var(--ch-warning-bg)] px-2 py-0.5 text-xs font-semibold text-[var(--ch-warning-text)]">Another property has this address</span> : null}
    </p> : null}
    <p className="mt-2 flex flex-wrap gap-3 text-sm font-semibold">
      {overview ? <><Link href={`/rentals/maintenance?property_id=${overview.property.id}`} className="text-[var(--ch-accent)]">Open maintenance tickets</Link>
        <Link href={`/rentals/maintenance/new?property_id=${overview.property.id}&unit_id=${unitId}`} className="text-[var(--ch-accent)]">+ New ticket for this unit</Link>
        <Link href={`/rentals/inspections?property_id=${overview.property.id}`} className="text-[var(--ch-accent)]">Inspections</Link></> : null}
    </p>
    <nav className="mt-4 flex gap-2" aria-label="Unit tabs" role="tablist">
      {(["maintenance", "leases"] as const).map((name) => <button key={name} type="button" role="tab" aria-selected={tab === name} onClick={() => onTab(name)} className={`rounded-lg px-4 py-2 font-semibold ${tab === name ? "bg-[var(--ch-accent)] text-white" : "border"}`}>{name === "maintenance" ? "Maintenance & QR" : "Leases"}</button>)}
    </nav>
  </header>;
}

export default function UnitPage({ params }: { params: Promise<{unitId:string}> }) {
  const { unitId: rawUnitId } = use(params);
  const unitId = Number(rawUnitId);
  const [status, setStatus] = useState<maintenance.QrStatus | null>(null);
  const [overview, setOverview] = useState<UnitOverview | null>(null);
  const [generated, setGenerated] = useState<{token:string;url:string} | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [tab, setTabState] = useState<Tab>("maintenance");
  useEffect(() => {
    const timer = window.setTimeout(() => { if (new URLSearchParams(window.location.search).get("tab") === "leases") setTabState("leases"); }, 0);
    return () => window.clearTimeout(timer);
  }, []);
  const setTab = useCallback((next: Tab) => {
    setTabState(next);
    const url = new URL(window.location.href);
    if (next === "leases") url.searchParams.set("tab", "leases"); else url.searchParams.delete("tab");
    window.history.replaceState(null, "", `${url.pathname}${url.search}`);
  }, []);

  const refreshOverview = useCallback(() => getUnitOverview(unitId).then(setOverview).catch((cause) => setError(cause.message)), [unitId]);
  useEffect(() => { void refreshOverview(); }, [refreshOverview]);
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

  return <main className="mx-auto max-w-3xl p-6">
    <UnitHeader unitId={unitId} overview={overview} tab={tab} onTab={setTab} />
    {tab === "leases" ? <LeasesPanel unitId={unitId} overview={overview} /> : <>
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
