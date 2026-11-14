"use client";
import { Download, FlaskConical, Eye } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api, download, effectiveOutcome, fmtDate, pct, type Finding, type InspectionDetail } from "@/lib/api";
import { useApi, useAuth } from "@/lib/auth";
import ImageViewer, { SEV_COLOR, type Layers } from "./ImageViewer";
import { Card, Meter, Notice, OutcomeBadge, SeverityBadge, Tag, Toggle } from "./ui";

const BASIS: Record<string, string> = { model_probability: "model score", anomaly_strength: "anomaly strength", screening_heuristic: "uncalibrated screening", human: "inspector" };
type Verdict = { qc_status: "confirmed" | "rejected" | "corrected"; human_type?: string };

export default function InspectionView({ data, onChange, stacked = false }: { data: InspectionDetail; onChange: (d: InspectionDetail) => void; stacked?: boolean }) {
  const { can } = useAuth();
  const s = data.summary;
  const dec = s.decision;
  const [layers, setLayers] = useState<Layers>({ boxes: true, masks: true, heatmap: false, markers: true });
  const [compare, setCompare] = useState(false);
  const [sel, setSel] = useState<number | null>(data.defects[0]?.idx ?? null);
  const selected = data.defects.find((d) => d.idx === sel) ?? null;
  const eff = effectiveOutcome(data);
  const set = (k: keyof Layers) => (v: boolean) => setLayers((l) => ({ ...l, [k]: v }));
  useEffect(() => { setSel(data.defects[0]?.idx ?? null); }, [data.id]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className={stacked ? "grid gap-4 min-[1800px]:grid-cols-[minmax(0,1fr)_420px]" : "grid gap-4 xl:grid-cols-[minmax(0,1fr)_420px]"}>
      <div className="min-w-0 space-y-4">
        <Card pad={false} title={<span className="flex items-center gap-2 whitespace-nowrap"><Eye size={14} aria-hidden />Inspection image</span>}
          right={<div className="flex flex-wrap items-center gap-1.5">
            <Toggle label="Boxes" checked={layers.boxes} onChange={set("boxes")} />
            <Toggle label="Masks" checked={layers.masks} onChange={set("masks")} />
            <Toggle label="Markers" checked={layers.markers} onChange={set("markers")} />
            {data.heatmap_url && <Toggle label="Heatmap" checked={layers.heatmap} onChange={set("heatmap")} />}
            <Toggle label={data.reference_url ? "Compare with reference" : "Before / after"} checked={compare} onChange={setCompare} />
          </div>}>
          <ImageViewer className="h-[min(62vh,640px)] rounded-none border-0" src={data.image_url} width={s.image.width} height={s.image.height} heatmapUrl={data.heatmap_url}
            findings={data.defects} layers={layers} selected={sel} onSelect={setSel}
            compareSrc={compare ? data.reference_url ?? data.image_url : null} compareLabel={data.reference_url ? "Golden reference" : "Original"} />
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-line px-3 py-2 text-xs text-muted">
            <span>Scroll to zoom · drag to pan · click a finding to select</span>
            <span className="ml-auto flex items-center gap-3">
              {(["minor", "major", "critical"] as const).map((l) => <span key={l} className="flex items-center gap-1 capitalize"><i className="inline-block h-2 w-2 rounded-sm" style={{ background: SEV_COLOR[l] }} />{l}</span>)}
            </span>
          </div>
        </Card>
        <FindingsTable data={data} sel={sel} setSel={setSel} />
        {can("inspector") && <ReviewPanel key={data.id + (data.reviewed_at ?? "")} data={data} onChange={onChange} />}
      </div>

      <div className={stacked ? "grid content-start gap-4 lg:grid-cols-2 min-[1800px]:grid-cols-1" : "space-y-4"}>
        <Card title="Quality-control status" right={<OutcomeBadge outcome={eff} size="lg" />}>
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5 text-sm">
            <dt className="text-muted">AI outcome</dt><dd><OutcomeBadge outcome={data.outcome} /></dd>
            <dt className="text-muted">Human review</dt>
            <dd className="text-ink2">{data.review_status === "pending" ? "Pending" : data.review_status ? `${data.review_status} by ${data.reviewed_by} · ${fmtDate(data.reviewed_at)}` : "Not required"}</dd>
            <dt className="text-muted">Decision rule</dt>
            <dd>{dec.validated ? <Tag tone="good" title={dec.evidence ?? ""}>validated on held-out data</Tag> : <Tag tone="warn">not validated – screening only</Tag>}</dd>
          </dl>
          {dec.p_defect !== null && (
            <div className="mt-3">
              <div className="mb-1 flex justify-between text-xs text-muted"><span>Calibrated defect probability</span><span className="tabular-nums text-ink">{pct(dec.p_defect)}</span></div>
              <Meter value={dec.p_defect} tLow={dec.thresholds.t_low} tHigh={dec.thresholds.t_high} />
              <div className="mt-1 flex justify-between text-[10px] text-muted"><span>pass ≤ {pct(dec.thresholds.t_low, 1)}</span><span>review band</span><span>reject ≥ {pct(dec.thresholds.t_high, 1)}</span></div>
              {Object.keys(dec.per_detector_probability).length > 0 && (
                <div className="mt-2 text-xs text-muted">Per detector: {Object.entries(dec.per_detector_probability).map(([k, v]) => `${k} ${pct(v, 0)}`).join(" · ")}</div>
              )}
            </div>
          )}
          <ul className="mt-3 space-y-1 border-t border-line pt-3 text-sm text-ink2">{dec.reasons.map((r, i) => <li key={i} className="flex gap-2"><span className="text-muted">›</span>{r}</li>)}</ul>
          <div className="mt-3 flex flex-wrap gap-2">
            <button className="btn btn-sm" onClick={() => download(`/reports/inspections/${data.id}.pdf`)}><Download size={12} />PDF report</button>
            <button className="btn btn-sm" onClick={() => download(`/reports/inspections/${data.id}.csv`)}><Download size={12} />CSV</button>
            {can("engineer") && data.review_status && data.review_status !== "pending" && <AddToDataset inspection={data} />}
          </div>
        </Card>

        {selected ? <FindingDetail f={selected} material={data.material_key} /> : <Card title="Finding detail"><p className="text-sm text-muted">{data.defects.length ? "Select a finding in the image or table." : "No irregularities were localized."}</p></Card>}

        <Card title="Part & image">
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5 text-sm">
            <dt className="text-muted">Product ID</dt><dd className="text-ink2">{data.product_id ?? "–"}</dd>
            <dt className="text-muted">Batch</dt><dd className="text-ink2">{data.batch_id ?? "–"}</dd>
            <dt className="text-muted">Material</dt>
            <dd className="text-ink2">{data.material_key} <Tag tone={data.material_source === "suggested" ? "accent" : "neutral"}>{data.material_source === "suggested" ? "AI-suggested" : data.material_source === "override" ? "operator override" : "operator-selected"}</Tag></dd>
            <dt className="text-muted">Profile</dt><dd className="text-ink2">{s.profile_name ?? "Generic screening"}</dd>
            <dt className="text-muted">Inspected</dt><dd className="text-ink2">{fmtDate(data.created_at)} · {data.created_by ?? "–"}</dd>
            <dt className="text-muted">Source</dt><dd className="text-ink2">{data.source}{data.frame_index !== null ? ` · frame ${data.frame_index}` : ""} · {s.processing_ms.toFixed(0)} ms</dd>
            <dt className="text-muted">Scale</dt><dd className="text-ink2">{s.mm_per_pixel ? `${s.mm_per_pixel} mm/px (calibrated)` : "Not calibrated – sizes in pixels only"}</dd>
          </dl>
          <div className="mt-3 border-t border-line pt-3">
            <div className="mb-1.5 flex items-center justify-between text-xs"><span className="font-medium uppercase tracking-wider text-muted">Image quality gate</span>
              <Tag tone={s.quality.status === "ok" ? "good" : s.quality.status === "warn" ? "warn" : "crit"}>{s.quality.status}</Tag></div>
            <ul className="space-y-1 text-xs">{s.quality.checks.map((c) => (
              <li key={c.name} className="flex items-baseline gap-2"><span className={c.status === "ok" ? "text-good" : c.status === "warn" ? "text-warn" : "text-crit"}>●</span>
                <span className="w-32 shrink-0 text-ink2">{c.name.replace(/_/g, " ")}</span><span className="text-muted">{c.message}</span></li>))}</ul>
          </div>
          <div className="mt-3 border-t border-line pt-3">
            <div className="mb-1.5 text-xs font-medium uppercase tracking-wider text-muted">Detectors run</div>
            <table className="w-full text-xs"><tbody>{s.detectors.map((d) => (
              <tr key={d.name}><td className="py-0.5 text-ink2">{d.name}{d.model_version ? ` ${d.model_version}` : ""}</td><td className="text-muted">{d.kind}</td>
                <td>{d.validated ? <Tag tone="good">validated</Tag> : <Tag tone="warn">unvalidated</Tag>}</td>
                <td className="text-right tabular-nums text-muted">{d.note ? "skipped" : `${d.regions} regions · ${d.latency_ms.toFixed(0)} ms`}</td></tr>))}</tbody></table>
            {s.errors.length > 0 && <div className="mt-2"><Notice tone="error">{s.errors.join("; ")}</Notice></div>}
          </div>
        </Card>
      </div>
    </div>
  );
}

