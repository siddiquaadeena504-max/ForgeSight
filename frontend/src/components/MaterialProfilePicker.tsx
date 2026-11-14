"use client";
import type { Material } from "@/lib/api";
import { Field, Tag } from "./ui";

/** Material + inspection-profile selection shared by New / Live inspection. */
export default function MaterialProfilePicker({ materials, material, profile, onMaterial, onProfile }: {
  materials: Material[]; material: string; profile: string; onMaterial: (k: string) => void; onProfile: (k: string) => void;
}) {
  const m = materials.find((x) => x.key === material);
  const p = m?.profiles.find((x) => x.key === profile);
  return (
    <>
      <Field label="Material">
        <select className="input" value={material} onChange={(e) => { onMaterial(e.target.value); onProfile(""); }}>
          <option value="">Select material…</option>
          {materials.map((x) => <option key={x.key} value={x.key}>{x.name}</option>)}
        </select>
      </Field>
      <Field label="Inspection profile">
        <select className="input" value={profile} disabled={!m} onChange={(e) => onProfile(e.target.value)}>
          <option value="">Generic surface screening (unvalidated)</option>
          {m?.profiles.map((x) => <option key={x.key} value={x.key}>{x.name}</option>)}
        </select>
        <span className="mt-1.5 flex flex-wrap items-center gap-1.5 text-xs text-muted">
          {!m ? null : p ? (
            <>
              {p.validated ? <Tag tone="good">validated model</Tag> : <Tag tone="warn">not validated</Tag>}
              {p.requires_reference && <Tag tone="accent">needs golden reference image</Tag>}
              {p.product_category && <span>{p.product_category}</span>}
            </>
          ) : <><Tag tone="warn">screening only</Tag><span>Finds candidates for human review; never auto-passes.</span></>}
        </span>
      </Field>
    </>
  );
}
