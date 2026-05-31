from __future__ import annotations

import argparse
import csv
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any

import fitz
import gdown

from build_unit_test_csv_from_link_map import (
    answer_list_text,
    download_pdf,
    safe_file_part,
)


@dataclass(frozen=True)
class FolderSpec:
    label: str
    folder_id: str
    slug: str
    subject: str
    difficulty: str
    order_offset: int


@dataclass(frozen=True)
class DrivePdf:
    spec: FolderSpec
    file_id: str
    title: str
    path: str
    round_no: int
    is_solution: bool


FOLDERS = [
    FolderSpec(
        label="공수1 상",
        folder_id="16og5R_VH6Sx18g08hQNu8-zQjTdN7_y3",
        slug="gongsu1_high",
        subject="공수1",
        difficulty="상",
        order_offset=0,
    ),
    FolderSpec(
        label="공수1 중상",
        folder_id="1FXVaW1cljIOYKMn77MFtdnR3pEj06Ljc",
        slug="gongsu1_mid_high",
        subject="공수1",
        difficulty="중상",
        order_offset=100,
    ),
    FolderSpec(
        label="대수 상",
        folder_id="1NkZpQgrfFcJzrPngUmWP0LthUKP0VrnV",
        slug="daesu_high",
        subject="대수",
        difficulty="상",
        order_offset=200,
    ),
    FolderSpec(
        label="대수 중상",
        folder_id="1NgX4Y2j5O7XYj3uaWa3rpusfr7xM-hlv",
        slug="daesu_mid_high",
        subject="대수",
        difficulty="중상",
        order_offset=300,
    ),
]

CSV_HEADERS = [
    "id",
    "category",
    "subject",
    "difficulty",
    "round",
    "name",
    "problems",
    "answers",
    "source_order",
    "problem_file",
    "solution_file",
    "problem_file_id",
    "solution_file_id",
]

ISSUE_HEADERS = ["type", "folder", "round", "name", "file", "message"]

CIRCLED = {
    "\u2460": "1",
    "\u2461": "2",
    "\u2462": "3",
    "\u2463": "4",
    "\u2464": "5",
}

# The review-test PDFs use a math font whose ToUnicode map emits private-use
# codepoints for simple digits/operators. Mapping them here keeps answer keys
# human-readable and importable.
MATH_FONT_MAP = str.maketrans(
    {
        "\ue034": "1",
        "\ue035": "2",
        "\ue036": "3",
        "\ue037": "4",
        "\ue038": "5",
        "\ue039": "6",
        "\ue03a": "7",
        "\ue03b": "8",
        "\ue03c": "9",
        "\ue03d": "0",
        "\ue044": "(",
        "\ue045": ")",
        "\ue046": "-",
        "\ue047": "=",
        "\ue048": "+",
        "\ue052": ",",
        "\ue053": "P",
        "\ue055": "≤",
        "\ue056": ">",
        "\ue05c": "√",
        "\ue06d": "/",
        "\ue07c": "",
        "\ue07e": "",
        "\ue07f": "",
        "\ue081": "",
        "\ue0a4": "θ",
        "\ue0ac": "pi",
        "\ue0c8": "°",
        "\ue0e5": "a",
        "\ue0e6": "b",
        "\ue0e7": "c",
        "\ue0e8": "d",
        "\ue0ea": "f",
        "\ue0eb": "g",
        "\ue0f1": "m",
        "\ue0f2": "n",
        "\ue0fc": "x",
        "\ue0fd": "y",
        "\ue0fe": "z",
    }
)

FULL_MANUAL_ANSWERS = {
    ("daesu_high", 1): ["11", "3", "1", "4", "512", "125", "2", "1", "4", "426", "3", "17/25"],
}

PATCH_MANUAL_ANSWERS = {
    ("gongsu1_high", 1): {6: "3", 7: "4"},
    ("daesu_high", 2): {11: "해설참조"},
    ("daesu_mid_high", 7): {9: "해설참조"},
}


def split_drive_path(path: str) -> tuple[str, ...]:
    normalized = str(path or "").replace("/", "\\")
    return PureWindowsPath(normalized).parts


def clean_title(title: str) -> str:
    value = re.sub(r"\.pdf$", "", str(title or ""), flags=re.IGNORECASE).strip()
    value = re.sub(r"[_\s-]*해설\s*$", "", value).strip()
    value = re.sub(r"\s+", " ", value)
    return value


def round_from_title(title: str) -> int | None:
    match = re.search(r"(\d{1,3})\s*회차", str(title or ""))
    return int(match.group(1)) if match else None


def is_solution_title(title: str) -> bool:
    return bool(re.search(r"(?:해설|정답)", str(title or "")))


