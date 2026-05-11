"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";

import { getChangeOrders, type ChangeOrder } from "@/lib/api/change-orders";

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

  return (
    <main className="min-h-screen bg-[#0f1117] text-white">
      <div className="mx-auto flex max-w-6xl flex-col gap-6 px-6 py-8 lg:px-10">
        <header className="flex flex-col gap-4 border-b border-white/10 pb-6 md:flex-row md:items-end md:justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.24em] text-white/35">
              Projects
            </p>
            <h1 className="mt-2 text-3xl font-semibold tracking-tight">Change Orders</h1>
            <p className="mt-2 text-sm text-white/50">
              Filter and review saved change order drafts across all projects.
            </p>
          </div>
          <Link
            href="/change-orders/new"
            className="rounded-lg bg-[#FAC775] px-4 py-2 text-sm font-bold text-[#0f1117] hover:brightness-105"
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
            className="w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2.5 text-sm text-white outline-none placeholder:text-white/30 focus:border-amber-400/50 sm:max-w-md"
          />
          <p className="text-sm text-white/40">
            {filtered.length} of {changeOrders.length} shown
          </p>
        </section>

        {error && (
          <section className="rounded-xl border border-red-400/30 bg-red-500/10 px-4 py-3 text-sm text-red-200">
            {error}
          </section>
        )}

        <section className="overflow-hidden rounded-xl border border-white/10 bg-white/5">
          {loading ? (
            <div className="p-8 text-center text-sm text-white/35">Loading change orders...</div>
          ) : filtered.length === 0 ? (
            <div className="p-8 text-center text-sm text-white/35">
              No change orders found.
            </div>
          ) : (
            <div className="divide-y divide-white/10">
              {filtered.map((order) => (
                <article
                  key={order.id}
                  className="grid gap-4 px-4 py-4 md:grid-cols-[1.2fr_1fr_160px_130px] md:items-center"
                >
                  <div className="min-w-0">
                    <p className="truncate text-sm font-semibold text-white">{order.address}</p>
                    <p className="mt-1 truncate text-xs text-white/45">{order.client_name}</p>
                  </div>
                  <div className="min-w-0">
                    <p className="truncate text-sm text-white/70">
                      {order.co_number || "Unnumbered"}
                    </p>
                    <p className="mt-1 truncate text-xs text-white/40">
                      {order.line_items.length} line item{order.line_items.length === 1 ? "" : "s"}
                    </p>
                  </div>
                  <div>
                    <p className="text-sm font-semibold text-white">{money(orderTotal(order))}</p>
                    <p className="mt-1 text-xs text-white/40">{formatDate(order.date)}</p>
                  </div>
                  <div className="flex items-center justify-start md:justify-end">
                    <span className="rounded-full border border-amber-400/30 bg-amber-400/15 px-2.5 py-1 text-xs font-semibold text-amber-300">
                      {order.status || "draft"}
                    </span>
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
