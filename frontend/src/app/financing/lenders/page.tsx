"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { Plus, Search, Users } from "lucide-react";

import { createLender, getLenders } from "@/lib/api/lenders";
import type { LenderListItem, LenderPayload } from "@/types/lenders";
import { LenderForm } from "./LenderForm";


export default function LendersPage() {
  const [lenders, setLenders] = useState<LenderListItem[]>([]);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    let active = true;
    getLenders()
      .then((result) => {
        if (active) setLenders(result);
      })
      .catch((loadError) => {
        if (active) setError(loadError instanceof Error ? loadError.message : "Could not load lenders.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  const filtered = useMemo(() => {
    const query = search.trim().toLowerCase();
    return query
      ? lenders.filter((lender) => lender.name.toLowerCase().includes(query))
      : lenders;
  }, [lenders, search]);

  async function create(payload: LenderPayload) {
    const lender = await createLender(payload);
    setLenders((current) => [...current, lender].sort((a, b) => a.name.localeCompare(b.name)));
    setCreating(false);
  }

  return (
    <main className="min-h-screen bg-[var(--ch-page-bg)] px-6 py-8 text-[var(--ch-text-primary)] lg:px-10">
      <div className="mx-auto max-w-6xl space-y-6">
        <header className="flex flex-col gap-4 border-b border-[var(--ch-border)] pb-6 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-[var(--ch-text-muted)]">Financing</p>
            <h1 className="mt-1 text-3xl font-semibold tracking-tight">Lenders</h1>
            <p className="mt-2 text-sm text-[var(--ch-text-muted)]">Manage lender contacts and review linked facilities.</p>
          </div>
          <button
            type="button"
            onClick={() => setCreating(true)}
            className="inline-flex items-center justify-center gap-2 rounded-lg bg-[var(--ch-accent)] px-4 py-2.5 text-sm font-semibold text-[var(--ch-accent-text)]"
          >
            <Plus className="h-4 w-4" aria-hidden="true" />
            New lender
          </button>
        </header>

        {creating ? (
          <section className="rounded-xl border border-[var(--ch-border)] bg-[var(--ch-surface)] p-5">
            <h2 className="mb-4 text-lg font-semibold">Create lender</h2>
            <LenderForm submitLabel="Create lender" onSubmit={create} onCancel={() => setCreating(false)} />
          </section>
        ) : null}

        <section className="rounded-xl border border-[var(--ch-border)] bg-[var(--ch-surface)]">
          <div className="border-b border-[var(--ch-border)] p-4">
            <label className="relative block max-w-md">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--ch-text-muted)]" aria-hidden="true" />
              <span className="sr-only">Search lenders by name</span>
              <input
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Search lenders by name"
                className="w-full rounded-lg border border-[var(--ch-border)] bg-[var(--ch-page-bg)] py-2.5 pl-9 pr-3 text-sm outline-none focus:border-[var(--ch-accent)] focus:ring-2 focus:ring-[var(--ch-focus-ring)]"
              />
            </label>
          </div>

          {error ? (
            <p className="m-4 rounded-lg border border-[var(--ch-error-border)] bg-[var(--ch-error-bg)] px-3 py-2 text-sm text-[var(--ch-error-text)]">{error}</p>
          ) : loading ? (
            <LenderTableSkeleton />
          ) : filtered.length === 0 ? (
            <div className="grid place-items-center gap-2 px-6 py-14 text-center">
              <Users className="h-8 w-8 text-[var(--ch-text-muted)]" aria-hidden="true" />
              <p className="font-medium">{search ? "No lenders match your search." : "No lenders have been created yet."}</p>
              <p className="text-sm text-[var(--ch-text-muted)]">Create a lender to keep reusable contact information in one place.</p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[760px] text-left text-sm">
                <thead className="bg-[var(--ch-surface-muted)] text-xs uppercase tracking-wide text-[var(--ch-text-muted)]">
                  <tr>
                    <th className="px-4 py-3 font-semibold">Name</th>
                    <th className="px-4 py-3 font-semibold">Contact</th>
                    <th className="px-4 py-3 font-semibold">Email / phone</th>
                    <th className="px-4 py-3 text-right font-semibold">Active facilities</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[var(--ch-border)]">
                  {filtered.map((lender) => (
                    <tr key={lender.id} className="hover:bg-[var(--ch-surface-muted)]">
                      <td className="px-4 py-3 font-semibold">
                        <Link href={`/financing/lenders/${lender.id}`} className="text-[var(--ch-accent)] hover:underline">
                          {lender.name}
                        </Link>
                      </td>
                      <td className="px-4 py-3 text-[var(--ch-text-secondary)]">{lender.contact_name || "No contact assigned"}</td>
                      <td className="px-4 py-3 text-[var(--ch-text-secondary)]">
                        <div>{lender.contact_email || "No email"}</div>
                        <div className="text-xs text-[var(--ch-text-muted)]">{lender.contact_phone || "No phone"}</div>
                      </td>
                      <td className="px-4 py-3 text-right font-semibold">{lender.active_facility_count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </div>
    </main>
  );
}

function LenderTableSkeleton() {
  return (
    <div className="space-y-3 p-4" aria-label="Loading lenders">
      {[0, 1, 2].map((row) => (
        <div key={row} className="h-12 animate-pulse rounded-lg bg-[var(--ch-surface-muted)]" />
      ))}
    </div>
  );
}
