from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path, PureWindowsPath

import gdown


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FOLDER_ID = "1wORo_OsYO5EicLd2Xd044KcRM2wCCyuy"
DEFAULT_CONFIG_PATH = ROOT / "tests-config.json"
DEFAULT_OUTPUT_PATH = ROOT / "static/js/test_answer_link_map.json"

SUBJECT_ALIASES = {
    "공통수학1": "공수1",
    "공통수학2": "공수2",
    "확률과 통계": "확통",
    "확통": "확통",
    "대수": "대수",
    "미적분1": "미적분1",
    "미적분2": "미적분2",
    "기하": "기하",
}

ANSWER_NAME_ALIASES = {
    "평면좌표1": ["평면좌표"],
    "직선의방정식1": ["직방1"],
    "직선의방정식2": ["직방2"],
    "원의방정식1": ["원방1"],
    "원의방정식2": ["원방2"],
    "무리함수": ["무리함수1", "무리함수2"],
    "공수2무리함수": ["무리함수1", "무리함수2"],
    "최대최소1": ["함수의최대최소1"],
    "최대최소2": ["함수의최대최소2"],
}


NON_FATAL_ISSUE_TYPES = frozenset({"unmatched_answer_file", "expected_missing_round"})

def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def same_path(left: Path, right: Path) -> bool:
    return left.resolve(strict=False) == right.resolve(strict=False)


def require_backup_for_live_output(output_path: Path, backup_confirmed: bool, parser: argparse.ArgumentParser) -> None:
    if same_path(output_path, DEFAULT_OUTPUT_PATH) and not backup_confirmed:
        parser.error(
            "refusing to update live static/js/test_answer_link_map.json without --backup-confirmed; "
            "run python scripts/backup_runtime_data.py first or pass --output <temp path>"
        )


