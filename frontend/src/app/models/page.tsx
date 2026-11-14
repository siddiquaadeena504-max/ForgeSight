"use client";
import { useState } from "react";
import { MetricBars, ReliabilityChart } from "@/components/charts";
import { Card, Empty, Notice, PageHeader, Spinner, Stat, Tag } from "@/components/ui";
import { api, fmtDate, pct } from "@/lib/api";
import { useApi, useAuth } from "@/lib/auth";

const fmt = (v: any) => (v === null || v === undefined ? "–" : typeof v === "number" ? (v <= 1 && v >= 0 ? pct(v) : v) : String(v));
const ci = (c: number[] | null | undefined) => (c ? `${pct(c[0])}–${pct(c[1])}` : "–");

export default function Models() {
  const { can } = useAuth();
  const ev = useApi<any[]>("/evaluations");
  const models = useApi<any[]>("/models");
  const prod = useApi<any[]>("/monitoring/production");
  const drift = useApi<any[]>("/monitoring/drift");
  const [sel, setSel] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const cur = ev.data?.find((e) => e.id === sel) ?? ev.data?.[0];
  const act = async (id: number, what: "promote" | "archive") => { setErr(null); try { await api(`/models/${id}/${what}`, { json: {} }); models.reload(); } catch (e: any) { setErr(e.message); } };
  return (
    <>
      <PageHeader title="Model Performance" sub="Every figure on this page was measured on held-out data and is stored with its dataset, split and sample size. Nothing is estimated or copied from publications." />
      <div className="mb-4"><Notice tone="warn" title="Engineering target: 99.9% validated performance – not reached, and not yet verifiable">
        No model here meets the target. With the current test sets it could not be demonstrated even by a perfect model: showing ≥99.9% with 95% confidence needs roughly 3,000+ error-free test samples per class. The 95% confidence intervals below show what the data actually supports.</Notice></div>
      {!ev.data ? <Spinner /> : ev.data.length === 0 ? <Empty>No evaluation records. Run <code>python scripts/benchmarks.py</code> or train a model from a dataset.</Empty> : (
        <div className="grid gap-4 xl:grid-cols-[300px_minmax(0,1fr)]">
          <Card pad={false} title="Evaluations">
            <ul>{ev.data.map((e) => (
              <li key={e.id}><button onClick={() => setSel(e.id)} className={`block w-full border-b border-line px-4 py-2.5 text-left hover:bg-raised/60 ${cur?.id === e.id ? "bg-raised" : ""}`}>
                <div className="text-sm font-medium text-ink">{e.model} <span className="font-normal text-muted">{e.version}</span></div>
                <div className="text-xs text-muted">{e.dataset} · {e.split} · n={e.n}</div><div className="mt-0.5 text-xs text-ink2">{e.task}</div></button></li>))}</ul>
          </Card>
          {cur && <Evaluation e={cur} />}
        </div>
      )}

      <h2 className="mb-2 mt-8 text-sm font-semibold uppercase tracking-wider text-muted">Production monitoring</h2>
      <div className="grid gap-4 xl:grid-cols-2">
        <Card pad={false} title="Decisions in production">
          <table className="w-full"><thead><tr>{["Profile", "n", "Review rate", "Audited", "Overturned", "Labelled replay"].map((h) => <th key={h} className="th">{h}</th>)}</tr></thead>
            <tbody>{prod.data?.map((p) => (
              <tr key={p.profile_key}><td className="td text-ink">{p.profile_key}</td><td className="td tabular-nums">{p.inspections}</td><td className="td tabular-nums">{pct(p.review_rate)}</td>
                <td className="td tabular-nums">{p.auto_decisions_audited_by_human}</td><td className="td tabular-nums">{p.auto_decisions_overturned}</td>
                <td className="td text-xs">{p.labelled_replay ? `${p.labelled_replay.correct_auto_decisions}/${p.labelled_replay.n} correct auto · ${p.labelled_replay.sent_to_review} review · ${p.labelled_replay.escaped_defects} escaped · ${p.labelled_replay.false_rejects} false rejects` : "–"}</td></tr>))}</tbody></table>
          <p className="p-3 text-xs text-muted">“Labelled replay” rows come from held-out test images with known ground truth that were run through the live pipeline. Unlabelled production parts can only be checked through human audits.</p>
        </Card>
        <Card pad={false} title="Input & score drift (PSI vs. validation reference)">
          <table className="w-full"><thead><tr>{["Profile", "Signal", "PSI", "Status", "Recent n", "Reference"].map((h) => <th key={h} className="th">{h}</th>)}</tr></thead>
            <tbody>{drift.data?.flatMap((d) => d.signals.map((s: any) => (
              <tr key={d.profile_key + s.signal}><td className="td text-ink">{d.profile_key}</td><td className="td">{s.signal}</td><td className="td tabular-nums">{s.psi ?? "–"}</td>
                <td className="td"><Tag tone={s.status === "stable" ? "good" : s.status === "significant_shift" ? "crit" : s.status === "moderate_shift" ? "warn" : "neutral"}>{s.status.replace(/_/g, " ")}</Tag></td>
                <td className="td tabular-nums">{s.n_recent}</td><td className="td text-xs">{s.reference ?? "none stored"}</td></tr>)))}</tbody></table>
          <p className="p-3 text-xs text-muted">PSI &lt; 0.1 stable · 0.1–0.25 moderate shift · &gt; 0.25 significant shift: re-validate before trusting automatic decisions.</p>
        </Card>
      </div>

      <h2 className="mb-2 mt-8 text-sm font-semibold uppercase tracking-wider text-muted">Model registry</h2>
      {err && <div className="mb-3"><Notice tone="error">{err}</Notice></div>}
      <Card pad={false}>
        <div className="overflow-x-auto"><table className="w-full"><thead><tr>{["Model", "Version", "Type", "Material", "Status", "Used by profiles", "Trained on", "Created", ""].map((h) => <th key={h} className="th">{h}</th>)}</tr></thead>
          <tbody>{models.data?.map((m) => (
            <tr key={m.id}><td className="td text-ink">{m.name}</td><td className="td font-mono text-xs">{m.version}</td><td className="td">{m.kind}</td><td className="td">{m.material_key ?? "–"}</td>
              <td className="td"><Tag tone={m.status === "production" ? "good" : m.status === "candidate" ? "accent" : "neutral"}>{m.status}</Tag></td>
              <td className="td text-xs">{m.used_by_profiles.join(", ") || "–"}</td><td className="td max-w-[260px] truncate text-xs" title={m.card.dataset}>{m.card.dataset ?? "–"}</td><td className="td whitespace-nowrap text-xs">{fmtDate(m.created_at)}</td>
              <td className="td whitespace-nowrap text-right">{can("engineer") && <>
                {m.status === "candidate" && <button className="btn btn-sm btn-primary" onClick={() => act(m.id, "promote")}>Promote</button>}
                {m.status !== "archived" && m.used_by_profiles.length === 0 && m.status !== "candidate" && <button className="btn btn-sm" onClick={() => act(m.id, "archive")}>Archive</button>}</>}</td></tr>))}</tbody></table></div>
      </Card>
    </>
  );
}

