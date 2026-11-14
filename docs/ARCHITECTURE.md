# Architecture and design decisions

## 1. What was available when this was built

| Resource | Finding | Consequence |
|---|---|---|
| GPU | none (4 CPU cores, 15 GB RAM) | Small backbones, fixed input sizes, CPU-feasible training. Device is auto-selected (`cuda` > `mps` > `cpu`), so the same code uses a GPU when present. |
| Pretrained weights | Hugging Face and pytorch.org were unreachable; GitHub was reachable | Backbone = ImageNet MobileNetV2 (checkpoint from `d-li14/mobilenetv2.pytorch`, Apache-2.0). ResNet / ViT backbones are wired through `timm:<name>` but were **not exercised** here. |
| Datasets | Public datasets on GitHub only | Magnetic Tile (ceramics), DeepPCB (electronics), CrackForest (construction). MVTec AD, NEU, AITEX, Kolektor etc. could not be fetched. |
| Docker | CLI present, no daemon | Compose files are syntax-validated (`docker compose config`) but the images were **not built or run** here. |
| PostgreSQL 16 | available | The app was developed and run against real Postgres with Alembic migrations. |

## 2. System overview

```
 Browser (Next.js 15 / React 19 / Tailwind / Recharts)
    │  /api/* proxied by Next rewrites, JWT bearer, signed file URLs
    ▼
 FastAPI ── auth + RBAC + audit ── Pydantic validation
    ├── inspections ─► InspectionEngine ─► detectors (per profile)
    ├── datasets    ─► pHash / leakage groups / splits / export
    ├── models      ─► registry, evaluations, drift, production monitoring
    ├── jobs        ─► thread pool: video inspection, PatchCore fitting
    ├── reports     ─► PDF (ReportLab) / CSV
    ▼                         ▼                         ▼
 PostgreSQL (SQLAlchemy 2,   Object storage            Model store on disk
 Alembic migrations)         (local dir or S3/MinIO)   data/models/<name>/<version>/{model.pt, card.json}
```

## 3. The inspection engine (`backend/app/ml`)

**No single model inspects everything.** A material is inspected through an *inspection profile*: a list of detectors
plus a decision rule. Profiles are data (JSON in the DB), so adding a material means adding a profile, not code.

| Stage | Module | Notes |
|---|---|---|
| 1. Material / profile | `material_id.py` | Nearest-prototype suggestion with an "unknown" reject. The operator can always override; an unknown material is *requested*, never guessed. |
| 2. Image quality | `quality.py` | Resolution, exposure, glare, contrast, sharpness, lighting uniformity. A failed gate forces human review. |
| 3. Detection | `detectors/` | `classical` (training-free OpenCV screening), `patchcore` (anomaly detection, needs only good samples), `segnet` (supervised segmentation + per-pixel class), `refdiff` (golden-template comparison + CNN crop classifier), `yolo` (Ultralytics adapter). |
| 4. Fusion | `pipeline.py::_merge_regions` | Overlapping regions from different detectors become one finding carried by the most specific detector; agreement is recorded. |
| 5. Typing | detector or `_heuristic_type` | A region no trained classifier named gets a *shape description* ("linear mark", "dark spot") flagged `type_source=heuristic`. |
| 6. Severity | `severity.py` | Transparent rules on area, extent, calibrated length and defect criticality; overridable per profile. The rationale is stored with every finding. |
| 7. Decision | `pipeline.py::_decide` | Three-way: pass / review / defective (below). |
| 8. Knowledge | `knowledge.py` | Cause hypotheses and recommended actions are a table lookup by (defect type, material family). They are stored and displayed separately from observations and are empty when the type is not established. |

### Decision modes

* **fusion** - a logistic combination of detector scores, fitted on the validation split, gives a calibrated P(defect).
  `p <= t_low` passes, `p >= t_high` rejects, anything in between goes to review. Thresholds are chosen on validation so
  that no validation defect is passed and no validation good is rejected. Strong disagreement between detectors also forces review.
* **regions** - for detectors validated at defect level only. A confident, model-classified finding means *defective*.
  "Nothing found" becomes *pass* only if the profile was validated on defect-free samples; otherwise it is *review*.
* **screening** - unvalidated profiles (every material without a trained model). Never passes or fails automatically.

Additional safety rules: a detector that throws forces review (a broken model must not look like "no defects"); a wrong or
unregistered golden template is detected and reported instead of producing an empty result; hand-editing the thresholds of a
validated profile removes its *validated* flag.

## 4. Accuracy and reliability engineering

* Metrics (`metrics.py`): precision, recall, F1, FPR, FNR, AUROC, ECE + reliability bins, per-class and per-defect tables,
  pixel metrics, triage report (escapes, false rejects, review rate). Rates carry Wilson 95% intervals.
* Evaluation records are written by `scripts/benchmarks.py` (or the in-app training job) at evaluation time and stored with
  dataset, split and sample size. The dashboard only renders stored records; there are no hard-coded numbers.
* Splits are deterministic hash splits by group; exact duplicates across splits are dropped; test data is never used for
  fitting, calibration or threshold selection.
* Cross-validation: 5-fold image-level AUROC for the anomaly model.
* Drift: PSI of recent detector scores and image brightness against validation-time deciles.
* Production monitoring: human-audit agreement, and measured errors wherever ground truth exists.
* **99.9% target:** treated as an engineering target, not a claim. See `docs/MODEL_RESULTS.md` for what was measured and
  why the available test sets cannot demonstrate 99.9% even in principle.

## 5. Data model (13 tables)

`users`, `audit_logs`, `materials`, `inspection_profiles`, `model_versions`, `evaluation_runs`, `inspections`, `defects`,
`datasets`, `dataset_images`, `annotations`, `jobs`, `settings`. The AI outcome (`inspections.outcome`) is immutable; a human
disposition is stored beside it (`final_outcome`, `review_status`), so AI-vs-human agreement stays auditable.

## 6. Dataset management and active learning

* Upload labelled images; exact duplicates (SHA-256) are refused.
* Leakage groups = explicit part keys ∪ perceptual-hash near-duplicates (union-find). A whole group goes to one split.
* Boxes and polygon masks are drawn in the browser; export as COCO or YOLO.
* Active learning loop: review queue sorted by uncertainty → inspector confirms / rejects / corrects → reviewed inspection
  is added to a dataset as a labelled example (unreviewed model output is refused) → re-assign splits → refit → candidate
  model with its own test metrics → promote.

## 7. Security

JWT (HS256) bearer auth, bcrypt password hashing, login lockout, four roles (viewer < inspector < engineer < admin) enforced
per endpoint, Pydantic validation on every input, upload type/size limits, images served only through short-lived
HMAC-signed URLs, path-traversal-safe storage keys, audit log of security- and quality-relevant actions, production refuses
to start with the development secret.

## 8. Scaling path (designed for, not built)

| Concern | MVP | Enterprise step |
|---|---|---|
| Background work | in-process thread pool + `jobs` table | swap `services/jobs.py::submit` for Celery/Arq workers (handlers keep their signature) |
| Inference | in the API process | dedicated GPU inference service (TorchServe / Triton); export detectors to ONNX / TensorRT |
| Analytics | SQL aggregates on OLTP tables | materialized views / warehouse |
| Live inspection | browser frames over HTTP | edge agent with GigE/RTSP capture and hardware trigger, results over MQTT/OPC UA |
| Auth | local users | OIDC / SAML SSO, per-site tenancy |
| Rate limiting | login lockout only | gateway-level rate limits |
