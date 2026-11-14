# API reference

Base path `/api`. Interactive docs: `/docs` (Swagger) and `/redoc`; machine-readable schema: `/openapi.json`.

Authentication: `POST /api/auth/login` returns a bearer token; send `Authorization: Bearer <token>` on every other call.
Errors are JSON `{"detail": ...}`; validation errors (422) also carry an `errors` list. Roles: viewer < inspector < engineer < admin.

## auth

| Method | Path | Summary | Parameters / body |
|---|---|---|---|
| POST | `/api/auth/login` | Login | json: email*, password* |
| GET | `/api/auth/me` | Me |  |
| POST | `/api/auth/password` | Change Password | json: current_password*, new_password* |
| GET | `/api/users` | List Users |  |
| POST | `/api/users` | Create User | json: email*, full_name, password*, role* |
| PATCH | `/api/users/{user_id}` | Update User | user_id*; json: full_name, password, role, is_active |

## inspections

| Method | Path | Summary | Parameters / body |
|---|---|---|---|
| POST | `/api/inspections/identify` | Step 1-3 of the workflow: suggest material/profile and analyse image quality before inspecting. | form: file* |
| POST | `/api/inspections` | Create Inspection | form: file*, reference, material_key, profile_key, product_id, batch_id, mm_per_pixel, material_overridden, material_from_suggestion |
| GET | `/api/inspections` | List Inspections | outcome; material; batch; source; review_status; search; date_from; date_to; job_id; defect_type; profile; sort; limit; offset |
| POST | `/api/inspections/video` | Create Video Inspection | form: file*, material_key, profile_key, batch_id, product_id, every_seconds, max_frames |
| GET | `/api/jobs/{job_id}` | Get Job | job_id* |
| GET | `/api/jobs` | List Jobs | kind |
| GET | `/api/inspections/{inspection_id}` | Get Inspection | inspection_id* |
| DELETE | `/api/inspections/{inspection_id}` | Delete Inspection | inspection_id* |
| POST | `/api/inspections/{inspection_id}/review` | Human disposition. The AI outcome is preserved; `final_outcome` records the inspector's decision. | inspection_id*; json: final_outcome*, notes, defects, missed_defects |
| GET | `/api/taxonomy` | Taxonomy |  |

## materials & profiles

| Method | Path | Summary | Parameters / body |
|---|---|---|---|
| GET | `/api/materials` | List Materials |  |
| POST | `/api/materials` | Create Material | json: name*, family, description, imaging_notes, common_defects |
| GET | `/api/profiles` | List Profiles | material |
| PATCH | `/api/profiles/{key}` | Update Profile | key*; json: name, product_category, mm_per_pixel, clear_calibration, t_low, t_high, region_confident, severity, is_active |

## datasets

| Method | Path | Summary | Parameters / body |
|---|---|---|---|
| GET | `/api/datasets` | List Datasets | material |
| POST | `/api/datasets` | Create Dataset | json: name*, material_key*, description, val_fraction, test_fraction |
| GET | `/api/datasets/{dataset_id}` | Get Dataset | dataset_id* |
| DELETE | `/api/datasets/{dataset_id}` | Delete Dataset | dataset_id* |
| POST | `/api/datasets/{dataset_id}/images` | Upload Images | dataset_id*; form: files*, label, group_key |
| GET | `/api/datasets/{dataset_id}/images` | List Images | dataset_id*; split; label; defect_type; limit; offset |
| PATCH | `/api/datasets/{dataset_id}/images/{image_id}` | Update Image | dataset_id*; image_id*; json: label, group_key, annotations |
| DELETE | `/api/datasets/{dataset_id}/images/{image_id}` | Delete Image | dataset_id*; image_id* |
| POST | `/api/datasets/{dataset_id}/split` | Split Dataset | dataset_id* |
| GET | `/api/datasets/{dataset_id}/leakage` | Dataset Leakage | dataset_id* |
| GET | `/api/datasets/{dataset_id}/export` | Export Dataset | dataset_id*; format |
| POST | `/api/datasets/{dataset_id}/from-inspection` | Active learning: a human-reviewed inspection becomes a labelled training example. | dataset_id*; json: inspection_id* |

## models

| Method | Path | Summary | Parameters / body |
|---|---|---|---|
| GET | `/api/models` | List Models |  |
| GET | `/api/evaluations` | List Evaluations |  |
| POST | `/api/models/train` | Train Model | json: dataset_id*, name* |
| POST | `/api/models/{model_id}/promote` | Candidate -> production. For in-app anomaly models this also creates/updates the inspection profile that uses the model. | model_id*; json: profile_name |
| POST | `/api/models/{model_id}/archive` | Archive Model | model_id* |
| GET | `/api/monitoring/production` | What happened to AI decisions in production: human agreement, and - where ground truth exists - measured errors. |  |
| GET | `/api/monitoring/drift` | PSI of recent detector scores / image brightness against the validation-time reference of each profile. | window |

## analytics

| Method | Path | Summary | Parameters / body |
|---|---|---|---|
| GET | `/api/analytics/overview` | Overview | days; material; date_from; date_to |

## reports

| Method | Path | Summary | Parameters / body |
|---|---|---|---|
| GET | `/api/reports/inspections/{inspection_id}.pdf` | Inspection Pdf | inspection_id* |
| GET | `/api/reports/inspections/{inspection_id}.csv` | Inspection Csv | inspection_id* |
| GET | `/api/reports/inspections.csv` | Inspections Csv | outcome; material; batch; source; date_from; date_to |
| GET | `/api/reports/defects.csv` | Defects Csv | outcome; material; batch; source; date_from; date_to |
| GET | `/api/reports/quality.pdf` | Quality Pdf | days; material; date_from; date_to |

## live

| Method | Path | Summary | Parameters / body |
|---|---|---|---|
| POST | `/api/live/reference` | Learn the normal appearance of a material from 6-60 defect-free frames (for materials without a trained model). | form: files* |
| POST | `/api/live/frame` | Inspect one camera frame. By default only frames that are not a clean PASS are stored (and enter the review queue). | form: file*, material_key, profile_key, batch_id, save, session_id, sensitivity |

## settings

| Method | Path | Summary | Parameters / body |
|---|---|---|---|
| GET | `/api/settings/policy` | Read Policy |  |
| PUT | `/api/settings/policy` | Write Policy | json: allow_unvalidated_pass*, review_on_quality_warn*, disagreement_delta* |
| GET | `/api/settings/system` | System |  |
| GET | `/api/audit` | Audit Log | action; user_email; limit; offset |

## system

| Method | Path | Summary | Parameters / body |
|---|---|---|---|
| GET | `/api/health` | Health |  |

`*` = required.
