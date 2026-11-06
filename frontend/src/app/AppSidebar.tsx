"use client";

import Image from "next/image";
import Link from "next/link";
import { Cog, LogIn, LogOut } from "lucide-react";
import { useAuth } from "./auth-context";

// Staging sidebar: the static module list from the pre-workspace layout, plus
// the PR #3 Sign in / Sign out control.
export default function AppSidebar({ fallbackUserName }: { fallbackUserName: string }) {
  const { session, signOutAndLeave } = useAuth();
  const userName = session?.user?.full_name || fallbackUserName;
  return (
    <aside className="hidden w-56 shrink-0 flex-col border-r border-[var(--ch-sidebar-border)] bg-[var(--ch-sidebar-bg)] px-4 py-5 lg:flex">
      <Link href="/documents" className="flex items-center gap-2">
        <Image src="/favicon.png" alt="Office Hub" width={24} height={24} />
        <span className="text-sm font-semibold text-[var(--ch-sidebar-text-primary)]">Office Hub</span>
      </Link>
      <nav className="mt-8 flex flex-1 flex-col gap-1">
        <Link
          href="/documents"
          className="rounded-lg px-3 py-2 text-sm text-[var(--ch-sidebar-text-secondary)] transition hover:bg-[var(--ch-sidebar-hover)] hover:text-[var(--ch-sidebar-text-primary)]"
        >
          Documents
        </Link>
        <Link
          href="/lots"
          className="rounded-lg px-3 py-2 text-sm text-[var(--ch-sidebar-text-secondary)] transition hover:bg-[var(--ch-sidebar-hover)] hover:text-[var(--ch-sidebar-text-primary)]"
        >
          Lots
        </Link>
        <Link
          href="/lots/timeline"
          className="ml-3 rounded-lg border-l border-[var(--ch-sidebar-border)] px-3 py-1.5 text-xs text-[var(--ch-sidebar-text-muted)] transition hover:bg-[var(--ch-sidebar-hover)] hover:text-[var(--ch-sidebar-text-primary)]"
        >
          OTP Timeline
        </Link>
        <Link
          href="/projects"
          className="rounded-lg px-3 py-2 text-sm text-[var(--ch-sidebar-text-secondary)] transition hover:bg-[var(--ch-sidebar-hover)] hover:text-[var(--ch-sidebar-text-primary)]"
        >
          Projects
        </Link>
        <Link
          href="/projects/change-orders"
          className="ml-3 rounded-lg border-l border-[var(--ch-sidebar-border)] px-3 py-1.5 text-xs text-[var(--ch-sidebar-text-muted)] transition hover:bg-[var(--ch-sidebar-hover)] hover:text-[var(--ch-sidebar-text-primary)]"
        >
          Change Orders
        </Link>
        <Link
          href="/costbook"
          className="rounded-lg px-3 py-2 text-sm text-[var(--ch-sidebar-text-secondary)] transition hover:bg-[var(--ch-sidebar-hover)] hover:text-[var(--ch-sidebar-text-primary)]"
        >
          Costbook
        </Link>
        <Link
          href="/financing"
          className="rounded-lg px-3 py-2 text-sm text-[var(--ch-sidebar-text-secondary)] transition hover:bg-[var(--ch-sidebar-hover)] hover:text-[var(--ch-sidebar-text-primary)]"
        >
          Financing
        </Link>
        <Link
          href="/financing/presales"
          className="ml-3 rounded-lg border-l border-[var(--ch-sidebar-border)] px-3 py-1.5 text-xs text-[var(--ch-sidebar-text-muted)] transition hover:bg-[var(--ch-sidebar-hover)] hover:text-[var(--ch-sidebar-text-primary)]"
        >
          Presales
        </Link>
        <Link
          href="/contractors"
          className="rounded-lg px-3 py-2 text-sm text-[var(--ch-sidebar-text-secondary)] transition hover:bg-[var(--ch-sidebar-hover)] hover:text-[var(--ch-sidebar-text-primary)]"
        >
          Contractors
        </Link>
        <Link
          href="/financing/lenders"
          className="ml-3 rounded-lg border-l border-[var(--ch-sidebar-border)] px-3 py-1.5 text-xs text-[var(--ch-sidebar-text-muted)] transition hover:bg-[var(--ch-sidebar-hover)] hover:text-[var(--ch-sidebar-text-primary)]"
        >
          Lenders
        </Link>
        <Link
          href="/rentals"
          className="rounded-lg px-3 py-2 text-sm text-[var(--ch-sidebar-text-secondary)] transition hover:bg-[var(--ch-sidebar-hover)] hover:text-[var(--ch-sidebar-text-primary)]"
        >
          Rentals
        </Link>
        <Link
          href="/rentals/lease-import"
          className="ml-3 rounded-lg border-l border-[var(--ch-sidebar-border)] px-3 py-1.5 text-xs text-[var(--ch-sidebar-text-muted)] transition hover:bg-[var(--ch-sidebar-hover)] hover:text-[var(--ch-sidebar-text-primary)]"
        >
          Lease Import
        </Link>
        <Link href="/rentals/units" className="ml-3 rounded-lg border-l border-[var(--ch-sidebar-border)] px-3 py-1.5 text-xs text-[var(--ch-sidebar-text-muted)] transition hover:bg-[var(--ch-sidebar-hover)] hover:text-[var(--ch-sidebar-text-primary)]">Rental Units</Link>
        <Link href="/rentals/maintenance" className="ml-3 rounded-lg border-l border-[var(--ch-sidebar-border)] px-3 py-1.5 text-xs text-[var(--ch-sidebar-text-muted)] transition hover:bg-[var(--ch-sidebar-hover)] hover:text-[var(--ch-sidebar-text-primary)]">Maintenance</Link>
        <Link href="/rentals/inspections" className="ml-3 rounded-lg border-l border-[var(--ch-sidebar-border)] px-3 py-1.5 text-xs text-[var(--ch-sidebar-text-muted)] transition hover:bg-[var(--ch-sidebar-hover)] hover:text-[var(--ch-sidebar-text-primary)]">Inspections</Link>
        <Link href="/rentals/reports" className="ml-3 rounded-lg border-l border-[var(--ch-sidebar-border)] px-3 py-1.5 text-xs text-[var(--ch-sidebar-text-muted)] transition hover:bg-[var(--ch-sidebar-hover)] hover:text-[var(--ch-sidebar-text-primary)]">Inspection Reports</Link>
      </nav>
      <div className="border-t border-[var(--ch-sidebar-border)] pt-3">
        <Link
          href="/settings"
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
