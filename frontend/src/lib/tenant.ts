// Selected organisation for tenant-aware API calls.
//
// The value is only a *selector*: the backend checks the signed-in user's
// memberships on every request and never treats this header as
// authentication. Stored per browser tab (sessionStorage).

export const ORG_STORAGE_KEY = "officehub.org";
export const ORG_HEADER = "X-OfficeHub-Org";

export function getSelectedOrg(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.sessionStorage.getItem(ORG_STORAGE_KEY);
  } catch {
    return null;
  }
}

export function setSelectedOrg(slug: string | null): void {
  if (typeof window === "undefined") return;
  try {
    if (slug) window.sessionStorage.setItem(ORG_STORAGE_KEY, slug);
    else window.sessionStorage.removeItem(ORG_STORAGE_KEY);
  } catch {
    // Storage can be unavailable (private mode); the home org is used then.
  }
}

export function tenantHeaders(): Record<string, string> {
  const org = getSelectedOrg();
  return org ? { [ORG_HEADER]: org } : {};
}

/** Adds ?org= to plain links (PDF downloads) that cannot send headers. */
export function withOrgQuery(url: string): string {
  const org = getSelectedOrg();
  if (!org) return url;
  const [base, hash] = url.split("#", 2);
  const separator = base.includes("?") ? "&" : "?";
  return `${base}${separator}org=${encodeURIComponent(org)}${hash !== undefined ? `#${hash}` : ""}`;
}
