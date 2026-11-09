"use client";
import { useEffect, useState } from "react";
import { getLots, getProjects } from "@/lib/api/costbook";
import type { PinRecord } from "@/lib/pin-state";
import { LocationMapWorkspace } from "../../components/LocationMapWorkspace";
export default function LotsMapPage(){
 const [rows,setRows]=useState<PinRecord[]>([]),[loading,setLoading]=useState(true),[error,setError]=useState<string|null>(null);
 useEffect(()=>{Promise.allSettled([getLots(),getProjects()]).then((results)=>{
  const next:PinRecord[]=[],errors:string[]=[];
  results.forEach((result,index)=>{if(result.status==="rejected"){errors.push(result.reason instanceof Error?result.reason.message:"Map data unavailable");return;}
   result.value.filter((r)=>!r.cancelled).forEach((r)=>next.push({...r,id:r.id,label:r.address,address:r.address,community:r.community,kind:index===0?"lot":"project",client:r.client_name??r.buyer_name,status:r.status,href:index===0?`/lots/${r.id}`:`/projects/${r.id}`,color:index===0?"#8a6d1f":"#17698c"}));
  });setRows(next);setError(errors.length?errors.join("; "):null);setLoading(false);
 });},[]);
 return <LocationMapWorkspace title="Land map" mode="land" records={rows} loading={loading} error={error}/>;
}
