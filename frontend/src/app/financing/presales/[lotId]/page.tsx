"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { presaleDownloadUrl, presalesApi, type PresaleDetail } from "@/lib/api/presales";

const LABELS: Record<string, string> = {
  approval_letter: "Approval letter", appraisal: "Formal appraisal", otp_land: "OTP (Land)",
  otp_sale: "OTP (Sale)", stamped_plans: "Stamped plans", prelim_budget: "Prelim budget",
  "lot.building_type": "Building type", "scu.capacity_headroom": "SCU capacity",
};

export default function PresaleLotPage() {
  const params = useParams<{ lotId: string }>();
  const lotId = params.lotId;
  const [detail, setDetail] = useState<PresaleDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const appraisalInput = useRef<HTMLInputElement>(null);
  const plansInput = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    try { setDetail(await presalesApi.lot(lotId)); setError(null); }
    catch (loadError) { setError(loadError instanceof Error ? loadError.message : "Could not load presale lot"); }
    finally { setLoading(false); }
  }, [lotId]);
  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  const columns = useMemo(() => {
    const docs = Object.values(detail?.readiness.partners || {}).flatMap((partner) => [...partner.package_docs, ...partner.missing]);
    return [...new Set(docs.length ? docs : Object.keys(detail?.package_items || {}))];
  }, [detail]);

  async function run(key: string, operation: () => Promise<unknown>) {
    setBusy(key); setError(null);
    try {
      const result = await operation();
      if (result && typeof result === "object" && "lot" in result) setDetail(result as PresaleDetail);
      else await load();
    }
    catch (actionError) { setError(actionError instanceof Error ? actionError.message : "Action failed"); }
    finally { setBusy(null); }
  }

  async function upload(item: "appraisal" | "stamped_plans", file?: File) {
    if (!file) return;
    await run(`upload-${item}`, () => presalesApi.uploadItem(lotId, item, file, item === "appraisal" ? { appraiser: "Red River Group" } : {}));
  }

  function openGmailDraft(subject: string, body: string, to = "") {
    window.open(
      `https://mail.google.com/mail/?view=cm&fs=1&to=${encodeURIComponent(to)}&su=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`,
      "_blank",
      "noopener,noreferrer",
    );
  }

  if (loading) return <main className="p-8 text-sm text-[var(--ch-text-muted)]">Loading presale financing…</main>;
  if (!detail) return <main className="p-8 text-sm text-[var(--ch-error-text)]">{error || "Lot not found"}</main>;

  const letter = detail.active_letter || detail.letter_history[0] || null;
  return (
    <main className="min-h-screen bg-[var(--ch-page-bg)] px-5 py-6 text-[var(--ch-text-primary)] md:px-8">
      <div className="mx-auto max-w-7xl space-y-5">
        <header className="flex flex-wrap items-start justify-between gap-4">
          <div><Link href="/financing/presales" className="text-xs font-semibold text-[var(--ch-accent)]">← Presales board</Link><h1 className="mt-2 text-2xl font-semibold">{detail.lot.address}</h1><p className="mt-1 text-sm text-[var(--ch-text-muted)]">{detail.buyer_names.join(", ") || "No purchaser recorded"}</p></div>
          <div className="flex gap-2">
            {detail.lot.sale_type !== "presale" ? <button type="button" disabled={Boolean(busy)} onClick={() => run("presale", () => presalesApi.updateLot(lotId, { sale_type: "presale" }))} className="rounded-lg bg-[var(--ch-accent)] px-4 py-2 text-sm font-semibold text-[var(--ch-accent-text)]">Mark as presale</button> : null}
            <Link href={`/lots/${lotId}/costbook`} className="rounded-lg border border-[var(--ch-border)] px-4 py-2 text-sm">Open costbook</Link>
          </div>
        </header>

        {error ? <p className="rounded-lg border border-[var(--ch-error-border)] bg-[var(--ch-error-bg)] px-3 py-2 text-sm text-[var(--ch-error-text)]">{error}</p> : null}

        <section className="grid gap-5 lg:grid-cols-2">
          <div className="rounded-xl border border-[var(--ch-border)] bg-[var(--ch-surface)] p-5">
            <div className="flex items-center justify-between"><h2 className="font-semibold">Approval letter</h2>{letter ? <span className="text-xs text-[var(--ch-text-muted)]">v{letter.version} · {letter.status.replaceAll("_", " ")}</span> : null}</div>
            {!letter ? (
              <div className="mt-4 rounded-lg border border-dashed border-[var(--ch-border)] p-4 text-sm">
                <p>No approval letter has been requested.</p>
                <p className="mt-1 text-[var(--ch-text-muted)]">Realtor: {detail.lot.realtor_name || "missing"} · {detail.lot.realtor_email || "email missing"}</p>
                <button type="button" disabled={Boolean(busy) || !detail.lot.realtor_email} onClick={() => run("request-letter", async () => {
                  const subject = encodeURIComponent(`Approval letter request — ${detail.lot.address}`);
                  const body = encodeURIComponent(`Hi ${detail.lot.realtor_name || "there"},\n\nPlease send the purchaser's lender approval letter for ${detail.lot.address} (${detail.buyer_names.join(", ")}).\n\nThank you.`);
                  window.open(`https://mail.google.com/mail/?view=cm&fs=1&to=${encodeURIComponent(detail.lot.realtor_email || "")}&su=${subject}&body=${body}`, "_blank", "noopener,noreferrer");
                  await presalesApi.markLetterRequested(lotId); await load();
                })} className="mt-3 rounded-md bg-[var(--ch-accent)] px-3 py-2 text-xs font-semibold text-[var(--ch-accent-text)] disabled:opacity-45">Draft request email</button>
              </div>
            ) : (
              <div className="mt-4 space-y-3 text-sm">
                <div className="grid grid-cols-2 gap-3"><Fact label="Lender" value={String(letter.extracted.lender_name || "—")} /><Fact label="Broker" value={String(letter.extracted.broker_name || "—")} /><Fact label="Approved" value={money(letter.extracted.approved_amount)} /><Fact label="Expires" value={String(letter.extracted.expiry_date || "—")} /><Fact label="Quality" value={letter.quality_score ? `${letter.quality_score}/10` : "—"} /><Fact label="Lender contacted" value={letter.lender_contacted_at ? dateText(letter.lender_contacted_at) : "No"} /></div>
                <div className="flex flex-wrap gap-2">{detail.quality_flags.map((flag) => <span key={flag.code} className="rounded-full border border-[var(--ch-warning-border)] bg-[var(--ch-warning-bg)] px-2 py-1 text-[11px] text-[var(--ch-warning-text)]">{flag.label}</span>)}</div>
                <div><h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--ch-text-muted)]">Conditions</h3>{(letter.extracted.conditions || []).length ? <ul className="mt-2 space-y-2">{(letter.extracted.conditions || []).map((condition, index) => <li key={`${condition.text}-${index}`} className="rounded-md border border-[var(--ch-border)] p-2"><p>{condition.text}</p><p className="mt-1 text-xs text-[var(--ch-text-muted)]">{condition.category.replaceAll("_", " ")}{condition.deadline ? ` · ${condition.deadline}` : ""}</p></li>)}</ul> : <p className="mt-1 text-[var(--ch-text-muted)]">No conditions.</p>}</div>
              </div>
            )}
          </div>

          <div className="rounded-xl border border-[var(--ch-border)] bg-[var(--ch-surface)] p-5">
            <h2 className="font-semibold">Package actions</h2>
            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              <Action title="Formal appraisal" status={lifecycle(detail, "appraisal")}><button onClick={() => run("order-appraisal", async () => { openGmailDraft(`Formal appraisal order — ${detail.lot.address}`, `Hello Red River Group,\n\nPlease prepare a formal appraisal for ${detail.lot.address}. The plans and OTP (Sale) are available in Office Hub for attachment.\n\nThank you.`); return presalesApi.markItem(lotId, "appraisal", "ordered"); })} className="text-xs font-semibold text-[var(--ch-accent)]">Draft order email</button><button onClick={() => appraisalInput.current?.click()} className="text-xs font-semibold text-[var(--ch-accent)]">Upload</button><input ref={appraisalInput} type="file" accept="application/pdf" hidden onChange={(event) => void upload("appraisal", event.target.files?.[0])} /></Action>
              <Action title="Prelim budget" status={lifecycle(detail, "prelim_budget")}><button onClick={() => run("request-budget", async () => { openGmailDraft(`Prelim budget request — ${detail.lot.address}`, `Hi Joan,\n\nPlease prepare the prelim budget for ${detail.lot.address}.\nBuilding type: ${detail.lot.building_type || "not set"}.\n\nThank you.`); return presalesApi.markItem(lotId, "prelim_budget", "requested"); })} className="text-xs font-semibold text-[var(--ch-accent)]">Draft request to Joan</button><Link href={`/lots/${lotId}/costbook`} className="text-xs font-semibold text-[var(--ch-accent)]">Open costbook</Link></Action>
              <Action title="Stamped plans" status={lifecycle(detail, "stamped_plans")}><button onClick={() => plansInput.current?.click()} className="text-xs font-semibold text-[var(--ch-accent)]">Upload PDF</button><input ref={plansInput} type="file" accept="application/pdf" hidden onChange={(event) => void upload("stamped_plans", event.target.files?.[0])} /></Action>
              <Action title="Building type" status={detail.lot.building_type || "Not set"}><select value={detail.lot.building_type || ""} onChange={(event) => run("building", () => presalesApi.updateLot(lotId, { sale_type: "presale", building_type: event.target.value }))} className="rounded-md border border-[var(--ch-border)] bg-[var(--ch-page-bg)] px-2 py-1 text-xs"><option value="">Set…</option><option value="bungalow">Bungalow</option><option value="two_storey">Two storey</option><option value="duplex">Duplex</option><option value="other">Other</option></select></Action>
            </div>
          </div>
        </section>

        <section className="overflow-x-auto rounded-xl border border-[var(--ch-border)] bg-[var(--ch-surface)] p-5">
          <div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="font-semibold">Partner readiness</h2><p className="mt-1 text-xs text-[var(--ch-text-muted)]">Computed {new Date(detail.readiness.computed_at).toLocaleString()}</p></div><strong className="text-[var(--ch-accent)]">Suggested: {detail.readiness.suggested || "Not fundable yet"}</strong></div>
          <table className="mt-4 min-w-[760px] w-full text-sm"><thead><tr className="text-left text-xs uppercase tracking-wider text-[var(--ch-text-muted)]"><th className="py-2">Partner</th>{columns.map((column) => <th key={column} className="px-2 py-2">{LABELS[column] || column}</th>)}<th className="px-2 py-2">Capacity</th><th className="px-2 py-2">State</th></tr></thead><tbody>{Object.entries(detail.readiness.partners).map(([code, partner]) => <tr key={code} className="border-t border-[var(--ch-border)]"><td className="py-3 font-semibold">{partner.display_name}</td>{columns.map((column) => <td key={column} className={`px-2 py-3 ${partner.missing.includes(column) ? "text-[var(--ch-error-text)]" : "text-[var(--ch-success-text)]"}`}>{partner.package_docs.includes(column) || partner.missing.includes(column) ? (partner.missing.includes(column) ? "✗" : "✓") : "—"}</td>)}<td className="px-2 py-3">{partner.capacity_ok === undefined ? "—" : partner.capacity_ok ? "✓" : "✗"}</td><td className="px-2 py-3"><span className={stateTone(partner.state)}>{partner.state.replaceAll("_", " ")}</span>{partner.disqualified_by.map((condition) => <p key={condition.text} className="mt-1 max-w-xs text-xs text-[var(--ch-error-text)]">{condition.text}</p>)}</td></tr>)}</tbody></table>
        </section>

        {Object.entries(detail.readiness.partners).some(([, partner]) => partner.advance !== undefined) ? <section className="rounded-xl border border-[var(--ch-border)] bg-[var(--ch-surface)] p-5"><h2 className="font-semibold">PROAuto calculation</h2>{Object.entries(detail.readiness.partners).filter(([, partner]) => partner.advance !== undefined).map(([code, partner]) => <div key={code} className="mt-3 grid gap-3 sm:grid-cols-4"><Fact label="Advance (90% lot + build)" value={money(partner.advance)} /><Fact label="Sale price" value={money(partner.sale_price)} /><Fact label="Approved mortgage" value={money(partner.approved_mortgage)} /><Fact label="Equity gap" value={money(partner.equity_gap)} /></div>)}</section> : null}

        <section className="flex flex-wrap items-center justify-between gap-4 rounded-xl border border-[var(--ch-border)] bg-[var(--ch-surface)] p-5">
          <div><h2 className="font-semibold">Funding handoff</h2><p className="mt-1 text-sm text-[var(--ch-text-muted)]">Create the partner package, record sending, then assign the facility in the existing module.</p></div>
          <div className="flex flex-wrap gap-2">
            {detail.lot.package_sent_at ? <span className="rounded-lg border border-[var(--ch-success-border)] bg-[var(--ch-success-bg)] px-4 py-2 text-sm font-semibold text-[var(--ch-success-text)]">Sent to {detail.lot.package_sent_to} · {dateText(detail.lot.package_sent_at)}</span> : null}
            {!detail.lot.package_sent_at && detail.readiness.suggested ? <button type="button" disabled={Boolean(busy)} onClick={() => run("draft", async () => { const result = await presalesApi.draftPackage(lotId, detail.readiness.suggested!); if (result.mode === "gmail_draft" && result.gmail_url) window.open(result.gmail_url, "_blank", "noopener,noreferrer"); if (result.mode === "download" && result.download_url) window.location.href = presaleDownloadUrl(result.download_url); })} className="rounded-lg bg-[var(--ch-accent)] px-4 py-2 text-sm font-semibold text-[var(--ch-accent-text)]">{busy === "draft" ? "Creating…" : `Send ${detail.readiness.suggested} package`}</button> : null}
            {!detail.lot.package_sent_at && detail.readiness.suggested ? <button type="button" disabled={Boolean(busy)} onClick={() => run("sent", () => presalesApi.markPackageSent(lotId, detail.readiness.suggested!))} className="rounded-lg border border-[var(--ch-border-strong)] px-4 py-2 text-sm">Mark package sent</button> : null}
            <Link href={`/financing?property_id=${detail.lot.property_id || ""}`} className="rounded-lg border border-[var(--ch-border)] px-4 py-2 text-sm">Assign facility</Link>
          </div>
        </section>

        <section className="rounded-xl border border-[var(--ch-border)] bg-[var(--ch-surface)] p-5"><h2 className="font-semibold">Approval letter history</h2><div className="mt-3 divide-y divide-[var(--ch-border)]">{detail.letter_history.length ? detail.letter_history.map((item) => <div key={item.id} className="flex flex-wrap justify-between gap-2 py-3 text-sm"><span>Version {item.version} · {item.status.replaceAll("_", " ")}</span><span className="text-[var(--ch-text-muted)]">{item.quality_score ? `${item.quality_score}/10` : "No score"} · {dateText(item.created_at)}</span></div>) : <p className="py-3 text-sm text-[var(--ch-text-muted)]">No letters yet.</p>}</div></section>
      </div>
    </main>
  );
}

