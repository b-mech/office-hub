"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ChevronLeft, ChevronRight, Download, Minus, Plus, Redo2, Save, Trash2, Undo2, X } from "lucide-react";
import { Canvas, Ellipse, FabricObject, IText, Line, PencilBrush, Rect } from "fabric";
import type { TPointerEventInfo } from "fabric";
import type { PDFDocumentProxy } from "pdfjs-dist";
import {
  getTenderDocumentMarkup,
  getTenderDocumentMarkups,
  saveTenderDocumentMarkup,
  tenderDocumentMarkupPdfUrl,
  tenderDocumentUrl,
} from "@/lib/api/tendering";
import type { MarkupPageState, TenderDocument, TenderDocumentMarkupSummary, TenderMarkupCalibration } from "@/types/tendering";

type Tool = "select" | "pan" | "pen" | "rect" | "ellipse" | "line" | "arrow" | "text" | "measure";
const tools: { id: Tool; label: string }[] = [
  { id: "select", label: "Select" }, { id: "pan", label: "Pan" }, { id: "pen", label: "Pen" },
  { id: "rect", label: "Rectangle" }, { id: "ellipse", label: "Ellipse" },
  { id: "line", label: "Line" }, { id: "arrow", label: "Arrow" },
  { id: "text", label: "Text" }, { id: "measure", label: "Measure" },
];

