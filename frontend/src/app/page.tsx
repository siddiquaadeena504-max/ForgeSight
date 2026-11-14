"use client";
import { Download } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { OutcomeTrend, SeverityBars, SimpleBars, StackedOutcomeBars } from "@/components/charts";
import { Card, Empty, Notice, PageHeader, Spinner, Stat, Tag } from "@/components/ui";
import { download, num, pct } from "@/lib/api";
import { useApi } from "@/lib/auth";

export default function Overview() {
  const [days, setDays] = useState("");
  const a = useApi<any>("/analytics/overview", { days });
  const ev = useApi<any[]>("/evaluations");
  const prod = useApi<any[]>("/monitoring/production");
  const o = a.data?.overview;
  return (
    <>
      <PageHeader title="Overview" sub="Quality status across all inspected products. Outcomes use the human-reviewed result where one exists."
        right={<>
          <select aria-label="Period" className="input w-36 py-1" value={days} onChange={(e) => setDays(e.target.value)}><option value="">All time</option><option value="1">Last 24 hours</option><option value="7">Last 7 days</option><option value="30">Last 30 days</option></select>
          <button className="btn btn-sm" onClick={() => download("/reports/quality.pdf", { days })}><Download size={12} />Quality report (PDF)</button>
        </>} />
      {a.error && <Notice tone="error">{a.error}</Notice>}
      {!a.data ? <Spinner /> : o.total === 0 ? (
        <Empty>No inspections yet. <Link className="text-accent underline" href="/inspect">Run the first inspection</Link>.</Empty>
      ) : (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
            <Stat label="Products inspected" value={num(o.total)} sub={`${num(a.data.throughput.inspections_last_24h)} in the last 24 h`} />
            <Stat label="Passed" tone="good" value={num(o.passed)} sub={pct(o.passed / o.total) + " of inspected"} />
            <Stat label="Requiring review" tone="warn" value={num(o.review)} sub={<Link className="underline" href="/history?review_status=pending&sort=uncertain">{num(o.pending_review)} in review queue</Link>} />
            <Stat label="Flagged defective" tone="crit" value={num(o.defective)} sub={pct(o.defective / o.total) + " of inspected"} />
            <Stat label="Engine throughput" value={a.data.throughput.engine_capacity_per_hour ? `${num(a.data.throughput.engine_capacity_per_hour)}/h` : "–"} sub={`mean ${o.mean_processing_ms?.toFixed(0)} ms · p95 ${o.p95_processing_ms?.toFixed(0)} ms per image`} />
          </div>
          <div className="grid gap-4 xl:grid-cols-3">
            <Card title="Historical quality trend" className="xl:col-span-2"><OutcomeTrend data={a.data.trend} height={260} />
              <p className="mt-1 text-xs text-muted">Inspections per day by final outcome.</p></Card>
            <Card title="Most common defect types" right={<Link className="text-xs text-accent hover:underline" href="/defects">Defect analysis →</Link>}>
              {a.data.by_type.length ? <SeverityBars data={a.data.by_type.slice(0, 7)} /> : <Empty>No defects recorded.</Empty>}</Card>
          </div>
          <div className="grid gap-4 xl:grid-cols-2">
            <Card title="Outcomes by material"><StackedOutcomeBars data={a.data.by_material} category="material" /></Card>
            <Card title="Defective rate by production batch">
              {a.data.by_batch.length ? <SimpleBars data={a.data.by_batch.slice(-16).map((b: any) => ({ ...b, rate: b.defective / b.total }))} x="batch" y="rate" name="Defective rate" percent height={250} /> : <Empty>No batch IDs recorded.</Empty>}</Card>
          </div>
          <div className="grid gap-4 xl:grid-cols-2">
            <Card pad={false} title="Model performance (held-out test data)" right={<Link className="text-xs text-accent hover:underline" href="/models">Evaluation dashboard →</Link>}>
              {!ev.data?.length ? <p className="p-4 text-sm text-muted">No evaluation records. Until a model is validated, every result is routed to human review.</p> : (
                <div className="overflow-x-auto"><table className="w-full"><thead><tr>{["Model", "Dataset", "n", "Headline (measured)"].map((h) => <th key={h} className="th">{h}</th>)}</tr></thead>
                  <tbody>{ev.data.map((e) => (
                    <tr key={e.id}><td className="td text-ink">{e.model}</td><td className="td">{e.dataset}</td><td className="td tabular-nums">{e.n}</td>
                      <td className="td">{e.headline.slice(0, 2).map((h: any) => <span key={h.label} className="mr-3 inline-block whitespace-nowrap">{h.label} <b className="tabular-nums text-ink">{h.value}</b></span>)}</td></tr>))}</tbody></table></div>
              )}
            </Card>
            <Card pad={false} title="AI decisions in production">
              <div className="overflow-x-auto"><table className="w-full"><thead><tr>{["Profile", "Inspected", "Auto-decided", "To review", "Human audit"].map((h) => <th key={h} className="th">{h}</th>)}</tr></thead>
                <tbody>{prod.data?.map((p) => (
                  <tr key={p.profile_key}><td className="td text-ink">{p.profile_key}</td><td className="td tabular-nums">{p.inspections}</td><td className="td tabular-nums">{p.auto_decided}</td>
                    <td className="td tabular-nums">{pct(p.review_rate)}</td>
                    <td className="td tabular-nums">{p.auto_decisions_audited_by_human ? `${p.auto_decisions_overturned} of ${p.auto_decisions_audited_by_human} overturned` : <Tag>none audited</Tag>}</td></tr>))}</tbody></table></div>
            </Card>
          </div>
        </div>
      )}
    </>
  );
}
