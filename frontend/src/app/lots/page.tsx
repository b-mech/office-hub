"use client";

import { useEffect, useState, useMemo } from "react";
import Link from "next/link";
import { getLots, type Lot } from "@/lib/api/costbook";

// ─── helpers ──────────────────────────────────────────────────────────────────

const STATUS_LABEL: Record<string, string> = {
  active: "Active",
  possession: "Possession",
  complete: "Complete",
};

const STATUS_COLOR: Record<string, string> = {
  active: "bg-blue-500/15 text-blue-300 border-blue-500/30",
  possession: "bg-[var(--ch-warning-bg)] text-[var(--ch-warning-text)] border-[var(--ch-warning-border)]",
  complete: "bg-[var(--ch-success-bg)] text-[var(--ch-success-text)] border-[var(--ch-success-border)]",
};

function formatDate(d?: string) {
  if (!d) return "—";
  return new Date(d).toLocaleDateString("en-CA", {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

function daysUntil(d?: string) {
  if (!d) return null;
  const diff = Math.ceil((new Date(d).getTime() - Date.now()) / 86400000);
  return diff;
}

const money = new Intl.NumberFormat("en-CA", {
  style: "currency",
  currency: "CAD",
  maximumFractionDigits: 0,
});

function formatMoney(value?: string | number | null) {
  if (value === null || value === undefined || value === "") return "—";
  const numeric = typeof value === "number" ? value : Number(value);
  return Number.isFinite(numeric) ? money.format(numeric) : "—";
}

function formatStage(stage?: string | null) {
  if (!stage || stage === "NA") return "No stage";
  return stage
    .toLowerCase()
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

type SortKey = "community" | "status" | "possession_date";

// ─── LotCard ─────────────────────────────────────────────────────────────────

function LotCard({
  lot,
  selected,
  onClick,
}: {
  lot: Lot;
  selected: boolean;
  onClick: () => void;
}) {
  const days = daysUntil(lot.possession_date);

  return (
    <button
      onClick={onClick}
      className={`w-full text-left px-4 py-3 border-b border-[var(--ch-border)] transition-all duration-150
        ${selected
          ? "bg-[var(--ch-surface)] border-l-2 border-l-amber-400"
          : "hover:bg-[var(--ch-surface)] border-l-2 border-l-transparent"
        }`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-sm font-medium text-[var(--ch-text-primary)] truncate">{lot.address}</p>
          {lot.buyer_name && (
            <p className="text-xs text-[var(--ch-text-muted)] truncate mt-0.5">{lot.buyer_name}</p>
          )}
        </div>
        <span className={`shrink-0 text-[10px] font-semibold px-2 py-0.5 rounded-full border ${STATUS_COLOR[lot.status]}`}>
          {STATUS_LABEL[lot.status]}
        </span>
      </div>
      {lot.possession_date && (
        <p className={`text-xs mt-1.5 ${days !== null && days <= 30 ? "text-[var(--ch-warning-text)]" : "text-[var(--ch-text-muted)]"}`}>
          Possession {formatDate(lot.possession_date)}
          {days !== null && days > 0 && ` · ${days}d`}
          {days !== null && days <= 0 && " · Past due"}
        </p>
      )}
      {(lot.lender_type || lot.construction_stage || lot.draw_available != null) && (
        <div className="mt-2 grid grid-cols-2 gap-2 text-xs">
          <div className="min-w-0 rounded-md bg-[var(--ch-page-bg)] px-2 py-1">
            <p className="text-[10px] uppercase tracking-wider text-[var(--ch-text-muted)]">Lender</p>
            <p className="truncate font-medium text-[var(--ch-text-secondary)]">{lot.lender_type || "—"}</p>
          </div>
          <div className="min-w-0 rounded-md bg-[var(--ch-page-bg)] px-2 py-1 text-right">
            <p className="text-[10px] uppercase tracking-wider text-[var(--ch-text-muted)]">Draw</p>
            <p className="truncate font-semibold text-[var(--ch-text-primary)]">{formatMoney(lot.draw_available)}</p>
          </div>
        </div>
      )}
      {lot.construction_stage && (
        <p className="mt-1.5 truncate text-xs text-[var(--ch-text-muted)]">
          {formatStage(lot.construction_stage)}
          {lot.construction_stage_updated_at && ` · Updated ${formatDate(lot.construction_stage_updated_at)}`}
        </p>
      )}
    </button>
  );
}

// ─── LotDetail ────────────────────────────────────────────────────────────────

function LotDetail({ lot }: { lot: Lot }) {
  const dates = [
    { label: "Agreement", value: lot.agreement_date },
    { label: "Conditions", value: lot.condition_removal_date },
    { label: "Possession", value: lot.possession_date },
  ];

  return (
    <div className="h-full overflow-y-auto p-8">
      {/* Header */}
      <div className="mb-8">
        <div className="flex items-center gap-3 mb-1">
          {lot.lot_number && (
            <span className="text-xs font-mono text-[var(--ch-text-muted)] bg-[var(--ch-surface)] px-2 py-0.5 rounded">
              Lot {lot.lot_number}
            </span>
          )}
          <span className={`text-xs font-semibold px-2.5 py-0.5 rounded-full border ${STATUS_COLOR[lot.status]}`}>
            {STATUS_LABEL[lot.status]}
          </span>
        </div>
        <h1 className="text-2xl font-semibold text-[var(--ch-text-primary)] tracking-tight">{lot.address}</h1>
        {lot.buyer_name && (
          <p className="text-[var(--ch-text-muted)] mt-1">{lot.buyer_name}</p>
        )}
        <p className="text-sm text-[var(--ch-text-muted)] mt-1">{lot.community}</p>
      </div>

      {/* Financing */}
      <div className="mb-8">
        <h2 className="text-xs font-semibold text-[var(--ch-text-muted)] uppercase tracking-widest mb-3">Financing & Construction</h2>
        <div className="grid grid-cols-2 gap-3">
          <div className="rounded-xl p-4 bg-[var(--ch-surface)] border border-[var(--ch-border)]">
            <p className="text-xs text-[var(--ch-text-muted)] mb-1">Lender</p>
            <p className="text-sm font-medium text-[var(--ch-text-primary)]">
              {lot.lender_name || lot.lender_type || "Not linked"}
            </p>
            {lot.lender_name && lot.lender_type && (
              <p className="text-xs text-[var(--ch-text-muted)] mt-0.5">{lot.lender_type}</p>
            )}
          </div>
          <div className="rounded-xl p-4 bg-[var(--ch-surface)] border border-[var(--ch-border)]">
            <p className="text-xs text-[var(--ch-text-muted)] mb-1">Available to Draw</p>
            <p className="text-sm font-semibold text-[var(--ch-accent)]">{formatMoney(lot.draw_available)}</p>
          </div>
          <div className="rounded-xl p-4 bg-[var(--ch-surface)] border border-[var(--ch-border)]">
            <p className="text-xs text-[var(--ch-text-muted)] mb-1">Construction Stage</p>
            <p className="text-sm font-medium text-[var(--ch-text-primary)]">{formatStage(lot.construction_stage)}</p>
          </div>
          <div className="rounded-xl p-4 bg-[var(--ch-surface)] border border-[var(--ch-border)]">
            <p className="text-xs text-[var(--ch-text-muted)] mb-1">Stage Updated</p>
            <p className="text-sm font-medium text-[var(--ch-text-primary)]">
              {formatDate(lot.construction_stage_updated_at || undefined)}
            </p>
          </div>
        </div>
      </div>

      {/* Key Dates */}
      <div className="mb-8">
        <h2 className="text-xs font-semibold text-[var(--ch-text-muted)] uppercase tracking-widest mb-3">Key Dates</h2>
        <div className="grid grid-cols-3 gap-3">
          {dates.map(({ label, value }) => {
            const days = daysUntil(value);
            const urgent = days !== null && days <= 14 && days >= 0;
            return (
              <div
                key={label}
                className={`rounded-xl p-4 border ${
                  urgent
                    ? "bg-[var(--ch-warning-bg)] border-[var(--ch-warning-border)]"
                    : "bg-[var(--ch-surface)] border-[var(--ch-border)]"
                }`}
              >
                <p className="text-xs text-[var(--ch-text-muted)] mb-1">{label}</p>
                <p className={`text-sm font-medium ${urgent ? "text-[var(--ch-warning-text)]" : "text-[var(--ch-text-primary)]"}`}>
                  {formatDate(value)}
                </p>
                {days !== null && days >= 0 && (
                  <p className="text-xs text-[var(--ch-text-muted)] mt-0.5">{days}d away</p>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* Actions */}
      <div className="mb-8">
        <h2 className="text-xs font-semibold text-[var(--ch-text-muted)] uppercase tracking-widest mb-3">Quick Actions</h2>
        <div className="grid grid-cols-2 gap-3">
          <Link
            href={`/lots/${lot.id}/costbook`}
            className="flex items-center gap-3 rounded-xl p-4 bg-[var(--ch-surface)] border border-[var(--ch-border)] hover:bg-[var(--ch-surface)] hover:border-[var(--ch-border-strong)] transition-all group"
          >
            <span className="text-xl">📒</span>
            <div>
              <p className="text-sm font-medium text-[var(--ch-text-primary)] group-hover:text-[var(--ch-warning-text)] transition-colors">Costbook</p>
              <p className="text-xs text-[var(--ch-text-muted)]">Budget & POs</p>
            </div>
          </Link>
          <Link
            href={`/lots/${lot.id}/costbook?tab=invoices`}
            className="flex items-center gap-3 rounded-xl p-4 bg-[var(--ch-surface)] border border-[var(--ch-border)] hover:bg-[var(--ch-surface)] hover:border-[var(--ch-border-strong)] transition-all group"
          >
            <span className="text-xl">🧾</span>
            <div>
              <p className="text-sm font-medium text-[var(--ch-text-primary)] group-hover:text-[var(--ch-warning-text)] transition-colors">Invoices</p>
              <p className="text-xs text-[var(--ch-text-muted)]">Review & approve</p>
            </div>
          </Link>
        </div>
      </div>

      {/* Agreement IDs for debugging */}
      <div className="rounded-xl bg-[var(--ch-surface)] border border-[var(--ch-border)] p-4">
        <h2 className="text-xs font-semibold text-[var(--ch-text-muted)] uppercase tracking-widest mb-2">Agreement IDs</h2>
        <div className="space-y-1">
          {lot.land_agreement_id && (
            <p className="text-xs font-mono text-[var(--ch-text-muted)]">Land: {lot.land_agreement_id}</p>
          )}
          {lot.sale_agreement_id && (
            <p className="text-xs font-mono text-[var(--ch-text-muted)]">Sale: {lot.sale_agreement_id}</p>
          )}
        </div>
      </div>
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export function LotWorkspace({
  title,
  loadingText,
  emptyText,
  loadLots,
}: {
  title: string;
  loadingText: string;
  emptyText: string;
  loadLots: () => Promise<Lot[]>;
}) {
  const [lots, setLots] = useState<Lot[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<Lot | null>(null);
  const [sortKey, setSortKey] = useState<SortKey>("community");
  const [search, setSearch] = useState("");

  useEffect(() => {
    loadLots()
      .then((data) => {
        setLots(data);
        if (data.length > 0) setSelected(data[0]);
      })
      .finally(() => setLoading(false));
  }, [loadLots]);

  const filtered = useMemo(() => {
    const q = search.toLowerCase();
    return lots.filter(
      (l) =>
        l.address.toLowerCase().includes(q) ||
        (l.buyer_name || "").toLowerCase().includes(q) ||
        l.community.toLowerCase().includes(q)
    );
  }, [lots, search]);

  const grouped = useMemo(() => {
    const sorted = [...filtered].sort((a, b) => {
      if (sortKey === "community") return a.community.localeCompare(b.community);
      if (sortKey === "status") return a.status.localeCompare(b.status);
      if (sortKey === "possession_date") {
        if (!a.possession_date) return 1;
        if (!b.possession_date) return -1;
        return new Date(a.possession_date).getTime() - new Date(b.possession_date).getTime();
      }
      return 0;
    });

    return sorted.reduce<Record<string, Lot[]>>((acc, lot) => {
      const key =
        sortKey === "community"
          ? lot.community
          : sortKey === "status"
          ? STATUS_LABEL[lot.status]
          : lot.possession_date
          ? new Date(lot.possession_date).toLocaleDateString("en-CA", { year: "numeric", month: "long" })
          : "No Date";
      (acc[key] = acc[key] || []).push(lot);
      return acc;
    }, {});
  }, [filtered, sortKey]);

  return (
    <div className="flex h-screen bg-[var(--ch-page-bg)] text-[var(--ch-text-primary)] overflow-hidden">
      {/* Left panel */}
      <div className="w-80 shrink-0 flex flex-col border-r border-[var(--ch-border)]">
        {/* Panel header */}
        <div className="p-4 border-b border-[var(--ch-border)]">
          <h1 className="text-base font-semibold text-[var(--ch-text-primary)] mb-3">{title}</h1>

          {/* Search */}
          <input
            type="text"
            placeholder="Search address, buyer…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full bg-[var(--ch-surface)] border border-[var(--ch-border)] rounded-lg px-3 py-2 text-sm text-[var(--ch-text-primary)] placeholder:text-[var(--ch-text-muted)] focus:outline-none focus:border-amber-400/50 mb-3"
          />

          {/* Sort toggles */}
          <div className="flex gap-1">
            {(["community", "status", "possession_date"] as SortKey[]).map((key) => (
              <button
                key={key}
                onClick={() => setSortKey(key)}
                className={`flex-1 text-[10px] font-medium py-1.5 rounded-md transition-all ${
                  sortKey === key
                    ? "bg-amber-400/20 text-[var(--ch-warning-text)] border border-[var(--ch-warning-border)]"
                    : "bg-[var(--ch-surface)] text-[var(--ch-text-muted)] border border-transparent hover:text-[var(--ch-text-secondary)]"
                }`}
              >
                {key === "community" ? "Community" : key === "status" ? "Status" : "Possession"}
              </button>
            ))}
          </div>
        </div>

        {/* List */}
        <div className="flex-1 overflow-y-auto">
          {loading ? (
            <div className="p-8 text-center text-[var(--ch-text-muted)] text-sm">{loadingText}</div>
          ) : Object.keys(grouped).length === 0 ? (
            <div className="p-8 text-center text-[var(--ch-text-muted)] text-sm">{emptyText}</div>
          ) : (
            Object.entries(grouped).map(([group, groupLots]) => (
              <div key={group}>
                <div className="px-4 py-2 text-[10px] font-semibold text-[var(--ch-text-muted)] uppercase tracking-widest bg-[var(--ch-surface)] border-b border-[var(--ch-border)] sticky top-0">
                  {group}
                  <span className="ml-2 text-[var(--ch-text-muted)]">{groupLots.length}</span>
                </div>
                {groupLots.map((lot) => (
                  <LotCard
                    key={lot.id}
                    lot={lot}
                    selected={selected?.id === lot.id}
                    onClick={() => setSelected(lot)}
                  />
                ))}
              </div>
            ))
          )}
        </div>
      </div>

      {/* Right panel */}
      <div className="flex-1 overflow-hidden">
        {selected ? (
          <LotDetail lot={selected} />
        ) : (
          <div className="h-full flex items-center justify-center text-[var(--ch-text-muted)] text-sm">
            Select a lot to view details
          </div>
        )}
      </div>
    </div>
  );
}

export default function LotsPage() {
  return (
    <LotWorkspace
      title="Lots"
      loadingText="Loading lots..."
      emptyText="No lots found"
      loadLots={getLots}
    />
  );
}
