from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final, TypeAlias, assert_never

from tools.subjective_sheet_lab.ocr_preprocess_variants import ImageArray, OpenCvModule, read_grayscale_crop, require_cv2
from tools.subjective_sheet_lab.verify_ocr_priority_crop_feature_targets import BoundingBox, answer_components
from tools.subjective_sheet_lab.verify_ocr_priority_digit_shape_scores import ComponentScore, component_score
from tools.subjective_sheet_lab.verify_ocr_visible_digit_candidate_targets import is_digit_candidate

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]

ROOT: Final[Path] = Path(__file__).resolve().parents[2]
ARTIFACT_DIR: Final[Path] = ROOT / "tools/subjective_sheet_lab/visual_evidence/person_second_pass_request_manifests"
FORBIDDEN_OUTPUT_TOKENS: Final[tuple[str, ...]] = (
    "expected",
    "canonical_answer",
    "accepted_answers",
    "correct",
    "incorrect",
    "grading",
    "crop_path",
    "C:\\",
    "C:/",
    "/c/",
)
VALID_DIGITS: Final[frozenset[str]] = frozenset(("1", "2", "3", "4", "5"))
SCALE: Final[int] = 4
PAD: Final[int] = 10


@dataclass(frozen=True, slots=True)
class Target:
    question_no: int
    final_side: str


@dataclass(frozen=True, slots=True)
class CaseSpec:
    case_id: str
    should_queue: bool
    targets: tuple[Target, ...]


@dataclass(frozen=True, slots=True)
class EvalItem:
    question_no: int
    recognized: str
    status: str


@dataclass(frozen=True, slots=True)
class RequestItem:
    question_no: int
    current_recognized: str
    current_status: str
    artifact_file: str
    enlarged_width: int
    enlarged_height: int
    action: str
    auto_confirm_allowed: bool


@dataclass(frozen=True, slots=True)
class ControlItem:
    question_no: int
    current_recognized: str
    current_status: str
    queued: bool
    reason: str


@dataclass(frozen=True, slots=True)
class CaseResult:
    case_id: str
    status: str
    request_items: tuple[RequestItem, ...]
    control_items: tuple[ControlItem, ...]


@dataclass(frozen=True, slots=True)
class ManifestBuild:
    cases: tuple[CaseResult, ...]
    output: JsonObject


@dataclass(frozen=True, slots=True)
class PersonSecondPassError(Exception):
    message: str

    def __str__(self) -> str:
        return self.message


def build_manifest() -> ManifestBuild:
    cv2 = require_cv2()
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    cases = tuple(case_result(cv2, spec) for spec in case_specs())
    assert_cases(cases)
    output = output_json(cases)
    output["sensitive_field_leak_count"] = leak_count(json.dumps(output, ensure_ascii=False))
    if output["sensitive_field_leak_count"] != 0:
        raise PersonSecondPassError("sensitive token leaked into person second-pass manifest")
    return ManifestBuild(cases, output)


def case_specs() -> tuple[CaseSpec, ...]:
    return (
        CaseSpec("person_03", True, (Target(16, "right"), Target(17, "left"))),
        CaseSpec("person_04", False, (Target(16, "right"), Target(17, "left"))),
    )


def case_result(cv2: OpenCvModule, spec: CaseSpec) -> CaseResult:
    items = eval_items_by_question(spec.case_id)
    request_items: list[RequestItem] = []
    control_items: list[ControlItem] = []
    for target in spec.targets:
        item = items[target.question_no]
        if should_queue(item, spec.should_queue):
            request_items.append(request_item(cv2, spec.case_id, target, item))
        else:
            control_items.append(control_item(item))
    status = "USER_APPROVAL_REQUIRED" if request_items else "NO_SECOND_PASS_NEEDED"
    return CaseResult(spec.case_id, status, tuple(request_items), tuple(control_items))


def request_item(cv2: OpenCvModule, case_id: str, target: Target, item: EvalItem) -> RequestItem:
    gray = read_grayscale_crop(cv2, Path("C:/server-ocr/crop_benchmark_inputs") / case_id / "crops" / f"q{target.question_no:03d}.png")
    components = tuple(sorted(answer_components(cv2, gray), key=lambda box: box.x))
    candidate = select_visible_candidate(tuple(component_score(cv2, gray, box) for box in components), target.final_side)
    enlarged = enlarge(cv2, padded_crop(gray, candidate.bbox, PAD), SCALE)
    height, width = enlarged.shape[:2]
    artifact_file = f"{case_id}_q{target.question_no:03d}_visible_digit_x{SCALE}.png"
    if not cv2.imwrite(str(ARTIFACT_DIR / artifact_file), enlarged):
        raise PersonSecondPassError(f"failed to write {artifact_file}")
    return RequestItem(target.question_no, item.recognized, item.status, artifact_file, int(width), int(height), "USER_APPROVAL_REQUIRED", False)


def control_item(item: EvalItem) -> ControlItem:
    if item.recognized in VALID_DIGITS:
        reason = "already_digit_recognized"
    elif item.status != "review_required":
        reason = "not_review_required"
    else:
        reason = "not_queued_control_case"
    return ControlItem(item.question_no, item.recognized, item.status, False, reason)


def should_queue(item: EvalItem, target_case: bool) -> bool:
    return target_case and item.status == "review_required" and item.recognized not in VALID_DIGITS


