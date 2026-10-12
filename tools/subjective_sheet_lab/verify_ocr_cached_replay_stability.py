from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Final, TypeAlias

LAB: Final[Path] = Path(__file__).resolve().parent
PAYLOAD_PATH: Final[Path] = LAB / "gangyuhyun849_live_review_payload_cache_replay_20260703.json"
REPORT_JSON: Final[Path] = LAB / "ocr_cached_replay_stability.json"
REPORT_MD: Final[Path] = LAB / "ocr_cached_replay_stability.md"

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]


class CachedReplayStabilityError(Exception):
    pass


def main() -> int:
    payload = require_object(read_json(PAYLOAD_PATH).get("review_payload"), "review_payload")
    items = require_array(payload.get("items"), "review_payload.items")
    canonical = canonical_payload(payload)
    answers_text = answers_text_from_safe_items(items)
    output = {
        "ok": True,
        "provider_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "payload_path": PAYLOAD_PATH.name,
        "item_count": len(items),
        "question_sequence_ok": question_sequence(items) == list(range(1, 21)),
        "review_payload_sha256": sha256_text(canonical),
        "safe_answers_text_sha256": sha256_text(answers_text),
        "safe_answers_line_count": len(answers_text.splitlines()) if answers_text else 0,
        "review_required_count": sum(1 for item in items if require_object(item, "item").get("status") == "review_required"),
    }
    if output["question_sequence_ok"] is not True or output["item_count"] != 20:
        raise CachedReplayStabilityError("cached replay payload must contain q001..q020")
    REPORT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown(output), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def read_json(path: Path) -> JsonObject:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    return require_object(payload, str(path))


def canonical_payload(payload: JsonObject) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def answers_text_from_safe_items(items: list[JsonValue]) -> str:
    values: list[str] = []
    for item in items:
        raw = require_object(item, "item")
        final_answer = raw.get("final_answer")
        values.append(final_answer if isinstance(final_answer, str) else "")
    return "\n".join(values)


def question_sequence(items: list[JsonValue]) -> list[int]:
    numbers: list[int] = []
    for item in items:
        question_no = require_object(item, "item").get("question_no")
        if isinstance(question_no, int) and not isinstance(question_no, bool):
            numbers.append(question_no)
    return numbers


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def require_object(value: JsonValue, label: str) -> JsonObject:
    if not isinstance(value, dict):
        raise CachedReplayStabilityError(f"{label} must be a JSON object")
    return value


def require_array(value: JsonValue, label: str) -> list[JsonValue]:
    if not isinstance(value, list):
        raise CachedReplayStabilityError(f"{label} must be a JSON array")
    return value


def markdown(output: JsonObject) -> str:
    return "\n".join(
        [
            "# OCR Cached Replay Stability",
            "",
            "- provider calls: 0",
            "- submit-test calls: 0",
            f"- payload: `{output['payload_path']}`",
            f"- item count: {output['item_count']}",
            f"- question sequence ok: {output['question_sequence_ok']}",
            f"- review_required count: {output['review_required_count']}",
            f"- review payload sha256: `{output['review_payload_sha256']}`",
            f"- safe answersText sha256: `{output['safe_answers_text_sha256']}`",
            "",
        ],
    )


if __name__ == "__main__":
    raise SystemExit(main())
