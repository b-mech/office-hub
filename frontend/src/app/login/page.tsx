"use client";

import Image from "next/image";
import Link from "next/link";
import { Suspense, useEffect, useState, type FormEvent } from "react";
import { useSearchParams } from "next/navigation";
import { AuthError, getAuthSession, passwordLogin } from "@/lib/auth";
import { safeNextPath } from "@/lib/auth-paths";
import { setSelectedOrg } from "@/lib/tenant";

const NOTICES: Record<string, string> = {
  expired: "Your session has ended. Sign in again to continue.",
  signed_out: "You have been signed out.",
};

function LoginForm() {
  const params = useSearchParams();
  const next = safeNextPath(params.get("next"));
  const notice = NOTICES[params.get("reason") || ""] || null;
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [authEnforced, setAuthEnforced] = useState<boolean | null>(null);

  useEffect(() => {
    let active = true;
    getAuthSession()
      .then((session) => {
        if (!active) return;
        if (session.authenticated) {
          window.location.replace(next);
          return;
        }
        setAuthEnforced(session.auth_enforced);
      })
      .catch(() => { if (active) setAuthEnforced(null); });
    return () => { active = false; };
  }, [next]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      await passwordLogin(email.trim(), password);
      setPassword("");
      setSelectedOrg(null);
      window.location.assign(next);
    } catch (cause) {
      setPassword("");
      setError(cause instanceof AuthError ? cause.message : "Office Hub is unavailable. Try again shortly.");
      setSubmitting(false);
    }
  }

  const input = "w-full rounded-lg border border-[var(--ch-border)] bg-[var(--ch-card-bg,white)] px-3 py-2 text-sm text-[var(--ch-text-primary)] outline-none focus:border-[var(--ch-accent,#2563eb)]";
  return (
    <main className="grid min-h-screen w-full place-items-center px-4 py-10">
      <div className="w-full max-w-sm rounded-2xl border border-[var(--ch-border)] bg-[var(--ch-card-bg,white)] p-6 shadow-sm">
        <div className="mb-6 flex items-center gap-2">
          <Image src="/favicon.png" alt="" width={28} height={28} />
          <h1 className="text-lg font-semibold">Sign in to Office Hub</h1>
        </div>
        {notice ? <p className="mb-4 rounded-lg bg-[var(--ch-page-bg)] px-3 py-2 text-sm text-[var(--ch-text-secondary)]" role="status">{notice}</p> : null}
        <form onSubmit={submit} className="space-y-4" noValidate>
          <label className="block space-y-1 text-sm font-medium">
            <span>Email</span>
            <input className={input} type="email" name="email" autoComplete="username" required autoFocus
              value={email} onChange={(event) => setEmail(event.target.value)} />
          </label>
          <label className="block space-y-1 text-sm font-medium">
            <span>Password</span>
            <input className={input} type="password" name="password" autoComplete="current-password" required
              value={password} onChange={(event) => setPassword(event.target.value)} />
          </label>
          {error ? <p className="text-sm text-red-600" role="alert">{error}</p> : null}
          <button type="submit" disabled={submitting || !email.trim() || !password}
            className="w-full rounded-lg bg-[var(--ch-accent,#1f2937)] px-3 py-2 text-sm font-semibold text-white disabled:opacity-50">
            {submitting ? "Signing in…" : "Sign in"}
          </button>
        </form>
        {authEnforced === false ? (
          <p className="mt-5 border-t border-[var(--ch-border)] pt-4 text-xs text-[var(--ch-text-secondary)]">
            Sign-in is optional on this installation.{" "}
            <Link href={next} className="font-medium underline">Continue without signing in</Link>
          </p>
        ) : null}
      </div>
    </main>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={null}>
      <LoginForm />
    </Suspense>
  );
}
