import { tenantHeaders } from "@/lib/tenant";
export interface FacilityDraw {
  id:string;facility_id:string;txn_date:string;txn_type:"draw"|"repayment";
  amount:string;reference:string|null;notes:string|null;confirmed_by:string|null;
  percent_complete:string|null;source:string;created_at:string;running_total:string;can_delete:boolean;
}
export interface FacilityDrawHistory {
  facility_id:string;lender_type:string;already_drawn:string|null;
  sum_of_draws:string;sum_of_repayments:string;net_draws:string;
  difference_from_already_drawn:string|null;items:FacilityDraw[];
}
export interface FacilityDrawInput {
  txn_date:string;amount:string;txn_type?:"draw"|"repayment";reference?:string|null;
  notes?:string|null;confirmed_by?:string|null;percent_complete?:string|null;
  source?:"scu_confirmation"|"manual";
}
export interface FacilityDrawImport {
  facility_id:string;created:number;skipped:number;
  results:{status:"created"|"skipped";txn_id:string}[];history:FacilityDrawHistory;
}
async function drawFetch<T>(path:string,options:RequestInit={}):Promise<T>{
  const response=await fetch(`/backend-api/api/v1/financing/facilities/${path}`,{
    ...options,credentials:"include",cache:"no-store",headers:{"Content-Type":"application/json",...tenantHeaders(),...options.headers},
  });
  if(!response.ok){
    const body=await response.json().catch(()=>({}));
    const detail=body.detail;
    throw new Error(typeof detail==="string"?detail:Array.isArray(detail)?detail.map((e:{loc?:unknown[];msg?:string})=>`${e.loc?.slice(1).join(".")??""}: ${e.msg??"Invalid value"}`).join("; "):`Draw history API ${response.status}`);
  }
  return response.json();
}
export const getFacilityDraws=(id:string)=>drawFetch<FacilityDrawHistory>(`${id}/draws`);
export const addFacilityDraws=(id:string,input:FacilityDrawInput|FacilityDrawInput[])=>drawFetch<FacilityDrawImport>(`${id}/draws`,{method:"POST",body:JSON.stringify(input)});
export const deleteFacilityDraw=(id:string,txnId:string)=>drawFetch<{deleted:boolean;txn_id:string;history:FacilityDrawHistory}>(`${id}/draws/${txnId}`,{method:"DELETE"});