def drive_file_title(drive_file: Any) -> str:
    title = str(getattr(drive_file, "name", "") or "").strip()
    if title:
        return title
    path = str(getattr(drive_file, "path", "") or "")
    parts = split_drive_path(path)
    return parts[-1] if parts else path


def iter_folder_pdfs(spec: FolderSpec) -> list[DrivePdf]:
    files = gdown.download_folder(id=spec.folder_id, quiet=True, skip_download=True)
    out: list[DrivePdf] = []
    for drive_file in files or []:
        file_id = str(getattr(drive_file, "id", "") or "").strip()
        path = str(getattr(drive_file, "path", "") or "")
        title = drive_file_title(drive_file)
        if not file_id or not title.lower().endswith(".pdf"):
            continue
        round_no = round_from_title(title)
        if not round_no:
            continue
        out.append(
            DrivePdf(
                spec=spec,
                file_id=file_id,
                title=title,
                path=path or title,
                round_no=round_no,
                is_solution=is_solution_title(title) or any("해설" in part for part in split_drive_path(path)),
            )
        )
    return out


def clean_answer_token(text: str) -> str:
    value = str(text or "").strip()
    value = CIRCLED.get(value, value)
    value = value.translate(MATH_FONT_MAP)
    value = value.replace("−", "-").replace("–", "-").replace("—", "-")
    value = re.sub(r"\s+", "", value)
    value = re.sub(r"√/([A-Za-z0-9]+)", r"√\1", value)
    return value.strip(".,;:")


def answer_from_tokens(tokens: list[tuple[float, float, float, float, str]]) -> str:
    cleaned = []
    for x0, y0, x1, y1, text in tokens:
        token = clean_answer_token(text)
        if not token or token in {"[", "]"}:
            continue
        cleaned.append((x0, y0, x1, y1, token))

    if not cleaned:
        return ""

    cleaned.sort(key=lambda item: (item[1], item[0]))
    if len(cleaned) == 2:
        a, b = cleaned
        same_x = abs(((a[0] + a[2]) / 2) - ((b[0] + b[2]) / 2)) <= 8
        separated_y = abs(((a[1] + a[3]) / 2) - ((b[1] + b[3]) / 2)) >= 5
        if same_x and separated_y:
            top, bottom = sorted(cleaned, key=lambda item: item[1])
            return normalize_answer_text(f"{top[4].strip('/')}/{bottom[4].strip('/')}")

    same_line = max(item[3] for item in cleaned) - min(item[1] for item in cleaned) <= 16
    if same_line:
        return normalize_answer_text("".join(item[4] for item in sorted(cleaned, key=lambda item: item[0])))

    return normalize_answer_text("/".join(item[4].strip("/") for item in cleaned))


def normalize_answer_text(text: str) -> str:
    value = str(text or "").strip()
    value = re.sub(r"√/+([A-Za-z0-9]+)", r"√\1", value)
    value = value.replace("/또는/", "또는").replace("또는/", "또는").replace("/또는", "또는")
    value = re.sub(r"/{2,}", "/", value)
    return value.strip("/")


def line_words(words: list[tuple], y_center: float, tolerance: float = 3.0) -> list[tuple]:
    row = [word for word in words if abs(((word[1] + word[3]) / 2) - y_center) <= tolerance]
    row.sort(key=lambda word: word[0])
    return row


def find_question_no(row: list[tuple], answer_word: tuple) -> int | None:
    candidates = [
        word
        for word in row
        if word[0] < answer_word[0] and re.fullmatch(r"\d{1,2}\.", str(word[4] or ""))
    ]
    if not candidates:
        return None
    return int(str(candidates[-1][4]).rstrip("."))


def find_answer_start(row: list[tuple], answer_word: tuple) -> float:
    right_brackets = [word for word in row if word[4] == "]" and word[0] > answer_word[0]]
    if right_brackets:
        return max(word[2] for word in right_brackets) + 0.5
    return answer_word[2] + 0.5


def find_explanation_y(
    words: list[tuple],
    answer_word: tuple,
    question_x: float,
    column_min: float,
    column_max: float,
) -> float | None:
    y_center = (answer_word[1] + answer_word[3]) / 2
    candidates = []
    for word in words:
        if word[4] != "해설":
            continue
        if not (column_min <= word[0] <= column_max):
            continue
        word_y = (word[1] + word[3]) / 2
        if word_y <= y_center:
            continue
        if abs(word[0] - question_x) <= 16 or abs(word[0] - answer_word[0]) <= 16:
            candidates.append(word[1])
    return min(candidates) if candidates else None