function Action({ title, status, children }: { title: string; status: string; children: React.ReactNode }) { return <div className="rounded-lg border border-[var(--ch-border)] bg-[var(--ch-page-bg)] p-3"><p className="text-sm font-semibold">{title}</p><p className="mt-1 text-xs text-[var(--ch-text-muted)]">{status}</p><div className="mt-3 flex flex-wrap gap-3">{children}</div></div>; }
function Fact({ label, value }: { label: string; value: string }) { return <div className="rounded-lg bg-[var(--ch-page-bg)] p-3"><p className="text-xs text-[var(--ch-text-muted)]">{label}</p><p className="mt-1 font-semibold">{value}</p></div>; }
function lifecycle(detail: PresaleDetail, item: string) { const value = detail.package_items[item]; if (value?.received_at) return `Received ${dateText(value.received_at)}`; if (value?.ordered_at) return `Ordered ${dateText(value.ordered_at)}`; if (value?.requested_at) return `Requested ${dateText(value.requested_at)}`; return "Not started"; }
function dateText(value: string) { return new Date(value).toLocaleDateString("en-CA", { month: "short", day: "numeric", year: "numeric" }); }
function money(value: unknown) { if (value === null || value === undefined || value === "") return "—"; const amount = Number(value); return Number.isFinite(amount) ? new Intl.NumberFormat("en-CA", { style: "currency", currency: "CAD", maximumFractionDigits: 0 }).format(amount) : "—"; }
function stateTone(state: string) { if (state === "ready") return "text-[var(--ch-success-text)]"; if (state === "disqualified") return "text-[var(--ch-error-text)]"; if (state === "blocked_by_quality") return "text-[var(--ch-warning-text)]"; return "text-[var(--ch-text-muted)]"; }
