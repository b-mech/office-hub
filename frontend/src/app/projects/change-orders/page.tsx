"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { AlertTriangle, Columns, LayoutList, MoreVertical, RefreshCw } from "lucide-react";

import PipelineView from "@/app/projects/change-orders/PipelineView";
import {
  archiveChangeOrder,
  downloadChangeOrderPdf,
  getChangeOrders,
  prepareChangeOrderSignature,
  retryChangeOrderQbo,
  setChangeOrderQboMapping,
  submitChangeOrderPaymentLink,
  syncSignedChangeOrder,
  type ChangeOrder,
  updateChangeOrder,
  updateChangeOrderStatus,
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

function StatusPill({ status }: { status: string }) {
  const styles: Record<string, string> = {
    draft: "bg-[var(--ch-status-draft-bg)] text-[var(--ch-status-draft-text)] border-[var(--ch-status-draft-border)]",
    sent: "bg-[var(--ch-status-sent-bg)] text-[var(--ch-status-sent-text)] border-[var(--ch-status-sent-border)]",
    awaiting_payment_link: "bg-[var(--ch-warning-bg)] text-[var(--ch-warning-text)] border-[var(--ch-warning-border)]",
    signed: "bg-[var(--ch-status-signed-bg)] text-[var(--ch-status-signed-text)] border-[var(--ch-status-signed-border)]",
    complete: "bg-[var(--ch-status-complete-bg)] text-[var(--ch-status-complete-text)] border-[var(--ch-status-complete-border)]",
    declined: "bg-[var(--ch-status-declined-bg)] text-[var(--ch-status-declined-text)] border-[var(--ch-status-declined-border)]",
  };
  const labels: Record<string, string> = {
    draft: "draft",
    sent: "sent",
    awaiting_payment_link: "awaiting payment link",
    signed: "signed",
    complete: "complete ✓",
    declined: "declined",
  };
  const style = styles[status] ?? styles.draft;
  const label = labels[status] ?? status;
  return (
    <span className={`rounded-full border px-2.5 py-1 text-xs font-medium ${style}`}>
      {label}
    </span>
  );
}

type ViewMode = "list" | "pipeline";

export default function ProjectChangeOrdersPage() {
  const router = useRouter();
  const [changeOrders, setChangeOrders] = useState<ChangeOrder[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const [busyOrderId, setBusyOrderId] = useState<string | null>(null);
  const [openMenuId, setOpenMenuId] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [scopedAddress, setScopedAddress] = useState("");
  const [view, setView] = useState<ViewMode>("list");
  const [includeArchived, setIncludeArchived] = useState(false);
  const [paymentOrder, setPaymentOrder] = useState<ChangeOrder | null>(null);
  const [paymentLink, setPaymentLink] = useState("");
  useEffect(() => {
    const timeoutId = window.setTimeout(() => {
      const params = new URLSearchParams(window.location.search);
      const address = params.get("property_id") ? params.get("address")?.trim() || "" : "";
      if (address) {
        setScopedAddress(address);
        setSearch(address);
      }
    }, 0);
    return () => window.clearTimeout(timeoutId);
  }, []);

  useEffect(() => {
    getChangeOrders(includeArchived)
      .then((result) => {
        setChangeOrders(result);
        setError(null);
      })
      .catch((loadError) => {
        setError(loadError instanceof Error ? loadError.message : "Could not load change orders.");
      })
      .finally(() => setLoading(false));
  }, [includeArchived]);

  useEffect(() => {
    if (!openMenuId) return;
    function closeMenu() {
      setOpenMenuId(null);
    }
    document.addEventListener("mousedown", closeMenu);
    return () => document.removeEventListener("mousedown", closeMenu);
  }, [openMenuId]);

  const filtered = useMemo(() => {
    const query = search.trim().toLowerCase();
    if (!query) return changeOrders;

    return changeOrders.filter((order) => {
      if (scopedAddress && order.address.trim().toLowerCase() !== scopedAddress.toLowerCase()) return false;
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
  }, [changeOrders, scopedAddress, search]);

  async function handleDownloadPdf(order: ChangeOrder) {
    setOpenMenuId(null);
    setBusyOrderId(order.id);
    setError(null);
    setActionMessage(null);
    try {
      const blob = await downloadChangeOrderPdf(order.id);
      const objectUrl = URL.createObjectURL(blob);
      window.open(objectUrl, "_blank", "noopener,noreferrer");
      window.setTimeout(() => URL.revokeObjectURL(objectUrl), 30000);
      setActionMessage(`PDF generated for ${order.address}.`);
      getChangeOrders(includeArchived)
        .then((result) => setChangeOrders(result))
        .catch(() => undefined);
    } catch (downloadError) {
      setError(downloadError instanceof Error ? downloadError.message : "Could not generate PDF.");
    } finally {
      setBusyOrderId(null);
    }
  }

  async function handleSendSignature(order: ChangeOrder) {
    setOpenMenuId(null);
    let customerEmail = order.customer_email;
    if (!customerEmail) {
      const entered = window.prompt("Client email required before sending for signature.");
      if (!entered) return;
      customerEmail = entered.trim();
    }
    setBusyOrderId(order.id);
    setError(null);
    setActionMessage(null);
    try {
      if (customerEmail !== order.customer_email) {
        await updateChangeOrder(order.id, { customer_email: customerEmail });
      }
      const result = await prepareChangeOrderSignature(order.id);
      setActionMessage("QuickBooks invoice creation started. Paste the Plooto link to continue to DocuSign.");
      setPaymentOrder({ ...order, ...result, customer_email: customerEmail });
      setChangeOrders((current) =>
        current.map((item) =>
          item.id === order.id
            ? {
                ...item,
                ...result,
                customer_email: customerEmail,
              }
            : item,
        ),
      );
    } catch (sendError) {
      setError(sendError instanceof Error ? sendError.message : "Could not send for signature.");
    } finally {
      setBusyOrderId(null);
    }
  }

  async function handlePaymentLinkSubmit(event: React.FormEvent) {
    event.preventDefault(); if (!paymentOrder) return;
    setBusyOrderId(paymentOrder.id); setError(null);
    try {
      await submitChangeOrderPaymentLink(paymentOrder.id, paymentLink);
      const refreshed = await getChangeOrders(includeArchived); setChangeOrders(refreshed);
      setPaymentOrder(null); setPaymentLink(""); setActionMessage("Plooto link saved and change order sent to DocuSign.");
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not save payment link."); }
    finally { setBusyOrderId(null); }
  }

  async function handleSyncSigned(order: ChangeOrder) {
    setOpenMenuId(null);
    setBusyOrderId(order.id);
    setError(null);
    setActionMessage(null);
    try {
      const result = await syncSignedChangeOrder(order.id);
      setActionMessage(result.message);
      setChangeOrders((current) =>
        current.map((item) =>
          item.id === order.id
            ? {
                ...item,
                status: result.status as ChangeOrder["status"],
                box_file_id: result.box_file_id ?? item.box_file_id,
                box_file_url: result.box_file_url ?? item.box_file_url,
                box_unfiled: result.box_unfiled ?? item.box_unfiled,
              }
            : item,
        ),
      );
    } catch (syncError) {
      setError(syncError instanceof Error ? syncError.message : "Could not sync signed PDF.");
    } finally {
      setBusyOrderId(null);
    }
  }

  function handleEdit(order: ChangeOrder) {
    setOpenMenuId(null);
    router.push(`/change-orders/${order.id}/edit`);
  }

  async function handleDelete(order: ChangeOrder) {
    setOpenMenuId(null);
    if (window.confirm(`Archive change order for ${order.address}? It will be hidden by default but retained.`)) {
      setBusyOrderId(order.id);
      setError(null);
      try {
        await archiveChangeOrder(order.id);
        setChangeOrders((current) => current.filter((item) => item.id !== order.id));
        setActionMessage(`Archived change order for ${order.address}.`);
      } catch (archiveError) {
        setError(archiveError instanceof Error ? archiveError.message : "Could not archive change order.");
      } finally {
        setBusyOrderId(null);
      }
    }
  }

  function handleViewInBox(order: ChangeOrder) {
    setOpenMenuId(null);
    if (order.box_file_url) {
      window.open(order.box_file_url, "_blank", "noopener,noreferrer");
    }
  }

  async function handleStatusChange(id: string, newStatus: ChangeOrder["status"]) {
    setError(null);
    setActionMessage(null);
    try {
      await updateChangeOrderStatus(id, newStatus);
      setChangeOrders((current) =>
        current.map((co) => (co.id === id ? { ...co, status: newStatus } : co)),
      );
    } catch (statusError) {
      setError(statusError instanceof Error ? statusError.message : "Could not update status.");
      throw statusError;
    }
  }

  return (
    <main className="min-h-screen bg-[var(--ch-page-bg)] text-[var(--ch-text-primary)]">
      <div className={`mx-auto flex flex-col gap-6 px-6 py-8 lg:px-10 ${view === "pipeline" ? "max-w-none" : "max-w-6xl"}`}>
        <header className="flex flex-col gap-4 border-b border-[var(--ch-border)] pb-6 md:flex-row md:items-end md:justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.24em] text-[var(--ch-text-muted)]">
              Projects
            </p>
            <h1 className="mt-2 text-3xl font-semibold tracking-tight">Change Orders</h1>
            <p className="mt-2 text-sm text-[var(--ch-text-muted)]">
              Filter and review saved change order drafts across all projects.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2 md:justify-end">
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => setView("list")}
                className={`inline-flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-semibold transition ${
                  view === "list"
                    ? "bg-[var(--ch-accent)] text-[var(--ch-accent-text)]"
                    : "border border-[var(--ch-border)] bg-[var(--ch-surface)] text-[var(--ch-text-secondary)] hover:text-[var(--ch-text-primary)]"
                }`}
              >
                <LayoutList className="h-4 w-4" aria-hidden="true" />
                List
              </button>
              <button
                type="button"
                onClick={() => setView("pipeline")}
                className={`inline-flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-semibold transition ${
                  view === "pipeline"
                    ? "bg-[var(--ch-accent)] text-[var(--ch-accent-text)]"
                    : "border border-[var(--ch-border)] bg-[var(--ch-surface)] text-[var(--ch-text-secondary)] hover:text-[var(--ch-text-primary)]"
                }`}
              >
                <Columns className="h-4 w-4" aria-hidden="true" />
                Pipeline
              </button>
            </div>
            <Link
              href="/change-orders/new"
              className="rounded-lg bg-[var(--ch-accent)] px-4 py-2 text-sm font-bold text-[var(--ch-accent-text)] hover:brightness-105"
            >
              New Change Order
            </Link>
          </div>
        </header>

        {view === "list" && (
          <section className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <input
              type="search"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Filter address, client, CO number, line item..."
              className="w-full rounded-lg border border-[var(--ch-border)] bg-[var(--ch-surface)] px-3 py-2.5 text-sm text-[var(--ch-text-primary)] outline-none placeholder:text-[var(--ch-text-muted)] focus:border-amber-400/50 sm:max-w-md"
            />
            <p className="text-sm text-[var(--ch-text-muted)]">
              {filtered.length} of {changeOrders.length} shown
            </p>
            <label className="flex items-center gap-2 text-sm text-[var(--ch-text-muted)]">
              <input
                type="checkbox"
                checked={includeArchived}
                onChange={(event) => setIncludeArchived(event.target.checked)}
              />
              Include archived
            </label>
          </section>
        )}

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

        {view === "pipeline" ? (
          loading ? (
            <div className="rounded-xl border border-[var(--ch-border)] bg-[var(--ch-surface)] p-8 text-center text-sm text-[var(--ch-text-muted)]">
              Loading change orders...
            </div>
          ) : (
            <PipelineView
              changeOrders={changeOrders}
              onStatusChange={handleStatusChange}
              onSendSignature={handleSendSignature}
            />
          )
        ) : (
          <section className="overflow-hidden rounded-xl border border-[var(--ch-border)] bg-[var(--ch-surface)]">
            {loading ? (
              <div className="p-8 text-center text-sm text-[var(--ch-text-muted)]">Loading change orders...</div>
            ) : filtered.length === 0 ? (
              <div className="p-8 text-center text-sm text-[var(--ch-text-muted)]">
                No change orders found.
              </div>
            ) : (
              <div className="divide-y divide-white/10">
                {filtered.map((order) => (
                  <article
                    key={order.id}
                    className="grid gap-4 px-4 py-4 md:grid-cols-[1.2fr_1fr_150px_110px_220px] md:items-center"
                  >
                  <div className="min-w-0">
                    <p className="truncate text-sm font-semibold text-[var(--ch-text-primary)]">{order.address}</p>
                    <div className="mt-1 flex flex-wrap items-center gap-2">
                      <p className="truncate text-xs text-[var(--ch-text-muted)]">{order.client_name}</p>
                      {!order.customer_email && (
                        <span className="rounded-full border border-[var(--ch-warning-border)] bg-[var(--ch-warning-bg)] px-2 py-0.5 text-[10px] font-semibold text-[var(--ch-warning-text)]">
                          needs email
                        </span>
                      )}
                      {order.archived_at && (
                        <span className="rounded-full border border-[var(--ch-border)] px-2 py-0.5 text-[10px] font-semibold text-[var(--ch-text-muted)]">
                          archived
                        </span>
                      )}
                    </div>
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
                    <StatusPill status={order.status || "draft"} />
                  </div>
                  <div className="flex flex-wrap items-center gap-2 md:justify-end">
                    <button
                      type="button"
                      onClick={() => void handleDownloadPdf(order)}
                      disabled={busyOrderId === order.id}
                      className="rounded-lg border border-[var(--ch-border)] bg-[var(--ch-surface)] px-3 py-2 text-xs font-semibold text-[var(--ch-text-secondary)] transition hover:bg-[var(--ch-surface)] hover:text-[var(--ch-text-primary)] disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      PDF
                    </button>
                    {order.status === "draft" && (
                      <button
                        type="button"
                        onClick={() => void handleSendSignature(order)}
                        disabled={busyOrderId === order.id}
                        className="rounded-lg bg-[var(--ch-accent)] px-3 py-2 text-xs font-bold text-[var(--ch-accent-text)] transition hover:brightness-105 disabled:cursor-not-allowed disabled:opacity-60"
                      >
                        {busyOrderId === order.id ? "Working..." : "Send for Signature"}
                      </button>
                    )}
                    {order.status === "awaiting_payment_link" && (
                      <button type="button" onClick={() => { setPaymentOrder(order); setPaymentLink(order.plooto_payment_link || ""); }} className="rounded-lg bg-[var(--ch-accent)] px-3 py-2 text-xs font-bold text-[var(--ch-accent-text)]">Paste Plooto Link</button>
                    )}
                    <div className="flex gap-1">
                      <span className="rounded-full border border-[var(--ch-border)] px-2 py-1 text-[10px]">{order.status === "signed" || order.status === "complete" ? "Signed" : "Not signed"}</span>
                      <span className={`rounded-full border px-2 py-1 text-[10px] ${order.qb_invoice_status === "paid" ? "border-[var(--ch-success-border)] bg-[var(--ch-success-bg)] text-[var(--ch-success-text)]" : "border-[var(--ch-border)]"}`}>{order.qb_invoice_status === "paid" ? "Paid" : "Not paid"}</span>
                    </div>
                    {order.box_unfiled && (
                      <span title="Filed to Unfiled Change Orders - Box folder not found for this address">
                        <AlertTriangle
                          className="h-3.5 w-3.5 text-[var(--ch-warning-text)]"
                          aria-label="Filed to Unfiled Change Orders - Box folder not found for this address"
                        />
                      </span>
                    )}
                    <div className="relative" onMouseDown={(event) => event.stopPropagation()}>
                      <button
                        type="button"
                        onClick={() => setOpenMenuId((current) => (current === order.id ? null : order.id))}
                        aria-label={`Actions for ${order.address}`}
                        className="rounded-lg border border-[var(--ch-border)] bg-[var(--ch-surface)] p-1.5 text-[var(--ch-text-muted)] transition hover:bg-[var(--ch-page-bg)]"
                      >
                        <MoreVertical className="h-4 w-4" aria-hidden="true" />
                      </button>
                      {openMenuId === order.id && (
                        <div className="absolute right-0 top-full z-10 mt-1 min-w-[160px] rounded-xl border border-[var(--ch-border)] bg-[var(--ch-surface)] py-1 shadow-lg">
                          {order.status === "draft" && (
                            <>
                              <button
                                type="button"
                                onClick={() => handleEdit(order)}
                                className="flex w-full items-center gap-2 px-3 py-2 text-sm text-[var(--ch-text-primary)] hover:bg-[var(--ch-page-bg)] disabled:cursor-not-allowed disabled:opacity-50"
                              >
                                Edit
                              </button>
                              <button
                                type="button"
                                onClick={() => void handleDelete(order)}
                                className="flex w-full items-center gap-2 px-3 py-2 text-sm text-[var(--ch-text-primary)] hover:bg-[var(--ch-page-bg)] disabled:cursor-not-allowed disabled:opacity-50"
                              >
                                Archive
                              </button>
                            </>
                          )}
                          {order.status === "sent" && (
                            <>
                              <button
                                type="button"
                                onClick={() => void handleSyncSigned(order)}
                                disabled={busyOrderId === order.id}
                                className="flex w-full items-center gap-2 px-3 py-2 text-sm text-[var(--ch-text-primary)] hover:bg-[var(--ch-page-bg)] disabled:cursor-not-allowed disabled:opacity-50"
                              >
                                <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
                                Sync Signed
                              </button>
                              <button
                                type="button"
                                onClick={() => void handleSendSignature(order)}
                                disabled={busyOrderId === order.id || !order.customer_email}
                                className="flex w-full items-center gap-2 px-3 py-2 text-sm text-[var(--ch-text-primary)] hover:bg-[var(--ch-page-bg)] disabled:cursor-not-allowed disabled:opacity-50"
                              >
                                Resend
                              </button>
                            </>
                          )}
                          {(order.status === "signed" || order.status === "complete") && order.box_file_url && (
                            <button
                              type="button"
                              onClick={() => handleViewInBox(order)}
                              className="flex w-full items-center gap-2 px-3 py-2 text-sm text-[var(--ch-text-primary)] hover:bg-[var(--ch-page-bg)] disabled:cursor-not-allowed disabled:opacity-50"
                            >
                              View in Box
                            </button>
                          )}
                          <button
                            type="button"
                            onClick={() => void handleDownloadPdf(order)}
                            disabled={busyOrderId === order.id}
                            className="flex w-full items-center gap-2 px-3 py-2 text-sm text-[var(--ch-text-primary)] hover:bg-[var(--ch-page-bg)] disabled:cursor-not-allowed disabled:opacity-50"
                          >
                            View PDF
                          </button>
                        </div>
                      )}
                    </div>
                  </div>
                  </article>
                ))}
              </div>
            )}
          </section>
        )}
      </div>
      {paymentOrder && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-black/50 p-4">
          <form onSubmit={handlePaymentLinkSubmit} className="w-full max-w-lg rounded-xl border border-[var(--ch-border)] bg-[var(--ch-surface)] p-5 shadow-xl">
            <h2 className="text-lg font-semibold">Create Plooto funds request</h2>
            <p className="mt-1 text-sm text-[var(--ch-text-muted)]">Create this request manually in Plooto, then paste its payment link. DocuSign will not send until the link is saved.</p>
            <dl className="mt-4 grid gap-2 rounded-lg bg-[var(--ch-page-bg)] p-3 text-sm"><div><dt className="text-[var(--ch-text-muted)]">Amount</dt><dd className="font-semibold">{money(orderTotal(paymentOrder))}</dd></div><div><dt className="text-[var(--ch-text-muted)]">Customer</dt><dd>{paymentOrder.client_name}</dd></div><div><dt className="text-[var(--ch-text-muted)]">Property</dt><dd>{paymentOrder.address}</dd></div></dl>
            <label className="mt-4 block text-sm font-medium">Plooto payment link<input required type="url" value={paymentLink} onChange={event => setPaymentLink(event.target.value)} placeholder="https://…" className="mt-1 w-full rounded-lg border border-[var(--ch-border)] bg-[var(--ch-page-bg)] px-3 py-2"/></label>
            {paymentOrder.qb_invoice_status === "synced_error" && <div className="mt-3 rounded-lg bg-[var(--ch-error-bg)] p-3 text-xs text-[var(--ch-error-text)]"><p>{paymentOrder.qb_sync_error || "QuickBooks sync failed."}</p><div className="mt-2 flex gap-3"><button type="button" onClick={() => void retryChangeOrderQbo(paymentOrder.id).then(result => setPaymentOrder(result)).catch(reason => setError(reason instanceof Error ? reason.message : "QBO retry failed"))} className="font-semibold underline">Retry QuickBooks sync</button><button type="button" onClick={() => { const customer = window.prompt("QuickBooks parent customer ID", paymentOrder.qb_customer_id || ""); const project = window.prompt("QuickBooks project/sub-customer ID", paymentOrder.qb_project_id || ""); if (customer && project) void setChangeOrderQboMapping(paymentOrder.id, customer, project).then(result => setPaymentOrder(result)).catch(reason => setError(reason instanceof Error ? reason.message : "QBO mapping failed")); }} className="font-semibold underline">Set IDs manually</button></div></div>}
            <div className="mt-5 flex justify-end gap-2"><button type="button" onClick={() => setPaymentOrder(null)} className="rounded-lg border border-[var(--ch-border)] px-3 py-2 text-sm">Close</button><button disabled={busyOrderId === paymentOrder.id} className="rounded-lg bg-[var(--ch-accent)] px-4 py-2 text-sm font-semibold text-[var(--ch-accent-text)] disabled:opacity-50">Save link &amp; send to DocuSign</button></div>
          </form>
        </div>
      )}
    </main>
  );
}
