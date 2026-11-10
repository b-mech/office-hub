"use client";
import Link from "next/link";
import { useEffect, useMemo, useState, type FormEvent } from "react";
import { createStaffTicket, getStaffTicketOptions, type StaffTicketOptions, type TicketCategory, type TicketPriority } from "@/lib/api/maintenance";
const categories = ["plumbing","electrical","heating","cooling","appliance","doors_locks_windows","pests","exterior_grounds","structural","water_leak","no_heat","gas_smell","no_power","security","other"] as TicketCategory[];
const input = "mt-1 min-h-11 w-full rounded-xl border border-[var(--ch-border)] bg-[var(--ch-surface-strong)] px-3 py-2 text-sm";
export default function NewMaintenanceTicket() {
  const [options,setOptions] = useState<StaffTicketOptions>({properties:[],units:[]});
  const [propertyId,setPropertyId] = useState(""); const [unitId,setUnitId] = useState("");
  const [propertySearch,setPropertySearch] = useState(""); const [unitSearch,setUnitSearch] = useState("");
  const [category,setCategory] = useState<TicketCategory>("other"); const [priority,setPriority] = useState<TicketPriority>("routine");
  const [emergency,setEmergency] = useState(false); const [photos,setPhotos] = useState<File[]>([]);
  const [busy,setBusy] = useState(false); const [ready,setReady] = useState(false); const [error,setError] = useState("");
  const [created,setCreated] = useState<Awaited<ReturnType<typeof createStaffTicket>>|null>(null);
  useEffect(()=>{ getStaffTicketOptions().then(setOptions).catch(e=>setError(e.message)).finally(()=>setReady(true)); },[]);
  const properties = useMemo(()=>options.properties.filter(p=>p.id===Number(propertyId)||`${p.name} ${p.address}`.toLowerCase().includes(propertySearch.toLowerCase())),[options.properties,propertySearch,propertyId]);
  const units = useMemo(()=>options.units.filter(u=>u.property_id===Number(propertyId)&&(u.id===Number(unitId)||u.label.toLowerCase().includes(unitSearch.toLowerCase()))),[options.units,propertyId,unitSearch,unitId]);
  async function submit(event:FormEvent<HTMLFormElement>) {
    event.preventDefault();setError("");const data=new FormData(event.currentTarget);
    if(photos.length>10||photos.some(f=>f.size>10*1024*1024)){setError("Choose up to 10 photos, each 10 MB or smaller");return;}
    setBusy(true);
    try{setCreated(await createStaffTicket({ property_id:Number(propertyId),unit_id:unitId?Number(unitId):null,
      title:String(data.get("title")||""),description:String(data.get("description")||""),category,priority,is_emergency:emergency,
      reporter_name:String(data.get("reporter_name")||"")||null,reporter_phone:String(data.get("reporter_phone")||"")||null,
      sms_opt_in:data.get("sms_opt_in")==="on",entry_permission:String(data.get("entry_permission")) as "granted"|"denied"|"not_asked",
      entry_notes:String(data.get("entry_notes")||"")||null},photos));}
    catch(e){setError(e instanceof Error?e.message:"Could not create ticket");}finally{setBusy(false);}
  }
  return <main className="min-h-screen bg-[var(--ch-page-bg)] p-5 sm:p-8"><div className="mx-auto max-w-4xl">
    <Link href="/rentals/maintenance" className="text-sm text-[var(--ch-accent)]">← Maintenance queue</Link>
    <h1 className="mt-3 text-3xl font-semibold">New ticket</h1><p className="mt-2 text-sm text-[var(--ch-text-muted)]">Staff intake · classification starts the SLA. Emergency acknowledgement remains a separate action.</p>
    {error&&<p role="alert" className="my-4 rounded-xl border border-[var(--ch-error-border)] bg-[var(--ch-error-bg)] p-3">{error}</p>}
    {created?<section role="status" className="mt-6 rounded-2xl border border-[var(--ch-success-border)] bg-[var(--ch-success-bg)] p-6"><h2 className="text-xl font-semibold">{created.number} created</h2><p className="mt-2">Status: {created.status}. Confirmation: {created.confirmation.replaceAll("_"," ")}. SLA due {new Date(created.sla_due_at).toLocaleString()}.</p><Link className="mt-4 inline-block font-semibold underline" href={`/rentals/maintenance/${created.id}`}>Open ticket →</Link></section>:
    <form onSubmit={submit} className="mt-6 space-y-6 rounded-2xl border border-[var(--ch-border)] bg-[var(--ch-surface)] p-5 sm:p-7">
      <fieldset className="grid gap-4 sm:grid-cols-2"><legend className="mb-3 font-semibold">Location</legend>
        <label className="text-sm">Search properties<input aria-label="Search properties" value={propertySearch} onChange={e=>setPropertySearch(e.target.value)} className={input} placeholder="Address or property"/></label>
        <label className="text-sm">Search units<input aria-label="Search units" value={unitSearch} onChange={e=>setUnitSearch(e.target.value)} className={input} disabled={!propertyId} placeholder="Unit label"/></label>
        <label className="text-sm">Property *<select required aria-label="Property" className={input} value={propertyId} onChange={e=>{setPropertyId(e.target.value);setUnitId("");}}><option value="">Choose property</option>{properties.map(p=><option key={p.id} value={p.id}>{p.name} — {p.address}</option>)}</select></label>
        <label className="text-sm">Unit<select aria-label="Unit" className={input} value={unitId} onChange={e=>setUnitId(e.target.value)} disabled={!propertyId}><option value="">Common area / no unit</option>{units.map(u=><option key={u.id} value={u.id}>{u.label}</option>)}</select></label>
      </fieldset>
      <label className="block text-sm">Title *<input name="title" required maxLength={120} className={input} placeholder="Briefly describe the issue"/></label>
      <label className="block text-sm">Description *<textarea name="description" required minLength={10} maxLength={10000} rows={4} className={input}/></label>
      <div className="grid gap-4 sm:grid-cols-2"><label className="text-sm">Category<select aria-label="Category" value={category} onChange={e=>setCategory(e.target.value as TicketCategory)} className={input}>{categories.map(c=><option key={c} value={c}>{c.replaceAll("_"," ")}</option>)}</select></label>
      <label className="text-sm">Priority<select aria-label="Priority" value={priority} onChange={e=>setPriority(e.target.value as TicketPriority)} className={input}>{["routine","urgent","low","emergency"].map(p=><option key={p}>{p}</option>)}</select></label></div>
      <label className="flex items-center gap-3 text-sm"><input type="checkbox" checked={emergency} onChange={e=>setEmergency(e.target.checked)}/> Mark as emergency (hazard categories are automatically emergencies)</label>
      <fieldset className="grid gap-4 sm:grid-cols-2"><legend className="mb-3 font-semibold">Reporter & consent</legend><label className="text-sm">Name (optional)<input name="reporter_name" maxLength={150} className={input}/></label><label className="text-sm">Phone (optional)<input name="reporter_phone" type="tel" className={input}/></label><label className="flex items-start gap-3 text-sm sm:col-span-2"><input type="checkbox" name="sms_opt_in" className="mt-1"/> Reporter consented to a confirmation SMS. Existing opt-outs and the staging allowlist still apply.</label></fieldset>
      <div className="grid gap-4 sm:grid-cols-2"><label className="text-sm">Entry permission<select name="entry_permission" className={input}><option value="not_asked">Not asked</option><option value="granted">Granted</option><option value="denied">Denied</option></select></label><label className="text-sm">Photos (up to 10)<input aria-label="Photos" type="file" multiple accept="image/jpeg,image/png,image/webp,image/heic,image/heif" onChange={e=>setPhotos(Array.from(e.target.files||[]))} className={input}/></label></div>
      <label className="block text-sm">Entry notes<textarea name="entry_notes" rows={2} maxLength={2000} className={input}/></label><p className="text-xs text-[var(--ch-text-muted)]">Entry permission does not replace formal notice or documented consent for a scheduled visit.</p>
      <button disabled={busy||!ready||!propertyId} className="min-h-11 rounded-xl bg-[var(--ch-accent)] px-6 text-sm font-semibold text-white disabled:opacity-50">{busy?"Creating…":"Create ticket"}</button>
    </form>}</div></main>;
}
