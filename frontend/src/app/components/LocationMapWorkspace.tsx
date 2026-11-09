"use client";
import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { EntityMap, type EntityMapMarker } from "./EntityMap";
import { partitionMapRecords } from "@/lib/map-points";
import { needsPin, nextNeedsPin, outsideManitoba, pinStart, type PinDraft, type PinRecord } from "@/lib/pin-state";
import { patchLocation } from "@/lib/api/locations";
import { BASEMAP_CHOICES, readBasemap, resolveBasemap, saveBasemap, type MapBasemap } from "@/lib/map-basemaps";

const glass = "border border-[var(--ch-border)] bg-[var(--ch-surface)]/90 shadow-lg backdrop-blur-xl";
const button = "rounded-lg border border-[var(--ch-border)] bg-[var(--ch-surface)]/80 px-3 py-2 text-xs font-medium transition hover:border-[var(--ch-accent)] disabled:cursor-not-allowed disabled:opacity-50";
const primary = "rounded-lg border border-[var(--ch-accent)] bg-[var(--ch-accent)] px-3 py-2 text-xs font-semibold text-white transition disabled:cursor-not-allowed disabled:opacity-50";
const kindLabel = {lot:"Land lot",project:"Project",rental:"Rental property"};
const precisionLabel = (r:PinRecord) => r.geocode_precision === "manual" ? "Manual · exact pin" : r.geocode_precision === "house" ? "House-level geocode" : r.geocode_precision === "street" ? "Approximate street · needs pin" : "Unplaced · needs pin";
export function LocationMapWorkspace({title,records,loading=false,error,mode}:{title:string;records:PinRecord[];loading?:boolean;error?:string|null;mode:"land"|"rentals"}) {
 const [rows,setRows]=useState(records),[query,setQuery]=useState(""),[kind,setKind]=useState("all");
 const [needsOnly,setNeedsOnly]=useState(false),[selectedId,setSelectedId]=useState<string|null>(null),[draft,setDraft]=useState<PinDraft|null>(null);
 const [trayOpen,setTrayOpen]=useState(true),[busy,setBusy]=useState(false),[notice,setNotice]=useState(""),[failure,setFailure]=useState(""),[fitKey,setFitKey]=useState(0);
 const [basemap,setBasemap]=useState<MapBasemap>("street"),[basemapLoaded,setBasemapLoaded]=useState(false);
 const initialized=useRef(false);
 useEffect(()=>{
  const requested=new URLSearchParams(window.location.search).get("basemap");
  try{setBasemap(readBasemap(window.localStorage,requested));}catch{setBasemap(resolveBasemap(requested,null));}
  setBasemapLoaded(true);
 },[]);
 useEffect(()=>{if(basemapLoaded){try{saveBasemap(window.localStorage,basemap);}catch{/* Storage getter may be blocked. */}}},[basemap,basemapLoaded]);
 useEffect(()=>setRows(records),[records]);
 useEffect(()=>{
  if(!rows.length||initialized.current)return;initialized.current=true;
  const params=new URLSearchParams(window.location.search),only=params.get("needs")==="1";
  const place=params.get("place"),chosen=rows.find((r)=>r.id===(place??params.get("selected")))??(only?rows.find(needsPin):undefined);
  setNeedsOnly(only&&(!chosen||needsPin(chosen)));
  if(chosen){setSelectedId(chosen.id);if(place||only)setDraft(pinStart(chosen,rows));}
 },[rows]);
 const matches=(r:PinRecord)=> (kind==="all"||r.kind===kind)&&`${r.address} ${r.community} ${r.municipality??""} ${r.client??""} ${r.lot_number??""}`.toLowerCase().includes(query.trim().toLowerCase());
 const filtered=rows.filter(matches),queue=filtered.filter(needsPin),visible=needsOnly?queue:filtered;
 const partition=useMemo(()=>partitionMapRecords(rows),[rows]);
 const selected=rows.find((r)=>r.id===selectedId);
 const focus=useMemo(()=>{const r=rows.find((r)=>r.id===selectedId);return r?pinStart(r,rows):null;},[rows,selectedId]);
 const markers=useMemo<EntityMapMarker[]>(()=>partition.located.filter((p)=>visible.some((r)=>r.id===p.record.id)).map(({record,lat,lng,approximate})=>({id:record.id,lat,lng,title:record.address,lines:[record.community,precisionLabel(record),...(record.details??[])],href:record.href,linkLabel:record.kind==="rental"?"View units & inspections":`Open ${record.kind}`,color:record.geocode_precision==="manual"?"#17698c":record.color,manual:record.geocode_precision==="manual",approximate})),[partition,visible]);
 // Stable marker data prevents map redraws while typing / moving an unsaved pin.
 const markerSignature=JSON.stringify(markers);
 const stableMarkers=useMemo(()=>markers,[markerSignature]); // eslint-disable-line react-hooks/exhaustive-deps
 const select=(id:string)=>{
  if(busy)return;if(draft?.moved&&draft.id!==id){setFailure("Save or Cancel the current pin before switching items.");return;}
  const row=rows.find((r)=>r.id===id);if(!row)return;setSelectedId(id);setTrayOpen(true);setFailure("");
  if(needsOnly)setDraft(pinStart(row,rows));else if(draft?.id!==id)setDraft(null);
 };
 const begin=(row:PinRecord)=>{if(busy)return;setSelectedId(row.id);setDraft(pinStart(row,rows));setTrayOpen(true);setFailure("");setNotice("");};
 const move=(lat:number,lng:number)=>{if(!busy)setDraft((d)=>d?{...d,lat,lng,moved:true}:null);};
 const changeNeeds=()=>{
  const only=!needsOnly;setNeedsOnly(only);setFailure("");setDraft(null);
  if(only){const next=queue[0];setSelectedId(next?.id??null);if(next)setDraft(pinStart(next,rows));setTrayOpen(true);}
 };
 const update=async(action:"set"|"reset"|"clear")=>{
  if(!selected||busy||(action==="set"&&(!draft||!draft.moved)))return;
  setBusy(true);setFailure("");
  try{
   const result=await patchLocation(selected.kind,selected.id,{action,...(action==="set"&&draft?{latitude:draft.lat,longitude:draft.lng}:{})});
   const updated=rows.map((r)=>r.id===selected.id?{...r,...result}:r);setRows(updated);
   const next=action==="set"?nextNeedsPin(updated.filter(matches),selected.id):undefined;
   setDraft(next?pinStart(next,updated):null);setSelectedId(next?.id??selected.id);
   setNotice([action==="set"?`Saved ${selected.address}.${next?" Next item ready.":""}`:action==="reset"?"Restored the original geocoded location.":"Pin cleared. It is unplaced until saved again.",...result.warnings,result.actor_is_fallback?"Preview: attributed to the fallback actor.":""].filter(Boolean).join(" "));
  }catch(e){setFailure(e instanceof Error?e.message:"Unable to update pin");}finally{setBusy(false);}
 };
 return <main className="relative h-[calc(100dvh-3.5rem)] w-full overflow-hidden lg:h-dvh" aria-label={title}>
  <EntityMap markers={stableMarkers} selectedId={selectedId} onSelect={select} ariaLabel={title} draft={draft} onDraftMove={move} focus={focus} resizeKey={trayOpen} fitKey={fitKey} basemap={basemap}/>
  <header className={`absolute inset-x-3 top-3 z-20 rounded-xl px-3 py-2 ${glass}`}>
   <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
    <div className="min-w-0 flex-1"><h1 className="text-base font-semibold">{title}</h1><p className="text-[11px] text-[var(--ch-text-muted)]">{loading?"Loading locations…":`${rows.length} records · ${partition.located.length} mapped · ${rows.filter(needsPin).length} need a pin`}</p></div>
    <div role="group" aria-label="Map base layer" className="order-last flex w-full shrink-0 gap-1 rounded-lg border border-[var(--ch-border)] bg-[var(--ch-surface)]/80 p-0.5 sm:order-none sm:w-auto">{BASEMAP_CHOICES.map((choice)=><button key={choice.id} type="button" aria-pressed={basemap===choice.id} onClick={()=>setBasemap(choice.id)} className={`flex-1 rounded-md px-2 py-1.5 text-[11px] font-medium transition focus-visible:outline-2 focus-visible:outline-[var(--ch-accent)] ${basemap===choice.id?"bg-[var(--ch-accent)] text-white shadow-sm":"hover:bg-[var(--ch-accent-soft)]"}`}>{choice.label}</button>)}</div>
    <Link href={mode==="land"?"/land":"/rentals"} className={`${button} hidden sm:inline-flex`}>Overview</Link>
    <button className={button} aria-label="Fit all locations" disabled={busy||Boolean(draft?.moved)} onClick={()=>{setSelectedId(null);setDraft(null);setFitKey((n)=>n+1);}}><span className="sm:hidden">⤢</span><span className="hidden sm:inline">Fit all</span></button>
    <button className={button} onClick={()=>setTrayOpen((v)=>!v)} aria-expanded={trayOpen} aria-controls="map-item-tray" aria-label={trayOpen?"Hide location tray":"Show location tray"}><span className="sm:hidden">▤</span><span className="hidden sm:inline">{trayOpen?"Hide tray":"Show tray"}</span></button>
   </div>
   <div className="mt-2 flex flex-wrap items-center gap-2">
    {mode==="land"?<div className="flex gap-1" role="group" aria-label="Location type">{[["all","All"],["lot","Land lots"],["project","Projects"]].map(([key,label])=><button key={key} className={`${button} ${kind===key?"border-[var(--ch-accent)] bg-[var(--ch-accent-soft)]":""}`} aria-pressed={kind===key} disabled={busy||Boolean(draft?.moved)} onClick={()=>{setKind(key);setSelectedId(null);setDraft(null);}}>{label}</button>)}</div>:null}
    <input aria-label="Search locations" placeholder="Search address, community, client" value={query} disabled={busy||Boolean(draft?.moved)} onChange={(e)=>setQuery(e.target.value)} className="order-first w-full min-w-0 flex-none rounded-lg sm:order-none sm:w-auto sm:flex-1 border border-[var(--ch-border)] bg-[var(--ch-surface)]/80 px-3 py-2 text-xs outline-none focus:border-[var(--ch-accent)]"/>
    <button className={`${button} ${needsOnly?"border-[var(--ch-accent)] bg-[var(--ch-accent-soft)] font-semibold":""}`} onClick={changeNeeds} disabled={busy||Boolean(draft?.moved)} aria-pressed={needsOnly}>Needs pin ({queue.length})</button>
   </div>
  </header>
  <div className={`absolute left-3 top-[13rem] z-10 max-w-[calc(100%-1.5rem)] rounded-full px-3 py-1.5 text-[10px] lg:bottom-6 lg:top-auto ${glass}`} aria-label="Map legend">● House / manual · ◌ Approximate · <span className="text-orange-700">● Unsaved</span> · Clusters expand</div>
  {trayOpen?<aside id="map-item-tray" aria-label="Location details and pin queue" className={`absolute inset-x-3 bottom-12 z-20 flex max-h-[43dvh] flex-col overflow-hidden rounded-2xl lg:bottom-8 lg:left-auto lg:right-3 lg:top-[7.5rem] lg:max-h-none lg:w-[21rem] ${glass}`}>
   <div className="flex shrink-0 items-center justify-between border-b border-[var(--ch-border)] px-3 py-2"><h2 className="text-xs font-semibold">{needsOnly?"Needs pin queue":"Locations"} · {visible.length}</h2><button className="rounded px-2 py-1 text-xs" aria-label="Collapse location tray" onClick={()=>setTrayOpen(false)}>Collapse ↓</button></div>
   <div className="min-h-0 overflow-y-auto overscroll-contain">
    {error||failure?<p role="alert" className="m-3 rounded-lg bg-red-50 p-2 text-xs text-red-900">{failure||error}</p>:null}
    {notice?<p role="status" className="m-3 text-xs text-[var(--ch-accent)]">{notice}</p>:null}
    {selected?<section className="border-b border-[var(--ch-border)] px-3 py-3" aria-label="Selected location">
      <p className="text-[10px] font-semibold uppercase tracking-wider text-[var(--ch-text-muted)]">{kindLabel[selected.kind]}</p><h3 className="mt-1 text-sm font-semibold">{selected.address}</h3>
      <p className="mt-1 text-xs text-[var(--ch-text-muted)]">{[selected.community,selected.municipality,selected.lot_number?`Lot ${selected.lot_number}`:null].filter(Boolean).join(" · ")}</p>
      <p className="mt-1 text-xs">{[selected.status,selected.client].filter(Boolean).join(" · ")}</p>
      <p className="mt-2 text-xs font-medium">{precisionLabel(selected)}</p>
      {selected.location_set_by?<p className="mt-1 break-all text-[10px] text-[var(--ch-text-muted)]">Placed by {selected.location_set_by}</p>:null}
      <Link href={selected.href} className="mt-2 inline-block text-xs font-semibold text-[var(--ch-accent)]">{selected.kind==="rental"?"Units & inspections":"Open workspace"} ↗</Link>
      {draft?<div className="mt-3 space-y-2 rounded-xl border border-orange-300 bg-orange-50/90 p-3 text-slate-900" aria-label="Pin placement controls">
        <div className="flex flex-wrap items-center justify-between gap-2"><p className="text-xs font-semibold">{selected.latitude==null?"Place pin":"Adjust pin"} · UNSAVED</p><button type="button" className="rounded-md border border-orange-300 bg-white px-2 py-1 text-[11px] font-semibold text-slate-900" aria-pressed={basemap==="satellite"} onClick={()=>setBasemap("satellite")}>Satellite ↗</button></div><p className="text-[11px]">{draft.startLabel}</p>
        <p className="text-[11px]">Drag the orange pin, click the map, or focus the pin and use arrow keys. Nothing is saved until Save pin.</p>
        <div className="flex gap-2"><label className="min-w-0 flex-1 text-[10px]">Latitude<input aria-label="Pin latitude" type="number" step="0.000001" value={Number(draft.lat.toFixed(6))} disabled={busy} onChange={(e)=>{const n=Number(e.target.value);if(e.target.value&&Number.isFinite(n)&&Math.abs(n)<=90)move(n,draft.lng);}} className="mt-1 w-full rounded border border-orange-200 bg-white px-1 py-1 text-xs"/></label><label className="min-w-0 flex-1 text-[10px]">Longitude<input aria-label="Pin longitude" type="number" step="0.000001" value={Number(draft.lng.toFixed(6))} disabled={busy} onChange={(e)=>{const n=Number(e.target.value);if(e.target.value&&Number.isFinite(n)&&Math.abs(n)<=180)move(draft.lat,n);}} className="mt-1 w-full rounded border border-orange-200 bg-white px-1 py-1 text-xs"/></label></div>
        {outsideManitoba(draft.lat,draft.lng)?<p role="alert" className="text-[11px] font-semibold text-red-800">Outside the usual Manitoba area — check before saving.</p>:null}
        <div className="flex gap-2"><button className={primary} disabled={busy||!draft.moved} onClick={()=>update("set")}>{busy?"Saving…":"Save pin & next"}</button><button className={button} disabled={busy} onClick={()=>{setDraft(null);setFailure("");}}>Cancel</button></div>
      </div>:<div className="mt-3 flex flex-wrap gap-2"><button className={primary} disabled={busy} onClick={()=>begin(selected)}>{selected.latitude==null?"Place pin":"Adjust pin"}</button>{selected.can_reset_location?<button className={button} disabled={busy} onClick={()=>update("reset")}>Reset to geocoded</button>:null}<button className={button} disabled={busy||selected.latitude==null} onClick={()=>update("clear")}>Clear pin</button></div>}
     </section>:<p className="px-3 py-3 text-xs text-[var(--ch-text-muted)]">Select a marker or an item to inspect it and place its pin.</p>}
    <ul aria-label={needsOnly?"Items needing pins":"Map locations"}>{visible.map((row)=><li key={row.id}><button type="button" disabled={busy} onClick={()=>select(row.id)} aria-pressed={selectedId===row.id} className={`flex w-full items-start gap-2 border-b border-[var(--ch-border)] px-3 py-3 text-left transition hover:bg-[var(--ch-accent-soft)] ${row.id===selectedId?"bg-[var(--ch-accent-soft)]":""}`}><span className="mt-1 h-2.5 w-2.5 shrink-0 rounded-full" style={{background:row.geocode_precision==="manual"?"#17698c":row.color}}/><span className="min-w-0"><span className="block text-xs font-semibold">{row.address}</span><span className="mt-0.5 block text-[10px] text-[var(--ch-text-muted)]">{row.community} · {precisionLabel(row)}</span></span></button></li>)}</ul>
    {!visible.length&&!loading?<p className="p-4 text-xs">{needsOnly?"No items need a pin in this filter.":"No matching locations."}</p>:null}
   </div>
  </aside>:null}
  {!trayOpen&&(failure||error||notice)?<p role="status" className={`absolute bottom-20 left-3 right-3 z-20 rounded-lg p-3 text-xs ${glass}`}>{failure||error||notice}</p>:null}
 </main>;
}
