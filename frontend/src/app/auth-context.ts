"use client";

import { createContext, useContext } from "react";
import type { AuthSession } from "@/lib/auth";

export interface AuthState {
  /** null when the backend sign-in status is unknown (older backend or outage). */
  session: AuthSession | null;
  signOutAndLeave: () => Promise<void>;
}

export const AuthContext = createContext<AuthState>({ session: null, signOutAndLeave: async () => {} });

export function useAuth(): AuthState {
  return useContext(AuthContext);
}
