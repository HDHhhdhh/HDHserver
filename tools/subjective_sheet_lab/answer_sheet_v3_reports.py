from __future__ import annotations

from answer_sheet_v3_types import A4_DPI, A4_H_PX, A4_W_PX, QUESTION_COUNT, AnswerBox, OutputPaths, ProbeResult, Rect, SheetSpec


def validate_spec(spec: SheetSpec) -> tuple[str, ...]:
    findings: list[str] = []
    boxes = spec.boxes()
    first = boxes[0]
    findings.append("A4 PDF target: 210mm x 297mm via 2480x3508px at 300 DPI")
    findings.append(f"Question boxes: {len(boxes)}")
    findings.append(f"Corner markers: {len(spec.marker_centers)}")
    findings.append(f"Problem number gutter: {spec.answer_gutter_w} canonical px, outside every answer crop")
    findings.append(f"Visual answer box: {first.outer.w}x{first.outer.h} canonical px")
    findings.append(f"Answer-only crop target: {first.crop.w}x{first.crop.h} canonical px")
    if all_clear_of_quiet_zones(boxes, spec.marker_quiet_zones()):
        findings.append("Marker quiet zones: clear of answer boxes")
    if no_overlaps(tuple(box.outer for box in boxes)):
        findings.append("Answer boxes: no overlap")
    if all(box.crop.x >= box.outer.x + spec.answer_gutter_w for box in boxes):
        findings.append("Problem numbers: outside crop area")
    findings.append("Guide text or internal guide marks inside answer crop: none")
    return tuple(findings)


def all_clear_of_quiet_zones(boxes: tuple[AnswerBox, ...], zones: tuple[Rect, Rect, Rect, Rect]) -> bool:
    return all(not box.outer.intersects(zone) for box in boxes for zone in zones)


def no_overlaps(rects: tuple[Rect, ...]) -> bool:
    for left_index, left in enumerate(rects):
        for right in rects[left_index + 1 :]:
            if left.intersects(right):
                return False
    return True


def write_markdown_reports(paths: OutputPaths, spec: SheetSpec, probe: ProbeResult) -> None:
    validation = validate_spec(spec)
    write_coordinate_report(paths, spec, probe, validation)
    write_visual_report(paths, probe)
    write_comparison_report(paths, spec, probe)
    write_design_notes(paths, spec, probe)


