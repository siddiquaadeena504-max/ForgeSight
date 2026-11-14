"use client";
import clsx from "clsx";
import { Maximize, Minus, Plus } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import type { Finding } from "@/lib/api";

export const SEV_COLOR: Record<string, string> = { minor: "#fab219", major: "#ec835a", critical: "#e25555" };

export interface Layers { boxes: boolean; masks: boolean; heatmap: boolean; markers: boolean }
type Overlay = Pick<Finding, "bbox" | "polygon" | "severity" | "label"> & { idx?: number; centroid?: [number, number]; confidence?: number; qc_status?: string };

/** Zoom/pan image viewer with defect overlays (boxes, masks, heatmap, markers) and a before/after wipe. */
export default function ImageViewer({ src, width, height, heatmapUrl, findings, layers, selected, onSelect, compareSrc, compareLabel, className, children }: {
  src: string; width: number; height: number; heatmapUrl?: string | null; findings: Overlay[]; layers: Layers; selected?: number | null;
  onSelect?: (idx: number | null) => void; compareSrc?: string | null; compareLabel?: string; className?: string; children?: React.ReactNode;
}) {
  const box = useRef<HTMLDivElement>(null);
  const [view, setView] = useState({ s: 1, x: 0, y: 0 });
  const [fit, setFit] = useState(1);
  const [wipe, setWipe] = useState(0.5);
  const drag = useRef<{ x: number; y: number; vx: number; vy: number; moved: boolean } | null>(null);

  const doFit = useCallback(() => {
    const el = box.current;
    if (!el || !width) return;
    const f = Math.min(el.clientWidth / width, el.clientHeight / height);
    setFit(f);
    setView({ s: f, x: (el.clientWidth - width * f) / 2, y: (el.clientHeight - height * f) / 2 });
  }, [width, height]);
  useEffect(() => {
    doFit();
    const ro = new ResizeObserver(doFit);
    if (box.current) ro.observe(box.current);
    return () => ro.disconnect();
  }, [doFit]);

  const zoomAt = (cx: number, cy: number, factor: number) =>
    setView((v) => {
      const s = Math.min(fit * 24, Math.max(fit * 0.5, v.s * factor));
      const k = s / v.s;
      return { s, x: cx - (cx - v.x) * k, y: cy - (cy - v.y) * k };
    });
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const r = el.getBoundingClientRect();
      zoomAt(e.clientX - r.left, e.clientY - r.top, e.deltaY < 0 ? 1.15 : 1 / 1.15);
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fit]);

  const centre = () => { const el = box.current!; return [el.clientWidth / 2, el.clientHeight / 2] as const; };
  const sw = Math.max(1, 1.6 / view.s); // constant on-screen stroke
  const fs = 12 / view.s;
  const clip = compareSrc ? `inset(0 0 0 ${wipe * 100}%)` : undefined;

  return (
    <div className={clsx("relative select-none overflow-hidden rounded border border-line bg-[#0b0c0d]", className)}>
      <div ref={box} className="absolute inset-0 cursor-grab touch-none active:cursor-grabbing"
        onPointerDown={(e) => { (e.target as Element).setPointerCapture?.(e.pointerId); drag.current = { x: e.clientX, y: e.clientY, vx: view.x, vy: view.y, moved: false }; }}
        onPointerMove={(e) => { const d = drag.current; if (!d) return; const dx = e.clientX - d.x, dy = e.clientY - d.y; if (Math.abs(dx) + Math.abs(dy) > 3) d.moved = true; setView((v) => ({ ...v, x: d.vx + dx, y: d.vy + dy })); }}
        onPointerUp={() => { if (drag.current && !drag.current.moved) onSelect?.(null); drag.current = null; }}>
        <div style={{ transform: `translate(${view.x}px, ${view.y}px) scale(${view.s})`, transformOrigin: "0 0", width, height, position: "absolute" }}>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={compareSrc ?? src} alt={compareSrc ? compareLabel ?? "Comparison image" : "Inspected part"} width={width} height={height} draggable={false} className="absolute left-0 top-0 block max-w-none" style={{ imageRendering: view.s > fit * 6 ? "pixelated" : "auto" }} />
          <div className="absolute left-0 top-0" style={{ width, height, clipPath: clip }}>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            {compareSrc && <img src={src} alt="Inspected part" width={width} height={height} draggable={false} className="absolute left-0 top-0 block max-w-none" />}
            {/* eslint-disable-next-line @next/next/no-img-element */}
            {layers.heatmap && heatmapUrl && <img src={heatmapUrl} alt="" width={width} height={height} draggable={false} className="absolute left-0 top-0 block max-w-none opacity-80" />}
            <svg viewBox={`0 0 ${width} ${height}`} width={width} height={height} className="absolute left-0 top-0 overflow-visible">
              {findings.map((f, i) => {
                const idx = f.idx ?? i + 1;
                const col = SEV_COLOR[f.severity.level] ?? "#c3c2b7";
                const sel = selected === idx;
                const dim = f.qc_status === "rejected";
                const [x, y, w, h] = f.bbox;
                return (
                  <g key={idx} opacity={dim ? 0.35 : 1} className="cursor-pointer" onPointerUp={(e) => { if (!drag.current?.moved) { e.stopPropagation(); drag.current = null; onSelect?.(idx); } }}>
                    {layers.masks && f.polygon?.length >= 3 && <polygon points={f.polygon.map((p) => p.join(",")).join(" ")} fill={col} fillOpacity={sel ? 0.45 : 0.25} stroke={col} strokeWidth={sw} strokeLinejoin="round" />}
                    {layers.boxes && <rect x={x} y={y} width={w} height={h} fill="transparent" stroke={col} strokeWidth={sel ? sw * 2 : sw} strokeDasharray={dim ? `${4 * sw} ${3 * sw}` : undefined} />}
                    {!layers.boxes && !layers.masks && <rect x={x} y={y} width={w} height={h} fill="transparent" />}
                    {layers.markers && (
                      <g transform={`translate(${x}, ${Math.max(fs * 1.5, y - fs * 0.4)})`}>
                        <rect x={0} y={-fs * 1.25} width={fs * (String(idx).length * 0.62 + 0.9)} height={fs * 1.45} fill={col} rx={fs * 0.15} />
                        <text x={fs * 0.45} y={-fs * 0.18} fontSize={fs} fontWeight={700} fill="#111214">{idx}</text>
                      </g>
                    )}
                  </g>
                );
              })}
              {children}
            </svg>
          </div>
          {compareSrc && <div className="absolute top-0 bg-white/80" style={{ left: wipe * width, width: sw * 1.2, height }} />}
        </div>
      </div>
      {compareSrc && (
        <div className="absolute inset-x-3 bottom-3 flex items-center gap-2 rounded bg-black/70 px-2 py-1 text-[11px] text-ink2">
          <span>{compareLabel ?? "Before"}</span>
          <input aria-label="Before / after position" type="range" min={0} max={1} step={0.005} value={wipe} onChange={(e) => setWipe(+e.target.value)} className="flex-1 accent-[#3987e5]" />
          <span>Inspected + findings</span>
        </div>
      )}
      <div className="absolute right-2 top-2 flex flex-col overflow-hidden rounded border border-line bg-panel/90">
        <button type="button" aria-label="Zoom in" className="p-1.5 hover:bg-raised" onClick={() => zoomAt(...centre(), 1.4)}><Plus size={14} /></button>
        <button type="button" aria-label="Zoom out" className="border-y border-line p-1.5 hover:bg-raised" onClick={() => zoomAt(...centre(), 1 / 1.4)}><Minus size={14} /></button>
        <button type="button" aria-label="Fit to view" className="p-1.5 hover:bg-raised" onClick={doFit}><Maximize size={14} /></button>
      </div>
      <div className="pointer-events-none absolute left-2 top-2 rounded bg-black/60 px-1.5 py-0.5 text-[10px] tabular-nums text-ink2">{Math.round((view.s / 1) * 100)}% · {width}×{height}px</div>
    </div>
  );
}
