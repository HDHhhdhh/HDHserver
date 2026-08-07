from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any

import fitz
import gdown

from build_unit_test_csv_from_link_map import answer_list_text, download_pdf, safe_file_part


@dataclass(frozen=True)
class FolderSpec:
    label: str
    folder_id: str
    slug: str
    subject: str
    difficulty: str
    term: str
    exam_term: str
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
    FolderSpec("공수1 상 중간", "1ekojZCDECFilxqQktpVRZch_0BVA2MQ2", "gongsu1_high_midterm", "공수1", "상", "중간고사", "중간고사", 0),
    FolderSpec("공수1 상 기말", "15kS-2cS4EFMmHHwXMolsnnEFPp3Moq2T", "gongsu1_high_final", "공수1", "상", "기말고사", "기말고사", 100),
    FolderSpec("공수1 중상 중간", "1QDOS_w7Laxx4FyvEkg3d7qiopjyhKQ2w", "gongsu1_mid_high_midterm", "공수1", "중상", "중간고사", "중간고사", 200),
    FolderSpec("공수1 중상 기말", "15u_A0fDn_mRbTgw28-dFA-z-vccMiwiL", "gongsu1_mid_high_final", "공수1", "중상", "기말고사", "기말고사", 300),
    FolderSpec("대수 상 중간", "1YUc6wnZczNu4KnMegbMYJjVtiyn7a7Ja", "daesu_high_midterm", "대수", "상", "중간고사", "중간고사", 400),
    FolderSpec("대수 상 기말", "17-M2w7XZWndp-Wsw2Vgq10RMgmgZShfd", "daesu_high_final", "대수", "상", "기말고사", "기말고사", 500),
    FolderSpec("대수 중상 중간", "1cq-uVlM5kobqUnsdu2MEEq0SyzcFadNH", "daesu_mid_high_midterm", "대수", "중상", "중간고사", "중간고사", 600),
    FolderSpec("대수 중상 기말", "1kQ75bmJyZJbUZA1jMLX1LJIFR46t1hz1", "daesu_mid_high_final", "대수", "중상", "기말고사", "기말고사", 700),
]

CSV_HEADERS = [
    "id",
    "category",
    "subject",
    "difficulty",
    "term",
    "examTerm",
    "round",
    "name",
    "problems",
    "answers_json",
    "answers",
    "source_order",
    "problem_file",
    "solution_file",
    "problem_file_id",
    "solution_file_id",
    "warnings",
]

EXCLUDED_RE = re.compile(r"(손풀이|손해설|참고용)")
SOLUTION_RE = re.compile(r"(해설|정답)")
ROUND_RE = re.compile(r"^\s*(\d{1,3})(?:\s*회|\s*차|[.)_\-\s])")
CIRCLED = {
    "\u2460": "1",
    "\u2461": "2",
    "\u2462": "3",
    "\u2463": "4",
    "\u2464": "5",
}

PUA_MAP = str.maketrans({
    "\ue000": "A",
    "\ue00f": "f",
    "\ue010": "Q",
    "\ue011": "",
    "\ue012": "b",
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
    "\ue03e": "!",
    "\ue044": "(",
    "\ue045": ")",
    "\ue046": "-",
    "\ue047": "=",
    "\ue048": "+",
    "\ue04b": "{",
    "\ue04c": "}",
    "\ue04f": ":",
    "\ue052": ",",
    "\ue053": "P",
    "\ue055": "≤",
    "\ue056": ">",
    "\ue05c": "√",
    "\ue06d": "/",
    "\ue078": "{",
    "\ue079": "",
    "\ue07a": "",
    "\ue07b": "",
    "\ue0a4": "θ",
    "\ue0ac": "π",
    "\ue0e5": "a",
    "\ue0e6": "b",
    "\ue0e7": "c",
    "\ue0e8": "d",
    "\ue0e9": "e",
    "\ue0ea": "f",
    "\ue0eb": "g",
    "\ue0ed": "i",
    "\ue0ee": "j",
    "\ue0ef": "a",
    "\ue0f0": "b",
    "\ue0f1": "m",
    "\ue0f2": "n",
    "\ue0f4": "p",
    "\ue0f5": "q",
    "\ue0f8": "t",
    "\ue0fc": "x",
    "\ue0fd": "y",
    "\ue0fe": "z",
})


def split_drive_path(path: str) -> tuple[str, ...]:
    normalized = str(path or "").replace("/", "\\")
    return PureWindowsPath(normalized).parts


