# OCR Student Writing Rule Guidance

This is lab documentation for future OCR review/integration. It is not wired into the operating student page.

## Core Rule

Write the answer in the same format that the answer key expects.

For mixed-format unit tests, some questions require a selected option number and others require the final answer value.

## Student-Facing Guidance

- 선택형 문항은 선지 번호만 작성합니다.
- 답값형 문항은 계산 결과만 작성합니다.
- 선택형 문항에 선지 내용, 수식, 풀이식을 쓰지 않습니다.
- 답값형 문항에는 최종 답만 씁니다.
- 칸 중앙에 크게 씁니다.
- 아래 선에 붙이지 않습니다.
- `0/6`, `x/n`, `<`와 `<=`를 명확히 씁니다.
- `>`와 `>=`를 명확히 씁니다.
- `ㄱ/ㄴ/ㄷ/ㄹ`은 숫자처럼 쓰지 않습니다.

## Examples

### choice_number

If the correct option is `③`, write:

```text
3
```

Do not write the option expression, option text, or solution process.

### answer_value

If the final answer value is `64`, write:

```text
64
```

Do not write intermediate work or a different equivalent-looking expression unless that exact expression is the expected answer format.

## t_unit_daesu_01_lv3_r1 Specific Note

For `지수1 Lv.3 1회차`, the verified answer modes are mixed.

Answer-mode table:

```text
tools/subjective_sheet_lab/t_unit_daesu_01_lv3_r1_answer_mode_table.md
tools/subjective_sheet_lab/t_unit_daesu_01_lv3_r1_answer_mode_table.json
```

Choice-number questions:

```text
1, 3, 5, 9, 13, 14, 17, 19
```

Answer-value questions:

```text
2, 4, 6, 7, 8, 10, 11, 12, 15, 16, 18, 20
```

For q013, q017, and q019, the original answer key expects only the selected option number. If a student writes the option expression instead, Vision may read the writing correctly, but current string-comparison grading will not match the answer key.

## Integration Guidance

- Enable OCR only for tests with documented answer modes.
- Keep the test allowlist guard active.
- Preserve OCR text as written by the student.
- Do not automatically convert mathematical expressions into option numbers.
- Do not automatically convert option numbers into expressions.
- If a `choice_number` item receives a mathematical expression, classify it as `answer_mode_mismatch`, `data_check_required`, or student wrong-format.
- If an `answer_value` item receives a derivation or multiple equivalent forms, require review unless the exact final answer value matches the answer key.
- Keep final submission through the existing `/api/submit-test` path only after student confirmation.

## OCR `answersText` Output Policy

- OCR-filled `answersText` must be one answer per line.
- A 20-question test must produce exactly 20 non-empty lines.
- Line 1 must correspond to q001, line 2 to q002, continuing through line 20 for q020.
- Do not use concatenated digit format for OCR output.
- Concatenated format is unsafe for multi-digit answers such as `12`, `64`, and `42`.
- Each line must contain one complete final answer, preserving multi-character values as one line.

## Current System Constraint

The current `/api/submit-test` grading path compares answer strings against `tests-config.json` answer strings. It does not know per-question answer mode, does not simplify expressions, and does not convert between option numbers and expression values.