def clean_text(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    return re.sub(r"\s+", " ", text.replace("\u200b", "").replace("\ufeff", "")).strip()


def normalize_level(value: str) -> str:
    match = re.search(r"lv\.?\s*([3-6])", str(value or ""), re.IGNORECASE)
    return f"Lv.{match.group(1)}" if match else clean_text(value)


def normalize_round(value: str) -> str:
    match = re.search(r"\d+", str(value or ""))
    return match.group(0) if match else "1"


def strip_level(value: str) -> str:
    return re.sub(r"\s*Lv\.?\s*[3-6]\s*$", "", clean_text(value), flags=re.IGNORECASE).strip()


def compact_key(value: str) -> str:
    text = unicodedata.normalize("NFKC", strip_level(value)).lower()
    return re.sub(r"[\s_.,·\-()]+", "", text)


def answer_name_keys(value: str) -> list[str]:
    key = compact_key(value)
    return [key, *ANSWER_NAME_ALIASES.get(key, [])]


def source_order_from_title(title: str) -> int | None:
    name = clean_text(Path(str(title or "")).stem)
    match = re.match(r"^\s*(\d{1,3})\s*[.)]\s*", name)
    return int(match.group(1)) if match else None

def clean_answer_title(title: str, level: str, round_no: str) -> str:
    name = Path(str(title or "")).stem
    name = clean_text(name.replace("_", " "))
    name = re.sub(r"\s*해설\s*$", "", name)
    name = re.sub(r"^\s*\d{1,3}\s*[.)]\s*", "", name)
    name = re.sub(r"\s*Lv\.?\s*([3-6])", lambda m: f" Lv.{m.group(1)}", name, flags=re.IGNORECASE)
    name = re.sub(rf"\s*{re.escape(round_no)}\s*(?:회차|차)\s*$", "", name)
    name = clean_text(name)
    if not re.search(r"Lv\.[3-6]", name):
        name = f"{name} {level}".strip()
    return name


def drive_url(file_id: str) -> str:
    return f"https://drive.google.com/file/d/{file_id}/view?usp=drivesdk"


def build_config_index(config: dict) -> dict[tuple[str, str, str], dict]:
    unit_tests = config.get("categories", {}).get("UNIT", {}).get("tests", [])
    by_source: dict[str, dict] = {}
    for test in unit_tests:
        if not isinstance(test, dict):
            continue
        source_id = str(test.get("sourceId") or "").strip() or re.sub(r"_r[123]$", "", str(test.get("id") or "").strip())
        if not source_id:
            continue
        source_order_raw = test.get("sourceOrder", test.get("source_order"))
        try:
            source_order = int(source_order_raw) if source_order_raw not in (None, "") else None
        except (TypeError, ValueError):
            source_order = None
        status = str(test.get("answerLinkStatus") or test.get("answer_link_status") or "").strip().casefold()
        item = by_source.setdefault(
            source_id,
            {
                "sourceId": source_id,
                "subject": clean_text(test.get("curriculum")),
                "level": normalize_level(test.get("difficulty") or test.get("level")),
                "name": clean_text(test.get("name")),
                "sourceOrder": source_order,
                "answerLinkStatus": status,
            },
        )
        if not item["name"] and test.get("name"):
            item["name"] = clean_text(test.get("name"))
        if item.get("sourceOrder") is None and source_order is not None:
            item["sourceOrder"] = source_order
        if status:
            item["answerLinkStatus"] = status

    index = {}
    for item in by_source.values():
        key = (item["subject"], item["level"], compact_key(item["name"]))
        previous = index.get(key)
        if previous is not None and previous["sourceId"] != item["sourceId"]:
            raise ValueError(
                "ambiguous config key "
                f"{key!r}: {previous['sourceId']} and {item['sourceId']}"
            )
        index[key] = item
    return index

def iter_drive_answer_files(folder_id: str):
    files = gdown.download_folder(id=folder_id, quiet=True, skip_download=True)
    for drive_file in files:
        path = str(getattr(drive_file, "path", "") or "")
        file_id = str(getattr(drive_file, "id", "") or "").strip()
        if not path.lower().endswith(".pdf") or not file_id:
            continue

        parts = PureWindowsPath(path.replace("/", "\\")).parts
        if len(parts) < 5 or "해설" not in parts:
            continue

        subject = SUBJECT_ALIASES.get(parts[0], clean_text(parts[0]))
        level = normalize_level(parts[1])
        round_no = normalize_round(parts[2])
        title = parts[-1]
        name = clean_answer_title(title, level, round_no)
        yield {
            "subject": subject,
            "level": level,
            "round": round_no,
            "name": name,
            "title": title,
            "sourceOrder": source_order_from_title(title),
            "fileId": file_id,
        }


def build_link_map(config: dict, folder_id: str) -> tuple[dict, list[dict]]:
    config_index = build_config_index(config)
    link_map: dict[str, dict] = {}
    issues: list[dict] = []
    seen: set[tuple[str, str]] = set()
    file_owners: dict[str, tuple[str, str]] = {}

    for answer_file in iter_drive_answer_files(folder_id):
        config_items = []
        candidate_ids = set()
        for name_key in answer_name_keys(answer_file["name"]):
            config_item = config_index.get((answer_file["subject"], answer_file["level"], name_key))
            if not config_item or config_item["sourceId"] in candidate_ids:
                continue
            candidate_ids.add(config_item["sourceId"])
            config_items.append(config_item)
        if not config_items:
            issues.append({"type": "unmatched_answer_file", **answer_file})
            continue

        if len(config_items) > 1:
            answer_source_order = answer_file.get("sourceOrder")
            ordered_items = [
                item for item in config_items
                if answer_source_order is not None and item.get("sourceOrder") == answer_source_order
            ]
            if len(ordered_items) != 1:
                issues.append(
                    {
                        "type": "ambiguous_answer_file",
                        "candidateSourceIds": sorted(item["sourceId"] for item in config_items),
                        **answer_file,
                    }
                )
                continue
            config_items = ordered_items

        config_item = config_items[0]
        source_id = config_item["sourceId"]
        round_no = answer_file["round"]
        duplicate_key = (source_id, round_no)
        if duplicate_key in seen:
            issues.append({"type": "duplicate_answer_file", "sourceId": source_id, **answer_file})
            continue

        file_id = answer_file["fileId"]
        existing_owner = file_owners.get(file_id)
        if existing_owner is not None and existing_owner != duplicate_key:
            issues.append(
                {
                    "type": "reused_answer_file",
                    "sourceId": source_id,
                    "existingSourceId": existing_owner[0],
                    "existingRound": existing_owner[1],
                    **answer_file,
                }
            )
            continue

        seen.add(duplicate_key)
        file_owners[file_id] = duplicate_key
        unit_name = answer_file["name"]
        link_map.setdefault(source_id, {})[round_no] = {
            "answerUrl": drive_url(file_id),
            "fileId": file_id,
            "label": f"{unit_name} {round_no}회차 해설",
            "subject": config_item["subject"],
            "unitName": unit_name,
        }

    for item in config_index.values():
        rounds = link_map.get(item["sourceId"], {})
        missing_type = (
            "expected_missing_round"
            if item.get("answerLinkStatus") == "missing"
            else "missing_round"
        )
        for round_no in ("1", "2", "3"):
            if round_no not in rounds:
                issues.append({"type": missing_type, "sourceId": item["sourceId"], "round": round_no})

    return dict(sorted(link_map.items())), issues

def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--folder-id", default=DEFAULT_FOLDER_ID)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--issues", type=Path, default=None)
    parser.add_argument("--backup-confirmed", action="store_true", help=(
        "Required when writing static/js/test_answer_link_map.json after running backup_runtime_data.py."
    ))
    args = parser.parse_args(argv)

    require_backup_for_live_output(args.output, args.backup_confirmed, parser)

    config = read_json(args.config)
    link_map, issues = build_link_map(config, args.folder_id)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(link_map, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if args.issues:
        args.issues.parent.mkdir(parents=True, exist_ok=True)
        args.issues.write_text(json.dumps(issues, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    linked_rounds = sum(len(rounds) for rounds in link_map.values())
    fatal_issues = [issue for issue in issues if issue.get("type") not in NON_FATAL_ISSUE_TYPES]
    print(f"source_ids={len(link_map)} linked_rounds={linked_rounds} issues={len(issues)}")
    print(f"output={args.output}")
    if args.issues:
        print(f"issues={args.issues}")
    elif fatal_issues:
        print(json.dumps(fatal_issues[:10], ensure_ascii=False, indent=2))
    return 0 if not fatal_issues else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
