from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

import fitz


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

EXPECTED_ROUNDS = ("1", "2", "3")
EXPECTED_PROBLEMS = 20
CHOICE_NUMBER = "choice_number"
ANSWER_VALUE = "answer_value"
MANUAL_REVIEW = "manual_review"
VALID_MODES = frozenset({CHOICE_NUMBER, ANSWER_VALUE, MANUAL_REVIEW})
CIRCLED = {"①": "1", "②": "2", "③": "3", "④": "4", "⑤": "5"}
LABEL_ZONES = ((40.0, 61.0), (99.0, 118.0), (158.0, 178.0), (216.0, 236.0))


class ReconciliationError(ValueError):
    pass


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def clean_token(text: str) -> str:
    value = unicodedata.normalize("NFKC", str(text or ""))
    value = value.replace("\u200b", "").replace("\ufeff", "")
    value = value.replace("−", "-").replace("–", "-").replace("—", "-")
    return value.strip()


def cell_answer(tokens: list[tuple[float, float, float, float, str]]) -> str:
    cleaned = []
    for x0, y0, x1, y1, raw_text in tokens:
        token = clean_token(raw_text)
        if token:
            cleaned.append((x0, y0, x1, y1, token))
    if not cleaned:
        return ""

    cleaned.sort(key=lambda item: (item[1], item[0]))
    if len(cleaned) == 2:
        first, second = cleaned
        same_x = abs(((first[0] + first[2]) / 2) - ((second[0] + second[2]) / 2)) <= 6
        separated_y = abs(((first[1] + first[3]) / 2) - ((second[1] + second[3]) / 2)) >= 7
        simple = all(re.fullmatch(r"-?\d+", item[4]) for item in cleaned)
        if same_x and separated_y and simple:
            top, bottom = sorted(cleaned, key=lambda item: item[1])
            return f"{top[4]}/{bottom[4]}"

    same_line = max(item[3] for item in cleaned) - min(item[1] for item in cleaned) <= 18
    if same_line:
        return "".join(item[4] for item in sorted(cleaned, key=lambda item: item[0]))
    return "/".join(item[4] for item in cleaned)


def raw_answer_mode(tokens: list[tuple[float, float, float, float, str]], answer: str) -> str:
    if any(str(token[4]).strip() in CIRCLED for token in tokens):
        return CHOICE_NUMBER
    return ANSWER_VALUE if answer else MANUAL_REVIEW


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


