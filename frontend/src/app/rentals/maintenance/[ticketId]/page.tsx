"use client";

import Link from "next/link";
import { AlertTriangle, ArrowLeft, Check, Clock3, FileText, MoreHorizontal, Paperclip, RefreshCw, Send, UserRoundCheck, Wrench, X } from "lucide-react";
import { useParams } from "next/navigation";
import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  acknowledgeEmergency,
  assignTicket,
  attachmentUrl,
  cancelTicketMessage,
  completeWorkOrder,
  getTicket,
  resolveTicket,
  retryTicketMessage,
  scheduleTicket,
  sendTicketMessage,
  ticketMoreAction,
  triageTicket,
  updateScheduledVisit,
  type ScheduledVisit,
  type TicketCategory,
  type TicketDetail,
  type TicketPriority,
  type TimelineItem,
  type WorkOrder,
} from "@/lib/api/maintenance";

type ComposerTarget = "tenant" | "vendor" | "internal";
type ActionName = "triage" | "assign" | "schedule" | "resolve" | "more" | null;

const label = (value: string | null | undefined) => value ? value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase()) : "—";
const formatDate = (value: string | null) => value ? new Intl.DateTimeFormat("en-CA", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value)) : "Not scheduled";

function StatusPill({ children, tone = "neutral" }: { children: React.ReactNode; tone?: "neutral" | "good" | "warn" | "bad" | "info" }) {
  const classes = {
    neutral: "border-[var(--ch-border)] bg-[var(--ch-surface-muted)] text-[var(--ch-text-secondary)]",
    good: "border-[var(--ch-success-border)] bg-[var(--ch-success-bg)] text-[var(--ch-success-text)]",
    warn: "border-[var(--ch-warning-border)] bg-[var(--ch-warning-bg)] text-[var(--ch-warning-text)]",
    bad: "border-[var(--ch-error-border)] bg-[var(--ch-error-bg)] text-[var(--ch-error-text)]",
    info: "border-[var(--ch-info-border)] bg-[var(--ch-info-bg)] text-[var(--ch-info-text)]",
  }[tone];
  return <span className={`inline-flex rounded-full border px-2 py-1 text-xs font-semibold ${classes}`}>{children}</span>;
}