def drive_file_title(drive_file: Any) -> str:
    title = str(getattr(drive_file, "name", "") or "").strip()
    if title:
        return title
    path = str(getattr(drive_file, "path", "") or "")
    parts = split_drive_path(path)
    return parts[-1] if parts else path


def clean_title(title: str) -> str:
    value = re.sub(r"\.pdf$", "", str(title or ""), flags=re.IGNORECASE).strip()
    value = re.sub(r"\s*(해설|정답)\s*$", "", value).strip()
    value = re.sub(r"\s+", " ", value)
    return value


def round_from_title(title: str) -> int | None:
    match = ROUND_RE.search(str(title or ""))
    return int(match.group(1)) if match else None


def is_solution(title: str, path: str) -> bool:
    haystack = " ".join([str(title or ""), str(path or "")])
    return bool(SOLUTION_RE.search(haystack))


def iter_folder_pdfs(spec: FolderSpec) -> tuple[list[DrivePdf], list[str]]:
    warnings: list[str] = []
    try:
        files = gdown.download_folder(id=spec.folder_id, quiet=True, skip_download=True)
    except Exception as exc:  # noqa: BLE001 - batch report and continue.
        return [], [f"folder list failed: {exc}"]

    out: list[DrivePdf] = []
    for drive_file in files or []:
        file_id = str(getattr(drive_file, "id", "") or "").strip()
        path = str(getattr(drive_file, "path", "") or "")
        title = drive_file_title(drive_file)
        full_name = " ".join([title, path])
        if not file_id or not title.lower().endswith(".pdf"):
            continue
        if EXCLUDED_RE.search(full_name):
            continue
        round_no = round_from_title(title)
        if not round_no:
            warnings.append(f"skipped file without leading round number: {path or title}")
            continue
        out.append(
            DrivePdf(
                spec=spec,
                file_id=file_id,
                title=title,
                path=path or title,
                round_no=round_no,
                is_solution=is_solution(title, path),
            )
        )
    return out, warnings


def clean_answer_token(text: str) -> str:
    value = unicodedata.normalize("NFKC", str(text or ""))
    value = value.translate(PUA_MAP)
    value = value.replace("\u200b", "").replace("\ufeff", "")
    value = value.replace("\u2212", "-").replace("\u2013", "-").replace("\u2014", "-")
    value = re.sub(r"^\s*정답\s*", "", value)
    value = re.sub(r"[\ue000-\uf8ff]", "", value)
    value = value.strip()
    value = CIRCLED.get(value, value)
    return value.strip("[](){}.,;:")


def normalize_answer(text: str) -> str:
    value = unicodedata.normalize("NFKC", str(text or ""))
    value = value.translate(PUA_MAP)
    value = value.replace("\u200b", "").replace("\ufeff", "")
    value = value.replace("\u2212", "-").replace("\u2013", "-").replace("\u2014", "-")
    value = re.sub(r"^\s*정답\s*", "", value)
    value = re.sub(r"[\ue000-\uf8ff]", "", value)
    value = re.sub(r"\s+", "", value)
    value = value.strip("[](){}.,;:")
    value = fix_stacked_fraction_text(value)
    return CIRCLED.get(value, value)


def split_stacked_digits(digits: str) -> tuple[str, str]:
    if len(digits) <= 1:
        return digits, ""
    if len(digits) == 2:
        return digits[0], digits[1]
    first_two = int(digits[:2])
    if first_two <= 36:
        return digits[:2], digits[2:]
    return digits[0], digits[1:]


def fix_stacked_fraction_text(value: str) -> str:
    value = re.sub(r"√/(\d+)", r"√\1", value)

    def repl(match: re.Match[str]) -> str:
        sign = match.group(1) or ""
        digits = match.group(2)
        suffix = match.group(3) or ""
        denominator, numerator_digits = split_stacked_digits(digits)
        numerator = f"{numerator_digits}{suffix}" if numerator_digits else suffix
        if not numerator:
            return match.group(0)
        return f"{sign}{numerator}/{denominator}"

    return re.sub(r"(?<![A-Za-z0-9가-힣θπ])(-?)/(\d+)(π|√\d+)?(?=$|[^A-Za-z0-9가-힣])", repl, value)


