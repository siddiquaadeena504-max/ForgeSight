"use client";
import { Download, FileSpreadsheet, FileText } from "lucide-react";
import { useState } from "react";
import { Card, Field, Notice, PageHeader, Spinner, Stat } from "@/components/ui";
import { download, num, pct, type Material } from "@/lib/api";
import { useApi } from "@/lib/auth";

export default function Reports() {
  const mats = useApi<Material[]>("/materials");
  const [f, setF] = useState({ material: "", date_from: "", date_to: "", outcome: "", batch: "" });
  const a = useApi<any>("/analytics/overview", { material: f.material, date_from: f.date_from, date_to: f.date_to });
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setF((c) => ({ ...c, [k]: e.target.value }));
  const dl = async (key: string, path: string, params: Record<string, unknown>) => { setBusy(key); setErr(null); try { await download(path, params); } catch (e: any) { setErr(e.message); } finally { setBusy(null); } };
  const o = a.data?.overview;
  const REPORTS = [
    { key: "q", Icon: FileText, title: "Quality control report (PDF)", desc: "Totals, defects by type, by material, by batch, daily trend and the model validation evidence for the period.", go: () => dl("q", "/reports/quality.pdf", { material: f.material, date_from: f.date_from, date_to: f.date_to }) },
    { key: "i", Icon: FileSpreadsheet, title: "Inspections (CSV)", desc: "One row per inspection: product, batch, material, AI outcome, final outcome, review status, defect probability, timing.", go: () => dl("i", "/reports/inspections.csv", f) },
    { key: "d", Icon: FileSpreadsheet, title: "Defects (CSV)", desc: "One row per finding: type, classification source, confidence, severity, location, dimensions, hypotheses, recommended action.", go: () => dl("d", "/reports/defects.csv", f) },
  ];
  return (
    <>
      <PageHeader title="Quality Reports" sub="Download period reports. Per-inspection PDF reports (original and annotated image, classifications, severity, next steps) are available from each inspection." />
      <div className="grid gap-4 lg:grid-cols-[320px_minmax(0,1fr)]">
        <Card title="Report scope">
          <div className="space-y-3">
            <Field label="Material"><select className="input" value={f.material} onChange={set("material")}><option value="">All materials</option>{mats.data?.map((m) => <option key={m.key} value={m.key}>{m.name}</option>)}</select></Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="From"><input type="date" className="input" value={f.date_from} onChange={set("date_from")} /></Field>
              <Field label="To"><input type="date" className="input" value={f.date_to} onChange={set("date_to")} /></Field>
            </div>
            <Field label="Outcome (CSV only)"><select className="input" value={f.outcome} onChange={set("outcome")}><option value="">All</option><option value="pass">Pass</option><option value="review">Needs review</option><option value="defective">Defective</option></select></Field>
            <Field label="Batch (CSV only)"><input className="input" value={f.batch} onChange={set("batch")} placeholder="exact batch ID" /></Field>
          </div>
        </Card>
        <div className="space-y-4">
          {!o ? <Spinner /> : (
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              <Stat label="In scope" value={num(o.total)} /><Stat label="Passed" tone="good" value={num(o.passed)} sub={o.total ? pct(o.passed / o.total) : ""} />
              <Stat label="Review" tone="warn" value={num(o.review)} /><Stat label="Defective" tone="crit" value={num(o.defective)} sub={o.total ? pct(o.defective / o.total) : ""} />
            </div>)}
          {err && <Notice tone="error">{err}</Notice>}
          <div className="grid gap-3 md:grid-cols-3">
            {REPORTS.map((r) => (
              <div key={r.key} className="card flex flex-col p-4">
                <r.Icon size={20} className="text-accent" aria-hidden />
                <h3 className="mt-2 text-sm font-semibold">{r.title}</h3>
                <p className="mt-1 flex-1 text-xs text-muted">{r.desc}</p>
                <button className="btn btn-sm mt-3" disabled={busy !== null} onClick={r.go}><Download size={12} />{busy === r.key ? "Preparing…" : "Download"}</button>
              </div>))}
          </div>
          {a.data?.by_batch.length > 0 && (
            <Card pad={false} title="Batch summary (in scope)">
              <div className="max-h-96 overflow-auto"><table className="w-full"><thead><tr>{["Batch", "Inspected", "Passed", "Review", "Defective", "Defects"].map((h) => <th key={h} className="th sticky top-0 bg-panel">{h}</th>)}</tr></thead>
                <tbody>{a.data.by_batch.map((b: any) => <tr key={b.batch}><td className="td text-ink">{b.batch}</td><td className="td tabular-nums">{b.total}</td><td className="td tabular-nums">{b.passed}</td><td className="td tabular-nums">{b.review}</td><td className="td tabular-nums">{b.defective}</td><td className="td tabular-nums">{b.defects}</td></tr>)}</tbody></table></div>
            </Card>)}
        </div>
      </div>
    </>
  );
}
