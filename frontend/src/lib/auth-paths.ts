// Pure helpers for sign-in routing. No imports, so `node --test` can load this
// file directly (see tests/auth-paths.test.mjs).

export type LoginReason = "required" | "expired" | "signed_out";

const LOGIN_PATH = "/login";

/** Pages that render without a session or the app shell. */
export function isPublicPagePath(pathname: string): boolean {
  if (pathname === LOGIN_PATH || pathname.startsWith(`${LOGIN_PATH}/`)) return true;
  if (pathname === "/auth/callback") return true;
  if (pathname.startsWith("/r/")) return true; // maintenance QR intake
  // /rentals/reports/<token> is the public report; /rentals/reports is the staff list.
  return /^\/rentals\/reports\/[^/]+\/?$/.test(pathname);
}

/**
 * Only same-site relative paths are allowed as post-login destinations.
 * Anything absolute, protocol-relative, backslash-tricked, or pointing back at
 * /login falls back to "/".
 */
export function safeNextPath(raw: string | null | undefined): string {
  if (!raw || typeof raw !== "string") return "/";
  const value = raw.trim();
  if (!value.startsWith("/") || value.startsWith("//") || value.includes("\\")) return "/";
  if (/[\u0000-\u001f\u007f]/.test(value)) return "/";
  let parsed: URL;
  try {
    parsed = new URL(value, "http://officehub.invalid");
  } catch {
    return "/";
  }
  if (parsed.origin !== "http://officehub.invalid") return "/";
  if (parsed.pathname === LOGIN_PATH || parsed.pathname.startsWith(`${LOGIN_PATH}/`)) return "/";
  return `${parsed.pathname}${parsed.search}${parsed.hash}`;
}

export function loginHref(next?: string | null, reason?: LoginReason): string {
  const params = new URLSearchParams();
  const target = safeNextPath(next);
  if (target !== "/") params.set("next", target);
  if (reason && reason !== "required") params.set("reason", reason);
  const query = params.toString();
  return query ? `${LOGIN_PATH}?${query}` : LOGIN_PATH;
}

/** Strip a trailing /api/v1 so callers can address /api/auth and /api/v1 alike. */
export function apiRootFrom(configured: string | undefined): string {
  return (configured || "/backend-api").replace(/\/+$/, "").replace(/\/api\/v1$/, "");
}

/**
 * If `url` targets the Office Hub backend (through `apiRoot`) or a same-origin
 * Next.js `/api/*` route, return its backend-style path ("/api/..."); else null.
 */
export function apiRequestPath(url: string, apiRoot: string, origin: string): string | null {
  let target: URL;
  let root: URL;
  try {
    target = new URL(url, origin);
    root = new URL(apiRoot || "/", origin);
  } catch {
    return null;
  }
  const rootPath = root.pathname.replace(/\/+$/, "");
  if (target.origin === root.origin) {
    if (!rootPath) return target.pathname.startsWith("/api/") ? target.pathname : null;
    if (target.pathname === rootPath || target.pathname.startsWith(`${rootPath}/`)) {
      return target.pathname.slice(rootPath.length) || "/";
    }
  }
  if (target.origin === origin && target.pathname.startsWith("/api/")) return target.pathname;
  return null;
}

/** A 401 from these paths must not bounce the user to /login. */
export function isAuthExemptApiPath(path: string): boolean {
  return path.startsWith("/api/auth/") || path.startsWith("/api/public/") ||
    path.startsWith("/api/rentals/reports/public/");
}
