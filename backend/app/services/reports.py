"""PDF and CSV report generation."""
from __future__ import annotations

import csv
import io
from datetime import datetime, timezone

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Image as RLImage
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from ..ml.knowledge import defect_label
from ..models import Inspection
from ..storage import get_storage

OUTCOME_LABEL = {"pass": "PASS", "review": "REQUIRES HUMAN REVIEW", "defective": "DEFECTIVE"}
OUTCOME_COLOR = {"pass": colors.HexColor("#1f7a4d"), "review": colors.HexColor("#a56a00"), "defective": colors.HexColor("#b3261e")}
GRID = colors.HexColor("#c9cdd3")
HEAD = colors.HexColor("#22262c")

_ss = getSampleStyleSheet()
H1 = ParagraphStyle("h1", parent=_ss["Heading1"], fontSize=16, spaceAfter=4)
H2 = ParagraphStyle("h2", parent=_ss["Heading2"], fontSize=11, spaceBefore=10, spaceAfter=4, textColor=HEAD)
BODY = ParagraphStyle("body", parent=_ss["BodyText"], fontSize=8.5, leading=11)
SMALL = ParagraphStyle("small", parent=BODY, fontSize=7.5, leading=9.5, textColor=colors.HexColor("#555b64"))


def _table(rows, widths, header=True):
    t = Table(rows, colWidths=widths, repeatRows=1 if header else 0)
    style = [("FONTSIZE", (0, 0), (-1, -1), 8), ("GRID", (0, 0), (-1, -1), 0.4, GRID), ("VALIGN", (0, 0), (-1, -1), "TOP"),
             ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4)]
    if header:
        style += [("BACKGROUND", (0, 0), (-1, 0), HEAD), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold")]
    t.setStyle(TableStyle(style))
    return t


def _img(key: str | None, max_w: float, max_h: float):
    if not key:
        return Paragraph("n/a", SMALL)
    try:
        from PIL import Image as PILImage

        data = get_storage().get(key)
        w, h = PILImage.open(io.BytesIO(data)).size
        f = min(max_w / w, max_h / h)
        return RLImage(io.BytesIO(data), width=w * f, height=h * f)
    except Exception:
        return Paragraph("image unavailable", SMALL)


def _footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(colors.HexColor("#6b7280"))
    canvas.drawString(15 * mm, 9 * mm, "ForgeSight inspection report - AI-assisted result; cause statements are hypotheses, not observations.")
    canvas.drawRightString(A4[0] - 15 * mm, 9 * mm, f"Page {doc.page}")
    canvas.restoreState()


def effective_outcome(i: Inspection) -> str:
    return i.final_outcome or i.outcome or "review"


def inspection_pdf(i: Inspection, material_name: str) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=14 * mm, bottomMargin=16 * mm,
                            title=f"Inspection {i.id}", author="ForgeSight")
    s = i.summary or {}
    dec = s.get("decision", {})
    out = effective_outcome(i)
    el = [Paragraph("Inspection Report", H1),
          Paragraph(f"Report generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC", SMALL), Spacer(1, 6)]
    banner = Table([[Paragraph(f"<font color='white'><b>INSPECTION OUTCOME: {OUTCOME_LABEL.get(out, out.upper())}</b></font>", BODY)]], colWidths=[180 * mm])
    banner.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), OUTCOME_COLOR.get(out, HEAD)), ("LEFTPADDING", (0, 0), (-1, -1), 8),
                                ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
    el += [banner, Spacer(1, 8)]
    ai_line = OUTCOME_LABEL.get(i.outcome or "", "-")
    if i.review_status in ("confirmed", "corrected"):
        ai_line += f"  (human review by {i.reviewed_by}: {i.review_status}; final = {OUTCOME_LABEL.get(out)})"
    elif i.outcome == "review":
        ai_line += "  (awaiting human review)"
    ident = [
        ["Inspection ID", i.id, "Inspection date (UTC)", f"{i.created_at:%Y-%m-%d %H:%M:%S}"],
        ["Product ID", i.product_id or "-", "Batch", i.batch_id or "-"],
        ["Material", f"{material_name} ({'operator-selected' if i.material_source != 'suggested' else 'AI-suggested'})", "Inspection profile",
         s.get("profile_name") or "Generic screening"],
        ["Source file", i.filename or "-", "Operator", i.created_by or "-"],
        ["AI outcome", Paragraph(ai_line, BODY), "Defect probability", "-" if i.p_defect is None else f"{i.p_defect * 100:.1f}% (calibrated)"],
        ["Image quality gate", (s.get("quality", {}).get("status") or "-").upper(), "Decision rule validated", "Yes" if dec.get("validated") else "No - screening only"],
    ]
    t = _table(ident, [32 * mm, 62 * mm, 36 * mm, 50 * mm], header=False)
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#eef0f3")), ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#eef0f3"))]))
    el += [t, Paragraph("Decision basis", H2)]
    for r in dec.get("reasons", []):
        el.append(Paragraph(f"&bull; {r}", BODY))
    el += [Paragraph("Images", H2),
           Table([[_img(i.image_key, 88 * mm, 80 * mm), _img(i.annotated_key, 88 * mm, 80 * mm)],
                  [Paragraph("Original image", SMALL), Paragraph("Annotated image (numbers refer to the findings table)", SMALL)]], colWidths=[90 * mm, 90 * mm])]
    el.append(Paragraph(f"Findings ({len(i.defects)})", H2))
    if i.defects:
        rows = [["#", "Defect (classification)", "Location / size", "Confidence", "Severity", "QC status"]]
        for d in i.defects:
            f = d.data
            dims = f["dimensions"]
            size = f"{dims['length_mm']} x {dims['width_mm']} mm" if dims.get("calibrated") else f"{dims['length_px']:.0f} x {dims['width_px']:.0f} px (uncalibrated)"
            cls = d.label + {"model": "", "human": "<br/><font size=7 color='#666'>added by inspector</font>"}.get(
                d.type_source, "<br/><font size=7 color='#666'>shape heuristic, not a trained classifier</font>")
            if d.human_type:
                cls += f"<br/><font size=7>Inspector: {defect_label(d.human_type)}</font>"
            basis = {"model_probability": "model score", "anomaly_strength": "anomaly strength", "screening_heuristic": "screening, uncalibrated",
                     "human": "marked by inspector"}.get(f["confidence_basis"], f["confidence_basis"])
            rows.append([str(d.idx), Paragraph(cls, BODY), Paragraph(f"{f['location']}<br/>{size}", BODY),
                         Paragraph(f"{d.confidence * 100:.0f}%<br/><font size=7 color='#666'>{basis}</font>", BODY),
                         Paragraph(f"<b>{d.severity}</b><br/><font size=7 color='#666'>{f['severity']['rationale']}</font>", BODY), d.qc_status])
        el.append(_table(rows, [8 * mm, 48 * mm, 36 * mm, 26 * mm, 44 * mm, 18 * mm]))
        el.append(Paragraph("Possible causes (hypotheses) and recommended next steps", H2))
        el.append(Paragraph("The causes below are looked up from a manufacturing knowledge base by defect type and material. "
                            "They were <b>not observed</b> in the image and must be verified at the process.", SMALL))
        rows = [["#", "Possible causes (hypotheses)", "Recommended action"]]
        for d in i.defects:
            causes = d.data.get("cause_hypotheses") or []
            rows.append([str(d.idx), Paragraph("<br/>".join(f"&bull; {c}" for c in causes) or "No hypothesis: defect type not established.", BODY),
                         Paragraph(d.data["recommended_action"], BODY)])
        el += [Spacer(1, 3), _table(rows, [8 * mm, 86 * mm, 86 * mm])]
    else:
        el.append(Paragraph("No irregularities were localized by the detectors of this profile.", BODY))
    el.append(Paragraph("Models used", H2))
    rows = [["Detector", "Type", "Version", "Validated on held-out data", "Image score"]]
    for d in s.get("detectors", []):
        rows.append([d["name"], d["kind"], d.get("model_version") or "-", "yes" if d["validated"] else "no", "-" if d["image_score"] is None else f"{d['image_score']:.4f}"])
    el.append(_table(rows, [50 * mm, 30 * mm, 22 * mm, 46 * mm, 32 * mm]))
    if i.review_notes:
        el += [Paragraph("Reviewer notes", H2), Paragraph(i.review_notes, BODY)]
    doc.build(el, onFirstPage=_footer, onLaterPages=_footer)
    return buf.getvalue()


