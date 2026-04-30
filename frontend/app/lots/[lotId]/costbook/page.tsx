"use client";

import { useEffect, useState, useMemo } from "react";
import { useParams, useSearchParams, useRouter } from "next/navigation";
import Link from "next/link";
import {
  getBudgets, createBudget, updateBudgetLine,
  getPurchaseOrders, createPurchaseOrder, updatePoStatus,
  getInvoices, ingestInvoice, approveInvoice, rejectInvoice,
  getVendors,
  type Budget, type BudgetLine, type PurchaseOrder, type Invoice, type Vendor,
} from "@/lib/api/costbook";

// ─── Helpers ──────────────────────────────────────────────────────────────────

function fmt(n?: number | null) {
  if (n == null) return "—";
  return new Intl.NumberFormat("en-CA", { style: "currency", currency: "CAD", maximumFractionDigits: 0 }).format(n);
}

function confidence(n?: number | null) {
  if (n == null) return "";
  if (n >= 0.9) return "text-emerald-400";
  if (n >= 0.7) return "text-amber-400";
  return "text-red-400";
}

const TAB_ITEMS = ["Budget", "Purchase Orders", "Invoices"] as const;
type Tab = (typeof TAB_ITEMS)[number];

// ─── Budget Tab ───────────────────────────────────────────────────────────────

