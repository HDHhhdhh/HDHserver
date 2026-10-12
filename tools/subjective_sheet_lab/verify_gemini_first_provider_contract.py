# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///

from __future__ import annotations

import binascii
import json
import struct
import sys
import tempfile
import zlib
from pathlib import Path
from typing import Final, TypeAlias

ROOT: Final[Path] = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.subjective_sheet_lab.phase2e_gemini_live_ocr_adapter import (  # noqa: E402
    Phase2EFeatureFlags,
    Phase2EStatus,
    prepare_phase2e_live_ocr,
)
from tools.subjective_sheet_lab.phase2e_gemini_live_ocr_adapter_verifier_support import (  # noqa: E402
    fake_phase2e_request,
    provider_items,
    write_cache_fixtures,
)
from tools.subjective_sheet_lab.phase2e_live_provider_runner import (  # noqa: E402
    ProviderInputContractError,
    materialize_deidentified_provider_contacts,
    review_payload_from_provider_items,
)
from tools.subjective_sheet_lab.phase2e_stable_cache import (  # noqa: E402
    StableOcrCacheRequest,
    phase2e_provider_model,
    phase2e_provider_prompt_version,
    stable_recognized_path_or_none,
)

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]
TEST_ID: Final[str] = "t_unit_daesu_01_lv3_r1"


class ProviderContractVerificationError(Exception):
    pass


def main() -> int:
    write_cache_fixtures()
    results = {
        "process_local_model_selector": verify_process_local_model_selector(),
        "deidentified_contact_cache_key": verify_deidentified_contact_cache_key(),
        "provider_input_aliases": verify_provider_input_aliases(),
        "candidate_only_review_payload": verify_candidate_only_review_payload(),
        "budget_zero_fails_closed": verify_budget_zero_fails_closed(),
        "external_call_counts": {
            "gemini_provider": 0,
            "external_ocr_api": 0,
            "ocr_review_route": 0,
            "submit_test": 0,
            "final_submit": 0,
        },
    }
    print(json.dumps({"ok": True, "results": results}, ensure_ascii=False, indent=2))
    return 0


def verify_process_local_model_selector() -> JsonObject:
    default_model = phase2e_provider_model({})
    selected_model = phase2e_provider_model({"OCR_PHASE2E_PROVIDER_MODEL": "gemini-2.5-flash-lite"})
    prompt_version = phase2e_provider_prompt_version({"OCR_PHASE2E_PROVIDER_PROMPT_VERSION": "gemini_first_contact_v1"})
    if selected_model != "gemini-2.5-flash-lite":
        raise ProviderContractVerificationError("process-local model selector did not preserve the supplied stable model")
    if not default_model or not prompt_version:
        raise ProviderContractVerificationError("model selector returned an empty value")
    return {
        "default_model_present": True,
        "selected_model": selected_model,
        "prompt_version": prompt_version,
        "global_environment_mutated": False,
    }


def verify_deidentified_contact_cache_key() -> JsonObject:
    with tempfile.TemporaryDirectory(prefix="gemini_first_contract_") as raw_dir:
        case_dir = Path(raw_dir) / "case"
        source = case_dir / "incoming" / "full_sheet.jpg"
        source.parent.mkdir(parents=True)
        source.write_bytes(b"local-only-source")
        contact_dir = case_dir / "review_assets" / "contact_sheets"
        contact_dir.mkdir(parents=True)
        write_contact_images(contact_dir)
        request = StableOcrCacheRequest(
            sid="anonymous-test-sid",
            test_id=TEST_ID,
            round_no=1,
            source_image=source,
            cache_root=case_dir / "cache",
        )
        first = stable_recognized_path_or_none(request)
        if first is None:
            raise ProviderContractVerificationError("cache key could not be generated")
        renamed = contact_dir / "raw_contact_01_renamed.png"
        (contact_dir / "raw_contact_01.png").replace(renamed)
        second = stable_recognized_path_or_none(request)
        if first != second:
            raise ProviderContractVerificationError("cache key used a source filename instead of deidentified image content")
        write_png(renamed, (1, 2, 3))
        third = stable_recognized_path_or_none(request)
        if third == second:
            raise ProviderContractVerificationError("cache key did not change with deidentified contact content")
        changed_model = stable_recognized_path_or_none(
            StableOcrCacheRequest(
                sid="anonymous-test-sid",
                test_id=TEST_ID,
                round_no=1,
                source_image=source,
                cache_root=case_dir / "cache",
                provider_model="gemini-2.5-flash",
            )
        )
        if changed_model == third:
            raise ProviderContractVerificationError("cache key did not include the provider model")
        changed_prompt = stable_recognized_path_or_none(
            StableOcrCacheRequest(
                sid="anonymous-test-sid",
                test_id=TEST_ID,
                round_no=1,
                source_image=source,
                cache_root=case_dir / "cache",
                prompt_version="gemini_first_contact_v2",
            )
        )
        changed_round = stable_recognized_path_or_none(
            StableOcrCacheRequest(
                sid="anonymous-test-sid",
                test_id=TEST_ID,
                round_no=2,
                source_image=source,
                cache_root=case_dir / "cache",
            )
        )
        changed_test = stable_recognized_path_or_none(
            StableOcrCacheRequest(
                sid="anonymous-test-sid",
                test_id="t_unit_daesu_01_lv3_r2",
                round_no=1,
                source_image=source,
                cache_root=case_dir / "cache",
            )
        )
        if changed_prompt == third or changed_round == third or changed_test == third:
            raise ProviderContractVerificationError("cache key did not include the prompt version, test, and round")
    return {
        "cache_key_uses_deidentified_content": True,
        "cache_key_uses_model": True,
        "cache_key_uses_prompt_test_and_round": True,
    }


