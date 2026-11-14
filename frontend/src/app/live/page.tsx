"use client";
import { Camera, FileVideo, Square } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import MaterialProfilePicker from "@/components/MaterialProfilePicker";
import { Card, Field, Notice, OutcomeBadge, PageHeader, Stat, Tag } from "@/components/ui";
import { api, type Material, type Outcome } from "@/lib/api";
import { useApi, useAuth } from "@/lib/auth";

interface LiveFinding { label: string; defect_type: string; type_source: string; bbox: number[]; polygon: number[][]; severity: { level: string }; confidence: number; location: string }
interface FrameResult { decision: { outcome: Outcome; p_defect: number | null; reasons: string[] }; quality: { status: string }; processing_ms: number; image: { width: number; height: number };
  findings: LiveFinding[]; saved_inspection_id: string | null }
interface Event { t: string; pos: number | null; outcome: Outcome; n: number; top: string; id: string | null }

const OUT = { pass: { c: "#22c55e", t: "OK" }, review: { c: "#fab219", t: "REVIEW" }, defective: { c: "#ef4444", t: "NG" } } as const;
const fmtPos = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}.${Math.floor((s % 1) * 10)}`;

export default function Live() {
  const { can } = useAuth();
  const mats = useApi<Material[]>("/materials");
  const [material, setMaterial] = useState("");
  const [profile, setProfile] = useState("");
  const [batch, setBatch] = useState("");
  const [interval, setIntervalS] = useState("0.5");
  const [save, setSave] = useState("flagged");
  const [mode, setMode] = useState<"learn" | "profile">("learn");
  const [learnSeconds, setLearnSeconds] = useState("5");
  const [sensitivity, setSensitivity] = useState("normal");
  const [phase, setPhase] = useState<string | null>(null);
  const session = useRef<string | null>(null);
  const [running, setRunning] = useState(false);
  const [source, setSource] = useState<"camera" | "file" | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [last, setLast] = useState<FrameResult | null>(null);
  const [stats, setStats] = useState({ frames: 0, pass: 0, clear: 0, review: 0, defective: 0, ms: 0, fps: 0, defects: 0 });
  const [events, setEvents] = useState<Event[]>([]);
  const [progress, setProgress] = useState<number | null>(null);
  const video = useRef<HTMLVideoElement>(null);
  const canvas = useRef<HTMLCanvasElement | null>(null);
  const loop = useRef<{ stop: boolean }>({ stop: true });
  const stream = useRef<MediaStream | null>(null);
  const prof = mats.data?.flatMap((m) => m.profiles).find((p) => p.key === profile);

  const stop = () => {
    loop.current.stop = true;
    stream.current?.getTracks().forEach((t) => t.stop());
    stream.current = null;
    video.current?.pause();
    if (video.current?.srcObject) video.current.srcObject = null;
    setRunning(false);
  };
  useEffect(() => stop, []); // eslint-disable-line react-hooks/exhaustive-deps

  const analyse = async (v: HTMLVideoElement): Promise<FrameResult> => {
    canvas.current ??= document.createElement("canvas");
    const c = canvas.current;
    c.width = v.videoWidth; c.height = v.videoHeight;
    c.getContext("2d")!.drawImage(v, 0, 0);
    const blob: Blob = await new Promise((r) => c.toBlob((b) => r(b!), "image/jpeg", 0.92));
    const fd = new FormData();
    fd.append("file", blob, "frame.jpg");
    if (material) fd.append("material_key", material);
    if (profile && mode === "profile") fd.append("profile_key", profile);
    if (session.current) { fd.append("session_id", session.current); fd.append("sensitivity", sensitivity); }
    if (batch) fd.append("batch_id", batch);
    fd.append("save", save);
    return api<FrameResult>("/live/frame", { form: fd });
  };
  const grab = async (v: HTMLVideoElement): Promise<Blob> => {
    canvas.current ??= document.createElement("canvas");
    const c = canvas.current;
    c.width = v.videoWidth; c.height = v.videoHeight;
    c.getContext("2d")!.drawImage(v, 0, 0);
    return new Promise((r) => c.toBlob((b) => r(b!), "image/jpeg", 0.92));
  };
  /** Fit the normal appearance of the material from defect-free frames; later frames are compared against it. */
  const learn = async (blobs: Blob[]) => {
    setPhase(`Learning normal appearance from ${blobs.length} reference frames…`);
    const fd = new FormData();
    blobs.forEach((b, i) => fd.append("files", b, `ref_${i}.jpg`));
    const info = await api<{ session_id: string }>("/live/reference", { form: fd });
    session.current = info.session_id;
    setPhase(null);
  };
  const record = (r: FrameResult, pos: number | null, dt: number) => {
    setLast(r);
    const clear = r.decision.outcome === "review" && r.findings.length === 0 && r.quality.status !== "fail";
    setStats((s) => ({ frames: s.frames + 1, pass: s.pass + +(r.decision.outcome === "pass"), clear: s.clear + +clear, review: s.review + +(r.decision.outcome === "review" && !clear),
      defective: s.defective + +(r.decision.outcome === "defective"), ms: s.ms + r.processing_ms, fps: 1000 / Math.max(1, dt), defects: s.defects + r.findings.length }));
    if (r.decision.outcome !== "pass" && !clear)
      setEvents((e) => [{ t: new Date().toLocaleTimeString(), pos, outcome: r.decision.outcome, n: r.findings.length, top: r.findings[0]?.label ?? "no finding", id: r.saved_inspection_id }, ...e].slice(0, 200));
  };
  const begin = () => {
    const ctl = { stop: false };
    loop.current = ctl;
    setRunning(true); setErr(null); setLast(null); setEvents([]); setProgress(null);
    setStats({ frames: 0, pass: 0, clear: 0, review: 0, defective: 0, ms: 0, fps: 0, defects: 0 });
    session.current = null;
    return ctl;
  };

  /** Camera: the feed keeps running; a frame is analysed every `interval` seconds. */
  const startCamera = async () => {
    try {
      const s = await navigator.mediaDevices.getUserMedia({ video: { width: { ideal: 1280 }, height: { ideal: 720 }, facingMode: "environment" }, audio: false });
      stream.current = s;
      const v = video.current!;
      v.srcObject = s;
      await v.play();
      setSource("camera");
      const ctl = begin();
      if (mode === "learn") {
        try {
          const n = 12, gap = Math.max(150, ((parseFloat(learnSeconds) || 5) * 1000) / n);
          const blobs: Blob[] = [];
          for (let i = 0; i < n && !ctl.stop; i++) {
            setPhase(`Show defect-free material: capturing reference frame ${i + 1} of ${n}…`);
            await new Promise((r) => setTimeout(r, gap));
            blobs.push(await grab(v));
          }
          if (!ctl.stop) await learn(blobs);
        } catch (e: any) { setErr(e.message); setPhase(null); stop(); return; }
      }
      while (!ctl.stop) {
        const t0 = performance.now();
        if (v.readyState >= 2 && v.videoWidth) {
          try { const r = await analyse(v); if (ctl.stop) break; record(r, null, performance.now() - t0); } catch (e: any) { setErr(e.message); break; }
        }
        await new Promise((r) => setTimeout(r, Math.max(30, (parseFloat(interval) || 0) * 1000 - (performance.now() - t0))));
      }
      stop();
    } catch (e: any) {
      setErr(e?.name === "NotAllowedError" ? "Camera permission was denied. Allow camera access in the browser, or analyse a recorded video instead."
        : `No camera available (${e?.name ?? "error"}). Connect a camera, or analyse a recorded video instead.`);
    }
  };

  /** Recorded video: step through it. Each analysed frame is held on screen with its own detections, so overlays are frame-accurate. */
  const startFile = async (f: File) => {
    const v = video.current!;
    v.srcObject = null; v.src = URL.createObjectURL(f); v.muted = true;
    try { await new Promise<void>((res, rej) => { v.onloadeddata = () => res(); v.onerror = () => rej(new Error()); }); }
    catch { setErr("This video format cannot be decoded by the browser. Use MP4 (H.264) or WebM, or upload it under New Inspection (server-side decoding)."); return; }
    setSource("file");
    const ctl = begin();
    const step = Math.max(0.05, parseFloat(interval) || 0.5);
    const seek = (t: number) => new Promise<void>((res) => { v.onseeked = () => res(); v.currentTime = t; });
    let from = 0;
    if (mode === "learn") {
      const span = Math.min(parseFloat(learnSeconds) || 5, v.duration * 0.6);
      if (span < 0.4) { setErr("The video is too short to learn a reference from."); setRunning(false); return; }
      try {
        const n = 12, blobs: Blob[] = [];
        for (let i = 0; i < n && !ctl.stop; i++) {
          setPhase(`Reading reference frame ${i + 1} of ${n} from the first ${span.toFixed(1)} s…`);
          await seek((i / n) * span);
          blobs.push(await grab(v));
        }
        if (ctl.stop) return;
        await learn(blobs);
      } catch (e: any) { setErr(e.message); setPhase(null); setRunning(false); return; }
      from = span;
    }
    for (let t = from; t < v.duration && !ctl.stop; t += step) {
      const t0 = performance.now();
      await seek(t);
      try { const r = await analyse(v); if (ctl.stop) break; record(r, t, performance.now() - t0); setProgress(Math.min(1, (t + step) / v.duration)); }
      catch (e: any) { setErr(e.message); break; }
      await new Promise((r) => setTimeout(r, 180)); // keep the annotated frame visible
    }
    loop.current.stop = true;
    setRunning(false);
  };

  if (!can("inspector")) return <><PageHeader title="Live Inspection" /><Notice tone="warn">Your role (viewer) cannot run inspections.</Notice></>;
  const ready = !!material && (mode === "learn" || !prof?.requires_reference);
  const isClear = !!last && last.decision.outcome === "review" && last.findings.length === 0 && last.quality.status !== "fail";
  const o = !last ? null : isClear ? { c: "#9ca3af", t: "CLEAR*" } : last.decision.outcome === "review" ? { c: "#fab219", t: "CHECK" } : OUT[last.decision.outcome];
  const W = last?.image.width ?? 1, H = last?.image.height ?? 1;
  const u = Math.max(W, H) / 640; // overlay unit so text/strokes scale with the frame
  return (
    <>
      <PageHeader title="Live Inspection" sub="Point a camera at the part, or load a recorded video of the material. Each analysed frame is shown with the detected defects drawn on it and a running OK / NG count." />
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_360px]">
        <div className="min-w-0 space-y-4">
          <Card pad={false} title={source === "file" ? "Video analysis" : "Camera feed"} right={running ? <Tag tone="good">● analysing</Tag> : <Tag>{stats.frames ? "finished" : "idle"}</Tag>}>
            <div className="relative bg-black" style={o ? { boxShadow: `inset 0 0 0 3px ${o.c}` } : undefined}>
              <video ref={video} playsInline muted className="mx-auto block max-h-[64vh] w-full object-contain" />
              {last && (
                <svg viewBox={`0 0 ${W} ${H}`} className="pointer-events-none absolute inset-0 h-full w-full" preserveAspectRatio="xMidYMid meet" fontFamily="ui-monospace, Menlo, Consolas, monospace">
                  {last.findings.map((f, i) => {
                    const col = f.severity.level === "minor" ? "#fab219" : "#ef4444";
                    const text = `${(f.type_source === "model" ? f.label : f.defect_type.replace(/_/g, " ")).toUpperCase()} ${(f.confidence * 100).toFixed(0)}%`;
                    const fs = 11 * u, tw = text.length * fs * 0.62 + 6 * u;
                    const ty = f.bbox[1] - 3 * u > fs + 30 * u ? f.bbox[1] - 3 * u : f.bbox[1] + f.bbox[3] + fs + 3 * u;
                    const tx = Math.min(Math.max(0, f.bbox[0]), W - tw);
                    return (
                      <g key={i}>
                        {f.polygon.length >= 3 && <polygon points={f.polygon.map((p) => p.join(",")).join(" ")} fill={col} fillOpacity={0.3} stroke={col} strokeWidth={1.2 * u} />}
                        <rect x={f.bbox[0]} y={f.bbox[1]} width={f.bbox[2]} height={f.bbox[3]} fill="none" stroke={col} strokeWidth={2 * u} />
                        <rect x={tx} y={ty - fs} width={tw} height={fs + 3 * u} fill={col} />
                        <text x={tx + 3 * u} y={ty} fontSize={fs} fontWeight={700} fill="#111">{text}</text>
                      </g>);
                  })}
                  {/* status bar */}
                  <rect x={0} y={0} width={W} height={29 * u} fill="#000" fillOpacity={0.72} />
                  <text x={6 * u} y={12 * u} fontSize={10 * u} fill="#fff" fontWeight={700}>
                    MODE: {(mode === "learn" ? "LEARNED REFERENCE" : profile || "SCREENING").toUpperCase()}   FPS: {stats.fps.toFixed(1)}   LATENCY: {last.processing_ms.toFixed(0)} ms{source === "file" && video.current ? `   T: ${fmtPos(video.current.currentTime)}` : ""}
                  </text>
                  <text x={6 * u} y={24 * u} fontSize={10 * u} fill="#fff" fontWeight={700}>
                    FRAMES: {stats.frames}   OK: {stats.pass}   CLEAR*: {stats.clear}   CHECK: {stats.review}   NG: {stats.defective}   DEFECTS: {stats.defects}
                  </text>
                  <rect x={W - 78 * u} y={4 * u} width={72 * u} height={21 * u} fill={o!.c} rx={2 * u} />
                  <text x={W - 42 * u} y={19 * u} fontSize={13 * u} fontWeight={800} fill="#111" textAnchor="middle">{o!.t}</text>
                </svg>
              )}
              {!last && !running && <div className="absolute inset-0 grid place-items-center px-6 text-center text-sm text-muted">Choose a material on the right, then load a video or start the camera.</div>}
              {phase && <div className="absolute inset-x-0 bottom-0 bg-black/80 px-3 py-2 text-center text-sm text-ink">{phase}</div>}
            </div>
            {progress !== null && <div className="h-1 bg-raised"><div className="h-full bg-accent transition-[width]" style={{ width: `${progress * 100}%` }} /></div>}
            <div className="flex flex-wrap items-center gap-2 border-t border-line p-3">
              {!running ? (
                <>
                  <label className={`btn btn-primary cursor-pointer ${ready ? "" : "pointer-events-none opacity-50"}`}><FileVideo size={14} />Analyse video
                    <input type="file" accept="video/*" className="hidden" onChange={(e) => { const f = e.target.files?.[0]; if (f) startFile(f); e.target.value = ""; }} /></label>
                  <button className="btn" disabled={!ready} onClick={startCamera}><Camera size={14} />Start camera</button>
                  {!ready && <span className="text-xs text-warn">Select a material first.</span>}
                </>
              ) : <button className="btn btn-danger" onClick={stop}><Square size={14} />Stop</button>}
              {last && <span className="ml-auto text-xs text-muted">{last.findings.length} finding(s) in this frame · image quality {last.quality.status}</span>}
            </div>
          </Card>
          {err && <Notice tone="error">{err}</Notice>}
          {mode === "profile" && prof?.requires_reference && <Notice tone="warn">This profile compares each image with a golden reference image and cannot run on a free-running feed. Use New Inspection instead.</Notice>}
          {last && (
            <Card title="Current frame – what was found and why">
              <ul className="space-y-1 text-sm text-ink2">{last.decision.reasons.map((r, i) => <li key={i}>› {r}</li>)}</ul>
              {last.findings.length > 0 && (
                <table className="mt-3 w-full"><thead><tr>{["Defect", "Where", "Confidence", "Severity"].map((h) => <th key={h} className="th">{h}</th>)}</tr></thead>
                  <tbody>{last.findings.slice(0, 8).map((f, i) => (
                    <tr key={i}><td className="td text-ink">{f.label}{f.type_source !== "model" && <span className="ml-1 text-[11px] text-muted">(type not established)</span>}</td>
                      <td className="td">{f.location}</td><td className="td tabular-nums">{(f.confidence * 100).toFixed(0)}%</td><td className="td capitalize">{f.severity.level}</td></tr>))}</tbody></table>)}
            </Card>)}
        </div>
        <div className="space-y-4">
          <Card title="Setup">
            <div className="space-y-3">
              <Field label="How to detect">
                <select className="input" value={mode} disabled={running} onChange={(e) => setMode(e.target.value as "learn" | "profile")}>
                  <option value="learn">Learn normal from this footage (any material)</option>
                  <option value="profile">Use a trained inspection profile</option>
                </select>
              </Field>
              {mode === "learn" ? (
                <>
                  <Field label="Material"><select className="input" value={material} disabled={running} onChange={(e) => setMaterial(e.target.value)}>
                    <option value="">Select material…</option>{mats.data?.map((x) => <option key={x.key} value={x.key}>{x.name}</option>)}</select></Field>
                  <Field label="Defect-free footage at the start (s)" hint="These first seconds must show good material only. They teach the detector what normal looks like; everything after is checked against it.">
                    <input className="input" value={learnSeconds} disabled={running} onChange={(e) => setLearnSeconds(e.target.value.replace(/[^0-9.]/g, ""))} /></Field>
                  <Field label="Sensitivity" hint="High marks subtler deviations but raises more false alarms.">
                    <select className="input" value={sensitivity} disabled={running} onChange={(e) => setSensitivity(e.target.value)}><option value="low">Low</option><option value="normal">Normal</option><option value="high">High</option></select></Field>
                </>
              ) : mats.data && <MaterialProfilePicker materials={mats.data} material={material} profile={profile} onMaterial={setMaterial} onProfile={setProfile} />}
              <div className="grid grid-cols-2 gap-3">
                <Field label="Analyse every (s)" hint="Video: step between frames"><input className="input" value={interval} disabled={running} onChange={(e) => setIntervalS(e.target.value.replace(/[^0-9.]/g, ""))} /></Field>
                <Field label="Batch"><input className="input" value={batch} disabled={running} maxLength={120} onChange={(e) => setBatch(e.target.value)} placeholder="optional" /></Field>
              </div>
              <Field label="Store frames"><select className="input" value={save} disabled={running} onChange={(e) => setSave(e.target.value)}>
                <option value="flagged">Only review / defective frames</option><option value="always">Every frame</option><option value="never">Nothing (preview only)</option></select></Field>
            </div>
          </Card>
          <div className="grid grid-cols-2 gap-3">
            <Stat label="Frames analysed" value={stats.frames} sub={stats.frames ? `${(stats.ms / stats.frames).toFixed(0)} ms avg` : "–"} />
            <Stat label="OK / clear" tone="good" value={stats.pass + stats.clear} sub={`${stats.pass} validated pass · ${stats.clear} no deviation*`} />
            <Stat label="Check (findings)" tone="warn" value={stats.review} />
            <Stat label="NG (defective)" tone="crit" value={stats.defective} />
          </div>
          <Card pad={false} title={`Flagged frames (${events.length})`}>
            {events.length === 0 ? <p className="p-4 text-sm text-muted">None yet.</p> : (
              <ul className="max-h-80 divide-y divide-line overflow-y-auto">{events.map((f, i) => (
                <li key={i} className="flex items-center gap-2 px-3 py-1.5 text-sm">
                  {f.pos !== null ? <button className="tabular-nums text-accent hover:underline" title="Jump to this moment" disabled={running} onClick={() => { if (video.current) video.current.currentTime = f.pos!; setLast(null); }}>{fmtPos(f.pos)}</button> : <span className="tabular-nums text-muted">{f.t}</span>}
                  <OutcomeBadge outcome={f.outcome} /><span className="min-w-0 flex-1 truncate text-ink2">{f.n} · {f.top}</span>
                  {f.id && <Link className="text-xs text-accent hover:underline" href={`/inspections/${f.id}`}>open</Link>}</li>))}</ul>)}
          </Card>
          <p className="text-xs text-muted">* CLEAR means no deviation from the learned reference (or no screening candidate). It is not a validated pass: a detector without measured accuracy cannot certify a part.</p>
          <p className="text-xs text-muted">Counts are per analysed frame, not per part: a part that stays in view for several frames is counted several times.</p>
        </div>
      </div>
    </>
  );
}
