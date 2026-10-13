from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.storage import file_lock, save_atomic
from core.test_answer_modes import VALID_ANSWER_MODES, normalize_answer_modes


DEFAULT_CONFIG_PATH = ROOT / "tests-config.json"
DEFAULT_LINK_MAP_PATH = ROOT / "static" / "js" / "test_answer_link_map.json"
EXPECTED_UNIT_PROBLEMS = 20
EXPECTED_UNIT_ROUNDS = frozenset({"1", "2", "3"})


class MigrationError(ValueError):
    pass


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def same_path(left: Path, right: Path) -> bool:
    return left.resolve(strict=False) == right.resolve(strict=False)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def link_file_id_index(link_map: object) -> dict[tuple[str, str], str]:
    if not isinstance(link_map, dict):
        raise MigrationError("answer link map root must be an object")
    indexed: dict[tuple[str, str], str] = {}
    owners: dict[str, tuple[str, str]] = {}
    for raw_source_id, raw_rounds in link_map.items():
        source_id = str(raw_source_id or "").strip()
        if not source_id or not isinstance(raw_rounds, dict):
            raise MigrationError("answer link map contains an invalid source")
        for raw_round, raw_link in raw_rounds.items():
            round_no = str(raw_round or "").strip()
            if round_no not in EXPECTED_UNIT_ROUNDS or not isinstance(raw_link, dict):
                raise MigrationError(f"invalid answer link row for {source_id}/{round_no}")
            file_id = str(raw_link.get("fileId") or "").strip()
            if not file_id:
                raise MigrationError(f"missing answer fileId for {source_id}/{round_no}")
            key = (source_id, round_no)
            previous_owner = owners.get(file_id)
            if previous_owner is not None and previous_owner != key:
                raise MigrationError(f"answer fileId {file_id} is reused by {previous_owner} and {key}")
            owners[file_id] = key
            indexed[key] = file_id
    return indexed


def evidence_index(
    rows: object,
    expected_file_ids: dict[tuple[str, str], str],
) -> dict[tuple[str, str], list[str]]:
    if not isinstance(rows, list):
        raise MigrationError("evidence root must be a JSON array")
    indexed: dict[tuple[str, str], list[str]] = {}
    file_owners: dict[str, tuple[str, str]] = {}
    for row_number, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise MigrationError(f"evidence row {row_number} must be an object")
        source_id = str(row.get("sourceId") or "").strip()
        round_no = str(row.get("round") or "").strip()
        if not source_id or round_no not in EXPECTED_UNIT_ROUNDS:
            raise MigrationError(f"evidence row {row_number} has invalid sourceId/round")
        file_id = str(row.get("fileId") or "").strip()
        if not file_id:
            raise MigrationError(f"evidence row {row_number} is missing fileId")
        key = (source_id, round_no)
        expected_file_id = expected_file_ids.get(key)
        if expected_file_id is None:
            raise MigrationError(f"evidence row {row_number} has no matching answer link")
        if file_id != expected_file_id:
            raise MigrationError(
                f"evidence fileId mismatch for {source_id} round {round_no}: "
                f"expected {expected_file_id}, got {file_id}"
            )
        previous_owner = file_owners.get(file_id)
        if previous_owner is not None and previous_owner != key:
            raise MigrationError(f"evidence fileId {file_id} is reused by {previous_owner} and {key}")
        file_owners[file_id] = key
        modes = normalize_answer_modes(row.get("modes"), EXPECTED_UNIT_PROBLEMS)
        if len(modes) != EXPECTED_UNIT_PROBLEMS or any(mode not in VALID_ANSWER_MODES for mode in modes):
            raise MigrationError(f"evidence row {row_number} must contain 20 verified modes")
        previous = indexed.get(key)
        if previous is not None:
            raise MigrationError(f"duplicate evidence for {source_id} round {round_no}")
        indexed[key] = modes
    return indexed


def unit_tests(config: dict) -> list[dict]:
    categories = config.get("categories") if isinstance(config, dict) else None
    category = categories.get("UNIT") if isinstance(categories, dict) else None
    tests = category.get("tests") if isinstance(category, dict) else None
    if not isinstance(tests, list) or not all(isinstance(test, dict) for test in tests):
        raise MigrationError("tests-config categories.UNIT.tests must be an object array")
    return tests