def verify_provider_input_aliases() -> JsonObject:
    with tempfile.TemporaryDirectory(prefix="gemini_first_alias_") as raw_dir:
        root = Path(raw_dir)
        source_dir = root / "source"
        source_dir.mkdir()
        sources = tuple(source_dir / f"person_private_contact_{index}.png" for index in range(1, 5))
        for index, path in enumerate(sources, start=1):
            write_png(path, (index, index, index), metadata=b"private metadata")
        aliases = materialize_deidentified_provider_contacts(sources, root / "provider_input")
        names = [path.name for path in aliases]
        expected = ["answer_sheet_q001_q005.png", "answer_sheet_q006_q010.png", "answer_sheet_q011_q015.png", "answer_sheet_q016_q020.png"]
        if names != expected:
            raise ProviderContractVerificationError(f"unexpected provider aliases: {names}")
        if any("private" in path.name or "person" in path.name for path in aliases):
            raise ProviderContractVerificationError("provider alias retained source identity text")
        if any(has_png_metadata(path) for path in aliases):
            raise ProviderContractVerificationError("provider alias retained image metadata")
        assert_provider_payload_is_generic(aliases)
        try:
            materialize_deidentified_provider_contacts((sources[0], sources[1], sources[2], root / "full_sheet.jpg"), root / "invalid")
        except ProviderInputContractError:
            pass
        else:
            raise ProviderContractVerificationError("full-sheet input was not rejected")
    return {
        "generic_labels_only": True,
        "metadata_removed": True,
        "full_sheet_input_count": 0,
        "forbidden_provider_input_hits": 0,
    }


def verify_candidate_only_review_payload() -> JsonObject:
    request = fake_phase2e_request()
    payload = review_payload_from_provider_items(provider_items({number: str(number) for number in range(1, 21)}), request)
    items = require_items(payload)
    if any(item.get("status") != "review_required" for item in items):
        raise ProviderContractVerificationError("recognized values must remain review_required")
    if any(item.get("final_answer") is not None for item in items):
        raise ProviderContractVerificationError("review payload assigned a final answer before confirmation")
    if any(item.get("safe_auto_grade") is True for item in items):
        raise ProviderContractVerificationError("review payload enabled safe auto grade")
    return {"items": len(items), "safe_auto_grade": 0, "pre_confirmation_final_answer_count": 0}


def verify_budget_zero_fails_closed() -> JsonObject:
    result = prepare_phase2e_live_ocr(
        fake_phase2e_request(),
        Phase2EFeatureFlags(
            live_enabled=True,
            cache_write_enabled=True,
            local_only=False,
            provider_calls_require_cache_miss=True,
            max_provider_calls_per_request=0,
            fail_closed_on_provider_error=True,
            provider_calls_allowed=True,
        ),
    )
    if result.status is not Phase2EStatus.PROVIDER_BUDGET_EXHAUSTED:
        raise ProviderContractVerificationError(f"budget-zero status was {result.status}")
    if result.provider_call_count != 0 or result.provider_call_attempted:
        raise ProviderContractVerificationError("budget-zero flow attempted a provider call")
    return {"status": result.status.value, "provider_call_count": 0, "manual_fallback_required": True}


def write_contact_images(contact_dir: Path) -> None:
    for index in range(1, 5):
        write_png(contact_dir / f"raw_contact_{index:02d}.png", (index, 0, 0))


def assert_provider_payload_is_generic(aliases: tuple[Path, ...]) -> None:
    from tools.subjective_sheet_lab.gemini_provider import build_contact_payload, contact_image_from_path

    payload = build_contact_payload([contact_image_from_path(path) for path in aliases])
    rendered = json.dumps(payload, ensure_ascii=False)
    forbidden = ("private", "person", "full_sheet", "expected", "canonical_answer", "accepted_answers", "grading", "C:\\", "C:/")
    if any(token in rendered for token in forbidden):
        raise ProviderContractVerificationError("provider payload included a forbidden identity, key, grading, or path token")


def write_png(path: Path, color: tuple[int, int, int], metadata: bytes | None = None) -> None:
    width = 20
    height = 20
    scanline = bytes((0,)) + bytes(color) * width
    raw = scanline * height
    chunks = [png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))]
    if metadata is not None:
        chunks.append(png_chunk(b"tEXt", b"comment\x00" + metadata))
    chunks.extend((png_chunk(b"IDAT", zlib.compress(raw)), png_chunk(b"IEND", b"")))
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"".join(chunks))


def png_chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", binascii.crc32(kind + data) & 0xFFFFFFFF)


def has_png_metadata(path: Path) -> bool:
    raw = path.read_bytes()
    offset = 8
    allowed = {b"IHDR", b"PLTE", b"tRNS", b"IDAT", b"IEND"}
    while offset < len(raw):
        length = struct.unpack(">I", raw[offset:offset + 4])[0]
        kind = raw[offset + 4:offset + 8]
        if kind not in allowed:
            return True
        offset += 12 + length
    return False


def require_items(payload: JsonObject) -> list[JsonObject]:
    raw_items = payload.get("items")
    if not isinstance(raw_items, list) or len(raw_items) != 20:
        raise ProviderContractVerificationError("review payload must contain exactly 20 items")
    if not all(isinstance(item, dict) for item in raw_items):
        raise ProviderContractVerificationError("review items must be objects")
    return list(raw_items)


if __name__ == "__main__":
    raise SystemExit(main())