def extract_inline_answers(pdf_path: Path) -> tuple[list[str], list[str]]:
    answers: dict[int, str] = {}
    warnings: list[str] = []

    with fitz.open(str(pdf_path)) as doc:
        for page_index, page in enumerate(doc):
            words = page.get_text("words")
            for word in words:
                if word[4] != "정답":
                    continue
                split_x = float(page.rect.width) / 2
                column_min, column_max = (0.0, split_x) if word[0] < split_x else (split_x, float(page.rect.width))
                y_center = (word[1] + word[3]) / 2
                row = [item for item in line_words(words, y_center) if column_min <= item[0] <= column_max]
                question_no = find_question_no(row, word)
                if not question_no:
                    continue
                if question_no in answers:
                    warnings.append(f"duplicate answer label for question {question_no} on page {page_index + 1}")
                    continue

                question_words = [item for item in row if item[0] < word[0] and re.fullmatch(r"\d{1,2}\.", str(item[4] or ""))]
                question_x = question_words[-1][0] if question_words else word[0]
                x_start = find_answer_start(row, word)
                explain_y = find_explanation_y(words, word, question_x, column_min, column_max)
                y_min = min(item[1] for item in row) - 10
                same_row_tokens = [
                    (item[0], item[1], item[2], item[3], item[4])
                    for item in row
                    if item[0] >= x_start and item[4] not in {"정답", "해설", "[", "]"}
                ]
                same_row_text = "".join(str(item[4] or "") for item in same_row_tokens)
                needs_fraction_band = (not same_row_tokens) or ("\ue06d" in same_row_text)
                if needs_fraction_band:
                    x_max = min(column_max, (max((item[2] for item in same_row_tokens), default=x_start) + 24) if same_row_tokens else x_start + 110)
                    y_max = min((explain_y - 0.5) if explain_y else (max(item[3] for item in row) + 26), max(item[3] for item in row) + 30)
                else:
                    x_max = min(column_max, max(item[2] for item in same_row_tokens) + 2)
                    y_max = max(item[3] for item in row) + 2

                tokens = []
                for item in words:
                    x0, y0, x1, y1, text, *_ = item
                    y_mid = (y0 + y1) / 2
                    if not (x_start <= x0 <= x_max and y_min <= y_mid <= y_max):
                        continue
                    if text in {"정답", "해설", "[", "]"}:
                        continue
                    tokens.append((x0, y0, x1, y1, text))

                answer = answer_from_tokens(tokens)
                if not answer:
                    warnings.append(f"empty answer for question {question_no} on page {page_index + 1}")
                answers[question_no] = answer

    if not answers:
        return [], ["no inline answer labels found"]

    problem_count = max(answers)
    ordered = [answers.get(index, "") for index in range(1, problem_count + 1)]
    missing = [str(index) for index, value in enumerate(ordered, start=1) if not value]
    if missing:
        warnings.append(f"missing answers for questions: {', '.join(missing)}")
    return ordered, warnings


def apply_manual_overrides(item: DrivePdf, answers: list[str], warnings: list[str]) -> tuple[list[str], list[str]]:
    key = (item.spec.slug, item.round_no)
    if key in FULL_MANUAL_ANSWERS:
        return FULL_MANUAL_ANSWERS[key], []

    patches = PATCH_MANUAL_ANSWERS.get(key)
    if not patches:
        return answers, warnings

    patched = list(answers)
    max_question = max(max(patches), len(patched))
    if len(patched) < max_question:
        patched.extend([""] * (max_question - len(patched)))
    for question_no, answer in patches.items():
        patched[question_no - 1] = answer

    remaining_missing = [str(index) for index, value in enumerate(patched, start=1) if not value]
    next_warnings = []
    if remaining_missing:
        next_warnings.append(f"missing answers for questions: {', '.join(remaining_missing)}")
    return patched, next_warnings


def answer_pdf_path(download_dir: Path, item: DrivePdf) -> Path:
    name = safe_file_part(clean_title(item.title))
    return download_dir / item.spec.slug / f"{item.round_no:02d}_{name}_solution.pdf"


def process_solution(item: DrivePdf, download_dir: Path):
    pdf_path = answer_pdf_path(download_dir, item)
    try:
        download_pdf(f"https://drive.google.com/file/d/{item.file_id}/view", pdf_path)
        answers, warnings = extract_inline_answers(pdf_path)
        answers, warnings = apply_manual_overrides(item, answers, warnings)
        return item, answers, warnings, None
    except Exception as exc:  # noqa: BLE001 - batch report and continue.
        return (
            item,
            [],
            [],
            {
                "type": "extract_failed",
                "folder": item.spec.label,
                "round": str(item.round_no),
                "name": clean_title(item.title),
                "file": item.path,
                "message": str(exc),
            },
        )


