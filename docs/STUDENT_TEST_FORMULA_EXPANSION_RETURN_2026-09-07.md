# 무료 주관식 수식 OCR 확대 실험 수신 검토 · 2026-09-07

## 결론

**evidence·보고서·예측 JSONL 검증은 통과했다. checkpoint 바이너리 검증은 전송 차단으로 미완료다.** 마지막 part048만 수신·해시 검증했고 48조각 재조립과 네 후보 `.pth` 검사는 실행하지 않았다. 운영 모델 채택·복사·기능 활성화는 없다.

두 과목군 모두 사전 expanded 추천 조건을 통과하지 못했다. 공통은 전체 점수가 올랐지만 특정 작성자 집단이 하락했고, 상위는 전체 점수도 하락했다. 그러므로 **expanded 자동 선택 없음**이라는 송신 측 결론은 실제 재계산과 일치한다. 이번 focused_control의 개발 점수가 이전 focused1000보다 높은 것은 확인되지만, 이전 실험과의 pool·예산·seed 차이를 데이터 확대의 단독 효과로 해석하지 않는다.

- [수신 감사 JSON](<C:/Users/주인님/Documents/OCR_returns/formula_expansion_20260907_review_01/REVIEW_AUDIT_20260907.json>)
- [프로젝트 추적 manifest](STUDENT_TEST_FORMULA_EXPANSION_RETURN_2026-09-07.manifest.json)
- [받은 비교 원본](<C:/Users/주인님/Documents/OCR_returns/formula_expansion_20260907_review_01/evidence/COMPARISON.md>)
- [사전 실행·추천 조건](STUDENT_TEST_FORMULA_EXPANSION_GPU_INSTRUCTIONS.md)

## 실제 확인한 점수

숫자 동치는 수치값의 동등성(`numericCorrect`), 문자 일치는 정규화된 문자열 일치(`textExact`)다. 각 분모를 고정했고 오류 표본을 빼거나 정답 전사를 고치지 않았다.

| profile / 후보 | 숫자 동치 | 숫자 정확도 | 문자 일치 | 숫자 실패 |
|---|---:|---:|---:|---:|
| m3_h1 / base | 1166/1459 | 79.92% | 1130/1459 | 293 |
| m3_h1 / focused_control | 1382/1459 | 94.72% | 1362/1459 | 77 |
| m3_h1 / expanded_curriculum | 1395/1459 | 95.61% | 1376/1459 | 64 |
| m3_h1 / historical_focused1000 | 1354/1459 | 92.80% | 1331/1459 | 105 |
| m3_h1_h2_h3 / base | 1166/1473 | 79.16% | 1130/1473 | 307 |
| m3_h1_h2_h3 / focused_control | 1402/1473 | 95.18% | 1381/1473 | 71 |
| m3_h1_h2_h3 / expanded_curriculum | 1397/1473 | 94.84% | 1376/1473 | 76 |
| m3_h1_h2_h3 / historical_focused1000 | 1355/1473 | 91.99% | 1327/1473 | 118 |

8개 평가 모두 기록상 생성 실패 0이다. 미종료·공백 출력·64-token cap 도달이 각각 0이며 기록된 최대 tokenCount는 평가별 24~40이다. cap에 EOS가 있어도 실패라는 기존 계약을 유지했다. token ID는 JSONL에 없으므로 **각 행의 EOS 토큰을 독립적으로 재관측한 것은 아니다**. 원본 COMPARISON의 EOS 설명은 코드 계약/해시 확인으로만 해석하며 행별 EOS 입증으로 옮기지 않았다.

### 확대 후보 미채택 근거

- 공통: 전체 숫자 +13, 문자 +14. 그러나 `M_G3:abbe74fbd905a7abeb23`의 숫자·문자 일치가 각각 **61/63 → 59/63**으로 2개 감소했다.
- 상위: 전체 숫자·문자 각각 5개 감소. 중3 숫자 **1279 → 1274**, 문자 **1263 → 1258**. `M_G3:b9e873d758cd6eefdaac`의 숫자 **1220 → 1215**, 문자 **1204 → 1199**로 각각 감소했다.
- 사전 규칙은 전체 숫자의 엄격 증가와 전체 문자·모든 학년/작성자 숫자·문자 비감소, 생성 실패 비증가를 모두 요구한다. 결과를 본 뒤 조건을 완화하지 않았다. 이는 확대가 모든 경우에 무가치하다는 결론이 아니라, **이번 조건에서 채택 기준을 충족하지 못했다**는 결론이다.

