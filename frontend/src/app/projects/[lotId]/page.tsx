"use client";

import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";
import { getLot, type Lot } from "@/lib/api/costbook";
import { listClients, setProjectClient, type Client } from "@/lib/api/clients";
import { presalesApi } from "@/lib/api/presales";
import { LotDetail } from "@/app/lots/components/LotWorkspace";
import { TenderPackagesPanel } from "@/app/projects/components/TenderPackagesPanel";
import { useWorkspaceContext } from "@/app/useWorkspaceContext";
import { Card, ErrorNote, fieldClass, primaryButton, secondaryButton } from "@/app/components/WorkspaceUi";

type Tab = "overview" | "tendering" | "costs";

function ClientLink({ lot, canManage, onChanged }: { lot: Lot; canManage: boolean; onChanged: () => Promise<void> }) {
  const [clients, setClients] = useState<Client[]>([]);
  const [choice, setChoice] = useState(lot.client_id || "");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    if (!canManage) return;
    listClients({ limit: 500 }).then((page) => setClients(page.items)).catch((err: unknown) => setError(err instanceof Error ? err.message : "Clients unavailable"));
  }, [canManage]);
  async function save(clientId: string | null) {
    setSaving(true);
    setError(null);
    try {
      await setProjectClient(lot.id, clientId);
      await onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not update the client");
    } finally {
      setSaving(false);
    }
  }
  return (
    <Card title="Client">
      <ErrorNote message={error} />
      {lot.client_id ? (
        <p className="mb-3 text-sm">
          <Link href={`/clients/${lot.client_id}`} className="font-medium text-[var(--ch-accent)]">{lot.client_name || "View client"}</Link>
        </p>
      ) : (
        <p className="mb-3 text-sm text-[var(--ch-text-muted)]">No client linked{lot.buyer_name ? ` (buyer on agreement: ${lot.buyer_name})` : ""}.</p>
      )}
      {canManage ? (
        <div className="flex flex-wrap gap-2">
          <select value={choice} onChange={(event) => setChoice(event.target.value)} className={fieldClass}>
            <option value="">Select client…</option>
            {clients.map((client) => <option key={client.id} value={client.id}>{client.display_name}</option>)}
          </select>
          <button disabled={!choice || saving || choice === lot.client_id} onClick={() => void save(choice)} className={primaryButton}>Link client</button>
          {lot.client_id ? <button disabled={saving} onClick={() => void save(null)} className={secondaryButton}>Unlink</button> : null}
          <Link href="/clients" className={secondaryButton}>New client</Link>
        </div>
      ) : null}
    </Card>
  );
}

function ProjectWorkspace() {
  const params = useParams<{ lotId: string }>();
  const lotId = params.lotId;
  const router = useRouter();
  const search = useSearchParams();
  const tab = (search.get("tab") as Tab) || "overview";
  const { context } = useWorkspaceContext();
  const [lot, setLot] = useState<Lot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [version, setVersion] = useState(0);
  useEffect(() => {
    let active = true;
    getLot(lotId)
      .then((value) => { if (active) setLot(value); })
      .catch((err: unknown) => { if (active) setError(err instanceof Error ? err.message : "Project not found"); });
    return () => { active = false; };
  }, [lotId, version]);
  const load = useCallback(async () => { setVersion((value) => value + 1); }, []);

  const legacy = Boolean(context?.capabilities.legacy_modules);
  const tabs: { id: Tab; label: string }[] = [
    { id: "overview", label: "Overview" },
    { id: "tendering", label: "Tendering" },
    ...(legacy ? [{ id: "costs" as Tab, label: "Costs" }] : []),
  ];

  return (
    <main className="min-h-screen bg-[var(--ch-page-bg)] text-[var(--ch-text-primary)]">
      <div className="border-b border-[var(--ch-border)] px-8 pt-5">
        <Link href={`/projects?project=${lotId}`} className="text-xs text-[var(--ch-text-muted)] hover:text-[var(--ch-accent)]">← Projects</Link>
        <h1 className="mt-1 text-xl font-semibold">{lot ? lot.address : "Project"}</h1>
        <nav className="mt-3 flex gap-1">
          {tabs.map((item) => (
            <button
              key={item.id}
              onClick={() => router.replace(`/projects/${lotId}${item.id === "overview" ? "" : `?tab=${item.id}`}`)}
              className={`rounded-t-md border-b-2 px-3 py-2 text-sm ${tab === item.id ? "border-[var(--ch-accent)] font-semibold text-[var(--ch-accent)]" : "border-transparent text-[var(--ch-text-muted)] hover:text-[var(--ch-text-primary)]"}`}
            >
              {item.label}
            </button>
          ))}
        </nav>
      </div>
      <div className="px-0">
        {error ? <div className="p-8"><ErrorNote message={error} /></div> : null}
        {lot && tab === "overview" ? (
          <div>
            <div className="px-8 pt-6"><ClientLink lot={lot} canManage={Boolean(context?.capabilities.manage_clients)} onChanged={load} /></div>
            <LotDetail
              lot={lot}
              showTendering={false}
              showLegacyActions={legacy}
              onMarkedPresale={async () => {
                await presalesApi.updateLot(lot.id, { sale_type: "presale" });
                await load();
              }}
            />
          </div>
        ) : null}
        {lot && tab === "tendering" ? (
          <div className="p-8">
            {lot.property_id ? <TenderPackagesPanel propertyId={lot.property_id} /> : (
              <Card title="Tender packages">
                <p className="text-sm text-[var(--ch-text-muted)]">No linked property yet — link this lot to a property to enable tendering.</p>
              </Card>
            )}
          </div>
        ) : null}
        {lot && tab === "costs" && legacy ? (
          <div className="p-8">
            <Card title="Costs">
              <div className="flex flex-wrap gap-2 text-sm">
                <Link href={`/lots/${lot.id}/costbook`} className={primaryButton}>Open Costbook</Link>
                <Link href={`/lots/${lot.id}/costbook?tab=invoices`} className={secondaryButton}>Invoices</Link>
                {lot.sale_type === "presale" ? <Link href={`/financing/presales/${lot.id}`} className={secondaryButton}>Presale financing</Link> : null}
              </div>
            </Card>
          </div>
        ) : null}
      </div>
    </main>
  );
}

export default function ProjectWorkspacePage() {
  return (
    <Suspense fallback={<p className="p-8 text-sm text-[var(--ch-text-muted)]">Loading…</p>}>
      <ProjectWorkspace />
    </Suspense>
  );
}
