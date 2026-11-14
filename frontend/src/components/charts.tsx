"use client";
import { Bar, BarChart, CartesianGrid, Cell, ErrorBar, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

/* Colour roles (dark surface). Status colours are reserved for outcomes/severity; series use the categorical order. */
export const C = { pass: "#0ca30c", review: "#fab219", defective: "#d03b3b", minor: "#fab219", major: "#ec835a", critical: "#d03b3b",
  s1: "#3987e5", s2: "#d95926", s3: "#199e70", s4: "#c98500", grid: "#2c2f34", axis: "#8d9096", surface: "#191b1e" };

const tip = { contentStyle: { background: "#212428", border: "1px solid #3a3e45", borderRadius: 4, fontSize: 12, color: "#f0efec", padding: "6px 10px" }, labelStyle: { color: "#c3c2b7", marginBottom: 4 },
  itemStyle: { color: "#f0efec", padding: 0 }, cursor: { fill: "#ffffff", fillOpacity: 0.04 } };
const axis = { tickLine: false, axisLine: { stroke: C.grid }, tick: { fill: C.axis, fontSize: 11 } };
const seg = { stroke: C.surface, strokeWidth: 2 };

export function OutcomeTrend({ data, height = 240 }: { data: { date: string; passed: number; review: number; defective: number }[]; height?: number }) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ top: 8, right: 8, left: -12, bottom: 0 }} barCategoryGap="22%">
        <CartesianGrid vertical={false} stroke={C.grid} />
        <XAxis dataKey="date" {...axis} tickFormatter={(d: string) => d.slice(5)} minTickGap={16} />
        <YAxis {...axis} axisLine={false} allowDecimals={false} />
        <Tooltip {...tip} />
        <Legend iconType="square" iconSize={9} wrapperStyle={{ paddingTop: 6 }} />
        <Bar dataKey="passed" name="Pass" stackId="o" fill={C.pass} {...seg} maxBarSize={36} />
        <Bar dataKey="review" name="Needs review" stackId="o" fill={C.review} {...seg} maxBarSize={36} />
        <Bar dataKey="defective" name="Defective" stackId="o" fill={C.defective} {...seg} radius={[3, 3, 0, 0]} maxBarSize={36} />
      </BarChart>
    </ResponsiveContainer>
  );
}

export function StackedOutcomeBars({ data, category, height }: { data: any[]; category: string; height?: number }) {
  return (
    <ResponsiveContainer width="100%" height={height ?? Math.max(120, data.length * 34 + 50)}>
      <BarChart data={data} layout="vertical" margin={{ top: 4, right: 16, left: 8, bottom: 0 }} barCategoryGap="28%">
        <CartesianGrid horizontal={false} stroke={C.grid} />
        <XAxis type="number" {...axis} axisLine={false} allowDecimals={false} />
        <YAxis type="category" dataKey={category} {...axis} width={150} tick={{ fill: "#c3c2b7", fontSize: 12 }} />
        <Tooltip {...tip} />
        <Legend iconType="square" iconSize={9} wrapperStyle={{ paddingTop: 6 }} />
        <Bar dataKey="passed" name="Pass" stackId="o" fill={C.pass} {...seg} maxBarSize={18} />
        <Bar dataKey="review" name="Needs review" stackId="o" fill={C.review} {...seg} maxBarSize={18} />
        <Bar dataKey="defective" name="Defective" stackId="o" fill={C.defective} {...seg} radius={[0, 3, 3, 0]} maxBarSize={18} />
      </BarChart>
    </ResponsiveContainer>
  );
}

export function SeverityBars({ data, height }: { data: { label: string; minor: number; major: number; critical: number }[]; height?: number }) {
  return (
    <ResponsiveContainer width="100%" height={height ?? Math.max(120, data.length * 30 + 50)}>
      <BarChart data={data} layout="vertical" margin={{ top: 4, right: 16, left: 8, bottom: 0 }} barCategoryGap="26%">
        <CartesianGrid horizontal={false} stroke={C.grid} />
        <XAxis type="number" {...axis} axisLine={false} allowDecimals={false} />
        <YAxis type="category" dataKey="label" {...axis} width={210} tick={{ fill: "#c3c2b7", fontSize: 12 }} />
        <Tooltip {...tip} />
        <Legend iconType="square" iconSize={9} wrapperStyle={{ paddingTop: 6 }} />
        <Bar dataKey="minor" name="Minor" stackId="s" fill={C.minor} {...seg} maxBarSize={16} />
        <Bar dataKey="major" name="Major" stackId="s" fill={C.major} {...seg} maxBarSize={16} />
        <Bar dataKey="critical" name="Critical" stackId="s" fill={C.critical} {...seg} radius={[0, 3, 3, 0]} maxBarSize={16} />
      </BarChart>
    </ResponsiveContainer>
  );
}

