// Shared navigation config for the desktop sidebar and the mobile menu.
// Visibility follows /api/v1/workspace/context capabilities; hiding a link is
// usability only, the API enforces access.
import type { Capability } from "@/lib/api/workspace";

export interface NavLink {
  label: string;
  href: string;
  requires?: Capability[];
}

export interface NavSection {
  label: string | null;
  /** Overview route the section header links to. A section with an overview stays visible even with no child links. */
  href?: string;
  requires?: Capability[];
  links: NavLink[];
}

export const NAV_SECTIONS: NavSection[] = [
  {
    label: null,
    links: [
      { label: "Dashboard", href: "/" },
      { label: "Clients", href: "/clients" },
    ],
  },
  {
    label: "Projects",
    href: "/projects",
    links: [
      { label: "Change Orders", href: "/projects/change-orders", requires: ["legacy_modules"] },
      { label: "Costbook", href: "/costbook", requires: ["legacy_modules"] },
      { label: "Contractors", href: "/contractors", requires: ["legacy_modules"] },
    ],
  },
  {
    label: "Land",
    href: "/land",
    requires: ["land"],
    links: [
      { label: "Lots", href: "/lots" },
      { label: "OTP Timeline", href: "/lots/timeline" },
      { label: "Documents", href: "/documents", requires: ["legacy_modules"] },
      { label: "Presales", href: "/financing/presales", requires: ["legacy_modules"] },
      { label: "Financing", href: "/financing", requires: ["legacy_modules"] },
      { label: "Lenders", href: "/financing/lenders", requires: ["legacy_modules"] },
    ],
  },
  {
    label: "Rentals",
    href: "/rentals",
    requires: ["rentals"],
    links: [
      { label: "Map", href: "/rentals/map" },
      { label: "Lease Import", href: "/rentals/lease-import" },
      { label: "Inspections", href: "/rentals/inspections" },
      { label: "Inspection Reports", href: "/rentals/reports" },
    ],
  },
];

/** Entries behind the gear icon (no Workspace section in the main nav). */
export const SETTINGS_MENU: NavLink[] = [
  { label: "Imports", href: "/settings/imports", requires: ["settings"] },
  { label: "Settings", href: "/settings", requires: ["settings"] },
];

export function allowed(requires: Capability[] | undefined, capabilities: Record<string, boolean> | null): boolean {
  if (!requires || requires.length === 0) return true;
  if (!capabilities) return false;
  return requires.every((capability) => capabilities[capability]);
}

export function visibleSections(capabilities: Record<string, boolean> | null): NavSection[] {
  return NAV_SECTIONS.filter((section) => allowed(section.requires, capabilities))
    .map((section) => ({ ...section, links: section.links.filter((link) => allowed(link.requires, capabilities)) }))
    .filter((section) => Boolean(section.href) || section.links.length > 0);
}

export function visibleSettingsMenu(capabilities: Record<string, boolean> | null): NavLink[] {
  return SETTINGS_MENU.filter((link) => allowed(link.requires, capabilities));
}

const EXACT_MATCH = new Set(["/", "/rentals", "/settings", "/financing", "/lots", "/projects", "/land"]);

export function isActive(pathname: string, href: string): boolean {
  if (EXACT_MATCH.has(href)) return pathname === href;
  return pathname === href || pathname.startsWith(`${href}/`);
}
