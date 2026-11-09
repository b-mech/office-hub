import { useEffect, useRef, useState, type FormEvent } from "react";
import { addFacilityDraws, deleteFacilityDraw, getFacilityDraws, type FacilityDrawHistory as History } from "@/lib/api/facility-draws";
import type { FinancingProperty } from "@/types/financing";
const money=new Intl.NumberFormat("en-CA",{style:"currency",currency:"CAD",minimumFractionDigits:2,maximumFractionDigits:2});
const cash=(value:string|null)=>value==null?"Not supplied":money.format(Number(value));
const control="mt-1 w-full rounded-md border border-[var(--ch-border)] bg-[var(--ch-surface)] px-2 py-2 text-sm";
const button="rounded-md border border-[var(--ch-border)] px-3 py-2 text-xs font-semibold disabled:opacity-50";

export function FacilityDrawHistory({property}:{property:FinancingProperty}){
  const facilityId=property.facility_id!;
  const [history,setHistory]=useState<History|null>(null),[error,setError]=useState(""),[notice,setNotice]=useState("");
  const [busy,setBusy]=useState(false),[pendingDelete,setPendingDelete]=useState<string|null>(null);
  const [refresh,setRefresh]=useState(0);
  const section=useRef<HTMLElement>(null),details=useRef<HTMLDetailsElement>(null),scrolled=useRef(false),version=useRef(0);
  useEffect(()=>{
    let active=true;const requestVersion=version.current;
    getFacilityDraws(facilityId).then((data)=>{if(active&&requestVersion===version.current){setHistory(data);setError("");}})
      .catch((e:unknown)=>{if(active&&requestVersion===version.current)setError(e instanceof Error?e.message:"Could not load draw history");});
    return ()=>{active=false;};
  },[facilityId,property.already_drawn,refresh]);
  useEffect(()=>{
    if(!history||scrolled.current||window.location.hash!=="#draw-history")return;
    scrolled.current=true;const frame=requestAnimationFrame(()=>section.current?.scrollIntoView({block:"start"}));
    return ()=>cancelAnimationFrame(frame);
  },[history]);
  async function add(event:FormEvent<HTMLFormElement>){
    event.preventDefault();if(busy)return;
    const form=event.currentTarget,data=new FormData(form);
    setBusy(true);setError("");setNotice("");version.current++;
    try{
      const result=await addFacilityDraws(facilityId,{
        txn_date:String(data.get("txn_date")),amount:String(data.get("amount")),
        txn_type:data.get("txn_type")==="repayment"?"repayment":"draw",
        reference:String(data.get("reference")??""),notes:String(data.get("notes")??"")||null,
        confirmed_by:String(data.get("confirmed_by")??"")||null,percent_complete:String(data.get("percent_complete")??"")||null,
      });
      setHistory(result.history);setNotice(`${result.created} added · ${result.skipped} duplicate(s) skipped. Bank balance was not changed.`);
      form.reset();if(details.current)details.current.open=false;
    }catch(e){setError(e instanceof Error?e.message:"Could not add draw");}finally{setBusy(false);}
  }
  async function remove(id:string){
    if(busy)return;setBusy(true);setError("");setNotice("");version.current++;
    try{const result=await deleteFacilityDraw(facilityId,id);setHistory(result.history);setPendingDelete(null);setNotice("Transaction deleted. Bank balance was not changed.");}
    catch(e){setError(e instanceof Error?e.message:"Could not delete draw");}finally{setBusy(false);}
  }
  return <section id="draw-history" ref={section} aria-label="Draw history" className="mb-4 scroll-mt-4 rounded-lg border border-[var(--ch-border)] bg-[var(--ch-surface)] p-4">
    <div className="mb-3 flex items-start justify-between gap-3"><div><h3 className="text-sm font-semibold">Draw history</h3><p className="mt-1 text-xs text-[var(--ch-text-muted)]">{property.address} · {property.lender_type}</p></div><button type="button" className={button} disabled={busy} onClick={()=>setRefresh((n)=>n+1)}>Refresh</button></div>
    {error?<p role="alert" className="mb-3 text-xs text-[var(--ch-error-text)]">{error}</p>:null}
    {notice?<p role="status" className="mb-3 text-xs text-[var(--ch-accent)]">{notice}</p>:null}
    {!history&&!error?<p className="text-sm text-[var(--ch-text-muted)]">Loading draw history…</p>:null}
    {history?<>
      <div className="mb-3 grid gap-3 rounded-md bg-[var(--ch-surface-muted)] p-3 sm:grid-cols-3">
        {[['Recorded progress draws',cash(history.sum_of_draws)],['Bank balance · already drawn',cash(history.already_drawn)],['Bank less recorded draws',cash(history.difference_from_already_drawn)]].map(([label,value])=><div key={label}><p className="text-[11px] text-[var(--ch-text-muted)]">{label}</p><p className="mt-1 text-sm font-semibold tabular-nums">{value}</p></div>)}
      </div>
      <p className="mb-3 text-xs text-[var(--ch-text-secondary)]">Bank balance is maintained separately and may include land / initial advances absent from these progress draws. Adding or deleting history never changes already drawn.</p>
      <div className="overflow-x-auto"><table className="min-w-full text-xs"><caption className="sr-only">Dated draws and repayments for {property.address}</caption>
        <thead className="text-[var(--ch-text-muted)]"><tr>{['Date','Amount','Complete','Confirmed by','Note / reference','Running total','Actions'].map((label)=><th key={label} className="px-2 py-2 text-left font-semibold">{label}</th>)}</tr></thead>
        <tbody>{history.items.map((item)=><tr key={item.id} className="border-t border-[var(--ch-border)]">
          <td className="whitespace-nowrap px-2 py-2">{item.txn_date}</td>
          <td className="whitespace-nowrap px-2 py-2 text-right tabular-nums">{item.txn_type==='repayment'?'−':''}{cash(item.amount)}<span className="block text-[10px] text-[var(--ch-text-muted)]">{item.txn_type}</span></td>
          <td className="px-2 py-2">{item.percent_complete==null?'—':`${Number(item.percent_complete)}%`}</td>
          <td className="px-2 py-2">{item.confirmed_by||'—'}</td>
          <td className="max-w-40 break-words px-2 py-2"><span className="block whitespace-pre-wrap">{item.notes||'—'}</span>{item.reference?<span className="mt-1 block text-[10px] text-[var(--ch-text-muted)]">Ref: {item.reference}</span>:null}</td>
          <td className="whitespace-nowrap px-2 py-2 text-right font-semibold tabular-nums">{cash(item.running_total)}</td>
          <td className="px-2 py-2">{item.can_delete?(pendingDelete===item.id?<div className="flex flex-col gap-1"><button type="button" disabled={busy} onClick={()=>remove(item.id)} className="text-[var(--ch-error-text)]">Confirm delete</button><button type="button" disabled={busy} onClick={()=>setPendingDelete(null)}>Cancel</button></div>:<button type="button" disabled={busy} aria-label={`Delete ${item.txn_date} ${item.txn_type} ${item.amount}`} onClick={()=>setPendingDelete(item.id)} className="text-[var(--ch-error-text)]">Delete</button>):<span className="text-[10px] text-[var(--ch-text-muted)]">Managed<br/>by source</span>}</td>
        </tr>)}</tbody>
      </table></div>
      {!history.items.length?<p className="py-3 text-xs text-[var(--ch-text-muted)]">No dated draws recorded yet. The bank balance is not an opening draw entry.</p>:null}
      <p className="mt-3 text-xs text-[var(--ch-text-secondary)]">Repayments: {cash(history.sum_of_repayments)} · Net recorded draws / running total: {cash(history.net_draws)}. Ordered oldest first; running total excludes opening advances and interest.</p>
    </>:null}
    <details ref={details} className="mt-4 border-t border-[var(--ch-border)] pt-3"><summary className="cursor-pointer text-xs font-semibold text-[var(--ch-accent)]">Add draw / repayment</summary>
      <form onSubmit={add} className="mt-3"><fieldset disabled={busy||!history} className="grid gap-3 sm:grid-cols-2">
        <label className="text-xs">Date<input required name="txn_date" type="date" className={control}/></label>
        <label className="text-xs">Amount (CAD)<input required name="amount" type="number" min="0.01" max="999999999999.99" step="0.01" className={control}/></label>
        <label className="text-xs">Type<select name="txn_type" className={control}><option value="draw">Draw</option><option value="repayment">Repayment</option></select></label>
        <label className="text-xs">Percent complete<input name="percent_complete" type="number" min="0" max="100" step="0.01" className={control}/></label>
        <label className="text-xs">Confirmed by<input name="confirmed_by" maxLength={255} className={control}/></label>
        <label className="text-xs">Reference<input name="reference" maxLength={1000} className={control}/></label>
        <label className="text-xs sm:col-span-2">Notes / confirmation text<textarea name="notes" maxLength={10000} rows={3} className={control}/></label>
        <button type="submit" className="rounded-md bg-[var(--ch-accent)] px-3 py-2 text-xs font-semibold text-white disabled:opacity-50">{busy?'Saving…':'Add to history'}</button>
      </fieldset></form>
    </details>
  </section>;
}
