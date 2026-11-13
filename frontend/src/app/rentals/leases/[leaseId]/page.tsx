"use client";

import { use, useCallback, useEffect, useMemo, useState } from "react";
import * as api from "@/lib/api/lease-agreements";

type Values = Record<string, unknown>;
const MONEY = new Set(["basic_rent", "parking_amount", "other_charge_amount", "rent_discount",
  "security_deposit_amount", "pet_deposit_amount", "above_guideline_rent", "discount_increase_amount",
  "discount_reduced_amount", "agi_max_amount"]);
const DATES = new Set(["fixed_start", "fixed_end", "periodic_start", "security_deposit_date", "pet_deposit_date",
  "guideline_increase_date", "above_guideline_date"]);
function dateInput(value: unknown): string {
  if (!value) return "";
  const text = String(value);
  if (/^\d{4}-\d{2}-\d{2}$/.test(text)) return text;
  const parsed = new Date(`${text} 12:00:00 GMT`);
  return Number.isNaN(parsed.getTime()) ? "" : parsed.toISOString().slice(0, 10);
}
const amount = (value: unknown) => Number(String(value || "0").replaceAll(",", "")) || 0;
const formatted = (value: number) => value.toLocaleString("en-CA", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export default function LeaseEditor({ params }: { params: Promise<{ leaseId: string }> }) {
  const { leaseId } = use(params);
  const [lease, setLease] = useState<api.Lease | null>(null);
  const [values, setValues] = useState<Values>({});
  const [property, setProperty] = useState<api.Property | null>(null);
  const [records, setRecords] = useState<Awaited<ReturnType<typeof api.tenantRecords>>>([]);
  const [task, setTask] = useState<Awaited<ReturnType<typeof api.leaseTask>>>(null);
  const [selected, setSelected] = useState<Record<number, boolean>>({});
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const refresh = useCallback(async () => {
    const current = await api.getLease(leaseId);
    setLease(current); setValues(current.context); setDirty(false);
    const unit = await api.unitLeases(current.unit_id);
    setProperty(unit.property);
    if (current.contact_form_data) setRecords(await api.tenantRecords(leaseId));
    setTask(await api.leaseTask(leaseId));
  }, [leaseId]);
  useEffect(() => { void refresh().catch(cause => setError(cause.message)); }, [refresh]);
  const editable = lease?.status === "draft";
  const rentPayable = useMemo(() => amount(values.basic_rent) + amount(values.parking_amount) + amount(values.other_charge_amount), [values]);
  const actualRent = useMemo(() => rentPayable - amount(values.rent_discount), [rentPayable, values.rent_discount]);
  const term = values.fixed_start || values.fixed_end ? "fixed" : values.periodic_start || values.periodic_period ? "periodic" : "fixed";
  const tenants = (values.tenants as api.Tenant[] | undefined) || [];

  function set(key: string, value: unknown) { setValues(current => ({ ...current, [key]: value })); setDirty(true); setMessage(""); }
  function setTerm(next: "fixed" | "periodic") {
    setValues(current => ({ ...current, fixed_start: next === "fixed" ? current.fixed_start : null,
      fixed_end: next === "fixed" ? current.fixed_end : null,
      periodic_start: next === "periodic" ? current.periodic_start : null,
      periodic_period: next === "periodic" ? current.periodic_period : null }));
    setDirty(true);
  }
  function field(key: string, label: string, options?: { textarea?: boolean; placeholder?: string; required?: boolean }) {
    const value = DATES.has(key) ? dateInput(values[key]) : String(values[key] ?? "");
    return <label key={key} className="block text-sm font-semibold">{label}{options?.required ? " *" : ""}
      {options?.textarea ? <textarea disabled={!editable} value={value} placeholder={options.placeholder} onChange={e => set(key, e.target.value || null)} className="mt-1 min-h-24 w-full rounded-lg border p-2 font-normal disabled:bg-slate-50" />
        : <input disabled={!editable} type={DATES.has(key) ? "date" : MONEY.has(key) ? "text" : "text"} inputMode={MONEY.has(key) ? "decimal" : undefined}
            value={value} placeholder={options?.placeholder} onChange={e => set(key, e.target.value || null)} className="mt-1 block w-full rounded-lg border p-2 font-normal disabled:bg-slate-50" />}
    </label>;
  }
  function section(title: string, content: React.ReactNode) { return <section className="rounded-2xl border bg-[var(--ch-surface)] p-5"><h2 className="mb-4 text-lg font-bold">{title}</h2>{content}</section>; }

  async function save(): Promise<api.Lease> {
    const result = await api.saveLease(leaseId, values);
    setLease(result); setValues(result.context); setDirty(false); setMessage("Draft saved.");
    return result;
  }
  async function run(action: "save" | "preview" | "send") {
    if (!lease) return;
    if (action === "send") {
      if (dirty || !lease.draft_pdf_key) { setError("Save and preview the current draft before sending."); return; }
      const recipients = tenants.map(t => `${t.name} <${t.email}>`).join("\n");
      if (!window.confirm(`Send for signature?\n\nLandlord first: Robert Wieler\nThen:\n${recipients}`)) return;
    }
    const previewWindow = action === "preview" ? window.open("", "_blank") : null;
    setBusy(true); setError(""); setMessage("");
    try {
      if (action === "save") await save();
      if (action === "preview") {
        await save();
        const pdf = await api.preview(leaseId);
        const url = URL.createObjectURL(pdf);
        if (previewWindow) previewWindow.location.href = url;
        else window.open(url, "_blank");
        await refresh();
        setMessage("Preview is ready. This PDF will be sent for signature.");
      }
      if (action === "send") { const sent = await api.sendLease(leaseId); setLease(sent); setMessage("Lease sent to the landlord for signature."); }
    } catch (cause) {
      previewWindow?.close(); setError(cause instanceof Error ? cause.message : "Lease action failed");
    } finally { setBusy(false); }
  }

  async function saveUtilityDefault() {
    if (!property) return;
    setBusy(true); setError("");
    try {
      await api.updateProperty(property.id, { municipality: property.municipality || "", is_multiplex: property.is_multiplex,
        is_condo: property.is_condo, lease_utility_override: {
          services_tenant_pays: String(values.services_tenant_pays || ""),
          services_landlord_pays: String(values.services_landlord_pays || ""),
          utility_exceptions: values.utility_exceptions ? String(values.utility_exceptions) : null } });
      setMessage("Utility wording saved as this property's default.");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not save property default"); }
    finally { setBusy(false); }
  }

  async function apply() {
    if (!lease?.contact_form_data) return;
    const captured = lease.contact_form_data.tenants || [];
    const updates = records.filter(r => selected[r.id]).map(r => {
      const value = captured.find(t => t.name === r.name);
      return { tenant_id: r.id, phone: value?.phone || r.phone, email: value?.email || r.email };
    });
    if (!updates.length || !window.confirm(`Apply captured contact details to ${updates.length} tenant record(s)?`)) return;
    setBusy(true); setError("");
    try { await api.applyContacts(leaseId, updates); setRecords(await api.tenantRecords(leaseId)); setSelected({}); setMessage("Selected tenant records updated."); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Could not apply contacts"); }
    finally { setBusy(false); }
  }

  return <div className="mx-auto max-w-5xl space-y-5 p-6">
    <a className="text-sm font-semibold underline" href={lease ? `/rentals/units/${lease.unit_id}` : "/rentals"}>← Rental unit</a>
    <div className="flex flex-wrap items-center justify-between gap-3"><div><h1 className="text-3xl font-bold">Residential tenancy agreement</h1><p className="text-sm text-[var(--ch-text-muted)]">{String(values.unit_address || "")} · {lease?.display_status || "Loading"}</p></div>{lease?.signed_pdf_box_url && <a className="rounded-lg border px-4 py-2 font-semibold" href={lease.signed_pdf_box_url} target="_blank" rel="noreferrer">Signed copy in Box</a>}</div>
    {error && <p role="alert" className="rounded-lg bg-red-50 p-3 text-red-800">{error}</p>}{message && <p role="status" className="rounded-lg bg-green-50 p-3 text-green-800">{message}</p>}
    {section("1. Tenants", <div className="space-y-3">{tenants.map((tenant, i) => <div key={i} className="grid gap-2 rounded-xl border p-3 sm:grid-cols-[1fr_1fr_1fr_auto]">
      {(["name", "email", "phone"] as const).map(key => <label key={key} className="text-sm font-semibold">{key === "name" ? "Name *" : key === "email" ? "Email *" : "Phone"}<input disabled={!editable} className="mt-1 w-full rounded-lg border p-2 font-normal" type={key === "email" ? "email" : "text"} value={tenant[key] || ""} onChange={e => set("tenants", tenants.map((item, index) => index === i ? { ...item, [key]: e.target.value } : item))} /></label>)}
      <button disabled={!editable || tenants.length <= 1} className="self-end rounded-lg border px-3 py-2 disabled:opacity-50" onClick={() => set("tenants", tenants.filter((_, index) => index !== i))}>Remove</button>
    </div>)}{editable && <button className="rounded-lg border px-3 py-2 font-semibold" onClick={() => set("tenants", [...tenants, { name: "", email: "", phone: "" }])}>Add tenant</button>}</div>)}
    {section("2. Rental unit", <div className="grid gap-4 sm:grid-cols-2"><label className="text-sm font-semibold">Address<input readOnly value={String(values.unit_address || "")} className="mt-1 w-full rounded-lg border bg-slate-50 p-2" /></label><label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={Boolean(values.is_condo)} readOnly />Condominium (set on property)</label></div>)}
    {section("3. Term", <div className="space-y-4"><div className="flex gap-4 text-sm font-semibold"><label><input disabled={!editable} type="radio" checked={term === "fixed"} onChange={() => setTerm("fixed")} /> Fixed</label><label><input disabled={!editable} type="radio" checked={term === "periodic"} onChange={() => setTerm("periodic")} /> Periodic</label></div><div className="grid gap-4 sm:grid-cols-2">{term === "fixed" ? <>{field("fixed_start", "Start date", { required: true })}{field("fixed_end", "End date", { required: true })}</> : <>{field("periodic_start", "Start date", { required: true })}<label className="text-sm font-semibold">Period<select disabled={!editable} value={String(values.periodic_period || "")} onChange={e => set("periodic_period", e.target.value || null)} className="mt-1 block w-full rounded-lg border p-2"><option value="">Choose period</option><option value="week to week">Week to week</option><option value="month to month">Month to month</option><option value="other">Other</option></select></label></>}</div></div>)}
    {section("4. Deposits", <div className="grid gap-4 sm:grid-cols-2">{field("security_deposit_amount", `Security deposit (maximum ${formatted(rentPayable / 2)})`)}{field("security_deposit_date", "Date received")}{field("pet_deposit_amount", `Pet deposit (maximum ${formatted(rentPayable)})`)}{field("pet_deposit_date", "Date received")}</div>)}
    {section("5. Rent", <div className="space-y-4"><div className="grid gap-4 sm:grid-cols-3">{field("basic_rent", "Basic rent", { required: true })}{field("parking_spaces", "Parking spaces")}{field("parking_amount", "Parking amount")}{field("other_charge_desc", "Other charge description")}{field("other_charge_amount", "Other charge amount")}{field("rent_discount", "Discount")}</div><div className="grid gap-4 sm:grid-cols-2"><label className="text-sm font-semibold">Rent payable<input readOnly value={formatted(rentPayable)} className="mt-1 block w-full rounded-lg border bg-slate-50 p-2" /></label><label className="text-sm font-semibold">Actual rent after discount<input readOnly value={formatted(actualRent)} className="mt-1 block w-full rounded-lg border bg-slate-50 p-2" /></label></div><div className="grid gap-4 sm:grid-cols-2">{field("rent_due_day", "Rent due day")}{field("rent_period", "Rent period")}</div></div>)}
    {section("6. Rent increases", <div className="grid gap-4 sm:grid-cols-3">{field("guideline_increase_date", "Guideline increase date")}{field("above_guideline_date", "Above guideline date")}{field("above_guideline_rent", "Proposed rent")}</div>)}
    {section("7. Discount details", <div className="space-y-4">{field("discount_conditions", "Discount conditions", { textarea: true })}<label className="block text-sm font-semibold">Discount change on renewal<select disabled={!editable} value={String(values.discount_change || "")} onChange={e => set("discount_change", e.target.value || null)} className="mt-1 block w-full rounded-lg border p-2"><option value="">Not applicable</option><option value="same">Same</option><option value="reduced">Reduced</option><option value="removed">Removed</option><option value="agi">Subject to above guideline increase</option></select></label><div className="grid gap-4 sm:grid-cols-3">{field("discount_increase_amount", "Increase amount")}{field("discount_reduced_amount", "Reduced amount")}{field("agi_max_amount", "Above guideline maximum")}</div></div>)}
    {section("8. Services and utilities", <div className="space-y-4">{field("services_tenant_pays", "Tenant pays", { textarea: true })}{field("services_landlord_pays", "Landlord pays", { textarea: true })}{field("utility_exceptions", "Accounts remaining in landlord's name")} {editable && <button disabled={busy} onClick={() => void saveUtilityDefault()} className="rounded-lg border px-3 py-2 text-sm font-semibold">Save as this property's default</button>}</div>)}
    {section("9. Other details", <div className="space-y-4">{field("occupants", "Occupants", { textarea: true })}<label className="flex items-center gap-2 text-sm font-semibold"><input disabled={!editable} type="checkbox" checked={Boolean(values.furniture_provided)} onChange={e => set("furniture_provided", e.target.checked)} />Furniture provided</label>{field("other_attachments", "Other attachments", { textarea: true })}</div>)}
    <div className="sticky bottom-0 flex flex-wrap gap-3 border-t bg-[var(--ch-page-bg)] py-4">{editable && <><button disabled={busy} onClick={() => void run("save")} className="rounded-lg border px-4 py-3 font-bold disabled:opacity-50">Save draft</button><button disabled={busy} onClick={() => void run("preview")} className="rounded-lg border px-4 py-3 font-bold disabled:opacity-50">Preview PDF</button><button disabled={busy || dirty || !lease?.draft_pdf_key} onClick={() => void run("send")} className="rounded-lg bg-[var(--ch-accent)] px-4 py-3 font-bold text-white disabled:opacity-50">Send for signature</button></>}{lease?.draft_pdf_key && <a href={api.pdfUrl(leaseId)} target="_blank" rel="noreferrer" className="rounded-lg border px-4 py-3 font-bold">View PDF</a>}</div>
    {lease?.contact_form_data && section("Captured contact form · review before applying", <div className="space-y-4">{records.length === 0 && <p className="text-sm text-[var(--ch-text-muted)]">No tenant records are linked to this tenancy. Captured details remain available here.</p>}<div className="overflow-x-auto"><table className="min-w-full text-left text-sm"><thead><tr><th className="p-2">Apply</th><th className="p-2">Tenant</th><th className="p-2">Existing phone / email</th><th className="p-2">Signed form phone / email</th><th className="p-2">Preferred</th></tr></thead><tbody>{records.map(record => { const captured = lease.contact_form_data?.tenants?.find(t => t.name === record.name); return <tr key={record.id} className="border-t"><td className="p-2"><input type="checkbox" checked={Boolean(selected[record.id])} onChange={e => setSelected(current => ({ ...current, [record.id]: e.target.checked }))} /></td><td className="p-2">{record.name}</td><td className="p-2">{record.phone || "—"}<br />{record.email || "—"}</td><td className="p-2">{captured?.phone || "—"}<br />{captured?.email || "—"}</td><td className="p-2">{captured?.preferred || "—"}</td></tr>; })}</tbody></table></div><button disabled={busy || !Object.values(selected).some(Boolean)} onClick={() => void apply()} className="rounded-lg border px-4 py-2 font-semibold disabled:opacity-50">Apply selected to tenant records</button>{(["occupants", "emergency_contacts", "vehicles", "pets"] as const).map(group => <div key={group}><h3 className="font-semibold capitalize">{group.replaceAll("_", " ")}</h3>{lease.contact_form_data?.[group]?.length ? <ul className="list-disc pl-5 text-sm">{lease.contact_form_data[group]?.map((item, index) => <li key={index}>{Object.values(item).filter(Boolean).join(" · ")}</li>)}</ul> : <p className="text-sm text-[var(--ch-text-muted)]">None entered</p>}</div>)}</div>)}
    {task && section("Follow-up task", <div className="flex flex-wrap items-center justify-between gap-3"><div><strong>{task.title}</strong><p className="text-sm text-[var(--ch-text-muted)]">{task.status}</p></div>{task.status === "open" && <button disabled={busy} className="rounded-lg border px-4 py-2 font-semibold" onClick={() => { setBusy(true); void api.completeLeaseTask(leaseId).then(() => refresh()).catch(cause => setError(cause.message)).finally(() => setBusy(false)); }}>Mark complete</button>}</div>)}
  </div>;
}
