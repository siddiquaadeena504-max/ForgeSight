"use client";
import clsx from "clsx";
import { AlertTriangle, CheckCircle2, CircleAlert, Info, Loader2, ShieldAlert, XCircle } from "lucide-react";
import type { Outcome } from "@/lib/api";

export function Card({ title, right, children, className, pad = true }: { title?: React.ReactNode; right?: React.ReactNode; children: React.ReactNode; className?: string; pad?: boolean }) {
  return (
    <section className={clsx("card", className)}>
      {(title || right) && (
        <header className="card-h">
          <h2 className="card-t">{title}</h2>
          {right}
        </header>
      )}
      <div className={pad ? "p-4" : ""}>{children}</div>
    </section>
  );
}

export function PageHeader({ title, sub, right }: { title: string; sub?: React.ReactNode; right?: React.ReactNode }) {
  return (
    <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold tracking-tight text-ink">{title}</h1>
        {sub && <p className="mt-0.5 max-w-3xl text-sm text-muted">{sub}</p>}
      </div>
      {right && <div className="flex flex-wrap items-center gap-2">{right}</div>}
    </div>
  );
}

const OUTCOME = {
  pass: { label: "Pass", cls: "border-good/50 bg-good/10 text-[#7fd67f]", Icon: CheckCircle2 },
  review: { label: "Needs review", cls: "border-warn/50 bg-warn/10 text-warn", Icon: AlertTriangle },
  defective: { label: "Defective", cls: "border-crit/60 bg-crit/15 text-[#f08a8a]", Icon: XCircle },
} as const;

export function OutcomeBadge({ outcome, size = "sm" }: { outcome: Outcome | null | undefined; size?: "sm" | "lg" }) {
  if (!outcome) return <span className="chip border-line text-muted">–</span>;
  const o = OUTCOME[outcome];
  return (
    <span className={clsx("chip", o.cls, size === "lg" && "px-2.5 py-1 text-sm")}>
      <o.Icon size={size === "lg" ? 16 : 12} aria-hidden />
      {o.label}
    </span>
  );
}

const SEV = { minor: "border-warn/40 text-warn", major: "border-serious/50 text-serious", critical: "border-crit/60 bg-crit/15 text-[#f08a8a]" } as const;
export function SeverityBadge({ level }: { level: string | null | undefined }) {
  if (!level) return <span className="text-muted">–</span>;
  return (
    <span className={clsx("chip capitalize", SEV[level as keyof typeof SEV] ?? "border-line text-ink2")}>
      {level === "critical" ? <ShieldAlert size={12} aria-hidden /> : <CircleAlert size={12} aria-hidden />}
      {level}
    </span>
  );
}

export function Tag({ children, tone = "neutral", title }: { children: React.ReactNode; tone?: "neutral" | "good" | "warn" | "accent" | "crit"; title?: string }) {
  const cls = { neutral: "border-line text-ink2", good: "border-good/50 text-[#7fd67f]", warn: "border-warn/50 text-warn", accent: "border-accent/50 text-[#8bb9f2]", crit: "border-crit/60 text-[#f08a8a]" }[tone];
  return <span title={title} className={clsx("chip", cls)}>{children}</span>;
}

export function Stat({ label, value, sub, tone }: { label: string; value: React.ReactNode; sub?: React.ReactNode; tone?: "good" | "warn" | "crit" }) {
  const bar = tone === "good" ? "bg-good" : tone === "warn" ? "bg-warn" : tone === "crit" ? "bg-crit" : "bg-lineStrong";
  return (
    <div className="card relative overflow-hidden px-4 py-3">
      <span className={clsx("absolute inset-y-0 left-0 w-[3px]", bar)} aria-hidden />
      <div className="text-[11px] font-medium uppercase tracking-wider text-muted">{label}</div>
      <div className="mt-1 text-2xl font-semibold tabular-nums text-ink">{value}</div>
      {sub && <div className="mt-0.5 text-xs text-muted">{sub}</div>}
    </div>
  );
}

export function Notice({ tone = "info", children, title }: { tone?: "info" | "warn" | "error" | "good"; children: React.ReactNode; title?: string }) {
  const map = { info: ["border-accent/40 bg-accent/5", Info, "text-[#8bb9f2]"], warn: ["border-warn/40 bg-warn/5", AlertTriangle, "text-warn"],
    error: ["border-crit/50 bg-crit/10", XCircle, "text-[#f08a8a]"], good: ["border-good/40 bg-good/5", CheckCircle2, "text-[#7fd67f]"] } as const;
  const [cls, Icon, ic] = map[tone];
  return (
    <div role={tone === "error" ? "alert" : "note"} className={clsx("flex gap-2.5 rounded border px-3 py-2 text-sm text-ink2", cls)}>
      <Icon size={16} className={clsx("mt-0.5 shrink-0", ic)} aria-hidden />
      <div className="min-w-0">{title && <div className="font-medium text-ink">{title}</div>}{children}</div>
    </div>
  );
}

export function Spinner({ label }: { label?: string }) {
  return <div className="flex items-center gap-2 py-6 text-sm text-muted"><Loader2 size={16} className="animate-spin" aria-hidden />{label ?? "Loading…"}</div>;
}

export function Empty({ children }: { children: React.ReactNode }) {
  return <div className="rounded border border-dashed border-line px-4 py-8 text-center text-sm text-muted">{children}</div>;
}

export function Field({ label, children, hint }: { label: string; children: React.ReactNode; hint?: string }) {
  return (
    <label className="block">
      <span className="label">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-muted">{hint}</span>}
    </label>
  );
}

export function Toggle({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <button type="button" role="switch" aria-checked={checked} onClick={() => onChange(!checked)}
      className={clsx("chip cursor-pointer select-none", checked ? "border-accent/60 bg-accent/15 text-ink" : "border-line text-muted hover:text-ink2")}>
      <span className={clsx("h-2 w-2 rounded-full", checked ? "bg-accent" : "bg-lineStrong")} aria-hidden />
      {label}
    </button>
  );
}

export function Meter({ value, tLow, tHigh }: { value: number; tLow?: number; tHigh?: number }) {
  return (
    <div className="relative h-2 w-full rounded-sm bg-raised" aria-hidden>
      {tLow !== undefined && tHigh !== undefined && <div className="absolute inset-y-0 bg-warn/25" style={{ left: `${tLow * 100}%`, width: `${Math.max(0.5, (tHigh - tLow) * 100)}%` }} />}
      <div className="absolute -top-0.5 h-3 w-[3px] rounded-sm bg-ink" style={{ left: `calc(${Math.min(100, Math.max(0, value * 100))}% - 1px)` }} />
    </div>
  );
}
