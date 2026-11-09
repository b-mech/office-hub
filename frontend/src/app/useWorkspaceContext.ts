"use client";

import { useEffect, useState } from "react";
import { getWorkspaceContext, type WorkspaceContext } from "@/lib/api/workspace";
import { getSelectedOrg, setSelectedOrg } from "@/lib/tenant";

let pending: Promise<WorkspaceContext> | null = null;

function loadContext(): Promise<WorkspaceContext> {
  if (!pending) {
    pending = getWorkspaceContext()
      .then((context) => {
        // Drop a stale selection the user no longer belongs to.
        const selected = getSelectedOrg();
        if (selected && !context.available_orgs.some((org) => org.slug === selected || org.id === selected)) {
          setSelectedOrg(null);
        }
        return context;
      })
      .catch((error: unknown) => {
        pending = null;
        throw error;
      });
  }
  return pending;
}

export function useWorkspaceContext(): { context: WorkspaceContext | null; error: string | null } {
  const [context, setContext] = useState<WorkspaceContext | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let active = true;
    loadContext()
      .then((value) => { if (active) setContext(value); })
      .catch((err: unknown) => {
        if (active) {
          const message = err instanceof Error ? err.message : "Workspace unavailable";
          // A stale or forbidden org selection falls back to the home org once.
          if (getSelectedOrg()) {
            setSelectedOrg(null);
            window.location.reload();
            return;
          }
          setError(message);
        }
      });
    return () => { active = false; };
  }, []);
  return { context, error };
}

export function switchOrg(slug: string | null): void {
  setSelectedOrg(slug);
  window.location.assign("/");
}
