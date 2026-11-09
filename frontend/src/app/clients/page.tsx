"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { CLIENT_STAGES, createClient, listClients, stageLabel, type Client, type ClientStage, type ClientType } from "@/lib/api/clients";
import { useWorkspaceContext } from "../useWorkspaceContext";
import { Card, Empty, ErrorNote, PageShell, fieldClass, formatDate, primaryButton, secondaryButton } from "../components/WorkspaceUi";

export default function ClientsPage() {
  const { context } = useWorkspaceContext();
  const [clients, setClients] = useState<Client[]>([]);
  const [total, setTotal] = useState(0);
  const [q, setQ] = useState("");
  const [stage, setStage] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [type, setType] = useState<ClientType>("individual");
  const [newStage, setNewStage] = useState<ClientStage>("lead");

  const load = useCallback(async () => {
    try {
      const page = await listClients({ q: q || undefined, stage: stage || undefined, limit: 200 });
      setClients(page.items);
      setTotal(page.total);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Clients unavailable");
    } finally {
      setLoading(false);
    }
  }, [q, stage]);
  useEffect(() => {
    const timer = window.setTimeout(() => { void load(); }, 200);
    return () => window.clearTimeout(timer);
  }, [load]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    try {
      const created = await createClient({ display_name: name, client_type: type, lifecycle_stage: newStage });
      window.location.assign(`/clients/${created.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create client");
    }
  }

  const canManage = Boolean(context?.capabilities.manage_clients);
  return (
    <PageShell
      title="Clients"
      subtitle={`${total} client${total === 1 ? "" : "s"}${context ? ` · ${context.org.name}` : ""}`}
      actions={canManage ? <button onClick={() => setCreating(!creating)} className={primaryButton}>New client</button> : null}
    >
      <ErrorNote message={error} />
      {creating ? (
        <Card title="New client" className="mb-4">
          <form onSubmit={submit} className="grid gap-3 sm:grid-cols-4">
            <input required value={name} onChange={(event) => setName(event.target.value)} placeholder="Client name" className={`${fieldClass} sm:col-span-2`} />
            <select value={type} onChange={(event) => setType(event.target.value as ClientType)} className={fieldClass}>
              <option value="individual">Individual</option>
              <option value="company">Company</option>
            </select>
            <select value={newStage} onChange={(event) => setNewStage(event.target.value as ClientStage)} className={fieldClass}>
              {CLIENT_STAGES.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
            </select>
            <div className="flex justify-end gap-2 sm:col-span-4">
              <button type="button" onClick={() => setCreating(false)} className={secondaryButton}>Cancel</button>
              <button className={primaryButton}>Create</button>
            </div>
          </form>
        </Card>
      ) : null}
      <div className="mb-4 flex flex-wrap gap-2">
        <input value={q} onChange={(event) => setQ(event.target.value)} placeholder="Search clients" className={`${fieldClass} min-w-0 flex-1`} />
        <select value={stage} onChange={(event) => setStage(event.target.value)} className={fieldClass}>
          <option value="">All stages</option>
          {CLIENT_STAGES.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
        </select>
      </div>
      {loading ? <p className="text-sm text-[var(--ch-text-muted)]">Loading…</p> : clients.length === 0 ? (
        <Empty>{q || stage ? "No clients match." : "No clients yet. Existing buyers stay on their sale agreements until a client record is created and linked."}</Empty>
      ) : (
        <div className="overflow-hidden rounded-xl border border-[var(--ch-border)] bg-[var(--ch-surface)]">
          <table className="w-full text-sm">
            <thead className="text-left text-xs uppercase tracking-widest text-[var(--ch-text-muted)]">
              <tr><th className="px-4 py-2">Client</th><th className="px-4 py-2">Stage</th><th className="px-4 py-2">Projects</th><th className="px-4 py-2">Updated</th></tr>
            </thead>
            <tbody className="divide-y divide-[var(--ch-border)]">
              {clients.map((client) => (
                <tr key={client.id} className="hover:bg-[var(--ch-surface-hover)]">
                  <td className="px-4 py-2"><Link href={`/clients/${client.id}`} className="font-medium text-[var(--ch-accent)]">{client.display_name}</Link>{client.primary_contact ? <span className="block text-xs text-[var(--ch-text-muted)]">{client.primary_contact.email || client.primary_contact.phone || client.primary_contact.full_name}</span> : null}</td>
                  <td className="px-4 py-2">{stageLabel(client.lifecycle_stage)}</td>
                  <td className="px-4 py-2">{client.project_count}</td>
                  <td className="px-4 py-2 text-xs text-[var(--ch-text-muted)]">{formatDate(client.updated_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </PageShell>
  );
}
