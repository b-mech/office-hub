"use client";

import Script from "next/script";
import { FormEvent, use, useEffect, useState } from "react";

const BASE = process.env.NEXT_PUBLIC_API_URL || "/backend-api";
const emergency = [
  ["water_leak", "Water leak"], ["no_heat", "No heat"], ["gas_smell", "Gas smell"],
  ["no_power", "No power"], ["security", "Security / unsafe lock"],
] as const;
const routine = [
  ["plumbing", "Plumbing"], ["electrical", "Electrical"], ["heating", "Heating"],
  ["cooling", "Cooling"], ["appliance", "Appliance"], ["doors_locks_windows", "Doors / locks / windows"],
  ["pests", "Pests"], ["exterior_grounds", "Exterior / grounds"], ["structural", "Structural"], ["other", "Other"],
] as const;

type Config = { enabled:boolean;brand_name:string;emergency_phone:string;manitoba_hydro_emergency_phone:string;turnstile_site_key:string;emergency_messages:{gas_smell:string;default:string} };
type Context = { property_display_name:string;unit_label:string };

export default function IntakePage({ params }: { params: Promise<{token:string}> }) {
  const { token } = use(params);
  const [config, setConfig] = useState<Config | null>(null);
  const [context, setContext] = useState<Context | null>(null);
  const [category, setCategory] = useState("");
  const [entry, setEntry] = useState("not_asked");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [success, setSuccess] = useState<{ticket_number:string;phone:string}|null>(null);

  useEffect(() => {
    async function load() {
      try {
        const configResponse = await fetch(`${BASE}/api/public/maintenance/config`);
        const nextConfig = await configResponse.json();
        setConfig(nextConfig);
        document.title = `${nextConfig.brand_name} · Maintenance`;
        if (!nextConfig.enabled) return;
        const response = await fetch(`${BASE}/api/public/intake/${encodeURIComponent(token)}`);
        if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail || "This maintenance link is no longer available.");
        setContext(await response.json());
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : "This maintenance link is no longer available.");
      } finally {
        setLoading(false);
      }
    }
    void load();
  }, [token]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setError(""); setSubmitting(true);
    const body = new FormData(event.currentTarget);
    body.set("category", category);
    body.set("entry_permission", entry);
    try {
      const response = await fetch(`${BASE}/api/public/intake/${encodeURIComponent(token)}`, { method:"POST", body });
      const result = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(result.detail || "We couldn't submit your request. Please try again.");
      setSuccess(result);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Submission failed"); }
    finally { setSubmitting(false); }
  }

  const selectedEmergency = emergency.some(([value]) => value === category);
  const brand = config?.brand_name || "";
  const phoneHref = config?.emergency_phone ? `tel:${config.emergency_phone}` : undefined;
  const hydroHref = config?.manitoba_hydro_emergency_phone ? `tel:${config.manitoba_hydro_emergency_phone}` : undefined;

  return <main className="fixed inset-0 z-[100] overflow-y-auto bg-slate-50 text-slate-950">
    <div className="mx-auto min-h-full max-w-xl bg-white px-5 py-8 shadow-sm sm:my-6 sm:min-h-0 sm:rounded-3xl sm:px-8">
      <header>{brand ? <p className="font-bold text-teal-800">{brand}</p> : null}<h1 className="mt-2 text-3xl font-extrabold">Report a maintenance issue</h1>{context ? <p className="mt-2 text-slate-600">{context.property_display_name} · {context.unit_label}</p> : null}</header>
      {loading ? <p className="mt-8">Loading…</p> : null}
      {!loading && (!context || !config?.enabled) ? <section className="mt-8 rounded-2xl bg-slate-100 p-5"><h2 className="font-bold">This link isn&apos;t available</h2><p className="mt-2">Please contact {brand || "the property office"}{config?.emergency_phone ? ` at ${config.emergency_phone}` : ""}.</p></section> : null}
      {success ? <section className="mt-8 rounded-2xl bg-emerald-50 p-6"><h2 className="text-2xl font-bold">Got it — {success.ticket_number}.</h2><p className="mt-3">We&apos;ll text you at {success.phone}. Reply to that text anytime.</p></section> : null}
      {context && config?.enabled && !success ? <form onSubmit={submit} className="mt-8 space-y-7">
        <div className="grid gap-4 sm:grid-cols-2"><label className="font-semibold">Your name<input name="name" required className="mt-2 w-full rounded-xl border p-4 font-normal" autoComplete="name" /></label><label className="font-semibold">Mobile number<input name="phone" required inputMode="tel" className="mt-2 w-full rounded-xl border p-4 font-normal" autoComplete="tel" /></label></div>
        <fieldset><legend className="text-lg font-bold">What&apos;s the problem?</legend><p className="mt-3 text-sm font-bold uppercase tracking-wide text-red-700">Emergency issues</p><div className="mt-2 grid grid-cols-2 gap-2">{emergency.map(([value,label]) => <button type="button" key={value} onClick={() => setCategory(value)} className={`min-h-16 rounded-xl border-2 p-3 text-left font-bold ${category===value?"border-red-700 bg-red-100":"border-red-200 bg-red-50"}`}>{label}</button>)}</div><div className="mt-3 grid grid-cols-2 gap-2">{routine.map(([value,label]) => <button type="button" key={value} onClick={() => setCategory(value)} className={`min-h-14 rounded-xl border p-3 text-left ${category===value?"border-teal-700 bg-teal-50 font-bold":""}`}>{label}</button>)}</div><input required tabIndex={-1} aria-hidden className="h-px w-px opacity-0" value={category} onChange={() => undefined} /></fieldset>
        <label className="block text-lg font-bold">Description<textarea name="description" required minLength={10} rows={5} className="mt-2 w-full rounded-xl border p-4 font-normal" placeholder="Tell us what happened and where you see the problem." /></label>
        <label className="block font-bold">Photos (optional, up to 5)<input name="photos" type="file" multiple accept="image/jpeg,image/png,image/heic,image/heif,image/webp" capture="environment" className="mt-2 block w-full rounded-xl border p-4 font-normal" /></label>
        <fieldset><legend className="text-lg font-bold">Can we enter if you&apos;re not home?</legend><div className="mt-3 flex gap-3"><button type="button" onClick={() => setEntry("granted")} className={`flex-1 rounded-xl border p-4 font-bold ${entry==="granted"?"border-teal-700 bg-teal-50":""}`}>Yes</button><button type="button" onClick={() => setEntry("denied")} className={`flex-1 rounded-xl border p-4 font-bold ${entry==="denied"?"border-teal-700 bg-teal-50":""}`}>No</button></div><textarea name="entry_notes" rows={3} className="mt-3 w-full rounded-xl border p-4" placeholder="Pets, alarm, best times…" /></fieldset>
        {selectedEmergency ? <section className="rounded-2xl border-2 border-red-600 bg-red-50 p-5"><h2 className="text-xl font-extrabold text-red-800">Call now</h2><p className="mt-2 font-semibold">{category === "gas_smell" ? config.emergency_messages.gas_smell : config.emergency_messages.default}</p><div className="mt-4 grid gap-2">{category === "gas_smell" ? <a href="tel:911" className="rounded-xl bg-red-700 p-4 text-center font-bold text-white">Call 911</a> : null}{category === "gas_smell" && hydroHref ? <a href={hydroHref} className="rounded-xl border border-red-700 p-4 text-center font-bold text-red-800">Call Manitoba Hydro · {config.manitoba_hydro_emergency_phone}</a> : null}{phoneHref ? <a href={phoneHref} className="rounded-xl border border-red-700 p-4 text-center font-bold text-red-800">Call {brand} · {config.emergency_phone}</a> : null}</div></section> : null}
        {config.turnstile_site_key ? <><Script src="https://challenges.cloudflare.com/turnstile/v0/api.js" async defer /><div className="cf-turnstile" data-sitekey={config.turnstile_site_key} /></> : null}
        {error ? <p role="alert" className="rounded-xl bg-red-50 p-4 font-semibold text-red-800">{error}</p> : null}
        <button disabled={submitting || !category} className="w-full rounded-xl bg-teal-800 p-4 text-lg font-extrabold text-white disabled:opacity-50">{submitting ? "Submitting…" : "Submit request"}</button>
      </form> : null}
    </div>
  </main>;
}