INSPECTION_COLUMNS = ["inspection_id", "created_at_utc", "product_id", "batch_id", "material", "profile", "source", "ai_outcome", "final_outcome",
                      "review_status", "defect_probability", "decision_validated", "quality_gate", "defect_count", "max_severity", "processing_ms", "operator", "reviewed_by"]
DEFECT_COLUMNS = ["inspection_id", "created_at_utc", "product_id", "batch_id", "material", "defect_no", "defect_type", "defect_label", "category",
                  "classification_source", "confidence", "confidence_basis", "severity", "location", "bbox_x", "bbox_y", "bbox_w", "bbox_h",
                  "length_px", "width_px", "length_mm", "width_mm", "area_mm2", "detectors", "qc_status", "inspector_type",
                  "cause_hypotheses", "recommended_action"]


def inspection_row(i: Inspection) -> list:
    return [i.id, i.created_at.strftime("%Y-%m-%dT%H:%M:%SZ"), i.product_id or "", i.batch_id or "", i.material_key, i.profile_key or "generic_screening",
            i.source, i.outcome or "", effective_outcome(i), i.review_status or "", "" if i.p_defect is None else i.p_defect,
            bool((i.summary or {}).get("decision", {}).get("validated")), i.quality_status or "", i.defect_count, i.max_severity or "",
            i.processing_ms or "", i.created_by or "", i.reviewed_by or ""]


