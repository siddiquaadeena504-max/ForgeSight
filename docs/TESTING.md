# Testing and validation

## Automated tests (`backend/tests`, pytest)

```bash
cd backend && python -m pytest tests -q
```

The suite runs the real application (FastAPI `TestClient`) against a throw-away SQLite database and storage directory, with
background jobs executed inline. Tests that need the trained public-dataset models are skipped when those are absent.

| Area | What is asserted |
|---|---|
| Metrics | confusion counts and rates, Wilson intervals (50/50 correct does not show 99.9%), AUROC undefined for one class, ECE, triage escapes / false rejects, multiclass + pixel reports |
| Calibration | Platt scaling separates classes; review band yields zero validation escapes and false rejects; overlapping classes go to review |
| Quality gate | dark, tiny and glare images are flagged; normal texture passes |
| Severity / knowledge | rule thresholds, structural floor, calibrated length; **no cause hypotheses for unclassified regions** |
| Engine safety | unvalidated profile never auto-passes or auto-fails; policy override works and is labelled; a broken detector forces review; a failed quality gate overrides an automatic outcome; pixel sizes are not reported as millimetres without a scale |
| Drift | PSI stable vs. shifted distributions; insufficient data returns no value |
| Auth / RBAC | 401 without or with a bad token, login lockout after repeated failures, role checks on every write path, input validation errors, self-demotion blocked |
| Uploads | wrong content type (415), corrupt image (422), unknown material (404), invalid scale (422) |
| Inspection workflow | unknown material is requested rather than guessed; signed file URLs work and tampered/expired ones are rejected; list filters; human review (reject, correct, add missed defect); PDF and CSV reports contain the reviewed data |
| Golden-reference profile | suggestion of the PCB profile; missing reference → review; real pair → defective with model-classified findings in mm; identical pair → no findings but PASS withheld; profile/material mismatch rejected |
| Live and video | frame endpoint with the three storage modes; a generated MP4 is sampled and inspected by the background job; a corrupt video fails the job cleanly |
| Datasets | duplicate refusal, near-duplicate and serial-number grouping, deterministic leakage-free splits, annotation validation (box + polygon), COCO and YOLO export contents |
| Training loop | training refused before splits exist; PatchCore fit on train-good only; test metrics reported; candidate → promote creates a calibrated profile; archive blocked while in use; active learning refuses unreviewed output and accepts reviewed inspections; hand-edited thresholds void the validated flag |
| Analytics / audit | totals reconcile across breakdowns; audit trail contains the expected actions |

## Browser tests (Playwright, Chromium)

Executed against the production build of the UI and the API on PostgreSQL:

* sign-in failure and success; all ten pages render without console or page errors
* New Inspection: three PCB images with three references paired by file name → three results; layer toggles, zoom, pan, before/after wipe
* Live Inspection with Chromium's simulated camera: frames inspected at the set interval, overlays drawn, flagged frames stored
* dataset creation, upload, split assignment, annotation dialog, model training job, promotion (see results below)

## Model validation

`backend/scripts/benchmarks.py` trains and evaluates the shipped models; results are in `docs/MODEL_RESULTS.md` and the
Model Performance page. `backend/scripts/replay_benchmark.py` then replays the held-out test images through the live API
pipeline, which is what the production-monitoring table reports.

## Results of the last run

* **pytest:** `34 passed in 15.52s` (34 tests: 16 engine/metric unit tests, 15 API integration tests, 3 storage tests incl. S3 against an emulator).
* **Browser (Chromium, production build, PostgreSQL):** all ten pages load without console or page errors.
  * New Inspection: 3 PCB images + 3 templates paired by file name → 3 results (9 / 7 / 7 defects found, all *defective*).
  * Video analysis, trained crack profile: a 12 s video built from held-out CrackForest test photos → 24 analysed frames, 24 NG, 70 crack regions, about 70 ms per frame on CPU.
  * Video analysis, learn-from-footage mode: a tile video (6 s defect-free lead-in, then 8 good / 8 defective parts alternating) → 4 of 8 defective parts marked, 1 of 8 good parts falsely marked. Consistent with the measured rates in `docs/learned_reference_check.json`.
  * Live camera path with Chromium's simulated camera: frames captured at the set interval, analysed, overlays drawn, flagged frames stored.
  * Dataset Management: 223 uploads (3 exact duplicates refused), splits over 198 leakage groups (20 near-duplicate groups kept together), box + polygon labelling, in-app training → candidate model with test AUROC 0.879 (n = 48), promotion to a production profile.
* **Benchmark replay through the live pipeline:** 427 held-out test images inspected and stored with ground truth; see Model Performance → Production monitoring.
* **Bugs found by these tests and fixed:** PDF report crashed on inspector-added defects; quality gate failed valid binarized PCB images; a wrong golden template silently produced "0 findings"; video "view frames" link was unclickable; one reference image was applied to every upload; defect-type head collapsed onto large defect classes (39% → 71% after class-balanced loss); live mode ran inference twice for stored frames.
* **Not run:** Docker image builds (no daemon available), GPU execution, real camera hardware, real S3/MinIO endpoint, load testing.
