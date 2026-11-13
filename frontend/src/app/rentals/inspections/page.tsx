"use client";

import { useEffect, useMemo, useState } from "react";
import * as api from "@/lib/api/rental-inspections";
import { formatDate, inspectionStatusLabel, plural, sortInspectionUnits, todayIso, type InspectionSort } from "@/lib/rentals-ux";

async function resize(file: File): Promise<File> {
  const image = await createImageBitmap(file);
  const scale = Math.min(1, 1920 / Math.max(image.width, image.height));
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(image.width * scale);
  canvas.height = Math.round(image.height * scale);
  canvas.getContext("2d")!.drawImage(image, 0, 0, canvas.width, canvas.height);
  const blob = await new Promise<Blob>((resolve, reject) =>
    canvas.toBlob(
      (result) => result ? resolve(result) : reject(new Error("Photo resize failed")),
      "image/jpeg",
      0.8,
    ),
  );
  return new File([blob], file.name.replace(/\.[^.]+$/, "") + ".jpg", { type: "image/jpeg" });
}

function StatusBadge({ status }: { status: string }) {
  const submitted = status === "submitted";
  return <span className={`inline-flex rounded-full border px-2 py-0.5 text-xs font-semibold ${submitted ? "border-[var(--ch-success-border)] bg-[var(--ch-success-bg)] text-[var(--ch-success-text)]" : "border-[var(--ch-warning-border)] bg-[var(--ch-warning-bg)] text-[var(--ch-warning-text)]"}`}>{inspectionStatusLabel(status)}</span>;
}

const unitTitle = (unit: api.Unit) => `${unit.street_address}${unit.unit_label ? ` · ${unit.unit_label}` : ""}`;

