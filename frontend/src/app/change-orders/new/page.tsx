"use client";

import { Suspense } from "react";
import { ChangeOrderForm } from "@/components/change-orders/ChangeOrderForm";

export default function NewChangeOrderPage() {
  return (
    <Suspense
      fallback={
        <main className="min-h-screen bg-[var(--ch-page-bg)] px-6 py-8 text-[var(--ch-text-primary)]">
          <div className="mx-auto max-w-6xl text-sm text-[var(--ch-text-muted)]">
            Loading change order...
          </div>
        </main>
      }
    >
      <ChangeOrderForm />
    </Suspense>
  );
}
