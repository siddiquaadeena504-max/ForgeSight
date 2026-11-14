"use client";
import { useEffect, useState } from "react";
import { Card, Field, Notice, PageHeader, Spinner, Tag } from "@/components/ui";
import { api, fmtDate, type User } from "@/lib/api";
import { useApi, useAuth } from "@/lib/auth";

export default function SettingsPage() {
  const { user, can } = useAuth();
  const [tab, setTab] = useState("policy");
  const tabs = [["policy", "Decision policy"], ["system", "System"], ["account", "My account"], ...(can("admin") ? [["users", "Users & roles"], ["audit", "Audit log"]] : [])];
  return (
    <>
      <PageHeader title="Settings" sub={`Signed in as ${user?.email} (${user?.role}).`} />
      <div className="mb-4 flex gap-1 border-b border-line" role="tablist">{tabs.map(([k, l]) => (
        <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)} className={`-mb-px border-b-2 px-3 py-2 text-sm ${tab === k ? "border-accent text-ink" : "border-transparent text-muted hover:text-ink2"}`}>{l}</button>))}</div>
      {tab === "policy" && <Policy />}{tab === "system" && <System />}{tab === "account" && <Account />}{tab === "users" && <Users />}{tab === "audit" && <Audit />}
    </>
  );
}

function Policy() {
  const { can } = useAuth();
  const p = useApi<any>("/settings/policy");
  const [v, setV] = useState<any>(null);
  const [msg, setMsg] = useState<string | null>(null);
  useEffect(() => { if (p.data) setV(p.data); }, [p.data]);
  if (!v) return <Spinner />;
  const ro = !can("admin");
  const Row = ({ k, title, desc }: { k: string; title: string; desc: string }) => (
    <label className="flex cursor-pointer items-start gap-3 border-b border-line py-3">
      <input type="checkbox" className="mt-1 h-4 w-4 accent-[#3987e5]" checked={v[k]} disabled={ro} onChange={(e) => setV({ ...v, [k]: e.target.checked })} />
      <span><span className="block text-sm font-medium text-ink">{title}</span><span className="text-sm text-muted">{desc}</span></span>
    </label>);
  return (
    <Card title="Decision policy" className="max-w-3xl">
      <Row k="allow_unvalidated_pass" title="Allow automatic PASS without validation"
        desc="Off (recommended): a part can only be passed automatically by a profile whose pass decision was validated on defect-free held-out samples. On: profiles without that evidence may pass parts when they find nothing. This weakens the safety guarantee." />
      <Row k="review_on_quality_warn" title="Send images with quality warnings to review" desc="Off: only a failed quality gate (unusable image) forces review. On: warnings such as glare or low contrast also force review." />
      <div className="py-3"><Field label={`Detector disagreement that forces review: ${v.disagreement_delta}`} hint="When two calibrated detectors differ by at least this much in defect probability, the part goes to review.">
        <input type="range" min={0.1} max={1} step={0.05} disabled={ro} value={v.disagreement_delta} onChange={(e) => setV({ ...v, disagreement_delta: +e.target.value })} className="w-full accent-[#3987e5]" /></Field></div>
      {ro ? <Notice tone="info">Only administrators can change the policy.</Notice> : (
        <div className="flex items-center gap-3"><button className="btn btn-primary" onClick={async () => { try { await api("/settings/policy", { method: "PUT", json: v }); setMsg("Saved – applies to new inspections; change recorded in the audit log."); } catch (e: any) { setMsg(e.message); } }}>Save policy</button>
          {msg && <span className="text-sm text-muted">{msg}</span>}</div>)}
    </Card>
  );
}

function System() {
  const s = useApi<any>("/settings/system");
  if (!s.data) return <Spinner />;
  const d = s.data;
  const rows: [string, React.ReactNode][] = [["Inference device", d.gpu ? `${d.device} – ${d.gpu.name} (${d.gpu.memory_gb} GB)` : `${d.device} (${d.cpu_threads} threads, no GPU detected)`], ["PyTorch", d.torch], ["OpenCV", d.opencv],
    ["Database", d.database], ["Object storage", d.storage_backend], ["Environment", d.environment], ["Material identifier", d.material_identifier_installed ? "installed" : "not installed – material is always requested"],
    ["Upload limits", `${d.max_upload_mb} MB per image · ${d.max_video_mb} MB per video`]];
  return (
    <Card title="System" className="max-w-3xl">
      {d.default_secret_in_use && <div className="mb-3"><Notice tone="warn">The development signing key is in use. Set FS_SECRET_KEY before exposing this deployment.</Notice></div>}
      <dl className="grid grid-cols-[200px_1fr] gap-y-2 text-sm">{rows.map(([k, val]) => <div key={k} className="contents"><dt className="text-muted">{k}</dt><dd className="text-ink2">{val}</dd></div>)}</dl>
    </Card>
  );
}

function Account() {
  const [cur, setCur] = useState(""); const [nw, setNw] = useState(""); const [msg, setMsg] = useState<{ ok: boolean; t: string } | null>(null);
  return (
    <Card title="Change password" className="max-w-md">
      <form className="space-y-3" onSubmit={async (e) => { e.preventDefault(); try { await api("/auth/password", { json: { current_password: cur, new_password: nw } }); setMsg({ ok: true, t: "Password changed." }); setCur(""); setNw(""); } catch (ex: any) { setMsg({ ok: false, t: ex.message }); } }}>
        <Field label="Current password"><input className="input" type="password" autoComplete="current-password" required value={cur} onChange={(e) => setCur(e.target.value)} /></Field>
        <Field label="New password" hint="At least 10 characters."><input className="input" type="password" autoComplete="new-password" required minLength={10} value={nw} onChange={(e) => setNw(e.target.value)} /></Field>
        <button className="btn btn-primary">Update password</button>
        {msg && <Notice tone={msg.ok ? "good" : "error"}>{msg.t}</Notice>}
      </form>
    </Card>
  );
}