export default function Page() {
  const [units, setUnits] = useState<api.Unit[]>([]);
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<InspectionSort>("oldest_inspection");
  const sortedUnits = useMemo(() => sortInspectionUnits(units, sort), [units, sort]);
  const [unit, setUnit] = useState<api.Unit | null>(null);
  const [item, setItem] = useState<api.Inspection | null>(null);
  const [history, setHistory] = useState<api.Inspection[]>([]);
  const [editing, setEditing] = useState(false);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [starting, setStarting] = useState(false);
  const [saveMessage, setSaveMessage] = useState("");
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    api.units(query).then(setUnits).catch((cause) => setError(cause.message));
  }, [query]);

  useEffect(() => {
    if (item && dirty) {
      window.localStorage.setItem(`officehub-inspection-draft:${item.id}`, JSON.stringify(item));
    }
  }, [dirty, item]);

  /** Selecting a unit only reads its history. Nothing is created until "Start inspection". */
  async function selectUnit(selected: api.Unit) {
    setError(""); setSaveMessage(""); setItem(null);
    setUnit(selected);
    setHistory(await api.history(selected.id));
  }

  function backToUnit() {
    if (dirty && !window.confirm("Leave without saving? Unsaved changes stay in this browser as a recovery copy.")) return;
    setItem(null); setEditing(false); setError(""); setSaveMessage("");
    if (unit) void api.history(unit.id).then(setHistory).catch((cause) => setError(cause.message));
  }

  function openInspection(inspection: api.Inspection, edit: boolean) {
    setError(""); setSaveMessage("");
    const cached = edit ? window.localStorage.getItem(`officehub-inspection-draft:${inspection.id}`) : null;
    if (cached) {
      try {
        setItem({ ...inspection, ...JSON.parse(cached), photos: inspection.photos });
        setDirty(true);
        setSaveMessage("Recovered unsaved changes from this browser.");
      } catch {
        window.localStorage.removeItem(`officehub-inspection-draft:${inspection.id}`);
        setItem(inspection); setDirty(false);
      }
    } else {
      setItem(inspection); setDirty(false);
    }
    setEditing(edit);
  }

  async function startInspection() {
    if (!unit) return;
    const today = todayIso();
    const existing = history.find((inspection) => inspection.inspection_date === today && inspection.status !== "submitted");
    if (existing) { openInspection(existing, true); return; }
    setStarting(true); setError("");
    try {
      const created = await api.create(unit.id);
      setHistory((current) => [created, ...current]);
      openInspection(created, true);
      setSaveMessage("Draft started. It is saved when you tap Save draft or Submit.");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not start inspection"); }
    finally { setStarting(false); }
  }

  function markDirty() {
    setDirty(true);
    setSaveMessage("");
  }

  async function save() {
    if (!item || !editing) return item;
    setSaving(true);
    setError("");
    setSaveMessage("");
    try {
      const saved = await api.patch(item.id, item);
      setItem(saved);
      setDirty(false);
      window.localStorage.removeItem(`officehub-inspection-draft:${saved.id}`);
      setSaveMessage(saved.status === "submitted" ? "Changes saved." : "Draft saved.");
      return saved;
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not save inspection.");
      throw cause;
    } finally {
      setSaving(false);
    }
  }

  async function submit() {
    if (!window.confirm("Submit this inspection? It will count as the unit's latest inspection.")) return;
    try {
      const saved = await save();
      if (!saved) return;
      await api.submit(saved.id);
      setDirty(false);
      setItem(null); setEditing(false);
      if (unit) setHistory(await api.history(unit.id));
      setSaveMessage("Inspection submitted.");
    } catch {
      // save() and the API client provide the user-facing error.
    }
  }

  function remove() {
    if (!item) return;
    const what = item.status === "submitted" ? "this submitted inspection" : "this draft";
    if (!window.confirm(`Delete ${what} from ${formatDate(item.inspection_date)} and its ${plural(item.photos.length, "photo")}? This cannot be undone.`)) return;
    api.deleteInspection(item.id).then(() => {
      window.localStorage.removeItem(`officehub-inspection-draft:${item.id}`);
      setHistory((current) => current.filter((candidate) => candidate.id !== item.id));
      setItem(null); setEditing(false); setDirty(false);
    }).catch((cause) => setError(cause.message));
  }

  // ---------- Inspection (view or edit) ----------
  if (item && unit) {
    const readOnly = !editing;
    return (
      <div className="mx-auto flex min-h-screen max-w-xl flex-col">
        <header className="sticky top-0 z-10 bg-[var(--ch-sidebar-bg)] p-4 text-white">
          <button onClick={backToUnit}>← {unitTitle(unit)}</button>
          <h1 className="mt-2 flex flex-wrap items-center gap-2 text-xl font-bold">Inspection {formatDate(item.inspection_date)} <StatusBadge status={item.status} /></h1>
          <p className="text-xs opacity-80">{unitTitle(unit)} · Unit #{unit.id} · {item.inspection_type}{dirty ? " · unsaved changes" : ""}</p>
        </header>
        {readOnly ? <div className="m-4 flex items-center justify-between gap-3 rounded-xl border bg-[var(--ch-surface)] p-3 text-sm font-semibold"><span>Viewing {item.status === "submitted" ? "a submitted inspection" : "a draft"} (read-only)</span><button onClick={() => openInspection(item, true)} className="rounded-lg border px-3 py-2">{item.status === "submitted" ? "Edit inspection" : "Continue draft"}</button></div> : null}
        <fieldset disabled={readOnly} className="flex-1 space-y-5 p-4 disabled:opacity-80">
          {error ? <p className="text-[var(--ch-error-text)]">{error}</p> : null}
          {saveMessage ? <p className="text-[var(--ch-success-text)]">{saveMessage}</p> : null}
          <label className="block">Type
            <select value={item.inspection_type} onChange={(event) => { setItem({ ...item, inspection_type: event.target.value }); markDirty(); }} className="mt-1 w-full rounded-xl border p-3">
              <option>exterior</option><option>interior</option>
            </select>
          </label>
          {(["front_yard", "back_yard"] as const).map((key) => (
            <section key={key}>
              <h2 className="text-lg font-bold">{key === "front_yard" ? "Front yard" : "Back yard"}</h2>
              <input type="number" min="1" max="10" value={item[`${key}_score`] ?? ""} onChange={(event) => { setItem({ ...item, [`${key}_score`]: event.target.value ? Number(event.target.value) : null }); markDirty(); }} className="mt-2 w-full rounded-xl border p-4 text-xl" placeholder="Score 1–10" />
              <textarea value={item[`${key}_notes`] || ""} onChange={(event) => { setItem({ ...item, [`${key}_notes`]: event.target.value }); markDirty(); }} className="mt-2 w-full rounded-xl border p-3" placeholder="Notes / why unseen" />
            </section>
          ))}
          <input value={item.building_condition || ""} onChange={(event) => { setItem({ ...item, building_condition: event.target.value }); markDirty(); }} className="w-full rounded-xl border p-3" placeholder="Building condition" />
          <textarea value={item.building_notes || ""} onChange={(event) => { setItem({ ...item, building_notes: event.target.value }); markDirty(); }} className="w-full rounded-xl border p-3" placeholder="Building notes" />
          <select value={item.occupancy_flag || ""} onChange={(event) => { setItem({ ...item, occupancy_flag: event.target.value }); markDirty(); }} className="w-full rounded-xl border p-3">
            <option value="">Occupancy unsure</option><option>occupied</option><option>vacant</option><option>unsure</option>
          </select>
          <textarea value={item.general_notes || ""} onChange={(event) => { setItem({ ...item, general_notes: event.target.value }); markDirty(); }} className="w-full rounded-xl border p-3" placeholder="General notes" />
          <section>
            <h2 className="font-bold">Photos</h2>
            <div className="grid grid-cols-3 gap-2">
              {item.photos.map((photo) => <div key={photo.id}>{photo.preview_url ? <a href={photo.preview_url} target="_blank"><img src={photo.preview_url} alt="Inspection" className="h-24 w-full rounded object-cover" /></a> : null}{!readOnly ? <button onClick={() => { if (window.confirm("Delete this photo?")) void api.remove(item.id, photo.id).then(() => setItem({ ...item, photos: item.photos.filter((candidate) => candidate.id !== photo.id) })); }} className="text-xs text-[var(--ch-error-text)]">Delete</button> : null}</div>)}
              {!item.photos.length ? <p className="col-span-3 text-sm text-[var(--ch-text-muted)]">No photos yet.</p> : null}
            </div>
            {!readOnly ? <>
            <label className="mt-3 block rounded-xl bg-[var(--ch-accent)] p-4 text-center font-bold text-white">Take photo
              <input hidden type="file" accept="image/*" capture="environment" onChange={async (event) => { const file = event.target.files?.[0]; if (!file) return; try { const photos = await api.upload(item.id, await resize(file)); setItem({ ...item, photos: [...item.photos, ...photos] }); } catch (cause) { setError(`${cause instanceof Error ? cause.message : "Upload failed"} — select the photo again to retry`); } }} />
            </label>
            <label className="mt-2 block rounded-xl border p-4 text-center">Choose photos
              <input hidden multiple type="file" accept="image/*" onChange={async (event) => { for (const file of Array.from(event.target.files || [])) { try { const photos = await api.upload(item.id, await resize(file)); setItem((current) => current ? { ...current, photos: [...current.photos, ...photos] } : current); } catch (cause) { setError(`${cause instanceof Error ? cause.message : "Upload failed"} — retry failed photo`); } } }} />
            </label></> : null}
          </section>
        </fieldset>
        {!readOnly ? <footer className="sticky bottom-0 z-10 mt-4 flex gap-2 border-t bg-[var(--ch-surface)] p-4 shadow-[0_-4px_12px_rgba(0,0,0,0.06)]">
          <button onClick={remove} className="rounded-xl border border-[var(--ch-error-text)] px-4 py-3 font-bold text-[var(--ch-error-text)]">Delete</button>
          <button disabled={saving} onClick={() => void save().then((saved) => { if (saved?.status === "submitted") setEditing(false); }).catch(() => undefined)} className="flex-1 rounded-xl border px-4 py-3 font-bold disabled:opacity-50">{saving ? "Saving…" : item.status === "submitted" ? "Save changes" : "Save draft"}</button>
          {item.status !== "submitted" ? <button disabled={saving} onClick={() => void submit()} className="flex-1 rounded-xl bg-[var(--ch-accent)] px-4 py-3 font-bold text-white disabled:opacity-50">{saving ? "Saving…" : "Submit"}</button> : null}
        </footer> : null}
      </div>
    );
  }

  // ---------- Unit view (read-only history + explicit start) ----------
  if (unit) {
    const today = todayIso();
    const todaysDraft = history.find((inspection) => inspection.inspection_date === today && inspection.status !== "submitted");
    return <div className="mx-auto max-w-2xl p-4">
      <button onClick={() => { setUnit(null); setHistory([]); setError(""); setSaveMessage(""); }} className="text-sm font-semibold text-[var(--ch-accent)]">← All units</button>
      <h1 className="mt-2 text-2xl font-bold">{unitTitle(unit)}</h1>
      <p className="text-sm text-[var(--ch-text-muted)]">{unit.group_name ? `${unit.group_name} · ` : ""}Property #{unit.property_id} · Unit #{unit.id}</p>
      {error ? <p className="mt-3 text-[var(--ch-error-text)]">{error}</p> : null}
      {saveMessage ? <p className="mt-3 text-[var(--ch-success-text)]">{saveMessage}</p> : null}
      <div className="mt-4 flex flex-wrap gap-2">
        <button disabled={starting} onClick={() => void startInspection()} className="rounded-xl bg-[var(--ch-accent)] px-5 py-3 font-bold text-white disabled:opacity-50">{todaysDraft ? "Continue today's draft" : starting ? "Starting…" : "Start inspection"}</button>
        <a href={`/rentals/units/${unit.id}`} className="rounded-xl border px-4 py-3 font-semibold">Unit page</a>
        <a href={`/rentals/units/${unit.id}?tab=leases`} className="rounded-xl border px-4 py-3 font-semibold">Leases</a>
      </div>
      <h2 className="mt-6 text-lg font-bold">Inspection history</h2>
      {history.length === 0 ? <p className="mt-2 rounded-xl border border-dashed p-6 text-sm text-[var(--ch-text-muted)]">No inspections yet. “Start inspection” creates a draft for today.</p> : <ul className="mt-2 space-y-2">{history.map((inspection) => <li key={inspection.id} className="flex flex-wrap items-center gap-3 rounded-xl border bg-[var(--ch-surface)] p-3">
        <div className="min-w-0 flex-1"><strong>{formatDate(inspection.inspection_date)}</strong> <StatusBadge status={inspection.status} /><div className="text-sm text-[var(--ch-text-muted)]">{inspection.inspection_type} · {plural(inspection.photos.length, "photo")}{inspection.front_yard_score != null ? ` · front ${inspection.front_yard_score}` : ""}{inspection.back_yard_score != null ? ` · back ${inspection.back_yard_score}` : ""}</div></div>
        <button onClick={() => openInspection(inspection, false)} className="rounded-lg border px-3 py-2 text-sm font-semibold">View</button>
        {inspection.status !== "submitted" ? <button onClick={() => openInspection(inspection, true)} className="rounded-lg border px-3 py-2 text-sm font-semibold">Continue draft</button> : null}
      </li>)}</ul>}
    </div>;
  }

  // ---------- Unit list ----------
  const rotationCount = units.filter((candidate) => candidate.maintenance_qr_rotation_recommended).length;
  return <div className="mx-auto max-w-2xl p-4">
    <h1 className="text-3xl font-bold">Rental Inspections</h1>
    <p className="mt-1 text-sm text-[var(--ch-text-muted)]">Pick a unit to see its history. Nothing is created until you tap “Start inspection”.</p>
    <div className="my-5 grid gap-3 sm:grid-cols-[1fr_auto]">
      <label className="text-sm font-medium">Search<input type="search" value={query} onChange={(event) => setQuery(event.target.value)} className="mt-1 w-full rounded-xl border p-3 font-normal" placeholder="Address or group" /></label>
      <label className="text-sm font-medium">Sort<select value={sort} onChange={(event) => setSort(event.target.value as InspectionSort)} className="mt-1 w-full rounded-xl border p-3 font-normal"><option value="oldest_inspection">Least recently inspected</option><option value="recent_inspection">Most recently inspected</option><option value="address">Address A–Z</option></select></label>
    </div>
    <div className="mb-3 flex flex-wrap items-center justify-between gap-2 text-sm text-[var(--ch-text-muted)]">
      <span aria-live="polite">{plural(units.length, "unit")}</span>
      {rotationCount ? <span id="qr-legend"><span aria-hidden="true">QR ⚠</span> = maintenance QR code should be rotated (open the unit page to reissue it). {plural(rotationCount, "unit")} flagged.</span> : null}
    </div>
    {error ? <p role="alert" className="text-[var(--ch-error-text)]">{error}</p> : null}
    {query && !units.length ? <p className="rounded-xl border border-dashed p-6 text-center text-sm text-[var(--ch-text-muted)]">No units match “{query}”. <button onClick={() => setQuery("")} className="font-semibold text-[var(--ch-accent)] underline">Clear search</button></p> : null}
    {sortedUnits.map((candidate) => <div key={candidate.id} className="mb-2 flex flex-wrap rounded-xl border sm:flex-nowrap">
      <button onClick={() => selectUnit(candidate).catch((cause) => setError(cause.message))} className="min-w-0 flex-1 basis-full p-4 text-left sm:basis-auto"><strong>{candidate.street_address} {candidate.unit_label || ""}</strong><div className="text-sm text-[var(--ch-text-muted)]">{candidate.group_name ? `${candidate.group_name} · ` : ""}Unit #{candidate.id} · {candidate.last_inspection ? `last inspected ${formatDate(candidate.last_inspection.inspection_date)}` : "never inspected"}</div></button>
      <div className="flex gap-2 px-2 pb-2 sm:items-center sm:pb-0">
        <a href={`/rentals/units/${candidate.id}?tab=leases`} className="rounded-lg border px-3 py-2 text-sm font-semibold">Leases</a>
        <a href={`/rentals/units/${candidate.id}`} title={candidate.maintenance_qr_rotation_recommended ? "Maintenance QR code should be rotated" : "Unit page and maintenance QR code"} aria-label={candidate.maintenance_qr_rotation_recommended ? `QR code for unit ${candidate.id}: rotation recommended` : `QR code for unit ${candidate.id}`} aria-describedby={candidate.maintenance_qr_rotation_recommended ? "qr-legend" : undefined} className="rounded-lg border px-3 py-2 text-sm font-semibold">QR{candidate.maintenance_qr_rotation_recommended ? " ⚠" : ""}</a>
      </div>
    </div>)}
  </div>;
}
