import assert from "node:assert/strict";
import {test} from "node:test";
import {needsPin,pinStart,nextNeedsPin,outsideManitoba,storedPoint,type PinRecord} from "./pin-state.ts";
const row=(id:string,extras:Partial<PinRecord>={}):PinRecord=>({id,label:id,address:id,kind:"lot",community:"Garson",municipality:"RM of Brokenhead",development_id:"dev",href:"/lots/"+id,color:"#8a6d1f",...extras});
test("manual and house are exact; street and absent stay in queue",()=>{
 assert.equal(needsPin(row("manual",{geocode_precision:"manual"})),false);
 assert.equal(needsPin(row("house",{geocode_precision:"house"})),false);
 assert.equal(needsPin(row("street",{geocode_precision:"street"})),true);
 assert.equal(needsPin(row("missing")),true);
});
test("approximate start keeps stored street point but is unsaved",()=>{
 const r=row("a",{geocode_precision:"street",latitude:50.075,longitude:-96.7});const start=pinStart(r,[r]);
 assert.equal(start.lat,50.075);assert.equal(start.moved,false);assert.match(start.startLabel,/not saved/);
});
test("missing uses same-development centroid, not another development",()=>{
 const a=row("a"),b=row("b",{geocode_precision:"manual",latitude:50,longitude:-97}),c=row("c",{geocode_precision:"house",latitude:50.2,longitude:-97.2}),d=row("d",{development_id:"other",geocode_precision:"house",latitude:55,longitude:-100});
 const start=pinStart(a,[a,b,c,d]);assert.equal(start.lat,50.1);assert.equal(start.lng,-97.1);assert.equal(start.moved,false);assert.match(start.startLabel,/Unplaced/);
});
test("all-missing Garson starts in community but never creates a saved point",()=>{
 const r=row("a"),start=pinStart(r,[r]);assert.equal(start.lat,50.076);assert.equal(start.moved,false);assert.equal(storedPoint(r),null);
});
test("queue advances and wraps without manual/house entries",()=>{
 const a=row("a"),b=row("b",{geocode_precision:"manual"}),c=row("c");assert.equal(nextNeedsPin([a,b,c],"a")?.id,"c");assert.equal(nextNeedsPin([a,b,c],"c")?.id,"a");assert.equal(nextNeedsPin([b],"b"),undefined);
});
test("Manitoba boundary is warning only; worldwide manual coordinate can be represented",()=>{
 assert.equal(outsideManitoba(49.9,-97),false);assert.equal(outsideManitoba(48.5,-97),true);assert.deepEqual(storedPoint(row("zero",{geocode_precision:"manual",latitude:0,longitude:0})),{lat:0,lng:0});
});