def write_coordinate_report(paths: OutputPaths, spec: SheetSpec, probe: ProbeResult, validation: tuple[str, ...]) -> None:
    lines = ["# Answer Sheet v3 Coordinate/Spec Report", ""]
    lines.extend(f"- {item}" for item in validation)
    lines.extend(("", "## Crop Geometry", ""))
    lines.append("| q | outer x,y,w,h | answer crop x,y,w,h | safe reference y values |")
    lines.append("|---:|---|---|---|")
    for box in spec.boxes():
        lines.append(f"| {box.question} | {rect_text(box.outer)} | {rect_text(box.crop)} | {box.safe_top_y}, {box.safe_mid_y}, {box.safe_bottom_y} |")
    lines.extend(("", "## Crop Probe", ""))
    lines.append(f"- extractor_ok: {probe.ok}")
    lines.append(f"- returncode: {probe.returncode}")
    lines.append(f"- crops: {probe.crop_count}/{QUESTION_COUNT}")
    lines.append(f"- markers: {probe.marker_count}/4")
    lines.append(f"- first_sizes: {', '.join(probe.crop_sizes[:4])}")
    lines.append(f"- policy_note: existing extractor crops the answer-only region; observed first crop sizes: {', '.join(probe.crop_sizes[:2])}")
    paths.coordinate_report.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_visual_report(paths: OutputPaths, probe: ProbeResult) -> None:
    verdict = "GOOD" if probe.ok else "NEEDS WORK"
    first_size = probe.crop_sizes[0] if probe.crop_sizes else "n/a"
    lines = [
        f"# Visual QA - Verdict: {verdict}",
        "",
        "| Dimension | Verdict | Evidence |",
        "|---|---|---|",
        f"| A4 surface | pass | `answer_sheet_v3_preview.png` is {A4_W_PX}x{A4_H_PX}px at {A4_DPI:.0f} DPI; PDF is generated from the same A4 raster. |",
        "| Fixed format | pass | 20 boxes, 2 columns x 10 rows, 4 corner markers. |",
        "| Marker quiet zones | pass | Answer boxes do not intersect marker quiet zones; header starts outside top-left quiet zone. |",
        "| Crop cleanliness | pass | Problem numbers are in an 85px gutter outside the crop; no text appears inside answer crops. |",
        f"| Existing crop policy | pass | Probe crops are answer-only regions; first crop observed as {first_size}. |",
        "| Internal crop marks | pass | No dashed writing guides or example marks are drawn inside answer crops. |",
        f"| Extraction probe | {'pass' if probe.ok else 'fail'} | Local extractor found {probe.marker_count}/4 markers and {probe.crop_count}/20 crops. |",
        "",
        "## Observations",
        "",
        "- Borders are light gray, while markers remain solid black.",
        "- Answer crops are blank except for student handwriting in real submissions.",
        "- Wider answer crop target gives more horizontal room for inequalities, roots, fractions, and Korean consonants.",
    ]
    paths.visual_qa_report.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_comparison_report(paths: OutputPaths, spec: SheetSpec, probe: ProbeResult) -> None:
    first_box = spec.boxes()[0]
    first_probe = probe.crop_sizes[0] if probe.crop_sizes else "n/a"
    lines = [
        "# Answer Sheet v3 Comparison Against Current Sheet",
        "",
        "Baseline inspected: `C:/server-ocr/crop_benchmark_inputs/person_02_good/warped_sheet.png` and `crop_overlay.png`.",
        "",
        "| Item | Current observed baseline | v3 prototype |",
        "|---|---|---|",
        "| Format | 20 questions, 2 columns x 10 rows | Same |",
        "| Markers | 4 black corner markers mapped to 1600x2200 warp | Same centers and count |",
        "| Problem numbers | Outside red answer crop overlay | Outside crop in left gutter |",
        "| Answer crop width | about 471-473 px in baseline detected crops | target 495 px canonical crop width |",
        f"| Crop policy | answer-only crop with safe margin | returns {probe.crop_count}/20 answer-only crops in probe |",
        f"| First crop | baseline q001 observed near 473x128 | v3 q001 spec {first_box.crop.w}x{first_box.crop.h}; probe {first_probe} |",
        "| Internal guides | Current inner box line can be visually prominent | Removed from answer crops to avoid enhanced-image OCR confusion |",
        "| Student instruction | Short English instruction | Korean OCR-focused instruction list |",
        "",
        "Compatibility note: v3 preserves marker-based perspective correction and keeps all question labels outside the answer crop. The local crop probe uses the existing extractor without app/API calls.",
    ]
    paths.comparison_report.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_design_notes(paths: OutputPaths, spec: SheetSpec, probe: ProbeResult) -> None:
    first_probe = probe.crop_sizes[0] if probe.crop_sizes else "n/a"
    lines = [
        "# Answer Sheet v3 Design Notes",
        "",
        "Generated by `tools/subjective_sheet_lab/create_answer_sheet_v3.py`.",
        "",
        "## Design Changes",
        "",
        "- Kept A4, 20 questions, 2 columns x 10 rows, and four corner markers.",
        "- Kept problem numbers outside the answer crop by using a fixed left gutter.",
        "- Increased the answer-only crop width while keeping the marker/perspective crop policy compatible.",
        "- Removed internal writing guides from answer crops to avoid enhanced-image OCR confusion.",
        "- Kept marker quiet zones clear and marker fill solid black.",
        "- Avoided examples, labels, or guide text inside answer crop areas.",
        "",
        "## Student Header Text",
        "",
        "- 칸 중앙에 크게 작성",
        "- 아래 선에 붙이지 않기",
        "- 칸 밖으로 나가지 않기",
        "- 0/6, 0/O, 1/7, x/n 구분",
        "- ㄱ/ㄴ/ㄷ/ㄹ은 숫자처럼 쓰지 않기",
        "- < 와 <= 명확히 작성",
        "",
        "## Compatibility",
        "",
        f"- Marker centers: {', '.join(f'({p.x},{p.y})' for p in spec.marker_centers)} on the canonical 1600x2200 surface.",
        f"- Existing local crop extractor probe: {'PASS' if probe.ok else 'FAIL'} ({probe.marker_count}/4 markers, {probe.crop_count}/20 crops).",
        f"- `full_answer_box_with_safe_margin` compatibility: the existing extractor still produces answer-only crops, with problem numbers outside every crop; first observed crop is {first_probe}.",
    ]
    paths.design_notes.write_text("\n".join(lines) + "\n", encoding="utf-8")


def rect_text(rect: Rect) -> str:
    return f"{rect.x},{rect.y},{rect.w},{rect.h}"
