from __future__ import annotations

import argparse
import csv
import json
import re
import time
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote

import fitz


DRIVE_ID_RE = re.compile(r"/d/([A-Za-z0-9_-]+)|[?&]id=([A-Za-z0-9_-]+)")

CIRCLED = {
    "\u2460": "1",
    "\u2461": "2",
    "\u2462": "3",
    "\u2463": "4",
    "\u2464": "5",
}

LABEL_ZONES = ((40.0, 61.0), (99.0, 118.0), (158.0, 178.0), (216.0, 236.0))


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def clean_token(text: str) -> str:
    text = unicodedata.normalize("NFKC", str(text or ""))
    text = text.replace("\u200b", "").replace("\ufeff", "")
    text = text.replace("\u2212", "-").replace("\u2013", "-").replace("\u2014", "-")
    text = text.strip()
    return CIRCLED.get(text, text)


def cell_answer(tokens: list[tuple[float, float, float, float, str]]) -> str:
    cleaned = []
    for x0, y0, x1, y1, text in tokens:
        token = clean_token(text)
        if not token:
            continue
        cleaned.append((x0, y0, x1, y1, token))

    if not cleaned:
        return ""

    cleaned.sort(key=lambda item: (item[1], item[0]))

    if len(cleaned) == 2:
        a, b = cleaned
        same_x = abs(((a[0] + a[2]) / 2) - ((b[0] + b[2]) / 2)) <= 6
        separated_y = abs(((a[1] + a[3]) / 2) - ((b[1] + b[3]) / 2)) >= 7
        simple = all(re.fullmatch(r"-?\d+", item[4]) for item in cleaned)
        if same_x and separated_y and simple:
            top, bottom = sorted(cleaned, key=lambda item: item[1])
            return f"{top[4]}/{bottom[4]}"

    same_line = max(item[3] for item in cleaned) - min(item[1] for item in cleaned) <= 18
    if same_line:
        return "".join(item[4] for item in sorted(cleaned, key=lambda item: item[0]))

    return "/".join(item[4] for item in cleaned)


def in_label_zone(x0: float) -> bool:
    return any(start <= x0 <= end for start, end in LABEL_ZONES)


def match_question_label(row_words: list[tuple], start_index: int, question_no: int):
    token = clean_token(row_words[start_index][4])
    if not in_label_zone(row_words[start_index][0]):
        return None

    digits = str(question_no)
    if question_no < 10:
        if token == "0" and start_index + 1 < len(row_words):
            next_word = row_words[start_index + 1]
            next_token = clean_token(next_word[4])
            close = 0 <= next_word[0] - row_words[start_index][2] <= 8
            if next_token == digits and close:
                return {
                    "start": row_words[start_index][0],
                    "end": next_word[2],
                    "word_indexes": {start_index, start_index + 1},
                }
        if token == digits:
            return {
                "start": row_words[start_index][0],
                "end": row_words[start_index][2],
                "word_indexes": {start_index},
            }
        return None

    if token == digits:
        return {
            "start": row_words[start_index][0],
            "end": row_words[start_index][2],
            "word_indexes": {start_index},
        }

    if start_index + 1 < len(row_words):
        next_word = row_words[start_index + 1]
        next_token = clean_token(next_word[4])
        close = 0 <= next_word[0] - row_words[start_index][2] <= 8
        if token == digits[0] and next_token == digits[1] and close:
            return {
                "start": row_words[start_index][0],
                "end": next_word[2],
                "word_indexes": {start_index, start_index + 1},
            }
    return None


