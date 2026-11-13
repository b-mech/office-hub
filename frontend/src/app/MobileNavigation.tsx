"use client";

import Image from "next/image";
import Link from "next/link";
import { Menu, X } from "lucide-react";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { useAuth } from "./auth-context";
import { NAV } from "./AppSidebar";
import { activeNavHref } from "@/lib/rentals-ux";

const NAV_HREFS = NAV.map((item) => item.href);

export default function MobileNavigation() {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const { session, signOutAndLeave } = useAuth();
  const activeHref = activeNavHref(pathname, NAV_HREFS);

  return (
    <>
      <header className="sticky top-0 z-40 flex h-14 items-center justify-between border-b border-[var(--ch-sidebar-border)] bg-[var(--ch-sidebar-bg)] px-4 lg:hidden">
        <Link href="/documents" className="flex items-center gap-2">
          <Image src="/favicon.png" alt="Office Hub" width={26} height={26} />
          <span className="text-sm font-semibold text-[var(--ch-sidebar-text-primary)]">Office Hub</span>
        </Link>
        <button
          type="button"
          onClick={() => setOpen((current) => !current)}
          aria-label={open ? "Close module menu" : "Open module menu"}
          aria-expanded={open}
          className="grid h-10 w-10 place-items-center rounded-lg text-[var(--ch-sidebar-text-primary)] hover:bg-[var(--ch-sidebar-hover)]"
        >
          {open ? <X size={24} /> : <Menu size={24} />}
        </button>
      </header>

      {open ? (
        <div className="fixed inset-x-0 bottom-0 top-14 z-50 lg:hidden">
          <button
            type="button"
            aria-label="Close module menu"
            className="absolute inset-0 bg-black/40"
            onClick={() => setOpen(false)}
          />
          <nav aria-label="Modules" className="absolute right-0 top-0 h-full w-[min(82vw,20rem)] overflow-y-auto border-l border-[var(--ch-sidebar-border)] bg-[var(--ch-sidebar-bg)] p-4 shadow-2xl">
            <p className="px-3 pb-3 pt-1 text-xs font-semibold uppercase tracking-[0.2em] text-[var(--ch-sidebar-text-muted)]">
              Modules
            </p>
            {NAV.map(({ label, href, parent }) => {
              const active = href === activeHref;
              return (
                <Link
                  key={href}
                  href={href}
                  onClick={() => setOpen(false)}
                  aria-current={active ? "page" : undefined}
                  className={`mb-1 block rounded-lg px-3 py-3 text-sm font-medium transition ${parent ? "ml-3 " : ""}${
                    active
                      ? "bg-[var(--ch-sidebar-hover)] text-[var(--ch-sidebar-text-primary)]"
                      : "text-[var(--ch-sidebar-text-secondary)] hover:bg-[var(--ch-sidebar-hover)] hover:text-[var(--ch-sidebar-text-primary)]"
                  }`}
                >
                  {label}
                </Link>
              );
            })}
            <div className="mt-4 border-t border-[var(--ch-sidebar-border)] pt-4">
              <Link
                href="/settings"
                onClick={() => setOpen(false)}
                className="block rounded-lg px-3 py-3 text-sm font-medium text-[var(--ch-sidebar-text-secondary)] hover:bg-[var(--ch-sidebar-hover)] hover:text-[var(--ch-sidebar-text-primary)]"
              >
                Settings
              </Link>
            </div>
            {session?.authenticated ? (
              <button type="button" onClick={() => { setOpen(false); void signOutAndLeave(); }}
                className="mt-2 block w-full rounded-lg px-3 py-3 text-left text-sm font-medium text-[var(--ch-sidebar-text-secondary)] hover:bg-[var(--ch-sidebar-hover)] hover:text-[var(--ch-sidebar-text-primary)]">
                Sign out
              </button>
            ) : session && !session.auth_enforced ? (
              <Link href="/login" onClick={() => setOpen(false)}
                className="mt-2 block rounded-lg px-3 py-3 text-sm font-medium text-[var(--ch-sidebar-text-secondary)] hover:bg-[var(--ch-sidebar-hover)] hover:text-[var(--ch-sidebar-text-primary)]">
                Sign in
              </Link>
            ) : null}
          </nav>
        </div>
      ) : null}
    </>
  );
}
