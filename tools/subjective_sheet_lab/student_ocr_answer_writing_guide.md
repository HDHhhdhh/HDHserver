# Student OCR Answer Writing Guide Draft

Date: 2026-06-30 KST

Scope: student-facing wording draft for OCR answer-sheet review. This is a documentation draft only. It does not change the student page, scoring, OCR route, provider behavior, or production default.

## Short Student Notice

OCR은 답안을 대신 제출하는 기능이 아닙니다. 사진에서 읽은 답을 확인 화면에서 다시 보고, 틀리거나 애매한 부분은 학생이 직접 고쳐야 합니다.

객관식은 선지 번호만, 주관식/답값형은 최종 답만 써 주세요. 풀이식, 중간식, 선지 내용, 여러 답을 한 칸에 같이 쓰는 방식은 인식 후 확인이 필요할 수 있습니다.

## Core Writing Rules

- 한 칸에는 한 문제의 답 하나만 씁니다.
- 객관식/선택형 문항은 선택한 선지 번호만 씁니다.
- 주관식/답값형 문항은 최종 답만 씁니다.
- 계산 과정, 풀이식, 중간식은 답안 칸에 쓰지 않습니다.
- 여러 자리 수는 한 답으로 붙여 씁니다.
- 답을 고친 경우에는 이전 답을 깨끗하게 지우고 다시 씁니다.
- 답 위에 덧쓰거나, 취소선만 긋고 옆에 새 답을 쓰지 않습니다.

## Good Examples

객관식/선택형:

```text
3
```

답값형:

```text
12
64
42
30
16
```

한 문제의 답은 한 줄 또는 한 칸에 완성된 형태로 씁니다. `12`는 `1`과 `2`가 아니라 하나의 답입니다.

## Bad Examples

다음처럼 쓰면 확인 화면에서 수정이 필요할 수 있습니다.

```text
x=2
1,3
풀이: ...
3번 선지의 식
12 64
```

선택형 문항에는 식이나 선지 내용을 쓰지 말고 번호만 씁니다. 답값형 문항에는 최종 답만 씁니다.

## Multi-Digit And Line Rules

- 여러 자리 답은 숫자를 나누지 않습니다.
- 여러 답을 한 줄에 이어 붙이지 않습니다.
- 사진 인식 결과를 답칸에 옮길 때는 문제 순서대로 한 문제에 한 답이 들어가야 합니다.
- 답이 비어 있거나 애매하면 자동으로 확정하지 말고 확인 화면에서 고칩니다.

## Erased Or Overwritten Answers

지우거나 고친 흔적이 있으면 OCR이 답을 확신하기 어렵습니다.

- 틀린 답은 완전히 지우고 새 답을 씁니다.
- 기존 답 위에 새 답을 덧쓰지 않습니다.
- 취소선만 긋고 같은 칸에 다른 답을 쓰지 않습니다.
- 답이 겹쳐 보이면 확인 화면에서 직접 고르거나 다시 촬영해야 할 수 있습니다.

## Handwriting Tips

- 칸 중앙에 크게 씁니다.
- 아래 선이나 칸 테두리에 붙여 쓰지 않습니다.
- `0`과 `6`을 구분해서 씁니다.
- `x`와 `n`을 구분해서 씁니다.
- 부등호와 등호를 분명하게 씁니다.
- 보기 기호나 한글 자모는 숫자처럼 보이지 않게 씁니다.

## Review Screen Guidance

- 인식 결과를 그대로 믿지 말고 한 문제씩 확인합니다.
- 애매한 문항은 직접 수정합니다.
- 비어 있는 문항은 반드시 채웁니다.
- 선택형 문항에 번호가 아닌 값이나 식이 들어가면 답칸 채우기가 막힐 수 있습니다.
- 모든 답을 확인한 뒤에만 기존 제출 절차를 진행합니다.

## Instructor Note

이 안내문은 학생에게 보여줄 수 있는 문구 초안입니다. 내부 경로, 내부 설정값, 정답 관련 내부값, provider 세부 정보는 학생용 안내에 넣지 않습니다.

## Confirmation For This Draft

- no code changes
- no Gemini/API call
- no final submit call
- no submit button click
- no environment changes
- no production default changes
- no operating data/config changes
- no internal answer-value disclosure
- no filesystem path disclosure
