"use client";

import FullCalendar from "@fullcalendar/react";
import dayGridPlugin from "@fullcalendar/daygrid";
import interactionPlugin, { Draggable, type DropArg } from "@fullcalendar/interaction";
import listPlugin from "@fullcalendar/list";
import timeGridPlugin from "@fullcalendar/timegrid";
import type { DatesSetArg, EventClickArg, EventContentArg, EventDropArg } from "@fullcalendar/core";
import { AlertCircle, CalendarClock, ChevronLeft, ChevronRight, GripVertical, X } from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  getMaintenanceCalendar,
  previewScheduledVisit,
  scheduleTicket,
  type CalendarUnscheduled,
  type CalendarVisit,
  type CalendarVisitType,
  type MaintenanceCalendarResponse,
  type ScheduleTicketRequest,
  type TicketStatus,
} from "@/lib/api/maintenance";
import { validateCalendarDrop, winnipegDateTimeFields, winnipegLocalToIso } from "@/lib/maintenance-calendar";

const EMPTY: MaintenanceCalendarResponse = { timezone: "America/Winnipeg", visits: [], unscheduled: [], properties: [], assignees: [] };
const statusOptions: TicketStatus[] = ["new", "triaged", "assigned", "scheduled", "in_progress", "awaiting_parts", "awaiting_tenant", "resolved"];
const label = (value: string) => value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());

type Draft = {
  ticketId: string;
  workOrderId: string;
  title: string;
  start: Date;
  end: Date;
  visitType: CalendarVisitType;
  reschedule: boolean;
};

function age(createdAt: string) {
  const hours = Math.max(0, Math.floor((Date.now() - new Date(createdAt).getTime()) / 3_600_000));
  if (hours < 24) return `${hours}h old`;
  const days = Math.floor(hours / 24);
  return `${days}d old`;
}

function noticeBadge(status: CalendarVisit["notice_status"]) {
  if (!status) return null;
  const classes = status === "failed"
    ? "bg-[var(--ch-error-text)] text-[var(--ch-accent-text)] ring-2 ring-[var(--ch-error-border)]"
    : status === "delivered"
      ? "bg-[var(--ch-success-bg)] text-[var(--ch-success-text)]"
      : "bg-[var(--ch-surface-strong)] text-[var(--ch-text-primary)]";
  return <span className={`rounded px-1.5 py-0.5 text-[10px] font-bold uppercase ${classes}`}>{status}</span>;
}

