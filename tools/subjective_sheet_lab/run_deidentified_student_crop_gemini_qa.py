from __future__ import annotations

import argparse
import base64
import json
import os
import re
import struct
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Final, TypeAlias

from PIL import Image, ImageDraw

from tools.subjective_sheet_lab.gemini_provider import (
    DEFAULT_MODEL,
    GEMINI_ENDPOINT,
    ContactImage,
    CropImage,
    build_gemini_payload,
    build_contact_payload,
    extract_response_text,
    parse_recognized_items,
    parse_contact_items,
)
from tools.subjective_sheet_lab.ocr_answer_mode_policy import (
    answer_mode_auto_grade_warning,
    answer_mode_for_question,
)

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]

QUESTION_COUNT: Final[int] = 20
CONTACT_GROUP_SIZE: Final[int] = 5
TEST_ID: Final[str] = "t_unit_daesu_01_lv3_r1"
GENERIC_CASE_PREFIX: Final[str] = "anon_crop_case_"
FORBIDDEN_PROVIDER_TEXT: Final[tuple[str, ...]] = (
    "answer key",
    "answer_key",
    "expected",
    "canonical_answer",
    "accepted_answers",
    "grading",
    "student id",
    "student_id",
    "sid=",
    "assignment",
    "attendance",
    "memo",
)
PATH_RE: Final[re.Pattern[str]] = re.compile(r"(?:[A-Za-z]:[\\/]|\\\\|/Users/|/home/|/server(?:-ocr)?/)", re.IGNORECASE)
PNG_FORBIDDEN_CHUNKS: Final[frozenset[bytes]] = frozenset((b"tEXt", b"zTXt", b"iTXt", b"eXIf"))


@dataclass(frozen=True, slots=True)
class Config:
    command: str
    crop_dir: Path
    human_path: Path | None
    out_dir: Path
    case_id: str
    max_calls: int
    question: int | None


class QaError(RuntimeError):
    pass


def main() -> int:
    config = parse_args()
    if config.command == "prepare":
        summary = prepare_pack(config)
    elif config.command == "provider":
        summary = run_provider(config)
    elif config.command == "second-pass":
        summary = run_second_pass(config)
    elif config.command == "finalize":
        summary = finalize_outputs(config)
    else:
        raise QaError(f"unsupported command: {config.command}")
    print(json.dumps(summary, ensure_ascii=True, sort_keys=True))
    return 0


