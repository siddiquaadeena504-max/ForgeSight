"use client";
import { ClipboardList } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Notice } from "@/components/ui";
import { useAuth } from "@/lib/auth";

export default function Login() {
  const { login, user } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (user) router.replace("/"); }, [user, router]);
  return (
    <div className="grid min-h-screen place-items-center px-4">
      <form className="card w-full max-w-sm p-6" onSubmit={async (e) => {
        e.preventDefault(); setBusy(true); setErr(null);
        try { await login(email.trim(), password); router.replace("/"); } catch (ex: any) { setErr(ex.message); } finally { setBusy(false); }
      }}>
        <div className="mb-5 flex items-center gap-2.5">
          <div className="grid h-9 w-9 place-items-center rounded bg-accentDim"><ClipboardList size={20} aria-hidden /></div>
          <div><div className="text-base font-semibold">ForgeSight</div><div className="text-xs text-muted">Manufacturing quality inspection</div></div>
        </div>
        <label className="label" htmlFor="email">Email</label>
        <input id="email" className="input mb-3" type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} />
        <label className="label" htmlFor="pw">Password</label>
        <input id="pw" className="input mb-4" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
        {err && <div className="mb-3"><Notice tone="error">{err}</Notice></div>}
        <button className="btn btn-primary w-full" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
      </form>
    </div>
  );
}
