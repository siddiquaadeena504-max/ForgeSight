"use client";
import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import InspectionView from "@/components/InspectionView";
import { Notice, PageHeader, Spinner } from "@/components/ui";
import { api, type InspectionDetail } from "@/lib/api";

export default function InspectionPage() {
  const { id } = useParams<{ id: string }>();
  const [data, setData] = useState<InspectionDetail | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { api<InspectionDetail>(`/inspections/${id}`).then(setData).catch((e) => setErr(e.message)); }, [id]);
  return (
    <>
      <PageHeader title={`Inspection ${id.slice(0, 8)}`} sub={data ? `${data.filename ?? "image"} · ${data.material_key}` : undefined}
        right={<Link href="/history" className="btn btn-sm"><ArrowLeft size={12} />History</Link>} />
      {err ? <Notice tone="error">{err}</Notice> : !data ? <Spinner /> : <InspectionView data={data} onChange={setData} />}
    </>
  );
}
