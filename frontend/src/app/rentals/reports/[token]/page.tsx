"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import * as api from "@/lib/api/rental-reports";

export default function PublicReportPage() {
  const { token } = useParams<{ token: string }>();
  const [report, setReport] = useState<api.Report | null>(null);
  const [authorNames, setAuthorNames] = useState<Record<string, string>>({});
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState<string | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.publicReport(token).then(setReport).catch((cause) => setError(cause.message));
  }, [token]);

  async function addComment(itemId: string) {
    const author = (authorNames[itemId] || "").trim();
    const body = (drafts[itemId] || "").trim();
    if (!author || !body) {
      setError("Enter your name and a comment before posting.");
      return;
    }
    setSaving(itemId);
    setError("");
    try {
      const comment = await api.addComment(token, itemId, author, body);
      setReport((current) => current ? {
        ...current,
        items: current.items.map((item) => item.id === itemId
          ? { ...item, comments: [...item.comments, comment] }
          : item),
      } : current);
      setDrafts((current) => ({ ...current, [itemId]: "" }));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not post comment");
    } finally {
      setSaving(null);
    }
  }

  if (error && !report) return <main className="mx-auto max-w-2xl p-8"><h1 className="text-2xl font-bold">Report unavailable</h1><p className="mt-3 text-[var(--ch-error-text)]">{error}</p></main>;
  if (!report) return <main className="p-8">Loading report…</main>;

  return <main className="mx-auto max-w-4xl p-4 sm:p-8">
    <header className="mb-8 border-b pb-5"><p className="text-xs uppercase tracking-[.2em] text-[var(--ch-text-muted)]">Office Hub</p><h1 className="mt-2 text-3xl font-bold">{report.title}</h1><p className="mt-2 text-sm text-[var(--ch-text-muted)]">Secure report · link expires {new Date(report.expires_at).toLocaleString()}</p></header>
    {error ? <p className="mb-4 rounded-xl bg-[var(--ch-error-bg)] p-3 text-[var(--ch-error-text)]">{error}</p> : null}
    {report.items.map((item) => <article key={item.id} className="mb-8 break-inside-avoid rounded-2xl border bg-[var(--ch-surface)] p-5">
      <h2 className="text-2xl font-bold">{item.address} {item.unit_label || ""}</h2><p className="text-sm text-[var(--ch-text-muted)]">{item.inspection_date} · {item.inspection_type}</p>
      <div className="mt-4 grid grid-cols-2 gap-3"><div className="rounded-xl border p-3"><span className="text-sm text-[var(--ch-text-muted)]">Front yard</span><strong className="block text-2xl">{item.front_yard_score ?? "—"}/10</strong><p>{item.front_yard_notes || "No notes"}</p></div><div className="rounded-xl border p-3"><span className="text-sm text-[var(--ch-text-muted)]">Back yard</span><strong className="block text-2xl">{item.back_yard_score ?? "—"}/10</strong><p>{item.back_yard_notes || "No notes"}</p></div></div>
      <dl className="mt-4 space-y-2 text-sm"><div><dt className="font-bold">Building</dt><dd>{item.building_condition || "Not recorded"}{item.building_notes ? ` — ${item.building_notes}` : ""}</dd></div><div><dt className="font-bold">Occupancy</dt><dd>{item.occupancy_flag || "Not recorded"}</dd></div><div><dt className="font-bold">General summary</dt><dd>{item.general_notes || "No additional observations"}</dd></div></dl>
      {item.photos.length ? <div className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-3">{item.photos.map((photo) => <img key={photo.id} src={api.absolutePhotoUrl(photo.url!)} alt={photo.caption || `Inspection photo for ${item.address}`} className="aspect-square w-full rounded-xl object-cover" />)}</div> : <p className="mt-5 text-sm text-[var(--ch-text-muted)]">No inspection photos.</p>}
      <section className="mt-6 border-t pt-4"><h3 className="font-bold">Property discussion</h3>
        {item.comments.length ? <div className="mt-3 space-y-3">{item.comments.map((comment) => <div key={comment.id} className="rounded-xl bg-[var(--ch-surface-muted)] p-3"><div className="flex flex-wrap justify-between gap-2 text-sm"><strong>{comment.author_name}</strong><time className="text-[var(--ch-text-muted)]">{new Date(comment.created_at).toLocaleString()}</time></div><p className="mt-1 whitespace-pre-wrap">{comment.body}</p></div>)}</div> : <p className="mt-2 text-sm text-[var(--ch-text-muted)]">No comments yet. Start the discussion below.</p>}
        <div className="mt-4 grid gap-2"><input value={authorNames[item.id] || ""} onChange={(event) => setAuthorNames((current) => ({ ...current, [item.id]: event.target.value }))} className="rounded-xl border p-3" maxLength={100} placeholder="Your name"/><textarea value={drafts[item.id] || ""} onChange={(event) => setDrafts((current) => ({ ...current, [item.id]: event.target.value }))} className="min-h-28 rounded-xl border p-3" maxLength={5000} placeholder="Add a comment or reply…"/><button disabled={saving === item.id} onClick={() => void addComment(item.id)} className="justify-self-start rounded-xl bg-[var(--ch-accent)] px-5 py-3 font-bold text-white disabled:opacity-50">{saving === item.id ? "Posting…" : "Post comment"}</button></div>
      </section>
    </article>)}
  </main>;
}
