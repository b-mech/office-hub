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
  requires?: Capability[];
  links: NavLink[];
}

export const NAV_SECTIONS: NavSection[] = [
  {
    label: null,
    links: [
      { label: "Dashboard", href: "/" },
      { label: "Projects", href: "/projects" },
      { label: "Clients", href: "/clients" },
    ],
  },
  {
    label: "Projects",
    requires: ["legacy_modules"],
    links: [
      { label: "Change Orders", href: "/projects/change-orders" },
      { label: "Costbook", href: "/costbook" },
      { label: "Contractors", href: "/contractors" },
    ],
  },
  {
    label: "Land",
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
    requires: ["rentals"],
    links: [
      { label: "Overview", href: "/rentals" },
      { label: "Map", href: "/rentals/map" },
      { label: "Lease Import", href: "/rentals/lease-import" },
      { label: "Inspections", href: "/rentals/inspections" },
      { label: "Inspection Reports", href: "/rentals/reports" },
    ],
  },
  {
    label: "Workspace",
    requires: ["settings"],
    links: [
      { label: "Imports", href: "/settings/imports" },
      { label: "Settings", href: "/settings" },
    ],
  },
];

export function allowed(requires: Capability[] | undefined, capabilities: Record<string, boolean> | null): boolean {
  if (!requires || requires.length === 0) return true;
  if (!capabilities) return false;
  return requires.every((capability) => capabilities[capability]);
}

export function visibleSections(capabilities: Record<string, boolean> | null): NavSection[] {
  return NAV_SECTIONS.filter((section) => allowed(section.requires, capabilities))
    .map((section) => ({ ...section, links: section.links.filter((link) => allowed(link.requires, capabilities)) }))
    .filter((section) => section.links.length > 0);
}

export function isActive(pathname: string, href: string): boolean {
  if (href === "/") return pathname === "/";
  if (href === "/rentals" || href === "/settings" || href === "/financing" || href === "/lots" || href === "/projects") {
    return pathname === href;
  }
  return pathname === href || pathname.startsWith(`${href}/`);
}
