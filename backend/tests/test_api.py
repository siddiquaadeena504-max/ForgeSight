import io
import json
import zipfile

import cv2
import numpy as np

from .conftest import EXTERNAL, jpg, needs_mt, needs_pcb, png, texture


def img_file(img, name="part.jpg"):
    return (name, jpg(img), "image/jpeg")


# ------------------------------------------------------------------ auth / RBAC / validation
def test_health_and_auth_required(client):
    assert client.get("/api/health").json() == {"status": "ok"}
    assert client.get("/api/inspections").status_code == 401
    assert client.get("/api/inspections", headers={"Authorization": "Bearer nonsense"}).status_code == 401


def test_login_failure_and_lockout(client):
    for _ in range(8):
        assert client.post("/api/auth/login", json={"email": "ghost@test.local", "password": "x"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": "ghost@test.local", "password": "x"}).status_code == 429


def test_rbac(client, users):
    files = {"file": img_file(texture(1))}
    assert client.post("/api/inspections", headers=users["viewer"], files=files, data={"material_key": "metals"}).status_code == 403
    assert client.get("/api/inspections", headers=users["viewer"]).status_code == 200
    assert client.post("/api/datasets", headers=users["inspector"], json={"name": "x1", "material_key": "metals"}).status_code == 403
    assert client.get("/api/users", headers=users["engineer"]).status_code == 403
    assert client.get("/api/audit", headers=users["engineer"]).status_code == 403
    assert client.put("/api/settings/policy", headers=users["engineer"], json={"allow_unvalidated_pass": True, "review_on_quality_warn": False,
                                                                              "disagreement_delta": 0.6}).status_code == 403


def test_user_validation(client, admin):
    r = client.post("/api/users", headers=admin, json={"email": "bad", "password": "short", "role": "root"})
    assert r.status_code == 422 and "errors" in r.json()
    assert client.post("/api/users", headers=admin, json={"email": "viewer@test.local", "password": "Password!2026", "role": "viewer"}).status_code in (201, 409)
    me = client.get("/api/auth/me", headers=admin).json()
    assert client.patch(f"/api/users/{me['id']}", headers=admin, json={"is_active": False}).status_code == 400


def test_upload_validation(client, users):
    h = users["inspector"]
    r = client.post("/api/inspections", headers=h, files={"file": ("x.txt", b"hello", "text/plain")}, data={"material_key": "metals"})
    assert r.status_code == 415
    r = client.post("/api/inspections", headers=h, files={"file": ("x.jpg", b"not an image", "image/jpeg")}, data={"material_key": "metals"})
    assert r.status_code == 422
    r = client.post("/api/inspections", headers=h, files={"file": img_file(texture(1))}, data={"material_key": "unobtainium"})
    assert r.status_code == 404
    r = client.post("/api/inspections", headers=h, files={"file": img_file(texture(1))}, data={"material_key": "metals", "mm_per_pixel": "-1"})
    assert r.status_code == 422


# ------------------------------------------------------------------ inspection workflow
def test_unknown_material_is_requested_not_guessed(client, users):
    r = client.post("/api/inspections", headers=users["inspector"], files={"file": img_file(texture(3))})
    assert r.status_code == 422
    d = r.json()["detail"]
    assert d["code"] == "material_required" and d["suggestion"]["known"] is False


def test_generic_inspection_review_and_reports(client, users):
    h = users["inspector"]
    r = client.post("/api/inspections", headers=h, files={"file": img_file(texture(10, defect="blob"))},
                    data={"material_key": "metals", "product_id": "SN-001", "batch_id": "B-7", "mm_per_pixel": "0.05"})
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["outcome"] == "review" and d["final_outcome"] is None and d["review_status"] == "pending"
    assert d["defect_count"] >= 1 and d["summary"]["decision"]["validated"] is False
    f = d["defects"][0]
    assert f["type_source"] == "heuristic" and f["cause_hypotheses"] == [] and f["dimensions"]["calibrated"] and f["dimensions"]["length_mm"] > 0
    for k in ("image_url", "annotated_url", "heatmap_url", "thumb_url"):
        fr = client.get(d[k])
        assert fr.status_code == 200 and len(fr.content) > 500, k
    assert client.get(d["image_url"].replace("sig=", "sig=0")).status_code == 403  # tampered signature
    assert client.get(d["image_url"].split("?")[0] + "?exp=1&sig=abc").status_code == 403

    # list + filters
    lst = client.get("/api/inspections", headers=h, params={"batch": "B-7", "outcome": "review", "search": "SN-0"}).json()
    assert lst["total"] == 1 and lst["items"][0]["id"] == d["id"]
    assert client.get("/api/inspections", headers=h, params={"outcome": "bogus"}).status_code == 422

    # human review: reject AI finding 1 as false alarm, add a missed one, final = defective
    body = {"final_outcome": "defective", "notes": "Confirmed pit near centre", "defects": [{"id": f["id"], "qc_status": "corrected", "human_type": "pore"}],
            "missed_defects": [{"defect_type": "scratch", "bbox": [5, 5, 40, 8]}]}
    assert client.post(f"/api/inspections/{d['id']}/review", headers=users["viewer"], json=body).status_code == 403
    rv = client.post(f"/api/inspections/{d['id']}/review", headers=h, json=body)
    assert rv.status_code == 200, rv.text
    rv = rv.json()
    assert rv["outcome"] == "review" and rv["final_outcome"] == "defective" and rv["review_status"] == "corrected"
    assert any(x["type_source"] == "human" for x in rv["defects"]) and rv["defects"][0]["human_type"] == "pore"
    bad = client.post(f"/api/inspections/{d['id']}/review", headers=h, json={"final_outcome": "pass", "defects": [{"id": 999999, "qc_status": "confirmed"}]})
    assert bad.status_code == 422

    # reports
    pdf = client.get(f"/api/reports/inspections/{d['id']}.pdf", headers=h)
    assert pdf.status_code == 200 and pdf.content[:5] == b"%PDF-" and len(pdf.content) > 20000
    csv_ = client.get(f"/api/reports/inspections/{d['id']}.csv", headers=h).content.decode("utf-8-sig")
    assert "defect_type" in csv_.splitlines()[0] and "pore" in csv_ and "scratch" in csv_
    allcsv = client.get("/api/reports/inspections.csv", headers=h, params={"batch": "B-7"}).content.decode("utf-8-sig")
    assert d["id"] in allcsv and "SN-001" in allcsv
    assert client.get("/api/reports/defects.csv", headers=h).status_code == 200
    q = client.get("/api/reports/quality.pdf", headers=h)
    assert q.status_code == 200 and q.content[:5] == b"%PDF-"
    assert client.get("/api/reports/inspections/doesnotexist.pdf", headers=h).status_code == 404


def test_clean_part_on_unvalidated_profile_is_not_passed(client, users, admin):
    h = users["inspector"]
    r = client.post("/api/inspections", headers=h, files={"file": img_file(texture(2))}, data={"material_key": "plastics"}).json()
    assert r["outcome"] == "review" and r["defect_count"] == 0
    assert "cannot be passed automatically" in " ".join(r["summary"]["decision"]["reasons"])
    # policy change by admin is audited and takes effect
    p = client.put("/api/settings/policy", headers=admin, json={"allow_unvalidated_pass": True, "review_on_quality_warn": False, "disagreement_delta": 0.6})
    assert p.status_code == 200
    r2 = client.post("/api/inspections", headers=h, files={"file": img_file(texture(4))}, data={"material_key": "plastics"}).json()
    assert r2["outcome"] == "pass" and r2["summary"]["decision"]["validated"] is False
    client.put("/api/settings/policy", headers=admin, json={"allow_unvalidated_pass": False, "review_on_quality_warn": False, "disagreement_delta": 0.6})
    acts = [a["action"] for a in client.get("/api/audit", headers=admin, params={"action": "settings."}).json()["items"]]
    assert "settings.policy_updated" in acts


@needs_pcb
def test_pcb_reference_profile(client, users):
    h = users["inspector"]
    base = EXTERNAL / "DeepPCB" / "PCBData" / "group20085" / "20085"
    test_img, temp_img = (base / "20085291_test.jpg").read_bytes(), (base / "20085291_temp.jpg").read_bytes()
    ident = client.post("/api/inspections/identify", headers=h, files={"file": ("a.jpg", test_img, "image/jpeg")}).json()
    assert ident["suggestion"]["known"] and ident["suggestion"]["profile_key"] == "pcb_bare_board"
    # without the golden reference the profile must refuse to decide
    r = client.post("/api/inspections", headers=h, files={"file": ("a.jpg", test_img, "image/jpeg")}, data={"profile_key": "pcb_bare_board"}).json()
    assert r["outcome"] == "review" and "golden reference" in " ".join(r["summary"]["decision"]["reasons"])
    r = client.post("/api/inspections", headers=h, files={"file": ("a.jpg", test_img, "image/jpeg"), "reference": ("t.jpg", temp_img, "image/jpeg")},
                    data={"profile_key": "pcb_bare_board"}).json()
    assert r["outcome"] == "defective" and r["defect_count"] >= 3 and r["material_key"] == "electronics"
    f = r["defects"][0]
    assert f["type_source"] == "model" and f["cause_hypotheses"] and f["dimensions"]["calibrated"] and f["class_probs"]
    # template vs itself: nothing found, but PASS is withheld because defect-free boards were never validated
    r = client.post("/api/inspections", headers=h, files={"file": ("a.jpg", temp_img, "image/jpeg"), "reference": ("t.jpg", temp_img, "image/jpeg")},
                    data={"profile_key": "pcb_bare_board"}).json()
    assert r["defect_count"] == 0 and r["outcome"] == "review"
    # profile/material mismatch is rejected
    r = client.post("/api/inspections", headers=h, files={"file": ("a.jpg", test_img, "image/jpeg")}, data={"profile_key": "pcb_bare_board", "material_key": "wood"})
    assert r.status_code == 422


@needs_mt
def test_magnetic_tile_validated_profile(client, users):
    h = users["inspector"]
    root = EXTERNAL / "Magnetic-tile-defect-datasets"
    good = sorted((root / "MT_Free" / "Imgs").glob("*.jpg"))[0].read_bytes()
    r = client.post("/api/inspections", headers=h, files={"file": ("g.jpg", good, "image/jpeg")}, data={"profile_key": "magnetic_tile"}).json()
    dec = r["summary"]["decision"]
    assert dec["validated"] and dec["p_defect"] is not None and dec["thresholds"]["t_low"] <= dec["thresholds"]["t_high"]
    assert r["outcome"] in ("pass", "review", "defective") and len(r["summary"]["detectors"]) == 2


def test_live_frame(client, users):
    h = users["inspector"]
    r = client.post("/api/live/frame", headers=h, files={"file": img_file(texture(10, defect="blob"))}, data={"material_key": "metals", "save": "never"}).json()
    assert r["decision"]["outcome"] == "review" and r["findings"] and r["saved_inspection_id"] is None
    r = client.post("/api/live/frame", headers=h, files={"file": img_file(texture(10, defect="blob"))}, data={"material_key": "metals", "save": "flagged"}).json()
    assert r["saved_inspection_id"]
    got = client.get(f"/api/inspections/{r['saved_inspection_id']}", headers=h).json()
    assert got["source"] == "live"


def test_video_inspection_job(client, users, tmp_path):
    path = str(tmp_path / "line.mp4")
    vw = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), 10.0, (256, 256))
    for i in range(30):
        vw.write(texture(100 + i // 10, defect="blob" if i >= 20 else None))
    vw.release()
    h = users["inspector"]
    with open(path, "rb") as f:
        r = client.post("/api/inspections/video", headers=h, files={"file": ("line.mp4", f.read(), "video/mp4")},
                        data={"material_key": "metals", "every_seconds": "1.0", "max_frames": "10", "batch_id": "VID-1"})
    assert r.status_code == 202, r.text
    job = client.get(f"/api/jobs/{r.json()['id']}", headers=h).json()
    assert job["status"] == "done", job
    assert job["result"]["frames_inspected"] == 3 and sum(job["result"]["outcomes"].values()) == 3
    frames = client.get("/api/inspections", headers=h, params={"job_id": job["id"]}).json()
    assert frames["total"] == 3 and {f["source"] for f in frames["items"]} == {"video"}
    r = client.post("/api/inspections/video", headers=h, files={"file": ("x.mp4", b"garbage", "video/mp4")}, data={"material_key": "metals"})
    assert client.get(f"/api/jobs/{r.json()['id']}", headers=h).json()["status"] == "failed"


# ------------------------------------------------------------------ datasets, leakage, active learning, training
def test_dataset_lifecycle_leakage_and_training(client, users):
    e, ins = users["engineer"], users["inspector"]
    ds = client.post("/api/datasets", headers=e, json={"name": "Brushed plate v1", "material_key": "metals", "description": "synthetic test fixture"})
    assert ds.status_code == 201, ds.text
    ds_id = ds.json()["id"]
    assert client.post("/api/datasets", headers=e, json={"name": "Brushed plate v1", "material_key": "metals"}).status_code == 409

    good = [("files", (f"good_{i}.png", png(texture(200 + i)), "image/png")) for i in range(48)]
    r = client.post(f"/api/datasets/{ds_id}/images", headers=e, files=good, data={"label": "good"}).json()
    assert len(r["added"]) == 48 and not r["errors"]
    bad = [("files", (f"bad_{i}.png", png(texture(300 + i, defect="blob" if i % 2 else "scratch")), "image/png")) for i in range(40)]
    r = client.post(f"/api/datasets/{ds_id}/images", headers=e, files=bad, data={"label": "defective"}).json()
    assert len(r["added"]) == 40
    # exact duplicate is refused; a re-compressed copy of an existing image is accepted but grouped with its twin
    r = client.post(f"/api/datasets/{ds_id}/images", headers=e, files=[good[0]], data={"label": "good"}).json()
    assert r["skipped_duplicates"] == ["good_0.png"] and not r["added"]
    twin = cv2.imencode(".jpg", texture(200), [cv2.IMWRITE_JPEG_QUALITY, 80])[1].tobytes()
    r = client.post(f"/api/datasets/{ds_id}/images", headers=e, files=[("files", ("good_0_copy.jpg", twin, "image/jpeg"))], data={"label": "good"}).json()
    twin_id = r["added"][0]["id"]
    # two shots of the same serial number must stay together
    serial = [("files", (f"sn42_{i}.png", png(texture(400 + i)), "image/png")) for i in range(2)]
    client.post(f"/api/datasets/{ds_id}/images", headers=e, files=serial, data={"label": "good", "group_key": "SN-42"})

    # training is refused until splits exist
    job = client.post("/api/models/train", headers=e, json={"dataset_id": ds_id, "name": "brushed_plate_anomaly"}).json()
    assert client.get(f"/api/jobs/{job['id']}", headers=e).json()["status"] == "failed"

    sp = client.post(f"/api/datasets/{ds_id}/split", headers=e).json()
    assert sum(sp["splits"].values()) == 91 and sp["leakage"]["clean"] and sp["multi_image_groups"] >= 2
    imgs = client.get(f"/api/datasets/{ds_id}/images", headers=e, params={"limit": 500}).json()["items"]
    by_name = {i["filename"]: i for i in imgs}
    assert by_name["good_0.png"]["split"] == by_name["good_0_copy.jpg"]["split"]
    assert by_name["good_0.png"]["leak_group"] == by_name["good_0_copy.jpg"]["leak_group"]
    assert by_name["sn42_0.png"]["split"] == by_name["sn42_1.png"]["split"]
    assert {i["split"] for i in imgs} == {"train", "val", "test"}
    # re-running is deterministic
    again = {i["id"]: i["split"] for i in client.get(f"/api/datasets/{ds_id}/images", headers=e, params={"limit": 500}).json()["items"]}
    client.post(f"/api/datasets/{ds_id}/split", headers=e)
    assert again == {i["id"]: i["split"] for i in client.get(f"/api/datasets/{ds_id}/images", headers=e, params={"limit": 500}).json()["items"]}

    # annotation: bbox + polygon
    target = by_name["bad_1.png"]
    ann = {"annotations": [{"defect_type": "pore", "shape": "bbox", "bbox": [10, 12, 30, 28]},
                           {"defect_type": "scratch", "shape": "polygon", "polygon": [[5, 5], [60, 8], [58, 14], [6, 11]]}]}
    a = client.patch(f"/api/datasets/{ds_id}/images/{target['id']}", headers=e, json=ann).json()
    assert len(a["annotations"]) == 2 and a["annotations"][1]["bbox"] == [5.0, 5.0, 55.0, 9.0] and a["label"] == "defective"
    assert client.patch(f"/api/datasets/{ds_id}/images/{target['id']}", headers=e, json={"label": "good"}).status_code == 422
    assert client.patch(f"/api/datasets/{ds_id}/images/{target['id']}", headers=e,
                        json={"annotations": [{"defect_type": "x", "shape": "polygon", "polygon": [[1, 1], [2, 2]]}]}).status_code == 422
    assert client.patch(f"/api/datasets/{ds_id}/images/{target['id']}", headers=ins, json=ann).status_code == 403
    info = client.get(f"/api/datasets/{ds_id}", headers=e).json()
    assert {c["type"] for c in info["defect_classes"]} == {"pore", "scratch"}
    assert client.get(f"/api/datasets/{ds_id}/images", headers=e, params={"defect_type": "pore"}).json()["total"] == 1

    # export
    z = zipfile.ZipFile(io.BytesIO(client.get(f"/api/datasets/{ds_id}/export", headers=e, params={"format": "coco"}).content))
    man = json.loads(z.read("manifest.json"))
    assert len(man["images"]) == 91 and man["classes"] == ["pore", "scratch"]
    coco = json.loads(z.read(f"{target['split']}/annotations.json"))
    assert len(coco["annotations"]) == 2 and coco["annotations"][1]["segmentation"]
    z = zipfile.ZipFile(io.BytesIO(client.get(f"/api/datasets/{ds_id}/export", headers=e, params={"format": "yolo"}).content))
    assert "data.yaml" in z.namelist() and any(n.endswith(".txt") and z.read(n) for n in z.namelist())

    # in-app training: fits on train goods only, calibrates on val, reports on test
    job = client.post("/api/models/train", headers=e, json={"dataset_id": ds_id, "name": "brushed_plate_anomaly"}).json()
    job = client.get(f"/api/jobs/{job['id']}", headers=e).json()
    assert job["status"] == "done", job
    res = job["result"]
    assert res["version"] == "1.0.0" and "test" in res["metrics"] and res["metrics"]["test"]["auroc"] > 0.9
    models = client.get("/api/models", headers=e).json()
    mv = next(m for m in models if m["name"] == "brushed_plate_anomaly")
    assert mv["status"] == "candidate" and mv["card"]["splits"]["train"]["good"] > 8
    assert client.post(f"/api/models/{mv['id']}/promote", headers=ins, json={}).status_code == 403
    pr = client.post(f"/api/models/{mv['id']}/promote", headers=e, json={"profile_name": "Brushed plate"}).json()
    assert pr["status"] == "production" and pr["profile_key"] == "brushed_plate_anomaly"
    assert client.post(f"/api/models/{mv['id']}/archive", headers=e).status_code == 409  # in use by an active profile

    # the new profile now makes calibrated three-way decisions
    r = client.post("/api/inspections", headers=ins, files={"file": ("n.png", png(texture(900, defect="blob")), "image/png")},
                    data={"profile_key": "brushed_plate_anomaly"}).json()
    assert r["summary"]["decision"]["mode"] == "fusion" and r["p_defect"] is not None and r["outcome"] in ("defective", "review")
    assert r["p_defect"] > 0.5
    r2 = client.post("/api/inspections", headers=ins, files={"file": ("n.png", png(texture(901)), "image/png")}, data={"profile_key": "brushed_plate_anomaly"}).json()
    assert r2["p_defect"] < r["p_defect"]

    # active learning: unreviewed AI output is refused; reviewed inspection becomes a labelled example
    assert client.post(f"/api/datasets/{ds_id}/from-inspection", headers=e, json={"inspection_id": r["id"]}).status_code in (201, 422)
    if r["review_status"] == "pending":
        assert client.post(f"/api/datasets/{ds_id}/from-inspection", headers=e, json={"inspection_id": r["id"]}).status_code == 422
    rv = client.post(f"/api/inspections/{r['id']}/review", headers=ins, json={
        "final_outcome": "defective", "defects": [{"id": d["id"], "qc_status": "confirmed"} for d in r["defects"]]}).json()
    added = client.post(f"/api/datasets/{ds_id}/from-inspection", headers=e, json={"inspection_id": r["id"]})
    assert added.status_code == 201, added.text
    assert added.json()["label"] == "defective" and added.json()["split"] == "unassigned" and added.json()["source_inspection_id"] == r["id"]
    assert len(added.json()["annotations"]) == len(rv["defects"])
    assert client.post(f"/api/datasets/{ds_id}/from-inspection", headers=e, json={"inspection_id": r["id"]}).status_code == 409
    assert client.get(f"/api/datasets/{ds_id}/leakage", headers=e).json()["unassigned_images"] == 1

    # editing validated thresholds by hand voids the validated flag
    prof = client.patch("/api/profiles/brushed_plate_anomaly", headers=e, json={"t_low": 0.01, "t_high": 0.99, "mm_per_pixel": 0.02}).json()
    assert prof["validated"] is False and prof["mm_per_pixel"] == 0.02
    assert client.patch("/api/profiles/brushed_plate_anomaly", headers=e, json={"t_low": 0.9, "t_high": 0.1}).status_code == 422


# ------------------------------------------------------------------ analytics / models / monitoring
def test_analytics_and_monitoring(client, users):
    h = users["viewer"]
    a = client.get("/api/analytics/overview", headers=h).json()
    o = a["overview"]
    assert o["total"] == o["passed"] + o["review"] + o["defective"] and o["total"] >= 5
    assert a["by_type"] and a["by_material"] and a["trend"] and any(b["batch"] == "B-7" for b in a["by_batch"])
    assert sum(t["total"] for t in a["trend"]) == o["total"]
    only = client.get("/api/analytics/overview", headers=h, params={"material": "plastics"}).json()
    assert 0 < only["overview"]["total"] < o["total"]
    mats = client.get("/api/materials", headers=h).json()
    assert len(mats) >= 12 and {m["coverage"] for m in mats} <= {"validated", "screening_only"}
    assert client.get("/api/evaluations", headers=h).status_code == 200
    prod = client.get("/api/monitoring/production", headers=h).json()
    assert any(p["profile_key"] == "generic_screening" for p in prod)
    assert isinstance(client.get("/api/monitoring/drift", headers=h).json(), list)
    sysinfo = client.get("/api/settings/system", headers=h).json()
    assert sysinfo["device"] in ("cpu", "cuda", "mps") and "torch" in sysinfo
    assert len(client.get("/api/taxonomy", headers=h).json()) > 20


def test_audit_trail(client, admin):
    items = client.get("/api/audit", headers=admin, params={"limit": 500}).json()["items"]
    actions = {a["action"] for a in items}
    assert {"auth.login", "auth.login_failed", "inspection.created", "inspection.reviewed", "dataset.created", "model.promoted", "user.created"} <= actions
