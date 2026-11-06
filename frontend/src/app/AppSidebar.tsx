"use client";

import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Cog, LogIn, LogOut } from "lucide-react";
import { useAuth } from "./auth-context";
import { isActive, visibleSections } from "./navigation";
import { switchOrg, useWorkspaceContext } from "./useWorkspaceContext";

const linkClass = "rounded-lg px-3 py-2 text-sm text-[var(--ch-sidebar-text-secondary)] transition hover:bg-[var(--ch-sidebar-hover)] hover:text-[var(--ch-sidebar-text-primary)]";
const subLinkClass = "ml-3 rounded-lg border-l border-[var(--ch-sidebar-border)] px-3 py-1.5 text-xs text-[var(--ch-sidebar-text-muted)] transition hover:bg-[var(--ch-sidebar-hover)] hover:text-[var(--ch-sidebar-text-primary)]";
const activeClass = "bg-[var(--ch-sidebar-hover)] text-[var(--ch-sidebar-text-primary)]";

export default function AppSidebar({ fallbackUserName }: { fallbackUserName: string }) {
  const pathname = usePathname();
  const { context, error } = useWorkspaceContext();
  const { session, signOutAndLeave } = useAuth();
  const sections = visibleSections(context?.capabilities ?? null);
  const userName = context?.actor.full_name || fallbackUserName;
  const canSwitch = Boolean(context && context.available_orgs.length > 1);

  return (
    <aside className="hidden w-56 shrink-0 flex-col border-r border-[var(--ch-sidebar-border)] bg-[var(--ch-sidebar-bg)] px-4 py-5 lg:flex">
      <Link href="/" className="flex items-center gap-2">
        <Image src="/favicon.png" alt="Office Hub" width={24} height={24} />
        <span className="text-sm font-semibold text-[var(--ch-sidebar-text-primary)]">Office Hub</span>
      </Link>
      {context ? (
        canSwitch ? (
          <select
            aria-label="Organization"
            value={context.org.slug}
            onChange={(event) => switchOrg(event.target.value)}
            className="mt-4 w-full rounded-lg border border-[var(--ch-sidebar-border)] bg-[var(--ch-sidebar-bg)] px-2 py-1.5 text-xs text-[var(--ch-sidebar-text-secondary)]"
          >
            {context.available_orgs.map((org) => (
              <option key={org.id} value={org.slug}>{org.name}</option>
            ))}
          </select>
        ) : (
          <p className="mt-4 truncate px-1 text-xs text-[var(--ch-sidebar-text-muted)]">{context.org.name}</p>
        )
      ) : null}
      <nav className="mt-6 flex flex-1 flex-col gap-1 overflow-y-auto">
        {sections.map((section, index) => (
          <div key={section.label || index} className="flex flex-col gap-1">
            {section.label ? (
              <p className="mt-3 px-3 text-[10px] font-semibold uppercase tracking-[0.2em] text-[var(--ch-sidebar-text-muted)]">{section.label}</p>
            ) : null}
            {section.links.map((link) => (
              <Link
                key={link.href}
                href={link.href}
                className={`${section.label ? subLinkClass : linkClass} ${isActive(pathname, link.href) ? activeClass : ""}`}
              >
                {link.label}
              </Link>
            ))}
          </div>
        ))}
        {error ? <p className="mt-3 px-3 text-xs text-[var(--ch-sidebar-text-muted)]">{error}</p> : null}
      </nav>
      <div className="border-t border-[var(--ch-sidebar-border)] pt-3">
        <Link
          href={context?.capabilities.settings ? "/settings" : "/"}
          className="flex items-center gap-3 rounded-lg px-2 py-2 text-[var(--ch-sidebar-text-secondary)] transition hover:bg-[var(--ch-sidebar-hover)] hover:text-[var(--ch-sidebar-text-primary)]"
        >
          <span className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-[var(--ch-sidebar-user-bg)] text-xs font-bold text-[var(--ch-sidebar-text-primary)]">
            {userName.slice(0, 1).toUpperCase()}
          </span>
          <span className="min-w-0 flex-1 truncate text-sm font-medium">{userName}</span>
          <Cog size={15} strokeWidth={2} aria-hidden="true" />
        </Link>
        {session?.authenticated ? (
          <button type="button" onClick={() => void signOutAndLeave()}
            className="mt-1 flex w-full items-center gap-3 rounded-lg px-2 py-1.5 text-xs text-[var(--ch-sidebar-text-muted)] transition hover:bg-[var(--ch-sidebar-hover)] hover:text-[var(--ch-sidebar-text-primary)]">
            <LogOut size={14} strokeWidth={2} aria-hidden="true" /> Sign out
          </button>
        ) : session && !session.auth_enforced ? (
          <Link href="/login"
            className="mt-1 flex w-full items-center gap-3 rounded-lg px-2 py-1.5 text-xs text-[var(--ch-sidebar-text-muted)] transition hover:bg-[var(--ch-sidebar-hover)] hover:text-[var(--ch-sidebar-text-primary)]">
            <LogIn size={14} strokeWidth={2} aria-hidden="true" /> Sign in
          </Link>
        ) : null}
      </div>
    </aside>
  );
}
