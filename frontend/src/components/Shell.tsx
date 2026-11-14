"use client";
import clsx from "clsx";
import { Activity, Boxes, Camera, ClipboardList, Database, FileText, Gauge, History, Layers, LogOut, ScanSearch, Settings } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";
import { useAuth } from "@/lib/auth";
import { Spinner } from "./ui";

const NAV = [
  { group: "Operate", items: [
    { href: "/", label: "Overview", Icon: Gauge },
    { href: "/inspect", label: "New Inspection", Icon: ScanSearch },
    { href: "/live", label: "Live Inspection", Icon: Camera },
    { href: "/history", label: "Inspection History", Icon: History },
  ] },
  { group: "Analyse", items: [
    { href: "/defects", label: "Defect Analysis", Icon: Activity },
    { href: "/reports", label: "Quality Reports", Icon: FileText },
  ] },
  { group: "Engineer", items: [
    { href: "/materials", label: "Material Library", Icon: Layers },
    { href: "/datasets", label: "Dataset Management", Icon: Database },
    { href: "/models", label: "Model Performance", Icon: Boxes },
    { href: "/settings", label: "Settings", Icon: Settings },
  ] },
];

export default function Shell({ children }: { children: React.ReactNode }) {
  const { user, loading, logout } = useAuth();
  const path = usePathname();
  const router = useRouter();
  const isLogin = path === "/login";
  useEffect(() => { if (!loading && !user && !isLogin) router.replace("/login"); }, [loading, user, isLogin, router]);
  if (isLogin) return <>{children}</>;
  if (loading || !user) return <div className="grid h-screen place-items-center"><Spinner /></div>;
  return (
    <div className="flex min-h-screen">
      <aside className="sticky top-0 hidden h-screen w-56 shrink-0 flex-col border-r border-line bg-panel md:flex">
        <div className="flex items-center gap-2 border-b border-line px-4 py-3.5">
          <div className="grid h-7 w-7 place-items-center rounded bg-accentDim"><ClipboardList size={16} aria-hidden /></div>
          <div>
            <div className="text-sm font-semibold leading-4 tracking-wide">ForgeSight</div>
            <div className="text-[10px] uppercase tracking-widest text-muted">Quality inspection</div>
          </div>
        </div>
        <nav className="flex-1 overflow-y-auto px-2 py-3" aria-label="Main">
          {NAV.map((g) => (
            <div key={g.group} className="mb-4">
              <div className="px-2 pb-1 text-[10px] font-medium uppercase tracking-widest text-muted">{g.group}</div>
              {g.items.map(({ href, label, Icon }) => {
                const active = href === "/" ? path === "/" : path === href || path.startsWith(href + "/") || (href === "/history" && path.startsWith("/inspections/"));
                return (
                  <Link key={href} href={href} aria-current={active ? "page" : undefined}
                    className={clsx("mb-0.5 flex items-center gap-2.5 rounded px-2 py-1.5 text-[13px]", active ? "bg-raised font-medium text-ink" : "text-ink2 hover:bg-raised/60 hover:text-ink")}>
                    <Icon size={15} className={active ? "text-accent" : "text-muted"} aria-hidden />
                    {label}
                  </Link>
                );
              })}
            </div>
          ))}
        </nav>
        <div className="border-t border-line px-3 py-3">
          <div className="truncate text-xs text-ink2" title={user.email}>{user.full_name || user.email}</div>
          <div className="mt-0.5 flex items-center justify-between">
            <span className="text-[10px] uppercase tracking-widest text-muted">{user.role}</span>
            <button onClick={logout} className="flex items-center gap-1 text-xs text-muted hover:text-ink"><LogOut size={12} aria-hidden />Sign out</button>
          </div>
        </div>
      </aside>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1 overflow-x-auto border-b border-line bg-panel px-2 py-2 md:hidden">
          {NAV.flatMap((g) => g.items).map(({ href, label }) => (
            <Link key={href} href={href} className={clsx("whitespace-nowrap rounded px-2 py-1 text-xs", (href === "/" ? path === "/" : path.startsWith(href)) ? "bg-raised text-ink" : "text-muted")}>{label}</Link>
          ))}
        </div>
        <main className="mx-auto max-w-[1500px] px-4 py-5 md:px-6">{children}</main>
      </div>
    </div>
  );
}
