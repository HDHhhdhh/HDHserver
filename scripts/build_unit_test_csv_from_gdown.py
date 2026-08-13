from __future__ import annotations

import argparse
import csv
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath

import gdown

from build_unit_test_csv_from_drive import clean_test_name, level_from_name, normalize_round_name
from build_unit_test_csv_from_link_map import answer_list_text, download_pdf, extract_quick_answers, safe_file_part


SUBJECTS = {
    "기하": {
        "folder_id": "1UGTVRO3u4Wvv4RjaKX1lgGmiyBlvwTcg",
        "slug": "giha",
        "subject": "기하",
    },
    "미적분1": {
        "folder_id": "1JPcZmqy4Foc--KYApH9V8XBjE7R_hkKj",
        "slug": "mijeok1",
        "subject": "미적분1",
    },
    "미적분2": {
        "folder_id": "1FAlKOm4CGpo58_49wbEPsxkSKJ7JxTnz",
        "slug": "mijeok2",
        "subject": "미적분2",
    },
    "확률과 통계": {
        "folder_id": "1VaLqMFacy21C_qlmDpXnjLxy3IWTkSJh",
        "slug": "hwaktong",
        "subject": "확통",
    },
}


@dataclass(frozen=True)
class DriveAnswerFile:
    subject_label: str
    app_subject: str
    slug: str
    level: str
    round_no: str
    order_no: int
    test_name: str
    file_id: str
    path: str


def split_drive_path(path: str) -> tuple[str, ...]:
    normalized = str(path or "").replace("/", "\\")
    return PureWindowsPath(normalized).parts


def title_order(title: str) -> int:
    match = re.match(r"^\s*(\d{1,3})\s*[.)]?", str(title or ""))
    return int(match.group(1)) if match else 999


def normalized_test_name(title: str, level: str, round_no: str) -> str:
    name = clean_test_name(Path(title), level, round_no)
    name = re.sub(rf"\s*{re.escape(round_no)}\s*회\s*$", "", name)
    name = re.sub(rf"\s*{re.escape(round_no)}\s*차\s*$", "", name)
    name = re.sub(r"\s*Lv\.\s*Lv\.", " Lv.", name)
    name = re.sub(r"\s+", " ", name).strip()
    if not re.search(r"Lv\.[3-6]", name):
        name = f"{name} {level}".strip()
    return name


def name_quality(name: str) -> tuple[int, int]:
    base = re.sub(r"\s*Lv\.[3-6].*$", "", str(name or "")).strip()
    penalty = -100 if re.search(r"Lv\.\s*Lv\.", str(name or "")) else 0
    return (penalty + len(base), len(str(name or "")))


def iter_answer_files(subject_label: str, info: dict[str, str]) -> list[DriveAnswerFile]:
    files = gdown.download_folder(id=info["folder_id"], quiet=True, skip_download=True)
    answers: list[DriveAnswerFile] = []
    for drive_file in files:
        path = getattr(drive_file, "path", "")
        file_id = getattr(drive_file, "id", "")
        parts = split_drive_path(path)
        if len(parts) < 4 or not file_id:
            continue
        if parts[-1].lower().endswith(".pdf") is False:
            continue
        if "해설" not in parts:
            continue

        level = level_from_name(parts[0], parts[0])
        round_no = normalize_round_name(parts[1])
        title = parts[-1]
        answers.append(
            DriveAnswerFile(
                subject_label=subject_label,
                app_subject=info["subject"],
                slug=info["slug"],
                level=level,
                round_no=round_no,
                order_no=title_order(title),
                test_name=normalized_test_name(title, level, round_no),
                file_id=file_id,
                path=path,
            )
        )
    return answers


