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
  possession: "bg-amber-500/15 text-amber-300 border-amber-500/30",
  complete: "bg-emerald-500/15 text-emerald-300 border-emerald-500/30",
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
      className={`w-full text-left px-4 py-3 border-b border-white/5 transition-all duration-150
        ${selected
          ? "bg-white/10 border-l-2 border-l-amber-400"
          : "hover:bg-white/5 border-l-2 border-l-transparent"
        }`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-sm font-medium text-white truncate">{lot.address}</p>
          {lot.buyer_name && (
            <p className="text-xs text-white/50 truncate mt-0.5">{lot.buyer_name}</p>
          )}
        </div>
        <span className={`shrink-0 text-[10px] font-semibold px-2 py-0.5 rounded-full border ${STATUS_COLOR[lot.status]}`}>
          {STATUS_LABEL[lot.status]}
        </span>
      </div>
      {lot.possession_date && (
        <p className={`text-xs mt-1.5 ${days !== null && days <= 30 ? "text-amber-400" : "text-white/40"}`}>
          Possession {formatDate(lot.possession_date)}
          {days !== null && days > 0 && ` · ${days}d`}
          {days !== null && days <= 0 && " · Past due"}
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
            <span className="text-xs font-mono text-white/40 bg-white/5 px-2 py-0.5 rounded">
              Lot {lot.lot_number}
            </span>
          )}
          <span className={`text-xs font-semibold px-2.5 py-0.5 rounded-full border ${STATUS_COLOR[lot.status]}`}>
            {STATUS_LABEL[lot.status]}
          </span>
        </div>
        <h1 className="text-2xl font-semibold text-white tracking-tight">{lot.address}</h1>
        {lot.buyer_name && (
          <p className="text-white/50 mt-1">{lot.buyer_name}</p>
        )}
        <p className="text-sm text-white/30 mt-1">{lot.community}</p>
      </div>

      {/* Key Dates */}
      <div className="mb-8">
        <h2 className="text-xs font-semibold text-white/30 uppercase tracking-widest mb-3">Key Dates</h2>
        <div className="grid grid-cols-3 gap-3">
          {dates.map(({ label, value }) => {
            const days = daysUntil(value);
            const urgent = days !== null && days <= 14 && days >= 0;
            return (
              <div
                key={label}
                className={`rounded-xl p-4 border ${
                  urgent
                    ? "bg-amber-500/10 border-amber-500/30"
                    : "bg-white/5 border-white/10"
                }`}
              >
                <p className="text-xs text-white/40 mb-1">{label}</p>
                <p className={`text-sm font-medium ${urgent ? "text-amber-300" : "text-white"}`}>
                  {formatDate(value)}
                </p>
                {days !== null && days >= 0 && (
                  <p className="text-xs text-white/30 mt-0.5">{days}d away</p>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* Actions */}
      <div className="mb-8">
        <h2 className="text-xs font-semibold text-white/30 uppercase tracking-widest mb-3">Quick Actions</h2>
        <div className="grid grid-cols-2 gap-3">
          <Link
            href={`/lots/${lot.id}/costbook`}
            className="flex items-center gap-3 rounded-xl p-4 bg-white/5 border border-white/10 hover:bg-white/10 hover:border-white/20 transition-all group"
          >
            <span className="text-xl">📒</span>
            <div>
              <p className="text-sm font-medium text-white group-hover:text-amber-300 transition-colors">Costbook</p>
              <p className="text-xs text-white/40">Budget & POs</p>
            </div>
          </Link>
          <Link
            href={`/lots/${lot.id}/costbook?tab=invoices`}
            className="flex items-center gap-3 rounded-xl p-4 bg-white/5 border border-white/10 hover:bg-white/10 hover:border-white/20 transition-all group"
          >
            <span className="text-xl">🧾</span>
            <div>
              <p className="text-sm font-medium text-white group-hover:text-amber-300 transition-colors">Invoices</p>
              <p className="text-xs text-white/40">Review & approve</p>
            </div>
          </Link>
        </div>
      </div>

      {/* Agreement IDs for debugging */}
      <div className="rounded-xl bg-white/3 border border-white/5 p-4">
        <h2 className="text-xs font-semibold text-white/20 uppercase tracking-widest mb-2">Agreement IDs</h2>
        <div className="space-y-1">
          {lot.land_agreement_id && (
            <p className="text-xs font-mono text-white/30">Land: {lot.land_agreement_id}</p>
          )}
          {lot.sale_agreement_id && (
            <p className="text-xs font-mono text-white/30">Sale: {lot.sale_agreement_id}</p>
          )}
        </div>
      </div>
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function LotsPage() {
  const [lots, setLots] = useState<Lot[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<Lot | null>(null);
  const [sortKey, setSortKey] = useState<SortKey>("community");
  const [search, setSearch] = useState("");

  useEffect(() => {
    getLots()
      .then((data) => {
        setLots(data);
        if (data.length > 0) setSelected(data[0]);
      })
      .finally(() => setLoading(false));
  }, []);

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
    <div className="flex h-screen bg-[#0f1117] text-white overflow-hidden">
      {/* Left panel */}
      <div className="w-80 shrink-0 flex flex-col border-r border-white/10">
        {/* Panel header */}
        <div className="p-4 border-b border-white/10">
          <h1 className="text-base font-semibold text-white mb-3">Lots</h1>

          {/* Search */}
          <input
            type="text"
            placeholder="Search address, buyer…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm text-white placeholder-white/30 focus:outline-none focus:border-amber-400/50 mb-3"
          />

          {/* Sort toggles */}
          <div className="flex gap-1">
            {(["community", "status", "possession_date"] as SortKey[]).map((key) => (
              <button
                key={key}
                onClick={() => setSortKey(key)}
                className={`flex-1 text-[10px] font-medium py-1.5 rounded-md transition-all ${
                  sortKey === key
                    ? "bg-amber-400/20 text-amber-300 border border-amber-400/30"
                    : "bg-white/5 text-white/40 border border-transparent hover:text-white/60"
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
            <div className="p-8 text-center text-white/30 text-sm">Loading lots…</div>
          ) : Object.keys(grouped).length === 0 ? (
            <div className="p-8 text-center text-white/30 text-sm">No lots found</div>
          ) : (
            Object.entries(grouped).map(([group, groupLots]) => (
              <div key={group}>
                <div className="px-4 py-2 text-[10px] font-semibold text-white/30 uppercase tracking-widest bg-white/2 border-b border-white/5 sticky top-0">
                  {group}
                  <span className="ml-2 text-white/20">{groupLots.length}</span>
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
          <div className="h-full flex items-center justify-center text-white/20 text-sm">
            Select a lot to view details
          </div>
        )}
      </div>
    </div>
  );
}