function TimelineRow({ item, now, onCancel, onRetry }: { item: TimelineItem; now: number; onCancel: (messageId: string) => Promise<void>; onRetry: (messageId: string) => Promise<void> }) {
  const outbound = item.direction === "outbound";
  const internal = item.visibility === "internal";
  const remaining = item.sms?.hold_until ? Math.max(0, Math.ceil((new Date(item.sms.hold_until).getTime() - now) / 1000)) : 0;
  const failureReason = item.sms?.status === "failed"
    ? item.sms.failure_reason
    : item.event_type === "sms_send_failed" && typeof item.payload.failure_reason === "string"
      ? item.payload.failure_reason
      : null;
  const bubble = internal
    ? "border-[var(--ch-warning-border)] bg-[var(--ch-warning-bg)]"
    : outbound
      ? "border-[var(--ch-info-border)] bg-[var(--ch-info-bg)]"
      : "border-[var(--ch-border)] bg-[var(--ch-surface-strong)]";
  const title = item.body ? null : label(item.event_type);

  return (
    <article className={`flex ${outbound ? "justify-end" : "justify-start"}`}>
      <div className={`max-w-[92%] rounded-2xl border px-4 py-3 shadow-sm sm:max-w-[76%] ${bubble}`}>
        <div className="flex flex-wrap items-center gap-2 text-xs text-[var(--ch-text-muted)]">
          <span className="font-semibold text-[var(--ch-text-secondary)]">{internal ? "Internal" : item.actor_name || label(item.party)}</span>
          <span>·</span><time>{formatDate(item.created_at)}</time>
        </div>
        {item.body ? <p className="mt-2 whitespace-pre-wrap text-sm leading-6">{item.body}</p> : <p className="mt-2 text-sm font-medium">{title}</p>}
        {item.event_type === "status_changed" && typeof item.payload.to === "string" ? <p className="mt-1 text-xs text-[var(--ch-text-muted)]">Status → {label(item.payload.to)}</p> : null}
        {failureReason ? <p className="mt-2 rounded-lg border border-[var(--ch-error-border)] bg-[var(--ch-error-bg)] px-2 py-1.5 text-xs text-[var(--ch-error-text)]">{failureReason}</p> : null}
        {item.attachments.length ? <div className="mt-3 flex flex-wrap gap-2">{item.attachments.map((file) => <a key={file.id} href={attachmentUrl(file.url)} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 rounded-lg border border-[var(--ch-border)] bg-[var(--ch-surface)] px-2 py-1 text-xs font-semibold text-[var(--ch-accent)]"><FileText size={13} />{file.filename || "Attachment"}</a>)}</div> : null}
        {item.sms ? <div className="mt-2 flex items-center justify-end gap-2 text-xs text-[var(--ch-text-muted)]">
          <span>{item.sms.status}{item.sms.status === "held" && remaining ? ` · ${remaining}s` : ""}</span>
          {item.sms.cancellable && remaining > 0 ? <button type="button" onClick={() => void onCancel(item.sms!.id)} className="rounded-lg border border-[var(--ch-error-border)] px-2 py-1 font-semibold text-[var(--ch-error-text)]">Cancel</button> : null}
          {item.sms.retryable ? <button type="button" onClick={() => void onRetry(item.sms!.id)} className="inline-flex items-center gap-1 rounded-lg border border-[var(--ch-error-border)] px-2 py-1 font-semibold text-[var(--ch-error-text)]"><RefreshCw size={12} /> Retry</button> : null}
        </div> : null}
      </div>
    </article>
  );
}

function WorkOrderCard({ order, busy, onComplete }: { order: WorkOrder; busy: boolean; onComplete: (order: WorkOrder) => Promise<void> }) {
  const complete = order.status === "completed" || order.status === "cancelled";
  return <article className="rounded-xl border border-[var(--ch-border)] bg-[var(--ch-surface-muted)] p-3">
    <div className="flex items-start justify-between gap-3"><div><p className="font-mono text-xs font-semibold text-[var(--ch-accent)]">{order.number}</p><h3 className="mt-1 text-sm font-semibold">{order.assignee_name}</h3></div><StatusPill tone={order.status === "completed" ? "good" : "neutral"}>{label(order.status)}</StatusPill></div>
    <p className="mt-2 text-sm text-[var(--ch-text-secondary)]">{order.scope}</p>
    <p className="mt-2 text-xs text-[var(--ch-text-muted)]">{formatDate(order.scheduled_start)}{order.scheduled_end ? ` – ${formatDate(order.scheduled_end)}` : ""}</p>
    {order.scheduled_visit_status ? <p className={`mt-2 text-xs font-semibold ${order.scheduled_visit_status === "scheduled" ? "text-[var(--ch-warning-text)]" : "text-[var(--ch-text-muted)]"}`}>Visit: {label(order.scheduled_visit_status)}</p> : null}
    {!complete ? <button type="button" disabled={busy} onClick={() => void onComplete(order)} className="mt-3 inline-flex min-h-10 items-center gap-2 rounded-lg border border-[var(--ch-border)] bg-[var(--ch-surface)] px-3 text-xs font-semibold disabled:opacity-50"><Check size={15} /> Complete work order</button> : null}
  </article>;
}

export default function MaintenanceTicketPage() {
  const params = useParams<{ ticketId: string }>();
  const ticketId = params.ticketId;
  const [ticket, setTicket] = useState<TicketDetail | null>(null);
  const [target, setTarget] = useState<ComposerTarget>("tenant");
  const [vendorOrderId, setVendorOrderId] = useState("");
  const [body, setBody] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [action, setAction] = useState<ActionName>(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [visitPrompt, setVisitPrompt] = useState<ScheduledVisit | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const timelineEnd = useRef<HTMLDivElement>(null);

  const load = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true);
    try { setTicket(await getTicket(ticketId)); setError(""); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Could not load ticket"); }
    finally { if (!quiet) setLoading(false); }
  }, [ticketId]);

  useEffect(() => { const initial = window.setTimeout(() => void load(), 0); const poll = window.setInterval(() => void load(true), 5000); return () => { window.clearTimeout(initial); window.clearInterval(poll); }; }, [load]);
  useEffect(() => { const timer = window.setInterval(() => setNow(Date.now()), 1000); return () => window.clearInterval(timer); }, []);
  useEffect(() => { if (!loading) timelineEnd.current?.scrollIntoView({ behavior: "smooth", block: "end" }); }, [loading, ticket?.timeline.length]);

  const vendorOrders = useMemo(() => ticket?.work_orders.filter((order) => order.external_party) || [], [ticket]);

  async function mutate(task: () => Promise<unknown>, closeAction = true) {
    setBusy(true); setError("");
    try { await task(); if (closeAction) setAction(null); await load(true); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "The ticket could not be updated"); }
    finally { setBusy(false); }
  }

  async function submitMessage(event: FormEvent) {
    event.preventDefault();
    await mutate(async () => {
      await sendTicketMessage(ticketId, { target, body, workOrderId: target === "vendor" ? vendorOrderId : undefined, attachments: files });
      setBody(""); setFiles([]);
    }, false);
  }

  async function finishOrder(order: WorkOrder) {
    const notes = window.prompt(`Completion notes for ${order.number}`, "Work completed") ?? "";
    if (!notes) return;
    let allComplete = false;
    let futureVisit: ScheduledVisit | null = null;
    await mutate(async () => {
      const result = await completeWorkOrder(ticketId, order.id, { completion_notes: notes });
      allComplete = result.all_work_orders_complete;
      futureVisit = result.future_scheduled_visits[0] || null;
    }, false);
    if (futureVisit) {
      setVisitPrompt(futureVisit);
    } else if (allComplete && window.confirm("All active work orders are complete. Mark resolved?")) {
      setAction("resolve");
    }
  }

  async function dispositionVisit(status: "completed" | "cancelled") {
    if (!visitPrompt) return;
    await mutate(async () => {
      await updateScheduledVisit(ticketId, visitPrompt.work_order_id, status);
      setVisitPrompt(null);
    }, false);
  }

  if (loading && !ticket) return <main className="grid min-h-[70vh] place-items-center text-sm text-[var(--ch-text-muted)]"><RefreshCw className="animate-spin" /> Loading ticket…</main>;
  if (!ticket) return <main className="p-6"><Link href="/rentals/maintenance" className="text-sm font-semibold text-[var(--ch-accent)]">← Back to tickets</Link><p className="mt-6 text-[var(--ch-error-text)]">{error || "Ticket not found"}</p></main>;

  return (
    <main className="min-h-screen bg-[var(--ch-page-bg)] px-3 py-4 sm:px-6 lg:px-8">
      <div className="mx-auto max-w-7xl">
        <header className="rounded-2xl border border-[var(--ch-border)] bg-[var(--ch-surface)] p-4 sm:p-5">
          <div className="flex items-start gap-3">
            <Link href="/rentals/maintenance" aria-label="Back to ticket list" className="grid h-11 w-11 shrink-0 place-items-center rounded-xl border border-[var(--ch-border)]"><ArrowLeft size={19} /></Link>
            <div className="min-w-0 flex-1"><div className="flex flex-wrap items-center gap-2"><span className="font-mono text-xs font-semibold text-[var(--ch-accent)]">{ticket.number}</span>{ticket.needs_reply ? <StatusPill tone="info">Needs reply</StatusPill> : null}{ticket.is_emergency ? <StatusPill tone="bad">Emergency</StatusPill> : null}<StatusPill>{label(ticket.status)}</StatusPill></div><h1 className="mt-2 text-xl font-semibold sm:text-2xl">{ticket.title}</h1><p className="mt-1 text-sm text-[var(--ch-text-secondary)]">{ticket.property} · {ticket.unit} · {label(ticket.category)} · {label(ticket.priority)}</p></div>
            <button type="button" aria-label="Refresh" onClick={() => void load()} className="grid h-11 w-11 shrink-0 place-items-center rounded-xl border border-[var(--ch-border)]"><RefreshCw size={18} /></button>
          </div>
          {ticket.is_emergency && !ticket.emergency_acked_at ? <button type="button" disabled={busy} onClick={() => void mutate(() => acknowledgeEmergency(ticketId), false)} className="mt-4 inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-xl bg-[var(--ch-error-text)] px-4 font-semibold text-[var(--ch-accent-text)] sm:w-auto"><AlertTriangle size={17} /> Acknowledge emergency</button> : null}
          <div className="mt-4 flex gap-2 overflow-x-auto pb-1">
            {[{ key: "triage", text: "Triage", icon: UserRoundCheck }, { key: "assign", text: "Assign", icon: Wrench }, { key: "schedule", text: "Schedule", icon: Clock3 }, { key: "resolve", text: "Resolve", icon: Check }, { key: "more", text: "More", icon: MoreHorizontal }].map(({ key, text, icon: Icon }) => <button key={key} type="button" onClick={() => setAction(action === key ? null : key as ActionName)} className={`inline-flex min-h-10 shrink-0 items-center gap-2 rounded-xl border px-3 text-sm font-semibold ${action === key ? "border-[var(--ch-accent)] bg-[var(--ch-accent-soft)] text-[var(--ch-accent)]" : "border-[var(--ch-border)]"}`}><Icon size={16} />{text}</button>)}
          </div>
        </header>

        {error ? <p className="mt-3 rounded-xl border border-[var(--ch-error-border)] bg-[var(--ch-error-bg)] p-3 text-sm text-[var(--ch-error-text)]">{error}</p> : null}
        {visitPrompt ? <section className="mt-3 rounded-2xl border border-[var(--ch-warning-border)] bg-[var(--ch-warning-bg)] p-4"><h2 className="font-semibold text-[var(--ch-warning-text)]">What happened to the scheduled visit?</h2><p className="mt-1 text-sm text-[var(--ch-text-secondary)]">{visitPrompt.work_order_number} was completed before its future visit on {formatDate(visitPrompt.scheduled_start)}. Mark that visit completed too, or cancel it. Cancelling sends the tenant a cancellation text if an entry notice was sent.</p><div className="mt-3 flex flex-wrap gap-2"><button type="button" disabled={busy} onClick={() => void dispositionVisit("completed")} className="min-h-10 rounded-xl border border-[var(--ch-border)] bg-[var(--ch-surface)] px-3 text-sm font-semibold">Mark visit completed</button><button type="button" disabled={busy} onClick={() => void dispositionVisit("cancelled")} className="min-h-10 rounded-xl bg-[var(--ch-error-text)] px-3 text-sm font-semibold text-[var(--ch-accent-text)]">Cancel visit</button></div></section> : null}
        {action ? <ActionPanel action={action} ticket={ticket} busy={busy} now={now} onClose={() => setAction(null)} onMutate={mutate} /> : null}

        <div className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,1fr)_20rem]">
          <section className="flex min-h-[65vh] flex-col overflow-hidden rounded-2xl border border-[var(--ch-border)] bg-[var(--ch-surface-muted)]">
            <div className="border-b border-[var(--ch-border)] px-4 py-3"><h2 className="font-semibold">Conversation & activity</h2><p className="mt-1 line-clamp-2 text-xs text-[var(--ch-text-muted)]">{ticket.description}</p></div>
            <div className="flex-1 space-y-3 overflow-y-auto p-3 sm:p-5">{ticket.timeline.map((item) => <TimelineRow key={item.id} item={item} now={now} onCancel={(messageId) => mutate(() => cancelTicketMessage(ticketId, messageId), false)} onRetry={(messageId) => mutate(() => retryTicketMessage(ticketId, messageId), false)} />)}<div ref={timelineEnd} /></div>
            <form onSubmit={submitMessage} className="border-t border-[var(--ch-border)] bg-[var(--ch-surface)] p-3 sm:p-4">
              {!ticket.messaging_allowed ? <p className="mb-3 rounded-lg border border-[var(--ch-warning-border)] bg-[var(--ch-warning-bg)] p-2 text-sm text-[var(--ch-warning-text)]">Messaging is blocked. An admin must reopen this ticket.</p> : null}
              <div className="flex gap-1 rounded-xl bg-[var(--ch-surface-muted)] p-1">{(["tenant", "vendor", "internal"] as ComposerTarget[]).map((choice) => <button key={choice} type="button" disabled={choice === "vendor" && vendorOrders.length === 0} onClick={() => setTarget(choice)} className={`min-h-9 flex-1 rounded-lg px-2 text-xs font-semibold disabled:opacity-40 ${target === choice ? "bg-[var(--ch-surface-strong)] text-[var(--ch-accent)] shadow-sm" : "text-[var(--ch-text-muted)]"}`}>{choice === "internal" ? "Internal note" : `Reply to ${choice}`}</button>)}</div>
              {target === "vendor" ? <select required value={vendorOrderId} onChange={(event) => setVendorOrderId(event.target.value)} className="mt-2 min-h-11 w-full rounded-xl border border-[var(--ch-border)] bg-[var(--ch-surface-strong)] px-3 text-sm"><option value="">Choose vendor work order</option>{vendorOrders.map((order) => <option key={order.id} value={order.id}>{order.number} · {order.assignee_name}</option>)}</select> : null}
              <textarea value={body} onChange={(event) => setBody(event.target.value)} rows={3} placeholder={target === "internal" ? "Add an internal note…" : `Text the ${target}…`} className="mt-2 w-full resize-none rounded-xl border border-[var(--ch-border)] bg-[var(--ch-surface-strong)] p-3 text-sm outline-none focus:ring-4 focus:ring-[var(--ch-focus-ring)]" />
              {files.length ? <div className="mt-2 flex flex-wrap gap-2">{files.map((file, index) => <span key={`${file.name}-${index}`} className="inline-flex items-center gap-1 rounded-lg border border-[var(--ch-border)] px-2 py-1 text-xs"><Paperclip size={12} />{file.name}<button type="button" aria-label={`Remove ${file.name}`} onClick={() => setFiles((current) => current.filter((_, itemIndex) => itemIndex !== index))}><X size={13} /></button></span>)}</div> : null}
              <div className="mt-2 flex items-center justify-between gap-2"><label className="inline-flex min-h-10 cursor-pointer items-center gap-2 rounded-xl border border-[var(--ch-border)] px-3 text-xs font-semibold"><Paperclip size={15} /> Attach<input type="file" accept="image/jpeg,image/png,image/heic,image/webp" multiple className="hidden" onChange={(event) => setFiles(Array.from(event.target.files || []))} /></label><button type="submit" disabled={busy || !ticket.messaging_allowed || (!body.trim() && files.length === 0)} className="inline-flex min-h-11 items-center gap-2 rounded-xl bg-[var(--ch-accent)] px-4 text-sm font-semibold text-[var(--ch-accent-text)] disabled:opacity-40"><Send size={16} />{target === "internal" ? "Add note" : "Send"}</button></div>
            </form>
          </section>

          <aside className="space-y-4">
            <section className="rounded-2xl border border-[var(--ch-border)] bg-[var(--ch-surface)] p-4"><h2 className="font-semibold">Ticket details</h2><dl className="mt-3 grid grid-cols-2 gap-3 text-sm"><div><dt className="text-xs text-[var(--ch-text-muted)]">SLA</dt><dd className="mt-1 font-semibold">{label(ticket.sla_status)}</dd></div><div><dt className="text-xs text-[var(--ch-text-muted)]">Due</dt><dd className="mt-1 font-semibold">{formatDate(ticket.sla_due_at)}</dd></div><div><dt className="text-xs text-[var(--ch-text-muted)]">Entry</dt><dd className="mt-1 font-semibold">{label(ticket.entry_permission)}</dd></div><div><dt className="text-xs text-[var(--ch-text-muted)]">Chargeback</dt><dd className="mt-1 font-semibold">{ticket.chargeback_flag ? "Flagged" : "No"}</dd></div></dl>{ticket.entry_notes ? <p className="mt-3 border-t border-[var(--ch-border)] pt-3 text-sm text-[var(--ch-text-secondary)]">{ticket.entry_notes}</p> : null}</section>
            <section className="rounded-2xl border border-[var(--ch-border)] bg-[var(--ch-surface)] p-4"><div className="flex items-center justify-between"><h2 className="font-semibold">Work orders</h2><span className="text-xs text-[var(--ch-text-muted)]">{ticket.work_orders.length}</span></div><div className="mt-3 space-y-3">{ticket.work_orders.length ? ticket.work_orders.map((order) => <WorkOrderCard key={order.id} order={order} busy={busy} onComplete={finishOrder} />) : <p className="text-sm text-[var(--ch-text-muted)]">No work orders yet.</p>}</div></section>
          </aside>
        </div>
      </div>
    </main>
  );
}

