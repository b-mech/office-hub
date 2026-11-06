"use client";

import Image from "next/image";
import Link from "next/link";
import { Menu, X } from "lucide-react";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { isActive, visibleSections } from "./navigation";
import { switchOrg, useWorkspaceContext } from "./useWorkspaceContext";
import { useAuth } from "./auth-context";



export default function MobileNavigation() {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const { context } = useWorkspaceContext();
  const { session, signOutAndLeave } = useAuth();
  const sections = visibleSections(context?.capabilities ?? null);

  return (
    <>
      <header className="sticky top-0 z-40 flex h-14 items-center justify-between border-b border-[var(--ch-sidebar-border)] bg-[var(--ch-sidebar-bg)] px-4 lg:hidden">
        <Link href="/" className="flex items-center gap-2">
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
          <nav className="absolute right-0 top-0 h-full w-[min(82vw,20rem)] overflow-y-auto border-l border-[var(--ch-sidebar-border)] bg-[var(--ch-sidebar-bg)] p-4 shadow-2xl">
            <p className="px-3 pb-3 pt-1 text-xs font-semibold uppercase tracking-[0.2em] text-[var(--ch-sidebar-text-muted)]">
              Modules
            </p>
            {context && context.available_orgs.length > 1 ? (
              <select
                aria-label="Organization"
                value={context.org.slug}
                onChange={(event) => switchOrg(event.target.value)}
                className="mb-3 w-full rounded-lg border border-[var(--ch-sidebar-border)] bg-[var(--ch-sidebar-bg)] px-3 py-2 text-sm text-[var(--ch-sidebar-text-secondary)]"
              >
                {context.available_orgs.map((org) => (
                  <option key={org.id} value={org.slug}>{org.name}</option>
                ))}
              </select>
            ) : null}
            {sections.map((section, index) => (
              <div key={section.label || index}>
                {section.label ? (
                  <p className="px-3 pb-1 pt-3 text-[10px] font-semibold uppercase tracking-[0.2em] text-[var(--ch-sidebar-text-muted)]">{section.label}</p>
                ) : null}
                {section.links.map(({ label, href }) => {
                  const active = isActive(pathname, href);
                  return (
                    <Link
                      key={href}
                      href={href}
                      onClick={() => setOpen(false)}
                      className={`mb-1 block rounded-lg px-3 py-3 text-sm font-medium transition ${
                        active
                          ? "bg-[var(--ch-sidebar-hover)] text-[var(--ch-sidebar-text-primary)]"
                          : "text-[var(--ch-sidebar-text-secondary)] hover:bg-[var(--ch-sidebar-hover)] hover:text-[var(--ch-sidebar-text-primary)]"
                      }`}
                    >
                      {label}
                    </Link>
                  );
                })}
              </div>
            ))}
            {context?.capabilities.settings ? <div className="mt-4 border-t border-[var(--ch-sidebar-border)] pt-4">
              <Link
                href="/settings"
                onClick={() => setOpen(false)}
                className="block rounded-lg px-3 py-3 text-sm font-medium text-[var(--ch-sidebar-text-secondary)] hover:bg-[var(--ch-sidebar-hover)] hover:text-[var(--ch-sidebar-text-primary)]"
              >
                Settings
              </Link>
            </div> : null}
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