def apply_evidence(config: dict, indexed: dict[tuple[str, str], list[str]]) -> dict:
    tests = unit_tests(config)
    expected: set[tuple[str, str]] = set()
    updated = 0
    unchanged = 0
    for test in tests:
        source_id = str(test.get("sourceId") or "").strip()
        round_no = str(test.get("round") or "").strip()
        problems = int(test.get("problems") or 0)
        if not source_id or round_no not in EXPECTED_UNIT_ROUNDS or problems != EXPECTED_UNIT_PROBLEMS:
            raise MigrationError(f"unsupported UNIT test shape: {test.get('id')!r}")
        key = (source_id, round_no)
        expected.add(key)
        modes = indexed.get(key)
        if modes is None:
            continue
        raw_answer_keys = test.get("answerKeys")
        answers = raw_answer_keys.get(round_no) if isinstance(raw_answer_keys, dict) else test.get("answerKey")
        if not isinstance(answers, list) or len(answers) != EXPECTED_UNIT_PROBLEMS:
            raise MigrationError(f"answer key must contain 20 entries: {test.get('id')!r}")
        for question_no, (raw_answer, mode) in enumerate(zip(answers, modes), start=1):
            answer = str(raw_answer or "").strip()
            if mode == "choice_number" and answer not in {"1", "2", "3", "4", "5"}:
                raise MigrationError(
                    f"choice_number answer must be 1..5: {test.get('id')!r} question {question_no}"
                )
            if mode == "answer_value" and not answer:
                raise MigrationError(
                    f"answer_value requires an answer: {test.get('id')!r} question {question_no}"
                )
        raw_answer_modes = test.get("answerModes")
        answer_modes = dict(raw_answer_modes) if isinstance(raw_answer_modes, dict) else {}
        if answer_modes.get(round_no) == modes:
            unchanged += 1
            continue
        answer_modes[round_no] = modes.copy()
        test["answerModes"] = answer_modes
        updated += 1

    missing = sorted(expected - set(indexed))
    extra = sorted(set(indexed) - expected)
    complete = len(missing) == 0 and len(expected) == len(indexed)
    choice_count = sum(mode == "choice_number" for key in expected & set(indexed) for mode in indexed[key])
    answer_value_count = sum(mode == "answer_value" for key in expected & set(indexed) for mode in indexed[key])
    manual_review_count = sum(mode == "manual_review" for key in expected & set(indexed) for mode in indexed[key])
    return {
        "config": config,
        "summary": {
            "unitTests": len(tests),
            "expectedEvidence": len(expected),
            "providedEvidence": len(indexed),
            "updated": updated,
            "unchanged": unchanged,
            "missing": len(missing),
            "extra": len(extra),
            "complete": complete,
            "choiceQuestions": choice_count,
            "answerValueQuestions": answer_value_count,
            "manualReviewQuestions": manual_review_count,
            "missingExamples": [{"sourceId": source_id, "round": round_no} for source_id, round_no in missing[:20]],
            "extraExamples": [{"sourceId": source_id, "round": round_no} for source_id, round_no in extra[:20]],
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Preview or apply Drive-verified UNIT question answer modes without inferring from answer values.",
    )
    parser.add_argument("--evidence", type=Path, required=True, help="JSON array produced from Drive solution PDFs")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--link-map", type=Path, default=DEFAULT_LINK_MAP_PATH)
    parser.add_argument("--output", type=Path, default=None, help="Optional preview output; never writes live config unless --apply is set")
    parser.add_argument("--apply", action="store_true", help="Write the merged configuration")
    parser.add_argument("--backup-confirmed", action="store_true", help="Required for a live tests-config.json write")
    parser.add_argument("--allow-incomplete", action="store_true", help="Allow a partial non-live output for debugging")
    return parser


def main(argv: list[str]) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config_path = args.config.resolve(strict=False)
    output_path = (args.output or args.config).resolve(strict=False)
    live_write = args.apply and same_path(output_path, DEFAULT_CONFIG_PATH)
    if live_write and not args.backup_confirmed:
        parser.error(
            "refusing to update live tests-config.json without --backup-confirmed; "
            "run python scripts/backup_runtime_data.py first"
        )

    config = read_json(config_path)
    expected_file_ids = link_file_id_index(read_json(args.link_map))
    result = apply_evidence(
        config,
        evidence_index(read_json(args.evidence), expected_file_ids),
    )
    summary = result["summary"]
    summary["configPath"] = str(config_path)
    summary["outputPath"] = str(output_path) if args.apply or args.output else ""
    summary["inputSha256"] = sha256_file(config_path)
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    if not summary["complete"] and not args.allow_incomplete:
        raise MigrationError("evidence does not cover the full UNIT catalog")
    if args.apply:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if same_path(config_path, output_path):
            with file_lock(output_path):
                if sha256_file(config_path) != summary["inputSha256"]:
                    raise MigrationError("tests-config.json changed during migration; rerun the preview")
                save_atomic(output_path, result["config"])
        else:
            save_atomic(output_path, result["config"])
        print(f"wrote {output_path}")
    elif args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        save_atomic(args.output, result["config"])
        print(f"wrote preview {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