## 수신·검증 범위

수신 루트: `C:/Users/주인님/Documents/OCR_returns/formula_expansion_20260907_review_01/`.

- evidence ZIP 7,815,422 bytes, SHA-256 `1e100ca90ec7fb49e2b31d8c7e08cab1d7dca780546eafb7ba914f5ff07750cf` 일치 후 안전 추출했다. ZIP 안에는 추가 RETURN 상위 폴더가 없다.
- receipt 목록 292개 파일의 경로·bytes·SHA 모두 일치. receipt 자체를 포함한 실제 일반 파일은 293개이며 누락·추가·중복·위험 경로·reparse가 없다. 독립 다운로드 RETURN_RECEIPT와 ZIP 내부 receipt도 같은 바이트다.
- 외부 evidence/RETURN/ARCHIVE/CHECKPOINT/BUILD/QA/SUMMARY/ZIP receipt/UPLOAD 원본의 크기·SHA를 전달 표와 대조했다. 원본과 수신 사본을 모두 보존했다.
- helper의 별도 `.py` 다운로드는 Chrome에서 차단됐다. 대신 이미 보유한 동일 9,209-byte/SHA helper의 전체 내용을 검토해 최초 추출에 사용했고, 검증된 evidence의 `transport/student_test_gpu_archive_80MiB.py`에서도 같은 바이트를 확인해 수신 폴더에 보존했다. helper를 수정하거나 보안 설정을 변경하지 않았다.
- 반환 `source_code` 18개와 데이터/모델 메타 24개가 원래 r3 snapshot과 일치. PACKET_MANIFEST도 원본과 바이트 동일하다. 이 manifest를 반환 inventory로 오해하지 않았다.
- 8개 predictions.jsonl, 총 11,728행의 index·학년·작성자·고정 분모·prediction/model/dataset/code 해시·report 및 그룹 집계가 일치한다. 별도 읽기 전용 에이전트가 검증된 순수 채점 규칙과 고정 전사로 기존 출력을 다시 채점했으며 numeric/text boolean 불일치 0이다. **모델 추론을 재실행한 검사가 아니다.**

## 학습·평가 수행 증거

| 구분 | 성공 | 실패 | 차단 | 미실행 |
|---|---:|---:|---:|---:|
| GPU 학습 stage | 8 | 0 | 0 | 0 |
| 필수 평가 | 6 | 0 | 0 | 0 |
| 선택 과거 후보 평가 | 2 | 0 | 0 | 0 |

이는 반환된 receipt·config·stdout/stderr·관찰 로그의 일관성 검증 결과이며 수신 컴퓨터에서 새로 수행한 학습/평가 건수가 아니다. 전송 중간 시도나 이번 다운로드 차단을 학습 실패로 합산하지 않았다.

공통 A2,000/B1,000, 상위 A3,000/B1,000 microbatch가 전략별로 맞는다. 8개 YAML과 config manifest 해시, generate/preflight/training exit0 및 로그 해시, 실제 저장 문구를 확인했다. 모든 A의 입력은 동일 원래 base SHA다. 각 B의 입력 경로·SHA는 해당 A의 마지막 `checkpoint_latest.pth`와 일치하고 A best가 아니다. B의 `resume_ckpt_path:null`, 동일 seed20260907·batch4·accum2 및 reset 계약을 확인했다.

최종 관찰 audit는 총 14,000 microbatch/56,000 forward 이미지 노출과 데이터 로더 재귀 대체 0을 기록한다. 성공 forward가 실제 optimizer update와 동일하다고 주장하지 않는다. 총 학습 command 시간은 약 2,895초(48.3분)로 기록돼 있다. 수신 컴퓨터는 GPU 실행을 직접 관측하지 않았으며 이 수치들은 해시가 묶인 저장 증거다.

네 B best는 로그·receipt상 모두 B-local 1,000이다. 공통 누적 3,000/상위 누적 4,000과 구분한다. **실제 `.pth`를 아직 받지 못했으므로 optimizer/scaler 포함 여부와 iters를 로컬에서 다시 읽은 것은 아니다.**