function FindingsTable({ data, sel, setSel }: { data: InspectionDetail; sel: number | null; setSel: (i: number) => void }) {
  return (
    <Card pad={false} title={`Findings (${data.defects.length})`}>
      {data.defects.length === 0 ? <p className="p-4 text-sm text-muted">No irregularities were localized by this profile&apos;s detectors.</p> : (
        <div className="overflow-x-auto"><table className="w-full">
          <thead><tr>{["#", "Defect", "Category", "Location", "Size", "Confidence", "Severity", "QC"].map((h) => <th key={h} className="th">{h}</th>)}</tr></thead>
          <tbody>{data.defects.map((f) => (
            <tr key={f.id} onClick={() => setSel(f.idx)} className={`cursor-pointer hover:bg-raised/60 ${sel === f.idx ? "bg-raised" : ""}`}>
              <td className="td tabular-nums">{f.idx}</td>
              <td className="td"><span className="text-ink">{f.human_type ? `${f.human_type} (inspector)` : f.label}</span>{f.type_source === "heuristic" && <div className="text-[11px] text-muted">shape heuristic – type not established</div>}</td>
              <td className="td capitalize">{f.category}</td><td className="td">{f.location}</td>
              <td className="td whitespace-nowrap tabular-nums">{f.dimensions.calibrated ? `${f.dimensions.length_mm} × ${f.dimensions.width_mm} mm` : `${f.dimensions.length_px.toFixed(0)} × ${f.dimensions.width_px.toFixed(0)} px`}</td>
              <td className="td whitespace-nowrap tabular-nums">{pct(f.confidence, 0)} <span className="text-[11px] text-muted">{BASIS[f.confidence_basis] ?? f.confidence_basis}</span></td>
              <td className="td"><SeverityBadge level={f.severity.level} /></td>
              <td className="td"><Tag tone={f.qc_status === "confirmed" ? "good" : f.qc_status === "rejected" ? "neutral" : f.qc_status === "corrected" ? "accent" : "warn"}>{f.qc_status}</Tag></td>
            </tr>))}</tbody>
        </table></div>
      )}
    </Card>
  );
}

