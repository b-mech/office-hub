"use client";

import { useEffect, useState } from "react";
import {
  createProDrawRequest,
  getProDrawRequests,
  updateProDrawRequest,
} from "@/lib/api/financing";
import type { FinancingProperty, ProDrawRequest } from "@/types/financing";

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

export function ProDrawRequestPanel({ property }: { property: FinancingProperty }) {
  const [requests, setRequests] = useState<ProDrawRequest[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    getProDrawRequests(property.property_id)
      .then((items) => {
        if (active) setRequests(items);
      })
      .catch((err) => {
        if (active) setError(err instanceof Error ? err.message : "Could not load requests");
      });
    return () => {
      active = false;
    };
  }, [property.property_id]);

  async function prepare() {
    setBusy(true);
    setError(null);
    try {
      const request = await createProDrawRequest(property.property_id, property.draw_eligible);
      setRequests((current) => [request, ...current]);
      const params = new URLSearchParams({
        view: "cm",
        fs: "1",
        to: request.initial_recipient,
        su: request.email_subject,
        body: request.email_body,
      });
      window.open(`https://mail.google.com/mail/?${params.toString()}`, "_blank", "noopener,noreferrer");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not prepare draw request");
    } finally {
      setBusy(false);
    }
  }

  async function changeStatus(request: ProDrawRequest, status: string) {
    const updated = await updateProDrawRequest(request.id, status);
    setRequests((current) => current.map((item) => (item.id === updated.id ? updated : item)));
  }

  return (
    <div className="mb-4 rounded-lg border border-[var(--ch-border)] bg-[var(--ch-surface)] p-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold">PRO Draw Requests</h3>
          <p className="mt-1 text-xs text-[var(--ch-text-muted)]">
            Email goes first to Nicholas; forward it to Robert at robert@connectionhomes.ca.
          </p>
        </div>
        <button
          type="button"
          disabled={busy || Number(property.draw_eligible || 0) <= 0}
          onClick={prepare}
          className="rounded-md bg-[var(--ch-accent)] px-3 py-2 text-sm font-semibold text-white disabled:opacity-50"
        >
          {busy ? "Preparing…" : `Request ${money.format(Number(property.draw_eligible || 0))}`}
        </button>
      </div>
      {error ? <p className="mt-3 text-sm text-[var(--ch-error-text)]">{error}</p> : null}
      <div className="mt-3 space-y-2">
        {requests.map((request) => (
          <div key={request.id} className="rounded-md bg-[var(--ch-surface-muted)] p-3">
            <div className="flex items-center justify-between gap-3">
              <div>
                <p className="text-sm font-semibold">{money.format(Number(request.amount))}</p>
                <p className="text-xs text-[var(--ch-text-muted)]">
                  {request.stage || "No stage"} · {new Date(request.created_at).toLocaleDateString("en-CA")}
                </p>
              </div>
              <select
                value={request.status}
                onChange={(event) => changeStatus(request, event.target.value)}
                className="rounded-md border border-[var(--ch-border)] bg-[var(--ch-surface)] px-2 py-1 text-xs"
              >
                {statuses.map((status) => (
                  <option key={status} value={status}>{status.replaceAll("_", " ")}</option>
                ))}
              </select>
            </div>
            <div className="mt-2 flex items-center justify-between gap-2">
              <p className="truncate text-xs text-[var(--ch-text-secondary)]">{request.email_subject}</p>
              <a
                href={`https://mail.google.com/mail/u/0/#search/${encodeURIComponent(`subject:"${request.email_subject}"`)}`}
                target="_blank"
                rel="noreferrer"
                className="shrink-0 text-xs font-semibold text-[var(--ch-accent)]"
              >
                View in Gmail
              </a>
            </div>
          </div>
        ))}
        {!requests.length ? <p className="text-xs text-[var(--ch-text-muted)]">No saved requests yet.</p> : null}
      </div>
    </div>
  );
}