def extract_dynamic_evidence(words: list[tuple]) -> tuple[list[str], list[str]]:
    label_y = []
    for x0, y0, x1, y1, raw_text, *_ in words:
        token = clean_token(raw_text)
        y_center = (y0 + y1) / 2
        if 95 <= y_center <= 285 and in_label_zone(x0) and re.fullmatch(r"\d{1,2}", token):
            label_y.append(y_center)
    if not label_y:
        return [], []

    label_y.sort()
    row_centers: list[float] = []
    for center in label_y:
        if not row_centers or abs(center - row_centers[-1]) > 8:
            row_centers.append(center)
        else:
            row_centers[-1] = (row_centers[-1] + center) / 2

    labels = []
    question_no = 1
    for row_y in row_centers:
        if question_no > EXPECTED_PROBLEMS:
            break
        row_words = [
            word
            for word in words
            if row_y - 11.5 <= (word[1] + word[3]) / 2 <= row_y + 11.5 and 35 <= word[0] <= 310
        ]
        row_words.sort(key=lambda word: (word[0], word[1]))
        cursor = 0
        while question_no <= EXPECTED_PROBLEMS and cursor < len(row_words):
            match = match_question_label(row_words, cursor, question_no)
            if not match:
                cursor += 1
                continue
            labels.append(
                {
                    "row_y": row_y,
                    "start": match["start"],
                    "end": match["end"],
                    "row_words": row_words,
                    "word_indexes": match["word_indexes"],
                }
            )
            question_no += 1
            cursor = max(match["word_indexes"]) + 1
    if len(labels) < max(10, EXPECTED_PROBLEMS // 2):
        return [], []

    answers: list[str] = []
    modes: list[str] = []
    for index, label in enumerate(labels[:EXPECTED_PROBLEMS]):
        same_row_next = None
        if index + 1 < len(labels) and abs(labels[index + 1]["row_y"] - label["row_y"]) <= 2:
            same_row_next = labels[index + 1]
        x_min = label["end"] + 0.5
        x_max = same_row_next["start"] - 1.0 if same_row_next else 310.0
        tokens = []
        for word_index, word in enumerate(label["row_words"]):
            x0, y0, x1, y1, raw_text, *_ = word
            x_center = (x0 + x1) / 2
            token = clean_token(raw_text)
            if word_index in label["word_indexes"] or not (x_min <= x_center <= x_max):
                continue
            if token == "0" and in_label_zone(x0):
                continue
            tokens.append((x0, y0, x1, y1, raw_text))
        answer = cell_answer(tokens)
        answers.append(answer)
        modes.append(raw_answer_mode(tokens, answer))
    return answers, modes


def extract_fixed_evidence(words: list[tuple]) -> tuple[list[str], list[str]]:
    answer_starts = [63.0, 121.0, 179.0, 238.0]
    column_ends = [104.0, 163.0, 221.0, 300.0]
    centers = []
    for x0, y0, x1, y1, raw_text, *_ in words:
        token = clean_token(raw_text)
        if not token:
            continue
        y_center = (y0 + y1) / 2
        if 95 <= y_center <= 220 and 35 <= x0 <= 280:
            if re.fullmatch(r"\d{1,2}", token) or raw_text.strip() in CIRCLED or token == "해설참조":
                centers.append(y_center)
    if not centers:
        return [], []

    centers.sort()
    row_centers: list[float] = []
    for center in centers:
        if not row_centers or abs(center - row_centers[-1]) > 8:
            row_centers.append(center)
        else:
            row_centers[-1] = (row_centers[-1] + center) / 2
    row_centers = row_centers[:5]
    if len(row_centers) < 5:
        first = row_centers[0]
        row_centers = [first + 18.75 * index for index in range(5)]

    answers: list[str] = []
    modes: list[str] = []
    for row_y in row_centers:
        for column_index in range(4):
            tokens = []
            for x0, y0, x1, y1, raw_text, *_ in words:
                y_center = (y0 + y1) / 2
                x_center = (x0 + x1) / 2
                if (
                    row_y - 10.5 <= y_center <= row_y + 10.5
                    and answer_starts[column_index] - 1.0 <= x_center <= column_ends[column_index] - 2.0
                ):
                    tokens.append((x0, y0, x1, y1, raw_text))
            answer = cell_answer(tokens)
            answers.append(answer)
            modes.append(raw_answer_mode(tokens, answer))
    return answers, modes


def evidence_score(evidence: tuple[list[str], list[str]]) -> tuple[int, int]:
    answers, _ = evidence
    head = answers[:EXPECTED_PROBLEMS]
    return sum(1 for answer in head if str(answer or "").strip()), min(len(answers), EXPECTED_PROBLEMS)


def extract_quick_answer_evidence(pdf_path: Path) -> tuple[list[str], list[str], str]:
    with fitz.open(str(pdf_path)) as document:
        if document.page_count < 1:
            raise ReconciliationError(f"empty PDF: {pdf_path}")
        header = " ".join(document[0].get_text("text").split())[:500]
        best: tuple[list[str], list[str]] = ([], [])
        best_score = (0, 0)
        for page_index in range(min(document.page_count, 8)):
            words = document[page_index].get_text("words")
            dynamic = extract_dynamic_evidence(words)
            fixed = extract_fixed_evidence(words)
            candidate = dynamic if evidence_score(dynamic) >= evidence_score(fixed) else fixed
            candidate_score = evidence_score(candidate)
            if candidate_score > best_score:
                best = candidate
                best_score = candidate_score
            if candidate_score == (EXPECTED_PROBLEMS, EXPECTED_PROBLEMS):
                break
    answers, modes = best

    if len(answers) != EXPECTED_PROBLEMS or any(not answer for answer in answers):
        raise ReconciliationError(f"expected 20 non-empty answers: {pdf_path}")
    for question_no, (answer, mode) in enumerate(zip(answers, modes), start=1):
        if mode == CHOICE_NUMBER and answer not in {"1", "2", "3", "4", "5"}:
            raise ReconciliationError(
                f"choice answer outside 1..5: {pdf_path} question {question_no}: {answer!r}"
            )
    return answers, modes, header


def normalize_level(value: object) -> str:
    match = re.search(r"lv\.?\s*([3-6])", str(value or ""), re.IGNORECASE)
    return f"Lv.{match.group(1)}" if match else str(value or "").strip()


def test_round(test: dict) -> str:
    return str(test.get("round") or "").strip()


def answer_key_for_test(test: dict) -> list[str]:
    round_no = test_round(test)
    answer_keys = test.get("answerKeys")
    if isinstance(answer_keys, dict) and isinstance(answer_keys.get(round_no), list):
        return [str(value) for value in answer_keys[round_no]]
    answer_key = test.get("answerKey")
    return [str(value) for value in answer_key] if isinstance(answer_key, list) else []


def answer_modes_for_test(test: dict) -> list[str]:
    round_no = test_round(test)
    answer_modes = test.get("answerModes")
    if isinstance(answer_modes, dict) and isinstance(answer_modes.get(round_no), list):
        return [str(value) for value in answer_modes[round_no]]
    return []


def load_override_index(path: Path | None) -> dict[tuple[str, str], Path]:
    if path is None:
        return {}
    rows = read_json(path)
    if not isinstance(rows, list):
        raise ReconciliationError("override manifest must be a JSON array")
    index: dict[tuple[str, str], Path] = {}
    for row_number, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise ReconciliationError(f"override row {row_number} must be an object")
        source_id = str(row.get("sourceId") or "").strip()
        round_no = str(row.get("round") or "").strip()
        pdf_path = Path(str(row.get("pdfPath") or "")).resolve(strict=False)
        if not source_id or round_no not in EXPECTED_ROUNDS or not pdf_path.is_file():
            raise ReconciliationError(f"invalid override row {row_number}: {row!r}")
        key = (source_id, round_no)
        if key in index:
            raise ReconciliationError(f"duplicate override: {source_id}/{round_no}")
        index[key] = pdf_path
    return index


def locate_cached_pdf(
    test: dict,
    legacy_cache: Path,
    recovery_cache: Path,
    new_cache: Path,
) -> Path:
    source_id = str(test.get("sourceId") or "").strip()
    round_no = test_round(test)
    exact_candidates = [
        legacy_cache / source_id / f"{round_no}.pdf",
        recovery_cache / source_id / f"{round_no}.pdf",
    ]
    if source_id.startswith("t_단원평가_"):
        suffix = source_id.removeprefix("t_단원평가_")
        exact_candidates.insert(0, legacy_cache / f"t___{suffix}" / f"{round_no}.pdf")
    existing = [path for path in exact_candidates if path.is_file()]
    if len(existing) == 1:
        return existing[0]
    if len(existing) > 1:
        raise ReconciliationError(f"multiple cached PDFs for {source_id}/{round_no}: {existing}")

    match = re.fullmatch(r"t_unit_(mijeok1|mijeok2|giha|hwaktong)_(\d+)_lv([3-6])", source_id)
    if not match:
        raise ReconciliationError(f"cached PDF not found for {source_id}/{round_no}")
    subject, order_text, level_no = match.groups()
    subject_root = new_cache / subject
    directory_pattern = f"Lv.{level_no}_{int(order_text):03d}_*"
    candidates = sorted(path / f"{round_no}.pdf" for path in subject_root.glob(directory_pattern))
    candidates = [path for path in candidates if path.is_file()]
    complete_parent_candidates = [
        path
        for path in candidates
        if all((path.parent / f"{candidate_round}.pdf").is_file() for candidate_round in EXPECTED_ROUNDS)
    ]
    if len(complete_parent_candidates) == 1:
        return complete_parent_candidates[0]
    if len(candidates) == 1:
        return candidates[0]
    raise ReconciliationError(f"cached PDF lookup is ambiguous for {source_id}/{round_no}: {candidates}")


def validate_catalog(config: dict) -> tuple[list[dict], dict[str, dict[str, dict]]]:
    tests = config.get("categories", {}).get("UNIT", {}).get("tests")
    if not isinstance(tests, list) or not all(isinstance(test, dict) for test in tests):
        raise ReconciliationError("categories.UNIT.tests must be an object array")
    ids: set[str] = set()
    by_source: dict[str, dict[str, dict]] = defaultdict(dict)
    for test in tests:
        test_id = str(test.get("id") or "").strip()
        source_id = str(test.get("sourceId") or "").strip()
        round_no = test_round(test)
        if not test_id or test_id in ids:
            raise ReconciliationError(f"missing or duplicate test id: {test_id!r}")
        ids.add(test_id)
        if not source_id or round_no not in EXPECTED_ROUNDS:
            raise ReconciliationError(f"invalid sourceId/round: {test_id}")
        if test_id != f"{source_id}_r{round_no}":
            raise ReconciliationError(f"testId/sourceId/round mismatch: {test_id}")
        if round_no in by_source[source_id]:
            raise ReconciliationError(f"duplicate source round: {source_id}/{round_no}")
        if int(test.get("problems") or 0) != EXPECTED_PROBLEMS:
            raise ReconciliationError(f"UNIT problems must be 20: {test_id}")
        answers = answer_key_for_test(test)
        modes = answer_modes_for_test(test)
        if len(answers) != EXPECTED_PROBLEMS or len(modes) != EXPECTED_PROBLEMS:
            raise ReconciliationError(f"answerKey/answerModes must each contain 20 entries: {test_id}")
        if any(mode not in VALID_MODES for mode in modes):
            raise ReconciliationError(f"invalid answer mode: {test_id}")
        by_source[source_id][round_no] = test
    for source_id, rounds in by_source.items():
        if set(rounds) != set(EXPECTED_ROUNDS):
            raise ReconciliationError(f"source must contain rounds 1,2,3: {source_id}")
    return tests, by_source


def anomaly_counts(tests: list[dict]) -> dict:
    choice_out_of_range = 0
    manual_review = 0
    choice_tests: set[str] = set()
    manual_tests: set[str] = set()
    for test in tests:
        test_id = str(test.get("id") or "")
        for answer, mode in zip(answer_key_for_test(test), answer_modes_for_test(test)):
            if mode == CHOICE_NUMBER and answer not in {"1", "2", "3", "4", "5"}:
                choice_out_of_range += 1
                choice_tests.add(test_id)
            if mode == MANUAL_REVIEW:
                manual_review += 1
                manual_tests.add(test_id)
    return {
        "choiceOutside1To5Questions": choice_out_of_range,
        "choiceOutside1To5Tests": len(choice_tests),
        "manualReviewQuestions": manual_review,
        "manualReviewTests": len(manual_tests),
    }


def reconcile(args: argparse.Namespace) -> dict:
    config = read_json(args.config)
    link_map = read_json(args.link_map)
    if not isinstance(config, dict) or not isinstance(link_map, dict):
        raise ReconciliationError("config and link map roots must be objects")
    tests, by_source = validate_catalog(config)
    remove_sources = set(args.remove_source_id)
    unknown_removals = sorted(remove_sources - set(by_source))
    if unknown_removals:
        raise ReconciliationError(f"remove-source-id not present in config: {unknown_removals}")

    expected_link_sources = set(by_source) - remove_sources
    link_sources_after_removal = set(link_map) - remove_sources
    if expected_link_sources != link_sources_after_removal:
        missing = sorted(expected_link_sources - link_sources_after_removal)
        extra = sorted(link_sources_after_removal - expected_link_sources)
        raise ReconciliationError(f"link-map/config source mismatch; missing={missing[:10]} extra={extra[:10]}")

    override_index = load_override_index(args.override_manifest)
    expected_override_keys = {
        (source_id, round_no)
        for source_id in set(source_id for source_id, _ in override_index)
        for round_no in EXPECTED_ROUNDS
    }
    if set(override_index) != expected_override_keys:
        raise ReconciliationError("every overridden source must provide exactly rounds 1,2,3")

    preview_config = copy.deepcopy(config)
    preview_tests = preview_config["categories"]["UNIT"]["tests"]
    preview_by_id = {str(test.get("id")): test for test in preview_tests}
    evidence: list[dict] = []
    answer_changed_questions = 0
    mode_changed_questions = 0
    answer_changed_tests: set[str] = set()
    mode_changed_tests: set[str] = set()
    changed_sources: set[str] = set()
    change_rows: list[dict[str, object]] = []
    file_owners: dict[str, tuple[str, str]] = {}
    extraction_methods = Counter()
    title_level_mismatches: list[dict[str, object]] = []

    for source_id in sorted(expected_link_sources):
        for round_no in EXPECTED_ROUNDS:
            test = by_source[source_id][round_no]
            test_id = str(test["id"])
            link = link_map.get(source_id, {}).get(round_no)
            if not isinstance(link, dict):
                raise ReconciliationError(f"missing link row: {source_id}/{round_no}")
            file_id = str(link.get("fileId") or "").strip()
            if not file_id or file_id not in str(link.get("answerUrl") or ""):
                raise ReconciliationError(f"invalid link/fileId: {source_id}/{round_no}")
            owner = file_owners.get(file_id)
            if owner and owner != (source_id, round_no):
                raise ReconciliationError(f"reused solution fileId {file_id}: {owner} and {(source_id, round_no)}")
            file_owners[file_id] = (source_id, round_no)

            override_path = override_index.get((source_id, round_no))
            pdf_path = override_path or locate_cached_pdf(
                test,
                args.legacy_cache,
                args.recovery_cache,
                args.new_cache,
            )
            method = "official_override" if override_path else "local_cache"
            answers, modes, header = extract_quick_answer_evidence(pdf_path)
            expected_level = normalize_level(test.get("difficulty"))
            header_levels = {
                f"Lv.{match}"
                for match in re.findall(r"lv\.?\s*([3-6])", header, flags=re.IGNORECASE)
            }
            if expected_level not in header_levels:
                title_level_mismatches.append(
                    {
                        "sourceId": source_id,
                        "testId": test_id,
                        "round": round_no,
                        "expectedLevel": expected_level,
                        "observedLevels": sorted(header_levels),
                        "pdfPath": str(pdf_path.resolve()),
                        "header": header[:160],
                    }
                )

            current_answers = answer_key_for_test(test)
            current_modes = answer_modes_for_test(test)
            answer_diff = sum(left != right for left, right in zip(current_answers, answers))
            mode_diff = sum(left != right for left, right in zip(current_modes, modes))
            if answer_diff:
                answer_changed_questions += answer_diff
                answer_changed_tests.add(test_id)
                changed_sources.add(source_id)
            if mode_diff:
                mode_changed_questions += mode_diff
                mode_changed_tests.add(test_id)
                changed_sources.add(source_id)
            if answer_diff or mode_diff:
                change_rows.append(
                    {
                        "sourceId": source_id,
                        "testId": test_id,
                        "round": round_no,
                        "fileId": file_id,
                        "answerChangedQuestionNumbers": [
                            index
                            for index, (current, official) in enumerate(
                                zip(current_answers, answers), start=1
                            )
                            if current != official
                        ],
                        "modeChangedQuestionNumbers": [
                            index
                            for index, (current, official) in enumerate(
                                zip(current_modes, modes), start=1
                            )
                            if current != official
                        ],
                        "beforeAnswers": current_answers,
                        "officialAnswers": answers,
                        "beforeModes": current_modes,
                        "officialModes": modes,
                    }
                )

            target = preview_by_id[test_id]
            target_answer_keys = dict(target.get("answerKeys")) if isinstance(target.get("answerKeys"), dict) else {}
            target_answer_keys[round_no] = answers.copy()
            target["answerKeys"] = target_answer_keys
            target["answerKey"] = answers.copy()
            target_answer_modes = dict(target.get("answerModes")) if isinstance(target.get("answerModes"), dict) else {}
            target_answer_modes[round_no] = modes.copy()
            target["answerModes"] = target_answer_modes

            extraction_methods[method] += 1
            evidence.append(
                {
                    "sourceId": source_id,
                    "testId": test_id,
                    "round": round_no,
                    "fileId": file_id,
                    "pdfPath": str(pdf_path.resolve()),
                    "pdfSize": pdf_path.stat().st_size,
                    "pdfSha256": sha256_file(pdf_path),
                    "answers": answers,
                    "modes": modes,
                    "method": method,
                    "header": header[:240],
                }
            )

    preview_config["categories"]["UNIT"]["tests"] = [
        test for test in preview_tests if str(test.get("sourceId") or "") not in remove_sources
    ]
    preview_link_map = {source_id: rounds for source_id, rounds in link_map.items() if source_id not in remove_sources}
    after_tests, after_by_source = validate_catalog(preview_config)

    before_other_fields = {
        str(test["id"]): {
            key: value
            for key, value in test.items()
            if key not in {"answerKey", "answerKeys", "answerModes"}
        }
        for test in tests
        if str(test.get("sourceId") or "") not in remove_sources
    }
    after_other_fields = {
        str(test["id"]): {
            key: value
            for key, value in test.items()
            if key not in {"answerKey", "answerKeys", "answerModes"}
        }
        for test in after_tests
    }
    if before_other_fields != after_other_fields:
        raise ReconciliationError("preview changed fields outside answerKey/answerKeys/answerModes")

    summary = {
        "inputConfigSha256": sha256_file(args.config),
        "inputLinkMapSha256": sha256_file(args.link_map),
        "before": {
            "unitTests": len(tests),
            "unitSources": len(by_source),
            "questions": len(tests) * EXPECTED_PROBLEMS,
            "anomalies": anomaly_counts(tests),
        },
        "after": {
            "unitTests": len(after_tests),
            "unitSources": len(after_by_source),
            "questions": len(after_tests) * EXPECTED_PROBLEMS,
            "linkedSources": len(preview_link_map),
            "linkedRounds": len(file_owners),
            "anomalies": anomaly_counts(after_tests),
        },
        "changes": {
            "removedSources": sorted(remove_sources),
            "removedTests": len(tests) - len(after_tests),
            "answerChangedQuestions": answer_changed_questions,
            "answerChangedTests": len(answer_changed_tests),
            "modeChangedQuestions": mode_changed_questions,
            "modeChangedTests": len(mode_changed_tests),
            "changedSources": len(changed_sources),
            "changedSourceIds": sorted(changed_sources),
        },
        "evidence": {
            "rows": len(evidence),
            "uniqueFileIds": len(file_owners),
            "methods": dict(sorted(extraction_methods.items())),
            "choiceQuestions": sum(row["modes"].count(CHOICE_NUMBER) for row in evidence),
            "answerValueQuestions": sum(row["modes"].count(ANSWER_VALUE) for row in evidence),
            "manualReviewQuestions": sum(row["modes"].count(MANUAL_REVIEW) for row in evidence),
            "titleLevelMismatches": len(title_level_mismatches),
            "titleLevelMismatchExamples": title_level_mismatches[:20],
        },
        "preservation": {
            "nonAnswerFieldsUnchanged": True,
            "validLinkRowsUnchanged": True,
        },
    }
    return {
        "config": preview_config,
        "linkMap": preview_link_map,
        "evidence": evidence,
        "changes": change_rows,
        "summary": summary,
    }


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Reconcile UNIT answers and independently observed answer modes from official solution PDFs."
    )
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--link-map", type=Path, required=True)
    parser.add_argument("--legacy-cache", type=Path, required=True)
    parser.add_argument("--recovery-cache", type=Path, required=True)
    parser.add_argument("--new-cache", type=Path, required=True)
    parser.add_argument("--override-manifest", type=Path, default=None)
    parser.add_argument("--remove-source-id", action="append", default=[])
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--backup-confirmed", action="store_true")
    parser.add_argument("--expected-config-sha256", default="")
    parser.add_argument("--expected-link-map-sha256", default="")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.config = args.config.resolve(strict=False)
    args.link_map = args.link_map.resolve(strict=False)
    args.legacy_cache = args.legacy_cache.resolve(strict=False)
    args.recovery_cache = args.recovery_cache.resolve(strict=False)
    args.new_cache = args.new_cache.resolve(strict=False)
    args.override_manifest = args.override_manifest.resolve(strict=False) if args.override_manifest else None
    args.output_dir = args.output_dir.resolve(strict=False)

    result = reconcile(args)
    write_json(args.output_dir / "tests-config.preview.json", result["config"])
    write_json(args.output_dir / "test_answer_link_map.preview.json", result["linkMap"])
    write_json(args.output_dir / "unit_solution_evidence.json", result["evidence"])
    write_json(args.output_dir / "unit_changes.json", result["changes"])
    write_json(args.output_dir / "reconciliation_report.json", result["summary"])
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    print(f"preview={args.output_dir}")

    if not args.apply:
        return 0
    if not args.backup_confirmed:
        parser.error("--apply requires --backup-confirmed")
    config_sha = sha256_file(args.config)
    link_sha = sha256_file(args.link_map)
    if not args.expected_config_sha256 or config_sha.casefold() != args.expected_config_sha256.casefold():
        raise ReconciliationError("config SHA-256 changed or was not supplied; rerun preview")
    if not args.expected_link_map_sha256 or link_sha.casefold() != args.expected_link_map_sha256.casefold():
        raise ReconciliationError("link-map SHA-256 changed or was not supplied; rerun preview")

    try:
        from core.storage import file_lock, save_atomic
    except ImportError as exc:
        raise ReconciliationError("live apply must run from the server repository") from exc
    with file_lock(args.config), file_lock(args.link_map):
        if sha256_file(args.config) != config_sha or sha256_file(args.link_map) != link_sha:
            raise ReconciliationError("live input changed while applying; rerun preview")
        save_atomic(args.config, result["config"])
        save_atomic(args.link_map, result["linkMap"])
    print("applied live config and link map")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
