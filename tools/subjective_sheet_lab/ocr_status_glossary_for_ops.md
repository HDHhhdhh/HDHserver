# OCR 상태 용어 운영자 가이드

목적: OCR QA 중 나오는 status/warning/provider 상태를 운영자가 같은 의미로 이해하게 한다.

## Review status

| status | 운영자 설명 | 학생 UI 처리 |
| --- | --- | --- |
| `safe_auto_grade` | 인식값이 명확하고 형식 검증을 통과함 | 자동 채움 가능 |
| `review_required` | 값은 있을 수 있으나 학생 확인이 필요함 | 확인 카드 표시 |
| `retake_required` | 사진/crop 품질이 낮아 재촬영이 필요함 | 답칸 채우기 차단 |
| `data_check_required` | crop/key/mapping 등 데이터 확인이 필요함 | 선생님 확인 |
| `missing` | 인식값 없음 | 확인 또는 재촬영 |

## Provider/cache 상태

| status | 의미 | 정상 여부 |
| --- | --- | --- |
| `not_called` | provider 호출 없이 cache 또는 stub으로 처리 | provider-free QA에서 정상 |
| `cache_status=hit` | cached review payload 사용 | 안정성 확인에 적합 |
| `cache_not_allowlisted` | 해당 cache source를 쓰지 않음 | live 미승인 시 정상 |
| `live_call_not_authorized` | live provider 승인이 없어 호출하지 않음 | 안전한 정상 동작 |
| `provider_error` | provider 호출 실패 | live QA 보고 필요 |

## Warning code

| warning | 운영자 설명 | 자동 확정 |
| --- | --- | --- |
| `crop_quality_blurry` | crop이 흐림 | 금지 |
| `crop_quality_cutoff_risk` | crop이 잘렸거나 경계 위험 | 금지 |
| `unclear_final_answer` | 최종 답이 명확하지 않음 | 금지 |
| `multiple_answer_candidates` | 답 후보가 여러 개 | 금지 |
| `answer_value_letter_confusion` | 답값이 글자처럼 보임 | 금지 |
| `arrow_equal_confusion` | 화살표/등호 혼동 | 금지 |
| `relation_symbol_confusion` | `<`, `<=`, `=`, `->` 등 관계기호 혼동 | 금지 |
| `expression_operator_confusion` | 식/연산자 혼동 | 금지 |
| `choice_number_invalid_for_auto_grade` | 객관식에 1~5 외 값 | 금지 |

## 자주 묻는 판단

- 객관식은 `1`, `2`, `3`, `4`, `5`만 자동 채움 가능.
- 객관식에 `x=2`, `3sqrt(2)`, `1,3`, `1/2,9/2`가 나오면 확인 필요.
- 주관식에 `n`, `x`, `?`가 나오면 확정칸을 비워 둔다.
- 주관식에 명확한 숫자나 분수만 있으면 확정칸에 미리 넣을 수 있다.
- recognized-only cache는 자동으로 `safe_auto_grade`로 승격하지 않는다.

## 운영 기준

자동 확정은 “맞을 것 같음”이 아니라 “형식과 품질 정책을 통과함”일 때만 허용한다. 애매한 인식은 학생 확인 또는 재촬영으로 보내는 것이 맞다.
