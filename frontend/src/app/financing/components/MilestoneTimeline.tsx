"use client";

import { useState } from "react";
import { Check, ChevronDown, ChevronUp, Circle, Pencil } from "lucide-react";
import { updateConstructionMilestone } from "@/lib/api/financing";
import type { ConstructionMilestone } from "@/types/financing";

const dateFormatter = new Intl.DateTimeFormat("en-CA", {
  year: "numeric",
  month: "short",
  day: "numeric",
});

function formatDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : dateFormatter.format(date);
}

function toDateInput(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "" : date.toISOString().slice(0, 10);
}

export function MilestoneTimeline({
  currentStage,
  achievedAt,
  history,
  onUpdated,
}: {
  currentStage?: string | null;
  achievedAt?: string | null;
  history: ConstructionMilestone[];
  onUpdated: () => Promise<void>;
}) {
  const [editingId, setEditingId] = useState<string | null>(null);
  const [achievedOn, setAchievedOn] = useState("");
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expandedHistory, setExpandedHistory] = useState<Set<string>>(
    new Set(),
  );
  const events = [...history].reverse();

  function beginReview(event: ConstructionMilestone) {
    setEditingId(event.id);
    setAchievedOn(toDateInput(event.achieved_at));
    setNote(event.confirmation_note || "");
    setError(null);
  }

  async function save(event: ConstructionMilestone) {
    if (!achievedOn) return;
    setSaving(true);
    setError(null);
    try {
      await updateConstructionMilestone(event.id, {
        achieved_on: achievedOn,
        note: note || null,
      });
      await onUpdated();
      setEditingId(null);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Unable to save milestone date",
      );
    } finally {
      setSaving(false);
    }
  }

  function toggleHistory(id: string) {
    setExpandedHistory((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  return (
    <section className="mb-4 rounded-lg border border-[var(--ch-border)] bg-[var(--ch-surface)] p-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h3 className="text-sm font-semibold">Construction Stage Timeline</h3>
          <p className="mt-1 text-xs text-[var(--ch-text-muted)]">
            Sheet dates are first-observed estimates until you review and confirm
            them.
          </p>
        </div>
        {achievedAt ? (
          <div className="shrink-0 text-right">
            <p className="text-[10px] font-semibold uppercase tracking-wide text-[var(--ch-text-muted)]">
              Current since
            </p>
            <p className="mt-1 text-sm font-semibold text-[var(--ch-accent)]">
              {formatDate(achievedAt)}
            </p>
          </div>
        ) : null}
      </div>

      {events.length ? (
        <ol className="mt-5">
          {events.map((event, index) => {
            const isCurrent = index === 0 && event.stage === currentStage;
            const isLast = index === events.length - 1;
            const isEditing = editingId === event.id;
            const isConfirmed = Boolean(event.confirmed_at);
            const revisions = event.revisions || [];
            const isHistoryExpanded = expandedHistory.has(event.id);
            return (
              <li
                key={event.id}
                className="relative grid grid-cols-[28px_1fr] gap-3 pb-5 last:pb-0"
              >
                {!isLast ? (
                  <span
                    className="absolute left-[13px] top-6 h-[calc(100%-8px)] w-px bg-[var(--ch-border)]"
                    aria-hidden="true"
                  />
                ) : null}
                <span
                  className={`relative z-10 flex h-7 w-7 items-center justify-center rounded-full border-2 ${
                    isCurrent
                      ? "border-[var(--ch-accent)] bg-[var(--ch-accent)] text-white"
                      : "border-[var(--ch-border)] bg-[var(--ch-surface)] text-[var(--ch-text-muted)]"
                  }`}
                  aria-hidden="true"
                >
                  {isCurrent ? (
                    <Check size={14} strokeWidth={3} />
                  ) : (
                    <Circle size={8} fill="currentColor" />
                  )}
                </span>
                <div className="min-w-0 pt-0.5">
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div>
                      <p
                        className={`text-sm font-semibold ${
                          isCurrent
                            ? "text-[var(--ch-accent)]"
                            : "text-[var(--ch-text-primary)]"
                        }`}
                      >
                        {event.stage}
                      </p>
                      <div className="mt-1 flex flex-wrap items-center gap-2">
                        <span
                          className={`rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${
                            isConfirmed
                              ? "bg-[var(--ch-success-bg)] text-[var(--ch-success-text)]"
                              : "bg-[var(--ch-warning-bg)] text-[var(--ch-warning-text)]"
                          }`}
                        >
                          {isConfirmed ? "Confirmed" : "Needs review"}
                        </span>
                        {isCurrent ? (
                          <span className="text-xs text-[var(--ch-text-secondary)]">
                            Current milestone
                          </span>
                        ) : null}
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <time
                        dateTime={event.achieved_at}
                        className="text-xs font-medium tabular-nums text-[var(--ch-text-muted)]"
                      >
                        {formatDate(event.achieved_at)}
                      </time>
                      <button
                        type="button"
                        onClick={() => beginReview(event)}
                        className="rounded-md border border-[var(--ch-border)] p-1.5 text-[var(--ch-text-muted)] hover:bg-[var(--ch-surface-hover)]"
                        aria-label={`Review ${event.stage} date`}
                      >
                        <Pencil size={13} />
                      </button>
                    </div>
                  </div>

                  {event.confirmation_note ? (
                    <p className="mt-2 text-xs text-[var(--ch-text-secondary)]">
                      {event.confirmation_note}
                    </p>
                  ) : null}

                  {isEditing ? (
                    <div className="mt-3 rounded-md border border-[var(--ch-border)] bg-[var(--ch-surface-muted)] p-3">
                      <label className="block text-xs font-medium">
                        Confirmed stage date
                        <input
                          type="date"
                          value={achievedOn}
                          onChange={(inputEvent) =>
                            setAchievedOn(inputEvent.target.value)
                          }
                          className="mt-1 block w-full rounded-md border border-[var(--ch-border)] bg-[var(--ch-surface)] px-3 py-2 text-sm"
                        />
                      </label>
                      <label className="mt-3 block text-xs font-medium">
                        Evidence or note (optional)
                        <input
                          value={note}
                          onChange={(inputEvent) =>
                            setNote(inputEvent.target.value)
                          }
                          placeholder="e.g. confirmed from site report"
                          maxLength={1000}
                          className="mt-1 block w-full rounded-md border border-[var(--ch-border)] bg-[var(--ch-surface)] px-3 py-2 text-sm"
                        />
                      </label>
                      {error ? (
                        <p className="mt-2 text-xs text-[var(--ch-error-text)]">
                          {error}
                        </p>
                      ) : null}
                      <div className="mt-3 flex justify-end gap-2">
                        <button
                          type="button"
                          onClick={() => setEditingId(null)}
                          disabled={saving}
                          className="rounded-md border border-[var(--ch-border)] px-3 py-1.5 text-xs font-semibold"
                        >
                          Cancel
                        </button>
                        <button
                          type="button"
                          onClick={() => save(event)}
                          disabled={saving || !achievedOn}
                          className="rounded-md bg-[var(--ch-accent)] px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-50"
                        >
                          {saving ? "Saving..." : "Save & confirm"}
                        </button>
                      </div>
                    </div>
                  ) : null}

                  {revisions.length ? (
                    <div className="mt-2">
                      <button
                        type="button"
                        onClick={() => toggleHistory(event.id)}
                        className="flex items-center gap-1 text-xs font-medium text-[var(--ch-text-muted)] hover:text-[var(--ch-text-primary)]"
                      >
                        {isHistoryExpanded ? (
                          <ChevronUp size={13} />
                        ) : (
                          <ChevronDown size={13} />
                        )}
                        {revisions.length} review
                        {revisions.length === 1 ? "" : "s"}
                      </button>
                      {isHistoryExpanded ? (
                        <ul className="mt-2 space-y-2 border-l border-[var(--ch-border)] pl-3">
                          {[...revisions].reverse().map((revision) => (
                            <li
                              key={revision.id}
                              className="text-xs text-[var(--ch-text-secondary)]"
                            >
                              <span className="font-medium">
                                {revision.action === "date_corrected"
                                  ? `${formatDate(revision.previous_achieved_at)} → ${formatDate(revision.achieved_at)}`
                                  : `Confirmed ${formatDate(revision.achieved_at)}`}
                              </span>
                              {" · "}
                              {formatDate(revision.created_at)}
                              {revision.note ? ` · ${revision.note}` : ""}
                            </li>
                          ))}
                        </ul>
                      ) : null}
                    </div>
                  ) : null}
                </div>
              </li>
            );
          })}
        </ol>
      ) : (
        <div className="mt-4 flex items-center gap-3 rounded-md bg-[var(--ch-surface-muted)] px-3 py-3">
          <span className="h-2.5 w-2.5 rounded-full bg-[var(--ch-border)]" />
          <p className="text-xs text-[var(--ch-text-muted)]">
            {currentStage && currentStage !== "NA"
              ? "This milestone predates date tracking. Its date will appear after the next stage change."
              : "No construction milestones have been recorded yet."}
          </p>
        </div>
      )}
    </section>
  );
}
