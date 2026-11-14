"use client";
import { Plus } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { Card, Field, Notice, PageHeader, Spinner, Tag } from "@/components/ui";
import { api, pct, type Material, type Profile } from "@/lib/api";
import { useApi, useAuth } from "@/lib/auth";

export default function Materials() {
  const { can } = useAuth();
  const mats = useApi<Material[]>("/materials");
  const [open, setOpen] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const validated = mats.data?.filter((m) => m.coverage === "validated").length ?? 0;
  return (
    <>
      <PageHeader title="Material Library" sub="Each material is inspected through profiles: a set of detectors plus a decision rule. No single model covers every material; a material without a validated profile is screened only and always goes to human review."
        right={can("engineer") && <button className="btn btn-sm" onClick={() => setAdding(!adding)}><Plus size={12} />Custom material</button>} />
      {adding && <NewMaterial onDone={() => { setAdding(false); mats.reload(); }} />}
      {!mats.data ? <Spinner /> : (
        <>
          <div className="mb-4"><Notice tone="info">{validated} of {mats.data.length} materials have at least one profile validated on held-out data. The others use the training-free screening detector until you collect data and fit a model (Dataset Management → Train).</Notice></div>
          <div className="grid gap-4 md:grid-cols-2 2xl:grid-cols-3">
            {mats.data.map((m) => (
              <Card key={m.key} title={m.name} right={m.coverage === "validated" ? <Tag tone="good">validated profile</Tag> : <Tag tone="warn">screening only</Tag>}>
                <p className="text-sm text-ink2">{m.description}</p>
                <div className="mt-3 flex flex-wrap gap-1">{m.common_defects.map((d) => <Tag key={d.type}>{d.label}</Tag>)}</div>
                {m.imaging_notes && <p className="mt-3 text-xs text-muted"><b className="font-medium text-ink2">Imaging:</b> {m.imaging_notes}</p>}
                <div className="mt-3 border-t border-line pt-3">
                  <div className="mb-1.5 text-[11px] font-medium uppercase tracking-wider text-muted">Inspection profiles</div>
                  <ul className="space-y-1.5 text-sm">
                    {m.profiles.map((p) => (
                      <li key={p.key}>
                        <button className="flex w-full items-center gap-2 text-left hover:text-ink" onClick={() => setOpen(open === p.key ? null : p.key)}>
                          <span className="min-w-0 flex-1 truncate text-ink2">{p.name}</span>
                          {p.validated ? <Tag tone="good">validated</Tag> : <Tag tone="warn">unvalidated</Tag>}
                        </button>
                        {open === p.key && <ProfileEditor p={p} editable={can("engineer")} onSaved={mats.reload} />}
                      </li>))}
                    <li className="flex items-center gap-2 text-muted"><span className="flex-1">Generic surface screening</span><Tag>built-in</Tag></li>
                  </ul>
                </div>
                <div className="mt-3 flex gap-4 border-t border-line pt-2.5 text-xs text-muted">
                  <Link className="hover:text-ink" href={`/history?material=${m.key}`}>{m.inspections} inspections</Link><span>{m.datasets} datasets</span><span>{m.production_models} production models</span>
                </div>
              </Card>))}
          </div>
        </>
      )}
    </>
  );
}

function ProfileEditor({ p, editable, onSaved }: { p: Profile; editable: boolean; onSaved: () => void }) {
  const d = p.decision ?? {};
  const [mm, setMm] = useState(p.mm_per_pixel?.toString() ?? "");
  const [tl, setTl] = useState(d.t_low?.toString() ?? "");
  const [th, setTh] = useState(d.t_high?.toString() ?? "");
  const [msg, setMsg] = useState<{ tone: "good" | "error"; text: string } | null>(null);
  const save = async () => {
    try {
      const body: any = {};
      if (mm) body.mm_per_pixel = +mm; else if (p.mm_per_pixel) body.clear_calibration = true;
      if (d.mode === "fusion") { body.t_low = +tl; body.t_high = +th; }
      await api(`/profiles/${p.key}`, { method: "PATCH", json: body });
      setMsg({ tone: "good", text: "Saved" }); onSaved();
    } catch (e: any) { setMsg({ tone: "error", text: e.message }); }
  };
  return (
    <div className="mt-2 rounded border border-line bg-bg/60 p-3 text-xs">
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
        <dt className="text-muted">Detectors</dt><dd className="text-ink2">{p.detectors.map((x) => (x.model ? `${x.model} ${x.version}` : x.type)).join(" + ")}</dd>
        <dt className="text-muted">Decision</dt><dd className="text-ink2">{d.mode === "fusion" ? `calibrated probability; pass ≤ ${pct(d.t_low)}, reject ≥ ${pct(d.t_high)}` : d.mode === "regions" ? `defect-level; confident at ≥ ${pct(d.region_confident, 0)}` : "screening → human review"}</dd>
        <dt className="text-muted">Auto-pass</dt><dd className="text-ink2">{p.image_level_validated ? "allowed (validated on defect-free samples)" : "disabled – never validated on defect-free samples"}</dd>
        {d.evidence && <><dt className="text-muted">Evidence</dt><dd><Link className="text-accent underline" href="/models">{d.evidence}</Link></dd></>}
        {d.note && <><dt className="text-muted">Note</dt><dd className="text-warn">{d.note}</dd></>}
        {p.requires_reference && <><dt className="text-muted">Input</dt><dd className="text-ink2">requires a golden reference image</dd></>}
      </dl>
      {editable && (
        <div className="mt-3 flex flex-wrap items-end gap-2 border-t border-line pt-3">
          <Field label="mm per pixel"><input className="input w-24 py-1" value={mm} onChange={(e) => setMm(e.target.value.replace(/[^0-9.]/g, ""))} placeholder="none" /></Field>
          {d.mode === "fusion" && <>
            <Field label="Pass ≤"><input className="input w-20 py-1" value={tl} onChange={(e) => setTl(e.target.value.replace(/[^0-9.]/g, ""))} /></Field>
            <Field label="Reject ≥"><input className="input w-20 py-1" value={th} onChange={(e) => setTh(e.target.value.replace(/[^0-9.]/g, ""))} /></Field></>}
          <button className="btn btn-sm" onClick={save}>Save</button>
          {msg && <span className={msg.tone === "good" ? "text-good" : "text-[#f08a8a]"}>{msg.text}</span>}
          {d.mode === "fusion" && d.validated && <p className="w-full text-muted">Changing thresholds by hand removes the “validated” status: the stored evidence was measured with the current values.</p>}
        </div>
      )}
    </div>
  );
}

function NewMaterial({ onDone }: { onDone: () => void }) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [err, setErr] = useState<string | null>(null);
  return (
    <form className="card mb-4 flex flex-wrap items-end gap-3 p-4" onSubmit={async (e) => {
      e.preventDefault();
      try { await api("/materials", { json: { name, description } }); onDone(); } catch (ex: any) { setErr(ex.message); }
    }}>
      <Field label="Material name"><input className="input w-56" required minLength={2} value={name} onChange={(e) => setName(e.target.value)} /></Field>
      <div className="min-w-[240px] flex-1"><Field label="Description"><input className="input" value={description} onChange={(e) => setDescription(e.target.value)} /></Field></div>
      <button className="btn btn-primary">Add material</button>
      {err && <span className="text-sm text-[#f08a8a]">{err}</span>}
    </form>
  );
}