def parse_args() -> Config:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("prepare", "provider", "second-pass", "finalize"))
    parser.add_argument("--crop-dir", required=True, type=Path)
    parser.add_argument("--human", type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--max-calls", type=int, default=5)
    parser.add_argument("--question", type=int)
    args = parser.parse_args()
    case_id = str(args.case_id).strip()
    if not re.fullmatch(r"anon_crop_case_[a-z0-9_]+", case_id):
        raise QaError("case_id must be an anonymous ASCII label")
    if not 1 <= int(args.max_calls) <= 5:
        raise QaError("max_calls must be between 1 and 5")
    return Config(
        command=str(args.command),
        crop_dir=Path(args.crop_dir).resolve(),
        human_path=Path(args.human).resolve() if args.human else None,
        out_dir=Path(args.out_dir).resolve(),
        case_id=case_id,
        max_calls=int(args.max_calls),
        question=int(args.question) if args.question is not None else None,
    )


def prepare_pack(config: Config) -> JsonObject:
    source_paths = expected_source_paths(config.crop_dir)
    pack_dir = config.out_dir / "deidentified_pack"
    crop_out = pack_dir / "crops"
    contact_out = pack_dir / "contact_sheets"
    crop_out.mkdir(parents=True, exist_ok=False)
    contact_out.mkdir(parents=True, exist_ok=False)

    deidentified: list[Path] = []
    manifest_items: list[JsonObject] = []
    for question_no, source in enumerate(source_paths, start=1):
        target = crop_out / f"answer_sheet_q{question_no:03d}.png"
        reencode_png(source, target)
        require_metadata_free_png(target)
        deidentified.append(target)
        manifest_items.append(
            {
                "case_id": config.case_id,
                "question_no": question_no,
                "generic_label": f"answer_sheet_q{question_no:03d}",
            }
        )

    contacts = create_contact_sheets(deidentified, contact_out)
    for path in contacts:
        require_metadata_free_png(path)

    manifest: JsonObject = {
        "case_id": config.case_id,
        "items": manifest_items,
    }
    write_json(pack_dir / "transmission_manifest.json", manifest)
    payload_preview = provider_payload(contacts)
    assert_provider_payload_safe(payload_preview)
    gate: JsonObject = {
        "classification": "PASS_DEIDENTIFICATION_GATE",
        "case_id": config.case_id,
        "crop_count": len(deidentified),
        "contact_sheet_count": len(contacts),
        "full_sheet_in_pack": False,
        "metadata_chunk_hits": 0,
        "provider_payload_forbidden_text_hits": 0,
        "provider_payload_path_hits": 0,
        "provider_call_count": 0,
        "contact_labels": [path.name for path in contacts],
    }
    write_json(config.out_dir / "deidentification_gate.json", gate)
    return gate


def expected_source_paths(crop_dir: Path) -> list[Path]:
    paths = [crop_dir / f"q{question_no:03d}.png" for question_no in range(1, QUESTION_COUNT + 1)]
    missing = [path.name for path in paths if not path.is_file()]
    if missing:
        raise QaError(f"missing crop count: {len(missing)}")
    return paths


def reencode_png(source: Path, target: Path) -> None:
    with Image.open(source) as image:
        clean = image.convert("RGB")
        clean.save(target, format="PNG", optimize=True)


def require_metadata_free_png(path: Path) -> None:
    with Image.open(path) as image:
        if image.info:
            raise QaError(f"image metadata remains in {path.name}: {sorted(image.info)}")
    chunks = png_chunk_names(path.read_bytes())
    forbidden = chunks & PNG_FORBIDDEN_CHUNKS
    if forbidden:
        names = ",".join(sorted(chunk.decode("ascii") for chunk in forbidden))
        raise QaError(f"forbidden PNG metadata chunks in {path.name}: {names}")


def png_chunk_names(data: bytes) -> frozenset[bytes]:
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise QaError("deidentified image is not PNG")
    offset = 8
    chunks: set[bytes] = set()
    while offset + 12 <= len(data):
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        chunk_type = data[offset + 4 : offset + 8]
        chunks.add(chunk_type)
        offset += 12 + length
        if chunk_type == b"IEND":
            break
    return frozenset(chunks)


def create_contact_sheets(crops: list[Path], out_dir: Path) -> list[Path]:
    output: list[Path] = []
    for start in range(0, QUESTION_COUNT, CONTACT_GROUP_SIZE):
        group = crops[start : start + CONTACT_GROUP_SIZE]
        opened: list[Image.Image] = []
        try:
            for path in group:
                with Image.open(path) as image:
                    opened.append(image.convert("RGB"))
            max_width = max(image.width for image in opened)
            row_height = max(image.height for image in opened) + 36
            canvas = Image.new("RGB", (max_width + 140, row_height * len(opened)), "white")
            draw = ImageDraw.Draw(canvas)
            for offset, image in enumerate(opened):
                question_no = start + offset + 1
                y = offset * row_height
                draw.text((16, y + 10), f"q{question_no:03d}", fill="black")
                canvas.paste(image, (120, y + 4))
            first = start + 1
            last = start + len(group)
            target = out_dir / f"answer_sheet_q{first:03d}_q{last:03d}.png"
            canvas.save(target, format="PNG", optimize=True)
            output.append(target)
        finally:
            for image in opened:
                image.close()
    return output


def provider_payload(contact_paths: list[Path]) -> JsonObject:
    contacts = [contact_from_path(path) for path in contact_paths]
    payload = build_contact_payload(contacts, test_id=None, numeric_only=False)
    if not isinstance(payload, dict):
        raise QaError("provider payload must be an object")
    return payload


def contact_from_path(path: Path) -> ContactImage:
    questions = contact_questions(path.name)
    return ContactImage(
        path=path,
        mime_type="image/png",
        data_base64=base64.b64encode(path.read_bytes()).decode("ascii"),
        questions=questions,
    )


def contact_questions(name: str) -> tuple[int, ...]:
    match = re.fullmatch(r"answer_sheet_q(\d{3})_q(\d{3})\.png", name)
    if match is None:
        raise QaError(f"invalid generic contact-sheet filename: {name}")
    first, last = int(match.group(1)), int(match.group(2))
    return tuple(range(first, last + 1))


def assert_provider_payload_safe(payload: JsonObject) -> None:
    strings: list[str] = []
    collect_payload_strings(payload, strings)
    for text in strings:
        lowered = text.lower()
        if any(token in lowered for token in FORBIDDEN_PROVIDER_TEXT):
            raise QaError("forbidden semantic field found in provider payload")
        if PATH_RE.search(text):
            raise QaError("local filesystem path found in provider payload")
    serialized = json.dumps(payload, ensure_ascii=False)
    if config_like_field_hit(serialized):
        raise QaError("forbidden provider field name found")


def collect_payload_strings(value: JsonValue, output: list[str], key: str = "") -> None:
    if isinstance(value, dict):
        for child_key, child in value.items():
            output.append(child_key)
            collect_payload_strings(child, output, child_key)
    elif isinstance(value, list):
        for child in value:
            collect_payload_strings(child, output, key)
    elif isinstance(value, str) and key != "data":
        output.append(value)


def config_like_field_hit(text: str) -> bool:
    lowered = text.lower()
    return any(f'"{token}"' in lowered for token in ("expected", "canonical_answer", "accepted_answers", "grading"))


def run_provider(config: Config) -> JsonObject:
    gate = read_object(config.out_dir / "deidentification_gate.json")
    if gate.get("classification") != "PASS_DEIDENTIFICATION_GATE":
        raise QaError("deidentification gate did not pass")
    contact_paths = sorted((config.out_dir / "deidentified_pack" / "contact_sheets").glob("*.png"))
    if len(contact_paths) != 4:
        raise QaError("expected four deidentified contact sheets")
    payload = provider_payload(contact_paths)
    assert_provider_payload_safe(payload)
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        raise QaError("process-local GEMINI_API_KEY is missing")
    response, call_count, retry_count = post_provider(payload, key, DEFAULT_MODEL, config.max_calls)
    text = extract_response_text(response)
    contacts = [contact_from_path(path) for path in contact_paths]
    parsed = parse_contact_items(text, contacts)
    by_question = {item.question: item.recognized.strip() or "?" for item in parsed}
    items: list[JsonObject] = []
    for question_no in range(1, QUESTION_COUNT + 1):
        present = question_no in by_question
        recognized = by_question.get(question_no, "?")
        completion = "pending" if not present else ("completed_unresolved" if recognized == "?" else "completed_recognized")
        items.append(
            {
                "question": question_no,
                "recognized": recognized,
                "completion_status": completion,
                "status": "review_required",
                "safe_auto_grade": False,
                "final_answer": None,
            }
        )
    recognized_payload: JsonObject = {
        "case_id": config.case_id,
        "model": DEFAULT_MODEL,
        "provider_call_count": call_count,
        "retry_count": retry_count,
        "items": items,
    }
    assert_student_safe_output(recognized_payload)
    write_json(config.out_dir / "recognized.json", recognized_payload)
    provider_summary: JsonObject = {
        "classification": "PROVIDER_CALL_COMPLETED",
        "provider_call_count": call_count,
        "retry_count": retry_count,
        "recognized_count": sum(1 for item in items if item["completion_status"] == "completed_recognized"),
        "completed_unresolved": sum(1 for item in items if item["completion_status"] == "completed_unresolved"),
        "pending": sum(1 for item in items if item["completion_status"] == "pending"),
        "http_status": 200,
    }
    write_json(config.out_dir / "provider_summary.json", provider_summary)
    return provider_summary


def run_second_pass(config: Config) -> JsonObject:
    if config.question is None or not 1 <= config.question <= QUESTION_COUNT:
        raise QaError("second-pass requires --question 1..20")
    provider_summary = read_object(config.out_dir / "provider_summary.json")
    prior_calls = provider_summary.get("provider_call_count")
    if not isinstance(prior_calls, int) or isinstance(prior_calls, bool):
        raise QaError("provider summary call count is invalid")
    if prior_calls >= config.max_calls:
        raise QaError("provider call budget exhausted before second pass")
    if config.human_path is None:
        raise QaError("second-pass requires --human")
    human = read_object(config.human_path)
    human_items = human.get("answers")
    if not isinstance(human_items, list):
        raise QaError("human transcription answers are missing")
    human_item = next(
        (item for item in human_items if isinstance(item, dict) and item.get("question_no") == config.question),
        None,
    )
    if not isinstance(human_item, dict) or str(human_item.get("confidence") or "").strip().lower() != "high":
        raise QaError("second-pass question does not have high-confidence human transcription")
    recognized = read_object(config.out_dir / "recognized.json")
    items = require_items(recognized, "recognized")
    first_item = next((item for item in items if item.get("question") == config.question), None)
    if not isinstance(first_item, dict):
        raise QaError("first-pass item is missing")
    first_value = require_text(first_item.get("recognized"), "recognized")
    human_value = require_text(human_item.get("human_answer"), "human_answer")
    if normalize_answer(first_value) == normalize_answer(human_value):
        raise QaError("second-pass question is not a first-pass mismatch")

    crop_path = config.out_dir / "deidentified_pack" / "crops" / f"answer_sheet_q{config.question:03d}.png"
    require_metadata_free_png(crop_path)
    crop = CropImage(
        question=config.question,
        path=crop_path,
        mime_type="image/png",
        data_base64=base64.b64encode(crop_path.read_bytes()).decode("ascii"),
    )
    payload = build_gemini_payload([crop], numeric_only=False)
    assert_provider_payload_safe(payload)
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        raise QaError("process-local GEMINI_API_KEY is missing")
    response, call_count, retry_count = post_provider(payload, key, DEFAULT_MODEL, config.max_calls - prior_calls)
    parsed = parse_recognized_items(extract_response_text(response), [crop])
    second_value = parsed[0].recognized.strip() or "?"
    output: JsonObject = {
        "question_no": config.question,
        "recognized": second_value,
        "agrees_with_first_pass": normalize_answer(second_value) == normalize_answer(first_value),
        "matches_human_transcription": normalize_answer(second_value) == normalize_answer(human_value),
        "candidate_promotion_allowed": False,
        "status": "review_required",
        "provider_call_count": call_count,
        "retry_count": retry_count,
    }
    assert_student_safe_output(output)
    write_json(config.out_dir / "second_pass.json", output)
    total_calls = prior_calls + call_count
    provider_summary["provider_call_count"] = total_calls
    provider_summary["retry_count"] = int(provider_summary.get("retry_count") or 0) + retry_count
    provider_summary["second_pass_question_count"] = 1
    write_json(config.out_dir / "provider_summary.json", provider_summary)
    return {
        "classification": "SECOND_PASS_COMPLETED_REVIEW_GATED",
        "question_count": 1,
        "provider_call_count_this_stage": call_count,
        "provider_call_count_total": total_calls,
        "retry_count_this_stage": retry_count,
        "agrees_with_first_pass": output["agrees_with_first_pass"],
        "matches_human_transcription": output["matches_human_transcription"],
        "candidate_promotion_allowed": False,
    }


def post_provider(payload: JsonObject, api_key: str, model: str, max_calls: int) -> tuple[JsonObject, int, int]:
    request = urllib.request.Request(
        GEMINI_ENDPOINT.format(model=model),
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
        method="POST",
    )
    call_count = 0
    retry_count = 0
    while call_count < max_calls:
        call_count += 1
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                decoded = json.loads(response.read().decode("utf-8"))
            if not isinstance(decoded, dict):
                raise QaError("provider response root was not an object")
            return decoded, call_count, retry_count
        except urllib.error.HTTPError as error:
            if error.code not in {429, 503} or retry_count >= 1 or call_count >= max_calls:
                raise
            retry_count += 1
            time.sleep(4)
    raise QaError("provider call budget exhausted")


def finalize_outputs(config: Config) -> JsonObject:
    if config.human_path is None:
        raise QaError("--human is required for finalize")
    recognized = read_object(config.out_dir / "recognized.json")
    recognized_items = require_items(recognized, "recognized")
    human = read_object(config.human_path)
    human_items = human.get("answers")
    if not isinstance(human_items, list) or len(human_items) != QUESTION_COUNT:
        raise QaError("human transcription must contain 20 answers")
    human_by_question: dict[int, tuple[str, str, str]] = {}
    for raw in human_items:
        if not isinstance(raw, dict):
            raise QaError("human transcription item must be an object")
        question_no = raw.get("question_no")
        answer = raw.get("human_answer")
        confidence = raw.get("confidence")
        notes = raw.get("notes")
        if (
            not isinstance(question_no, int)
            or not isinstance(answer, str)
            or not isinstance(confidence, str)
            or not isinstance(notes, str)
        ):
            raise QaError("human transcription item schema mismatch")
        human_by_question[question_no] = (answer.strip(), confidence.strip().lower(), notes.strip().lower())

    human_quality_blocked = {
        question_no
        for question_no, (_, confidence, notes) in human_by_question.items()
        if confidence == "low" or any(token in notes for token in ("erase", "overwrit", "unclear", "multiple"))
    }

    second_pass = read_optional_object(config.out_dir / "second_pass.json")
    second_pass_disagreement_question = None
    if second_pass is not None and second_pass.get("agrees_with_first_pass") is False:
        raw_question = second_pass.get("question_no")
        if isinstance(raw_question, int) and not isinstance(raw_question, bool):
            second_pass_disagreement_question = raw_question

    comparisons: list[JsonObject] = []
    matched = 0
    eligible = 0
    high_matched = 0
    high_eligible = 0
    review_items: list[JsonObject] = []
    for raw in recognized_items:
        question_no = require_question(raw)
        recognized_value = require_text(raw.get("recognized"), "recognized")
        human_value, human_confidence, _human_notes = human_by_question[question_no]
        is_recognized = recognized_value != "?" and raw.get("completion_status") != "pending"
        matches = is_recognized and normalize_answer(recognized_value) == normalize_answer(human_value)
        if is_recognized:
            eligible += 1
            matched += int(matches)
        if is_recognized and human_confidence == "high":
            high_eligible += 1
            high_matched += int(matches)
        comparisons.append(
            {
                "question_no": question_no,
                "recognized": recognized_value,
                "human_transcription": human_value,
                "human_confidence": human_confidence,
                "ocr_matches_human": matches,
            }
        )
        review_items.append(
            review_item(
                question_no,
                recognized_value,
                raw.get("completion_status"),
                second_pass_disagreement_question,
                human_quality_blocked,
            )
        )

    candidate_count = sum(1 for item in review_items if isinstance(item.get("candidates"), list) and item["candidates"])
    eval_summary: JsonObject = {
        "case_id": config.case_id,
        "question_count": QUESTION_COUNT,
        "recognized_count": eligible,
        "ocr_vs_human_matched": matched,
        "ocr_vs_human_accuracy": ratio(matched, eligible),
        "high_confidence_count": high_eligible,
        "high_confidence_matched": high_matched,
        "high_confidence_accuracy": ratio(high_matched, high_eligible),
        "completed_unresolved": sum(1 for item in recognized_items if item.get("completion_status") == "completed_unresolved"),
        "pending_missing": sum(1 for item in recognized_items if item.get("completion_status") == "pending"),
        "review_required": QUESTION_COUNT,
        "partial_fill_candidate_count": candidate_count,
        "wrong_safe_auto_grade": 0,
        "second_pass_question_count": 1 if second_pass is not None else 0,
        "second_pass_disagreement": second_pass_disagreement_question is not None,
        "items": comparisons,
    }
    review_payload: JsonObject = {
        "source": "deidentified_crop_teacher_confirmation",
        "test_id": TEST_ID,
        "round": "1",
        "problem_count": QUESTION_COUNT,
        "items": review_items,
    }
    assert_student_safe_output(review_payload)
    write_json(config.out_dir / "human_transcription_eval.json", eval_summary)
    write_json(config.out_dir / "review_payload.json", review_payload)
    final_summary: JsonObject = {
        "classification": accuracy_classification(eval_summary),
        "recognized_count": eligible,
        "ocr_vs_human_matched": matched,
        "ocr_vs_human_accuracy": eval_summary["ocr_vs_human_accuracy"],
        "high_confidence_count": high_eligible,
        "high_confidence_matched": high_matched,
        "high_confidence_accuracy": eval_summary["high_confidence_accuracy"],
        "partial_fill_candidate_count": candidate_count,
        "wrong_safe_auto_grade": 0,
        "review_item_count": QUESTION_COUNT,
        "second_pass_question_count": 1 if second_pass is not None else 0,
        "second_pass_disagreement": second_pass_disagreement_question is not None,
    }
    write_json(config.out_dir / "evaluation_summary.json", final_summary)
    return final_summary


def review_item(
    question_no: int,
    recognized: str,
    completion_status: JsonValue,
    second_pass_disagreement_question: int | None,
    human_quality_blocked: set[int],
) -> JsonObject:
    warning = answer_mode_auto_grade_warning(question_no, recognized, TEST_ID)
    candidate = None
    if (
        question_no != second_pass_disagreement_question
        and question_no not in human_quality_blocked
        and completion_status != "pending"
        and recognized != "?"
        and warning is None
    ):
        mode = answer_mode_for_question(TEST_ID, question_no)
        if mode == "choice_number" and recognized in {"1", "2", "3", "4", "5"}:
            candidate = recognized
        elif mode == "answer_value":
            candidate = recognized
    if question_no == second_pass_disagreement_question:
        warnings: list[JsonValue] = ["second_pass_disagreement_requires_direct_input"]
    elif question_no in human_quality_blocked:
        warnings = ["low_confidence_or_overwritten_requires_direct_input"]
    else:
        warnings = [warning or "teacher_confirmation_required"]
    return {
        "question_no": question_no,
        "status": "review_required",
        "recognized": recognized,
        "warnings": warnings,
        "candidates": [candidate] if candidate is not None else [],
        "direct_input_allowed": True,
        "final_answer": None,
        "source": None,
    }


def assert_student_safe_output(payload: JsonObject) -> None:
    serialized = json.dumps(payload, ensure_ascii=False)
    if PATH_RE.search(serialized):
        raise QaError("student-facing payload contains a local filesystem path")
    if config_like_field_hit(serialized):
        raise QaError("student-facing payload contains a forbidden grading field")


def require_items(payload: JsonObject, label: str) -> list[JsonObject]:
    value = payload.get("items")
    if not isinstance(value, list) or len(value) != QUESTION_COUNT:
        raise QaError(f"{label} must contain exactly 20 items")
    output: list[JsonObject] = []
    for item in value:
        if not isinstance(item, dict):
            raise QaError(f"{label} item must be an object")
        output.append(item)
    return output


def require_question(item: JsonObject) -> int:
    value = item.get("question")
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= QUESTION_COUNT:
        raise QaError("question must be 1..20")
    return value


def require_text(value: JsonValue, label: str) -> str:
    if not isinstance(value, str):
        raise QaError(f"{label} must be text")
    return value.strip() or "?"


def normalize_answer(value: str) -> str:
    return re.sub(r"\s+", "", value).lower()


def ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def accuracy_classification(summary: JsonObject) -> str:
    value = summary.get("high_confidence_accuracy")
    if not isinstance(value, (int, float)):
        return "NO_GO"
    if value >= 0.8:
        return "PASS_DEIDENTIFIED_CROP_ONLY_GEMINI_QA_PENDING_UI"
    if value >= 0.7:
        return "CONDITIONAL_GO_REVIEW_GATED_PENDING_UI"
    return "NO_GO"


def read_object(path: Path) -> JsonObject:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as error:
        raise QaError(f"cannot read {path.name}: {error}") from error
    if not isinstance(value, dict):
        raise QaError(f"{path.name} must be an object")
    return value


def read_optional_object(path: Path) -> JsonObject | None:
    return read_object(path) if path.is_file() else None


def write_json(path: Path, payload: JsonObject) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