function FindingDetail({ f, material }: { f: Finding; material: string }) {
  const d = f.dimensions;
  return (
    <Card title={<span>Finding #{f.idx} · {f.label}</span>} right={<SeverityBadge level={f.severity.level} />}>
      <div className="mb-1 flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wider text-muted"><Eye size={12} aria-hidden />Observed in the image</div>
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
        <dt className="text-muted">Classification</dt>
        <dd className="text-ink2">{f.type_source === "model" ? <>{f.label} <span className="text-muted">({pct(f.type_confidence, 0)} class score)</span></> : f.type_source === "human" ? `${f.label} (marked by inspector)` : <>Not classified by a trained model. Shape suggests: <i>{f.label}</i></>}</dd>
        <dt className="text-muted">Category</dt><dd className="capitalize text-ink2">{f.category}</dd>
        <dt className="text-muted">Material</dt><dd className="text-ink2">{material}</dd>
        <dt className="text-muted">Location</dt><dd className="text-ink2">{f.location} · bbox x{f.bbox[0]} y{f.bbox[1]} w{f.bbox[2]} h{f.bbox[3]} px</dd>
        <dt className="text-muted">Dimensions</dt>
        <dd className="text-ink2">{d.calibrated ? `${d.length_mm} × ${d.width_mm} mm · ${d.area_mm2} mm²` : `${d.length_px.toFixed(0)} × ${d.width_px.toFixed(0)} px · ${d.area_px} px² (no scale calibration)`}</dd>
        <dt className="text-muted">Confidence</dt><dd className="text-ink2">{pct(f.confidence, 1)} <span className="text-muted">({BASIS[f.confidence_basis]})</span></dd>
        <dt className="text-muted">Detected by</dt><dd className="text-ink2">{f.sources.join(" + ")}{f.agreement > 1 && <Tag tone="good"> {f.agreement} detectors agree</Tag>}</dd>
        <dt className="text-muted">Severity</dt><dd className="text-ink2">{f.severity.rationale}</dd>
      </dl>
      {f.class_probs && (
        <div className="mt-2 flex flex-wrap gap-1">{Object.entries(f.class_probs).filter(([, v]) => v >= 0.01).sort((a, b) => b[1] - a[1]).map(([k, v]) => <Tag key={k}>{k} {pct(v, 0)}</Tag>)}</div>
      )}
      <div className="mt-4 rounded border border-dashed border-lineStrong bg-bg/50 p-3">
        <div className="mb-1 flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wider text-[#8bb9f2]"><FlaskConical size={12} aria-hidden />Hypotheses – not observed</div>
        {f.cause_hypotheses.length ? (
          <>
            <p className="mb-1.5 text-xs text-muted">Possible manufacturing causes from the knowledge base for this defect type and material. Verify at the process before acting.</p>
            <ul className="list-disc space-y-0.5 pl-5 text-sm text-ink2">{f.cause_hypotheses.map((c) => <li key={c}>{c}</li>)}</ul>
          </>
        ) : <p className="text-sm text-muted">No cause is suggested because the defect type has not been established by a trained classifier or an inspector.</p>}
      </div>
      <div className="mt-3 text-sm"><span className="text-muted">Recommended action: </span><span className="text-ink2">{f.recommended_action}</span></div>
    </Card>
  );
}

function ReviewPanel({ data, onChange }: { data: InspectionDetail; onChange: (d: InspectionDetail) => void }) {
  const tax = useApi<{ type: string; label: string }[]>("/taxonomy");
  const [verdicts, setVerdicts] = useState<Record<number, Verdict>>(() => Object.fromEntries(data.defects.filter((d) => d.qc_status !== "open").map((d) => [d.id, { qc_status: d.qc_status as Verdict["qc_status"], human_type: d.human_type ?? undefined }])));
  const [final, setFinal] = useState<"pass" | "defective" | "">(data.review_status && data.review_status !== "pending" ? (data.final_outcome as any) ?? "" : "");
  const [notes, setNotes] = useState(data.review_notes ?? "");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const types = useMemo(() => (tax.data ?? []).filter((t) => !["anomaly", "linear_mark", "dark_spot", "bright_spot", "blotch"].includes(t.type)), [tax.data]);
  const ai = data.defects.filter((d) => d.type_source !== "human");
  const done = data.review_status === "confirmed" || data.review_status === "corrected";
  const submit = async () => {
    if (!final) return;
    setBusy(true); setErr(null);
    try {
      const r = await api<InspectionDetail>(`/inspections/${data.id}/review`, { json: { final_outcome: final, notes: notes || null,
        defects: Object.entries(verdicts).map(([id, v]) => ({ id: +id, qc_status: v.qc_status, human_type: v.qc_status === "corrected" ? v.human_type : null })) } });
      onChange(r);
    } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  };
  return (
    <Card title="Human review" right={done ? <Tag tone="good">reviewed</Tag> : data.review_status === "pending" ? <Tag tone="warn">awaiting review</Tag> : <Tag>optional audit</Tag>}>
      {ai.length > 0 && (
        <div className="mb-3 space-y-1.5">{ai.map((d) => {
          const v = verdicts[d.id];
          const setV = (nv: Verdict) => setVerdicts((m) => ({ ...m, [d.id]: nv }));
          return (
            <div key={d.id} className="flex flex-wrap items-center gap-2 text-sm">
              <span className="w-44 truncate text-ink2">#{d.idx} {d.label}</span>
              {(["confirmed", "rejected", "corrected"] as const).map((q) => (
                <button key={q} type="button" onClick={() => setV({ qc_status: q, human_type: v?.human_type })}
                  className={`chip cursor-pointer ${v?.qc_status === q ? "border-accent bg-accent/20 text-ink" : "border-line text-muted hover:text-ink2"}`}>
                  {q === "confirmed" ? "Real defect" : q === "rejected" ? "False alarm" : "Wrong type"}</button>))}
              {v?.qc_status === "corrected" && (
                <select aria-label={`Correct type for finding ${d.idx}`} className="input w-48 py-1 text-xs" value={v.human_type ?? ""} onChange={(e) => setV({ qc_status: "corrected", human_type: e.target.value })}>
                  <option value="">Select actual type…</option>{types.map((t) => <option key={t.type} value={t.type}>{t.label}</option>)}</select>)}
            </div>);
        })}</div>
      )}
      <div className="flex flex-wrap items-end gap-3">
        <div><span className="label">Final disposition</span>
          <div className="flex gap-1.5">{(["pass", "defective"] as const).map((o) => (
            <button key={o} type="button" onClick={() => setFinal(o)} className={`btn btn-sm ${final === o ? (o === "pass" ? "border-good bg-good/20" : "border-crit bg-crit/25") : ""}`}>{o === "pass" ? "Accept part" : "Reject part"}</button>))}</div></div>
        <label className="min-w-[200px] flex-1"><span className="label">Notes</span><input className="input" value={notes} maxLength={4000} onChange={(e) => setNotes(e.target.value)} placeholder="Optional" /></label>
        <button className="btn btn-primary" disabled={!final || busy || Object.values(verdicts).some((v) => v.qc_status === "corrected" && !v.human_type)} onClick={submit}>{busy ? "Saving…" : done ? "Update review" : "Submit review"}</button>
      </div>
      {err && <div className="mt-3"><Notice tone="error">{err}</Notice></div>}
      <p className="mt-2 text-xs text-muted">The AI outcome is kept for audit; your disposition becomes the final result and can feed the training datasets.</p>
    </Card>
  );
}

function AddToDataset({ inspection }: { inspection: InspectionDetail }) {
  const ds = useApi<{ id: number; name: string }[]>("/datasets", { material: inspection.material_key });
  const [msg, setMsg] = useState<string | null>(null);
  if (!ds.data?.length) return <span className="self-center text-xs text-muted">No dataset for this material yet</span>;
  return (
    <span className="flex items-center gap-1.5">
      <select aria-label="Add to dataset" className="input w-44 py-1 text-xs" defaultValue="" onChange={async (e) => {
        const id = e.target.value; if (!id) return;
        try { await api(`/datasets/${id}/from-inspection`, { json: { inspection_id: inspection.id } }); setMsg("Added"); } catch (ex: any) { setMsg(ex.message); }
        e.target.value = "";
      }}><option value="">Add to dataset…</option>{ds.data.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}</select>
      {msg && <span className="text-xs text-muted">{msg}</span>}
    </span>
  );
}