def extract_quick_answers_dynamic(words: list[tuple], expected: int = 20) -> list[str]:
    label_y = []
    for x0, y0, x1, y1, text, *_ in words:
        token = clean_token(text)
        yc = (y0 + y1) / 2
        if 95 <= yc <= 285 and in_label_zone(x0) and re.fullmatch(r"\d{1,2}", token):
            label_y.append(yc)

    if not label_y:
        return []

    label_y.sort()
    row_centers: list[float] = []
    for y in label_y:
        if not row_centers or abs(y - row_centers[-1]) > 8:
            row_centers.append(y)
        else:
            row_centers[-1] = (row_centers[-1] + y) / 2

    labels = []
    question_no = 1
    for row_y in row_centers:
        if question_no > expected:
            break
        row_words = [
            word
            for word in words
            if row_y - 11.5 <= (word[1] + word[3]) / 2 <= row_y + 11.5 and 35 <= word[0] <= 310
        ]
        row_words.sort(key=lambda word: (word[0], word[1]))

        cursor = 0
        while question_no <= expected and cursor < len(row_words):
            match = match_question_label(row_words, cursor, question_no)
            if not match:
                cursor += 1
                continue
            labels.append(
                {
                    "q": question_no,
                    "row_y": row_y,
                    "start": match["start"],
                    "end": match["end"],
                    "row_words": row_words,
                    "word_indexes": match["word_indexes"],
                }
            )
            question_no += 1
            cursor = max(match["word_indexes"]) + 1

    if len(labels) < max(10, expected // 2):
        return []

    answers: list[str] = []
    for index, label in enumerate(labels[:expected]):
        same_row_next = None
        if index + 1 < len(labels) and abs(labels[index + 1]["row_y"] - label["row_y"]) <= 2:
            same_row_next = labels[index + 1]

        x_min = label["end"] + 0.5
        x_max = (same_row_next["start"] - 1.0) if same_row_next else 310.0
        tokens = []
        for word_index, word in enumerate(label["row_words"]):
            x0, y0, x1, y1, text, *_ = word
            xc = (x0 + x1) / 2
            token = clean_token(text)
            if word_index in label["word_indexes"]:
                continue
            if not (x_min <= xc <= x_max):
                continue
            # Ignore stray leading zeroes from a shifted question label, while
            # keeping real zero answers that sit in answer columns.
            if token == "0" and in_label_zone(x0):
                continue
            tokens.append((x0, y0, x1, y1, text))
        answers.append(cell_answer(tokens))

    return answers


def extract_quick_answers_fixed(words: list[tuple]) -> list[str]:
    # The default APEX quick-answer table is a 4 x 5 grid near the top-left box.
    # This fallback is useful when text extraction does not expose every problem
    # label cleanly enough for the dynamic parser.
    ans_starts = [63.0, 121.0, 179.0, 238.0]
    col_ends = [104.0, 163.0, 221.0, 300.0]

    centers = []
    for x0, y0, x1, y1, text, *_ in words:
        token = clean_token(text)
        if not token:
            continue
        yc = (y0 + y1) / 2
        if 95 <= yc <= 260 and 35 <= x0 <= 280:
            if re.fullmatch(r"\d{1,2}", token) or token in CIRCLED.values():
                centers.append(yc)

    if not centers:
        return []

    centers.sort()
    row_centers: list[float] = []
    for y in centers:
        if not row_centers or abs(y - row_centers[-1]) > 8:
            row_centers.append(y)
        else:
            row_centers[-1] = (row_centers[-1] + y) / 2
    row_centers = row_centers[:5]

    if len(row_centers) < 5:
        first = row_centers[0]
        row_centers = [first + 18.75 * i for i in range(5)]

    answers: list[str] = []
    for row_y in row_centers:
        for col_index in range(4):
            y_min = row_y - 10.5
            y_max = row_y + 10.5
            x_min = ans_starts[col_index] - 1.0
            x_max = col_ends[col_index] - 2.0
            tokens = []
            for x0, y0, x1, y1, text, *_ in words:
                yc = (y0 + y1) / 2
                xc = (x0 + x1) / 2
                if y_min <= yc <= y_max and x_min <= xc <= x_max:
                    tokens.append((x0, y0, x1, y1, text))
            answers.append(cell_answer(tokens))

    while answers and answers[-1] == "":
        answers.pop()
    return answers


def score_answers(answers: list[str], expected: int) -> tuple[int, int]:
    head = answers[:expected]
    return (sum(1 for answer in head if str(answer or "").strip()), min(len(answers), expected))


def extract_quick_answers(pdf_path: Path, expected: int = 20) -> list[str]:
    with fitz.open(str(pdf_path)) as doc:
        if doc.page_count < 1:
            return []
        best: list[str] = []
        best_score = (0, 0)
        for page_index in range(min(doc.page_count, 8)):
            words = doc[page_index].get_text("words")
            dynamic = extract_quick_answers_dynamic(words, expected=expected)
            fixed = extract_quick_answers_fixed(words)
            candidate = dynamic if score_answers(dynamic, expected) >= score_answers(fixed, expected) else fixed
            candidate_score = score_answers(candidate, expected)
            if candidate_score > best_score:
                best = candidate
                best_score = candidate_score
            if candidate_score == (expected, expected):
                return candidate
        return best


def drive_file_id(url: str) -> str:
    match = DRIVE_ID_RE.search(str(url or ""))
    if not match:
        raise ValueError(f"Cannot find Drive file id in URL: {url}")
    return match.group(1) or match.group(2)


def drive_download_url(file_id: str) -> str:
    encoded = quote(file_id, safe="")
    return f"https://drive.usercontent.google.com/download?id={encoded}&export=download&authuser=0"


def valid_pdf(path: Path) -> bool:
    try:
        if path.stat().st_size < 1024:
            return False
        with path.open("rb") as fh:
            return fh.read(5) == b"%PDF-"
    except OSError:
        return False


def download_pdf(url: str, dest: Path, retries: int = 3) -> None:
    if valid_pdf(dest):
        return

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    file_id = drive_file_id(url)
    request_url = drive_download_url(file_id)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142 Safari/537.36"
        )
    }

    last_error = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(request_url, headers=headers)
            with urllib.request.urlopen(req, timeout=90) as response:
                tmp.write_bytes(response.read())
            if not valid_pdf(tmp):
                preview = tmp.read_text(encoding="utf-8", errors="replace")[:240]
                raise RuntimeError(f"Downloaded file is not a PDF: {preview!r}")
            tmp.replace(dest)
            return
        except (OSError, urllib.error.URLError, RuntimeError) as exc:
            last_error = exc
            if tmp.exists():
                tmp.unlink()
            time.sleep(min(2 * attempt, 8))

    raise RuntimeError(f"Download failed for {file_id}: {last_error}")