function KV({ rows }: { rows: [string, any, string?][] }) {
  return <table className="w-full"><tbody>{rows.filter((r) => r[1] !== undefined).map(([k, v, c]) => (
    <tr key={k}><td className="td">{k}</td><td className="td text-right tabular-nums text-ink">{fmt(v)}</td><td className="td w-40 text-right text-xs tabular-nums text-muted">{c ? `95% CI ${c}` : ""}</td></tr>))}</tbody></table>;
}

function Evaluation({ e }: { e: any }) {
  const m = e.metrics;
  const t = m.test && m.test.auroc !== undefined ? m.test : null;
  const bars = e.headline.filter((h: any) => typeof h.value === "number" && h.value <= 1 && !/rate/i.test(h.label)).map((h: any) => ({ label: h.label, value: h.value, ci95: h.ci95 }));
  const tri = m.test_triage ?? m.test?.triage;
  const perDefect = m.test_per_defect ?? m.per_defect;
  const conf = (m.test_defect_type ?? m.classification_of_matched ?? (m.test?.confusion ? m.test : null))?.confusion;
  return (
    <div className="min-w-0 space-y-4">
      <Card title={<span>{e.model} {e.version} · {e.task}</span>} right={<Tag>{e.dataset} · {e.split} · n={e.n}</Tag>}>
        <div className="grid gap-6 lg:grid-cols-2">
          <div>{bars.length ? <MetricBars data={bars} height={Math.max(120, bars.length * 34 + 40)} /> : <p className="text-sm text-muted">No ratio metrics.</p>}
            <p className="mt-1 text-xs text-muted">Bars: measured value. Whiskers: 95% Wilson interval where applicable.</p></div>
          <div>
            <div className="mb-1 text-[11px] font-medium uppercase tracking-wider text-muted">Known limitations</div>
            <ul className="list-disc space-y-1 pl-5 text-sm text-ink2">{(e.notes ?? []).map((n: string) => <li key={n}>{n}</li>)}</ul>
            <p className="mt-3 text-xs text-muted">Evaluated {fmtDate(e.created_at)} on {e.hardware}.</p>
          </div>
        </div>
      </Card>
      {t && (
        <div className="grid gap-4 lg:grid-cols-2">
          <Card pad={false} title="Image-level detection (defective vs. good, threshold 0.5)">
            <KV rows={[["AUROC", t.auroc], ["Precision", t.precision], ["Recall", t.recall, ci(t.recall_ci95)], ["F1 score", t.f1], ["Accuracy", t.accuracy, ci(t.accuracy_ci95)],
              ["False-positive rate", t.false_positive_rate, ci(t.fpr_ci95)], ["False-negative rate", t.false_negative_rate, ci(t.fnr_ci95)]]} />
            <div className="grid grid-cols-4 gap-2 p-3 text-center text-xs">{[["True pos.", t.tp], ["False pos.", t.fp], ["False neg.", t.fn], ["True neg.", t.tn]].map(([k, v]) => <div key={k} className="rounded border border-line py-1.5"><div className="text-lg font-semibold tabular-nums text-ink">{v}</div><div className="text-muted">{k}</div></div>)}</div>
          </Card>
          {t.calibration && <Card title={`Confidence calibration · ECE ${t.calibration.ece}`}><ReliabilityChart bins={t.calibration.bins} />
            <p className="mt-1 text-xs text-muted">Points on the dashed line mean a predicted probability of x% was right x% of the time.</p></Card>}
        </div>)}
      {tri && (
        <Card title="Three-way decision on the test split (pass / human review / defective)">
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
            <Stat label="Auto-pass" tone="good" value={tri.auto_pass} /><Stat label="Sent to review" tone="warn" value={tri.sent_to_review} sub={pct(tri.review_rate)} /><Stat label="Auto-defective" tone="crit" value={tri.auto_defective} />
            <Stat label="Escaped defects" value={tri.escaped_defects} sub={`95% CI ${ci(tri.escape_rate_ci95)}`} /><Stat label="False rejects" value={tri.false_rejects} sub={`95% CI ${ci(tri.false_reject_ci95)}`} />
          </div>
          <p className="mt-3 text-sm text-ink2">Thresholds (pass ≤ {pct(tri.t_low)}, reject ≥ {pct(tri.t_high)}) were chosen on the validation split only. Accuracy of automatic decisions: <b>{pct(tri.auto_decision_accuracy)}</b> (95% CI {ci(tri.auto_decision_accuracy_ci95)}).</p>
        </Card>)}
      {m.operating_points && (
        <Card pad={false} title="Review-band operating points (thresholds chosen on validation, measured on test)">
          <table className="w-full"><thead><tr>{["Validation tolerance", "Auto-pass", "Auto-defective", "Sent to review", "Escaped defects", "False rejects", "Auto-decision accuracy"].map((h) => <th key={h} className="th">{h}</th>)}</tr></thead><tbody>
            {m.operating_points.map((o: any) => (
              <tr key={o.validation_tolerance} className={o.shipped ? "bg-raised" : ""}><td className="td text-ink">{pct(o.validation_tolerance, 0)} {o.shipped && <Tag tone="accent">in use</Tag>}</td>
                <td className="td tabular-nums">{o.test.auto_pass}</td><td className="td tabular-nums">{o.test.auto_defective}</td><td className="td tabular-nums">{o.test.sent_to_review} ({pct(o.test.review_rate, 0)})</td>
                <td className="td tabular-nums">{o.test.escaped_defects} <span className="text-xs text-muted">CI {ci(o.test.escape_rate_ci95)}</span></td>
                <td className="td tabular-nums">{o.test.false_rejects} <span className="text-xs text-muted">CI {ci(o.test.false_reject_ci95)}</span></td>
                <td className="td tabular-nums">{pct(o.test.auto_decision_accuracy)}</td></tr>))}</tbody></table>
          <p className="p-3 text-xs text-muted">Tolerance = share of validation defects allowed below the pass threshold and of validation goods above the reject threshold. A tighter tolerance sends more parts to human review.</p>
        </Card>)}
      {m.cross_validation && <Card title="Cross-validation"><p className="text-sm text-ink2">{m.cross_validation.folds}-fold image-level AUROC: <b>{m.cross_validation.auroc_mean}</b> ± {m.cross_validation.auroc_std} (folds: {m.cross_validation.auroc_per_fold.join(", ")}).</p></Card>}
      {m.localization && (
        <div className="grid gap-4 lg:grid-cols-2">
          <Card pad={false} title={`Defect localization (IoU ≥ ${m.localization.iou_threshold})`}><KV rows={[["Precision", m.localization.precision], ["Recall", m.localization.recall, ci(m.localization.recall_ci95)], ["F1 score", m.localization.f1], ["False-negative rate", m.localization.false_negative_rate], ["False alarms per image", String(m.localization.false_alarms_per_image)], ["Ground-truth defects", String(m.gt_defects)]]} /></Card>
          <Card pad={false} title="Localization + correct class"><KV rows={[["Precision", m.class_aware.precision], ["Recall", m.class_aware.recall, ci(m.class_aware.recall_ci95)], ["F1 score", m.class_aware.f1], ["Mean latency", `${m.latency_ms_mean} ms`], ["p95 latency", `${m.latency_ms_p95} ms`]]} /></Card>
        </div>)}
      {(m.test_pixel || m.test_pixel_strict) && (
        <Card pad={false} title="Segmentation (pixel level, test defect images)">
          <table className="w-full"><thead><tr>{["Variant", "Pixel precision", "Pixel recall", "Pixel F1", "IoU"].map((h) => <th key={h} className="th">{h}</th>)}</tr></thead><tbody>
            {[["Strict", m.test_pixel ?? m.test_pixel_strict], m.test_pixel_tolerant && [`${m.test_pixel_tolerant.tolerance_px} px tolerance`, m.test_pixel_tolerant], m.classical_baseline && ["Classical baseline (strict)", m.classical_baseline.test_pixel_strict]].filter(Boolean).map(([k, v]: any) => (
              <tr key={k}><td className="td">{k}</td><td className="td tabular-nums">{fmt(v.pixel_precision)}</td><td className="td tabular-nums">{fmt(v.pixel_recall)}</td><td className="td tabular-nums text-ink">{fmt(v.pixel_f1)}</td><td className="td tabular-nums">{fmt(v.iou)}</td></tr>))}</tbody></table>
        </Card>)}
      {perDefect && (
        <Card pad={false} title="Per-defect performance">
          <table className="w-full"><thead><tr>{["Defect type", "Test samples", "Recall", "95% CI", "Precision / note"].map((h) => <th key={h} className="th">{h}</th>)}</tr></thead><tbody>
            {Object.entries(perDefect).map(([k, v]: any) => (
              <tr key={k}><td className="td text-ink">{k}</td><td className="td tabular-nums">{v.support}</td><td className="td tabular-nums">{fmt(v.recall ?? v.recall_at_0_5 ?? v["recall_at_0.5"])}</td><td className="td tabular-nums text-xs">{ci(v.recall_ci95)}</td>
                <td className="td text-xs">{v.precision !== undefined ? `precision ${fmt(v.precision)}` : `${fmt(v.caught_or_reviewed_rate)} caught or sent to review`}{v.support < 30 && <span className="ml-2 text-warn">small sample</span>}</td></tr>))}</tbody></table>
        </Card>)}
      {conf && (
        <Card title="Confusion matrix (rows: actual, columns: predicted)">
          <div className="overflow-x-auto"><table className="text-xs"><thead><tr><th />{conf.labels.map((l: string) => <th key={l} className="px-2 py-1 text-muted">{l}</th>)}</tr></thead><tbody>
            {conf.matrix.map((row: number[], i: number) => { const mx = Math.max(1, ...row); return (
              <tr key={i}><th className="pr-3 text-right font-normal text-muted">{conf.labels[i]}</th>{row.map((v, j) => (
                <td key={j} className="h-9 w-14 border border-bg text-center tabular-nums" style={{ background: v ? `rgba(57,135,229,${0.12 + 0.78 * (v / mx)})` : "#191b1e", color: v / mx > 0.5 ? "#fff" : "#c3c2b7" }}>{v}</td>))}</tr>); })}</tbody></table></div>
        </Card>)}
    </div>
  );
}
