"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";

import {
  createPurchaseOrder,
  getBudget,
  getVendors,
  updateBudgetLine,
  type Budget,
  type BudgetLine,
  type PurchaseOrder,
  type Vendor,
} from "@/lib/api/costbook";

function fmt(value?: number | null) {
  if (value == null) return "-";
  return new Intl.NumberFormat("en-CA", {
    style: "currency",
    currency: "CAD",
    maximumFractionDigits: 0,
  }).format(value);
}

export default function BudgetDraftPage() {
  const params = useParams<{ budgetId: string }>();
  const [budget, setBudget] = useState<Budget | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editingCell, setEditingCell] = useState<{ lineId: string; field: "estimate" | "actual" } | null>(null);
  const [editValue, setEditValue] = useState("");
  const [issuePOLine, setIssuePOLine] = useState<BudgetLine | null>(null);

  useEffect(() => {
    let cancelled = false;
    getBudget(params.budgetId)
      .then((loadedBudget) => {
        if (!cancelled) {
          setBudget(loadedBudget);
          setError(null);
        }
      })
      .catch((loadError) => {
        if (!cancelled) setError(loadError instanceof Error ? loadError.message : "Could not load budget.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [params.budgetId]);

  const sections = useMemo(() => {
    return (budget?.lines || []).reduce<Record<string, BudgetLine[]>>((acc, line) => {
      (acc[line.section] = acc[line.section] || []).push(line);
      return acc;
    }, {});
  }, [budget?.lines]);

  function startEdit(line: BudgetLine, field: "estimate" | "actual") {
    setEditingCell({ lineId: line.id, field });
    setEditValue(String(line[field] || 0));
  }

  async function commitEdit(line: BudgetLine, field: "estimate" | "actual") {
    if (!budget) return;
    const value = Number.parseFloat(editValue);
    setEditingCell(null);
    if (Number.isNaN(value)) return;

    const updatedLine = await updateBudgetLine(budget.id, line.id, { [field]: value });
    setBudget((current) => {
      if (!current) return current;
      const nextLines = current.lines.map((item) => (item.id === updatedLine.id ? updatedLine : item));
      const totalEstimate = nextLines.reduce((sum, item) => sum + item.estimate, 0);
      const totalActual = nextLines.reduce((sum, item) => sum + item.actual, 0);
      return {
        ...current,
        lines: nextLines,
        total_estimate: totalEstimate,
        total_actual: totalActual,
        total_variance: totalActual - totalEstimate,
      };
    });
  }

  function handlePOCreated(po: PurchaseOrder) {
    setBudget((current) => {
      if (!current) return current;
      const nextLines = current.lines.map((line) =>
        line.id === po.budget_line_id
          ? { ...line, estimate: (line.estimate || 0) + po.amount, origin_of_number: "PO total" }
          : line
      );
      const totalEstimate = nextLines.reduce((sum, item) => sum + item.estimate, 0);
      const totalActual = nextLines.reduce((sum, item) => sum + item.actual, 0);
      return {
        ...current,
        lines: nextLines,
        total_estimate: totalEstimate,
        total_actual: totalActual,
        total_variance: totalActual - totalEstimate,
      };
    });
  }

  if (loading) {
    return <div className="min-h-screen bg-[#0f1117] px-8 py-8 text-sm text-white/40">Loading budget...</div>;
  }

  if (error || !budget) {
    return (
      <div className="min-h-screen bg-[#0f1117] px-8 py-8 text-white">
        <Link href="/costbook" className="text-sm text-[#FAC775] hover:underline">
          Back to Costbook
        </Link>
        <p className="mt-8 rounded-xl border border-red-400/30 bg-red-500/10 p-4 text-sm text-red-200">
          {error || "Budget not found."}
        </p>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#0f1117] px-8 py-8 text-white">
      <div className="mx-auto max-w-6xl">
        <header className="mb-8 flex flex-wrap items-start justify-between gap-4">
          <div>
            <Link href="/costbook" className="text-sm text-white/40 transition-colors hover:text-white">
              Back to Costbook
            </Link>
            <h1 className="mt-4 text-2xl font-semibold tracking-tight">{budget.label}</h1>
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <span className="rounded-full bg-white/10 px-2.5 py-1 text-xs font-semibold uppercase tracking-widest text-white/60">
                {budget.status}
              </span>
              <span className="rounded-full border border-[#FAC775]/30 bg-[#FAC775]/10 px-2.5 py-1 text-xs font-semibold uppercase tracking-widest text-[#FAC775]">
                Draft budget
              </span>
            </div>
          </div>
        </header>

        <section className="mb-6 grid gap-4 md:grid-cols-3">
          {[
            { label: "Total Estimate", value: budget.total_estimate, color: "text-white" },
            { label: "Total Actual", value: budget.total_actual, color: "text-white" },
            {
              label: "Variance",
              value: budget.total_variance,
              color: budget.total_variance > 0 ? "text-red-400" : budget.total_variance < 0 ? "text-emerald-400" : "text-white",
            },
          ].map((item) => (
            <div key={item.label} className="rounded-xl border border-white/10 bg-white/[0.04] p-4">
              <p className="mb-1 text-xs text-white/40">{item.label}</p>
              <p className={`text-xl font-semibold ${item.color}`}>{fmt(item.value)}</p>
            </div>
          ))}
        </section>

        <section className="overflow-hidden rounded-xl border border-white/10 bg-white/[0.03]">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-white/10 bg-white/[0.04] text-xs uppercase tracking-widest text-white/40">
                <th className="w-20 px-4 py-3 text-left">PO #</th>
                <th className="px-4 py-3 text-left">Description</th>
                <th className="w-36 px-4 py-3 text-right">Estimate</th>
                <th className="w-36 px-4 py-3 text-right">Actual</th>
                <th className="w-36 px-4 py-3 text-right">Variance</th>
                <th className="w-12 px-4 py-3"></th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(sections).map(([section, lines]) => (
                <FragmentRows
                  key={section}
                  section={section}
                  lines={lines}
                  editingCell={editingCell}
                  editValue={editValue}
                  setEditValue={setEditValue}
                  startEdit={startEdit}
                  commitEdit={commitEdit}
                  onIssuePO={(line) => setIssuePOLine(line)}
                />
              ))}
            </tbody>
          </table>
        </section>
      </div>
      {issuePOLine && (
        <IssuePODrawer
          line={issuePOLine}
          budgetId={budget.id}
          onClose={() => setIssuePOLine(null)}
          onCreated={handlePOCreated}
        />
      )}
    </div>
  );
}

function FragmentRows({
  section,
  lines,
  editingCell,
  editValue,
  setEditValue,
  startEdit,
  commitEdit,
  onIssuePO,
}: {
  section: string;
  lines: BudgetLine[];
  editingCell: { lineId: string; field: "estimate" | "actual" } | null;
  editValue: string;
  setEditValue: (value: string) => void;
  startEdit: (line: BudgetLine, field: "estimate" | "actual") => void;
  commitEdit: (line: BudgetLine, field: "estimate" | "actual") => void;
  onIssuePO: (line: BudgetLine) => void;
}) {
  return (
    <>
      <tr className="border-t border-white/10 bg-white/[0.03]">
        <td colSpan={6} className="px-4 py-2 text-[10px] font-bold uppercase tracking-widest text-white/30">
          {section}
        </td>
      </tr>
      {lines.map((line) => {
        const variance = line.actual - line.estimate;
        const isOver = variance > 0 && line.actual > 0;
        const isUnder = variance < 0 && line.actual > 0;

        return (
          <tr key={line.id} className="border-t border-white/5 hover:bg-white/[0.03]">
            <td className="px-4 py-2.5 font-mono text-xs text-white/40">{line.po_number}</td>
            <td className="px-4 py-2.5 text-white/80">{line.description}</td>
            {(["estimate", "actual"] as const).map((field) => (
              <td key={field} className="px-4 py-2.5 text-right">
                {editingCell?.lineId === line.id && editingCell.field === field ? (
                  <input
                    autoFocus
                    type="text"
                    inputMode="decimal"
                    value={editValue}
                    onChange={(event) => setEditValue(event.target.value)}
                    onBlur={() => commitEdit(line, field)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") commitEdit(line, field);
                    }}
                    className="w-full rounded border border-[#FAC775]/50 bg-white/10 px-2 py-1 text-right text-white outline-none"
                  />
                ) : (
                  <button
                    type="button"
                    onClick={() => startEdit(line, field)}
                    className="text-right text-white/70 transition-colors hover:text-[#FAC775]"
                  >
                    {line[field] > 0 ? fmt(line[field]) : <span className="text-white/20">-</span>}
                  </button>
                )}
              </td>
            ))}
            <td className={`px-4 py-2.5 text-right font-medium ${isOver ? "text-red-400" : isUnder ? "text-emerald-400" : "text-white/20"}`}>
              {line.actual > 0 ? fmt(variance) : "-"}
            </td>
            <td className="px-4 py-2.5 text-center">
              <button
                type="button"
                onClick={() => onIssuePO(line)}
                className="rounded border border-[#FAC775]/30 px-2 py-1 text-xs font-semibold text-[#FAC775] opacity-70 transition hover:bg-[#FAC775]/10 hover:opacity-100"
              >
                PO+
              </button>
            </td>
          </tr>
        );
      })}
    </>
  );
}

function IssuePODrawer({
  line,
  budgetId,
  onClose,
  onCreated,
}: {
  line: BudgetLine;
  budgetId: string;
  onClose: () => void;
  onCreated: (po: PurchaseOrder) => void;
}) {
  const [vendors, setVendors] = useState<Vendor[]>([]);
  const [vendorId, setVendorId] = useState("");
  const [vendorName, setVendorName] = useState("");
  const [description, setDescription] = useState(line.description);
  const [amount, setAmount] = useState(String(line.estimate || ""));
  const [notes, setNotes] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    getVendors().then(setVendors).catch(() => setVendors([]));
  }, []);

  async function submit() {
    if (!vendorId && !vendorName.trim()) {
      alert("Enter a vendor.");
      return;
    }
    if (!amount || Number.isNaN(Number.parseFloat(amount))) {
      alert("Enter a valid amount.");
      return;
    }

    setSaving(true);
    try {
      const po = await createPurchaseOrder(budgetId, {
        budget_line_id: line.id,
        vendor_id: vendorId || undefined,
        vendor_name_adhoc: vendorId ? undefined : vendorName,
        description,
        amount: Number.parseFloat(amount),
        notes: notes || undefined,
      });
      onCreated(po);
      onClose();
    } catch (createError) {
      alert(createError instanceof Error ? createError.message : "Failed to issue purchase order.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} />
      <div className="relative flex h-full w-full max-w-md flex-col gap-5 overflow-y-auto border-l border-white/10 bg-[#161921] p-6">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-base font-semibold text-white">Issue Purchase Order</h2>
            <p className="mt-0.5 font-mono text-xs text-white/40">
              {line.po_number} - {line.description}
            </p>
          </div>
          <button type="button" onClick={onClose} className="text-xl text-white/30 hover:text-white">
            x
          </button>
        </div>

        <div className="space-y-4">
          <div>
            <label className="mb-1.5 block text-xs text-white/40">Vendor</label>
            <select
              value={vendorId}
              onChange={(event) => {
                setVendorId(event.target.value);
                if (event.target.value) setVendorName("");
              }}
              className="mb-2 w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm text-white focus:border-[#FAC775]/50 focus:outline-none"
            >
              <option value="">Type a new vendor name below...</option>
              {vendors.map((vendor) => (
                <option key={vendor.id} value={vendor.id}>
                  {vendor.name}
                </option>
              ))}
            </select>
            {!vendorId && (
              <input
                type="text"
                placeholder="New vendor name"
                value={vendorName}
                onChange={(event) => setVendorName(event.target.value)}
                className="w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm text-white placeholder-white/30 focus:border-[#FAC775]/50 focus:outline-none"
              />
            )}
          </div>

          <div>
            <label className="mb-1.5 block text-xs text-white/40">Description</label>
            <input
              type="text"
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              className="w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm text-white focus:border-[#FAC775]/50 focus:outline-none"
            />
          </div>

          <div>
            <label className="mb-1.5 block text-xs text-white/40">Amount (CAD)</label>
            <input
              type="text"
              inputMode="decimal"
              value={amount}
              onChange={(event) => setAmount(event.target.value)}
              className="w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm text-white focus:border-[#FAC775]/50 focus:outline-none"
            />
          </div>

          <div>
            <label className="mb-1.5 block text-xs text-white/40">Notes (optional)</label>
            <textarea
              value={notes}
              onChange={(event) => setNotes(event.target.value)}
              rows={3}
              className="w-full resize-none rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm text-white placeholder-white/30 focus:border-[#FAC775]/50 focus:outline-none"
            />
          </div>
        </div>

        <div className="mt-auto flex gap-3 border-t border-white/10 pt-4">
          <button
            type="button"
            onClick={submit}
            disabled={saving}
            className="flex-1 rounded-lg border border-[#FAC775]/30 bg-[#FAC775]/20 py-2.5 text-sm font-medium text-[#FAC775] transition-colors hover:bg-[#FAC775]/30 disabled:opacity-40"
          >
            {saving ? "Issuing..." : "Issue PO"}
          </button>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg bg-white/5 px-4 py-2.5 text-sm text-white/40 transition-colors hover:bg-white/10"
          >
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}
