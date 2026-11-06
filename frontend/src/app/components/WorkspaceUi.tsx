import Link from "next/link";
import type { ReactNode } from "react";

export function formatDate(value?: string | null): string {
  if (!value) return "—";
  const date = /^\d{4}-\d{2}-\d{2}$/.test(value) ? new Date(`${value}T00:00:00`) : new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleDateString("en-CA", { year: "numeric", month: "short", day: "numeric" });
}

export function PageShell({ title, subtitle, actions, children }: { title: string; subtitle?: string; actions?: ReactNode; children: ReactNode }) {
  return (
    <main className="min-h-screen bg-[var(--ch-page-bg)] px-6 py-8 text-[var(--ch-text-primary)] lg:px-10">
      <div className="mx-auto max-w-6xl">
        <header className="mb-6 flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
            {subtitle ? <p className="mt-1 text-sm text-[var(--ch-text-muted)]">{subtitle}</p> : null}
          </div>
          {actions}
        </header>
        {children}
      </div>
    </main>
  );
}

export function Card({ title, action, children, className = "" }: { title: string; action?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`rounded-xl border border-[var(--ch-border)] bg-[var(--ch-surface)] p-4 ${className}`}>
      <div className="mb-3 flex items-center justify-between gap-2">
        <h2 className="text-xs font-semibold uppercase tracking-widest text-[var(--ch-text-muted)]">{title}</h2>
        {action}
      </div>
      {children}
    </section>
  );
}

/** A metric tile. `null` means the data is not stored, shown as "Not tracked" rather than 0. */
export function Stat({ label, value, href, hint }: { label: string; value: number | string | null; href?: string; hint?: string }) {
  const body = (
    <>
      <p className="text-xs text-[var(--ch-text-muted)]">{label}</p>
      <p className={`mt-1 font-semibold ${value === null ? "text-sm text-[var(--ch-text-muted)]" : "text-2xl"}`}>
        {value === null ? "Not tracked" : value}
      </p>
      {hint ? <p className="mt-1 text-xs text-[var(--ch-text-muted)]">{hint}</p> : null}
    </>
  );
  const className = "block rounded-xl border border-[var(--ch-border)] bg-[var(--ch-surface)] p-4";
  return href ? <Link href={href} className={`${className} hover:border-[var(--ch-border-strong)]`}>{body}</Link> : <div className={className}>{body}</div>;
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="rounded-lg bg-[var(--ch-surface-muted)] p-4 text-center text-sm text-[var(--ch-text-muted)]">{children}</p>;
}

export function ErrorNote({ message }: { message: string | null }) {
  return message ? <p className="mb-4 rounded-md bg-[var(--ch-error-bg)] p-3 text-sm text-[var(--ch-error-text)]">{message}</p> : null;
}

export const fieldClass = "rounded-md border border-[var(--ch-border)] bg-[var(--ch-surface)] px-3 py-2 text-sm";
export const primaryButton = "rounded-md bg-[var(--ch-accent)] px-3 py-2 text-xs font-semibold text-[var(--ch-accent-text)] disabled:opacity-50";
export const secondaryButton = "rounded-md border border-[var(--ch-border)] px-3 py-2 text-xs disabled:opacity-50";