export function SimpleBars({ data, x, y, name, height = 220, color = C.s1, percent = false }: { data: any[]; x: string; y: string; name: string; height?: number; color?: string; percent?: boolean }) {
  const fmt = (v: number) => (percent ? `${(v * 100).toFixed(1)}%` : v.toLocaleString());
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ top: 8, right: 8, left: data.length > 8 ? 28 : -4, bottom: 0 }} barCategoryGap="25%">
        <CartesianGrid vertical={false} stroke={C.grid} />
        <XAxis dataKey={x} {...axis} interval={0} tick={{ fill: C.axis, fontSize: 10 }} angle={data.length > 8 ? -30 : 0} textAnchor={data.length > 8 ? "end" : "middle"} height={data.length > 8 ? 50 : 24} />
        <YAxis {...axis} axisLine={false} tickFormatter={fmt} domain={percent ? [0, 1] : undefined} />
        <Tooltip {...tip} formatter={(v: number) => [fmt(v), name]} />
        <Bar dataKey={y} name={name} fill={color} radius={[3, 3, 0, 0]} maxBarSize={32}>{data.map((_, i) => <Cell key={i} />)}</Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

export function RateLine({ data, x, y, name, height = 220 }: { data: any[]; x: string; y: string; name: string; height?: number }) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 8, right: 12, left: -4, bottom: 0 }}>
        <CartesianGrid vertical={false} stroke={C.grid} />
        <XAxis dataKey={x} {...axis} tickFormatter={(d: string) => (d.length === 10 ? d.slice(5) : d)} minTickGap={16} />
        <YAxis {...axis} axisLine={false} tickFormatter={(v: number) => `${(v * 100).toFixed(0)}%`} domain={[0, "auto"]} />
        <Tooltip {...tip} cursor={{ stroke: "#8d9096", strokeWidth: 1 }} formatter={(v: number) => [`${(v * 100).toFixed(1)}%`, name]} />
        <Line type="monotone" dataKey={y} name={name} stroke={C.s1} strokeWidth={2} dot={{ r: 3, fill: C.s1, stroke: C.surface, strokeWidth: 2 }} activeDot={{ r: 5 }} connectNulls />
      </LineChart>
    </ResponsiveContainer>
  );
}

/** Metric bars with 95% confidence whiskers (value 0..1). */
export function MetricBars({ data, height = 220 }: { data: { label: string; value: number; ci95?: [number, number] | null }[]; height?: number }) {
  const rows = data.map((d) => ({ ...d, err: d.ci95 ? [d.value - d.ci95[0], d.ci95[1] - d.value] : undefined }));
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={rows} layout="vertical" margin={{ top: 4, right: 44, left: 8, bottom: 0 }} barCategoryGap="30%">
        <CartesianGrid horizontal={false} stroke={C.grid} />
        <XAxis type="number" domain={[0, 1]} {...axis} axisLine={false} tickFormatter={(v: number) => `${Math.round(v * 100)}%`} />
        <YAxis type="category" dataKey="label" {...axis} width={170} tick={{ fill: "#c3c2b7", fontSize: 12 }} />
        <Tooltip {...tip} formatter={(v: number, _n, p: any) => [`${(v * 100).toFixed(1)}%${p.payload.ci95 ? `  (95% CI ${(p.payload.ci95[0] * 100).toFixed(1)}–${(p.payload.ci95[1] * 100).toFixed(1)}%)` : ""}`, "Measured"]} />
        <Bar dataKey="value" fill={C.s1} radius={[0, 3, 3, 0]} maxBarSize={14} label={{ position: "right", fill: "#c3c2b7", fontSize: 11, formatter: (v: number) => `${(v * 100).toFixed(1)}%` }}>
          <ErrorBar dataKey="err" direction="x" width={4} stroke="#f0efec" strokeWidth={1.2} />
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

export function ReliabilityChart({ bins, height = 220 }: { bins: { bin: string; n: number; mean_predicted: number; observed_rate: number }[]; height?: number }) {
  const data = [...bins].sort((a, b) => a.mean_predicted - b.mean_predicted);
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 8, right: 12, left: -8, bottom: 16 }}>
        <CartesianGrid stroke={C.grid} />
        <XAxis type="number" dataKey="mean_predicted" domain={[0, 1]} {...axis} tickFormatter={(v: number) => v.toFixed(1)} label={{ value: "Predicted P(defect)", position: "insideBottom", offset: -8, fill: C.axis, fontSize: 11 }} />
        <YAxis type="number" domain={[0, 1]} {...axis} axisLine={false} tickFormatter={(v: number) => v.toFixed(1)} />
        <Tooltip {...tip} cursor={{ stroke: "#8d9096", strokeWidth: 1 }} labelFormatter={(v: number) => `Predicted ${(+v).toFixed(2)}`} formatter={(v: number, n: string, p: any) => [n === "Perfect calibration" ? v.toFixed(2) : `${v.toFixed(2)}  (n=${p.payload.n})`, n]} />
        <Legend iconSize={9} wrapperStyle={{ paddingTop: 10 }} />
        <Line dataKey="mean_predicted" name="Perfect calibration" stroke="#8d9096" strokeDasharray="4 4" strokeWidth={1} dot={false} activeDot={false} />
        <Line dataKey="observed_rate" name="Observed defect rate" stroke={C.s1} strokeWidth={2} dot={{ r: 4, fill: C.s1, stroke: C.surface, strokeWidth: 2 }} />
      </LineChart>
    </ResponsiveContainer>
  );
}