def defect_rows(i: Inspection) -> list[list]:
    rows = []
    for d in i.defects:
        f = d.data
        dm = f["dimensions"]
        rows.append([i.id, i.created_at.strftime("%Y-%m-%dT%H:%M:%SZ"), i.product_id or "", i.batch_id or "", i.material_key, d.idx, d.defect_type, d.label,
                     d.category, d.type_source, d.confidence, f["confidence_basis"], d.severity, f["location"], *f["bbox"], dm["length_px"], dm["width_px"],
                     dm.get("length_mm", ""), dm.get("width_mm", ""), dm.get("area_mm2", ""), "+".join(f["sources"]), d.qc_status, d.human_type or "",
                     " | ".join(f.get("cause_hypotheses") or []), f["recommended_action"]])
    return rows


def to_csv(header: list[str], rows: list[list]) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    w.writerows(rows)
    return buf.getvalue().encode("utf-8-sig")


def quality_pdf(title: str, period: str, overview: dict, by_type: list, by_material: list, by_batch: list, trend: list, evals: list) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=14 * mm, bottomMargin=16 * mm, title=title, author="ForgeSight")
    el = [Paragraph(title, H1), Paragraph(f"{period} - generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC", SMALL), Spacer(1, 8)]
    o = overview
    rows = [["Inspected", "Passed", "Requiring review", "Defective", "Pass rate", "Mean processing"],
            [o["total"], o["passed"], o["review"], o["defective"], "-" if not o["total"] else f"{o['passed'] / o['total'] * 100:.1f}%",
             "-" if o.get("mean_processing_ms") is None else f"{o['mean_processing_ms']:.0f} ms"]]
    el += [_table(rows, [30 * mm] * 6), Paragraph("Outcomes use the final (human-reviewed) result where a review exists, otherwise the AI outcome.", SMALL)]

    def section(name, header, data, widths):
        el.append(Paragraph(name, H2))
        el.append(_table([header] + data, widths) if data else Paragraph("No data in this period.", BODY))

    section("Defects by type", ["Defect type", "Count", "Critical", "Major", "Minor"],
            [[r["label"], r["count"], r["critical"], r["major"], r["minor"]] for r in by_type], [80 * mm, 25 * mm, 25 * mm, 25 * mm, 25 * mm])
    section("By material", ["Material", "Inspected", "Passed", "Review", "Defective", "Defects found"],
            [[r["material"], r["total"], r["passed"], r["review"], r["defective"], r["defects"]] for r in by_material], [55 * mm] + [25 * mm] * 5)
    section("By production batch", ["Batch", "Inspected", "Passed", "Review", "Defective", "Defect rate"],
            [[r["batch"], r["total"], r["passed"], r["review"], r["defective"], f"{r['defective'] / r['total'] * 100:.1f}%"] for r in by_batch[:40]],
            [55 * mm] + [25 * mm] * 5)
    section("Daily trend", ["Date", "Inspected", "Passed", "Review", "Defective"],
            [[r["date"], r["total"], r["passed"], r["review"], r["defective"]] for r in trend[-31:]], [40 * mm] + [35 * mm] * 4)
    el.append(PageBreak())
    el.append(Paragraph("Model validation evidence", H2))
    el.append(Paragraph("Measured on held-out test splits of the named datasets. These figures do not transfer to other materials, cameras or lighting.", SMALL))
    rows = [["Model", "Dataset / split", "Task", "n", "Headline metric"]]
    for e in evals:
        rows.append([Paragraph(f"{e['model']} {e['version']}", BODY), Paragraph(f"{e['dataset']} / {e['split']}", BODY), Paragraph(e["task"], BODY), e["n"],
                     Paragraph(e["headline"], BODY)])
    el.append(_table(rows, [34 * mm, 40 * mm, 46 * mm, 12 * mm, 48 * mm]))
    doc.build(el, onFirstPage=_footer, onLaterPages=_footer)
    return buf.getvalue()