def normalize_answer_block(text: str) -> str:
    lines = [normalize_answer(line) for line in str(text or "").splitlines()]
    lines = [line for line in lines if line]
    if len(lines) >= 3:
        first, second, third = lines[0], lines[1], lines[2]
        match = re.fullmatch(r"(-?)/(\d+)", first)
        second_match = re.fullmatch(r"(\d+)([≤<>=].*)/(\d+)", second)
        if match and second_match and re.fullmatch(r"\d+", third):
            sign, left_den = match.groups()
            left_num, middle, right_den = second_match.groups()
            return f"{sign}{left_num}/{left_den}{middle}{third}/{right_den}"
    return normalize_answer("".join(lines))


def first_page_quick_answer_text(pdf_path: Path) -> tuple[str, list[str]]:
    warnings: list[str] = []
    with fitz.open(str(pdf_path)) as doc:
        if doc.page_count < 1:
            return "", ["PDF has no pages"]
        text = doc[0].get_text("text") or ""

    quick_match = re.search(r"\[\s*빠른\s*정답\s*\]|\b빠른\s*정답\b", text)
    explain_match = re.search(r"\[\s*해설\s*\]|\b해설\b", text)
    if not quick_match:
        warnings.append("first page quick-answer marker not found")
        start = 0
    else:
        start = quick_match.end()
    if not explain_match or explain_match.start() <= start:
        warnings.append("first page explanation marker not found after quick-answer section")
        end = len(text)
    else:
        end = explain_match.start()
    return text[start:end], warnings


def parse_numbered_answers(section: str) -> list[str]:
    lines = []
    for line in str(section or "").splitlines():
        line = re.sub(r"\s+", " ", line.translate(PUA_MAP)).strip()
        if line:
            lines.append(line)
    compact = "\n".join(lines)

    matches = list(re.finditer(r"(?m)^\s*(\d{1,2})\s*[.)]\s+", compact))
    found: dict[int, str] = {}
    for index, match in enumerate(matches):
        question_no = int(match.group(1))
        if question_no < 1 or question_no > 100:
            continue
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(compact)
        answer = normalize_answer_block(compact[start:end])
        if answer:
            found.setdefault(question_no, answer)

    if not found:
        tokens = [clean_answer_token(token) for token in re.split(r"[\s,]+", compact) if clean_answer_token(token)]
        for index, token in enumerate(tokens):
            if not re.fullmatch(r"\d{1,2}", token):
                continue
            question_no = int(token)
            if question_no < 1 or question_no > 100 or question_no in found:
                continue
            if index + 1 < len(tokens):
                answer = normalize_answer(tokens[index + 1])
                if answer and not re.fullmatch(r"\d{1,2}", answer):
                    found[question_no] = answer

    if not found:
        return []
    max_question = max(found)
    return [found.get(question_no, "") for question_no in range(1, max_question + 1)]


def extract_answers(pdf_path: Path) -> tuple[list[str], list[str]]:
    try:
        section, warnings = first_page_quick_answer_text(pdf_path)
        answers = parse_numbered_answers(section)
        if not answers:
            warnings.append("no answers parsed from first page quick-answer section")
        missing = [str(index) for index, answer in enumerate(answers, start=1) if not answer]
        if missing:
            warnings.append(f"missing answers for questions: {', '.join(missing)}")
        return answers, warnings
    except Exception as exc:  # noqa: BLE001 - batch report and continue.
        return [], [f"answer extraction failed: {exc}"]


def solution_pdf_path(download_dir: Path, item: DrivePdf) -> Path:
    name = safe_file_part(clean_title(item.title))
    return download_dir / item.spec.slug / f"{item.round_no:03d}_{name}_solution.pdf"


def process_solution(item: DrivePdf, download_dir: Path) -> tuple[str, list[str], list[str]]:
    pdf_path = solution_pdf_path(download_dir, item)
    warnings: list[str] = []
    try:
        download_pdf(f"https://drive.google.com/file/d/{item.file_id}/view", pdf_path)
    except Exception as exc:  # noqa: BLE001 - batch report and continue.
        return item.file_id, [], [f"solution download failed: {exc}"]
    answers, extract_warnings = extract_answers(pdf_path)
    warnings.extend(extract_warnings)
    return item.file_id, answers, warnings


def choose_duplicate(current: DrivePdf | None, candidate: DrivePdf, warnings: list[str], kind: str) -> DrivePdf:
    if current is None:
        return candidate
    warnings.append(
        f"duplicate {kind} for {candidate.spec.label} round {candidate.round_no}: kept {current.path}; skipped {candidate.path}"
    )
    return current


