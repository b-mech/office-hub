"use client";

import Link from "next/link";
import { Check, FileText, History, ListChecks, Package, Plus, Receipt, Trash2, X } from "lucide-react";
import { FormEvent, useEffect, useMemo, useState } from "react";

import {
  addChecklistItems,
  attachmentUrl,
  listTickets,
  logPurchase,
  setPurchaseStatus,
  updateChecklistItem,
  type CompleteWorkOrderInput,
  type PurchaseStatus,
  type TicketDetail,
  type TicketListItem,
  type WorkOrder,
} from "@/lib/api/maintenance";
import { checklistLabel, duplicateCandidates, formatMoney, parseMoney } from "@/lib/maintenance-workflows";
import { formatDate } from "@/lib/rentals-ux";

type Mutate = (task: () => Promise<unknown>, closeAction?: boolean) => Promise<void>;

const field = "min-h-11 w-full rounded-xl border border-[var(--ch-border)] bg-[var(--ch-surface-strong)] px-3 text-sm";
const primary = "min-h-11 rounded-xl bg-[var(--ch-accent)] px-4 text-sm font-semibold text-[var(--ch-accent-text)] disabled:opacity-40";
const secondary = "min-h-10 rounded-xl border border-[var(--ch-border)] bg-[var(--ch-surface)] px-3 text-xs font-semibold disabled:opacity-40";
const card = "rounded-2xl border border-[var(--ch-border)] bg-[var(--ch-surface)] p-4";
const label = (value: string | null | undefined) => value ? value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase()) : "—";
const shortDate = (value: string | null) => formatDate(value);

export type CompletionSubmit = (order: WorkOrder, mode: "complete" | "costs", values: CompleteWorkOrderInput, invoice: File | null) => Promise<boolean>;

/** Structured work completion (replaces window.prompt): notes, actual cost, repair/capital, optional invoice. */
export function CompleteWorkOrderDialog({ order, mode, busy, serverError, onClose, onSubmit }: { order: WorkOrder; mode: "complete" | "costs"; busy: boolean; serverError?: string; onClose: () => void; onSubmit: CompletionSubmit }) {
  const [error, setError] = useState("");
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const notes = String(data.get("notes") || "").trim();
    let cost: string | null;
    try { cost = parseMoney(String(data.get("cost") || "")); } catch (caught) { setError(caught instanceof Error ? caught.message : "Check the amount"); return; }
    if (mode === "complete" && !notes) { setError("Completion notes are required."); return; }
    const costClass = String(data.get("cost_class") || "") as "repair" | "capital" | "";
    const file = data.get("invoice");
    const invoice = file instanceof File && file.size > 0 ? file : null;
    setError("");
    const ok = await onSubmit(order, mode, { completion_notes: notes, cost_actual: cost, cost_class: costClass || null }, invoice);
    if (ok) onClose();
  }
  const title = mode === "complete" ? `Complete ${order.number}` : `Final cost for ${order.number}`;
  return <div role="dialog" aria-modal="true" aria-labelledby="complete-title" className="fixed inset-0 z-50 grid place-items-end bg-black/40 p-0 sm:place-items-center sm:p-4">
    <form onSubmit={(event) => void submit(event)} className="w-full max-w-lg rounded-t-2xl border border-[var(--ch-border)] bg-[var(--ch-surface)] p-5 shadow-xl sm:rounded-2xl">
      <div className="flex items-start justify-between gap-3"><div><h2 id="complete-title" className="text-lg font-semibold">{title}</h2><p className="mt-1 text-sm text-[var(--ch-text-muted)]">{order.assignee_name} · {order.scope}</p></div><button type="button" aria-label="Close" onClick={onClose} className="grid h-9 w-9 place-items-center rounded-lg border border-[var(--ch-border)]"><X size={16} /></button></div>
      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        {mode === "complete" ? <label className="text-xs font-semibold text-[var(--ch-text-muted)] sm:col-span-2">Completion notes (required)<textarea name="notes" required autoFocus defaultValue="" placeholder="What was done, parts used, follow-up needed" className={`${field} mt-1 min-h-28 py-3 font-normal text-[var(--ch-text-primary)]`} /></label> : null}
        <label className="text-xs font-semibold text-[var(--ch-text-muted)]">Actual cost (CAD)<input name="cost" inputMode="decimal" defaultValue={order.cost_actual || ""} placeholder={order.cost_estimate ? `Estimate ${order.cost_estimate}` : "0.00"} className={`${field} mt-1 font-normal`} /></label>
        <label className="text-xs font-semibold text-[var(--ch-text-muted)]">Cost type<select name="cost_class" defaultValue={order.cost_class || ""} className={`${field} mt-1 font-normal`}><option value="">Not classified</option><option value="repair">Repair (opex)</option><option value="capital">Capital (capex)</option></select></label>
        <label className="text-xs font-semibold text-[var(--ch-text-muted)] sm:col-span-2">Invoice (PDF or photo, optional)<input name="invoice" type="file" accept="application/pdf,image/jpeg,image/png,image/heic,image/webp" className="mt-1 block w-full text-sm font-normal" /></label>
        {order.invoice_url ? <p className="text-xs text-[var(--ch-text-muted)] sm:col-span-2">An invoice is already attached; uploading another replaces the link on this work order (the old file stays in the timeline).</p> : null}
      </div>
      {error || serverError ? <p className="mt-3 rounded-lg border border-[var(--ch-error-border)] bg-[var(--ch-error-bg)] p-2 text-sm text-[var(--ch-error-text)]">{error || serverError}</p> : null}
      <div className="mt-5 flex justify-end gap-2"><button type="button" onClick={onClose} className={secondary}>Cancel</button><button disabled={busy} className={primary}>{mode === "complete" ? "Complete work order" : "Save cost"}</button></div>
    </form>
  </div>;
}

