# ForgeSight - universal AI manufacturing defect inspection platform

A working, profile-driven visual inspection platform: upload images or video (or point a camera at the line), and the engine
checks image quality, runs the detectors configured for that material, localizes and classifies defects, estimates severity,
and returns **pass**, **defective**, or **needs human review** - with the evidence for the decision.

It is built as a *platform*, not a single model: each material is inspected through an inspection profile (detectors +
decision rule), and a material without a validated model is screened and routed to a human instead of being guessed at.

> **Read this first - what is and is not validated.** Three profiles ship with models trained and measured on public
> datasets (ferrite magnetic tiles, bare PCBs, pavement cracks). Their measured results are in
> [`docs/MODEL_RESULTS.md`](docs/MODEL_RESULTS.md). The other nine material families have **no trained model**: they use a
> training-free screening detector whose candidates always go to human review until you collect data and fit a model in the
> app. Nothing reaches the 99.9% target and no accuracy figure in the UI or docs is estimated - see *Known limitations*.

## Contents

```
backend/            FastAPI service
  app/ml/           inspection engine: detectors, pipeline, metrics, calibration, drift, knowledge base
  app/api/          REST endpoints          app/services/   inspection, datasets, reports, jobs
  alembic/          database migrations     scripts/        benchmarks, YOLO training, benchmark replay
  tests/            automated tests (pytest)
frontend/           Next.js 15 + React 19 + TypeScript + Tailwind + Recharts (10 pages)
data/models/        model store: <name>/<version>/{model.pt, card.json}, profiles/, evaluations/
docs/               ARCHITECTURE.md, API.md, MODEL_RESULTS.md, TESTING.md
docker-compose.yml  Postgres + MinIO + API + web
```

## Quick start (local)

Prerequisites: Python 3.11+, Node 20+, PostgreSQL 14+ (or use SQLite for a quick look), git.

```bash
# 1. pretrained backbone + public validation datasets (GitHub)
./scripts/fetch_assets.sh
```

```bash
# 2. backend dependencies
pip install -r backend/requirements.txt -r backend/requirements-dev.txt
```

```bash
# 3. database (PostgreSQL)
psql -U postgres -c "CREATE USER forgesight WITH PASSWORD 'forgesight' CREATEDB" -c "CREATE DATABASE forgesight OWNER forgesight"
```

```bash
# 4. train + validate the shipped models (about 45 min on 4 CPU cores; minutes on a GPU). Writes data/models/
(cd backend && python scripts/benchmarks.py)
```

```bash
# 5. frontend dependencies and build
(cd frontend && npm install && npm run build)
```

```bash
# 6. start API (:8000, runs migrations + seeding) and UI (:3000)
./scripts/dev.sh
```

Open http://localhost:3000 and sign in with `admin@forgesight.local` / `ChangeMe!2026` (override with `FS_ADMIN_EMAIL` /
`FS_ADMIN_PASSWORD` before first start; change the password under Settings → My account).

Optional: `python backend/scripts/replay_benchmark.py` runs the held-out test images through the live pipeline so the
dashboards show real results (stored with `source = benchmark` and their ground truth).

No Postgres at hand? `FS_DATABASE_URL=sqlite:///./dev.db ./scripts/dev.sh` works for evaluation (tables are created
directly; migrations target Postgres).

Step 4 can be skipped: the platform then starts with screening-only profiles and you train models from your own data in
Dataset Management.

## Environment configuration

All backend settings are environment variables with the `FS_` prefix (`backend/app/config.py`); see `.env.example`.

