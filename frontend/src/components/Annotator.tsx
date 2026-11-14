"use client";
import { Trash2, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { useApi } from "@/lib/auth";
import { Notice } from "./ui";

interface Ann { defect_type: string; shape: "bbox" | "polygon"; bbox?: number[] | null; polygon?: number[][] | null; source?: string }
const COLORS = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#9085e9"];

/** Label an image: draw bounding boxes (drag) or polygon masks (click points, double-click to close). */
export default function Annotator({ datasetId, image, editable, onClose, onSaved }: { datasetId: number; image: any; editable: boolean; onClose: () => void; onSaved: (im: any) => void }) {
  const tax = useApi<{ type: string; label: string; category: string }[]>("/taxonomy");
  const [anns, setAnns] = useState<Ann[]>(image.annotations);
  const [label, setLabel] = useState<string>(image.label);
  const [group, setGroup] = useState<string>(image.group_key ?? "");
  const [tool, setTool] = useState<"bbox" | "polygon">("bbox");
  const [type, setType] = useState("scratch");
  const [draft, setDraft] = useState<number[][] | null>(null);
  const [sel, setSel] = useState<number | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const svg = useRef<SVGSVGElement>(null);
  const types = (tax.data ?? []).filter((t) => t.category !== "unclassified");
  const classes = Array.from(new Set(anns.map((a) => a.defect_type)));
  const color = (t: string) => COLORS[classes.indexOf(t) % COLORS.length] ?? COLORS[0];
  const sw = Math.max(1.5, image.width / 500);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") (draft ? setDraft(null) : onClose()); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [draft, onClose]);

  const pt = (e: React.PointerEvent | React.MouseEvent) => {
    const r = svg.current!.getBoundingClientRect();
    return [Math.round(Math.min(image.width, Math.max(0, ((e.clientX - r.left) / r.width) * image.width))), Math.round(Math.min(image.height, Math.max(0, ((e.clientY - r.top) / r.height) * image.height)))];
  };
  const add = (a: Ann) => { setAnns((c) => [...c, a]); setLabel("defective"); setSel(anns.length); };
  const down = (e: React.PointerEvent) => {
    if (!editable) return;
    const p = pt(e);
    if (tool === "bbox") { setDraft([p, p]); (e.target as Element).setPointerCapture(e.pointerId); }
    else setDraft((d) => (d ? [...d, p] : [p]));
  };
  const move = (e: React.PointerEvent) => { if (tool === "bbox" && draft) setDraft([draft[0], pt(e)]); };
  const up = () => {
    if (tool !== "bbox" || !draft) return;
    const [a, b] = draft;
    const w = Math.abs(b[0] - a[0]), h = Math.abs(b[1] - a[1]);
    if (w >= 3 && h >= 3) add({ defect_type: type, shape: "bbox", bbox: [Math.min(a[0], b[0]), Math.min(a[1], b[1]), w, h] });
    setDraft(null);
  };
  const closePoly = () => { if (tool === "polygon" && draft && draft.length >= 3) { add({ defect_type: type, shape: "polygon", polygon: draft }); } setDraft(null); };

  const save = async () => {
    setBusy(true); setErr(null);
    try {
      const body: any = { annotations: anns.map((a) => ({ defect_type: a.defect_type, shape: a.shape, bbox: a.shape === "bbox" ? a.bbox : null, polygon: a.shape === "polygon" ? a.polygon : null })), label, group_key: group };
      onSaved(await api(`/datasets/${datasetId}/images/${image.id}`, { method: "PATCH", json: body }));
    } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  };

  return (
    <div className="fixed inset-0 z-50 flex bg-black/80 p-4" role="dialog" aria-modal="true" aria-label="Annotate image">
      <div className="card flex min-w-0 flex-1 flex-col lg:flex-row">
        <div className="relative grid min-h-0 flex-1 place-items-center overflow-hidden bg-[#0b0c0d] p-3">
          <div className="relative max-h-full" style={{ aspectRatio: `${image.width} / ${image.height}`, maxWidth: "100%", height: "100%" }}>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={image.image_url} alt={image.filename} className="h-full w-full object-contain" draggable={false} />
            <svg ref={svg} viewBox={`0 0 ${image.width} ${image.height}`} className={`absolute inset-0 h-full w-full ${editable ? "cursor-crosshair" : ""}`} onPointerDown={down} onPointerMove={move} onPointerUp={up} onDoubleClick={closePoly}>
              {anns.map((a, i) => {
                const c = color(a.defect_type);
                const on = () => (e: React.PointerEvent) => { if (!draft) { e.stopPropagation(); setSel(i); } };
                return a.shape === "polygon" && a.polygon
                  ? <polygon key={i} points={a.polygon.map((p) => p.join(",")).join(" ")} fill={c} fillOpacity={sel === i ? 0.45 : 0.25} stroke={c} strokeWidth={sw} onPointerDown={on()} />
                  : a.bbox && <rect key={i} x={a.bbox[0]} y={a.bbox[1]} width={a.bbox[2]} height={a.bbox[3]} fill={c} fillOpacity={sel === i ? 0.3 : 0.08} stroke={c} strokeWidth={sw} onPointerDown={on()} />;
              })}
              {draft && tool === "bbox" && <rect x={Math.min(draft[0][0], draft[1][0])} y={Math.min(draft[0][1], draft[1][1])} width={Math.abs(draft[1][0] - draft[0][0])} height={Math.abs(draft[1][1] - draft[0][1])} fill="none" stroke="#fff" strokeDasharray={`${4 * sw} ${3 * sw}`} strokeWidth={sw} />}
              {draft && tool === "polygon" && <><polyline points={draft.map((p) => p.join(",")).join(" ")} fill="none" stroke="#fff" strokeWidth={sw} />{draft.map((p, i) => <circle key={i} cx={p[0]} cy={p[1]} r={sw * 2.5} fill="#fff" />)}</>}
            </svg>
          </div>
        </div>
        <aside className="flex w-full shrink-0 flex-col border-t border-line lg:w-80 lg:border-l lg:border-t-0">
          <div className="card-h"><h2 className="card-t truncate">{image.filename || `Image ${image.id}`}</h2><button aria-label="Close" onClick={onClose} className="p-1 text-muted hover:text-ink"><X size={16} /></button></div>
          <div className="flex-1 space-y-4 overflow-y-auto p-4 text-sm">
            <div><span className="label">Image label</span>
              <div className="flex gap-1.5">{["good", "defective", "unlabeled"].map((l) => (
                <button key={l} disabled={!editable || (l === "good" && anns.length > 0)} onClick={() => setLabel(l)} className={`btn btn-sm capitalize ${label === l ? "border-accent bg-accent/20" : ""}`}>{l === "good" ? "Defect-free" : l}</button>))}</div></div>
            {editable && (
              <div><span className="label">Draw defect</span>
                <div className="mb-2 flex gap-1.5">{(["bbox", "polygon"] as const).map((t) => <button key={t} onClick={() => { setTool(t); setDraft(null); }} className={`btn btn-sm ${tool === t ? "border-accent bg-accent/20" : ""}`}>{t === "bbox" ? "Bounding box" : "Mask (polygon)"}</button>)}</div>
                <select aria-label="Defect type" className="input" value={type} onChange={(e) => setType(e.target.value)}>{types.map((t) => <option key={t.type} value={t.type}>{t.label}</option>)}</select>
                <p className="mt-1.5 text-xs text-muted">{tool === "bbox" ? "Drag on the image to draw a box." : "Click to add points, double-click to close the mask. Esc cancels."}</p></div>)}
            <div><span className="label">Annotations ({anns.length})</span>
              {anns.length === 0 ? <p className="text-xs text-muted">None.</p> : (
                <ul className="space-y-1">{anns.map((a, i) => (
                  <li key={i} className={`flex items-center gap-2 rounded border px-2 py-1 ${sel === i ? "border-accent bg-raised" : "border-line"}`} onClick={() => setSel(i)}>
                    <i className="h-2.5 w-2.5 rounded-sm" style={{ background: color(a.defect_type) }} /><span className="flex-1 truncate text-ink2">{a.defect_type}</span>
                    <span className="text-[11px] text-muted">{a.shape === "polygon" ? "mask" : "box"}{a.source && a.source !== "human" ? ` · ${a.source.replace("_", " ")}` : ""}</span>
                    {editable && <button aria-label="Delete annotation" className="text-muted hover:text-ink" onClick={(e) => { e.stopPropagation(); setAnns((c) => c.filter((_, j) => j !== i)); setSel(null); }}><Trash2 size={13} /></button>}
                  </li>))}</ul>)}</div>
            <label className="block"><span className="label">Leakage group (serial / part ID)</span>
              <input className="input" value={group} disabled={!editable} onChange={(e) => setGroup(e.target.value)} placeholder="images of the same part share a key" /></label>
            <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs text-muted"><dt>Split</dt><dd className="text-ink2">{image.split}</dd><dt>Size</dt><dd className="text-ink2">{image.width}×{image.height}px</dd>
              {image.source_inspection_id && <><dt>Origin</dt><dd className="text-ink2">reviewed inspection {image.source_inspection_id.slice(0, 8)}</dd></>}</dl>
            {err && <Notice tone="error">{err}</Notice>}
          </div>
          {editable && <div className="flex gap-2 border-t border-line p-3"><button className="btn flex-1" onClick={onClose}>Cancel</button><button className="btn btn-primary flex-1" disabled={busy} onClick={save}>{busy ? "Saving…" : "Save labels"}</button></div>}
        </aside>
      </div>
    </div>
  );
}
