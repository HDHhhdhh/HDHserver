from __future__ import annotations

from typing import Final

from ocr_second_pass_batch_request_manifest_model import JsonObject, RequestItem, RequestManifest

FORBIDDEN_OUTPUT_TOKENS: Final[tuple[str, ...]] = (
    "expected",
    "canonical_answer",
    "accepted_answers",
    "correct",
    "incorrect",
    "grading",
    "C:\\",
    "C:/",
    "/c/",
)


def output_json(request: RequestManifest) -> JsonObject:
    return {
        "ok": True,
        "student_facing": False,
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "production_default": "NO_GO",
        "status": "USER_APPROVAL_REQUIRED",
        "provider_call_budget_required_for_future_run": 1,
        "source_payload_name": request.source_payload_name,
        "source_batch_name": request.source_batch_name,
        "batch_item_count": len(request.items),
        "candidate_count": len(request.items),
        "auto_confirm_allowed_count": sum(1 for item in request.items if item.auto_confirm_allowed),
        "request_items": [request_item_json(item) for item in request.items],
        "filesystem_path_leak_count": 0,
    }


def request_item_json(item: RequestItem) -> JsonObject:
    return {
        "question_no": item.question_no,
        "current_recognized": item.current_recognized,
        "current_status": item.current_status,
        "warnings": list(item.warnings),
        "artifact_file": item.artifact_file,
        "enlarged_width": item.enlarged_width,
        "enlarged_height": item.enlarged_height,
        "request_scope": item.request_scope,
        "action": item.action,
        "auto_confirm_allowed": item.auto_confirm_allowed,
    }


def markdown_report(request: RequestManifest) -> str:
    lines = [
        "# OCR Second-Pass Batch Request Manifest",
        "",
        "Provider-free request manifest for a future approved q016/q017 enlarged-crop second pass.",
        "",
        "| q | Current OCR | Status | Artifact | Enlarged size | Action |",
        "|---:|---|---|---|---|---|",
    ]
    for item in request.items:
        lines.append(
            f"| {item.question_no} | `{item.current_recognized}` | `{item.current_status}` | "
            f"`{item.artifact_file}` | {item.enlarged_width}x{item.enlarged_height} | `{item.action}` |"
        )
    lines.extend(
        (
            "",
            "- Status: `USER_APPROVAL_REQUIRED`",
            "- Future provider call budget required: 1",
            "- Auto-confirm allowed: 0",
            "- Gemini/API calls now: 0",
            "- External OCR API calls now: 0",
            "- `/api/submit-test` calls: 0",
            "- `#tsSubmit` clicks: 0",
            "- answer-key/grading/path leak count: 0",
        )
    )
    return "\n".join(lines) + "\n"


def leak_count(text: str) -> int:
    lowered = text.lower()
    return sum(1 for token in FORBIDDEN_OUTPUT_TOKENS if token.lower() in lowered)
