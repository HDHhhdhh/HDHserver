from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.quick_printer_export import (
    MAPPING_VERSION,
    build_test_definitions,
    file_sha256,
    normalize_subject,
    normalize_term,
    read_registered_catalog,
    test_definitions_sha256,
)


DEFAULT_CATALOG = ROOT / "core" / "resources" / "quick_printer_registered_tests.csv"
DEFAULT_TESTS_CONFIG = ROOT / "tests-config.json"
DEFAULT_OUTPUT = ROOT / "core" / "resources" / "quick_printer_test_mapping.json"

CATALOG_CATEGORY_KEYS = {
    "단원평가": "UNIT",
    "복습테스트": "REVIEW",
    "학군지기출": "SCHOOL_PAST",
    "일산기출": "ILSAN_PAST",
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _difficulty(value: Any) -> str:
    compact = re.sub(r"\s+", "", _text(value)).lower()
    match = re.fullmatch(r"lv\.?([3-6])", compact)
    if match:
        return f"Lv.{match.group(1)}"
    return _text(value)


def _term(value: Any) -> str:
    raw = _text(value)
    if not raw:
        return ""
    return normalize_term(raw)


def _filename(value: Any, *, drop_print_suffix: bool = False) -> str:
    name = re.sub(r"\s+", " ", _text(value)).casefold()
    if drop_print_suffix:
        name = re.sub(r"\s*인쇄(?=\.pdf$)", "", name)
    return name


def _positive_int(value: Any) -> int | None:
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _catalog_meta(row: dict) -> dict:
    return {
        "materialId": _text(row.get("자료ID")),
        "categoryKey": CATALOG_CATEGORY_KEYS.get(_text(row.get("자료유형")), ""),
        "subject": normalize_subject(row.get("과목")),
        "difficulty": _difficulty(row.get("레벨")),
        "term": _term(row.get("시험구분")),
        "round": _text(row.get("회차")),
        "individualNumber": _positive_int(row.get("개별번호")),
        "displayName": _text(row.get("표시이름")),
        "fileName": _text(row.get("파일명")),
        "relativePath": _text(row.get("상대경로")),
        "row": row,
    }


def _candidate_view(meta: dict) -> dict:
    return {
        "materialId": meta["materialId"],
        "displayName": meta["displayName"],
        "relativePath": meta["relativePath"],
    }


def _server_file_name(definition: dict) -> str:
    problem_file = _text(definition.get("problemFile"))
    return problem_file or f"{_text(definition.get('name'))}.pdf"


def _base_candidates(definition: dict, catalog: list[dict]) -> list[dict]:
    return [
        row
        for row in catalog
        if row["categoryKey"] == definition["categoryKey"]
        and row["subject"] == definition["curriculum"]
    ]


def _related_candidates(definition: dict, catalog: list[dict]) -> list[dict]:
    candidates = _base_candidates(definition, catalog)
    if definition["categoryKey"] in ("SCHOOL_PAST", "ILSAN_PAST"):
        same_term = [row for row in candidates if row["term"] == definition["term"]]
        if same_term:
            candidates = same_term
    wanted_round = _text(definition.get("round"))
    round_candidates = [
        row
        for row in candidates
        if re.search(rf"(?<!\d){re.escape(wanted_round)}\s*회차", row["displayName"])
        or re.search(rf"(?<!\d){re.escape(wanted_round)}\s*회차", row["fileName"])
    ]
    if round_candidates:
        candidates = round_candidates
    return candidates[:8]


def _issue(
    definition: dict,
    *,
    code: str,
    reason: str,
    candidates: list[dict],
    match_method: str,
) -> dict:
    return {
        "code": code,
        "reason": reason,
        "matchMethod": match_method,
        "candidates": [_candidate_view(candidate) for candidate in candidates[:10]],
    }


def _mapping(candidate: dict, *, match_method: str) -> dict:
    return {
        "materialId": candidate["materialId"],
        "matchMethod": match_method,
    }


def build_mapping_bundle(tests_config: dict, catalog_rows: list[dict], catalog_hash: str) -> dict:
    definitions = build_test_definitions(tests_config)
    catalog = [_catalog_meta(row) for row in catalog_rows]
    mappings: dict[str, dict] = {}
    issues: dict[str, dict] = {}

    server_unit_groups: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    catalog_unit_groups: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for definition in definitions:
        if definition["categoryKey"] == "UNIT":
            server_unit_groups[
                (definition["curriculum"], definition["difficulty"], definition["round"])
            ].append(definition)
    for row in catalog:
        if row["categoryKey"] == "UNIT":
            catalog_unit_groups[(row["subject"], row["difficulty"], row["round"])].append(row)

    unit_candidates_by_id: dict[str, dict] = {}
    unit_group_failures: dict[tuple[str, str, str], str] = {}
    for group_key in sorted(set(server_unit_groups) | set(catalog_unit_groups)):
        server_rows = sorted(
            server_unit_groups.get(group_key, []),
            key=lambda row: (_positive_int(row.get("sourceOrder")) or 10**9, row["id"]),
        )
        printer_rows = sorted(
            catalog_unit_groups.get(group_key, []),
            key=lambda row: row["individualNumber"] or 10**9,
        )
        server_orders = [_positive_int(row.get("sourceOrder")) for row in server_rows]
        printer_orders = [row["individualNumber"] for row in printer_rows]
        if len(server_rows) != len(printer_rows):
            unit_group_failures[group_key] = (
                f"단원평가 그룹 수량이 다릅니다(서버 {len(server_rows)}개, 등록 목록 {len(printer_rows)}개)."
            )
            continue
        if not server_rows or None in server_orders or len(server_orders) != len(set(server_orders)):
            unit_group_failures[group_key] = "서버 단원평가 그룹의 sourceOrder가 비어 있거나 중복되었습니다."
            continue
        if printer_orders != list(range(1, len(printer_rows) + 1)):
            unit_group_failures[group_key] = "등록 단원평가 그룹의 개별번호가 1부터 연속되지 않습니다."
            continue
        for definition, candidate in zip(server_rows, printer_rows):
            unit_candidates_by_id[definition["id"]] = candidate

    for definition in definitions:
        test_id = definition["id"]
        category_key = definition["categoryKey"]
        candidates: list[dict]
        match_method: str

        if category_key == "UNIT":
            group_key = (definition["curriculum"], definition["difficulty"], definition["round"])
            candidate = unit_candidates_by_id.get(test_id)
            if candidate:
                mappings[test_id] = _mapping(
                    candidate,
                    match_method="unit_group_position",
                )
                continue
            candidates = catalog_unit_groups.get(group_key, [])[:8]
            issues[test_id] = _issue(
                definition,
                code="unit_group_not_exact",
                reason=unit_group_failures.get(group_key, "단원평가 그룹을 정확히 대조할 수 없습니다."),
                candidates=candidates,
                match_method="unit_group_position",
            )
            continue

        candidates = _base_candidates(definition, catalog)
        server_file = _server_file_name(definition)
        if category_key == "REVIEW":
            match_method = "exact_subject_difficulty_filename"
            candidates = [row for row in candidates if row["difficulty"] == definition["difficulty"]]
            candidates = [row for row in candidates if _filename(row["fileName"]) == _filename(server_file)]
        elif category_key == "SCHOOL_PAST":
            match_method = "exact_subject_term_filename"
            candidates = [row for row in candidates if row["term"] == definition["term"]]
            candidates = [
                row
                for row in candidates
                if _filename(row["fileName"], drop_print_suffix=True)
                == _filename(server_file, drop_print_suffix=True)
            ]
        else:
            match_method = "exact_subject_term_filename"
            candidates = [row for row in candidates if row["term"] == definition["term"]]
            candidates = [row for row in candidates if _filename(row["fileName"]) == _filename(server_file)]

        if len(candidates) == 1:
            mappings[test_id] = _mapping(
                candidates[0],
                match_method=match_method,
            )
        elif len(candidates) > 1:
            issues[test_id] = _issue(
                definition,
                code="ambiguous_registered_material",
                reason="같은 서버 시험과 정확히 일치하는 등록 자료가 여러 개입니다.",
                candidates=candidates,
                match_method=match_method,
            )
        else:
            issues[test_id] = _issue(
                definition,
                code="registered_material_not_found",
                reason="서버 시험과 정확히 일치하는 등록 자료가 없습니다.",
                candidates=_related_candidates(definition, catalog),
                match_method=match_method,
            )

    material_owners: dict[str, list[str]] = defaultdict(list)
    for test_id, mapping in mappings.items():
        material_owners[mapping["materialId"]].append(test_id)
    for material_id, owner_ids in material_owners.items():
        if len(owner_ids) == 1:
            continue
        candidate = next((row for row in catalog if row["materialId"] == material_id), None)
        for test_id in owner_ids:
            mapping = mappings.pop(test_id)
            definition = next(row for row in definitions if row["id"] == test_id)
            issues[test_id] = _issue(
                definition,
                code="duplicate_material_mapping",
                reason="하나의 자료ID가 여러 서버 시험에 매핑되어 자동 선택할 수 없습니다.",
                candidates=[candidate] if candidate else [],
                match_method=mapping["matchMethod"],
            )

    status_by_category: dict[str, Counter] = defaultdict(Counter)
    for definition in definitions:
        status_by_category[definition["categoryKey"]][
            "matched" if definition["id"] in mappings else issues[definition["id"]]["code"]
        ] += 1
    catalog_counts = Counter(row["categoryKey"] for row in catalog)
    material_ids = [row["materialId"] for row in catalog]
    duplicate_material_ids = sorted(
        material_id for material_id, count in Counter(material_ids).items() if not material_id or count != 1
    )

    return {
        "version": MAPPING_VERSION,
        "catalog": {
            "fileName": "quick_printer_registered_tests.csv",
            "sha256": catalog_hash,
            "rowCount": len(catalog_rows),
            "uniqueMaterialIdCount": len(set(material_ids)),
            "duplicateMaterialIdCount": len(duplicate_material_ids),
            "countsByCategory": {
                key: catalog_counts.get(key, 0)
                for key in ("UNIT", "REVIEW", "SCHOOL_PAST", "ILSAN_PAST")
            },
        },
        "server": {
            "definitionCount": len(definitions),
            "signatureSha256": test_definitions_sha256(definitions),
            "matchedCount": len(mappings),
            "issueCount": len(issues),
            "countsByCategory": {
                key: dict(status_by_category.get(key, {}))
                for key in ("UNIT", "REVIEW", "SCHOOL_PAST", "ILSAN_PAST")
            },
        },
        "mappings": dict(sorted(mappings.items())),
        "issues": dict(sorted(issues.items())),
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="빠른 인쇄기 등록 목록과 서버 시험의 영구 자료ID 매핑을 생성합니다.")
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--tests-config", type=Path, default=DEFAULT_TESTS_CONFIG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true", help="기존 출력이 현재 입력으로 재생성한 내용과 같은지 검사합니다.")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    catalog_rows = read_registered_catalog(args.catalog)
    tests_config = json.loads(args.tests_config.read_text(encoding="utf-8-sig"))
    bundle = build_mapping_bundle(tests_config, catalog_rows, file_sha256(args.catalog))
    rendered = json.dumps(bundle, ensure_ascii=False, indent=2, sort_keys=False) + "\n"

    if args.check:
        try:
            current = args.output.read_text(encoding="utf-8-sig")
        except FileNotFoundError:
            print(f"mapping check failed: missing {args.output}")
            return 1
        if current != rendered:
            print("mapping check failed: current mapping is stale")
            return 1
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8", newline="")

    server = bundle["server"]
    catalog = bundle["catalog"]
    action = "verified" if args.check else "generated"
    print(
        f"quick-printer mapping {action}: "
        f"catalog={catalog['rowCount']} unique={catalog['uniqueMaterialIdCount']} "
        f"duplicates={catalog['duplicateMaterialIdCount']} "
        f"server={server['definitionCount']} matched={server['matchedCount']} issues={server['issueCount']}"
    )
    for category, counts in server["countsByCategory"].items():
        print(f"  {category}: {counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
