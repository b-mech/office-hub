import { apiRequestPath, isAuthExemptApiPath, isPublicPagePath, loginHref } from "./auth-paths";

// One central hook instead of editing every API helper: browser fetches to the
// Office Hub backend always carry the session cookie, and a 401 (no session,
// expired, or revoked) sends the user to /login once.

let installed = false;
let redirecting = false;

export function installAuthFetch(apiRoot: string): void {
  if (installed || typeof window === "undefined") return;
  installed = true;
  const original = window.fetch.bind(window);
  window.fetch = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    const path = apiRequestPath(url, apiRoot, window.location.origin);
    if (path === null) return original(input, init);
    const nextInit: RequestInit | undefined =
      input instanceof Request || init?.credentials !== undefined ? init : { ...init, credentials: "include" };
    const response = await original(input, nextInit);
    if (
      response.status === 401 &&
      !redirecting &&
      !isAuthExemptApiPath(path) &&
      !isPublicPagePath(window.location.pathname)
    ) {
      redirecting = true;
      const here = `${window.location.pathname}${window.location.search}${window.location.hash}`;
      window.location.assign(loginHref(here, "expired"));
    }
    return response;
  };
}
