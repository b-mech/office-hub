"use client";

import { useEffect, useState } from "react";
import * as api from "@/lib/api/rental-inspections";

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

export default function Page() {
  const [units, setUnits] = useState<api.Unit[]>([]);
  const [query, setQuery] = useState("");
  const [unit, setUnit] = useState<api.Unit | null>(null);
  const [item, setItem] = useState<api.Inspection | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.units(query).then(setUnits).catch((cause) => setError(cause.message));
  }, [query]);

  async function open(selected: api.Unit) {
    setError("");
    setUnit(selected);
    const history = await api.history(selected.id);
    const today = new Date().toISOString().slice(0, 10);
    const existing = history.find((inspection) => inspection.inspection_date === today);
    setItem(existing || await api.create(selected.id));
  }

  async function save() {
    if (item && item.status !== "submitted") setItem(await api.patch(item.id, item));
  }

  if (item && unit) {
    const readOnly = item.status === "submitted";
    return (
      <main className="mx-auto max-w-xl pb-28">
        <header className="sticky top-0 z-10 bg-[var(--ch-sidebar-bg)] p-4 text-white">
          <button onClick={() => { setItem(null); setUnit(null); setError(""); }}>← Units</button>
          <h1 className="mt-2 text-xl font-bold">{unit.street_address} {unit.unit_label || ""}</h1>
        </header>
        {readOnly ? <p className="m-4 rounded-xl bg-[var(--ch-success-bg)] p-3 text-sm font-semibold text-[var(--ch-success-text)]">Submitted inspection · read only</p> : null}
        <fieldset disabled={readOnly} className="space-y-5 p-4 disabled:opacity-80">
          {error ? <p className="text-[var(--ch-error-text)]">{error}</p> : null}
          <label className="block">Type
            <select value={item.inspection_type} onChange={(event) => setItem({ ...item, inspection_type: event.target.value })} className="mt-1 w-full rounded-xl border p-3">
              <option>exterior</option><option>interior</option>
            </select>
          </label>
          {(["front_yard", "back_yard"] as const).map((key) => (
            <section key={key}>
              <h2 className="text-lg font-bold">{key === "front_yard" ? "Front yard" : "Back yard"}</h2>
              <input type="number" min="1" max="10" value={item[`${key}_score`] ?? ""} onChange={(event) => setItem({ ...item, [`${key}_score`]: event.target.value ? Number(event.target.value) : null })} onBlur={save} className="mt-2 w-full rounded-xl border p-4 text-xl" placeholder="Score 1–10" />
              <textarea value={item[`${key}_notes`] || ""} onChange={(event) => setItem({ ...item, [`${key}_notes`]: event.target.value })} onBlur={save} className="mt-2 w-full rounded-xl border p-3" placeholder="Notes / why unseen" />
            </section>
          ))}
          <input value={item.building_condition || ""} onChange={(event) => setItem({ ...item, building_condition: event.target.value })} onBlur={save} className="w-full rounded-xl border p-3" placeholder="Building condition" />
          <textarea value={item.building_notes || ""} onChange={(event) => setItem({ ...item, building_notes: event.target.value })} onBlur={save} className="w-full rounded-xl border p-3" placeholder="Building notes" />
          <select value={item.occupancy_flag || ""} onChange={(event) => setItem({ ...item, occupancy_flag: event.target.value })} onBlur={save} className="w-full rounded-xl border p-3">
            <option value="">Occupancy unsure</option><option>occupied</option><option>vacant</option><option>unsure</option>
          </select>
          <textarea value={item.general_notes || ""} onChange={(event) => setItem({ ...item, general_notes: event.target.value })} onBlur={save} className="w-full rounded-xl border p-3" placeholder="General notes" />
          <section>
            <h2 className="font-bold">Photos</h2>
            <div className="grid grid-cols-3 gap-2">
              {item.photos.map((photo) => <div key={photo.id}>{photo.preview_url ? <a href={photo.preview_url} target="_blank"><img src={photo.preview_url} alt="Inspection" className="h-24 w-full rounded object-cover" /></a> : null}<button onClick={() => api.remove(item.id, photo.id).then(() => setItem({ ...item, photos: item.photos.filter((candidate) => candidate.id !== photo.id) }))} className="text-xs text-[var(--ch-error-text)]">Delete</button></div>)}
            </div>
            <label className="mt-3 block rounded-xl bg-[var(--ch-accent)] p-4 text-center font-bold text-white">Take photo
              <input hidden type="file" accept="image/*" capture="environment" onChange={async (event) => { const file = event.target.files?.[0]; if (!file) return; try { const photos = await api.upload(item.id, await resize(file)); setItem({ ...item, photos: [...item.photos, ...photos] }); } catch (cause) { setError(`${cause instanceof Error ? cause.message : "Upload failed"} — select the photo again to retry`); } }} />
            </label>
            <label className="mt-2 block rounded-xl border p-4 text-center">Choose photos
              <input hidden multiple type="file" accept="image/*" onChange={async (event) => { for (const file of Array.from(event.target.files || [])) { try { const photos = await api.upload(item.id, await resize(file)); setItem((current) => current ? { ...current, photos: [...current.photos, ...photos] } : current); } catch (cause) { setError(`${cause instanceof Error ? cause.message : "Upload failed"} — retry failed photo`); } } }} />
            </label>
          </section>
        </fieldset>
        {!readOnly ? <footer className="fixed bottom-0 left-0 right-0 flex gap-2 border-t bg-[var(--ch-surface)] p-4 lg:left-56">
          <button onClick={save} className="flex-1 rounded-xl border p-4 font-bold">Save Draft</button>
          <button onClick={() => save().then(() => api.submit(item.id)).then(() => { setItem(null); setUnit(null); }).catch((cause) => setError(cause.message))} className="flex-1 rounded-xl bg-[var(--ch-accent)] p-4 font-bold text-white">Submit</button>
        </footer> : null}
      </main>
    );
  }

  return <main className="mx-auto max-w-2xl p-4"><h1 className="text-3xl font-bold">Rental Inspections</h1><input value={query} onChange={(event) => setQuery(event.target.value)} className="my-5 w-full rounded-xl border p-4" placeholder="Search address or group" />{error ? <p className="text-[var(--ch-error-text)]">{error}</p> : null}{units.map((candidate) => <button key={candidate.id} onClick={() => open(candidate).catch((cause) => setError(cause.message))} className="mb-2 block w-full rounded-xl border p-4 text-left"><strong>{candidate.street_address} {candidate.unit_label || ""}</strong><div className="text-sm text-[var(--ch-text-muted)]">{candidate.group_name} · {candidate.last_inspection ? `last inspected ${candidate.last_inspection.inspection_date}` : "never inspected"}</div></button>)}</main>;
}
