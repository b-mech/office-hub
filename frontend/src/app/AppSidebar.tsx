"use client";

import Image from "next/image";
import Link from "next/link";
import { Cog, LogIn, LogOut } from "lucide-react";
import { usePathname } from "next/navigation";
import { useAuth } from "./auth-context";
import { activeNavHref } from "@/lib/rentals-ux";

// Module list; `parent` marks a sub-link shown indented under its section.
export const NAV: readonly { label: string; href: string; parent?: string }[] = [
  { label: "Documents", href: "/documents" },
  { label: "Lots", href: "/lots" },
  { label: "OTP Timeline", href: "/lots/timeline", parent: "/lots" },
  { label: "Projects", href: "/projects" },
  { label: "Change Orders", href: "/projects/change-orders", parent: "/projects" },
  { label: "Costbook", href: "/costbook" },
  { label: "Financing", href: "/financing" },
  { label: "Presales", href: "/financing/presales", parent: "/financing" },
  { label: "Contractors", href: "/contractors" },
  { label: "Lenders", href: "/financing/lenders", parent: "/contractors" },
  { label: "Rentals", href: "/rentals" },
  { label: "Lease Import", href: "/rentals/lease-import", parent: "/rentals" },
  { label: "Rental Units", href: "/rentals/units", parent: "/rentals" },
  { label: "Maintenance", href: "/rentals/maintenance", parent: "/rentals" },
  { label: "Inspections", href: "/rentals/inspections", parent: "/rentals" },
  { label: "Inspection Reports", href: "/rentals/reports", parent: "/rentals" },
];
const NAV_HREFS = NAV.map((item) => item.href);

// Staging sidebar: the static module list from the pre-workspace layout, plus
// the PR #3 Sign in / Sign out control.
export default function AppSidebar({ fallbackUserName }: { fallbackUserName: string }) {
  const { session, signOutAndLeave } = useAuth();
  const userName = session?.user?.full_name || fallbackUserName;
  const pathname = usePathname();
  // The deepest matching entry is the current page; its parent section is highlighted too.
  const active = activeNavHref(pathname, NAV_HREFS);
  const activeSection = NAV.find((item) => item.href === active)?.parent ?? active;
  return (
    <aside className="hidden w-56 shrink-0 flex-col border-r border-[var(--ch-sidebar-border)] bg-[var(--ch-sidebar-bg)] px-4 py-5 lg:flex">
      <Link href="/documents" className="flex items-center gap-2">
        <Image src="/favicon.png" alt="Office Hub" width={24} height={24} />
        <span className="text-sm font-semibold text-[var(--ch-sidebar-text-primary)]">Office Hub</span>
      </Link>
      <nav aria-label="Modules" className="mt-8 flex flex-1 flex-col gap-1">
        {NAV.map(({ label, href, parent }) => {
          const current = href === active;
          const section = !parent && activeSection === href;
          const base = parent
            ? "ml-3 rounded-lg border-l px-3 py-1.5 text-xs transition hover:bg-[var(--ch-sidebar-hover)] hover:text-[var(--ch-sidebar-text-primary)]"
            : "rounded-lg px-3 py-2 text-sm transition hover:bg-[var(--ch-sidebar-hover)] hover:text-[var(--ch-sidebar-text-primary)]";
          const tone = current
            ? `bg-[var(--ch-sidebar-hover)] font-semibold text-[var(--ch-sidebar-text-primary)] ${parent ? "border-[var(--ch-sidebar-text-primary)]" : ""}`
            : section
              ? "font-semibold text-[var(--ch-sidebar-text-primary)]"
              : parent
                ? "border-[var(--ch-sidebar-border)] text-[var(--ch-sidebar-text-muted)]"
                : "text-[var(--ch-sidebar-text-secondary)]";
          return <Link key={href} href={href} aria-current={current ? "page" : undefined} className={`${base} ${tone}`}>{label}</Link>;
        })}
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
