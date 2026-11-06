import { apiRootFrom } from "./auth-paths";

// Office Hub sign-in. The session lives in an HttpOnly cookie set by the
// backend; the browser never sees a token and nothing is kept in storage.

export const API_ROOT = apiRootFrom(process.env.NEXT_PUBLIC_API_URL);
const AUTH_BASE = `${API_ROOT}/api/auth`;

export interface AuthMembership { org_id: string; slug: string; name: string; role: string }

export interface AuthSession {
  auth_enforced: boolean;
  authenticated: boolean;
  session_expired: boolean;
  password_login: boolean;
  user: { id: string; email: string; full_name: string; role: string; is_superadmin: boolean } | null;
  memberships: AuthMembership[];
  expires_at: string | null;
}

export class AuthError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

async function detail(response: Response, fallback: string): Promise<string> {
  const body = (await response.json().catch(() => ({}))) as { detail?: unknown };
  return typeof body.detail === "string" ? body.detail : fallback;
}

export async function getAuthSession(): Promise<AuthSession> {
  const response = await fetch(`${AUTH_BASE}/session`, { credentials: "include", cache: "no-store" });
  if (!response.ok) throw new AuthError(await detail(response, "Sign-in status unavailable"), response.status);
  return (await response.json()) as AuthSession;
}

export async function passwordLogin(email: string, password: string): Promise<AuthSession> {
  const response = await fetch(`${AUTH_BASE}/login`, {
    method: "POST",
    credentials: "include",
    cache: "no-store",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!response.ok) {
    const fallback = response.status === 429 ? "Too many sign-in attempts. Try again later." : "Sign-in failed";
    throw new AuthError(await detail(response, fallback), response.status);
  }
  return (await response.json()) as AuthSession;
}

export async function signOut(): Promise<void> {
  await fetch(`${AUTH_BASE}/logout`, { method: "POST", credentials: "include", cache: "no-store" });
}