| Variable | Default | Purpose |
|---|---|---|
| `FS_DATABASE_URL` | `postgresql+psycopg://forgesight:forgesight@localhost:5432/forgesight` | SQLAlchemy URL |
| `FS_SECRET_KEY` | development value | JWT + file-URL signing key. **Must be set in production** (startup fails otherwise) |
| `FS_ENV` | `development` | `production` enables the secret check |
| `FS_ADMIN_EMAIL`, `FS_ADMIN_PASSWORD` | see above | bootstrap admin, created only when the user table is empty |
| `FS_STORAGE_BACKEND` | `local` | `local` or `s3` |
| `FS_STORAGE_DIR` | `data/storage` | local object store |
| `FS_S3_ENDPOINT_URL`, `FS_S3_BUCKET`, `FS_S3_REGION`, `FS_S3_ACCESS_KEY`, `FS_S3_SECRET_KEY` | - | any S3-compatible store (MinIO, AWS S3, ...) |
| `FS_MODELS_DIR`, `FS_WEIGHTS_DIR` | `data/models`, `data/weights` | model store, pretrained backbone |
| `FS_DEVICE` | auto | force `cpu` / `cuda` / `mps` |
| `FS_ACCESS_TOKEN_MINUTES` | 480 | session length |
| `FS_MAX_UPLOAD_MB`, `FS_MAX_VIDEO_MB` | 25, 300 | upload limits |
| `FS_JOB_WORKERS` | 2 | background job threads |
| `FS_CORS_ORIGINS` | `http://localhost:3000` | only needed if the UI calls the API cross-origin |
| `BACKEND_URL` (frontend) | `http://127.0.0.1:8000` | where Next.js proxies `/api` |

## Deployment (Docker)

```bash
cp .env.example .env    # set POSTGRES_PASSWORD, S3_*, FS_SECRET_KEY, FS_ADMIN_PASSWORD
```

```bash
./scripts/fetch_assets.sh
```

```bash
docker compose up --build -d
```

