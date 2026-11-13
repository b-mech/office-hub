"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { fundsApi, type FundsEntry, type FundsNotice, type FundsTask, type ReviewOptions } from "@/lib/api/funds";

const TYPES = ["lot_deposit", "pro_draw", "client_funded_draw", "statement_of_adjustments", "other"];

export default function FundsPage() {
  const [notices, setNotices] = useState<FundsNotice[]>([]);
  const [selected, setSelected] = useState<FundsNotice | null>(null);
  const [options, setOptions] = useState<ReviewOptions | null>(null);
  const [tasks, setTasks] = useState<FundsTask[]>([]);
  const [possessionLot, setPossessionLot] = useState("");
  const [possessionDate, setPossessionDate] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async (id?: string) => {
    const [rows, choices, taskRows] = await Promise.all([fundsApi.list(), fundsApi.options(), fundsApi.tasks()]);
    setNotices(rows);
    setOptions(choices);
    setTasks(taskRows);
    const target = id || selected?.id || rows[0]?.id;
    setSelected(target ? await fundsApi.detail(target) : null);
  }, [selected?.id]);

  useEffect(() => { void load().catch((e) => setError(String(e))); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  async function act(operation: () => Promise<unknown>) {
    setBusy(true); setError(""); setMessage("");
    try { const result = await operation(); setMessage(JSON.stringify(result)); await load(); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  }

  const total = Number(selected?.entry_total || 0);
  const trust = selected?.trust_statement_total == null ? null : Number(selected.trust_statement_total);
  return <div className="min-h-screen bg-[var(--ch-page-bg)] p-6 text-[var(--ch-text-primary)]">
    <div className="mx-auto max-w-[1500px] space-y-5">
      <header className="flex items-center justify-between gap-4">
        <div><Link href="/financing" className="text-sm text-[var(--ch-accent)]">← Financing</Link>
          <h1 className="mt-2 text-2xl font-semibold">Lawyer funds intake</h1>
          <p className="text-sm text-[var(--ch-text-muted)]">Confirm every entry before any funds are posted.</p></div>
      </header>
      {error && <p role="alert" className="rounded-lg bg-red-50 p-3 text-red-700">{error}</p>}
      {message && <p role="status" className="rounded-lg bg-green-50 p-3 text-green-700">{message}</p>}
      <section className="rounded-xl border bg-white p-4">
        <h2 className="font-semibold">Possession taken</h2>
        <p className="text-sm text-gray-600">Sales only. Confirming possession posts no money and starts the closing document watch.</p>
        <div className="mt-3 flex flex-wrap gap-2">
          <select value={possessionLot} onChange={(e) => {
            setPossessionLot(e.target.value);
            setPossessionDate(options?.lots.find((l) => l.id === e.target.value)?.estimated_possession_date || "");
          }} className="min-w-64 rounded border p-2">
            <option value="">Choose sale lot</option>
            {options?.lots.filter((l) => l.is_sale && !l.possession_confirmed_date).map((lot) =>
              <option key={lot.id} value={lot.id}>{lot.address}</option>)}
          </select>
          <input type="date" value={possessionDate} onChange={(e) => setPossessionDate(e.target.value)} className="rounded border p-2" />
          <button type="button" disabled={busy || !possessionLot || !possessionDate}
            onClick={() => void act(() => fundsApi.possessionTaken(possessionLot, possessionDate))}
            className="rounded bg-blue-700 px-4 py-2 text-white">Confirm possession</button>
        </div>
        {possessionLot && options?.lots.find((l) => l.id === possessionLot)?.tracker_date_locked &&
          <p className="mt-2 text-xs text-gray-600">Production has locked this date in the tracker. Confirm here only when keys were released.</p>}
      </section>
      {tasks.length > 0 && <section className="rounded-xl border bg-white p-4">
        <h2 className="font-semibold">Open funds and closing tasks ({tasks.length})</h2>
        <div className="mt-3 max-h-56 overflow-auto text-sm">
          {tasks.map((task) => <p key={task.id} className="border-t py-2">{task.title}</p>)}
        </div>
      </section>}
      <div className="grid gap-5 lg:grid-cols-[320px_1fr]">
        <aside className="space-y-2">
          {notices.map((notice) => <button key={notice.id} type="button" onClick={() => void load(notice.id).catch((e) => setError(String(e)))}
            className={`w-full rounded-xl border p-4 text-left ${selected?.id === notice.id ? "border-blue-500 bg-blue-50" : "bg-white"}`}>
            <strong className="block truncate">{notice.subject || "Multiple properties"}</strong>
            <span className="text-sm text-gray-600">{notice.funds_type || "Extracting"} · {notice.status}</span>
            <span className="block text-xs text-gray-500">{notice.received_at?.slice(0, 10) || "Date unknown"}</span>
          </button>)}
          {!notices.length && <p className="rounded-xl border bg-white p-4 text-sm">No captured notices yet.</p>}
        </aside>
        {selected && <section className="space-y-5">
          <div className="rounded-xl border bg-white p-5">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div><h2 className="text-xl font-semibold">{selected.subject || "Multiple properties"}</h2>
                <p className="text-sm text-gray-600">{selected.email_from} · {selected.law_firm || "Law firm unknown"} · {selected.status}</p>
                <p className="mt-1 text-sm">Classification: <strong>{selected.funds_type || "pending"}</strong> — {selected.classification_reason || "Review the PDF"}</p></div>
              <button disabled={busy} onClick={() => void act(() => fundsApi.fileToBox(selected.id))}
                className="rounded-lg border px-3 py-2 text-sm">File PDFs to Box</button>
            </div>
            <p className={`mt-3 text-sm ${trust !== null && trust !== total ? "font-semibold text-red-700" : "text-gray-600"}`}>
              Entries ${total.toFixed(2)} · Trust statement {trust === null ? "not stated" : trust.toFixed(2)}
              {trust !== null && trust !== total ? ` · Difference ${(total - trust).toFixed(2)}` : ""}
            </p>
            {(selected.review_flags || []).map((flag) => <p key={flag} className="text-sm text-amber-700">{flag}</p>)}
            <div className="mt-4 grid gap-3 md:grid-cols-2">
              {selected.attachments?.map((attachment) => <div key={attachment.id} className="rounded-lg border p-3">
                <div className="flex justify-between gap-2 text-sm"><strong>{attachment.filename}</strong><span>{attachment.box_filing_status}</span></div>
                {attachment.extraction_error && <p className="text-sm text-red-700">{attachment.extraction_error}</p>}
                {attachment.box_file_url && <a href={attachment.box_file_url} target="_blank" rel="noreferrer" className="text-sm text-blue-700">Open Box copy</a>}
                <iframe title={attachment.filename} src={fundsApi.pdfUrl(selected.id, attachment.id)} className="mt-2 h-80 w-full rounded border" />
              </div>)}
            </div>
          </div>
          {selected.entries?.map((entry) => <EntryCard key={entry.id} entry={entry} noticeId={selected.id}
            options={options} disabled={busy} act={act} />)}
          {selected.entries?.every((entry) => entry.status === "confirmed") &&
            <button disabled={busy} onClick={() => void act(() => fundsApi.retryPost(selected.id))}
              className="rounded-lg bg-blue-700 px-4 py-2 text-white">Post confirmed entries</button>}
        </section>}
      </div>
    </div>
  </div>;
}

function EntryCard({ entry, noticeId, options, disabled, act }: {
  entry: FundsEntry; noticeId: string; options: ReviewOptions | null; disabled: boolean;
  act: (operation: () => Promise<unknown>) => Promise<void>;
}) {
  const [draft, setDraft] = useState<FundsEntry>(entry);
  const [closingJson, setClosingJson] = useState(JSON.stringify(entry.closing || {}, null, 2));
  useEffect(() => { setDraft(entry); setClosingJson(JSON.stringify(entry.closing || {}, null, 2)); }, [entry]);
  const set = (name: keyof FundsEntry, value: string | number | null) =>
    setDraft((old) => ({ ...old, [name]: value }));
  const lots = options?.lots.filter((lot) => !draft.property_id || lot.property_id === draft.property_id) || [];
  const facilities = options?.facilities.filter((f) => f.lot_id === draft.lot_id || f.property_id === draft.property_id) || [];
  const fields: (keyof FundsEntry)[] = ["property_id", "lot_id", "facility_id", "property_address", "funds_type",
    "deposit_ordinal", "amount", "cheque_number", "txn_date", "payee", "memo"];
  const dirty = fields.some((key) => draft[key] !== entry[key]) || closingJson !== JSON.stringify(entry.closing || {}, null, 2);
  async function save() {
    let closing: Record<string, unknown> | null = null;
    if (draft.funds_type === "statement_of_adjustments") closing = JSON.parse(closingJson);
    await act(() => fundsApi.updateEntry(noticeId, entry.id, {
      property_id: draft.property_id, lot_id: draft.lot_id, facility_id: draft.facility_id,
      property_address: draft.property_address, funds_type: draft.funds_type,
      deposit_ordinal: draft.deposit_ordinal, amount: draft.amount,
      cheque_number: draft.cheque_number, txn_date: draft.txn_date,
      payee: draft.payee, memo: draft.memo, closing,
    }));
  }
  const input = (label: string, key: keyof FundsEntry, type = "text") =>
    <label className="block text-sm"><span className="mb-1 block text-gray-600">{label}</span>
      <input type={type} value={String(draft[key] ?? "")} onChange={(e) => set(key, e.target.value || null)}
        disabled={entry.status === "posted"} className="w-full rounded border px-2 py-2" /></label>;
  return <article className="rounded-xl border bg-white p-5">
    <div className="mb-4 flex justify-between"><h3 className="font-semibold">{draft.property_address || "Unmatched entry"}</h3><span>{entry.status}</span></div>
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      <label className="text-sm">Type<select value={draft.funds_type} onChange={(e) => set("funds_type", e.target.value)}
        disabled={entry.status === "posted"} className="mt-1 w-full rounded border px-2 py-2">
        {TYPES.map((type) => <option key={type} value={type}>{type}</option>)}</select></label>
      <label className="text-sm">Property<select value={draft.property_id || ""} onChange={(e) => { set("property_id", e.target.value || null); set("lot_id", null); set("facility_id", null); }}
        disabled={entry.status === "posted"} className="mt-1 w-full rounded border px-2 py-2">
        <option value="">Choose property</option>{options?.properties.map((p) => <option key={p.id} value={p.id}>{p.address}</option>)}</select></label>
      <label className="text-sm">Lot<select value={draft.lot_id || ""} onChange={(e) => set("lot_id", e.target.value || null)}
        disabled={entry.status === "posted"} className="mt-1 w-full rounded border px-2 py-2">
        <option value="">Choose lot</option>{lots.map((lot) => <option key={lot.id} value={lot.id}>{lot.address}</option>)}</select></label>
      {draft.funds_type === "pro_draw" && <label className="text-sm">PRO facility<select value={draft.facility_id || ""} onChange={(e) => set("facility_id", e.target.value || null)}
        disabled={entry.status === "posted"} className="mt-1 w-full rounded border px-2 py-2">
        <option value="">Choose facility</option>{facilities.filter((f) => f.lender_type === "PRO").map((f) => <option key={f.id} value={f.id}>{f.label}</option>)}</select></label>}
      {input("Address as printed", "property_address")}
      {input("Amount", "amount", "number")}
      {input("Date", "txn_date", "date")}
      {input("Cheque", "cheque_number")}
      {draft.funds_type === "lot_deposit" && <label className="text-sm">Deposit number<select value={draft.deposit_ordinal || ""}
        onChange={(e) => set("deposit_ordinal", e.target.value ? Number(e.target.value) : null)} className="mt-1 w-full rounded border px-2 py-2">
        <option value="">Choose</option>{[1, 2, 3].map((n) => <option key={n} value={n}>{n}</option>)}</select></label>}
      {input("Payee", "payee")}{input("Memo", "memo")}
    </div>
    {draft.funds_type === "statement_of_adjustments" && <label className="mt-3 block text-sm">Closing details
      <textarea value={closingJson} onChange={(e) => setClosingJson(e.target.value)} rows={12}
        className="mt-1 w-full rounded border p-2 font-mono text-xs" /></label>}
    {entry.match && <p className="mt-3 text-sm text-green-700">Match: {JSON.stringify(entry.match)}</p>}
    {entry.flags.map((flag) => <p key={flag} className="text-sm text-amber-700">{flag}</p>)}
    <div className="mt-4 flex gap-2">
      {entry.status !== "posted" && <><button disabled={disabled} onClick={() => void save()}
        className="rounded-lg border px-4 py-2 text-sm">Save changes</button>
      <button disabled={disabled || dirty} onClick={() => void act(() => fundsApi.confirmEntry(noticeId, entry.id))}
        className="rounded-lg bg-blue-700 px-4 py-2 text-sm text-white">{dirty ? "Save before confirming" : "Confirm entry"}</button></>}
    </div>
  </article>;
}
