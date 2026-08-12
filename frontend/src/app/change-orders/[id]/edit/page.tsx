"use client";

import { Suspense, useEffect, useState } from "react";
import { useParams } from "next/navigation";

import { ChangeOrderForm } from "@/app/change-orders/new/page";
import { getChangeOrder, type ChangeOrderDraft } from "@/lib/api/change-orders";


export default function EditChangeOrderPage() {
  const params = useParams<{ id: string }>();
  const changeOrderId = params.id;
  const [draft, setDraft] = useState<ChangeOrderDraft | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    getChangeOrder(changeOrderId)
      .then((order) => {
        if (!active) return;
        setDraft({
          address: order.address,
          client_name: order.client_name,
          customer_email: order.customer_email || "",
          co_number: order.co_number || "",
          date: order.date || "",
          line_items: order.line_items,
          payment_method: order.payment_method,
          notes: order.notes || "",
        });
      })
      .catch((loadError) => {
        if (active) setError(loadError instanceof Error ? loadError.message : "Could not load change order.");
      });
    return () => {
      active = false;
    };
  }, [changeOrderId]);

  if (error) {
    return (
      <main className="min-h-screen bg-[var(--ch-page-bg)] px-6 py-8 text-[var(--ch-text-primary)]">
        <div className="mx-auto max-w-6xl rounded-xl border border-[var(--ch-error-border)] bg-[var(--ch-error-bg)] px-4 py-3 text-sm text-[var(--ch-error-text)]">
          {error}
        </div>
      </main>
    );
  }

  if (!draft) {
    return (
      <main className="min-h-screen bg-[var(--ch-page-bg)] px-6 py-8 text-[var(--ch-text-primary)]">
        <div className="mx-auto max-w-6xl text-sm text-[var(--ch-text-muted)]">Loading change order...</div>
      </main>
    );
  }

  return (
    <Suspense fallback={null}>
      <ChangeOrderForm changeOrderId={changeOrderId} initialDraft={draft} />
    </Suspense>
  );
}