def build_pairs(spec: FolderSpec) -> tuple[list[tuple[DrivePdf | None, DrivePdf | None]], list[str]]:
    files, warnings = iter_folder_pdfs(spec)
    problems: dict[int, DrivePdf] = {}
    solutions: dict[int, DrivePdf] = {}

    for item in files:
        if item.is_solution:
            solutions[item.round_no] = choose_duplicate(solutions.get(item.round_no), item, warnings, "solution")
        else:
            problems[item.round_no] = choose_duplicate(problems.get(item.round_no), item, warnings, "problem")

    pairs: list[tuple[DrivePdf | None, DrivePdf | None]] = []
    for round_no in sorted(set(problems) | set(solutions)):
        problem = problems.get(round_no)
        solution = solutions.get(round_no)
        if not problem:
            warnings.append(f"{spec.label} round {round_no}: problem PDF missing")
        if not solution:
            warnings.append(f"{spec.label} round {round_no}: solution PDF missing")
        pairs.append((problem, solution))

    print(f"{spec.label}: problems={len(problems)} solutions={len(solutions)} rows={len(pairs)}", file=sys.stderr)
    return pairs, warnings


def row_name(problem: DrivePdf | None, solution: DrivePdf | None) -> str:
    source = problem or solution
    if not source:
        return ""
    return clean_title(source.title)


def build_catalog(download_dir: Path, workers: int) -> list[dict[str, str]]:
    all_pairs: list[tuple[DrivePdf | None, DrivePdf | None]] = []
    folder_warnings: dict[tuple[str, int], list[str]] = {}
    solutions: list[DrivePdf] = []

    for spec in FOLDERS:
        pairs, warnings = build_pairs(spec)
        for warning in warnings:
            match = re.search(r"round\s+(\d+)", warning)
            round_no = int(match.group(1)) if match else 0
            folder_warnings.setdefault((spec.slug, round_no), []).append(warning)
        all_pairs.extend(pairs)
        solutions.extend(solution for _, solution in pairs if solution is not None)

    answer_results: dict[str, tuple[list[str], list[str]]] = {}
    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        futures = [executor.submit(process_solution, solution, download_dir) for solution in solutions]
        for done_count, future in enumerate(as_completed(futures), start=1):
            if done_count % 10 == 0 or done_count == len(futures):
                print(f"processed solution PDFs={done_count}/{len(futures)}", file=sys.stderr)
            file_id, answers, warnings = future.result()
            answer_results[file_id] = (answers, warnings)

    rows: list[dict[str, str]] = []
    for problem, solution in sorted(
        all_pairs,
        key=lambda pair: ((pair[0] or pair[1]).spec.order_offset, (pair[0] or pair[1]).round_no),  # type: ignore[union-attr]
    ):
        source = problem or solution
        if source is None:
            continue
        answers, answer_warnings = answer_results.get(solution.file_id, ([], [])) if solution else ([], [])
        warnings = list(folder_warnings.get((source.spec.slug, source.round_no), []))
        warnings.extend(answer_warnings)
        if solution and not answers:
            warnings.append("empty answers")

        source_order = source.spec.order_offset + source.round_no
        problems = len(answers)
        rows.append(
            {
                "id": f"t_school_past_{source.spec.slug}_{source.round_no:03d}",
                "category": "SCHOOL_PAST",
                "subject": source.spec.subject,
                "difficulty": source.spec.difficulty,
                "term": source.spec.term,
                "examTerm": source.spec.exam_term,
                "round": str(source.round_no),
                "name": row_name(problem, solution),
                "problems": str(problems),
                "answers_json": json.dumps(answers, ensure_ascii=False),
                "answers": answer_list_text(answers, problems),
                "source_order": str(source_order),
                "problem_file": problem.title if problem else "",
                "solution_file": solution.title if solution else "",
                "problem_file_id": problem.file_id if problem else "",
                "solution_file_id": solution.file_id if solution else "",
                "warnings": " | ".join(warnings),
            }
        )

    return rows


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_HEADERS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--download-dir", type=Path, default=Path(".codex_drive_download/school_past_answer_pdfs"))
    parser.add_argument("--output", type=Path, default=Path("generated/school_past_test_catalog.csv"))
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args(argv)

    rows = build_catalog(args.download_dir, workers=args.workers)
    write_csv(args.output, rows)

    filled = sum(1 for row in rows if row.get("answers"))
    warned = sum(1 for row in rows if row.get("warnings"))
    print(f"rows={len(rows)} filled={filled} warned={warned}")
    print(f"csv={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
