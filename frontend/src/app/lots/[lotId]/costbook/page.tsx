"use client";

import { Fragment, useEffect, useState, useMemo } from "react";
import { useParams, useSearchParams } from "next/navigation";
import Link from "next/link";
import {
  getBudgets, createBudget, updateBudget, updateBudgetLine, getLot,
  getPurchaseOrders, createPurchaseOrder, updatePoStatus,
  getInvoices, ingestInvoice, approveInvoice, rejectInvoice,
  getVendors,
  type Budget, type BudgetLine, type PurchaseOrder, type Invoice, type Vendor, type Lot,
} from "@/lib/api/costbook";

// ─── Helpers ──────────────────────────────────────────────────────────────────

function fmt(n?: number | null) {
  if (n == null) return "—";
  return new Intl.NumberFormat("en-CA", { style: "currency", currency: "CAD", maximumFractionDigits: 0 }).format(n);
}

function confidence(n?: number | null) {
  if (n == null) return "";
  if (n >= 0.9) return "text-[var(--ch-success-text)]";
  if (n >= 0.7) return "text-[var(--ch-warning-text)]";
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
          { label: "Total Estimate", value: budget.total_estimate, color: "text-[var(--ch-text-primary)]" },
          { label: "Total Actual", value: budget.total_actual, color: "text-[var(--ch-text-primary)]" },
          {
            label: "Variance",
            value: budget.total_variance,
            color: budget.total_variance > 0 ? "text-red-400" : budget.total_variance < 0 ? "text-[var(--ch-success-text)]" : "text-[var(--ch-text-primary)]",
          },
        ].map(({ label, value, color }) => (
          <div key={label} className="bg-[var(--ch-surface)] border border-[var(--ch-border)] rounded-xl p-4">
            <p className="text-xs text-[var(--ch-text-muted)] mb-1">{label}</p>
            <p className={`text-xl font-semibold ${color}`}>{fmt(value)}</p>
          </div>
        ))}
      </div>

      {/* Table */}
      <div className="rounded-xl border border-[var(--ch-border)] overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-[var(--ch-surface)] border-b border-[var(--ch-border)] text-xs text-[var(--ch-text-muted)] uppercase tracking-widest">
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
              <Fragment key={section}>
                <tr className="bg-[var(--ch-surface)] border-t border-[var(--ch-border)]">
                  <td colSpan={6} className="px-4 py-2 text-[10px] font-bold text-[var(--ch-text-muted)] uppercase tracking-widest">
                    {section}
                  </td>
                </tr>
                {lines.map((line) => {
                  const variance = line.actual - line.estimate;
                  const isOver = variance > 0 && line.actual > 0;
                  const isUnder = variance < 0 && line.actual > 0;

                  return (
                    <tr key={line.id} className="border-t border-[var(--ch-border)] hover:bg-[var(--ch-surface)] group">
                      <td className="px-4 py-2.5 font-mono text-xs text-[var(--ch-text-muted)]">{line.po_number}</td>
                      <td className="px-4 py-2.5 text-[var(--ch-text-secondary)]">{line.description}</td>

                      {/* Estimate cell */}
                      <td className="px-4 py-2.5 text-right">
                        {editingCell?.lineId === line.id && editingCell.field === "estimate" ? (
                          <input
                            autoFocus
                            type="text"
                            inputMode="decimal"
                            value={editValue}
                            onChange={(e) => setEditValue(e.target.value)}
                            onBlur={() => commitEdit(line, "estimate")}
                            onKeyDown={(e) => e.key === "Enter" && commitEdit(line, "estimate")}
                            className="w-full text-right bg-[var(--ch-surface)] border border-amber-400/50 rounded px-2 py-0.5 text-[var(--ch-text-primary)] focus:outline-none"
                          />
                        ) : (
                          <span
                            onClick={() => startEdit(line, "estimate")}
                            className="cursor-pointer hover:text-[var(--ch-warning-text)] transition-colors text-[var(--ch-text-secondary)]"
                          >
                            {line.estimate > 0 ? fmt(line.estimate) : <span className="text-[var(--ch-text-muted)]">—</span>}
                          </span>
                        )}
                      </td>

                      {/* Actual cell */}
                      <td className="px-4 py-2.5 text-right">
                        {editingCell?.lineId === line.id && editingCell.field === "actual" ? (
                          <input
                            autoFocus
                            type="text"
                            inputMode="decimal"
                            value={editValue}
                            onChange={(e) => setEditValue(e.target.value)}
                            onBlur={() => commitEdit(line, "actual")}
                            onKeyDown={(e) => e.key === "Enter" && commitEdit(line, "actual")}
                            className="w-full text-right bg-[var(--ch-surface)] border border-amber-400/50 rounded px-2 py-0.5 text-[var(--ch-text-primary)] focus:outline-none"
                          />
                        ) : (
                          <span
                            onClick={() => startEdit(line, "actual")}
                            className="cursor-pointer hover:text-[var(--ch-warning-text)] transition-colors text-[var(--ch-text-secondary)]"
                          >
                            {line.actual > 0 ? fmt(line.actual) : <span className="text-[var(--ch-text-muted)]">—</span>}
                          </span>
                        )}
                      </td>

                      {/* Variance */}
                      <td className={`px-4 py-2.5 text-right font-medium ${isOver ? "text-red-400" : isUnder ? "text-[var(--ch-success-text)]" : "text-[var(--ch-text-muted)]"}`}>
                        {line.actual > 0 ? fmt(variance) : "—"}
                      </td>

                      {/* Issue PO */}
                      <td className="px-4 py-2.5 text-center opacity-0 group-hover:opacity-100 transition-opacity">
                        <button
                          onClick={() => onIssuePO(line)}
                          title="Issue PO"
                          className="text-xs text-[var(--ch-text-muted)] hover:text-[var(--ch-warning-text)] transition-colors"
                        >
                          PO+
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ─── PO Tab ───────────────────────────────────────────────────────────────────

const PO_STATUS_COLOR: Record<string, string> = {
  draft: "bg-[var(--ch-surface)] text-[var(--ch-text-muted)]",
  issued: "bg-blue-500/15 text-blue-300",
  acknowledged: "bg-purple-500/15 text-purple-300",
  complete: "bg-[var(--ch-success-bg)] text-[var(--ch-success-text)]",
  cancelled: "bg-[var(--ch-error-bg)] text-[var(--ch-error-text)]",
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

  if (loading) return <div className="text-[var(--ch-text-muted)] text-sm py-8 text-center">Loading…</div>;
  if (pos.length === 0) return <div className="text-[var(--ch-text-muted)] text-sm py-8 text-center">No purchase orders yet. Issue one from the Budget tab.</div>;

  return (
    <div className="rounded-xl border border-[var(--ch-border)] overflow-hidden">
      <table className="w-full text-sm">
        <thead>
          <tr className="bg-[var(--ch-surface)] border-b border-[var(--ch-border)] text-xs text-[var(--ch-text-muted)] uppercase tracking-widest">
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
            <tr key={po.id} className="border-t border-[var(--ch-border)] hover:bg-[var(--ch-surface)]">
              <td className="px-4 py-3 font-mono text-xs text-[var(--ch-text-muted)]">{po.po_number}</td>
              <td className="px-4 py-3 text-[var(--ch-text-secondary)]">{po.vendor_name || po.vendor_name_adhoc || "—"}</td>
              <td className="px-4 py-3 text-[var(--ch-text-secondary)]">{po.description}</td>
              <td className="px-4 py-3 text-right text-[var(--ch-text-secondary)]">{fmt(po.amount)}</td>
              <td className="px-4 py-3">
                <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${PO_STATUS_COLOR[po.status]}`}>
                  {po.status}
                </span>
              </td>
              <td className="px-4 py-3 text-right">
                {["draft", "issued", "acknowledged"].includes(po.status) && (
                  <button
                    onClick={() => advance(po)}
                    className="text-xs text-[var(--ch-text-muted)] hover:text-[var(--ch-warning-text)] transition-colors"
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
            ? "bg-[var(--ch-surface)] text-[var(--ch-text-muted)] cursor-not-allowed"
            : "bg-amber-400/20 text-[var(--ch-warning-text)] border border-[var(--ch-warning-border)] hover:bg-amber-400/30"
          }`}
        >
          {uploading ? "Extracting…" : "Upload Invoice"}
          <input type="file" accept=".pdf,.png,.jpg,.jpeg" className="hidden" onChange={handleUpload} disabled={uploading} />
        </label>
        <p className="text-xs text-[var(--ch-text-muted)] mt-1.5">PDF or image — Claude extracts the details automatically</p>
      </div>

      {loading ? (
        <div className="text-[var(--ch-text-muted)] text-sm py-8 text-center">Loading…</div>
      ) : invoices.length === 0 ? (
        <div className="text-[var(--ch-text-muted)] text-sm py-8 text-center">No invoices yet.</div>
      ) : (
        <div className="space-y-3">
          {invoices.map((inv) => (
            <div key={inv.id} className="rounded-xl border border-[var(--ch-border)] bg-[var(--ch-surface)] p-5">
              <div className="flex items-start justify-between gap-4 mb-3">
                <div>
                  <div className="flex items-center gap-2 mb-1">
                    <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${
                      inv.status === "approved" ? "bg-[var(--ch-success-bg)] text-[var(--ch-success-text)]"
                      : inv.status === "rejected" ? "bg-[var(--ch-error-bg)] text-[var(--ch-error-text)]"
                      : "bg-[var(--ch-warning-bg)] text-[var(--ch-warning-text)]"
                    }`}>
                      {inv.status.replace("_", " ")}
                    </span>
                    {inv.extraction_confidence != null && (
                      <span className={`text-xs ${confidence(inv.extraction_confidence)}`}>
                        {Math.round(inv.extraction_confidence * 100)}% confidence
                      </span>
                    )}
                  </div>
                  <p className="text-[var(--ch-text-primary)] font-medium">{inv.vendor_name || "Unknown Vendor"}</p>
                  {inv.invoice_number && <p className="text-xs text-[var(--ch-text-muted)]">#{inv.invoice_number}</p>}
                </div>
                <div className="text-right">
                  <p className="text-lg font-semibold text-[var(--ch-text-primary)]">{fmt(inv.amount_claimed)}</p>
                  {inv.invoice_date && <p className="text-xs text-[var(--ch-text-muted)]">{inv.invoice_date}</p>}
                </div>
              </div>

              {inv.suggested_po_number && (
                <p className="text-xs text-[var(--ch-text-muted)] mb-3">
                  Suggested category: <span className="font-mono text-[var(--ch-text-secondary)]">{inv.suggested_po_number}</span>
                </p>
              )}

              {inv.status === "pending_review" && (
                <div className="flex items-center gap-3 mt-3 pt-3 border-t border-[var(--ch-border)]">
                  {approvingId === inv.id ? (
                    <>
                      <select
                        value={selectedLineId}
                        onChange={(e) => setSelectedLineId(e.target.value)}
                        className="flex-1 bg-[var(--ch-surface)] border border-[var(--ch-border-strong)] rounded-lg px-3 py-1.5 text-sm text-[var(--ch-text-primary)] focus:outline-none focus:border-amber-400/50"
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
                        className="px-3 py-1.5 rounded-lg bg-[var(--ch-success-bg)] text-[var(--ch-success-text)] text-sm hover:brightness-105 transition-colors"
                      >
                        Confirm
                      </button>
                      <button
                        onClick={() => setApprovingId(null)}
                        className="px-3 py-1.5 rounded-lg bg-[var(--ch-surface)] text-[var(--ch-text-muted)] text-sm hover:bg-[var(--ch-surface)] transition-colors"
                      >
                        Cancel
                      </button>
                    </>
                  ) : (
                    <>
                      <button
                        onClick={() => setApprovingId(inv.id)}
                        className="px-3 py-1.5 rounded-lg bg-[var(--ch-success-bg)] text-[var(--ch-success-text)] text-sm hover:brightness-105 transition-colors"
                      >
                        Approve
                      </button>
                      <button
                        onClick={() => handleReject(inv)}
                        className="px-3 py-1.5 rounded-lg bg-[var(--ch-error-bg)] text-[var(--ch-error-text)] text-sm hover:brightness-105 transition-colors"
                      >
                        Reject
                      </button>
                    </>
                  )}
                </div>
              )}

              {inv.status === "rejected" && inv.rejection_reason && (
                <p className="text-xs text-red-400/70 mt-2 pt-2 border-t border-[var(--ch-border)]">{inv.rejection_reason}</p>
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
    } catch (err) {
      alert(err instanceof Error ? err.message : "Failed to issue purchase order.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={onClose} />
      <div className="relative flex h-full w-full max-w-md flex-col overflow-y-auto rounded-l-2xl border-l border-[var(--ch-border)] bg-[var(--ch-surface)] shadow-xl">
        <div className="flex items-center justify-between border-b border-[var(--ch-border)] px-5 py-4">
          <div>
            <h2 className="text-base font-semibold text-[var(--ch-text-primary)]">Issue Purchase Order</h2>
            <p className="text-xs text-[var(--ch-text-muted)] mt-0.5 font-mono">{line.po_number} — {line.description}</p>
          </div>
          <button onClick={onClose} className="text-[var(--ch-text-muted)] hover:text-[var(--ch-text-primary)] text-xl">×</button>
        </div>

        <div className="flex-1 space-y-4 px-5 py-4">
          <div>
            <label className="text-xs text-[var(--ch-text-muted)] mb-1.5 block">Vendor</label>
            <select
              value={vendorId}
              onChange={(e) => { setVendorId(e.target.value); if (e.target.value) setVendorName(""); }}
              className="w-full bg-[var(--ch-surface)] border border-[var(--ch-border)] rounded-lg px-3 py-2 text-sm text-[var(--ch-text-primary)] focus:outline-none focus:border-[var(--ch-accent)] focus:ring-2 focus:ring-[var(--ch-focus-ring)] mb-2"
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
                className="w-full bg-[var(--ch-surface)] border border-[var(--ch-border)] rounded-lg px-3 py-2 text-sm text-[var(--ch-text-primary)] placeholder:text-[var(--ch-text-muted)] focus:outline-none focus:border-[var(--ch-accent)] focus:ring-2 focus:ring-[var(--ch-focus-ring)]"
              />
            )}
          </div>

          <div>
            <label className="text-xs text-[var(--ch-text-muted)] mb-1.5 block">Description</label>
            <input
              type="text"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              className="w-full bg-[var(--ch-surface)] border border-[var(--ch-border)] rounded-lg px-3 py-2 text-sm text-[var(--ch-text-primary)] focus:outline-none focus:border-[var(--ch-accent)] focus:ring-2 focus:ring-[var(--ch-focus-ring)]"
            />
          </div>

          <div>
            <label className="text-xs text-[var(--ch-text-muted)] mb-1.5 block">Amount (CAD)</label>
            <input
              type="text"
              inputMode="decimal"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              className="w-full bg-[var(--ch-surface)] border border-[var(--ch-border)] rounded-lg px-3 py-2 text-sm text-[var(--ch-text-primary)] focus:outline-none focus:border-[var(--ch-accent)] focus:ring-2 focus:ring-[var(--ch-focus-ring)]"
            />
          </div>

          <div>
            <label className="text-xs text-[var(--ch-text-muted)] mb-1.5 block">Notes (optional)</label>
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              rows={3}
              className="w-full bg-[var(--ch-surface)] border border-[var(--ch-border)] rounded-lg px-3 py-2 text-sm text-[var(--ch-text-primary)] placeholder:text-[var(--ch-text-muted)] focus:outline-none focus:border-[var(--ch-accent)] focus:ring-2 focus:ring-[var(--ch-focus-ring)] resize-none"
            />
          </div>
        </div>

        <div className="mt-auto flex justify-end gap-3 border-t border-[var(--ch-border)] px-5 py-4">
          <button
            onClick={submit}
            disabled={saving}
            className="rounded-lg bg-[var(--ch-accent)] px-5 py-2.5 text-sm font-medium text-[var(--ch-accent-text)] transition-colors hover:bg-[var(--ch-accent-hover)] disabled:opacity-40"
          >
            {saving ? "Issuing…" : "Issue PO"}
          </button>
          <button
            onClick={onClose}
            className="rounded-lg border border-[var(--ch-border-strong)] bg-[var(--ch-surface)] px-4 py-2.5 text-sm text-[var(--ch-text-secondary)] transition-colors hover:bg-[var(--ch-surface-hover)]"
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
  const lotId = params?.lotId as string | undefined;

  const initialTab = (searchParams?.get("tab") === "invoices" ? "Invoices" : "Budget") as Tab;
  const [activeTab, setActiveTab] = useState<Tab>(initialTab);
  const [budget, setBudget] = useState<Budget | null>(null);
  const [lot, setLot] = useState<Lot | null>(null);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [issuePOLine, setIssuePOLine] = useState<BudgetLine | null>(null);
  const visibleBudget = budget && (!lotId || budget.lot_agreement_id === lotId) ? budget : null;

  useEffect(() => {
    const load = async () => {
      try {
        const [lotData, budgets] = await Promise.all([
          lotId ? getLot(lotId).catch(() => null) : Promise.resolve(null),
          getBudgets(),
        ]);
        setLot(lotData);
        const match = lotId
          ? budgets.find((b) => b.lot_agreement_id === lotId)
          : budgets[0];
        if (match && lotData?.address && match.label === "New Budget") {
          const renamed = await updateBudget(match.id, { label: lotData.address });
          setBudget(renamed);
        } else {
          setBudget(match ?? null);
        }
      } finally {
        setLoading(false);
      }
    };

    void load();
  }, [lotId]);

  async function handleCreate() {
    setCreating(true);
    try {
      const lotData = lot ?? (lotId ? await getLot(lotId).catch(() => null) : null);
      if (lotData) setLot(lotData);
      const b = await createBudget({
        label: lotData?.address || "New Budget",
        lot_agreement_id: lotId,
      });
      setBudget(b);
    } finally {
      setCreating(false);
    }
  }

  async function handleLineUpdate(lineId: string, field: "estimate" | "actual", value: number) {
    if (!visibleBudget) return;
    const updated = await updateBudgetLine(visibleBudget.id, lineId, { [field]: value });
    setBudget((prev) => {
      if (!prev) return prev;
      const lines = prev.lines.map((l) => (l.id === updated.id ? { ...l, [field]: value } : l));
      const total_estimate = lines.reduce((s, l) => s + (l.estimate || 0), 0);
      const total_actual = lines.reduce((s, l) => s + (l.actual || 0), 0);
      return { ...prev, lines, total_estimate, total_actual, total_variance: total_actual - total_estimate };
    });
  }

  function handlePOCreated(po: PurchaseOrder) {
    setBudget((prev) => {
      if (!prev) return prev;
      const lines = prev.lines.map((line) =>
        line.id === po.budget_line_id
          ? { ...line, estimate: (line.estimate || 0) + po.amount, origin_of_number: "PO total" }
          : line
      );
      const total_estimate = lines.reduce((sum, line) => sum + (line.estimate || 0), 0);
      const total_actual = lines.reduce((sum, line) => sum + (line.actual || 0), 0);
      return { ...prev, lines, total_estimate, total_actual, total_variance: total_actual - total_estimate };
    });
  }

  return (
    <div className="min-h-screen bg-[var(--ch-page-bg)] text-[var(--ch-text-primary)]">
      {/* Top bar */}
      <div className="border-b border-[var(--ch-border)] px-8 py-4 flex items-center gap-4">
        {lotId && (
          <Link href="/lots" className="text-[var(--ch-text-muted)] hover:text-[var(--ch-text-primary)] text-sm transition-colors">
            ← Lots
          </Link>
        )}
        <h1 className="text-base font-semibold text-[var(--ch-text-primary)]">
          {visibleBudget ? visibleBudget.label : "Costbook"}
        </h1>
        {visibleBudget && (
          <span className="text-xs font-mono text-[var(--ch-text-muted)] bg-[var(--ch-surface)] px-2 py-0.5 rounded">
            {visibleBudget.status}
          </span>
        )}
      </div>

      <div className="px-8 py-6">
        {loading ? (
          <div className="text-[var(--ch-text-muted)] text-sm py-16 text-center">Loading…</div>
        ) : !visibleBudget ? (
          <div className="text-center py-16">
            <p className="text-[var(--ch-text-muted)] text-sm mb-4">No budget yet for this lot.</p>
            <button
              onClick={handleCreate}
              disabled={creating}
              className="px-5 py-2.5 rounded-lg bg-amber-400/20 text-[var(--ch-warning-text)] border border-[var(--ch-warning-border)] text-sm font-medium hover:bg-amber-400/30 transition-colors disabled:opacity-40"
            >
              {creating ? "Creating…" : "Create Budget"}
            </button>
          </div>
        ) : (
          <>
            {/* Tabs */}
            <div className="flex gap-1 mb-6 bg-[var(--ch-surface)] rounded-xl p-1 w-fit">
              {TAB_ITEMS.map((tab) => (
                <button
                  key={tab}
                  onClick={() => setActiveTab(tab)}
                  className={`px-4 py-2 rounded-lg text-sm font-medium transition-all ${
                    activeTab === tab
                      ? "bg-[var(--ch-surface)] text-[var(--ch-text-primary)]"
                      : "text-[var(--ch-text-muted)] hover:text-[var(--ch-text-secondary)]"
                  }`}
                >
                  {tab}
                </button>
              ))}
            </div>

            {activeTab === "Budget" && (
              <BudgetTab
                budget={visibleBudget}
                onLineUpdate={handleLineUpdate}
                onIssuePO={(line) => setIssuePOLine(line)}
              />
            )}
            {activeTab === "Purchase Orders" && <POTab budgetId={visibleBudget.id} />}
            {activeTab === "Invoices" && (
              <InvoiceTab budgetId={visibleBudget.id} budgetLines={visibleBudget.lines} />
            )}
          </>
        )}
      </div>

      {issuePOLine && visibleBudget && (
        <IssuePODrawer
          line={issuePOLine}
          budgetId={visibleBudget.id}
          onClose={() => setIssuePOLine(null)}
          onCreated={handlePOCreated}
        />
      )}
    </div>
  );
}
