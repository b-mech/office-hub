"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { CLIENT_STAGES, getClient, getContactOptions, stageLabel, updateClient, type ClientDetail, type ClientStage, type ContactSummary } from "@/lib/api/clients";
import { useWorkspaceContext } from "@/app/useWorkspaceContext";
import { Card, Empty, ErrorNote, PageShell, fieldClass, formatDate, primaryButton, secondaryButton } from "@/app/components/WorkspaceUi";

export default function ClientDetailPage() {
  const { clientId } = useParams<{ clientId: string }>();
  const { context } = useWorkspaceContext();
  const [client, setClient] = useState<ClientDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState("");
  const [notes, setNotes] = useState("");
  const [contactQuery, setContactQuery] = useState("");
  const [contacts, setContacts] = useState<ContactSummary[]>([]);

  useEffect(() => {
    let active = true;
    getClient(clientId)
      .then((value) => {
        if (!active) return;
        setClient(value);
        setName(value.display_name);
        setNotes(value.notes || "");
      })
      .catch((err: unknown) => { if (active) setError(err instanceof Error ? err.message : "Client not found"); });
    return () => { active = false; };
  }, [clientId]);

  const canManage = Boolean(context?.capabilities.manage_clients);
  useEffect(() => {
    if (!editing || !canManage) return;
    const timer = window.setTimeout(() => {
      getContactOptions(contactQuery || undefined).then(setContacts).catch(() => setContacts([]));
    }, 200);
    return () => window.clearTimeout(timer);
  }, [editing, canManage, contactQuery]);

  async function save(payload: Parameters<typeof updateClient>[1]) {
    try {
      setClient(await updateClient(clientId, payload));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save client");
    }
  }

  return (
    <PageShell
      title={client?.display_name || "Client"}
      subtitle={client ? `${client.client_type === "company" ? "Company" : "Individual"} · ${stageLabel(client.lifecycle_stage)} since ${formatDate(client.stage_changed_at)}` : undefined}
      actions={<Link href="/clients" className={secondaryButton}>← Clients</Link>}
    >
      <ErrorNote message={error} />
      {client ? (
        <div className="grid gap-4 lg:grid-cols-3">
          <div className="space-y-4 lg:col-span-2">
            <Card title="Projects">
              {client.projects.length === 0 ? <Empty>No projects linked. Link one from the project workspace.</Empty> : (
                <ul className="divide-y divide-[var(--ch-border)]">
                  {client.projects.map((project) => (
                    <li key={project.id} className="py-2">
                      <Link href={`/projects/${project.id}`} className="flex justify-between gap-3 text-sm hover:text-[var(--ch-accent)]">
                        <span className="min-w-0"><span className="block truncate font-medium">{project.address}</span><span className="block text-xs text-[var(--ch-text-muted)]">{project.community} · {project.lifecycle_status.replace(/_/g, " ")}{project.on_hold ? " · on hold" : ""}</span></span>
                        <span className="shrink-0 text-xs text-[var(--ch-text-muted)]">{project.possession_date ? `Possession ${formatDate(project.possession_date)}` : ""}</span>
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
            <Card title="Notes" action={canManage && !editing ? <button onClick={() => setEditing(true)} className={secondaryButton}>Edit</button> : null}>
              {editing ? (
                <div className="space-y-3">
                  <input value={name} onChange={(event) => setName(event.target.value)} className={`${fieldClass} w-full`} />
                  <textarea value={notes} onChange={(event) => setNotes(event.target.value)} className={`${fieldClass} min-h-24 w-full`} />
                  <div>
                    <p className="mb-1 text-xs text-[var(--ch-text-muted)]">Primary contact (contacts in this organization)</p>
                    <input value={contactQuery} onChange={(event) => setContactQuery(event.target.value)} placeholder="Search contacts" className={`${fieldClass} mb-2 w-full`} />
                    <div className="max-h-40 space-y-1 overflow-y-auto">
                      {contacts.map((contact) => (
                        <button key={contact.id} type="button" onClick={() => void save({ primary_contact_id: contact.id })} className="block w-full rounded-md px-2 py-1 text-left text-xs hover:bg-[var(--ch-surface-hover)]">
                          {contact.full_name}{contact.email ? ` · ${contact.email}` : ""} <span className="text-[var(--ch-text-muted)]">({contact.contact_type})</span>
                        </button>
                      ))}
                    </div>
                  </div>
                  <div className="flex justify-end gap-2">
                    <button onClick={() => setEditing(false)} className={secondaryButton}>Done</button>
                    <button onClick={() => void save({ display_name: name, notes: notes || null })} className={primaryButton}>Save</button>
                  </div>
                </div>
              ) : (
                <p className="whitespace-pre-wrap text-sm">{client.notes || <span className="text-[var(--ch-text-muted)]">No notes.</span>}</p>
              )}
            </Card>
          </div>
          <div className="space-y-4">
            <Card title="Lifecycle">
              {canManage ? (
                <select value={client.lifecycle_stage} onChange={(event) => void save({ lifecycle_stage: event.target.value as ClientStage })} className={`${fieldClass} w-full`}>
                  {CLIENT_STAGES.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
                </select>
              ) : <p className="text-sm">{stageLabel(client.lifecycle_stage)}</p>}
              <p className="mt-2 text-xs text-[var(--ch-text-muted)]">Client stage is tracked separately from each project&apos;s construction and possession status. Changes are recorded in the audit log.</p>
            </Card>
            <Card title="Primary contact">
              {client.primary_contact ? (
                <div className="text-sm">
                  <p className="font-medium">{client.primary_contact.full_name}</p>
                  {client.primary_contact.company_name ? <p>{client.primary_contact.company_name}</p> : null}
                  {client.primary_contact.email ? <p className="text-[var(--ch-text-muted)]">{client.primary_contact.email}</p> : null}
                  {client.primary_contact.phone ? <p className="text-[var(--ch-text-muted)]">{client.primary_contact.phone}</p> : null}
                  {canManage ? <button onClick={() => void save({ primary_contact_id: null })} className={`${secondaryButton} mt-2`}>Remove</button> : null}
                </div>
              ) : <p className="text-sm text-[var(--ch-text-muted)]">None linked.</p>}
            </Card>
            {client.duplicate_name_count > 0 ? (
              <p className="rounded-md bg-[var(--ch-warning-bg)] p-3 text-xs text-[var(--ch-warning-text)]">{client.duplicate_name_count} other client{client.duplicate_name_count === 1 ? "" : "s"} in this organization share this name.</p>
            ) : null}
          </div>
        </div>
      ) : !error ? <p className="text-sm text-[var(--ch-text-muted)]">Loading…</p> : null}
    </PageShell>
  );
}