## checkpoint 수신 차단과 남은 작업

- 최종 parts 폴더의 48개 파일 각각의 Drive ID·이름·MIME·크기·부모를 확인했다. 전체 크기 3,984,481,528 bytes와 일치한다.
- 최종 ARCHIVE_PARTS.json 9,484 bytes 및 SHA `df6aa03c6e430a04d8213611d97fd01e9759b0408a7b7650b46bc6f0cebd0a47` 일치.
- `part048` 41,835,768 bytes 및 SHA `837dbbea68e09f6bda3ee16acba42f8251a987cf422e0542d60e2bf38f84dd35` 일치. 수신 폴더 `checkpoint_parts/`에 보존했다.
- `part001`은 Google의 용량 초과 바이러스 검사 불가 확인 뒤 Chrome `ERR_BLOCKED_BY_CLIENT`로 차단됐다. `part002~047`은 같은 80 MiB 전송 경로 문제로 추가 반복 요청하지 않았으며 **미수신/미검증**이다. 각 파일의 차단을 직접 관측했다고 쓰지 않는다.
- Drive 연결 도구의 원본 fetch는 로컬 경로가 아닌 sediment 파일 참조만 반환했고 현재 도구에 로컬 저장 기능이 없었다. Chrome 내부 다운로드 페이지도 도구 URL 정책으로 접근 불가였으며 우회하지 않았다.
- 재조립 ZIP·checkpoint 추출 폴더는 생성하지 않았다. 네 checkpoint 파일 검증 **0/4**, CPU metadata 재검사 **미실시**다. 기대 SHA는 별도 받은 CHECKPOINT_RECEIPT에만 등록된 값이다.

### 사용자 열린 Chrome 탭 재시도 · 16:31 KST

사용자가 열어둔 최종 parts 폴더에서 `part001`을 선택하고 폴더의 다운로드 버튼 및 Google의 크기 초과 안내에 있는 다운로드 버튼으로 다시 시도했다. Drive는 **“파일을 다운로드할 수 없습니다.”**, 전송 iframe은 **“Chrome에서 차단한 페이지입니다.”**라고 표시했다. 이번 재시도 화면에 오류 코드 자체는 노출되지 않았으므로 앞선 `ERR_BLOCKED_BY_CLIENT` 관측과 별도로 기록한다. 보안 설정 변경·차단 우회·다른 전송 경로 재시도는 하지 않았고 사용자의 Drive 탭은 그대로 유지했다. 새 part 수신이나 checkpoint 검증 완료로 처리하지 않았다.

남은 `part001~047`을 [최종 parts 폴더](https://drive.google.com/drive/folders/1IYld40Z6PN4lEskfQcPfTNBaZuW7pGg6)에서 사용자가 정상적으로 받을 수 있는 환경으로 다운로드하여 아래 폴더에 원래 이름으로 넣으면 재조립·네 후보 검증을 이어갈 수 있다. 이미 받은 manifest/part048은 덮어쓰지 않는다.

`C:/Users/주인님/Documents/OCR_returns/formula_expansion_20260907_review_01/checkpoint_parts/`

## 한계와 변경 경계

공통 1,459 crop/3 writer hash, 상위 1,473 crop/6 writer hash인 재사용 공개 개발 validation이다. 상위 고2는 14 crop이고 고3는 0이다. `mandela` 검토에서 공개 라벨 계열 공유와 반복된 후보 선택의 한계를 유지했다. 독립 미사용 작성자/실카메라/학생 calibration/고3 정확도/운영 GO로 승격하지 않는다. 동일인의 학년 간 관계·near-duplicate 독립성·원천 라벨 정확성을 보증하지 않는다.

새 학습·새 모델 평가·패키지 설치·외부 OCR/API·운영 복사·기능 활성화·서비스 중지/재시작을 하지 않았다. `providerCallCount:0`, `deploymentReady:false`. 기존 코드·데이터·모델·운영 DB·과거 문서를 삭제하거나 덮어쓰지 않았다. 이번 변경은 신규 수신 사본·검증 로그·검토 문서뿐이며 Git staging/commit은 하지 않았다.
