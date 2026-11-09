"use client";

import "leaflet/dist/leaflet.css";
import "leaflet.markercluster/dist/MarkerCluster.css";
import "leaflet.markercluster/dist/MarkerCluster.Default.css";
import { useEffect, useRef, useState } from "react";
import type { Map as LeafletMap, Marker, MarkerClusterGroup } from "leaflet";
import type { PinDraft } from "@/lib/pin-state";
import { basemapTiles, type MapBasemap } from "@/lib/map-basemaps";

export interface EntityMapMarker {
  id: string; lat: number; lng: number; title: string; lines?: string[];
  href: string; linkLabel: string; color?: string; approximate?: boolean; manual?: boolean;
}
function popupContent(marker: EntityMapMarker): HTMLElement {
  const root = document.createElement("div"); root.style.minWidth = "190px";
  const title = document.createElement("strong"); title.textContent = marker.title; root.appendChild(title);
  for (const line of [marker.manual ? "Manually placed pin" : marker.approximate ? "Approximate street location — manual pin needed" : "House-level geocode", ...(marker.lines ?? [])]) {
    if (!line) continue;
    const row = document.createElement("div"); row.textContent = line; row.style.fontSize = "12px"; root.appendChild(row);
  }
  const link = document.createElement("a"); link.href = marker.href; link.textContent = marker.linkLabel; link.style.display = "block"; link.style.marginTop = "6px"; root.appendChild(link);
  return root;
}
function markerHtml(color: string, approximate = false, manual = false): string {
  return `<span data-pin-precision="${manual ? "manual" : approximate ? "street" : "house"}" style="display:block;width:20px;height:20px;border-radius:9999px;background:${approximate ? "#fff" : color};border:3px ${approximate ? "dashed" : "solid"} ${approximate ? color : "#fff"};box-shadow:0 0 0 2px #fff,0 2px 8px #000b"></span>`;
}
// Keep selected/editor pins above the mobile bottom sheet without changing
// their stored coordinates. The same visible-centre offset applies to selection.
function flyPoint(map: LeafletMap, lat: number, lng: number, zoom: number) {
  const point = map.project([lat,lng],zoom);
  if(map.getSize().x<700) point.y += map.getSize().y*0.18;
  map.flyTo(map.unproject(point,zoom),zoom,{duration:0.65,easeLinearity:0.25});
}
export function EntityMap({ markers, selectedId, onSelect, ariaLabel, draft, onDraftMove, focus, resizeKey, fitKey = 0, basemap = "street" }: {
  markers: EntityMapMarker[]; selectedId?: string | null; onSelect?: (id:string)=>void; ariaLabel:string;
  draft?: PinDraft | null; onDraftMove?: (lat:number,lng:number)=>void;
  focus?: {id:string;lat:number;lng:number} | null; resizeKey?: boolean; fitKey?:number; basemap?:MapBasemap;
}) {
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<LeafletMap | null>(null);
  const groupRef = useRef<MarkerClusterGroup | null>(null);
  const editorRef = useRef<Marker | null>(null);
  const markerRefs = useRef(new Map<string,Marker>());
  const leafletRef = useRef<typeof import("leaflet") | null>(null);
  const onSelectRef = useRef(onSelect), onMoveRef = useRef(onDraftMove);
  const selectedRef = useRef(selectedId), draftRef = useRef(draft);
  const [ready,setReady] = useState(false), [error,setError] = useState<string|null>(null);
  const [tileErrors,setTileErrors] = useState(0);
  useEffect(()=>{onSelectRef.current=onSelect;onMoveRef.current=onDraftMove;selectedRef.current=selectedId;draftRef.current=draft;},[onSelect,onDraftMove,selectedId,draft]);
  useEffect(()=>{
    let cancelled=false;
    import("leaflet").then(async (module)=>{
      const L = (module as unknown as {default?:typeof import("leaflet")}).default ?? module;
      await import("leaflet.markercluster");
      if(cancelled || !container.current || mapRef.current) return;
      leafletRef.current=L;
      const map=L.map(container.current,{maxZoom:20,zoomControl:false,keyboard:true,zoomSnap:0.5,zoomDelta:0.5,inertia:true,wheelPxPerZoomLevel:110,wheelDebounceTime:20,zoomAnimation:true,markerZoomAnimation:true,preferCanvas:true}).setView([49.895,-97.138],9);
      L.control.zoom({position:"bottomleft"}).addTo(map);
      groupRef.current=L.markerClusterGroup({animate:true,animateAddingMarkers:true,maxClusterRadius:38,showCoverageOnHover:false,spiderfyOnMaxZoom:true,spiderfyDistanceMultiplier:1.8});
      groupRef.current.addTo(map); mapRef.current=map;setReady(true);
    }).catch((e:unknown)=>{if(!cancelled)setError(e instanceof Error?e.message:"Map failed to load");});
    const markersById=markerRefs.current;
    return ()=>{cancelled=true;mapRef.current?.remove();mapRef.current=null;groupRef.current=null;editorRef.current=null;markersById.clear();};
  },[]);
  // Replacing only tile layers preserves clusters, active drag state, markers,
  // current camera and draft coordinates. Leaflet maintains active attribution.
  useEffect(()=>{
    const L=leafletRef.current,map=mapRef.current;
    if(!ready||!L||!map)return;
    let active=true;setTileErrors(0);
    const layers=basemapTiles(basemap).map(({id: _id,...options})=>{
      const {url,...settings}=options;
      return L.tileLayer(url,settings).on("tileerror",()=>{if(active)setTileErrors((n)=>n+1);}).addTo(map);
    });
    return ()=>{active=false;layers.forEach((layer)=>layer.remove());};
  },[ready,basemap]);
  useEffect(()=>{
    const L=leafletRef.current,map=mapRef.current,group=groupRef.current;
    if(!ready||!L||!map||!group)return;
    group.clearLayers();markerRefs.current.clear();
    for(const item of markers){
      if(item.id===draft?.id)continue;
      const marker=L.marker([item.lat,item.lng],{title:item.title,alt:item.title,keyboard:true,bubblingMouseEvents:false,riseOnHover:true,icon:L.divIcon({className:"",html:markerHtml(item.color??"#17698c",item.approximate,item.manual),iconSize:[20,20],iconAnchor:[10,10],popupAnchor:[0,-12]})});
      marker.bindPopup(()=>popupContent(item));marker.on("click",()=>onSelectRef.current?.(item.id));group.addLayer(marker);markerRefs.current.set(item.id,marker);
    }
    if(markers.length&&!selectedRef.current&&!draftRef.current){
      const bounds=L.latLngBounds(markers.map((p)=>[p.lat,p.lng]));
      map.flyToBounds(bounds,{paddingTopLeft:map.getSize().x>700?[35,130]:[30,190],paddingBottomRight:map.getSize().x>700?[375,55]:[30,330],maxZoom:16,duration:0.7,easeLinearity:0.25});
    }
  },[ready,markers,draft?.id,fitKey]);
  useEffect(()=>{
    const map=mapRef.current,group=groupRef.current;
    if(!ready||!map||!selectedId||draft?.id)return;
    const marker=markerRefs.current.get(selectedId);
    if(marker){
      const point=marker.getLatLng();flyPoint(map,point.lat,point.lng,16);
      const open=()=>group?.zoomToShowLayer(marker,()=>marker.openPopup());
      map.once("moveend",open);return ()=>{map.off("moveend",open);};
    }
    if(focus)flyPoint(map,focus.lat,focus.lng,14);
  },[ready,selectedId,focus,draft?.id]);
  useEffect(()=>{
    const map=mapRef.current,L=leafletRef.current;
    if(!ready||!map||!L||!draft)return;
    const editor=L.marker([draft.lat,draft.lng],{draggable:true,keyboard:true,title:"Unsaved pin — drag, click map, or use arrow keys",alt:"Unsaved pin; arrow keys move it",zIndexOffset:1000,icon:L.divIcon({className:"",html:'<span style="display:block;width:26px;height:26px;background:#d36b23;border:4px solid white;border-radius:50%;box-shadow:0 0 0 3px #d36b2366,0 3px 12px #0005"></span>',iconSize:[26,26],iconAnchor:[13,13]})}).addTo(map);
    editorRef.current=editor;
    editor.on("dragend",()=>{const p=editor.getLatLng();onMoveRef.current?.(p.lat,p.lng);});
    const click=(e:import("leaflet").LeafletMouseEvent)=>onMoveRef.current?.(e.latlng.lat,e.latlng.lng);
    map.on("click",click);
    const element=editor.getElement();
    const key=(e:KeyboardEvent)=>{
      const delta:Record<string,[number,number]>={ArrowLeft:[-8,0],ArrowRight:[8,0],ArrowUp:[0,-8],ArrowDown:[0,8]};
      if(!delta[e.key])return;e.preventDefault();e.stopPropagation();
      const point=map.latLngToContainerPoint(editor.getLatLng());const [x,y]=delta[e.key];const p=map.containerPointToLatLng([point.x+x,point.y+y]);editor.setLatLng(p);onMoveRef.current?.(p.lat,p.lng);
    };
    element?.addEventListener("keydown",key);
    flyPoint(map,draft.lat,draft.lng,16);
    return ()=>{map.off("click",click);element?.removeEventListener("keydown",key);editor.remove();editorRef.current=null;};
    // Coordinates update the same draggable marker below, not its lifetime.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  },[ready,draft?.id]);
  useEffect(()=>{if(draft)editorRef.current?.setLatLng([draft.lat,draft.lng]);},[draft]);
  useEffect(()=>{
    const map=mapRef.current;if(!ready||!map||!container.current)return;
    const resize=()=>map.invalidateSize({pan:false,animate:false});
    const observer=new ResizeObserver(resize);observer.observe(container.current);window.addEventListener("resize",resize);const frame=requestAnimationFrame(resize);
    return ()=>{observer.disconnect();window.removeEventListener("resize",resize);cancelAnimationFrame(frame);};
  },[ready,resizeKey]);
  return <div className="absolute inset-0"><style>{`.marker-cluster { filter: drop-shadow(0 1px 3px #0009); outline: 2px solid #ffffffe6; } .leaflet-control-attribution { max-width: calc(100vw - 2rem); font-size: 9px; line-height: 1.25; } @media (min-width: 1024px) { .leaflet-control-attribution { max-width: calc(100vw - 18rem); } }`}</style><div ref={container} role="region" aria-label={ariaLabel} className="absolute inset-0 z-0 bg-[var(--ch-surface-muted)]"/>{error||tileErrors?<p role="alert" className="absolute bottom-8 left-14 z-10 rounded-lg bg-white/95 p-2 text-xs text-red-800">{error??`${tileErrors} map tiles failed to load`}</p>:null}</div>;
}
