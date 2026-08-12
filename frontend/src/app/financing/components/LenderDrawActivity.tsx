"use client";

import { useEffect, useMemo, useState } from "react";
import {
  getProDrawRequests,
  updateProDrawRequestBatch,
} from "@/lib/api/financing";
import type { ProDrawRequest } from "@/types/financing";

const money = new Intl.NumberFormat("en-CA", {
  style: "currency",
  currency: "CAD",
  maximumFractionDigits: 0,
});

const statuses = [
  "prepared",
  "sent",
  "acknowledged",
  "lawyer_processing",
  "funded",
  "closed",
  "cancelled",
];

interface RequestBatch {
  batchId: string;
  items: ProDrawRequest[];
  total: number;
  latest: ProDrawRequest;
}

export function LenderDrawActivity() {
  const [requests, setRequests] = useState<ProDrawRequest[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busyBatch, setBusyBatch] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    getProDrawRequests()
      .then((items) => {
        if (active) setRequests(items);
      })
      .catch((err) => {
        if (active) setError(err instanceof Error ? err.message : "Could not load draw activity");
      });
    return () => {
      active = false;
    };
  }, []);

  const batches = useMemo(() => {
    const grouped = new Map<string, ProDrawRequest[]>();
    requests.forEach((request) => {
      grouped.set(request.batch_id, [...(grouped.get(request.batch_id) || []), request]);
    });
    return [...grouped.entries()]
      .map(([batchId, items]): RequestBatch => ({
        batchId,
        items,
        total: items.reduce((sum, item) => sum + Number(item.amount), 0),
        latest: [...items].sort((a, b) => b.updated_at.localeCompare(a.updated_at))[0],
      }))
      .sort((a, b) => b.latest.created_at.localeCompare(a.latest.created_at))
      .slice(0, 10);
  }, [requests]);

  async function updateStatus(batch: RequestBatch, status: string) {
    setBusyBatch(batch.batchId);
    setError(null);
    try {
      await updateProDrawRequestBatch(batch.batchId, status);
      setRequests(await getProDrawRequests());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not update batch status");
    } finally {
      setBusyBatch(null);
    }
  }

  return (
    <section className="rounded-lg border border-[var(--ch-border)] bg-[var(--ch-surface)] p-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-base font-semibold">PRO Draw Request Activity</h2>
          <p className="mt-1 text-xs text-[var(--ch-text-muted)]">
            Track requests from preparation through Michaela, the lawyer, funding, and closure.
          </p>
        </div>
        <span className="rounded-full bg-[var(--ch-accent-soft)] px-2 py-1 text-xs font-semibold text-[var(--ch-accent)]">
          {batches.length} recent
        </span>
      </div>
      {error ? <p className="mt-3 text-sm text-[var(--ch-error-text)]">{error}</p> : null}
      <div className="mt-4 space-y-3">
        {batches.map((batch) => {
          const request = batch.latest;
          return (
            <article key={batch.batchId} className="rounded-md border border-[var(--ch-border)] p-3">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <p className="text-lg font-bold">{money.format(batch.total)}</p>
                  <p className="text-xs text-[var(--ch-text-muted)]">
                    {batch.items.length} {batch.items.length === 1 ? "property" : "properties"} ·{" "}
                    {new Date(request.created_at).toLocaleString("en-CA")}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <a
                    href={`https://mail.google.com/mail/u/0/#search/${encodeURIComponent(`subject:"${request.email_subject}"`)}`}
                    target="_blank"
                    rel="noreferrer"
                    className="rounded-md border border-[var(--ch-border)] px-3 py-2 text-xs font-semibold"
                  >
                    View in Gmail
                  </a>
                  <select
                    value={request.status}
                    disabled={busyBatch === batch.batchId}
                    onChange={(event) => updateStatus(batch, event.target.value)}
                    className="rounded-md border border-[var(--ch-border)] bg-[var(--ch-surface)] px-3 py-2 text-xs font-semibold"
                  >
                    {statuses.map((status) => (
                      <option key={status} value={status}>{status.replaceAll("_", " ")}</option>
                    ))}
                  </select>
                </div>
              </div>
              <ul className="mt-3 grid gap-1 text-xs text-[var(--ch-text-secondary)] sm:grid-cols-2">
                {batch.items.map((item) => (
                  <li key={item.id}>
                    {item.property_address || "Property"} · {item.stage || "No stage"} · {money.format(Number(item.amount))}
                  </li>
                ))}
              </ul>
              <p className="mt-3 truncate text-xs text-[var(--ch-text-muted)]">{request.email_subject}</p>
            </article>
          );
        })}
        {!batches.length && !error ? (
          <p className="rounded-md bg-[var(--ch-surface-muted)] px-3 py-4 text-sm text-[var(--ch-text-muted)]">
            No PRO draw requests have been saved yet.
          </p>
        ) : null}
      </div>
    </section>
  );
}
