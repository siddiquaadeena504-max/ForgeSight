"use client";
import { FileVideo, ImagePlus, Play, Trash2, UploadCloud } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import InspectionView from "@/components/InspectionView";
import MaterialProfilePicker from "@/components/MaterialProfilePicker";
import { Card, Field, Notice, OutcomeBadge, PageHeader, Tag } from "@/components/ui";
import { api, ApiError, type InspectionDetail, type Material, type Quality } from "@/lib/api";
import { useApi, useAuth } from "@/lib/auth";

interface Item { id: string; file: File; preview: string | null; isVideo: boolean; status: "queued" | "running" | "done" | "error"; result?: InspectionDetail; job?: any; error?: string }
interface Ident { suggestion: { known: boolean; profile_key: string | null; similarity?: number; method: string }; quality: Quality }

const stem = (n: string) => n.replace(/\.[^.]+$/, "").replace(/[_-](test|temp|template|ref|reference|golden|good)$/i, "").toLowerCase();
/** One reference -> used for all; several -> matched by name stem, else by position. */
function pickReference(file: File, index: number, refs: File[]): File | null {
  if (refs.length <= 1) return refs[0] ?? null;
  return refs.find((r) => stem(r.name) === stem(file.name)) ?? refs[index] ?? null;
}

export default function NewInspection() {
  const { can } = useAuth();
  const mats = useApi<Material[]>("/materials");
  const [items, setItems] = useState<Item[]>([]);
  const [material, setMaterial] = useState("");
  const [profile, setProfile] = useState("");
  const [suggested, setSuggested] = useState<string | null>(null);
  const [ident, setIdent] = useState<Ident | null>(null);
  const [identBusy, setIdentBusy] = useState(false);
  const [productId, setProductId] = useState("");
  const [batchId, setBatchId] = useState("");
  const [mmpp, setMmpp] = useState("");
  const [references, setReferences] = useState<File[]>([]);
  const [everySec, setEverySec] = useState("1");
  const [running, setRunning] = useState(false);
  const [active, setActive] = useState<string | null>(null);
  const [drag, setDrag] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const identDone = useRef(false);

  const prof = mats.data?.flatMap((m) => m.profiles).find((p) => p.key === profile);

  const addFiles = useCallback((files: FileList | File[]) => {
    const list = Array.from(files).filter((f) => f.type.startsWith("image/") || f.type.startsWith("video/"));
    setItems((cur) => [...cur, ...list.map((f) => ({ id: crypto.randomUUID(), file: f, isVideo: f.type.startsWith("video/"), preview: f.type.startsWith("image/") ? URL.createObjectURL(f) : null, status: "queued" as const }))]);
  }, []);

  // Workflow steps 1-3: identify material / analyse quality on the first image
  useEffect(() => {
    const first = items.find((i) => !i.isVideo);
    if (!first || identDone.current || !mats.data) return;
    identDone.current = true;
    setIdentBusy(true);
    const fd = new FormData();
    fd.append("file", first.file);
    api<Ident>("/inspections/identify", { form: fd }).then((r) => {
      setIdent(r);
      if (r.suggestion.known && r.suggestion.profile_key) {
        const m = mats.data!.find((x) => x.profiles.some((p) => p.key === r.suggestion.profile_key));
        if (m) { setMaterial((cur) => cur || m.key); setProfile((cur) => cur || r.suggestion.profile_key!); setSuggested(m.key); }
      }
    }).catch(() => {}).finally(() => setIdentBusy(false));
  }, [items, mats.data]);

  const update = (id: string, patch: Partial<Item>) => setItems((cur) => cur.map((i) => (i.id === id ? { ...i, ...patch } : i)));

  const pollJob = async (id: string, jobId: string) => {
    for (;;) {
      const job = await api(`/jobs/${jobId}`);
      update(id, { job });
      if (job.status === "done") return update(id, { status: "done" });
      if (job.status === "failed") return update(id, { status: "error", error: job.error });
      await new Promise((r) => setTimeout(r, 1200));
    }
  };

  const run = async () => {
    setRunning(true);
    const queue = items.filter((i) => i.status === "queued" || i.status === "error");
    let firstDone: string | null = null;
    const worker = async (it: Item) => {
      update(it.id, { status: "running", error: undefined });
      const fd = new FormData();
      fd.append("file", it.file);
      if (material) fd.append("material_key", material);
      if (profile) fd.append("profile_key", profile);
      if (batchId) fd.append("batch_id", batchId);
      if (productId) fd.append("product_id", items.length > 1 && !it.isVideo ? `${productId}-${items.indexOf(it) + 1}` : productId);
      try {
        if (it.isVideo) {
          fd.append("every_seconds", everySec || "1");
          const job = await api("/inspections/video", { form: fd });
          update(it.id, { job });
          await pollJob(it.id, job.id);
        } else {
          if (mmpp) fd.append("mm_per_pixel", mmpp);
          const ref = pickReference(it.file, items.filter((x) => !x.isVideo).indexOf(it), references);
          if (ref) fd.append("reference", ref);
          if (suggested && material && material !== suggested) fd.append("material_overridden", "true");
          else if (suggested && material === suggested && profile === ident?.suggestion.profile_key) fd.append("material_from_suggestion", "true");
          const res = await api<InspectionDetail>("/inspections", { form: fd });
          update(it.id, { status: "done", result: res });
          if (!firstDone) { firstDone = it.id; setActive(it.id); }
        }
      } catch (e) {
        const err = e as ApiError;
        update(it.id, { status: "error", error: err.message });
      }
    };
    // two at a time keeps the UI responsive without flooding the API
    const pending = [...queue];
    await Promise.all([0, 1].map(async () => { while (pending.length) await worker(pending.shift()!); }));
    setRunning(false);
  };

  const activeItem = items.find((i) => i.id === active && i.result);
  const queued = items.filter((i) => i.status === "queued" || i.status === "error").length;
  const hasVideo = items.some((i) => i.isVideo);
  const needMaterial = !material && !profile;

  if (!can("inspector")) return <><PageHeader title="New Inspection" /><Notice tone="warn">Your role (viewer) cannot run inspections.</Notice></>;

  return (
    <>
      <PageHeader title="New Inspection" sub="Upload part images or a video. The engine checks image quality, runs the detectors of the selected profile and returns pass, defective, or a request for human review." />
      <div className="grid gap-4 lg:grid-cols-[360px_minmax(0,1fr)]">
        <div className="space-y-4">
          <Card title="1 · Images">
            <div onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)}
              onDrop={(e) => { e.preventDefault(); setDrag(false); addFiles(e.dataTransfer.files); }}
              onClick={() => input.current?.click()} role="button" tabIndex={0} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") input.current?.click(); }}
              className={`flex cursor-pointer flex-col items-center gap-2 rounded border border-dashed px-4 py-7 text-center text-sm ${drag ? "border-accent bg-accent/10" : "border-lineStrong hover:border-accent/60"}`}>
              <UploadCloud size={26} className="text-muted" aria-hidden />
              <div className="text-ink2">Drag &amp; drop images or video here, or click to browse</div>
              <div className="text-xs text-muted">JPEG, PNG, BMP, TIFF, WebP · MP4/AVI/MOV video · multiple files allowed</div>
              <div className="text-xs text-muted">To watch a video with detections drawn on it, use <Link href="/live" className="text-accent underline" onClick={(e) => e.stopPropagation()}>Live Inspection → Analyse video</Link>.</div>
              <input ref={input} type="file" multiple accept="image/*,video/*" className="hidden" onChange={(e) => { if (e.target.files) addFiles(e.target.files); e.target.value = ""; }} />
            </div>
            {items.length > 0 && (
              <ul className="mt-3 max-h-72 space-y-1 overflow-y-auto">{items.map((it) => (
                <li key={it.id} className={`flex items-center gap-2 rounded border px-2 py-1.5 text-sm ${active === it.id ? "border-accent bg-raised" : "border-line"}`}>
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  {it.preview ? <img src={it.preview} alt="" className="h-9 w-9 rounded-sm object-cover" /> : <FileVideo size={20} className="mx-2 text-muted" aria-hidden />}
                  <div className="min-w-0 flex-1">
                    <button type="button" disabled={!it.result} onClick={() => setActive(it.id)} className="block w-full truncate text-left text-ink2 enabled:hover:text-ink">{it.file.name}</button>
                    <div className="text-xs text-muted">
                      {it.status === "queued" && "Ready"}{it.status === "running" && (it.job ? `Processing video… ${Math.round((it.job.progress ?? 0) * 100)}% (${it.job.result?.frames_inspected ?? 0} frames)` : "Inspecting…")}
                      {it.status === "error" && <span className="text-[#f08a8a]">{it.error}</span>}
                      {it.status === "done" && it.result && `${it.result.defect_count} finding(s) · ${it.result.processing_ms?.toFixed(0)} ms`}
                      {it.status === "done" && it.job && <>{it.job.result.frames_inspected} frames: {Object.entries(it.job.result.outcomes).map(([k, v]) => `${v} ${k}`).join(", ")} · <Link className="text-accent underline" href={`/history?job_id=${it.job.id}`}>view frames</Link></>}
                    </div>
                  </div>
                  {it.result && <OutcomeBadge outcome={it.result.outcome} />}
                  {it.status !== "running" && <button type="button" aria-label={`Remove ${it.file.name}`} className="p-1 text-muted hover:text-ink" onClick={() => setItems((c) => c.filter((x) => x.id !== it.id))}><Trash2 size={14} /></button>}
                </li>))}</ul>
            )}
          </Card>

          <Card title="2 · Material & profile">
            <div className="space-y-3">
              {identBusy && <p className="text-xs text-muted">Analysing first image…</p>}
              {ident && (ident.suggestion.known ? (
                <Notice tone="info" title="Material suggestion">Looks like profile <b>{ident.suggestion.profile_key}</b> (similarity {((ident.suggestion.similarity ?? 0) * 100).toFixed(0)}%). Pre-selected below. Change it if wrong; your choice always overrides the suggestion.</Notice>
              ) : (
                <Notice tone="warn" title="Material not recognised">The image does not match any profile the identifier knows, so no guess is made. Please select the material.</Notice>
              ))}
              {mats.data && <MaterialProfilePicker materials={mats.data} material={material} profile={profile} onMaterial={setMaterial} onProfile={setProfile} />}
              {suggested && material && material !== suggested && <Tag tone="accent">operator override of AI suggestion</Tag>}
              {prof?.requires_reference && (
                <Field label="Golden reference image(s) (defect-free template)" hint="One reference is applied to every image. Several are paired by file name (part_test ↔ part_temp / _ref / _golden), otherwise in order.">
                  <label className="btn btn-sm w-full cursor-pointer justify-start"><ImagePlus size={13} />{references.length ? (references.length === 1 ? references[0].name : `${references.length} reference images`) : "Choose reference image(s)…"}
                    <input type="file" accept="image/*" multiple className="hidden" onChange={(e) => setReferences(Array.from(e.target.files ?? []))} /></label>
                </Field>
              )}
              {ident && (
                <div className="rounded border border-line p-2.5">
                  <div className="mb-1 flex items-center justify-between text-xs"><span className="font-medium uppercase tracking-wider text-muted">Image quality (first image)</span>
                    <Tag tone={ident.quality.status === "ok" ? "good" : ident.quality.status === "warn" ? "warn" : "crit"}>{ident.quality.status}</Tag></div>
                  <ul className="space-y-0.5 text-xs text-muted">{ident.quality.checks.filter((c) => c.status !== "ok").map((c) => <li key={c.name}><span className={c.status === "warn" ? "text-warn" : "text-crit"}>●</span> {c.name.replace(/_/g, " ")}: {c.message}</li>)}
                    {ident.quality.checks.every((c) => c.status === "ok") && <li>All checks passed ({ident.quality.width}×{ident.quality.height}px).</li>}</ul>
                </div>
              )}
            </div>
          </Card>

          <Card title="3 · Part details">
            <div className="grid grid-cols-2 gap-3">
              <Field label="Product / serial ID"><input className="input" value={productId} maxLength={100} onChange={(e) => setProductId(e.target.value)} placeholder="optional" /></Field>
              <Field label="Production batch"><input className="input" value={batchId} maxLength={120} onChange={(e) => setBatchId(e.target.value)} placeholder="optional" /></Field>
              <Field label="Scale (mm per pixel)" hint={prof?.mm_per_pixel ? `Profile default ${prof.mm_per_pixel}` : "Leave empty if not calibrated"}>
                <input className="input" inputMode="decimal" value={mmpp} onChange={(e) => setMmpp(e.target.value.replace(/[^0-9.]/g, ""))} placeholder="e.g. 0.05" /></Field>
              {hasVideo && <Field label="Video: sample every (s)"><input className="input" inputMode="decimal" value={everySec} onChange={(e) => setEverySec(e.target.value.replace(/[^0-9.]/g, ""))} /></Field>}
            </div>
            <button className="btn btn-primary mt-4 w-full" disabled={running || queued === 0 || needMaterial || (!!prof?.requires_reference && references.length === 0 && items.some((i) => !i.isVideo))} onClick={run}>
              <Play size={14} />{running ? "Inspecting…" : `Run inspection${queued > 1 ? ` (${queued} files)` : ""}`}</button>
            {needMaterial && items.length > 0 && <p className="mt-2 text-xs text-warn">Select a material to continue.</p>}
          </Card>
        </div>

        <div className="min-w-0">
          {activeItem?.result ? (
            <InspectionView stacked data={activeItem.result} onChange={(d) => update(activeItem.id, { result: d })} />
          ) : (
            <div className="card grid h-full min-h-[420px] place-items-center p-8 text-center">
              <div className="max-w-md text-sm text-muted">
                <UploadCloud size={32} className="mx-auto mb-3" aria-hidden />
                Results appear here: annotated image with zoom/pan, heatmap, masks and bounding boxes, a findings table, the decision basis and the human-review form.
              </div>
            </div>
          )}
        </div>
      </div>
    </>
  );
}
