"use client";

import { useState } from "react";

import {
  downloadChangeOrderPdf,
  type ChangeOrder,
} from "@/lib/api/change-orders";

type Stage = {
  name: string;
  status: ChangeOrder["status"];
  color: string;
  description: string;
};

const stages: Stage[] = [
  {
    name: "AWAITING PAYMENT LINK",
    status: "awaiting_payment_link",
    color: "var(--ch-warning-border)",
    description: "Create Plooto request and paste its link",
  },
  {
    name: "EXTRACTED",
    status: "draft",
    color: "var(--ch-status-draft-border)",
    description: "Draft created from email",
  },
  {
    name: "PENDING SIGNATURE",
    status: "sent",
    color: "var(--ch-status-sent-border)",
    description: "Awaiting client signature",
  },
  {
    name: "SIGNED",
    status: "signed",
    color: "var(--ch-status-signed-border)",
    description: "Signed and returned",
  },
  {
    name: "COMPLETE",
    status: "complete",
    color: "var(--ch-status-complete-border)",
    description: "Paid or added to mortgage",
  },
];

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

function pdfFilename(order: ChangeOrder) {
  const address = order.address.trim() || order.co_number || "Change order";
  return `${address}.pdf`;
}

function stageIndex(status: ChangeOrder["status"]) {
  return stages.findIndex((stage) => stage.status === status);
}

type PipelineViewProps = {
  changeOrders: ChangeOrder[];
  onStatusChange: (id: string, newStatus: ChangeOrder["status"]) => Promise<void>;
  onSendSignature: (order: ChangeOrder) => Promise<void>;
};

