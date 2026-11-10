import type { Metadata } from "next";
import { notFound } from "next/navigation";
import VendorPortal from "@/components/maintenance/VendorPortal";
import type { VendorPortalOrder } from "@/lib/api/maintenance";
export const metadata:Metadata={title:"Work order · Office Hub",robots:{index:false,follow:false},referrer:"no-referrer"};
export const dynamic="force-dynamic";
export default async function VendorOrderPage({params}:{params:Promise<{token:string}>}){
  const {token}=await params;
  if(!/^[A-Za-z0-9_-]{32,128}$/.test(token))notFound();
  const origin=(process.env.BACKEND_INTERNAL_URL||"http://127.0.0.1:8000").replace(/\/+$/,"");
  let response:Response|null=null;let order:VendorPortalOrder|null=null;
  try{response=await fetch(`${origin}/api/public/work-orders/${encodeURIComponent(token)}`,{cache:"no-store",signal:AbortSignal.timeout(8000)});}
  catch{/* A temporary backend outage is not an invalid capability. */}
  if(response?.status===404)notFound();
  if(response?.ok)order=await response.json() as VendorPortalOrder;
  return <VendorPortal token={token} initialOrder={order}/>;
}