export function PdfMarkupEditor({ document, onClose }: { document: TenderDocument; onClose: () => void }) {
  const pdfCanvasRef = useRef<HTMLCanvasElement>(null);
  const markupCanvasRef = useRef<HTMLCanvasElement>(null);
  const scrollAreaRef = useRef<HTMLElement>(null);
  const panRef = useRef<{ x: number; y: number; left: number; top: number } | null>(null);
  const fabricRef = useRef<Canvas | null>(null);
  const canvasPageRef = useRef(1);
  const pageStatesRef = useRef<Record<string, MarkupPageState>>({});
  const undoRef = useRef<string[]>([]);
  const redoRef = useRef<string[]>([]);
  const restoringRef = useRef(false);
  const [pdf, setPdf] = useState<PDFDocumentProxy | null>(null);
  const [pageNumber, setPageNumber] = useState(1);
  const [pageCount, setPageCount] = useState(0);
  const [tool, setTool] = useState<Tool>("select");
  const [color, setColor] = useState("#d7263d");
  const [strokeWidth, setStrokeWidth] = useState(3);
  const [zoom, setZoom] = useState(1);
  const [pageSize, setPageSize] = useState({ width: 0, height: 0 });
  const [calibration, setCalibration] = useState<TenderMarkupCalibration | null>(null);
  const [versions, setVersions] = useState<TenderDocumentMarkupSummary[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const showError = useCallback((reason: unknown) => setError(reason instanceof Error ? reason.message : "Markup request failed"), []);
  const loadVersions = useCallback(async () => setVersions(await getTenderDocumentMarkups(document.id)), [document.id]);

  useEffect(() => {
    let active = true;
    Promise.all([import("pdfjs-dist"), getTenderDocumentMarkups(document.id)]).then(([pdfjs, savedVersions]) => {
      if (!active) return;
      setVersions(savedVersions);
      pdfjs.GlobalWorkerOptions.workerSrc = new URL("pdfjs-dist/build/pdf.worker.min.mjs", import.meta.url).toString();
      return pdfjs.getDocument(tenderDocumentUrl(document.id)).promise;
    }).then((loaded) => { if (active && loaded) { setPdf(loaded); setPageCount(loaded.numPages); } }).catch(showError);
    return () => { active = false; };
  }, [document.id, showError]);

  const snapshot = useCallback(() => {
    const canvas = fabricRef.current;
    if (!canvas || restoringRef.current) return;
    pageStatesRef.current[String(pageNumber)] = pageState(canvas);
    undoRef.current.push(JSON.stringify(pageStatesRef.current[String(pageNumber)]));
    if (undoRef.current.length > 50) undoRef.current.shift();
    redoRef.current = [];
  }, [pageNumber]);

  useEffect(() => {
    if (!pdf || !pdfCanvasRef.current || !markupCanvasRef.current) return;
    let cancelled = false;
    const previous = fabricRef.current;
    if (previous) {
      pageStatesRef.current[String(canvasPageRef.current)] = pageState(previous);
      previous.destroy();
    }
    void pdf.getPage(pageNumber).then(async (page) => {
      if (cancelled || !pdfCanvasRef.current || !markupCanvasRef.current) return;
      const base = page.getViewport({ scale: 1 });
      const viewport = page.getViewport({ scale: Math.min(1.5, 1000 / base.width) });
      const pdfCanvas = pdfCanvasRef.current;
      pdfCanvas.width = viewport.width; pdfCanvas.height = viewport.height;
      setPageSize({ width: viewport.width, height: viewport.height });
      await page.render({ canvas: pdfCanvas, canvasContext: pdfCanvas.getContext("2d")!, viewport }).promise;
      if (cancelled) return;
      const canvas = new Canvas(markupCanvasRef.current, { width: viewport.width, height: viewport.height, selection: true });
      fabricRef.current = canvas;
      canvasPageRef.current = pageNumber;
      canvas.wrapperEl.style.position = "absolute";
      canvas.wrapperEl.style.inset = "0";
      const saved = pageStatesRef.current[String(pageNumber)];
      if (saved) { restoringRef.current = true; await canvas.loadFromJSON({ objects: saved.objects }); restoringRef.current = false; canvas.requestRenderAll(); }
      undoRef.current = [JSON.stringify(pageState(canvas))]; redoRef.current = [];
      canvas.on("object:added", snapshot); canvas.on("object:modified", snapshot); canvas.on("object:removed", snapshot);
    }).catch(showError);
    return () => {
      cancelled = true;
      const canvas = fabricRef.current;
      if (canvas && canvasPageRef.current === pageNumber) {
        pageStatesRef.current[String(pageNumber)] = pageState(canvas);
        canvas.destroy();
        fabricRef.current = null;
      }
    };
  }, [pdf, pageNumber, snapshot, showError]);

  useEffect(() => {
    const canvas = fabricRef.current;
    if (!canvas) return;
    canvas.isDrawingMode = tool === "pen";
    canvas.selection = tool === "select";
    canvas.skipTargetFind = tool !== "select";
    if (tool === "pen") {
      const brush = new PencilBrush(canvas); brush.color = color; brush.width = strokeWidth; canvas.freeDrawingBrush = brush;
    }
    let start: { x: number; y: number } | null = null;
    let end: { x: number; y: number } | null = null;
    let shape: FabricObject | null = null;
    const down = (event: TPointerEventInfo) => {
      if (["select", "pan", "pen"].includes(tool)) return;
      const point = canvas.getScenePoint(event.e); start = { x: point.x, y: point.y }; end = start;
      if (tool === "text") {
        const text = new IText("Type here", { left: point.x, top: point.y, fill: color, fontSize: 20 });
        canvas.add(text);
        canvas.setActiveObject(text);
        text.enterEditing();
        text.selectAll();
        canvas.requestRenderAll();
        window.setTimeout(() => text.hiddenTextarea?.focus(), 0);
        start = null; end = null;
        return;
      }
      if (tool === "rect") shape = new Rect({ left: point.x, top: point.y, width: 1, height: 1, fill: "transparent", stroke: color, strokeWidth, selectable: false });
      else if (tool === "ellipse") shape = new Ellipse({ left: point.x, top: point.y, rx: 1, ry: 1, fill: "transparent", stroke: color, strokeWidth, selectable: false });
      else shape = new Line([point.x, point.y, point.x, point.y], { stroke: color, strokeWidth, selectable: false });
      if (shape) { if (tool === "arrow" || tool === "measure") shape.set("annotationKind" as keyof FabricObject, tool as never); canvas.add(shape); }
    };
    const move = (event: TPointerEventInfo) => {
      if (!start || !shape) return; const point = canvas.getScenePoint(event.e); end = { x: point.x, y: point.y };
      if (shape instanceof Rect) shape.set({ left: Math.min(start.x, point.x), top: Math.min(start.y, point.y), width: Math.abs(point.x - start.x), height: Math.abs(point.y - start.y) });
      else if (shape instanceof Ellipse) shape.set({ left: Math.min(start.x, point.x), top: Math.min(start.y, point.y), rx: Math.abs(point.x - start.x) / 2, ry: Math.abs(point.y - start.y) / 2 });
      else if (shape instanceof Line) shape.set({ x2: point.x, y2: point.y });
      canvas.requestRenderAll();
    };
    const up = () => {
      if (!start || !end || !shape) return;
      shape.set({ selectable: true }); shape.setCoords();
      if (tool === "arrow" && shape instanceof Line) {
        const angle = Math.atan2(end.y - start.y, end.x - start.x);
        const length = Math.max(10, strokeWidth * 4);
        for (const delta of [Math.PI * 0.8, -Math.PI * 0.8]) {
          canvas.add(new Line([
            end.x,
            end.y,
            end.x + length * Math.cos(angle + delta),
            end.y + length * Math.sin(angle + delta),
          ], { stroke: color, strokeWidth }));
        }
      }
      if (tool === "measure" && shape instanceof Line) {
        const pixels = Math.hypot(end.x - start.x, end.y - start.y);
        const nextCalibration = calibration || promptForCalibration(pixels);
        if (!nextCalibration) { canvas.remove(shape); } else {
          if (!calibration) setCalibration(nextCalibration);
          const distance = pixels / nextCalibration.pixel_distance * nextCalibration.real_distance;
          const label = new IText(`~${distance.toFixed(2)} ${nextCalibration.unit}`, { left: (start.x + end.x) / 2, top: (start.y + end.y) / 2, fill: color, fontSize: 15 });
          label.set("annotationKind" as keyof FabricObject, "measurement-label" as never); canvas.add(label);
        }
      }
      start = null; end = null; shape = null; snapshot();
    };
    canvas.on("mouse:down", down); canvas.on("mouse:move", move); canvas.on("mouse:up", up);
    return () => { canvas.off("mouse:down", down); canvas.off("mouse:move", move); canvas.off("mouse:up", up); };
  }, [tool, color, strokeWidth, calibration, snapshot]);

  async function save() {
    const canvas = fabricRef.current; if (!canvas) return;
    pageStatesRef.current[String(pageNumber)] = pageState(canvas); setSaving(true); setError(null);
    try { await saveTenderDocumentMarkup(document.id, { schema_version: 1, pages: pageStatesRef.current }, calibration); await loadVersions(); }
    catch (reason) { showError(reason); } finally { setSaving(false); }
  }
  async function loadVersion(id: string) {
    try {
      const version = await getTenderDocumentMarkup(id); pageStatesRef.current = version.annotation_data.pages; setCalibration(version.calibration || null);
      if (pageNumber !== 1) setPageNumber(1);
      else if (fabricRef.current) { restoringRef.current = true; await fabricRef.current.loadFromJSON({ objects: pageStatesRef.current["1"]?.objects || [] }); restoringRef.current = false; fabricRef.current.requestRenderAll(); }
    }
    catch (reason) { showError(reason); }
  }
  async function history(direction: "undo" | "redo") {
    const canvas = fabricRef.current; if (!canvas) return;
    const from = direction === "undo" ? undoRef.current : redoRef.current; const to = direction === "undo" ? redoRef.current : undoRef.current;
    if (from.length < 2) return; to.push(from.pop()!); const state = JSON.parse(from[from.length - 1]) as MarkupPageState;
    restoringRef.current = true; await canvas.loadFromJSON({ objects: state.objects }); restoringRef.current = false; canvas.requestRenderAll();
  }
  return <div className="fixed inset-0 z-50 flex flex-col bg-[var(--ch-bg)] text-[var(--ch-text)]">
    <header className="flex flex-wrap items-center gap-2 border-b border-[var(--ch-border)] bg-[var(--ch-surface)] p-3">
      <strong className="mr-2 min-w-48 truncate">Markup · {document.original_filename}</strong>
      {tools.map(item => <button key={item.id} onClick={() => setTool(item.id)} className={`rounded-md border px-2 py-1.5 text-xs ${tool === item.id ? "border-[var(--ch-accent)] bg-[var(--ch-accent)] text-[var(--ch-accent-text)]" : "border-[var(--ch-border)]"}`}>{item.label}</button>)}
      <input aria-label="Markup color" type="color" value={color} onChange={event => setColor(event.target.value)} className="h-8 w-9"/>
      <input aria-label="Stroke width" type="range" min="1" max="10" value={strokeWidth} onChange={event => setStrokeWidth(Number(event.target.value))}/>
      <div className="flex items-center rounded-md border border-[var(--ch-border)]">
        <button aria-label="Zoom out" disabled={zoom <= 0.5} onClick={() => setZoom(value => Math.max(0.5, value - 0.25))} className="p-1.5 disabled:opacity-40"><Minus size={15}/></button>
        <button title="Reset zoom" onClick={() => setZoom(1)} className="min-w-12 border-x border-[var(--ch-border)] px-1.5 py-1 text-xs">{Math.round(zoom * 100)}%</button>
        <button aria-label="Zoom in" disabled={zoom >= 2} onClick={() => setZoom(value => Math.min(2, value + 0.25))} className="p-1.5 disabled:opacity-40"><Plus size={15}/></button>
      </div>
      <button onClick={() => void history("undo")} title="Undo"><Undo2 size={17}/></button><button onClick={() => void history("redo")} title="Redo"><Redo2 size={17}/></button>
      <button onClick={() => { fabricRef.current?.clear(); snapshot(); }} title="Clear page"><Trash2 size={17}/></button>
      <button onClick={() => { setCalibration(null); setTool("measure"); }} className="rounded-md border border-[var(--ch-border)] px-2 py-1.5 text-xs">Recalibrate</button>
      <button disabled={saving} onClick={() => void save()} className="ml-auto inline-flex items-center gap-1 rounded-md bg-[var(--ch-accent)] px-3 py-2 text-xs font-semibold text-[var(--ch-accent-text)] disabled:opacity-50"><Save size={15}/>{saving ? "Saving…" : "Save Version"}</button>
      <button onClick={onClose} aria-label="Close editor"><X size={20}/></button>
    </header>
    {error ? <p className="bg-[var(--ch-error-bg)] px-4 py-2 text-sm text-[var(--ch-error-text)]">{error}</p> : null}
    <div className="flex min-h-0 flex-1">
      <main
        ref={scrollAreaRef}
        className={`min-w-0 flex-1 overflow-auto bg-neutral-700 p-6 ${tool === "pan" ? "cursor-grab active:cursor-grabbing" : ""}`}
        onPointerDown={event => { const area = scrollAreaRef.current; if (tool === "pan" && area) { panRef.current = { x: event.clientX, y: event.clientY, left: area.scrollLeft, top: area.scrollTop }; event.currentTarget.setPointerCapture(event.pointerId); } }}
        onPointerMove={event => { const area = scrollAreaRef.current; const origin = panRef.current; if (tool === "pan" && area && origin) { area.scrollLeft = origin.left - (event.clientX - origin.x); area.scrollTop = origin.top - (event.clientY - origin.y); } }}
        onPointerUp={() => { panRef.current = null; }}
      ><div
        className="relative mx-auto shadow-xl"
        style={{
          width: pageSize.width * zoom || undefined,
          height: pageSize.height * zoom || undefined,
        }}
      ><div className="absolute left-0 top-0 origin-top-left" style={{ transform: `scale(${zoom})` }}><canvas ref={pdfCanvasRef}/><canvas ref={markupCanvasRef} className="absolute inset-0"/></div></div></main>
      <aside className="w-64 shrink-0 overflow-auto border-l border-[var(--ch-border)] bg-[var(--ch-surface)] p-3">
        <div className="mb-4 flex items-center justify-between"><button disabled={pageNumber <= 1} onClick={() => setPageNumber(value => value - 1)}><ChevronLeft/></button><span className="text-sm">Page {pageNumber} / {pageCount || "…"}</span><button disabled={pageNumber >= pageCount} onClick={() => setPageNumber(value => value + 1)}><ChevronRight/></button></div>
        <h3 className="text-sm font-semibold">Versions</h3><p className="mb-2 text-xs text-[var(--ch-text-muted)]">Latest five are retained.</p>
        <div className="space-y-2">{versions.length === 0 ? <p className="text-xs text-[var(--ch-text-muted)]">No saved versions yet.</p> : versions.map(version => <div key={version.id} className="rounded-md border border-[var(--ch-border)] p-2 text-xs"><button onClick={() => void loadVersion(version.id)} className="block w-full text-left font-semibold">Version {version.version_number}</button><time className="text-[var(--ch-text-muted)]">{new Date(version.created_at).toLocaleString("en-CA")}</time><a href={tenderDocumentMarkupPdfUrl(version.id)} className="mt-2 inline-flex items-center gap-1 text-[var(--ch-accent)]"><Download size={13}/>Flattened PDF</a></div>)}</div>
        <p className="mt-4 text-[10px] text-[var(--ch-text-muted)]">Measurements marked “~” are visual estimates, not authoritative takeoffs.</p>
      </aside>
    </div>
  </div>;
}

function pageState(canvas: Canvas): MarkupPageState { const json = canvas.toObject(["annotationKind", "measurementLabel"]); return { width: canvas.width, height: canvas.height, objects: json.objects as Record<string, unknown>[] }; }
function promptForCalibration(pixelDistance: number): TenderMarkupCalibration | null {
  const lengthText = window.prompt("Calibration: enter the real length of this reference line."); if (!lengthText) return null;
  const realDistance = Number(lengthText); if (!Number.isFinite(realDistance) || realDistance <= 0) { window.alert("Enter a positive number."); return null; }
  const unitText = window.prompt("Unit: in, ft, mm, cm, or m", "ft") || ""; if (!["in", "ft", "mm", "cm", "m"].includes(unitText)) { window.alert("Use in, ft, mm, cm, or m."); return null; }
  return { pixel_distance: pixelDistance, real_distance: realDistance, unit: unitText as TenderMarkupCalibration["unit"] };
}
