"use client";
import Link from "next/link";
import { useState } from "react";
import { RateLine, SeverityBars, SimpleBars } from "@/components/charts";
import { Card, Empty, Notice, OutcomeBadge, PageHeader, SeverityBadge, Spinner, Stat, Tag } from "@/components/ui";
import { effectiveOutcome, fmtDate, num, type InspectionRow, type Material } from "@/lib/api";
import { useApi } from "@/lib/auth";

export default function Defects() {
  const [days, setDays] = useState("");
  const [material, setMaterial] = useState("");
  const [type, setType] = useState("");
  const mats = useApi<Material[]>("/materials");
  const a = useApi<any>("/analytics/overview", { days, material });
  const list = useApi<{ total: number; items: InspectionRow[] }>(type ? "/inspections" : null, { defect_type: type, material, limit: 12 });
  const types: any[] = a.data?.by_type ?? [];
  const total = types.reduce((s, t) => s + t.count, 0);
  const named = types.reduce((s, t) => s + t.classified_by_model, 0);
  const cur = types.find((t) => t.defect_type === type);
  return (
    <>
      <PageHeader title="Defect Analysis" sub="Distribution, severity and frequency of detected defects. Findings rejected by an inspector as false alarms are excluded."
        right={<>
          <select aria-label="Material" className="input w-48 py-1" value={material} onChange={(e) => { setMaterial(e.target.value); setType(""); }}><option value="">All materials</option>{mats.data?.map((m) => <option key={m.key} value={m.key}>{m.name}</option>)}</select>
          <select aria-label="Period" className="input w-36 py-1" value={days} onChange={(e) => setDays(e.target.value)}><option value="">All time</option><option value="7">Last 7 days</option><option value="30">Last 30 days</option></select>
        </>} />
      {!a.data ? <Spinner /> : total === 0 ? <Empty>No defects recorded for this selection.</Empty> : (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Stat label="Defects found" value={num(total)} />
            <Stat label="Critical" tone="crit" value={num(types.reduce((s, t) => s + t.critical, 0))} />
            <Stat label="Distinct types" value={types.length} />
            <Stat label="Named by a trained model" value={num(named)} sub={`${num(total - named)} localized only (type unknown)`} />
          </div>
          <div className="grid gap-4 xl:grid-cols-2">
            <Card title="Defect distribution by type and severity"><SeverityBars data={types} />
              <div className="mt-3 flex flex-wrap gap-1.5">{types.map((t) => (
                <button key={t.defect_type} onClick={() => setType(type === t.defect_type ? "" : t.defect_type)} className={`chip cursor-pointer ${type === t.defect_type ? "border-accent bg-accent/20 text-ink" : "border-line text-ink2 hover:border-lineStrong"}`}>{t.label} · {t.count}</button>))}</div>
            </Card>
            <div className="space-y-4">
              <Card title="Defects found per material"><SimpleBars data={a.data.by_material.filter((m: any) => m.defects > 0)} x="material" y="defects" name="Defects" height={200} /></Card>
              <Card title="Defective rate over time"><RateLine data={a.data.trend} x="date" y="defect_rate" name="Defective rate" height={200} /></Card>
            </div>
          </div>
          <Card pad={false} title="Defect frequency by production batch">
            {a.data.by_batch.length === 0 ? <p className="p-4 text-sm text-muted">No batch IDs recorded.</p> : (
              <div className="max-h-80 overflow-auto"><table className="w-full"><thead><tr>{["Batch", "Inspected", "Defects found", "Defects / part", "Defective parts", "In review"].map((h) => <th key={h} className="th sticky top-0 bg-panel">{h}</th>)}</tr></thead>
                <tbody>{a.data.by_batch.map((b: any) => (
                  <tr key={b.batch} className="hover:bg-raised/50"><td className="td"><Link className="text-ink hover:underline" href={`/history?batch=${encodeURIComponent(b.batch)}`}>{b.batch}</Link></td>
                    <td className="td tabular-nums">{b.total}</td><td className="td tabular-nums">{b.defects}</td><td className="td tabular-nums">{(b.defects / b.total).toFixed(2)}</td>
                    <td className="td tabular-nums">{b.defective} ({((b.defective / b.total) * 100).toFixed(0)}%)</td><td className="td tabular-nums">{b.review}</td></tr>))}</tbody></table></div>)}
          </Card>
          {type && cur && (
            <Card title={`${cur.label} – recent inspections`} right={<Link className="text-xs text-accent hover:underline" href={`/history?defect_type=${type}`}>All {cur.count} →</Link>}>
              {cur.classified_by_model === 0 && <div className="mb-3"><Notice tone="warn">This label is a shape description from the screening detector, not a defect type established by a trained classifier. No causes are suggested for it.</Notice></div>}
              {!list.data ? <Spinner /> : (
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">{list.data.items.map((i) => (
                  <Link key={i.id} href={`/inspections/${i.id}`} className="rounded border border-line p-1.5 hover:border-accent">
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    {i.thumb_url && <img src={i.thumb_url} alt="" loading="lazy" className="aspect-square w-full rounded-sm object-cover" />}
                    <div className="mt-1.5 flex items-center justify-between gap-1"><OutcomeBadge outcome={effectiveOutcome(i)} /><SeverityBadge level={i.max_severity} /></div>
                    <div className="mt-1 truncate text-[11px] text-muted">{fmtDate(i.created_at)}</div>
                  </Link>))}</div>)}
            </Card>
          )}
        </div>
      )}
    </>
  );
}
