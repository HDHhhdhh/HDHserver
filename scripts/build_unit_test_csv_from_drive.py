from __future__ import annotations

import argparse
import csv
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.build_unit_test_csv_from_link_map import (
    cell_answer,
    extract_quick_answers as extract_quick_answers_robust,
)


SUBJECT_ALIASES = {
    "공통수학1": "공수1",
    "공통수학2": "공수2",
    "대수": "대수",
    "미적분1": "미적분1",
    "미적분2": "미적분2",
    "기하": "기하",
    "확률과 통계": "확통",
}

CIRCLED = {
    "①": "1",
    "②": "2",
    "③": "3",
    "④": "4",
    "⑤": "5",
}
EXPECTED_PROBLEMS = 20


def clean_token(text: str) -> str:
    text = unicodedata.normalize("NFKC", str(text or ""))
    text = text.replace("\u200b", "").replace("\ufeff", "")
    text = text.replace("−", "-").replace("–", "-").replace("—", "-")
    text = text.strip()
    return CIRCLED.get(text, text)


def compact_key(text: str) -> str:
    text = clean_token(text).lower()
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"[\[\]\(\){}_\-.,·/]+", "", text)
    return text


def level_from_name(text: str, fallback: str) -> str:
    m = re.search(r"lv\.?\s*([3-6])", text, re.IGNORECASE)
    if m:
        return f"Lv.{m.group(1)}"
    m = re.search(r"([3-6])", fallback)
    return f"Lv.{m.group(1)}" if m else fallback


def normalize_round_name(text: str) -> str:
    m = re.search(r"\d+", str(text or ""))
    return m.group(0) if m else "1"


def clean_test_name(path: Path, level: str, round_no: str) -> str:
    name = path.stem
    name = unicodedata.normalize("NFKC", name)
    name = name.replace("_", " ")
    name = re.sub(r"\s*-\s*해설\s*$", "", name)
    name = re.sub(r"\s*해설\s*$", "", name)
    name = re.sub(r"^(공수1|공수2|공통수학1|공통수학2|대수|미적분1|미적분2|기하|확률과 통계)\s+", "", name)
    name = re.sub(r"^\s*\d{1,2}\s*[.)]\s*", "", name)
    name = re.sub(rf"\s*{re.escape(round_no)}\s*(?:회차|차)\s*$", "", name)
    name = re.sub(r"\s+", " ", name).strip()
    name = re.sub(r"\s+Lv\.?\s*$", "", name, flags=re.IGNORECASE).strip()

    lv = level_from_name(name, level)
    name = re.sub(r"lv\.?\s*([3-6])", lambda m: f"Lv.{m.group(1)}", name, flags=re.IGNORECASE)
    if not re.search(r"Lv\.[3-6]", name):
        name = f"{name} {lv}".strip()
    return name


def extract_quick_answers(pdf_path: Path) -> list[str]:
    return extract_quick_answers_robust(pdf_path, expected=EXPECTED_PROBLEMS)


def iter_round_dirs(root: Path):
    for subject_dir in sorted([p for p in root.iterdir() if p.is_dir()], key=lambda p: p.name):
        subject = SUBJECT_ALIASES.get(subject_dir.name)
        if not subject:
            continue
        for level_dir in sorted([p for p in subject_dir.iterdir() if p.is_dir()], key=lambda p: p.name.lower()):
            level = level_from_name(level_dir.name, level_dir.name)
            for round_dir in sorted([p for p in level_dir.iterdir() if p.is_dir()], key=lambda p: normalize_round_name(p.name)):
                round_no = normalize_round_name(round_dir.name)
                yield subject, level, round_no, round_dir


