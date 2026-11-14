"use client";
import { Download } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { Empty, Notice, OutcomeBadge, PageHeader, SeverityBadge, Spinner, Tag } from "@/components/ui";
import { download, effectiveOutcome, fmtDate, pct, type InspectionRow, type Material } from "@/lib/api";
import { useApi } from "@/lib/auth";

const PAGE = 25;

function History() {
  const sp = useSearchParams();
  const [f, setF] = useState({ outcome: sp.get("outcome") ?? "", material: sp.get("material") ?? "", source: "", review_status: sp.get("review_status") ?? "", search: "",
    date_from: "", date_to: "", batch: sp.get("batch") ?? "", defect_type: sp.get("defect_type") ?? "", job_id: sp.get("job_id") ?? "", sort: sp.get("sort") ?? "newest" });
  const [page, setPage] = useState(0);
  const mats = useApi<Material[]>("/materials");
  const q = useApi<{ total: number; items: InspectionRow[] }>("/inspections", { ...f, limit: PAGE, offset: page * PAGE });
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => { setF((c) => ({ ...c, [k]: e.target.value })); setPage(0); };
  const total = q.data?.total ?? 0;
  return (
    <>
      <PageHeader title="Inspection History" sub="Every inspection with its AI outcome, human disposition and audit trail."
        right={<>
          <button className={`btn btn-sm ${f.review_status === "pending" ? "border-warn bg-warn/15" : ""}`} onClick={() => { setF((c) => ({ ...c, review_status: c.review_status === "pending" ? "" : "pending", sort: c.review_status === "pending" ? "newest" : "uncertain" })); setPage(0); }}>Review queue</button>
          <button className="btn btn-sm" onClick={() => download("/reports/inspections.csv", f)}><Download size={12} />Export CSV</button>
        </>} />
      <div className="card mb-4 grid grid-cols-2 gap-3 p-3 md:grid-cols-4 xl:grid-cols-8">
        <input aria-label="Search" className="input col-span-2" placeholder="Search product, batch, file, ID…" value={f.search} onChange={set("search")} />
        <select aria-label="Outcome" className="input" value={f.outcome} onChange={set("outcome")}><option value="">All outcomes</option><option value="pass">Pass</option><option value="review">Needs review</option><option value="defective">Defective</option></select>
        <select aria-label="Material" className="input" value={f.material} onChange={set("material")}><option value="">All materials</option>{mats.data?.map((m) => <option key={m.key} value={m.key}>{m.name}</option>)}</select>
        <select aria-label="Source" className="input" value={f.source} onChange={set("source")}><option value="">All sources</option>{["upload", "video", "live", "benchmark"].map((s) => <option key={s}>{s}</option>)}</select>
        <select aria-label="Sort" className="input" value={f.sort} onChange={set("sort")}><option value="newest">Newest first</option><option value="oldest">Oldest first</option><option value="uncertain">Most uncertain first</option></select>
        <input aria-label="From date" type="date" className="input" value={f.date_from} onChange={set("date_from")} />
        <input aria-label="To date" type="date" className="input" value={f.date_to} onChange={set("date_to")} />
      </div>
      {(f.batch || f.defect_type || f.job_id) && (
        <div className="mb-3 flex flex-wrap gap-2 text-xs">{(["batch", "defect_type", "job_id"] as const).filter((k) => f[k]).map((k) => (
          <button key={k} className="chip border-accent/50 text-ink2" onClick={() => setF((c) => ({ ...c, [k]: "" }))}>{k.replace("_", " ")}: {f[k]} ✕</button>))}</div>
      )}
      {q.error && <Notice tone="error">{q.error}</Notice>}
      <div className="card overflow-x-auto">
        <table className="w-full">
          <thead><tr>{["", "Inspected", "Product / batch", "Material · profile", "Outcome", "P(defect)", "Findings", "Severity", "Review", "Source"].map((h, i) => <th key={i} className="th">{h}</th>)}</tr></thead>
          <tbody>{q.data?.items.map((i) => (
            <tr key={i.id} className="hover:bg-raised/50">
              <td className="td w-14">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <Link href={`/inspections/${i.id}`}>{i.thumb_url ? <img src={i.thumb_url} alt="Open inspection" loading="lazy" className="h-10 w-10 rounded-sm object-cover" /> : "open"}</Link></td>
              <td className="td whitespace-nowrap"><Link className="text-ink hover:underline" href={`/inspections/${i.id}`}>{fmtDate(i.created_at)}</Link><div className="font-mono text-[11px] text-muted">{i.id.slice(0, 8)}</div></td>
              <td className="td">{i.product_id ?? "–"}<div className="text-[11px] text-muted">{i.batch_id ?? ""}</div></td>
              <td className="td">{i.material_key}<div className="text-[11px] text-muted">{i.profile_key ?? "generic screening"}</div></td>
              <td className="td"><OutcomeBadge outcome={effectiveOutcome(i)} />{i.final_outcome && i.outcome && i.final_outcome !== i.outcome && <div className="mt-0.5 text-[11px] text-muted">AI: {i.outcome}</div>}</td>
              <td className="td tabular-nums">{pct(i.p_defect)}</td>
              <td className="td tabular-nums">{i.defect_count}</td>
              <td className="td"><SeverityBadge level={i.max_severity} /></td>
              <td className="td">{i.review_status ? <Tag tone={i.review_status === "pending" ? "warn" : i.review_status === "corrected" ? "accent" : "good"}>{i.review_status}</Tag> : <span className="text-muted">–</span>}</td>
              <td className="td">{i.source}{i.ground_truth && <div className="text-[11px] text-muted">labelled: {i.ground_truth}</div>}</td>
            </tr>))}</tbody>
        </table>
        {q.loading && !q.data && <div className="px-4"><Spinner /></div>}
        {q.data && q.data.items.length === 0 && <div className="p-4"><Empty>No inspections match these filters.</Empty></div>}
      </div>
      <div className="mt-3 flex items-center justify-between text-sm text-muted">
        <span>{total ? `${page * PAGE + 1}–${Math.min(total, (page + 1) * PAGE)} of ${total.toLocaleString()}` : ""}</span>
        <span className="flex gap-2"><button className="btn btn-sm" disabled={page === 0} onClick={() => setPage(page - 1)}>Previous</button>
          <button className="btn btn-sm" disabled={(page + 1) * PAGE >= total} onClick={() => setPage(page + 1)}>Next</button></span>
      </div>
    </>
  );
}

export default function Page() { return <Suspense fallback={<Spinner />}><History /></Suspense>; }
