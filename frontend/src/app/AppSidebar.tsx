"use client";

import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { Cog } from "lucide-react";
import { isActive, visibleSections, visibleSettingsMenu } from "./navigation";
import { switchOrg, useWorkspaceContext } from "./useWorkspaceContext";

const linkClass = "rounded-lg px-3 py-2 text-sm text-[var(--ch-sidebar-text-secondary)] transition hover:bg-[var(--ch-sidebar-hover)] hover:text-[var(--ch-sidebar-text-primary)]";
const subLinkClass = "ml-3 rounded-lg border-l border-[var(--ch-sidebar-border)] px-3 py-1.5 text-xs text-[var(--ch-sidebar-text-muted)] transition hover:bg-[var(--ch-sidebar-hover)] hover:text-[var(--ch-sidebar-text-primary)]";
const headerLinkClass = "mt-3 cursor-pointer rounded-lg px-3 py-1.5 text-[10px] font-semibold uppercase tracking-[0.2em] text-[var(--ch-sidebar-text-muted)] transition hover:bg-[var(--ch-sidebar-hover)] hover:text-[var(--ch-sidebar-text-primary)]";
const activeClass = "bg-[var(--ch-sidebar-hover)] text-[var(--ch-sidebar-text-primary)]";

export default function AppSidebar({ fallbackUserName }: { fallbackUserName: string }) {
  const pathname = usePathname();
  const { context, error } = useWorkspaceContext();
  const sections = visibleSections(context?.capabilities ?? null);
  const settingsMenu = visibleSettingsMenu(context?.capabilities ?? null);
  const userName = context?.actor.full_name || fallbackUserName;
  const canSwitch = Boolean(context && context.available_orgs.length > 1);
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!menuOpen) return;
    const onPointer = (event: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) setMenuOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setMenuOpen(false);
    };
    document.addEventListener("mousedown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [menuOpen]);

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
      <nav aria-label="Modules" className="mt-6 flex flex-1 flex-col gap-1 overflow-y-auto">
        {sections.map((section, index) => {
          const headerActive = section.href ? isActive(pathname, section.href) : false;
          return (
            <div key={section.label || index} className="flex flex-col gap-1">
              {section.label && section.href ? (
                <Link
                  href={section.href}
                  aria-label={`${section.label} overview`}
                  aria-current={headerActive ? "page" : undefined}
                  className={`${headerLinkClass} ${headerActive ? activeClass : ""}`}
                >
                  {section.label}
                </Link>
              ) : section.label ? (
                <p className="mt-3 px-3 text-[10px] font-semibold uppercase tracking-[0.2em] text-[var(--ch-sidebar-text-muted)]">{section.label}</p>
              ) : null}
              {section.links.map((link) => {
                const active = isActive(pathname, link.href);
                return (
                  <Link
                    key={link.href}
                    href={link.href}
                    aria-current={active ? "page" : undefined}
                    className={`${section.label ? subLinkClass : linkClass} ${active ? activeClass : ""}`}
                  >
                    {link.label}
                  </Link>
                );
              })}
            </div>
          );
        })}
        {error ? <p className="mt-3 px-3 text-xs text-[var(--ch-sidebar-text-muted)]">{error}</p> : null}
      </nav>
      <div ref={menuRef} className="relative border-t border-[var(--ch-sidebar-border)] pt-3">
        {menuOpen && settingsMenu.length > 0 ? (
          <div
            id="sidebar-settings-menu"
            className="absolute bottom-full left-0 right-0 mb-2 flex flex-col gap-1 rounded-lg border border-[var(--ch-sidebar-border)] bg-[var(--ch-sidebar-bg)] p-1 shadow-lg"
          >
            {settingsMenu.map((link) => {
              const active = isActive(pathname, link.href);
              return (
                <Link
                  key={link.href}
                  href={link.href}
                  aria-current={active ? "page" : undefined}
                  onClick={() => setMenuOpen(false)}
                  className={`${linkClass} ${active ? activeClass : ""}`}
                >
                  {link.label}
                </Link>
              );
            })}
          </div>
        ) : null}
        {settingsMenu.length > 0 ? (
          <button
            type="button"
            onClick={() => setMenuOpen((current) => !current)}
            aria-label="Settings and imports"
            aria-expanded={menuOpen}
            aria-controls={menuOpen ? "sidebar-settings-menu" : undefined}
            className="flex w-full items-center gap-3 rounded-lg px-2 py-2 text-left text-[var(--ch-sidebar-text-secondary)] transition hover:bg-[var(--ch-sidebar-hover)] hover:text-[var(--ch-sidebar-text-primary)]"
          >
            <span className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-[var(--ch-sidebar-user-bg)] text-xs font-bold text-[var(--ch-sidebar-text-primary)]">
              {userName.slice(0, 1).toUpperCase()}
            </span>
            <span className="min-w-0 flex-1 truncate text-sm font-medium">{userName}</span>
            <Cog size={15} strokeWidth={2} aria-hidden="true" />
          </button>
        ) : (
          <div className="flex items-center gap-3 rounded-lg px-2 py-2 text-[var(--ch-sidebar-text-secondary)]">
            <span className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-[var(--ch-sidebar-user-bg)] text-xs font-bold text-[var(--ch-sidebar-text-primary)]">
              {userName.slice(0, 1).toUpperCase()}
            </span>
            <span className="min-w-0 flex-1 truncate text-sm font-medium">{userName}</span>
          </div>
        )}
      </div>
    </aside>
  );
}