export default function PipelineView({ changeOrders, onStatusChange, onSendSignature }: PipelineViewProps) {
  const [openMenuId, setOpenMenuId] = useState<string | null>(null);
  const [busyOrderId, setBusyOrderId] = useState<string | null>(null);

  async function handleViewPdf(order: ChangeOrder) {
    setBusyOrderId(order.id);
    try {
      const blob = await downloadChangeOrderPdf(order.id);
      const objectUrl = URL.createObjectURL(blob);
      window.open(objectUrl, "_blank", "noopener,noreferrer");
      window.setTimeout(() => URL.revokeObjectURL(objectUrl), 30000);
      setOpenMenuId(null);
    } catch {
      setOpenMenuId(order.id);
    } finally {
      setBusyOrderId(null);
    }
  }

  async function handleMove(order: ChangeOrder, status: ChangeOrder["status"]) {
    setBusyOrderId(order.id);
    try {
      await onStatusChange(order.id, status);
      setOpenMenuId(null);
    } catch {
      setOpenMenuId(order.id);
    } finally {
      setBusyOrderId(null);
    }
  }

  async function handleSendSignature(order: ChangeOrder) {
    setBusyOrderId(order.id);
    try {
      await onSendSignature(order);
      setOpenMenuId(null);
    } catch {
      setOpenMenuId(order.id);
    } finally {
      setBusyOrderId(null);
    }
  }

  return (
    <section className="grid min-h-[560px] gap-4 xl:grid-cols-5">
      {stages.map((stage) => {
        const stageOrders = changeOrders.filter((order) => order.status === stage.status);
        return (
          <div
            key={stage.status}
            className="flex min-h-[360px] flex-col rounded-xl border border-[var(--ch-border)] bg-[var(--ch-surface)]"
            style={{ borderTop: `3px solid ${stage.color}` }}
          >
            <div className="border-b border-[var(--ch-border)] px-4 py-3">
              <div className="flex items-center justify-between gap-3">
                <h2 className="text-[12pt] font-bold" style={{ color: stage.color }}>
                  {stage.name}
                </h2>
                <span className="rounded-full border border-[var(--ch-border)] bg-[var(--ch-surface)] px-2 py-0.5 text-xs font-semibold text-[var(--ch-text-secondary)]">
                  {stageOrders.length}
                </span>
              </div>
              <p className="mt-1 text-xs text-[var(--ch-text-muted)]">{stage.description}</p>
            </div>

            <div className="flex-1 space-y-3 overflow-y-auto p-3">
              {stageOrders.length === 0 ? (
                <div className="grid min-h-48 place-items-center text-sm text-[var(--ch-text-muted)]">
                  No change orders
                </div>
              ) : (
                stageOrders.map((order) => {
                  const currentStageIndex = stageIndex(order.status);
                  const nextStage = stages[currentStageIndex + 1];
                  const previousStage = stages[currentStageIndex - 1];
                  return (
                    <article
                      key={order.id}
                      className="rounded-xl border border-[var(--ch-border)] bg-[var(--ch-surface)] p-3 transition hover:-translate-y-px hover:shadow-md"
                      style={{ borderTop: `2px solid ${stage.color}` }}
                    >
                      <div className="flex min-w-0 items-center gap-2">
                        <span
                          className="h-2.5 w-2.5 shrink-0 rounded-full"
                          style={{ backgroundColor: stage.color }}
                        />
                        <p className="truncate text-[13pt] font-semibold text-[var(--ch-text-primary)]">
                          {pdfFilename(order)}
                        </p>
                      </div>

                      <p className="mt-5 text-[14pt] font-bold text-[var(--ch-accent)]">
                        {money(orderTotal(order))}
                      </p>
                      {!order.customer_email && (
                        <span className="mt-2 inline-flex rounded-full border border-[var(--ch-warning-border)] bg-[var(--ch-warning-bg)] px-2 py-0.5 text-[10px] font-semibold text-[var(--ch-warning-text)]">
                          needs email
                        </span>
                      )}
                      <div className="mt-2 flex flex-wrap gap-1">
                        <span className="rounded-full border border-[var(--ch-border)] px-2 py-0.5 text-[10px]">{order.status === "signed" || order.status === "complete" ? "Signed" : "Not signed"}</span>
                        <span className={`rounded-full border px-2 py-0.5 text-[10px] ${order.qb_invoice_status === "paid" ? "border-[var(--ch-success-border)] bg-[var(--ch-success-bg)] text-[var(--ch-success-text)]" : "border-[var(--ch-border)]"}`}>{order.qb_invoice_status === "paid" ? "Paid" : "Not paid"}</span>
                      </div>

                      <div className="relative mt-1 flex justify-end">
                        <button
                          type="button"
                          onClick={() => setOpenMenuId(openMenuId === order.id ? null : order.id)}
                          disabled={busyOrderId === order.id}
                          aria-label={`Actions for ${pdfFilename(order)}`}
                          className="rounded-md px-2 py-1 text-lg leading-none text-[var(--ch-text-secondary)] hover:bg-[var(--ch-surface)] hover:text-[var(--ch-text-primary)] disabled:cursor-not-allowed disabled:opacity-50"
                        >
                          ...
                        </button>
                        {openMenuId === order.id && (
                          <div className="absolute right-0 top-8 z-20 w-48 rounded-lg border border-[var(--ch-border)] bg-[var(--ch-surface)] p-1 shadow-lg">
                            <button
                              type="button"
                              onClick={() => void handleViewPdf(order)}
                              disabled={busyOrderId === order.id}
                              className="block w-full rounded-md px-3 py-2 text-left text-sm text-[var(--ch-text-primary)] hover:bg-[var(--ch-surface)] disabled:cursor-not-allowed disabled:opacity-50"
                            >
                              View PDF
                            </button>
                            {order.status === "draft" && (
                              <button
                                type="button"
                                onClick={() => void handleSendSignature(order)}
                                disabled={busyOrderId === order.id}
                                className="block w-full rounded-md px-3 py-2 text-left text-sm text-[var(--ch-text-primary)] hover:bg-[var(--ch-surface)] disabled:cursor-not-allowed disabled:opacity-50"
                              >
                                Send for Signature
                              </button>
                            )}
                            {nextStage && !["draft", "awaiting_payment_link"].includes(order.status) && (
                              <button
                                type="button"
                                onClick={() => void handleMove(order, nextStage.status)}
                                disabled={busyOrderId === order.id}
                                className="block w-full rounded-md px-3 py-2 text-left text-sm text-[var(--ch-text-primary)] hover:bg-[var(--ch-surface)] disabled:cursor-not-allowed disabled:opacity-50"
                              >
                                Move to {nextStage.name}
                              </button>
                            )}
                            {previousStage && order.status !== "sent" && (
                              <button
                                type="button"
                                onClick={() => void handleMove(order, previousStage.status)}
                                disabled={busyOrderId === order.id}
                                className="block w-full rounded-md px-3 py-2 text-left text-sm text-[var(--ch-text-primary)] hover:bg-[var(--ch-surface)] disabled:cursor-not-allowed disabled:opacity-50"
                              >
                                Move to {previousStage.name}
                              </button>
                            )}
                          </div>
                        )}
                      </div>
                    </article>
                  );
                })
              )}
            </div>
          </div>
        );
      })}
    </section>
  );
}