export function WorkOrderCostLine({ order, onRecordCost }: { order: WorkOrder; onRecordCost: (order: WorkOrder) => void }) {
  const completed = order.status === "completed";
  return <div className="mt-2 space-y-1 text-xs text-[var(--ch-text-secondary)]">
    {order.cost_estimate || order.cost_actual ? <p>Estimate {formatMoney(order.cost_estimate)} · Actual {formatMoney(order.cost_actual)}{order.cost_class ? ` · ${label(order.cost_class)}` : ""}</p> : null}
    {order.completion_notes ? <p className="whitespace-pre-wrap"><strong>Notes:</strong> {order.completion_notes}</p> : null}
    <div className="flex flex-wrap gap-2">
      {order.invoice_url ? <a href={attachmentUrl(order.invoice_url)} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 rounded-lg border border-[var(--ch-border)] bg-[var(--ch-surface)] px-2 py-1 font-semibold text-[var(--ch-accent)]"><FileText size={13} /> Invoice</a> : null}
      {completed ? <button type="button" onClick={() => onRecordCost(order)} className="inline-flex items-center gap-1 rounded-lg border border-[var(--ch-border)] bg-[var(--ch-surface)] px-2 py-1 font-semibold"><Receipt size={13} /> {order.cost_actual ? "Edit cost / invoice" : "Record cost / invoice"}</button> : null}
    </div>
  </div>;
}

export function ChecklistPanel({ ticket, busy, locked, onMutate }: { ticket: TicketDetail; busy: boolean; locked: boolean; onMutate: Mutate }) {
  const [text, setText] = useState("");
  const progress = checklistLabel(ticket.checklist);
  return <section className={card} aria-labelledby="checklist-title">
    <div className="flex items-center justify-between"><h2 id="checklist-title" className="inline-flex items-center gap-2 font-semibold"><ListChecks size={17} /> Checklist</h2><span className="text-xs text-[var(--ch-text-muted)]">{progress || "No items"}</span></div>
    {ticket.checklist.total ? <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-[var(--ch-surface-muted)]"><div className="h-full bg-[var(--ch-accent)]" style={{ width: `${Math.round((ticket.checklist.done / ticket.checklist.total) * 100)}%` }} /></div> : null}
    <ul className="mt-3 space-y-2">{ticket.checklist_items.map((item) => <li key={item.id} className="flex items-start gap-2 text-sm">
      <input type="checkbox" aria-label={`Mark ${item.text} ${item.done ? "not done" : "done"}`} checked={item.done} disabled={busy || locked} onChange={(event) => void onMutate(() => updateChecklistItem(ticket.id, item.id, { done: event.target.checked }), false)} className="mt-1 h-4 w-4 accent-[var(--ch-accent)]" />
      <span className={`flex-1 ${item.done ? "text-[var(--ch-text-muted)] line-through" : ""}`}>{item.text}</span>
      {!locked ? <button type="button" aria-label={`Remove ${item.text}`} disabled={busy} onClick={() => { if (window.confirm(`Remove “${item.text}” from the checklist?`)) void onMutate(() => updateChecklistItem(ticket.id, item.id, { remove: true }), false); }} className="text-[var(--ch-text-muted)] hover:text-[var(--ch-error-text)]"><Trash2 size={14} /></button> : null}
    </li>)}</ul>
    {!locked ? <form onSubmit={(event) => { event.preventDefault(); if (!text.trim()) return; void onMutate(async () => { await addChecklistItems(ticket.id, { text }); setText(""); }, false); }} className="mt-3 space-y-2">
      <textarea value={text} onChange={(event) => setText(event.target.value)} rows={2} placeholder={"Add items, one per line (paste a punch list)"} className={`${field} py-2`} />
      <button disabled={busy || !text.trim()} className={`${secondary} inline-flex items-center gap-1`}><Plus size={14} /> Add {text.split("\n").filter((line) => line.trim()).length > 1 ? `${text.split("\n").filter((line) => line.trim()).length} items` : "item"}</button>
    </form> : null}
  </section>;
}

const PURCHASE_STATUSES: PurchaseStatus[] = ["needed", "ordered", "received", "cancelled"];

export function PurchasesPanel({ ticket, busy, locked, onMutate }: { ticket: TicketDetail; busy: boolean; locked: boolean; onMutate: Mutate }) {
  const [open, setOpen] = useState(false);
  const [error, setError] = useState("");
  const total = ticket.purchases.filter((item) => item.status !== "cancelled" && item.amount).reduce((sum, item) => sum + Number(item.amount), 0);
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    let amount: string | null;
    try { amount = parseMoney(String(data.get("amount") || "")); } catch (caught) { setError(caught instanceof Error ? caught.message : "Check the amount"); return; }
    setError("");
    void onMutate(async () => {
      await logPurchase(ticket.id, { vendor: String(data.get("vendor") || ""), item: String(data.get("item") || ""), amount, status: String(data.get("status")) as PurchaseStatus, reference: String(data.get("reference") || "") || null, work_order_id: String(data.get("work_order") || "") || null });
      form.reset(); setOpen(false);
    }, false);
  }
  return <section className={card} aria-labelledby="purchases-title">
    <div className="flex items-center justify-between"><h2 id="purchases-title" className="inline-flex items-center gap-2 font-semibold"><Package size={17} /> Purchases</h2><span className="text-xs text-[var(--ch-text-muted)]">{ticket.purchases.length ? formatMoney(total) : "None"}</span></div>
    <ul className="mt-3 space-y-2">{ticket.purchases.map((item) => <li key={item.id} className="rounded-xl border border-[var(--ch-border)] bg-[var(--ch-surface-muted)] p-2 text-sm">
      <div className="flex items-start justify-between gap-2"><div className="min-w-0"><p className="font-semibold">{item.item}</p><p className="text-xs text-[var(--ch-text-muted)]">{item.vendor}{item.amount ? ` · ${formatMoney(item.amount)}` : ""}{item.reference ? ` · ${item.reference}` : ""}</p></div>
        <select aria-label={`Status for ${item.item}`} value={item.status} disabled={busy || locked} onChange={(event) => void onMutate(() => setPurchaseStatus(ticket.id, item.id, event.target.value as PurchaseStatus), false)} className="min-h-8 rounded-lg border border-[var(--ch-border)] bg-[var(--ch-surface)] px-2 text-xs">{PURCHASE_STATUSES.map((status) => <option key={status} value={status}>{label(status)}</option>)}</select></div>
    </li>)}</ul>
    {!locked && !open ? <button type="button" onClick={() => setOpen(true)} className={`${secondary} mt-3 inline-flex items-center gap-1`}><Plus size={14} /> Log purchase</button> : null}
    {open ? <form onSubmit={submit} className="mt-3 grid gap-2">
      <input name="item" required maxLength={500} placeholder="Item (e.g. range hood filter)" className={field} />
      <div className="grid grid-cols-2 gap-2"><input name="vendor" required maxLength={200} placeholder="Store / supplier" className={field} /><input name="amount" inputMode="decimal" placeholder="Amount" className={field} /></div>
      <div className="grid grid-cols-2 gap-2"><select name="status" defaultValue="ordered" className={field}>{PURCHASE_STATUSES.filter((status) => status !== "cancelled").map((status) => <option key={status} value={status}>{label(status)}</option>)}</select><input name="reference" maxLength={500} placeholder="Order # or link" className={field} /></div>
      {ticket.work_orders.length ? <select name="work_order" defaultValue="" className={field}><option value="">Not tied to a work order</option>{ticket.work_orders.map((order) => <option key={order.id} value={order.id}>{order.number} · {order.assignee_name}</option>)}</select> : null}
      {error ? <p className="text-sm text-[var(--ch-error-text)]">{error}</p> : null}
      <div className="flex justify-end gap-2"><button type="button" onClick={() => setOpen(false)} className={secondary}>Cancel</button><button disabled={busy} className={primary}>Save purchase</button></div>
    </form> : null}
  </section>;
}

export function RelatedTicketsPanel({ ticket }: { ticket: TicketDetail }) {
  const sameUnit = ticket.related_tickets.filter((item) => item.same_unit).length;
  return <section className={card} aria-labelledby="history-title">
    <div className="flex items-center justify-between"><h2 id="history-title" className="inline-flex items-center gap-2 font-semibold"><History size={17} /> Unit & property history</h2><Link href={`/rentals/maintenance?property_id=${ticket.property_id}&include_terminal=true`} className="text-xs font-semibold text-[var(--ch-accent)]">All</Link></div>
    {ticket.related_tickets.length ? <p className="mt-1 text-xs text-[var(--ch-text-muted)]">{sameUnit} on this unit · {ticket.related_tickets.length - sameUnit} elsewhere at this property</p> : <p className="mt-2 text-sm text-[var(--ch-text-muted)]">No other tickets at this property.</p>}
    <ul className="mt-2 space-y-1">{ticket.related_tickets.map((item) => <li key={item.id}><Link href={`/rentals/maintenance/${item.id}`} className="block rounded-lg px-2 py-1.5 text-sm hover:bg-[var(--ch-surface-muted)]">
      <span className="font-mono text-xs font-semibold text-[var(--ch-accent)]">{item.number}</span> <span className="font-medium">{item.title}</span>
      <span className="block text-xs text-[var(--ch-text-muted)]">{item.same_unit ? "This unit" : item.unit} · {label(item.category)} · {label(item.status)} · {shortDate(item.created_at)}</span>
    </Link></li>)}</ul>
  </section>;
}

/** Typeahead replacing the raw canonical-UUID field. Writes the chosen id into a hidden input named `name`. */
export function DuplicatePicker({ ticketId, name }: { ticketId: string; name: string }) {
  const [tickets, setTickets] = useState<TicketListItem[]>([]);
  const [query, setQuery] = useState("");
  const [chosen, setChosen] = useState<TicketListItem | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { listTickets({ include_terminal: true }).then(setTickets).catch((caught) => setError(caught instanceof Error ? caught.message : "Could not load tickets")); }, []);
  const matches = useMemo(() => duplicateCandidates(tickets, ticketId, query), [tickets, ticketId, query]);
  return <div className="sm:col-span-2">
    <input type="hidden" name={name} value={chosen?.id || ""} />
    {chosen ? <div className="flex items-center justify-between gap-2 rounded-xl border border-[var(--ch-accent)] bg-[var(--ch-accent-soft)] px-3 py-2 text-sm"><span><span className="font-mono text-xs font-semibold">{chosen.number}</span> {chosen.title} · {chosen.property}</span><button type="button" onClick={() => setChosen(null)} className="text-xs font-semibold text-[var(--ch-accent)]">Change</button></div> : <>
      <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Duplicate of… search ticket number, title or property" aria-label="Canonical ticket" className={field} />
      <ul className="mt-1 max-h-56 overflow-y-auto rounded-xl border border-[var(--ch-border)]" role="listbox">{matches.map((item) => <li key={item.id}><button type="button" onClick={() => setChosen(item)} className="flex w-full items-start gap-2 px-3 py-2 text-left text-sm hover:bg-[var(--ch-surface-muted)]"><Check size={14} className="mt-0.5 opacity-0" /><span><span className="font-mono text-xs font-semibold text-[var(--ch-accent)]">{item.number}</span> {item.title}<span className="block text-xs text-[var(--ch-text-muted)]">{item.property} · {item.unit} · {label(item.status)}</span></span></button></li>)}{!matches.length ? <li className="px-3 py-2 text-xs text-[var(--ch-text-muted)]">{error || "No eligible tickets. Cancelled and duplicate tickets can’t be canonical."}</li> : null}</ul>
    </>}
  </div>;
}
