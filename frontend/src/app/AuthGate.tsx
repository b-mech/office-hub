"use client";

import { useCallback, useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import AppSidebar from "./AppSidebar";
import MobileNavigation from "./MobileNavigation";
import { AuthContext } from "./auth-context";
import { API_ROOT, AuthError, getAuthSession, signOut, type AuthSession } from "@/lib/auth";
import { installAuthFetch } from "@/lib/auth-fetch";
import { isPublicPagePath, loginHref } from "@/lib/auth-paths";

if (typeof window !== "undefined") installAuthFetch(API_ROOT);

type GateState = { status: "loading" } | { status: "ready"; session: AuthSession | null };

export default function AuthGate({ fallbackUserName, children }: { fallbackUserName: string; children: React.ReactNode }) {
  const pathname = usePathname() || "/";
  const publicPage = isPublicPagePath(pathname);
  const [state, setState] = useState<GateState>({ status: "loading" });

  useEffect(() => {
    if (publicPage) return;
    let active = true;
    getAuthSession()
      .then((session) => {
        if (!active) return;
        const here = `${window.location.pathname}${window.location.search}${window.location.hash}`;
        if (session.session_expired) {
          window.location.replace(loginHref(here, "expired"));
          return;
        }
        if (session.auth_enforced && !session.authenticated) {
          window.location.replace(loginHref(here, "required"));
          return;
        }
        setState({ status: "ready", session });
      })
      .catch((error: unknown) => {
        // A backend without /api/auth/session (older release) or a transient
        // failure keeps the legacy behaviour; data calls still enforce auth.
        if (active) setState({ status: "ready", session: null });
        if (!(error instanceof AuthError)) console.warn("Office Hub sign-in status unavailable");
      });
    return () => { active = false; };
  }, [publicPage]);

  const signOutAndLeave = useCallback(async () => {
    try {
      await signOut();
    } finally {
      window.location.assign(loginHref(null, "signed_out"));
    }
  }, []);

  if (publicPage) return <>{children}</>;
  if (state.status === "loading") {
    return <div className="grid min-h-screen w-full place-items-center text-sm text-[var(--ch-text-secondary)]">Loading…</div>;
  }
  return (
    <AuthContext.Provider value={{ session: state.session, signOutAndLeave }}>
      <div className="flex min-h-screen">
        <AppSidebar fallbackUserName={fallbackUserName} />
        <div className="min-w-0 flex-1">
          <MobileNavigation />
          {children}
        </div>
      </div>
    </AuthContext.Provider>
  );
}
