"use client";
import { useEffect, useState } from "react";
import { getRentalMap } from "@/lib/api/rentals-map";
import type { PinRecord } from "@/lib/pin-state";
import { LocationMapWorkspace } from "../../components/LocationMapWorkspace";
const COLORS={current:"#2e7d32",due:"#d6a700",overdue:"#c62828",never:"#777777"};
const STATUS={current:"Inspected",due:"Inspection due",overdue:"Inspection overdue",never:"Never inspected"};
export default function RentalsMapPage(){
 const [rows,setRows]=useState<PinRecord[]>([]),[loading,setLoading]=useState(true),[error,setError]=useState<string|null>(null);
 useEffect(()=>{getRentalMap().then((items)=>setRows(items.map((r)=>({...r,id:String(r.property_id),label:r.street_address,address:r.street_address,community:r.group_name??r.municipality??r.city??"Manitoba",kind:"rental",status:STATUS[r.inspection_status],href:`/rentals/inspections?property_id=${r.property_id}`,color:COLORS[r.inspection_status],details:[`${r.unit_count} units`,r.last_inspection_date?`Last inspection: ${r.last_inspection_date}`:"No inspection recorded"]})))).catch((e:unknown)=>setError(e instanceof Error?e.message:"Map unavailable")).finally(()=>setLoading(false));},[]);
 return <LocationMapWorkspace title="Rentals map" mode="rentals" records={rows} loading={loading} error={error}/>;
}
