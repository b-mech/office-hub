"use client";

import { useEffect } from "react";

// Landing page for the backend's Google OAuth redirect (FRONTEND_AUTH_CALLBACK_URL).
// The backend has already set the HttpOnly session cookie.
export default function AuthCallbackPage() {
  useEffect(() => { window.location.replace("/"); }, []);
  return null;
}
