"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const SETTINGS_NAV = [
  { href: "/settings/imports", label: "Imports" },
  { href: "/settings/users", label: "Users" },
];

export default function SettingsLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const current = SETTINGS_NAV.find((item) => pathname.startsWith(item.href));

  return (
    <main className="min-h-screen bg-[var(--ch-page-bg)] text-[var(--ch-text-primary)]">
      <div className="flex min-h-screen">
        <aside className="w-60 shrink-0 border-r border-[var(--ch-border)] bg-[var(--ch-surface)] px-4 py-6">
          <p className="px-3 text-xs font-semibold uppercase tracking-[0.24em] text-[var(--ch-text-muted)]">
            Settings
          </p>
          <nav className="mt-5 flex flex-col gap-1">
            {SETTINGS_NAV.map((item) => {
              const active = pathname.startsWith(item.href);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={`rounded-lg px-3 py-2 text-sm font-medium transition ${
                    active
                      ? "border border-[var(--ch-accent)] bg-[var(--ch-accent-soft)] text-[var(--ch-accent)]"
                      : "border border-transparent text-[var(--ch-text-secondary)] hover:bg-[var(--ch-surface-hover)] hover:text-[var(--ch-text-primary)]"
                  }`}
                >
                  {item.label}
                </Link>
              );
            })}
          </nav>
        </aside>

        <section className="min-w-0 flex-1">
          <div className="border-b border-[var(--ch-border)] px-8 py-5 text-sm text-[var(--ch-text-muted)]">
            <span>Settings</span>
            <span className="px-2 text-[var(--ch-text-muted)]">&gt;</span>
            <span className="text-[var(--ch-accent)]">{current?.label || "Imports"}</span>
          </div>
          {children}
        </section>
      </div>
    </main>
  );
}
