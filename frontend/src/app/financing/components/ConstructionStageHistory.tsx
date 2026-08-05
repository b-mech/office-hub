"use client";

import { useEffect, useState } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";
import { getConstructionStageHistory, type ConstructionStageHistoryEvent } from "@/lib/api/construction-stage-history";

const dateFormatter = new Intl.DateTimeFormat("en-CA", {
  year: "numeric",
  month: "short",
  day: "numeric",
});

export function ConstructionStageHistory({ propertyId }: { propertyId: string }) {
  const [events, setEvents] = useState<ConstructionStageHistoryEvent[]>([]);
  const [expanded, setExpanded] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    getConstructionStageHistory(propertyId)
      .then((rows) => { if (active) setEvents(rows); })
      .catch((reason) => { if (active) setError(reason instanceof Error ? reason.message : "Unable to load history"); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [propertyId]);

  return (
    <section className="mb-4 rounded-lg border border-[var(--ch-border)] bg-[var(--ch-surface)] px-4 py-3">
      <button
        type="button"
        onClick={() => setExpanded((value) => !value)}
        className="flex w-full items-center justify-between gap-3 text-left"
        aria-expanded={expanded}
      >
        <span>
          <span className="block text-sm font-semibold">Construction Stage History</span>
          <span className="mt-0.5 block text-xs text-[var(--ch-text-muted)]">
            {loading ? "Loading history…" : `${events.length} recorded transition${events.length === 1 ? "" : "s"}`}
          </span>
        </span>
        {expanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
      </button>

      {expanded ? (
        <div className="mt-3 border-t border-[var(--ch-border)] pt-3">
          {error ? <p className="text-xs text-[var(--ch-error-text)]">{error}</p> : null}
          {!loading && !error && events.length === 0 ? (
            <p className="text-xs text-[var(--ch-text-muted)]">No recorded history yet.</p>
          ) : null}
          {events.length ? (
            <ol className="space-y-3">
              {events.map((event) => (
                <li key={event.id} className="border-l-2 border-[var(--ch-border)] pl-3">
                  <p className="text-sm font-medium">
                    {event.previous_stage || "First recorded stage"} → {event.new_stage}
                  </p>
                  <time className="mt-0.5 block text-xs text-[var(--ch-text-muted)]" dateTime={event.changed_at}>
                    Detected {formatDate(event.changed_at)}
                  </time>
                </li>
              ))}
            </ol>
          ) : null}
          <p className="mt-3 text-[10px] text-[var(--ch-text-muted)]">
            Dates reflect when Office Hub observed the sheet change, not necessarily when the cell was edited.
          </p>
        </div>
      ) : null}
    </section>
  );
}

function formatDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : dateFormatter.format(date);
}