Services: `db` (Postgres 16), `minio` (S3-compatible storage), `backend` (FastAPI, migrations on start), `frontend`
(Next.js standalone). The model store and backbone weights are mounted from `./data`. GPU hosts:

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up --build -d
```

To train the shipped models inside the container: `docker compose exec backend python scripts/benchmarks.py` (mount
`./data/external` into the backend service first).

Production checklist: terminate TLS in front of the frontend (the camera page needs HTTPS outside localhost), set a strong
`FS_SECRET_KEY`, change the bootstrap admin password, back up Postgres and the object store, keep one uvicorn worker per
container and scale with replicas (job pool and model cache are per process).

> The compose files were validated with `docker compose config` only. This build environment had no Docker daemon, so
> **the images have not been built or run**. Expect to fix small issues on first build.

## Using the platform

| Page | What it does |
|---|---|
| Overview | totals, pass / review / defective, trend, defect distribution, by material and batch, throughput, model summary |
| New Inspection | drag-and-drop images or video; material suggestion with manual override; quality gate; result workspace with zoom/pan, boxes, masks, heatmap, markers, before/after wipe; human review; PDF/CSV |
| Live Inspection | load a video (or start a camera) and watch each analysed frame with labelled boxes/masks and a status bar (mode, FPS, latency, OK / CHECK / NG counts); clickable list of flagged moments. Two detection modes: **learn normal from this footage** (any material, no trained model needed) or a trained inspection profile |
| Inspection History | filterable, searchable history; review queue sorted by uncertainty; CSV export |
| Defect Analysis | defect types by severity, by material, by batch, over time |
| Material Library | 13 material families (incl. leather), their profiles, validation status, imaging notes; profile calibration and thresholds |
| Dataset Management | datasets per material, upload, labels, boxes and masks, leakage-safe splits, COCO/YOLO export, incorrect predictions, model training |
| Model Performance | every stored evaluation with confidence intervals, calibration, confusion matrices, per-defect results, drift, production monitoring, model registry |
| Quality Reports | period PDF and CSV downloads |
| Settings | decision policy, system info, users and roles, audit log, password |

Adding a material with your own data: Dataset Management → New dataset → upload defect-free and defective images → Assign
splits → Train → Model Performance → Promote. The new profile makes calibrated three-way decisions if the validation and
test splits contained both good and defective images; otherwise it localizes candidates for review and says so.

### Testing a video of your own material (e.g. leather)

1. Live Inspection → *How to detect*: **Learn normal from this footage** → choose the material (e.g. *Leather and hides*).
2. Set *Defect-free footage at the start* to the number of seconds at the beginning of the video that show only good material.
3. **Analyse video** (MP4/H.264 or WebM). The first seconds teach the detector what normal looks like; every later frame is
   compared against it. Deviations are boxed and labelled, the status bar shows CLEAR* / CHECK, and flagged moments are
   listed with their timestamps and stored for review.

This mode needs no trained model, which is why it works on any material, and for the same reason it is **not a validated
inspector**: it marks candidates for a person. Its measured behaviour on a deliberately hard proxy (12 reference stills of
ferrite tiles, every frame a different part; `docs/learned_reference_check.json`) is 49% / 80% / 89% of defective frames
marked at 12% / 33% / 51% false flags for low / normal / high sensitivity. Continuous footage of one material under fixed
lighting should be easier, but that was **not measured, and no leather footage was available in this build environment**.
To get a validated leather inspector: collect good and defective leather images in Dataset Management, label, assign
splits, train, and promote - the app then reports its measured accuracy on your own held-out images.

Sample videos made from held-out public test images are in `data/samples/`.

## Documentation

* [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) - environment findings, design decisions, engine, data model, scaling path
* [`docs/API.md`](docs/API.md) - endpoint reference (also live at `/docs`)
* [`docs/MODEL_RESULTS.md`](docs/MODEL_RESULTS.md) - model cards and measured results
* [`docs/TESTING.md`](docs/TESTING.md) - test suite and results
* [`docs/DATA_AND_LICENSES.md`](docs/DATA_AND_LICENSES.md) - datasets, weights, licences, data requirements

## Known limitations

**Models and accuracy**
* Only 3 of 13 material families have validated models, each on one public dataset from one imaging setup. Results do not
  transfer to other products, cameras or lighting. Metals, plastics, wood, glass, textiles, leather, rubber, paper and
  composites have no trained model: use the learn-from-footage mode or the generic screening detector, both unvalidated.
* Leather: material entry, defect vocabulary and cause knowledge base only. No leather data was available, so nothing
  about leather detection quality has been measured.
* Magnetic-tile defect *type* classification is 71% accurate on the test split (detection itself is far stronger); small
  blowholes and cracks are confused with each other.
* The validated tile profile still sends about 43% of parts to human review at the shipped operating point.
* The 99.9% target is not met and cannot be verified with the available test sets (see `docs/MODEL_RESULTS.md`).
* Defect types covered by trained classifiers: the 5 magnetic-tile classes, 6 PCB classes and cracks. Dents, bubbles,
  misalignment, missing components, dimensional irregularities etc. are in the taxonomy and labelling tools but no shipped
  model detects them by name. Dimensional inspection (gauging against tolerances) is not implemented.
* The classical screening detector is weak: on magnetic tiles it flagged every image (AUROC 0.47), on cracks it reached
  pixel F1 0.18. It is a way to surface candidates, not an inspector.
* Backbone is MobileNetV2 because other pretrained weights were unreachable here. The Vision Transformer / timm path and
  Hugging Face models are wired but untested; no self-supervised pretraining is implemented.
* YOLO: training, registration and inference were smoke-tested end to end (2 epochs, 32 images, from scratch → unusable
  model, deleted). No trained YOLO model ships.
* In-app training fits anomaly models (PatchCore) only; segmentation and crop-classifier training run from scripts.
* The material identifier knows three imaging setups and rejects the rest as unknown; rejection of unseen materials was
  only spot-checked.
* Severity is rule-based; cause hypotheses are a static knowledge-base lookup.
* Size estimates in millimetres need a user-supplied scale; there is no camera calibration or lens-distortion correction.

**Platform**
* No GPU was available: all timings are CPU. Docker images were not built.
* Video analysis decodes in the browser, so the file must be a format the browser plays (MP4/H.264, WebM); other formats
  go through New Inspection (server-side decoding, results as a frame list rather than an overlay player). Counts are per
  frame, not per part - there is no object tracking.
* Live inspection sends browser frames over HTTP (5-10 analysed frames per second on this CPU); there is no industrial camera
  (GigE/RTSP) or PLC integration, and the browser camera path was verified with a simulated camera only.
* Background jobs run in the API process (thread pool); a restart fails running jobs.
* Analytics are computed by SQL aggregation on request; fine for the tens of thousands, not for millions of rows.
* Auth is local accounts with JWT; no SSO, no MFA, login lockout is in-memory and per process.
* The S3 backend is tested against an S3 emulator (moto), not against a real MinIO/AWS endpoint.
* SQLite is supported for tests and evaluation only.