def build_pairs(spec: FolderSpec, issues: list[dict[str, str]]) -> list[tuple[DrivePdf, DrivePdf]]:
    files = iter_folder_pdfs(spec)
    problems: dict[int, DrivePdf] = {}
    solutions: dict[int, DrivePdf] = {}

    for item in files:
        target = solutions if item.is_solution else problems
        if item.round_no in target:
            issues.append(
                {
                    "type": "duplicate_solution" if item.is_solution else "duplicate_problem",
                    "folder": spec.label,
                    "round": str(item.round_no),
                    "name": clean_title(item.title),
                    "file": item.path,
                    "message": f"already saw {target[item.round_no].path}",
                }
            )
            continue
        target[item.round_no] = item

    pairs: list[tuple[DrivePdf, DrivePdf]] = []
    for round_no in sorted(set(problems) | set(solutions)):
        problem = problems.get(round_no)
        solution = solutions.get(round_no)
        if not problem:
            issues.append(
                {
                    "type": "missing_problem",
                    "folder": spec.label,
                    "round": str(round_no),
                    "name": clean_title(solution.title) if solution else "",
                    "file": solution.path if solution else "",
                    "message": "solution exists without a matching problem PDF",
                }
            )
            continue
        if not solution:
            issues.append(
                {
                    "type": "missing_solution",
                    "folder": spec.label,
                    "round": str(round_no),
                    "name": clean_title(problem.title),
                    "file": problem.path,
                    "message": "problem exists without a matching solution PDF",
                }
            )
            continue
        pairs.append((problem, solution))

    print(
        f"{spec.label}: problems={len(problems)} solutions={len(solutions)} pairs={len(pairs)}",
        file=sys.stderr,
    )
    return pairs


def build_catalog(download_dir: Path, workers: int) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    issues: list[dict[str, str]] = []
    pairs: list[tuple[DrivePdf, DrivePdf]] = []

    for spec in FOLDERS:
        pairs.extend(build_pairs(spec, issues))

    solution_results = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        futures = [executor.submit(process_solution, solution, download_dir) for _, solution in pairs]
        for done_count, future in enumerate(as_completed(futures), start=1):
            if done_count % 10 == 0 or done_count == len(futures):
                print(f"processed solution PDFs={done_count}/{len(futures)}", file=sys.stderr)
            solution_results.append(future.result())

    answers_by_id = {item.file_id: (answers, warnings, issue) for item, answers, warnings, issue in solution_results}
    rows: list[dict[str, str]] = []

    for problem, solution in sorted(pairs, key=lambda pair: (pair[0].spec.order_offset, pair[0].round_no)):
        answers, warnings, issue = answers_by_id.get(solution.file_id, ([], [], None))
        if issue:
            issues.append(issue)
        for warning in warnings:
            issues.append(
                {
                    "type": "answer_warning",
                    "folder": solution.spec.label,
                    "round": str(solution.round_no),
                    "name": clean_title(problem.title),
                    "file": solution.path,
                    "message": warning,
                }
            )
        if not answers:
            issues.append(
                {
                    "type": "empty_answers",
                    "folder": solution.spec.label,
                    "round": str(solution.round_no),
                    "name": clean_title(problem.title),
                    "file": solution.path,
                    "message": "",
                }
            )

        source_order = problem.spec.order_offset + problem.round_no
        rows.append(
            {
                "id": f"t_review_{problem.spec.slug}_{problem.round_no:02d}",
                "category": "REVIEW",
                "subject": problem.spec.subject,
                "difficulty": problem.spec.difficulty,
                "round": str(problem.round_no),
                "name": clean_title(problem.title),
                "problems": str(len(answers)),
                "answers": answer_list_text(answers, len(answers)),
                "source_order": str(source_order),
                "problem_file": problem.title,
                "solution_file": solution.title,
                "problem_file_id": problem.file_id,
                "solution_file_id": solution.file_id,
            }
        )

    return rows, issues


def write_csv(path: Path, rows: list[dict[str, str]], headers: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_issues(path: Path, issues: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=ISSUE_HEADERS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(issues)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--download-dir", type=Path, default=Path(".codex_drive_download/review_answer_pdfs"))
    parser.add_argument("--output", type=Path, default=Path("generated/review_test_catalog.csv"))
    parser.add_argument("--issues", type=Path, default=Path("generated/review_test_catalog_issues.csv"))
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args(argv)

    rows, issues = build_catalog(args.download_dir, workers=args.workers)
    write_csv(args.output, rows, CSV_HEADERS)
    write_issues(args.issues, issues)

    filled = sum(1 for row in rows if row.get("answers"))
    print(f"rows={len(rows)} filled={filled} issues={len(issues)}")
    print(f"csv={args.output}")
    print(f"issues={args.issues}")
    return 0 if not issues else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
