"use client";
import { ArrowLeft, Download, Shuffle, ShieldCheck, Trash2, UploadCloud, Wand2 } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useRef, useState } from "react";
import Annotator from "@/components/Annotator";
import { Card, Empty, Field, Notice, OutcomeBadge, PageHeader, Spinner, Stat, Tag } from "@/components/ui";
import { api, download, effectiveOutcome, fmtDate, type InspectionRow } from "@/lib/api";
import { useApi, useAuth } from "@/lib/auth";

const PAGE = 48;
export default function DatasetPage() {
  const { id } = useParams<{ id: string }>();
  const { can } = useAuth();
  const edit = can("engineer");
  const ds = useApi<any>(`/datasets/${id}`);
  const [f, setF] = useState({ split: "", label: "", defect_type: "" });
  const [page, setPage] = useState(0);
  const imgs = useApi<{ total: number; items: any[] }>(`/datasets/${id}/images`, { ...f, limit: PAGE, offset: page * PAGE });
  const leak = useApi<any>(`/datasets/${id}/leakage`);
  const corrected = useApi<{ items: InspectionRow[] }>(ds.data ? "/inspections" : null, { review_status: "corrected", material: ds.data?.material_key, limit: 8 });
  const [upLabel, setUpLabel] = useState("good");
  const [upGroup, setUpGroup] = useState("");
  const [msg, setMsg] = useState<{ tone: "good" | "warn" | "error" | "info"; text: string } | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [ann, setAnn] = useState<any | null>(null);
  const [modelName, setModelName] = useState("");
  const [job, setJob] = useState<any | null>(null);
  const file = useRef<HTMLInputElement>(null);
  const reload = () => { ds.reload(); imgs.reload(); leak.reload(); };

  const upload = async (files: FileList) => {
    setBusy("upload"); setMsg(null);
    let added = 0, dup = 0, errs = 0;
    const list = Array.from(files);
    for (let i = 0; i < list.length; i += 20) {
      const fd = new FormData();
      list.slice(i, i + 20).forEach((x) => fd.append("files", x));
      fd.append("label", upLabel);
      if (upGroup) fd.append("group_key", upGroup);
      try { const r = await api(`/datasets/${id}/images`, { form: fd }); added += r.added.length; dup += r.skipped_duplicates.length; errs += r.errors.length; }
      catch (e: any) { setMsg({ tone: "error", text: e.message }); break; }
    }
    setBusy(null);
    setMsg((m) => m ?? { tone: dup || errs ? "warn" : "good", text: `${added} added${dup ? `, ${dup} exact duplicates skipped` : ""}${errs ? `, ${errs} unreadable` : ""}. New images are unassigned until you assign splits.` });
    reload();
  };
  const split = async () => { setBusy("split"); try { const r = await api(`/datasets/${id}/split`, { method: "POST" }); setMsg({ tone: r.leakage.clean ? "good" : "warn", text: `Splits assigned over ${r.groups} leakage groups (${r.multi_image_groups} with several images): train ${r.splits.train}, val ${r.splits.val}, test ${r.splits.test}.` }); } catch (e: any) { setMsg({ tone: "error", text: e.message }); } setBusy(null); reload(); };
  const train = async () => {
    setBusy("train"); setJob(null);
    try {
      let j = await api("/models/train", { json: { dataset_id: +id, name: modelName } });
      while (j.status === "queued" || j.status === "running") { setJob(j); await new Promise((r) => setTimeout(r, 1500)); j = await api(`/jobs/${j.id}`); }
      setJob(j);
    } catch (e: any) { setMsg({ tone: "error", text: e.message }); }
    setBusy(null);
  };

  if (ds.error) return <Notice tone="error">{ds.error}</Notice>;
  if (!ds.data) return <Spinner />;
  const d = ds.data;
  const count = (s: string) => { const x = d.splits[s]; return x ? x.good + x.defective + x.unlabeled : 0; };
  const sel = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLSelectElement>) => { setF((c) => ({ ...c, [k]: e.target.value })); setPage(0); };
  return (
    <>
      <PageHeader title={d.name} sub={`${d.material_key} · ${d.description || "no description"} · target split ${Math.round((1 - d.val_fraction - d.test_fraction) * 100)}/${Math.round(d.val_fraction * 100)}/${Math.round(d.test_fraction * 100)}`}
        right={<>
          <Link href="/datasets" className="btn btn-sm"><ArrowLeft size={12} />Datasets</Link>
          {edit && <><button className="btn btn-sm" onClick={() => download(`/datasets/${id}/export`, { format: "coco" })}><Download size={12} />COCO</button>
            <button className="btn btn-sm" onClick={() => download(`/datasets/${id}/export`, { format: "yolo" })}><Download size={12} />YOLO</button></>}
        </>} />
      <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-5">
        <Stat label="Images" value={d.image_count} />
        {["train", "val", "test"].map((s) => <Stat key={s} label={s === "val" ? "Validation" : s === "train" ? "Training" : "Test"} value={count(s)} sub={d.splits[s] ? `${d.splits[s].good} good · ${d.splits[s].defective} defective` : "–"} />)}
        <Stat label="Unassigned" tone={count("unassigned") ? "warn" : undefined} value={count("unassigned")} />
      </div>
      {msg && <div className="mb-4"><Notice tone={msg.tone}>{msg.text}</Notice></div>}
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
        <div className="min-w-0 space-y-4">
          <Card pad={false} title={`Images (${imgs.data?.total ?? "…"})`} right={
            <div className="flex gap-1.5">
              <select aria-label="Split" className="input w-28 py-1 text-xs" value={f.split} onChange={sel("split")}><option value="">All splits</option>{["train", "val", "test", "unassigned"].map((s) => <option key={s}>{s}</option>)}</select>
              <select aria-label="Label" className="input w-28 py-1 text-xs" value={f.label} onChange={sel("label")}><option value="">All labels</option>{["good", "defective", "unlabeled"].map((s) => <option key={s}>{s}</option>)}</select>
              <select aria-label="Defect class" className="input w-32 py-1 text-xs" value={f.defect_type} onChange={sel("defect_type")}><option value="">All classes</option>{d.defect_classes.map((c: any) => <option key={c.type} value={c.type}>{c.type} ({c.annotations})</option>)}</select>
            </div>}>
            {!imgs.data ? <div className="px-4"><Spinner /></div> : imgs.data.items.length === 0 ? <div className="p-4"><Empty>No images match. Upload images on the right.</Empty></div> : (
              <div className="grid grid-cols-3 gap-2 p-3 sm:grid-cols-4 lg:grid-cols-6">{imgs.data.items.map((im) => (
                <button key={im.id} onClick={() => setAnn(im)} className="group relative overflow-hidden rounded border border-line text-left hover:border-accent">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={im.thumb_url} alt={im.filename} loading="lazy" className="aspect-square w-full object-cover" />
                  <span className={`absolute left-1 top-1 rounded-sm px-1 text-[10px] font-medium ${im.label === "good" ? "bg-good/80 text-white" : im.label === "defective" ? "bg-crit/85 text-white" : "bg-black/70 text-ink2"}`}>{im.label === "good" ? "good" : im.label}</span>
                  <span className="absolute right-1 top-1 rounded-sm bg-black/70 px-1 text-[10px] text-ink2">{im.split}</span>
                  {im.annotations.length > 0 && <span className="absolute bottom-1 right-1 rounded-sm bg-accentDim px-1 text-[10px] text-white">{im.annotations.length} ann.</span>}
                </button>))}</div>)}
            <div className="flex items-center justify-between border-t border-line p-3 text-sm text-muted"><span>Click an image to label it, draw boxes or masks.</span>
              <span className="flex gap-2"><button className="btn btn-sm" disabled={page === 0} onClick={() => setPage(page - 1)}>Previous</button><button className="btn btn-sm" disabled={(page + 1) * PAGE >= (imgs.data?.total ?? 0)} onClick={() => setPage(page + 1)}>Next</button></span></div>
          </Card>
          <Card pad={false} title="Incorrect predictions (corrected by inspectors)">
            {!corrected.data?.items.length ? <p className="p-4 text-sm text-muted">No human-corrected inspections for this material yet. When an inspector overturns or corrects an AI result it appears here and can be added as a labelled example.</p> : (
              <ul className="divide-y divide-line">{corrected.data.items.map((i) => (
                <li key={i.id} className="flex items-center gap-3 px-3 py-2 text-sm">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  {i.thumb_url && <img src={i.thumb_url} alt="" className="h-9 w-9 rounded-sm object-cover" />}
                  <span className="text-muted">AI</span><OutcomeBadge outcome={i.outcome} /><span className="text-muted">→ inspector</span><OutcomeBadge outcome={effectiveOutcome(i)} />
                  <span className="hidden text-xs text-muted sm:inline">{fmtDate(i.reviewed_at)}</span>
                  <Link className="ml-auto text-xs text-accent hover:underline" href={`/inspections/${i.id}`}>open</Link>
                  {edit && <button className="btn btn-sm" onClick={async () => { try { await api(`/datasets/${id}/from-inspection`, { json: { inspection_id: i.id } }); setMsg({ tone: "good", text: "Added as a labelled example (unassigned until splits are re-assigned)." }); reload(); } catch (e: any) { setMsg({ tone: e.status === 409 ? "info" : "error", text: e.message }); } }}>Add to dataset</button>}
                </li>))}</ul>)}
          </Card>
        </div>
        <div className="space-y-4">
          {edit && (
            <Card title="Upload labelled images">
              <div className="space-y-3">
                <Field label="Label for this upload"><select className="input" value={upLabel} onChange={(e) => setUpLabel(e.target.value)}><option value="good">Defect-free (good)</option><option value="defective">Defective</option><option value="unlabeled">Unlabeled</option></select></Field>
                <Field label="Leakage group (optional)" hint="Use when all files show the same physical part."><input className="input" value={upGroup} onChange={(e) => setUpGroup(e.target.value)} placeholder="e.g. serial number" /></Field>
                <button className="btn w-full" disabled={busy !== null} onClick={() => file.current?.click()}><UploadCloud size={14} />{busy === "upload" ? "Uploading…" : "Choose images…"}</button>
                <input ref={file} type="file" multiple accept="image/*" className="hidden" onChange={(e) => { if (e.target.files?.length) upload(e.target.files); e.target.value = ""; }} />
              </div>
            </Card>)}
          <Card title="Splits & leakage" right={leak.data && (leak.data.clean ? <Tag tone="good"><ShieldCheck size={11} />no leakage</Tag> : <Tag tone="crit">leakage found</Tag>)}>
            <p className="text-sm text-ink2">Images are grouped by explicit part key and by near-duplicate detection. A whole group always lands in one split, chosen by a deterministic hash.</p>
            {leak.data && <p className="mt-2 text-xs text-muted">Check: {leak.data.method}.</p>}
            {leak.data?.leaking_groups.length > 0 && <div className="mt-2"><Notice tone="error">{leak.data.leaking_groups.length} group(s) span several splits. Re-assign splits to repair.</Notice></div>}
            {leak.data?.unassigned_images > 0 && <div className="mt-2"><Notice tone="warn">{leak.data.unassigned_images} image(s) have no split yet.</Notice></div>}
            {edit && <button className="btn mt-3 w-full" disabled={busy !== null || d.image_count === 0} onClick={split}><Shuffle size={14} />{busy === "split" ? "Assigning…" : "Assign train / val / test splits"}</button>}
          </Card>
          {edit && (
            <Card title="Train anomaly model">
              <p className="text-sm text-ink2">Fits a PatchCore model on the defect-free <b>training</b> images, calibrates it on <b>validation</b>, and reports metrics on the untouched <b>test</b> split.</p>
              <div className="mt-3 flex gap-2"><input aria-label="Model name" className="input" placeholder="model_name (a-z, 0-9, _)" value={modelName} onChange={(e) => setModelName(e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, "_"))} />
                <button className="btn btn-primary shrink-0" disabled={busy !== null || modelName.length < 3} onClick={train}><Wand2 size={14} />Train</button></div>
              {job && (
                <div className="mt-3 text-sm">
                  {(job.status === "running" || job.status === "queued") && <div><div className="mb-1 text-muted">Training… {Math.round(job.progress * 100)}%</div><div className="h-1.5 rounded-sm bg-raised"><div className="h-full rounded-sm bg-accent" style={{ width: `${job.progress * 100}%` }} /></div></div>}
                  {job.status === "failed" && <Notice tone="error">{job.error}</Notice>}
                  {job.status === "done" && <Notice tone="good" title={`${job.result.name} ${job.result.version} created as candidate`}>
                    {job.result.metrics.test ? <>Test AUROC {job.result.metrics.test.auroc}, F1 {job.result.metrics.test.f1} (n={job.result.metrics.test.n}). </> : <>No test metrics could be computed. </>}
                    {job.result.notes.map((n: string) => <div key={n} className="text-xs text-warn">{n}</div>)}
                    <Link className="text-accent underline" href="/models">Review and promote in Model Performance →</Link></Notice>}
                </div>)}
            </Card>)}
          {can("admin") && <button className="btn btn-danger btn-sm" onClick={async () => { if (confirm(`Delete dataset "${d.name}" and all its images? This cannot be undone.`)) { await api(`/datasets/${id}`, { method: "DELETE" }); window.location.href = "/datasets"; } }}><Trash2 size={12} />Delete dataset</button>}
        </div>
      </div>
      {ann && <Annotator datasetId={+id} image={ann} editable={edit} onClose={() => setAnn(null)} onSaved={() => { setAnn(null); reload(); }} />}
    </>
  );
}