def infer_difficulty(*values: str) -> str:
    for value in values:
        match = re.search(r"Lv\.?\s*([3-6])", str(value or ""), re.IGNORECASE)
        if match:
            return f"Lv.{match.group(1)}"
    return "Lv.3"


def safe_file_part(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "")).strip("._") or "item"


def answer_list_text(values: list[str], problems: int) -> str:
    values = [str(v or "").strip() for v in values[:problems]]
    if len(values) < problems:
        values.extend([""] * (problems - len(values)))
    return " ".join(values).strip()


def build_rows(config: dict, link_map: dict, download_dir: Path, issues: list[dict[str, str]]) -> list[dict[str, str]]:
    unit_tests = config.get("categories", {}).get("UNIT", {}).get("tests", [])
    rows = []

    for index, test in enumerate(unit_tests, start=1):
        test_id = str(test.get("id") or "").strip()
        links = link_map.get(test_id) or {}
        name = str(test.get("name") or links.get("1", {}).get("unitName") or "").strip()
        subject = str(test.get("curriculum") or links.get("1", {}).get("subject") or "").strip()
        problems = int(test.get("problems") or 20)
        difficulty = infer_difficulty(test.get("difficulty"), test.get("level"), name, links.get("1", {}).get("unitName"))

        answer_cols = {"1": "", "2": "", "3": ""}
        for round_no in ("1", "2", "3"):
            info = links.get(round_no) or {}
            answer_url = info.get("answerUrl")
            if not answer_url:
                issues.append({"id": test_id, "round": round_no, "issue": "missing answerUrl"})
                continue

            pdf_path = download_dir / safe_file_part(test_id) / f"{round_no}.pdf"
            try:
                download_pdf(answer_url, pdf_path)
                answers = extract_quick_answers(pdf_path, expected=problems)
            except Exception as exc:
                issues.append({"id": test_id, "round": round_no, "issue": str(exc)})
                continue

            if len(answers) != problems or any(not answer for answer in answers[:problems]):
                issues.append(
                    {
                        "id": test_id,
                        "round": round_no,
                        "issue": f"expected {problems} answers, got {len(answers)}",
                    }
                )
            answer_cols[round_no] = answer_list_text(answers, problems)

        rows.append(
            {
                "id": test_id,
                "category": "UNIT",
                "subject": subject,
                "difficulty": difficulty,
                "round": "1",
                "name": name,
                "problems": str(problems),
                "answers1": answer_cols["1"],
                "answers2": answer_cols["2"],
                "answers3": answer_cols["3"],
                "source_order": str(index),
            }
        )

    return rows


def write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_catalog_csv(path: Path, rows: list[dict[str, str]]) -> None:
    headers = ["id", "분류", "과목", "난이도", "회차", "시험명", "문항수", "1회차정답", "2회차정답", "3회차정답"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(headers)
        for row in rows:
            writer.writerow(
                [
                    row["id"],
                    "단원평가",
                    row["subject"],
                    row["difficulty"],
                    row["round"],
                    row["name"],
                    row["problems"],
                    row["answers1"],
                    row["answers2"],
                    row["answers3"],
                ]
            )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("tests-config.json"))
    parser.add_argument("--link-map", type=Path, default=Path("static/js/test_answer_link_map.json"))
    parser.add_argument("--download-dir", type=Path, default=Path(".codex_drive_download/unit_answer_pdfs"))
    parser.add_argument("--output", type=Path, default=Path("generated/unit_test_catalog.csv"))
    parser.add_argument("--issues", type=Path, default=Path("generated/unit_test_catalog_issues.csv"))
    args = parser.parse_args()

    config = read_json(args.config)
    link_map = read_json(args.link_map)
    issues: list[dict[str, str]] = []
    rows = build_rows(config, link_map, args.download_dir, issues)

    write_catalog_csv(args.output, rows)
    write_csv(args.issues, issues, ["id", "round", "issue"])

    filled = sum(1 for row in rows for key in ("answers1", "answers2", "answers3") if row.get(key))
    print(f"rows={len(rows)} filled_rounds={filled} issues={len(issues)}")
    print(f"csv={args.output}")
    print(f"issues={args.issues}")
    return 0 if not issues else 1


if __name__ == "__main__":
    raise SystemExit(main())