def build_catalog(subject_filter: set[str], download_dir: Path, workers: int) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    catalog: dict[tuple[str, str, int], dict] = {}
    issues: list[dict[str, str]] = []
    answer_files: list[DriveAnswerFile] = []

    for subject_label, info in SUBJECTS.items():
        if subject_filter and subject_label not in subject_filter and info["subject"] not in subject_filter:
            continue
        subject_files = iter_answer_files(subject_label, info)
        print(f"{subject_label}: answer PDFs={len(subject_files)}", file=sys.stderr)
        answer_files.extend(subject_files)

    downloadable: list[DriveAnswerFile] = []
    for answer_file in answer_files:
        key = (answer_file.app_subject, answer_file.level, answer_file.order_no)
        item = catalog.setdefault(
            key,
            {
                "subject_label": answer_file.subject_label,
                "app_subject": answer_file.app_subject,
                "slug": answer_file.slug,
                "level": answer_file.level,
                "order_no": answer_file.order_no,
                "name": answer_file.test_name,
                "problems": 20,
                "answers": {"1": "", "2": "", "3": ""},
                "files": {},
            },
        )
        item["order_no"] = min(int(item["order_no"]), answer_file.order_no)
        if name_quality(answer_file.test_name) > name_quality(item["name"]):
            item["name"] = answer_file.test_name
        if answer_file.round_no in item["files"]:
            issues.append(
                {
                    "type": "duplicate_answer_round",
                    "subject": answer_file.app_subject,
                    "difficulty": answer_file.level,
                    "round": answer_file.round_no,
                    "name": answer_file.test_name,
                    "file": answer_file.path,
                    "message": f"already saw {item['files'][answer_file.round_no]}",
                }
            )
            continue
        item["files"][answer_file.round_no] = answer_file.path
        downloadable.append(answer_file)

    results = process_answer_files(downloadable, download_dir, workers=workers)
    for answer_file, answers, issue in results:
        if issue:
            issues.append(issue)
            continue
        if not answers:
            issues.append(
                {
                    "type": "empty_answers",
                    "subject": answer_file.app_subject,
                    "difficulty": answer_file.level,
                    "round": answer_file.round_no,
                    "name": answer_file.test_name,
                    "file": answer_file.path,
                    "message": "",
                }
            )
            continue
        item = catalog[(answer_file.app_subject, answer_file.level, answer_file.order_no)]
        item["problems"] = max(int(item["problems"]), len(answers))
        if len(answers) != 20 or any(not value for value in answers[:20]):
            issues.append(
                {
                    "type": "answer_count_warning",
                    "subject": answer_file.app_subject,
                    "difficulty": answer_file.level,
                    "round": answer_file.round_no,
                    "name": answer_file.test_name,
                    "file": answer_file.path,
                    "message": f"expected 20 answers, got {len(answers)}",
                }
            )
        item["answers"][answer_file.round_no] = answer_list_text(answers, int(item["problems"]))

    rows = []
    for row in sorted(catalog.values(), key=catalog_sort_key):
        missing = [round_no for round_no in ("1", "2", "3") if not row["answers"].get(round_no)]
        for round_no in missing:
            issues.append(
                {
                    "type": "missing_round_answers",
                    "subject": row["app_subject"],
                    "difficulty": row["level"],
                    "round": round_no,
                    "name": row["name"],
                    "file": "",
                    "message": "",
                }
            )
        source_id = f"t_unit_{row['slug']}_{int(row['order_no']):02d}_{row['level'].lower().replace('.', '')}"
        rows.append(
            {
                "id": source_id,
                "분류": "단원평가",
                "과목": row["app_subject"],
                "난이도": row["level"],
                "회차": "1",
                "시험명": row["name"],
                "문항수": str(row["problems"]),
                "1회차정답": row["answers"].get("1", ""),
                "2회차정답": row["answers"].get("2", ""),
                "3회차정답": row["answers"].get("3", ""),
            }
        )

    return rows, issues


def answer_pdf_path(download_dir: Path, answer_file: DriveAnswerFile) -> Path:
    return (
        download_dir
        / answer_file.slug
        / safe_file_part(f"{answer_file.level}_{answer_file.order_no:03d}_{answer_file.test_name}")
        / f"{answer_file.round_no}.pdf"
    )


def process_one_answer(answer_file: DriveAnswerFile, download_dir: Path):
    pdf_path = answer_pdf_path(download_dir, answer_file)
    try:
        download_pdf(f"https://drive.google.com/file/d/{answer_file.file_id}/view", pdf_path)
        answers = extract_quick_answers(pdf_path, expected=20)
        return answer_file, answers, None
    except Exception as exc:  # noqa: BLE001 - batch report and continue.
        return (
            answer_file,
            [],
            {
                "type": "extract_failed",
                "subject": answer_file.app_subject,
                "difficulty": answer_file.level,
                "round": answer_file.round_no,
                "name": answer_file.test_name,
                "file": answer_file.path,
                "message": str(exc),
            },
        )


def process_answer_files(answer_files: list[DriveAnswerFile], download_dir: Path, workers: int = 4):
    results = []
    completed = 0
    total = len(answer_files)
    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        futures = [executor.submit(process_one_answer, answer_file, download_dir) for answer_file in answer_files]
        for future in as_completed(futures):
            completed += 1
            if completed % 20 == 0 or completed == total:
                print(f"processed answer PDFs={completed}/{total}", file=sys.stderr)
            results.append(future.result())
    return results


def catalog_sort_key(row: dict) -> tuple[int, int, int, str]:
    subject_order = ["미적분1", "미적분2", "기하", "확통"]
    subject_index = subject_order.index(row["app_subject"]) if row["app_subject"] in subject_order else 999
    level_match = re.search(r"\d+", row["level"])
    level_no = int(level_match.group(0)) if level_match else 999
    return (subject_index, level_no, int(row["order_no"]), row["name"])


def write_catalog(path: Path, rows: list[dict[str, str]]) -> None:
    headers = ["id", "분류", "과목", "난이도", "회차", "시험명", "문항수", "1회차정답", "2회차정답", "3회차정답"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


def write_issues(path: Path, issues: list[dict[str, str]]) -> None:
    headers = ["type", "subject", "difficulty", "round", "name", "file", "message"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=headers)
        writer.writeheader()
        for issue in issues:
            writer.writerow({key: issue.get(key, "") for key in headers})


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--subject", action="append", default=[], help="Limit to a Drive subject label or app subject.")
    parser.add_argument("--download-dir", type=Path, default=Path(".codex_drive_download/new_unit_answer_pdfs"))
    parser.add_argument("--output", type=Path, default=Path("generated/unit_test_catalog_new_subjects.csv"))
    parser.add_argument("--issues", type=Path, default=Path("generated/unit_test_catalog_new_subjects_issues.csv"))
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args(argv)

    rows, issues = build_catalog(set(args.subject), args.download_dir, workers=args.workers)
    write_catalog(args.output, rows)
    write_issues(args.issues, issues)

    filled = sum(1 for row in rows for key in ("1회차정답", "2회차정답", "3회차정답") if row.get(key))
    print(f"rows={len(rows)} filled_rounds={filled} issues={len(issues)}")
    print(f"csv={args.output}")
    print(f"issues={args.issues}")
    return 0 if not issues else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
