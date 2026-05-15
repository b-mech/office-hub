"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";

import {
  downloadChangeOrderPdf,
  getChangeOrders,
  sendChangeOrderForSignature,
  type ChangeOrder,
} from "@/lib/api/change-orders";

function formatDate(value?: string) {
  if (!value) return "No date";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString("en-CA", {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

function money(value: number) {
  return new Intl.NumberFormat("en-CA", {
    style: "currency",
    currency: "CAD",
  }).format(value);
}

function orderTotal(order: ChangeOrder) {
  return order.line_items.reduce((sum, item) => {
    const amount = Math.abs(Number(item.amount) || 0);
    return sum + (item.is_credit ? -amount : amount);
  }, 0);
}

export default function ProjectChangeOrdersPage() {
  const [changeOrders, setChangeOrders] = useState<ChangeOrder[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const [busyOrderId, setBusyOrderId] = useState<string | null>(null);
  const [search, setSearch] = useState("");

  useEffect(() => {
    getChangeOrders()
      .then((result) => {
        setChangeOrders(result);
        setError(null);
      })
      .catch((loadError) => {
        setError(loadError instanceof Error ? loadError.message : "Could not load change orders.");
      })
      .finally(() => setLoading(false));
  }, []);

  const filtered = useMemo(() => {
    const query = search.trim().toLowerCase();
    if (!query) return changeOrders;

    return changeOrders.filter((order) => {
      const searchable = [
        order.address,
        order.client_name,
        order.co_number,
        order.payment_method,
        order.notes,
        ...order.line_items.map((item) => item.description),
      ].join(" ").toLowerCase();
      return searchable.includes(query);
    });
  }, [changeOrders, search]);

  async function handleDownloadPdf(order: ChangeOrder) {
    setBusyOrderId(order.id);
    setError(null);
    setActionMessage(null);
    try {
      const blob = await downloadChangeOrderPdf(order.id);
      const objectUrl = URL.createObjectURL(blob);
      window.open(objectUrl, "_blank", "noopener,noreferrer");
      window.setTimeout(() => URL.revokeObjectURL(objectUrl), 30000);
      setActionMessage(`PDF generated for ${order.address}.`);
    } catch (downloadError) {
      setError(downloadError instanceof Error ? downloadError.message : "Could not generate PDF.");
    } finally {
      setBusyOrderId(null);
    }
  }

  async function handleSendSignature(order: ChangeOrder) {
    setBusyOrderId(order.id);
    setError(null);
    setActionMessage(null);
    try {
      const result = await sendChangeOrderForSignature(order.id);
      setActionMessage(result.message || "Change order sent for signature.");
      setChangeOrders((current) =>
        current.map((item) =>
          item.id === order.id
            ? { ...item, status: result.status as ChangeOrder["status"] }
            : item,
        ),
      );
    } catch (sendError) {
      setError(sendError instanceof Error ? sendError.message : "Could not send for signature.");
    } finally {
      setBusyOrderId(null);
    }
  }

  return (
    <main className="min-h-screen bg-[var(--ch-page-bg)] text-[var(--ch-text-primary)]">
      <div className="mx-auto flex max-w-6xl flex-col gap-6 px-6 py-8 lg:px-10">
        <header className="flex flex-col gap-4 border-b border-[var(--ch-border)] pb-6 md:flex-row md:items-end md:justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.24em] text-[var(--ch-text-muted)]">
              Projects
            </p>
            <h1 className="mt-2 text-3xl font-semibold tracking-tight">Change Orders</h1>
            <p className="mt-2 text-sm text-[var(--ch-text-secondary)]">
              Filter and review saved change order drafts across all projects.
            </p>
          </div>
          <Link
            href="/change-orders/new"
            className="rounded-lg bg-[var(--ch-accent)] px-4 py-2 text-sm font-bold text-[var(--ch-accent-text)] hover:bg-[var(--ch-accent-hover)]"
          >
            New Change Order
          </Link>
        </header>

        <section className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <input
            type="search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Filter address, client, CO number, line item..."
            className="w-full rounded-lg border border-[var(--ch-border)] bg-[var(--ch-surface)] px-3 py-2.5 text-sm text-[var(--ch-text-primary)] outline-none placeholder:text-[var(--ch-text-muted)] focus:border-[var(--ch-accent)] focus:ring-2 focus:ring-[var(--ch-focus-ring)] sm:max-w-md"
          />
          <p className="text-sm text-[var(--ch-text-muted)]">
            {filtered.length} of {changeOrders.length} shown
          </p>
        </section>

        {error && (
          <section className="rounded-xl border border-[var(--ch-error-border)] bg-[var(--ch-error-bg)] px-4 py-3 text-sm text-[var(--ch-error-text)]">
            {error}
          </section>
        )}

        {actionMessage && (
          <section className="rounded-xl border border-[var(--ch-success-border)] bg-[var(--ch-success-bg)] px-4 py-3 text-sm text-[var(--ch-success-text)]">
            {actionMessage}
          </section>
        )}

        <section className="overflow-hidden rounded-xl border border-[var(--ch-border)] bg-[var(--ch-surface)]">
          {loading ? (
            <div className="p-8 text-center text-sm text-[var(--ch-text-muted)]">Loading change orders...</div>
          ) : filtered.length === 0 ? (
            <div className="p-8 text-center text-sm text-[var(--ch-text-muted)]">
              No change orders found.
            </div>
          ) : (
            <div className="divide-y divide-[var(--ch-border)]">
              {filtered.map((order) => (
                <article
                  key={order.id}
                  className="grid gap-4 px-4 py-4 transition hover:bg-[var(--ch-page-bg)] md:grid-cols-[1.2fr_1fr_150px_110px_220px] md:items-center"
                >
                  <div className="min-w-0">
                    <p className="truncate text-sm font-semibold text-[var(--ch-text-primary)]">{order.address}</p>
                    <p className="mt-1 truncate text-xs text-[var(--ch-text-secondary)]">{order.client_name}</p>
                  </div>
                  <div className="min-w-0">
                    <p className="truncate text-sm text-[var(--ch-text-secondary)]">
                      {order.co_number || "Unnumbered"}
                    </p>
                    <p className="mt-1 truncate text-xs text-[var(--ch-text-muted)]">
                      {order.line_items.length} line item{order.line_items.length === 1 ? "" : "s"}
                    </p>
                  </div>
                  <div>
                    <p className="text-sm font-semibold text-[var(--ch-text-primary)]">{money(orderTotal(order))}</p>
                    <p className="mt-1 text-xs text-[var(--ch-text-muted)]">{formatDate(order.date)}</p>
                  </div>
                  <div className="flex items-center justify-start md:justify-end">
                    <span className="rounded-full border border-[var(--ch-amber)] bg-[var(--ch-amber-bg)] px-2.5 py-1 text-xs font-semibold text-[var(--ch-amber-text)]">
                      {order.status || "draft"}
                    </span>
                  </div>
                  <div className="flex flex-wrap items-center gap-2 md:justify-end">
                    <button
                      type="button"
                      onClick={() => void handleDownloadPdf(order)}
                      disabled={busyOrderId === order.id}
                      className="rounded-lg border border-[var(--ch-border-strong)] bg-[var(--ch-surface)] px-3 py-2 text-xs font-semibold text-[var(--ch-text-secondary)] transition hover:bg-[var(--ch-page-bg)] disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      PDF
                    </button>
                    <button
                      type="button"
                      onClick={() => void handleSendSignature(order)}
                      disabled={busyOrderId === order.id}
                      className="rounded-lg bg-[var(--ch-accent)] px-3 py-2 text-xs font-bold text-[var(--ch-accent-text)] transition hover:bg-[var(--ch-accent-hover)] disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      {busyOrderId === order.id ? "Working..." : "Send for Signature"}
                    </button>
                  </div>
                </article>
              ))}
            </div>
          )}
        </section>
      </div>
    </main>
  );
}