def build_catalog(root: Path):
    catalog: dict[tuple[str, str, str], dict] = {}
    issues: list[dict[str, str]] = []

    for subject, level, round_no, round_dir in iter_round_dirs(root):
        answer_dir = round_dir / "해설"
        answer_files = []
        if answer_dir.exists():
            answer_files = sorted(answer_dir.glob("*.pdf"), key=lambda p: p.name)

        answers_by_name = defaultdict(list)
        for answer_file in answer_files:
            answer_name = clean_test_name(answer_file, level, round_no)
            answers_by_name[compact_key(answer_name)].append(answer_file)

        problem_files = sorted(
            [p for p in round_dir.glob("*.pdf") if p.is_file() and "해설" not in p.stem],
            key=lambda p: p.name,
        )

        for problem_file in problem_files:
            test_name = clean_test_name(problem_file, level, round_no)
            key = (subject, level, test_name)
            item = catalog.setdefault(
                key,
                {
                    "category": "UNIT",
                    "subject": subject,
                    "difficulty": level,
                    "round": "1",
                    "name": test_name,
                    "problems": 20,
                    "answers": {"1": "", "2": "", "3": ""},
                },
            )

            match_key = compact_key(test_name)
            candidates = answers_by_name.get(match_key, [])
            if not candidates:
                issues.append(
                    {
                        "type": "missing_answer_file",
                        "subject": subject,
                        "difficulty": level,
                        "round": round_no,
                        "name": test_name,
                        "file": str(problem_file),
                    }
                )
                continue

            answer_file = candidates[0]
            if len(candidates) > 1:
                issues.append(
                    {
                        "type": "duplicate_answer_file",
                        "subject": subject,
                        "difficulty": level,
                        "round": round_no,
                        "name": test_name,
                        "file": " | ".join(str(p) for p in candidates),
                    }
                )

            try:
                answers = extract_quick_answers(answer_file)
            except Exception as exc:  # noqa: BLE001 - keep the batch going and report the file.
                issues.append(
                    {
                        "type": "extract_failed",
                        "subject": subject,
                        "difficulty": level,
                        "round": round_no,
                        "name": test_name,
                        "file": str(answer_file),
                        "message": str(exc),
                    }
                )
                continue

            if not answers:
                issues.append(
                    {
                        "type": "empty_answers",
                        "subject": subject,
                        "difficulty": level,
                        "round": round_no,
                        "name": test_name,
                        "file": str(answer_file),
                    }
                )
                continue

            item["problems"] = max(int(item["problems"]), len(answers))
            item["answers"][round_no] = " ".join(answers)

    return catalog, issues


def write_csv(catalog: dict[tuple[str, str, str], dict], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    rows = sorted(
        catalog.values(),
        key=lambda row: (
            ["공수1", "공수2", "대수", "미적분1", "미적분2", "기하", "확통"].index(row["subject"]),
            int(re.search(r"\d", row["difficulty"]).group(0)),
            int(re.match(r"^\D*(\d+)", row["name"]).group(1)) if re.match(r"^\D*(\d+)", row["name"]) else 999,
            row["name"],
        ),
    )

    with output.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["category", "subject", "difficulty", "round", "name", "problems", "answers1", "answers2", "answers3"])
        for row in rows:
            writer.writerow(
                [
                    row["category"],
                    row["subject"],
                    row["difficulty"],
                    row["round"],
                    row["name"],
                    row["problems"],
                    row["answers"].get("1", ""),
                    row["answers"].get("2", ""),
                    row["answers"].get("3", ""),
                ]
            )


def write_issues(issues: list[dict[str, str]], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    keys = ["type", "subject", "difficulty", "round", "name", "file", "message"]
    with output.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        for issue in issues:
            writer.writerow({key: issue.get(key, "") for key in keys})


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".codex_drive_download/unit_tests", type=Path)
    parser.add_argument("--output", default="generated/unit_test_catalog.csv", type=Path)
    parser.add_argument("--issues", default="generated/unit_test_catalog_issues.csv", type=Path)
    args = parser.parse_args(argv)

    if not args.root.exists():
        print(f"Missing download root: {args.root}", file=sys.stderr)
        return 2

    catalog, issues = build_catalog(args.root)
    write_csv(catalog, args.output)
    write_issues(issues, args.issues)

    filled = sum(1 for row in catalog.values() for answer in row["answers"].values() if answer)
    print(f"rows={len(catalog)} filled_rounds={filled} issues={len(issues)}")
    print(f"csv={args.output}")
    print(f"issues={args.issues}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
