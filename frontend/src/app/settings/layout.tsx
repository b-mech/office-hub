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
    <main className="min-h-screen bg-[#0f1117] text-white">
      <div className="flex min-h-screen">
        <aside className="w-60 shrink-0 border-r border-white/10 bg-white/[0.03] px-4 py-6">
          <p className="px-3 text-xs font-semibold uppercase tracking-[0.24em] text-white/35">
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
                      ? "border border-[#FAC775]/35 bg-[#FAC775]/15 text-[#FAC775]"
                      : "border border-transparent text-white/55 hover:bg-white/5 hover:text-white"
                  }`}
                >
                  {item.label}
                </Link>
              );
            })}
          </nav>
        </aside>

        <section className="min-w-0 flex-1">
          <div className="border-b border-white/10 px-8 py-5 text-sm text-white/45">
            <span>Settings</span>
            <span className="px-2 text-white/25">&gt;</span>
            <span className="text-[#FAC775]">{current?.label || "Imports"}</span>
          </div>
          {children}
        </section>
      </div>
    </main>
  );
}