export default function MaintenanceCalendar() {
  const router = useRouter();
  const calendarRef = useRef<FullCalendar | null>(null);
  const backlogRef = useRef<HTMLDivElement | null>(null);
  const [data, setData] = useState(EMPTY);
  const [range, setRange] = useState<{ start: string; end: string } | null>(null);
  const [filters, setFilters] = useState<{ property?: number; assignee?: string; type?: CalendarVisitType; status?: TicketStatus }>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [title, setTitle] = useState("");
  const [isMobile, setIsMobile] = useState(false);
  const [mobileTab, setMobileTab] = useState<"calendar" | "unscheduled">("calendar");
  const [draft, setDraft] = useState<Draft | null>(null);

  useEffect(() => {
    const media = window.matchMedia("(max-width: 767px)");
    const update = () => {
      setIsMobile(media.matches);
      calendarRef.current?.getApi().changeView(media.matches ? "listWeek" : "timeGridWeek");
    };
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);

  const load = useCallback(async () => {
    if (!range) return;
    setBusy(true);
    setError("");
    try {
      setData(await getMaintenanceCalendar({
        start: range.start,
        end: range.end,
        property_id: filters.property,
        assignee_id: filters.assignee,
        visit_type: filters.type,
        status: filters.status,
      }));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not load the maintenance calendar");
    } finally {
      setBusy(false);
    }
  }, [filters, range]);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  const openDraft = useCallback((item: CalendarUnscheduled | CalendarVisit, start: Date, end: Date, reschedule: boolean) => {
    const reason = validateCalendarDrop({ start, end, visitType: item.visit_type, completed: "visit_status" in item && item.visit_status === "completed" });
    if (reason) {
      setError(reason);
      return;
    }
    if (!item.work_order_id) {
      setError("Assign this ticket before scheduling a visit.");
      return;
    }
    setError("");
    setDraft({ ticketId: item.ticket_id, workOrderId: item.work_order_id, title: item.title, start, end, visitType: item.visit_type, reschedule });
  }, []);

  useEffect(() => {
    if (!backlogRef.current) return;
    const draggable = new Draggable(backlogRef.current, {
      itemSelector: "[data-work-order-id]",
      eventData: (element) => ({ title: element.dataset.title || "Maintenance visit", duration: "01:00", create: false }),
    });
    return () => draggable.destroy();
  }, [data.unscheduled, mobileTab]);

  const events = useMemo(() => data.visits.map((visit) => ({
    id: visit.id,
    title: `${visit.address} · ${visit.unit}`,
    start: visit.start,
    end: visit.end,
    editable: visit.draggable,
    classNames: [`visit-${visit.visit_type}`, visit.visit_status === "completed" ? "visit-completed" : ""],
    extendedProps: { visit },
  })), [data.visits]);

  const handleDrop = (info: DropArg) => {
    const item = data.unscheduled.find((candidate) => candidate.work_order_id === info.draggedEl.dataset.workOrderId);
    if (item) openDraft(item, info.date, new Date(info.date.getTime() + 3_600_000), false);
  };

  const handleEventDrop = (info: EventDropArg) => {
    const visit = info.event.extendedProps.visit as CalendarVisit;
    const start = info.event.start;
    const end = info.event.end || (start ? new Date(start.getTime() + 3_600_000) : null);
    info.revert();
    if (start && end) openDraft(visit, start, end, true);
  };

  const handleDates = (info: DatesSetArg) => {
    setTitle(info.view.title);
    setRange((current) => current?.start === info.startStr && current.end === info.endStr ? current : { start: info.startStr, end: info.endStr });
  };

  const renderEvent = (info: EventContentArg) => {
    const visit = info.event.extendedProps.visit as CalendarVisit;
    return (
      <div className="min-w-0 px-0.5 py-0.5 leading-tight">
        <div className="calendar-event-heading flex items-center gap-1"><strong className="calendar-event-location truncate">{visit.address} · {visit.unit}</strong>{noticeBadge(visit.notice_status)}</div>
        <div className="truncate text-[11px]">{visit.title}</div>
        <div className="truncate text-[10px] opacity-80">{visit.assignee_name}</div>
      </div>
    );
  };

  const backlog = (
    <aside className="rounded-2xl border border-[var(--ch-border)] bg-[var(--ch-surface)] p-3 md:w-80 md:shrink-0" aria-label="Unscheduled maintenance">
      <div className="flex items-center justify-between border-b border-[var(--ch-border)] pb-3">
        <div><h2 className="font-semibold">Unscheduled</h2><p className="text-xs text-[var(--ch-text-muted)]">Emergency first, then oldest</p></div>
        <span className="rounded-full bg-[var(--ch-surface-muted)] px-2 py-1 text-xs font-bold">{data.unscheduled.length}</span>
      </div>
      <div ref={backlogRef} className="mt-3 max-h-[650px] space-y-2 overflow-y-auto pr-1">
        {data.unscheduled.length === 0 ? <p className="py-8 text-center text-sm text-[var(--ch-text-muted)]">Nothing waiting to be scheduled.</p> : null}
        {data.unscheduled.map((item) => (
          <article
            key={item.id}
            data-work-order-id={item.draggable ? item.work_order_id || undefined : undefined}
            data-title={item.title}
            className={`rounded-xl border p-3 ${item.is_emergency ? "border-[var(--ch-error-border)] bg-[var(--ch-error-bg)]" : "border-[var(--ch-border)] bg-[var(--ch-surface-strong)]"} ${item.draggable ? "cursor-grab active:cursor-grabbing" : ""}`}
          >
            <div className="flex items-start gap-2">
              {item.draggable ? <GripVertical size={16} className="mt-0.5 shrink-0 text-[var(--ch-text-muted)]" /> : <CalendarClock size={16} className="mt-0.5 shrink-0 text-[var(--ch-text-muted)]" />}
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-1.5 text-[10px] font-bold uppercase">
                  <span>{item.ticket_number}</span><span className={item.is_emergency ? "text-[var(--ch-error-text)]" : "text-[var(--ch-text-muted)]"}>{item.priority || "untriaged"}</span><span className="text-[var(--ch-text-muted)]">{age(item.created_at)}</span>
                </div>
                <p className="mt-1 truncate text-sm font-semibold">{item.address} · {item.unit}</p>
                <p className="mt-0.5 line-clamp-2 text-xs text-[var(--ch-text-secondary)]">{item.title}</p>
                {!item.draggable ? <p className="mt-1 text-[10px] font-semibold text-[var(--ch-warning-text)]">Assign first to schedule</p> : null}
              </div>
            </div>
          </article>
        ))}
      </div>
    </aside>
  );

  return (
    <section className="mt-5">
      <div className="grid gap-3 rounded-2xl border border-[var(--ch-border)] bg-[var(--ch-surface)] p-4 sm:grid-cols-2 lg:grid-cols-4" aria-label="Calendar filters">
        <select aria-label="Property" value={filters.property || ""} onChange={(event) => setFilters((current) => ({ ...current, property: event.target.value ? Number(event.target.value) : undefined }))} className="min-h-11 rounded-xl border border-[var(--ch-border)] bg-[var(--ch-surface-strong)] px-3 text-sm">
          <option value="">All properties</option>{data.properties.map((property) => <option key={property.id} value={property.id}>{property.name}</option>)}
        </select>
        <select aria-label="Vendor or assignee" value={filters.assignee || ""} onChange={(event) => setFilters((current) => ({ ...current, assignee: event.target.value || undefined }))} className="min-h-11 rounded-xl border border-[var(--ch-border)] bg-[var(--ch-surface-strong)] px-3 text-sm">
          <option value="">All vendors / assignees</option>{data.assignees.map((person) => <option key={person.id} value={person.id}>{person.name} · {label(person.type)}</option>)}
        </select>
        <select aria-label="Visit type" value={filters.type || ""} onChange={(event) => setFilters((current) => ({ ...current, type: event.target.value as CalendarVisitType || undefined }))} className="min-h-11 rounded-xl border border-[var(--ch-border)] bg-[var(--ch-surface-strong)] px-3 text-sm">
          <option value="">All visit types</option><option value="routine">Routine</option><option value="tenant_consent">Tenant consent</option><option value="emergency">Emergency</option>
        </select>
        <select aria-label="Ticket status" value={filters.status || ""} onChange={(event) => setFilters((current) => ({ ...current, status: event.target.value as TicketStatus || undefined }))} className="min-h-11 rounded-xl border border-[var(--ch-border)] bg-[var(--ch-surface-strong)] px-3 text-sm">
          <option value="">All ticket statuses</option>{statusOptions.map((status) => <option key={status} value={status}>{label(status)}</option>)}
        </select>
      </div>

      {error ? <div className="mt-3 flex items-start gap-2 rounded-xl border border-[var(--ch-error-border)] bg-[var(--ch-error-bg)] p-3 text-sm text-[var(--ch-error-text)]"><AlertCircle size={17} className="mt-0.5 shrink-0" /><span>{error}</span><button type="button" className="ml-auto" onClick={() => setError("")} aria-label="Dismiss"><X size={16} /></button></div> : null}

      <div className="mt-4 flex rounded-xl border border-[var(--ch-border)] p-1 md:hidden">
        <button type="button" onClick={() => setMobileTab("calendar")} className={`min-h-10 flex-1 rounded-lg text-sm font-semibold ${mobileTab === "calendar" ? "bg-[var(--ch-accent)] text-white" : ""}`}>Agenda</button>
        <button type="button" onClick={() => setMobileTab("unscheduled")} className={`min-h-10 flex-1 rounded-lg text-sm font-semibold ${mobileTab === "unscheduled" ? "bg-[var(--ch-accent)] text-white" : ""}`}>Unscheduled ({data.unscheduled.length})</button>
      </div>

      <div className="mt-4 flex gap-4">
        <div className={`${mobileTab === "unscheduled" ? "hidden md:block" : "block"} min-w-0 flex-1 rounded-2xl border border-[var(--ch-border)] bg-[var(--ch-surface)] p-3 sm:p-4`}>
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-1">
              <button type="button" aria-label="Previous" onClick={() => calendarRef.current?.getApi().prev()} className="rounded-lg border border-[var(--ch-border)] p-2"><ChevronLeft size={17} /></button>
              <button type="button" onClick={() => calendarRef.current?.getApi().today()} className="min-h-9 rounded-lg border border-[var(--ch-border)] px-3 text-xs font-semibold">Today</button>
              <button type="button" aria-label="Next" onClick={() => calendarRef.current?.getApi().next()} className="rounded-lg border border-[var(--ch-border)] p-2"><ChevronRight size={17} /></button>
            </div>
            <h2 className="text-sm font-semibold sm:text-base">{title}{busy ? <span className="ml-2 text-xs font-normal text-[var(--ch-text-muted)]">Loading…</span> : null}</h2>
            <div className="hidden rounded-lg border border-[var(--ch-border)] p-1 md:flex">
              {[["timeGridDay", "Day"], ["timeGridWeek", "Week"], ["dayGridMonth", "Month"]].map(([view, text]) => <button type="button" key={view} onClick={() => calendarRef.current?.getApi().changeView(view)} className="rounded-md px-3 py-1.5 text-xs font-semibold hover:bg-[var(--ch-surface-muted)]">{text}</button>)}
            </div>
          </div>
          <FullCalendar
            ref={calendarRef}
            plugins={[dayGridPlugin, timeGridPlugin, listPlugin, interactionPlugin]}
            initialView={isMobile ? "listWeek" : "timeGridWeek"}
            headerToolbar={false}
            timeZone="America/Winnipeg"
            firstDay={1}
            height="auto"
            slotMinTime="06:00:00"
            slotMaxTime="22:00:00"
            scrollTime="08:00:00"
            nowIndicator
            editable
            droppable
            eventDurationEditable={false}
            events={events}
            datesSet={handleDates}
            drop={handleDrop}
            eventDrop={handleEventDrop}
            eventClick={(info: EventClickArg) => router.push((info.event.extendedProps.visit as CalendarVisit).href)}
            eventContent={renderEvent}
            eventDidMount={(info) => {
              const visit = info.event.extendedProps.visit as CalendarVisit;
              info.el.title = `${visit.address} · ${visit.unit}\n${visit.title}\n${visit.assignee_name}`;
            }}
            slotLaneClassNames={(info) => info.date && info.date.getUTCHours() >= 8 && info.date.getUTCHours() < 20 ? ["entry-window-slot"] : []}
          />
        </div>
        <div className={`${mobileTab === "unscheduled" ? "block" : "hidden"} md:block`}>{backlog}</div>
      </div>
      {draft ? <ScheduleModal draft={draft} onClose={() => setDraft(null)} onSaved={async () => { setDraft(null); await load(); }} /> : null}
    </section>
  );
}

function ScheduleModal({ draft, onClose, onSaved }: { draft: Draft; onClose: () => void; onSaved: () => Promise<void> }) {
  const startFields = winnipegDateTimeFields(draft.start);
  const endFields = winnipegDateTimeFields(draft.end);
  const [date, setDate] = useState(startFields.date);
  const [startTime, setStartTime] = useState(startFields.time);
  const [endTime, setEndTime] = useState(endFields.time);
  const [basis, setBasis] = useState<CalendarVisitType>(draft.visitType);
  const [reason, setReason] = useState("");
  const [evidence, setEvidence] = useState("");
  const [preview, setPreview] = useState<{ message: string; request: ScheduleTicketRequest } | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const request = (): ScheduleTicketRequest => ({
    work_order_id: draft.workOrderId,
    start: winnipegLocalToIso(date, startTime),
    end: winnipegLocalToIso(date, endTime),
    access_basis: basis,
    consent_evidence: basis === "tenant_consent" ? evidence.trim() || null : null,
    reason: reason.trim() || null,
  });
  const previewMatches = preview && JSON.stringify(preview.request) === JSON.stringify(request());

  const makePreview = async () => {
    setBusy(true); setError("");
    try {
      if (!reason.trim()) throw new Error("Reason for entry is required.");
      const next = request();
      const validation = validateCalendarDrop({ start: new Date(next.start), end: new Date(next.end), visitType: basis });
      if (validation) throw new Error(validation);
      const result = await previewScheduledVisit(draft.ticketId, next);
      setPreview({ message: result.message, request: next });
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Could not preview this visit"); }
    finally { setBusy(false); }
  };
  const confirm = async () => {
    if (!preview || !previewMatches) { setError("Preview the current details before confirming."); return; }
    setBusy(true); setError("");
    try { await scheduleTicket(draft.ticketId, preview.request); await onSaved(); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Could not schedule this visit"); }
    finally { setBusy(false); }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-[var(--ch-overlay)] p-0 sm:items-center sm:p-4" role="dialog" aria-modal="true" aria-labelledby="schedule-title">
      <div className="max-h-[95vh] w-full overflow-y-auto rounded-t-2xl bg-[var(--ch-surface)] p-5 shadow-2xl sm:max-w-xl sm:rounded-2xl">
        <div className="flex items-start justify-between gap-3"><div><p className="text-xs font-semibold uppercase tracking-wide text-[var(--ch-accent)]">{draft.reschedule ? "Reschedule visit" : "Schedule visit"}</p><h2 id="schedule-title" className="mt-1 text-xl font-semibold">{draft.title}</h2></div><button type="button" onClick={onClose} className="rounded-lg p-2 hover:bg-[var(--ch-surface-muted)]" aria-label="Close"><X size={20} /></button></div>
        {draft.reschedule ? <p className="mt-3 rounded-lg bg-[var(--ch-warning-bg)] p-3 text-xs text-[var(--ch-warning-text)]">Confirming sends a cancellation for the old time and a new notice for this time. Nothing is sent until you confirm.</p> : <p className="mt-3 text-xs text-[var(--ch-text-muted)]">Dropping only prefills this form. Nothing is sent until you preview and confirm.</p>}
        <div className="mt-4 grid gap-3 sm:grid-cols-3">
          <label className="text-xs font-semibold">Date<input type="date" value={date} onChange={(event) => { setDate(event.target.value); setPreview(null); }} className="mt-1 min-h-11 w-full rounded-xl border border-[var(--ch-border)] px-3 text-sm" /></label>
          <label className="text-xs font-semibold">Start<input type="time" value={startTime} onChange={(event) => { setStartTime(event.target.value); setPreview(null); }} className="mt-1 min-h-11 w-full rounded-xl border border-[var(--ch-border)] px-3 text-sm" /></label>
          <label className="text-xs font-semibold">End<input type="time" value={endTime} onChange={(event) => { setEndTime(event.target.value); setPreview(null); }} className="mt-1 min-h-11 w-full rounded-xl border border-[var(--ch-border)] px-3 text-sm" /></label>
        </div>
        <label className="mt-3 block text-xs font-semibold">Visit type<select value={basis} onChange={(event) => { setBasis(event.target.value as CalendarVisitType); setPreview(null); }} className="mt-1 min-h-11 w-full rounded-xl border border-[var(--ch-border)] px-3 text-sm"><option value="routine">Routine entry notice</option><option value="tenant_consent">Tenant consent</option><option value="emergency">Emergency</option></select></label>
        {basis === "tenant_consent" ? <label className="mt-3 block text-xs font-semibold">Consent evidence<textarea value={evidence} onChange={(event) => { setEvidence(event.target.value); setPreview(null); }} placeholder="Paste the tenant message or enter a staff note" className="mt-1 min-h-20 w-full rounded-xl border border-[var(--ch-border)] p-3 text-sm" /></label> : null}
        <label className="mt-3 block text-xs font-semibold">Reason for entry <span className="text-[var(--ch-error-text)]">*</span><textarea value={reason} onChange={(event) => { setReason(event.target.value); setPreview(null); }} placeholder="What work will be performed?" className="mt-1 min-h-20 w-full rounded-xl border border-[var(--ch-border)] p-3 text-sm" /></label>
        {error ? <p className="mt-3 rounded-lg border border-[var(--ch-error-border)] bg-[var(--ch-error-bg)] p-3 text-sm text-[var(--ch-error-text)]">{error}</p> : null}
        {preview ? <div className="mt-4 rounded-xl border border-[var(--ch-info-border)] bg-[var(--ch-info-bg)] p-4"><p className="text-xs font-bold uppercase text-[var(--ch-info-text)]">Message preview</p><p className="mt-2 whitespace-pre-wrap text-sm">{preview.message}</p></div> : null}
        <div className="mt-5 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end"><button type="button" onClick={onClose} className="min-h-11 rounded-xl border border-[var(--ch-border)] px-4 text-sm font-semibold">Cancel</button>{!previewMatches ? <button type="button" disabled={busy} onClick={() => void makePreview()} className="min-h-11 rounded-xl bg-[var(--ch-accent)] px-4 text-sm font-semibold text-white disabled:opacity-50">{busy ? "Checking…" : "Preview notice"}</button> : <button type="button" disabled={busy} onClick={() => void confirm()} className="min-h-11 rounded-xl bg-[var(--ch-accent)] px-4 text-sm font-semibold text-white disabled:opacity-50">{busy ? "Sending…" : "Confirm & send"}</button>}</div>
      </div>
    </div>
  );
}
