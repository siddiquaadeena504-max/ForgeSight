"use client";

export class ApiError extends Error {
  status: number;
  detail: unknown;
  constructor(status: number, message: string, detail?: unknown) {
    super(message);
    this.status = status;
    this.detail = detail;
  }
}

const TOKEN_KEY = "fs_token";
export const getToken = () => (typeof window === "undefined" ? null : window.localStorage.getItem(TOKEN_KEY));
export const setToken = (t: string | null) => (t ? window.localStorage.setItem(TOKEN_KEY, t) : window.localStorage.removeItem(TOKEN_KEY));

async function parseError(res: Response): Promise<ApiError> {
  let detail: unknown = null;
  let msg = `Request failed (${res.status})`;
  try {
    const body = await res.json();
    detail = body.detail ?? body;
    if (typeof detail === "string") msg = detail;
    else if (detail && typeof detail === "object" && "message" in (detail as Record<string, unknown>)) msg = String((detail as Record<string, unknown>).message);
  } catch {
    /* non-JSON error body */
  }
  return new ApiError(res.status, msg, detail);
}

export async function api<T = any>(path: string, opts: { method?: string; json?: unknown; form?: FormData; params?: Record<string, unknown> } = {}): Promise<T> {
  const headers: Record<string, string> = {};
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  let body: BodyInit | undefined;
  if (opts.json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.json);
  } else if (opts.form) body = opts.form;
  const qs = opts.params
    ? "?" + Object.entries(opts.params).filter(([, v]) => v !== undefined && v !== null && v !== "").map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`).join("&")
    : "";
  const res = await fetch(`/api${path}${qs}`, { method: opts.method ?? (body ? "POST" : "GET"), headers, body });
  if (res.status === 401 && !path.startsWith("/auth/login")) {
    setToken(null);
    if (typeof window !== "undefined" && window.location.pathname !== "/login") window.location.href = "/login";
    throw new ApiError(401, "Session expired");
  }
  if (!res.ok) throw await parseError(res);
  if (res.status === 204) return undefined as T;
  return res.json();
}

/** Authenticated file download (PDF/CSV/ZIP) -> triggers a browser save. */
export async function download(path: string, params: Record<string, unknown> = {}, fallbackName = "download") {
  const token = getToken();
  const qs = Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== "").map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`).join("&");
  const res = await fetch(`/api${path}${qs ? "?" + qs : ""}`, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
  if (!res.ok) throw await parseError(res);
  const blob = await res.blob();
  const name = /filename="([^"]+)"/.exec(res.headers.get("Content-Disposition") ?? "")?.[1] ?? fallbackName;
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

export type Outcome = "pass" | "review" | "defective";
export type Role = "viewer" | "inspector" | "engineer" | "admin";
export const ROLE_RANK: Record<Role, number> = { viewer: 0, inspector: 1, engineer: 2, admin: 3 };

export interface User { id: number; email: string; full_name: string; role: Role; is_active: boolean; created_at: string }
export interface Finding {
  id: number; idx: number; defect_type: string; label: string; category: string; type_source: "model" | "heuristic" | "human"; type_confidence: number | null;
  confidence: number; confidence_basis: string; bbox: [number, number, number, number]; polygon: [number, number][]; centroid: [number, number];
  location: string; area_ratio: number; dimensions: { length_px: number; width_px: number; area_px: number; calibrated: boolean; length_mm?: number; width_mm?: number; area_mm2?: number };
  severity: { level: "minor" | "major" | "critical"; score: number; rationale: string }; sources: string[]; detector_scores: Record<string, number>; agreement: number;
  class_probs?: Record<string, number> | null; cause_hypotheses: string[]; recommended_action: string; qc_status: string; human_type: string | null; reviewed_by: string | null;
}
export interface InspectionRow {
  id: string; created_at: string; created_by: string | null; product_id: string | null; batch_id: string | null; filename: string | null; material_key: string;
  material_source: string; profile_key: string | null; source: string; job_id: string | null; frame_index: number | null; outcome: Outcome | null; final_outcome: Outcome | null;
  p_defect: number | null; quality_status: string | null; defect_count: number; max_severity: string | null; processing_ms: number | null; review_status: string | null;
  reviewed_by: string | null; reviewed_at: string | null; ground_truth: string | null; thumb_url: string | null;
}
export interface QualityCheck { name: string; value: number; unit: string; status: "ok" | "warn" | "fail"; message: string }
export interface Quality { status: "ok" | "warn" | "fail"; score: number; width: number; height: number; checks: QualityCheck[] }
export interface Decision {
  outcome: Outcome; mode: string; p_defect: number | null; per_detector_probability: Record<string, number>; thresholds: { t_low?: number; t_high?: number };
  validated: boolean; image_level_validated: boolean; evidence: string | null; reasons: string[];
}
export interface InspectionDetail extends InspectionRow {
  summary: { profile_key: string | null; profile_name: string | null; material: string; image: { width: number; height: number }; quality: Quality; decision: Decision;
    mm_per_pixel: number | null; detectors: { name: string; kind: string; model_version: string | null; validated: boolean; image_score: number | null; regions: number; latency_ms: number; note?: string }[];
    errors: string[]; processing_ms: number };
  material_suggestion: any; review_notes: string | null; image_url: string; annotated_url: string; heatmap_url: string | null; reference_url: string | null; defects: Finding[];
}
export interface Profile {
  key: string; material_key: string; name: string; product_category: string; builtin: boolean; requires_reference: boolean; mm_per_pixel: number | null;
  detectors: { type: string; model?: string; version?: string }[]; decision: any; validated: boolean; image_level_validated: boolean; updated_at: string;
}
export interface Material {
  key: string; name: string; family: string; description: string; imaging_notes: string; is_custom: boolean; common_defects: { type: string; label: string }[];
  profiles: Profile[]; coverage: "validated" | "screening_only"; inspections: number; datasets: number; production_models: number;
}

export const effectiveOutcome = (i: { outcome: Outcome | null; final_outcome: Outcome | null }): Outcome => i.final_outcome ?? i.outcome ?? "review";
export const pct = (v: number | null | undefined, digits = 1) => (v === null || v === undefined ? "–" : `${(v * 100).toFixed(digits)}%`);
export const fmtDate = (iso: string | null | undefined) => (iso ? new Date(iso).toLocaleString(undefined, { year: "numeric", month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit" }) : "–");
export const num = (v: number | null | undefined) => (v === null || v === undefined ? "–" : v.toLocaleString());