function BudgetTab({
  budget,
  onLineUpdate,
  onIssuePO,
}: {
  budget: Budget;
  onLineUpdate: (lineId: string, field: "estimate" | "actual", value: number) => void;
  onIssuePO: (line: BudgetLine) => void;
}) {
  const [editingCell, setEditingCell] = useState<{ lineId: string; field: "estimate" | "actual" } | null>(null);
  const [editValue, setEditValue] = useState("");

  const sections = useMemo(() => {
    return budget.lines.reduce<Record<string, BudgetLine[]>>((acc, line) => {
      (acc[line.section] = acc[line.section] || []).push(line);
      return acc;
    }, {});
  }, [budget.lines]);

  function startEdit(line: BudgetLine, field: "estimate" | "actual") {
    setEditingCell({ lineId: line.id, field });
    setEditValue(String(line[field] || 0));
  }

  function commitEdit(line: BudgetLine, field: "estimate" | "actual") {
    const val = parseFloat(editValue);
    if (!isNaN(val)) onLineUpdate(line.id, field, val);
    setEditingCell(null);
  }

  return (
    <div>
      {/* Totals bar */}
      <div className="grid grid-cols-3 gap-4 mb-6">
        {[
          { label: "Total Estimate", value: budget.total_estimate, color: "text-white" },
          { label: "Total Actual", value: budget.total_actual, color: "text-white" },
          {
            label: "Variance",
            value: budget.total_variance,
            color: budget.total_variance > 0 ? "text-red-400" : budget.total_variance < 0 ? "text-emerald-400" : "text-white",
          },
        ].map(({ label, value, color }) => (
          <div key={label} className="bg-white/5 border border-white/10 rounded-xl p-4">
            <p className="text-xs text-white/40 mb-1">{label}</p>
            <p className={`text-xl font-semibold ${color}`}>{fmt(value)}</p>
          </div>
        ))}
      </div>

      {/* Table */}
      <div className="rounded-xl border border-white/10 overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-white/5 border-b border-white/10 text-xs text-white/40 uppercase tracking-widest">
              <th className="text-left px-4 py-3 w-16">PO #</th>
              <th className="text-left px-4 py-3">Description</th>
              <th className="text-right px-4 py-3 w-36">Estimate</th>
              <th className="text-right px-4 py-3 w-36">Actual</th>
              <th className="text-right px-4 py-3 w-36">Variance</th>
              <th className="px-4 py-3 w-10"></th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(sections).map(([section, lines]) => (
              <>
                <tr key={section} className="bg-white/3 border-t border-white/10">
                  <td colSpan={6} className="px-4 py-2 text-[10px] font-bold text-white/30 uppercase tracking-widest">
                    {section}
                  </td>
                </tr>
                {lines.map((line) => {
                  const variance = line.actual - line.estimate;
                  const isOver = variance > 0 && line.actual > 0;
                  const isUnder = variance < 0 && line.actual > 0;

                  return (
                    <tr key={line.id} className="border-t border-white/5 hover:bg-white/3 group">
                      <td className="px-4 py-2.5 font-mono text-xs text-white/40">{line.po_number}</td>
                      <td className="px-4 py-2.5 text-white/80">{line.description}</td>

                      {/* Estimate cell */}
                      <td className="px-4 py-2.5 text-right">
                        {editingCell?.lineId === line.id && editingCell.field === "estimate" ? (
                          <input
                            autoFocus
                            type="number"
                            value={editValue}
                            onChange={(e) => setEditValue(e.target.value)}
                            onBlur={() => commitEdit(line, "estimate")}
                            onKeyDown={(e) => e.key === "Enter" && commitEdit(line, "estimate")}
                            className="w-full text-right bg-white/10 border border-amber-400/50 rounded px-2 py-0.5 text-white focus:outline-none"
                          />
                        ) : (
                          <span
                            onClick={() => startEdit(line, "estimate")}
                            className="cursor-pointer hover:text-amber-300 transition-colors text-white/70"
                          >
                            {line.estimate > 0 ? fmt(line.estimate) : <span className="text-white/20">—</span>}
                          </span>
                        )}
                      </td>

                      {/* Actual cell */}
                      <td className="px-4 py-2.5 text-right">
                        {editingCell?.lineId === line.id && editingCell.field === "actual" ? (
                          <input
                            autoFocus
                            type="number"
                            value={editValue}
                            onChange={(e) => setEditValue(e.target.value)}
                            onBlur={() => commitEdit(line, "actual")}
                            onKeyDown={(e) => e.key === "Enter" && commitEdit(line, "actual")}
                            className="w-full text-right bg-white/10 border border-amber-400/50 rounded px-2 py-0.5 text-white focus:outline-none"
                          />
                        ) : (
                          <span
                            onClick={() => startEdit(line, "actual")}
                            className="cursor-pointer hover:text-amber-300 transition-colors text-white/70"
                          >
                            {line.actual > 0 ? fmt(line.actual) : <span className="text-white/20">—</span>}
                          </span>
                        )}
                      </td>

                      {/* Variance */}
                      <td className={`px-4 py-2.5 text-right font-medium ${isOver ? "text-red-400" : isUnder ? "text-emerald-400" : "text-white/20"}`}>
                        {line.actual > 0 ? fmt(variance) : "—"}
                      </td>

                      {/* Issue PO */}
                      <td className="px-4 py-2.5 text-center opacity-0 group-hover:opacity-100 transition-opacity">
                        <button
                          onClick={() => onIssuePO(line)}
                          title="Issue PO"
                          className="text-xs text-white/40 hover:text-amber-300 transition-colors"
                        >
                          PO+
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ─── PO Tab ───────────────────────────────────────────────────────────────────

const PO_STATUS_COLOR: Record<string, string> = {
  draft: "bg-white/10 text-white/50",
  issued: "bg-blue-500/15 text-blue-300",
  acknowledged: "bg-purple-500/15 text-purple-300",
  complete: "bg-emerald-500/15 text-emerald-300",
  cancelled: "bg-red-500/15 text-red-300",
};

function POTab({ budgetId }: { budgetId: string }) {
  const [pos, setPOs] = useState<PurchaseOrder[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getPurchaseOrders(budgetId).then(setPOs).finally(() => setLoading(false));
  }, [budgetId]);

  async function advance(po: PurchaseOrder) {
    const next: Record<string, PurchaseOrder["status"]> = {
      draft: "issued", issued: "acknowledged", acknowledged: "complete",
    };
    if (!next[po.status]) return;
    const updated = await updatePoStatus(po.id, next[po.status]);
    setPOs((prev) => prev.map((p) => (p.id === updated.id ? updated : p)));
  }

  if (loading) return <div className="text-white/30 text-sm py-8 text-center">Loading…</div>;
  if (pos.length === 0) return <div className="text-white/30 text-sm py-8 text-center">No purchase orders yet. Issue one from the Budget tab.</div>;

  return (
    <div className="rounded-xl border border-white/10 overflow-hidden">
      <table className="w-full text-sm">
        <thead>
          <tr className="bg-white/5 border-b border-white/10 text-xs text-white/40 uppercase tracking-widest">
            <th className="text-left px-4 py-3">PO #</th>
            <th className="text-left px-4 py-3">Vendor</th>
            <th className="text-left px-4 py-3">Description</th>
            <th className="text-right px-4 py-3">Amount</th>
            <th className="text-left px-4 py-3">Status</th>
            <th className="px-4 py-3"></th>
          </tr>
        </thead>
        <tbody>
          {pos.map((po) => (
            <tr key={po.id} className="border-t border-white/5 hover:bg-white/3">
              <td className="px-4 py-3 font-mono text-xs text-white/50">{po.po_number}</td>
              <td className="px-4 py-3 text-white/80">{po.vendor_name || po.vendor_name_adhoc || "—"}</td>
              <td className="px-4 py-3 text-white/60">{po.description}</td>
              <td className="px-4 py-3 text-right text-white/80">{fmt(po.amount)}</td>
              <td className="px-4 py-3">
                <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${PO_STATUS_COLOR[po.status]}`}>
                  {po.status}
                </span>
              </td>
              <td className="px-4 py-3 text-right">
                {["draft", "issued", "acknowledged"].includes(po.status) && (
                  <button
                    onClick={() => advance(po)}
                    className="text-xs text-white/40 hover:text-amber-300 transition-colors"
                  >
                    Advance →
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ─── Invoice Tab ──────────────────────────────────────────────────────────────

function InvoiceTab({ budgetId, budgetLines }: { budgetId: string; budgetLines: BudgetLine[] }) {
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [approvingId, setApprovingId] = useState<string | null>(null);
  const [selectedLineId, setSelectedLineId] = useState<string>("");

  useEffect(() => {
    getInvoices({ budget_id: budgetId }).then(setInvoices).finally(() => setLoading(false));
  }, [budgetId]);

  async function handleUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    try {
      const inv = await ingestInvoice(file, budgetId);
      setInvoices((prev) => [inv, ...prev]);
    } finally {
      setUploading(false);
      e.target.value = "";
    }
  }

  async function handleApprove(invoice: Invoice) {
    if (!selectedLineId) {
      alert("Select a budget line to post this invoice against.");
      return;
    }
    const updated = await approveInvoice(invoice.id, { budget_line_id: selectedLineId });
    setInvoices((prev) => prev.map((i) => (i.id === updated.id ? updated : i)));
    setApprovingId(null);
    setSelectedLineId("");
  }

  async function handleReject(invoice: Invoice) {
    const reason = prompt("Rejection reason:");
    if (!reason) return;
    const updated = await rejectInvoice(invoice.id, reason);
    setInvoices((prev) => prev.map((i) => (i.id === updated.id ? updated : i)));
  }

  return (
    <div>
      {/* Upload */}
      <div className="mb-6">
        <label className={`inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium cursor-pointer transition-all
          ${uploading
            ? "bg-white/10 text-white/40 cursor-not-allowed"
            : "bg-amber-400/20 text-amber-300 border border-amber-400/30 hover:bg-amber-400/30"
          }`}
        >
          {uploading ? "Extracting…" : "Upload Invoice"}
          <input type="file" accept=".pdf,.png,.jpg,.jpeg" className="hidden" onChange={handleUpload} disabled={uploading} />
        </label>
        <p className="text-xs text-white/30 mt-1.5">PDF or image — Claude extracts the details automatically</p>
      </div>

      {loading ? (
        <div className="text-white/30 text-sm py-8 text-center">Loading…</div>
      ) : invoices.length === 0 ? (
        <div className="text-white/30 text-sm py-8 text-center">No invoices yet.</div>
      ) : (
        <div className="space-y-3">
          {invoices.map((inv) => (
            <div key={inv.id} className="rounded-xl border border-white/10 bg-white/3 p-5">
              <div className="flex items-start justify-between gap-4 mb-3">
                <div>
                  <div className="flex items-center gap-2 mb-1">
                    <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${
                      inv.status === "approved" ? "bg-emerald-500/15 text-emerald-300"
                      : inv.status === "rejected" ? "bg-red-500/15 text-red-300"
                      : "bg-amber-500/15 text-amber-300"
                    }`}>
                      {inv.status.replace("_", " ")}
                    </span>
                    {inv.extraction_confidence != null && (
                      <span className={`text-xs ${confidence(inv.extraction_confidence)}`}>
                        {Math.round(inv.extraction_confidence * 100)}% confidence
                      </span>
                    )}
                  </div>
                  <p className="text-white font-medium">{inv.vendor_name || "Unknown Vendor"}</p>
                  {inv.invoice_number && <p className="text-xs text-white/40">#{inv.invoice_number}</p>}
                </div>
                <div className="text-right">
                  <p className="text-lg font-semibold text-white">{fmt(inv.amount_claimed)}</p>
                  {inv.invoice_date && <p className="text-xs text-white/40">{inv.invoice_date}</p>}
                </div>
              </div>

              {inv.suggested_po_number && (
                <p className="text-xs text-white/40 mb-3">
                  Suggested category: <span className="font-mono text-white/60">{inv.suggested_po_number}</span>
                </p>
              )}

              {inv.status === "pending_review" && (
                <div className="flex items-center gap-3 mt-3 pt-3 border-t border-white/10">
                  {approvingId === inv.id ? (
                    <>
                      <select
                        value={selectedLineId}
                        onChange={(e) => setSelectedLineId(e.target.value)}
                        className="flex-1 bg-white/10 border border-white/20 rounded-lg px-3 py-1.5 text-sm text-white focus:outline-none focus:border-amber-400/50"
                      >
                        <option value="">Select budget line…</option>
                        {budgetLines.map((l) => (
                          <option key={l.id} value={l.id}>
                            {l.po_number} — {l.description}
                          </option>
                        ))}
                      </select>
                      <button
                        onClick={() => handleApprove(inv)}
                        className="px-3 py-1.5 rounded-lg bg-emerald-500/20 text-emerald-300 text-sm hover:bg-emerald-500/30 transition-colors"
                      >
                        Confirm
                      </button>
                      <button
                        onClick={() => setApprovingId(null)}
                        className="px-3 py-1.5 rounded-lg bg-white/5 text-white/40 text-sm hover:bg-white/10 transition-colors"
                      >
                        Cancel
                      </button>
                    </>
                  ) : (
                    <>
                      <button
                        onClick={() => setApprovingId(inv.id)}
                        className="px-3 py-1.5 rounded-lg bg-emerald-500/20 text-emerald-300 text-sm hover:bg-emerald-500/30 transition-colors"
                      >
                        Approve
                      </button>
                      <button
                        onClick={() => handleReject(inv)}
                        className="px-3 py-1.5 rounded-lg bg-red-500/20 text-red-300 text-sm hover:bg-red-500/30 transition-colors"
                      >
                        Reject
                      </button>
                    </>
                  )}
                </div>
              )}

              {inv.status === "rejected" && inv.rejection_reason && (
                <p className="text-xs text-red-400/70 mt-2 pt-2 border-t border-white/10">{inv.rejection_reason}</p>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ─── Issue PO Drawer ──────────────────────────────────────────────────────────

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
    getVendors().then(setVendors);
  }, []);

  async function submit() {
    if (!vendorId && !vendorName.trim()) { alert("Enter a vendor."); return; }
    if (!amount || isNaN(parseFloat(amount))) { alert("Enter a valid amount."); return; }
    setSaving(true);
    try {
      const po = await createPurchaseOrder(budgetId, {
        budget_line_id: line.id,
        vendor_id: vendorId || undefined,
        vendor_name_adhoc: !vendorId ? vendorName : undefined,
        description,
        amount: parseFloat(amount),
        notes: notes || undefined,
      });
      onCreated(po);
      onClose();
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} />
      <div className="relative w-full max-w-md bg-[#161921] border-l border-white/10 h-full overflow-y-auto p-6 flex flex-col gap-5">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-base font-semibold text-white">Issue Purchase Order</h2>
            <p className="text-xs text-white/40 mt-0.5 font-mono">{line.po_number} — {line.description}</p>
          </div>
          <button onClick={onClose} className="text-white/30 hover:text-white text-xl">×</button>
        </div>

        <div className="space-y-4">
          <div>
            <label className="text-xs text-white/40 mb-1.5 block">Vendor</label>
            <select
              value={vendorId}
              onChange={(e) => { setVendorId(e.target.value); if (e.target.value) setVendorName(""); }}
              className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-amber-400/50 mb-2"
            >
              <option value="">Type a new vendor name below…</option>
              {vendors.map((v) => (
                <option key={v.id} value={v.id}>{v.name}</option>
              ))}
            </select>
            {!vendorId && (
              <input
                type="text"
                placeholder="New vendor name"
                value={vendorName}
                onChange={(e) => setVendorName(e.target.value)}
                className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm text-white placeholder-white/30 focus:outline-none focus:border-amber-400/50"
              />
            )}
          </div>

          <div>
            <label className="text-xs text-white/40 mb-1.5 block">Description</label>
            <input
              type="text"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-amber-400/50"
            />
          </div>

          <div>
            <label className="text-xs text-white/40 mb-1.5 block">Amount (CAD)</label>
            <input
              type="number"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-amber-400/50"
            />
          </div>

          <div>
            <label className="text-xs text-white/40 mb-1.5 block">Notes (optional)</label>
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              rows={3}
              className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm text-white placeholder-white/30 focus:outline-none focus:border-amber-400/50 resize-none"
            />
          </div>
        </div>

        <div className="flex gap-3 mt-auto pt-4 border-t border-white/10">
          <button
            onClick={submit}
            disabled={saving}
            className="flex-1 py-2.5 rounded-lg bg-amber-400/20 text-amber-300 border border-amber-400/30 text-sm font-medium hover:bg-amber-400/30 transition-colors disabled:opacity-40"
          >
            {saving ? "Issuing…" : "Issue PO"}
          </button>
          <button
            onClick={onClose}
            className="px-4 py-2.5 rounded-lg bg-white/5 text-white/40 text-sm hover:bg-white/10 transition-colors"
          >
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function CostbookPage() {
  const params = useParams();
  const searchParams = useSearchParams();
  const router = useRouter();
  const lotId = params?.lotId as string | undefined;

  const initialTab = (searchParams?.get("tab") === "invoices" ? "Invoices" : "Budget") as Tab;
  const [activeTab, setActiveTab] = useState<Tab>(initialTab);
  const [budget, setBudget] = useState<Budget | null>(null);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [issuePOLine, setIssuePOLine] = useState<BudgetLine | null>(null);

  useEffect(() => {
    getBudgets()
      .then((budgets) => {
        // Find budget for this lot or use first budget
        const match = lotId
          ? budgets.find((b) => b.lot_agreement_id === lotId) || budgets[0]
          : budgets[0];
        if (match) setBudget(match);
      })
      .finally(() => setLoading(false));
  }, [lotId]);

  async function handleCreate() {
    setCreating(true);
    try {
      const b = await createBudget({
        label: "New Budget",
        lot_agreement_id: lotId,
      });
      setBudget(b);
    } finally {
      setCreating(false);
    }
  }

  async function handleLineUpdate(lineId: string, field: "estimate" | "actual", value: number) {
    if (!budget) return;
    const updated = await updateBudgetLine(budget.id, lineId, { [field]: value });
    setBudget((prev) => {
      if (!prev) return prev;
      const lines = prev.lines.map((l) => (l.id === updated.id ? { ...l, [field]: value } : l));
      const total_estimate = lines.reduce((s, l) => s + (l.estimate || 0), 0);
      const total_actual = lines.reduce((s, l) => s + (l.actual || 0), 0);
      return { ...prev, lines, total_estimate, total_actual, total_variance: total_actual - total_estimate };
    });
  }

  return (
    <div className="min-h-screen bg-[#0f1117] text-white">
      {/* Top bar */}
      <div className="border-b border-white/10 px-8 py-4 flex items-center gap-4">
        {lotId && (
          <Link href="/lots" className="text-white/30 hover:text-white text-sm transition-colors">
            ← Lots
          </Link>
        )}
        <h1 className="text-base font-semibold text-white">
          {budget ? budget.label : "Costbook"}
        </h1>
        {budget && (
          <span className="text-xs font-mono text-white/30 bg-white/5 px-2 py-0.5 rounded">
            {budget.status}
          </span>
        )}
      </div>

      <div className="px-8 py-6">
        {loading ? (
          <div className="text-white/30 text-sm py-16 text-center">Loading…</div>
        ) : !budget ? (
          <div className="text-center py-16">
            <p className="text-white/40 text-sm mb-4">No budget yet for this lot.</p>
            <button
              onClick={handleCreate}
              disabled={creating}
              className="px-5 py-2.5 rounded-lg bg-amber-400/20 text-amber-300 border border-amber-400/30 text-sm font-medium hover:bg-amber-400/30 transition-colors disabled:opacity-40"
            >
              {creating ? "Creating…" : "Create Budget"}
            </button>
          </div>
        ) : (
          <>
            {/* Tabs */}
            <div className="flex gap-1 mb-6 bg-white/5 rounded-xl p-1 w-fit">
              {TAB_ITEMS.map((tab) => (
                <button
                  key={tab}
                  onClick={() => setActiveTab(tab)}
                  className={`px-4 py-2 rounded-lg text-sm font-medium transition-all ${
                    activeTab === tab
                      ? "bg-white/10 text-white"
                      : "text-white/40 hover:text-white/70"
                  }`}
                >
                  {tab}
                </button>
              ))}
            </div>

            {activeTab === "Budget" && (
              <BudgetTab
                budget={budget}
                onLineUpdate={handleLineUpdate}
                onIssuePO={(line) => setIssuePOLine(line)}
              />
            )}
            {activeTab === "Purchase Orders" && <POTab budgetId={budget.id} />}
            {activeTab === "Invoices" && (
              <InvoiceTab budgetId={budget.id} budgetLines={budget.lines} />
            )}
          </>
        )}
      </div>

      {issuePOLine && (
        <IssuePODrawer
          line={issuePOLine}
          budgetId={budget!.id}
          onClose={() => setIssuePOLine(null)}
          onCreated={() => {}}
        />
      )}
    </div>
  );
}