const ROLES = ["viewer", "inspector", "engineer", "admin"];
const ROLE_DESC: Record<string, string> = { viewer: "read dashboards, history and reports", inspector: "+ run inspections and review results", engineer: "+ datasets, models, profiles", admin: "+ users, policy, audit log, deletion" };
function Users() {
  const { user } = useAuth();
  const u = useApi<User[]>("/users");
  const [n, setN] = useState({ email: "", full_name: "", password: "", role: "inspector" });
  const [err, setErr] = useState<string | null>(null);
  const patch = async (id: number, body: any) => { try { await api(`/users/${id}`, { method: "PATCH", json: body }); u.reload(); } catch (e: any) { setErr(e.message); } };
  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_340px]">
      <Card pad={false} title="Users">
        <table className="w-full"><thead><tr>{["User", "Role", "Status", "Created", ""].map((h) => <th key={h} className="th">{h}</th>)}</tr></thead>
          <tbody>{u.data?.map((x) => (
            <tr key={x.id}><td className="td"><span className="text-ink">{x.full_name || x.email}</span><div className="text-[11px] text-muted">{x.email}</div></td>
              <td className="td"><select aria-label={`Role of ${x.email}`} className="input w-32 py-1" value={x.role} disabled={x.id === user?.id} onChange={(e) => patch(x.id, { role: e.target.value })}>{ROLES.map((r) => <option key={r}>{r}</option>)}</select></td>
              <td className="td">{x.is_active ? <Tag tone="good">active</Tag> : <Tag>disabled</Tag>}</td><td className="td whitespace-nowrap">{fmtDate(x.created_at)}</td>
              <td className="td text-right">{x.id !== user?.id && <button className="btn btn-sm" onClick={() => patch(x.id, { is_active: !x.is_active })}>{x.is_active ? "Disable" : "Enable"}</button>}</td></tr>))}</tbody></table>
        {err && <div className="p-3"><Notice tone="error">{err}</Notice></div>}
      </Card>
      <Card title="Add user">
        <form className="space-y-3" onSubmit={async (e) => { e.preventDefault(); setErr(null); try { await api("/users", { json: n }); setN({ email: "", full_name: "", password: "", role: "inspector" }); u.reload(); } catch (ex: any) { setErr(ex.message); } }}>
          <Field label="Email"><input className="input" type="email" required value={n.email} onChange={(e) => setN({ ...n, email: e.target.value })} /></Field>
          <Field label="Full name"><input className="input" value={n.full_name} onChange={(e) => setN({ ...n, full_name: e.target.value })} /></Field>
          <Field label="Initial password" hint="At least 10 characters."><input className="input" type="password" autoComplete="new-password" required minLength={10} value={n.password} onChange={(e) => setN({ ...n, password: e.target.value })} /></Field>
          <Field label="Role" hint={ROLE_DESC[n.role]}><select className="input" value={n.role} onChange={(e) => setN({ ...n, role: e.target.value })}>{ROLES.map((r) => <option key={r}>{r}</option>)}</select></Field>
          <button className="btn btn-primary w-full">Create user</button>
        </form>
      </Card>
    </div>
  );
}

function Audit() {
  const [action, setAction] = useState("");
  const [page, setPage] = useState(0);
  const a = useApi<{ total: number; items: any[] }>("/audit", { action, limit: 50, offset: page * 50 });
  return (
    <Card pad={false} title="Audit log" right={<select aria-label="Filter by area" className="input w-44 py-1" value={action} onChange={(e) => { setAction(e.target.value); setPage(0); }}>
      <option value="">All actions</option>{["auth", "inspection", "dataset", "model", "profile", "settings", "user", "report", "material"].map((x) => <option key={x} value={x + "."}>{x}</option>)}</select>}>
      <div className="overflow-x-auto"><table className="w-full"><thead><tr>{["Time", "User", "Action", "Entity", "Detail", "IP"].map((h) => <th key={h} className="th">{h}</th>)}</tr></thead>
        <tbody>{a.data?.items.map((x) => (
          <tr key={x.id}><td className="td whitespace-nowrap">{fmtDate(x.ts)}</td><td className="td">{x.user_email ?? "–"}</td><td className="td font-mono text-xs text-ink">{x.action}</td>
            <td className="td font-mono text-xs">{x.entity ? `${x.entity}:${String(x.entity_id).slice(0, 12)}` : ""}</td>
            <td className="td max-w-md truncate font-mono text-[11px] text-muted" title={JSON.stringify(x.detail)}>{x.detail ? JSON.stringify(x.detail) : ""}</td><td className="td text-xs">{x.ip}</td></tr>))}</tbody></table></div>
      <div className="flex items-center justify-between p-3 text-sm text-muted"><span>{a.data?.total.toLocaleString()} entries</span>
        <span className="flex gap-2"><button className="btn btn-sm" disabled={page === 0} onClick={() => setPage(page - 1)}>Previous</button><button className="btn btn-sm" disabled={(page + 1) * 50 >= (a.data?.total ?? 0)} onClick={() => setPage(page + 1)}>Next</button></span></div>
    </Card>
  );
}