function ActionPanel({ action, ticket, busy, now, onClose, onMutate }: { action: Exclude<ActionName, null>; ticket: TicketDetail; busy: boolean; now: number; onClose: () => void; onMutate: (task: () => Promise<unknown>, closeAction?: boolean) => Promise<void> }) {
  const field = "min-h-11 w-full rounded-xl border border-[var(--ch-border)] bg-[var(--ch-surface-strong)] px-3 text-sm";
  const categories: TicketCategory[] = ["plumbing", "electrical", "heating", "cooling", "appliance", "doors_locks_windows", "pests", "exterior_grounds", "structural", "water_leak", "no_heat", "gas_smell", "no_power", "security", "other"];
  const priorities: TicketPriority[] = ["emergency", "urgent", "routine", "low"];
  const submitClass = "min-h-11 rounded-xl bg-[var(--ch-accent)] px-4 text-sm font-semibold text-[var(--ch-accent-text)] disabled:opacity-40";
  const blockingVisits = ticket.work_orders.filter((order) => order.scheduled_visit_status === "scheduled" && order.scheduled_start && new Date(order.scheduled_start).getTime() > now);

  function form(task: (data: FormData) => Promise<unknown>) { return (event: FormEvent<HTMLFormElement>) => { event.preventDefault(); const data = new FormData(event.currentTarget); void onMutate(() => task(data)); }; }
  return <section className="mt-3 rounded-2xl border border-[var(--ch-border)] bg-[var(--ch-surface)] p-4"><div className="mb-4 flex items-center justify-between"><h2 className="font-semibold">{label(action)} ticket</h2><button type="button" aria-label="Close action" onClick={onClose} className="grid h-9 w-9 place-items-center rounded-lg border border-[var(--ch-border)]"><X size={16} /></button></div>
    {action === "triage" ? <form onSubmit={form((data) => triageTicket(ticket.id, { category: data.get("category"), priority: data.get("priority"), is_emergency: data.get("emergency") === "on", title: data.get("title"), staff_summary: data.get("summary") || null }))} className="grid gap-3 sm:grid-cols-2"><input name="title" required defaultValue={ticket.title} className={`${field} sm:col-span-2`} /><select name="category" defaultValue={ticket.category || "other"} className={field}>{categories.map((item) => <option key={item} value={item}>{label(item)}</option>)}</select><select name="priority" defaultValue={ticket.priority || "routine"} className={field}>{priorities.map((item) => <option key={item} value={item}>{label(item)}</option>)}</select><textarea name="summary" placeholder="Internal triage summary" className={`${field} min-h-24 py-3 sm:col-span-2`} /><label className="flex items-center gap-2 text-sm"><input name="emergency" type="checkbox" defaultChecked={ticket.is_emergency} /> Emergency</label><button disabled={busy} className={`${submitClass} sm:justify-self-end`}>Save triage</button></form> : null}
    {action === "assign" ? <form onSubmit={form((data) => assignTicket(ticket.id, { assignee_type: data.get("type"), scope: data.get("scope"), assignee_user_id: data.get("type") === "staff" ? data.get("assignee") : null, vendor_id: data.get("type") === "vendor" ? data.get("assignee") : null, cost_estimate: data.get("cost") || null }))} className="grid gap-3 sm:grid-cols-2"><select name="type" defaultValue="staff" className={field}><option value="staff">Staff</option><option value="vendor">Vendor</option></select><select name="assignee" required className={field}><option value="">Choose assignee</option><optgroup label="Staff">{ticket.staff_options.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</optgroup><optgroup label="Vendors">{ticket.vendor_options.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</optgroup></select><textarea name="scope" required placeholder="Work scope" className={`${field} min-h-24 py-3 sm:col-span-2`} /><input name="cost" type="number" min="0" step="0.01" placeholder="Estimated cost" className={field} /><button disabled={busy} className={`${submitClass} sm:justify-self-end`}>Create work order</button></form> : null}
    {action === "schedule" ? <form onSubmit={form((data) => scheduleTicket(ticket.id, { work_order_id: data.get("order"), start: new Date(String(data.get("start"))).toISOString(), end: new Date(String(data.get("end"))).toISOString(), admin_override_reason: data.get("override") || null }))} className="grid gap-3 sm:grid-cols-2"><select name="order" required className={`${field} sm:col-span-2`}><option value="">Choose work order</option>{ticket.work_orders.filter((item) => !["completed", "cancelled"].includes(item.status)).map((item) => <option key={item.id} value={item.id}>{item.number} · {item.assignee_name}</option>)}</select><label className="text-xs text-[var(--ch-text-muted)]">Start<input name="start" type="datetime-local" required className={`mt-1 ${field}`} /></label><label className="text-xs text-[var(--ch-text-muted)]">End<input name="end" type="datetime-local" required className={`mt-1 ${field}`} /></label><textarea name="override" placeholder="Admin override reason, only if entry notice is short" className={`${field} min-h-20 py-3 sm:col-span-2`} /><button disabled={busy} className={`${submitClass} sm:col-start-2 sm:justify-self-end`}>Validate & schedule</button></form> : null}
    {action === "resolve" ? <form onSubmit={form((data) => resolveTicket(ticket.id, String(data.get("note")), data.getAll("cancel_visit").map(String)))} className="grid gap-3"><textarea name="note" required placeholder="Resolution note" className={`${field} min-h-24 py-3`} />{blockingVisits.length ? <fieldset className="rounded-xl border border-[var(--ch-warning-border)] bg-[var(--ch-warning-bg)] p-3"><legend className="px-1 text-sm font-semibold text-[var(--ch-warning-text)]">Scheduled visits blocking resolve</legend><p className="mb-2 text-xs text-[var(--ch-text-secondary)]">Confirm each cancellation to resolve. If an entry notice was sent, the tenant will receive a cancellation text.</p><div className="space-y-2">{blockingVisits.map((order) => <label key={order.id} className="flex items-start gap-2 text-sm"><input type="checkbox" name="cancel_visit" value={order.id} required className="mt-1" /><span><strong>{order.number}</strong><br /><span className="text-xs text-[var(--ch-text-muted)]">{formatDate(order.scheduled_start)}{order.scheduled_end ? ` – ${formatDate(order.scheduled_end)}` : ""}</span></span></label>)}</div></fieldset> : <p className="text-xs text-[var(--ch-text-muted)]">This marks the ticket resolved. It does not block follow-up messages.</p>}<button disabled={busy} className={`${submitClass} justify-self-end`}>{blockingVisits.length ? "Cancel visits & mark resolved" : "Mark resolved"}</button></form> : null}
    {action === "more" ? <form onSubmit={form((data) => ticketMoreAction(ticket.id, { action: data.get("action"), reason: data.get("reason") || null, canonical_ticket_id: data.get("canonical") || null }))} className="grid gap-3 sm:grid-cols-2"><select name="action" className={field}><option value="toggle_chargeback">Toggle chargeback flag</option><option value="cancel">Cancel ticket</option><option value="duplicate">Mark duplicate</option>{["closed", "cancelled", "duplicate"].includes(ticket.status) ? <option value="reopen">Reopen (admin)</option> : null}</select><input name="canonical" placeholder="Canonical ticket UUID (duplicate only)" className={field} /><textarea name="reason" placeholder="Reason or note" className={`${field} min-h-20 py-3 sm:col-span-2`} /><button disabled={busy} className={`${submitClass} sm:col-start-2 sm:justify-self-end`}>Apply action</button></form> : null}
  </section>;
}