def eval_items_by_question(case_id: str) -> dict[int, EvalItem]:
    path = Path("C:/server-ocr/gemini_outputs") / f"{case_id}_same_contact" / "human_transcription_eval.json"
    rows = require_list(read_json_object(path).get("items"), "items")
    return {item.question_no: item for item in tuple(parse_eval_item(row) for row in rows)}


def parse_eval_item(value: JsonValue) -> EvalItem:
    item = require_object(value, "items[]")
    return EvalItem(
        question_no=require_int(item.get("question_no"), "question_no"),
        recognized=require_text(item.get("recognized"), "recognized"),
        status=require_text(item.get("effective_policy"), "effective_policy"),
    )


def select_visible_candidate(scores: tuple[ComponentScore, ...], final_side: str) -> ComponentScore:
    candidates = tuple(score for score in scores if is_digit_candidate(score))
    if not candidates:
        raise PersonSecondPassError("visible digit candidate missing")
    match final_side:
        case "left":
            return min(candidates, key=lambda score: score.bbox.x)
        case "right":
            return max(candidates, key=lambda score: score.bbox.x)
        case unreachable:
            assert_never(unreachable)


def padded_crop(gray: ImageArray, box: BoundingBox, pad: int) -> ImageArray:
    height, width = gray.shape[:2]
    left = max(0, box.x - pad)
    top = max(0, box.y - pad)
    right = min(width, box.x + box.width + pad)
    bottom = min(height, box.y + box.height + pad)
    return gray[top:bottom, left:right]


def enlarge(cv2: OpenCvModule, gray: ImageArray, scale: int) -> ImageArray:
    height, width = gray.shape[:2]
    return cv2.resize(gray, (width * scale, height * scale), interpolation=cv2.INTER_CUBIC)


def assert_cases(cases: tuple[CaseResult, ...]) -> None:
    person_03, person_04 = cases
    if [item.question_no for item in person_03.request_items] != [16, 17]:
        raise PersonSecondPassError("person_03 must queue q016 and q017")
    if person_04.request_items:
        raise PersonSecondPassError("person_04 must not queue already recognized digits")
    if [item.question_no for item in person_04.control_items] != [16, 17]:
        raise PersonSecondPassError("person_04 controls must be q016 and q017")


def output_json(cases: tuple[CaseResult, ...]) -> JsonObject:
    request_count = sum(len(case.request_items) for case in cases)
    return {
        "ok": True,
        "student_facing": False,
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "production_default": "NO_GO",
        "status": "USER_APPROVAL_REQUIRED",
        "case_count": len(cases),
        "request_item_count": request_count,
        "control_item_count": sum(len(case.control_items) for case in cases),
        "future_provider_call_budget_required": 1 if request_count else 0,
        "auto_confirm_allowed_count": 0,
        "cases": [asdict(case) for case in cases],
        "filesystem_path_leak_count": 0,
    }


def read_json_object(path: Path) -> JsonObject:
    return require_object(json.loads(path.read_text(encoding="utf-8-sig")), path.name)


def require_object(value: JsonValue, label: str) -> JsonObject:
    match value:
        case dict():
            return value
        case None | bool() | int() | float() | str() | list():
            raise PersonSecondPassError(f"{label} must be a JSON object")
        case unreachable:
            assert_never(unreachable)


def require_list(value: JsonValue, label: str) -> list[JsonValue]:
    match value:
        case list():
            return value
        case None | bool() | int() | float() | str() | dict():
            raise PersonSecondPassError(f"{label} must be a list")
        case unreachable:
            assert_never(unreachable)


def require_int(value: JsonValue, label: str) -> int:
    match value:
        case int() if not isinstance(value, bool):
            return value
        case None | bool() | float() | str() | list() | dict():
            raise PersonSecondPassError(f"{label} must be an integer")
        case unreachable:
            assert_never(unreachable)


def require_text(value: JsonValue, label: str) -> str:
    match value:
        case str():
            return value.strip()
        case None | bool() | int() | float() | list() | dict():
            raise PersonSecondPassError(f"{label} must be text")
        case unreachable:
            assert_never(unreachable)


def markdown_report(cases: tuple[CaseResult, ...]) -> str:
    lines = ["# OCR Person Second-Pass Request Manifests", "", "| Case | q | Current OCR | Status | Artifact | Action |", "|---|---:|---|---|---|---|"]
    for case in cases:
        for item in case.request_items:
            lines.append(f"| `{case.case_id}` | {item.question_no} | `{item.current_recognized}` | `{item.current_status}` | `{item.artifact_file}` | `{item.action}` |")
        for item in case.control_items:
            lines.append(f"| `{case.case_id}` | {item.question_no} | `{item.current_recognized}` | `{item.current_status}` |  | `{item.reason}` |")
    lines.extend(("", "- Gemini/API calls: 0", "- External OCR API calls: 0", "- `/api/submit-test` calls: 0", "- `#tsSubmit` clicks: 0"))
    lines.extend(("- Auto-confirm allowed: 0", "- answer-key/grading/path leak count: 0"))
    return "\n".join(lines) + "\n"


def leak_count(text: str) -> int:
    lowered = text.lower()
    return sum(1 for token in FORBIDDEN_OUTPUT_TOKENS if token.lower() in lowered)
