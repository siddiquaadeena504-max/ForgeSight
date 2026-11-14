"use client";
import { Plus } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { Card, Empty, Field, Notice, PageHeader, Spinner, Tag } from "@/components/ui";
import { api, fmtDate, type Material } from "@/lib/api";
import { useApi, useAuth } from "@/lib/auth";

export default function Datasets() {
  const { can } = useAuth();
  const ds = useApi<any[]>("/datasets");
  const mats = useApi<Material[]>("/materials");
  const [n, setN] = useState({ name: "", material_key: "", description: "", val_fraction: 0.2, test_fraction: 0.2 });
  const [err, setErr] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  return (
    <>
      <PageHeader title="Dataset Management" sub="Material-specific image sets with labels, boxes and masks. Splits are assigned per leakage group so the same part never appears in both training and evaluation."
        right={can("engineer") && <button className="btn btn-sm btn-primary" onClick={() => setOpen(!open)}><Plus size={12} />New dataset</button>} />
      {open && (
        <form className="card mb-4 grid gap-3 p-4 md:grid-cols-[1fr_220px_1fr_110px_110px_auto] md:items-end" onSubmit={async (e) => {
          e.preventDefault(); setErr(null);
          try { await api("/datasets", { json: n }); setOpen(false); ds.reload(); } catch (ex: any) { setErr(ex.message); }
        }}>
          <Field label="Name"><input className="input" required minLength={2} value={n.name} onChange={(e) => setN({ ...n, name: e.target.value })} /></Field>
          <Field label="Material"><select className="input" required value={n.material_key} onChange={(e) => setN({ ...n, material_key: e.target.value })}><option value="">Select…</option>{mats.data?.map((m) => <option key={m.key} value={m.key}>{m.name}</option>)}</select></Field>
          <Field label="Description"><input className="input" value={n.description} onChange={(e) => setN({ ...n, description: e.target.value })} /></Field>
          <Field label="Validation %"><input className="input" type="number" min={0} max={45} value={n.val_fraction * 100} onChange={(e) => setN({ ...n, val_fraction: +e.target.value / 100 })} /></Field>
          <Field label="Test %"><input className="input" type="number" min={0} max={45} value={n.test_fraction * 100} onChange={(e) => setN({ ...n, test_fraction: +e.target.value / 100 })} /></Field>
          <button className="btn btn-primary">Create</button>
          {err && <div className="md:col-span-6"><Notice tone="error">{err}</Notice></div>}
        </form>
      )}
      {!ds.data ? <Spinner /> : ds.data.length === 0 ? <Empty>No datasets yet. Create one, upload defect-free and defective images, assign splits, then fit an anomaly model.</Empty> : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">{ds.data.map((d) => {
          const c = (s: string) => { const x = d.splits[s]; return x ? x.good + x.defective + x.unlabeled : 0; };
          return (
            <Link key={d.id} href={`/datasets/${d.id}`} className="card block p-4 hover:border-accent/60">
              <div className="flex items-start justify-between gap-2"><h3 className="text-sm font-semibold">{d.name}</h3><Tag>{d.material_key}</Tag></div>
              <p className="mt-1 line-clamp-2 text-xs text-muted">{d.description || "No description"}</p>
              <div className="mt-3 text-2xl font-semibold tabular-nums">{d.image_count}<span className="ml-1 text-xs font-normal text-muted">images</span></div>
              <div className="mt-2 flex h-2 gap-[2px] overflow-hidden rounded-sm">{[["train", "#3987e5"], ["val", "#d95926"], ["test", "#199e70"], ["unassigned", "#3a3e45"]].map(([s, col]) => c(s) > 0 && <div key={s} style={{ flex: c(s), background: col }} title={`${s}: ${c(s)}`} />)}</div>
              <div className="mt-1.5 flex flex-wrap gap-x-3 text-[11px] text-muted"><span>train {c("train")}</span><span>val {c("val")}</span><span>test {c("test")}</span>{c("unassigned") > 0 && <span className="text-warn">unassigned {c("unassigned")}</span>}</div>
              <div className="mt-2 text-[11px] text-muted">{d.defect_classes.length} defect classes · created {fmtDate(d.created_at)}</div>
            </Link>);
        })}</div>
      )}
    </>
  );
}
