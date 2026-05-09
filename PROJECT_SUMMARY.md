# PROJECT SUMMARY (한 장 요약)

## 0) 현재 버전
- 버전: v0.2 (2025-09-20)
- 안정 스냅샷: SNAPSHOT_2025-09-20.md 참조

## 1) 폴더 구조(요약)
- /static/js/admin/... : 관리자 JS 기능 모듈
  - today.js : 오늘표(정렬, 결석/복구, 완료처리)
  - calendar.js : 월 캘린더 + 보강/결석 + 주말 타임 선택
  - clinicModal.js : 클리닉 지정(주말 타임 연동)
  - hoverTooltip.js : 학생 Hover 툴팁 (영상 진도 + 단원평가/파이널/헬 표시)
  - features/exportLogs.js : TXT 내보내기 (건너뜀 제외, 정렬 반영)
- /static/js/student.js : 학생 페이지 (영상 자동 배정, 테스트 제출 모달)
- /static/js/tests.js : 테스트 관리 페이지 (카테고리/시험 추가·편집·통계)
- /api/* : Flask 엔드포인트 (students, videos, logs, progress, extra-attend, weekend-slots, tests 등)

## 2) 핵심 엔드포인트
- GET/POST /api/students, /api/videos, /api/progress
- GET/POST /api/logs (tests 병합 안전 저장)
- GET/POST /api/extra-attend   (보강 명단)
- GET/POST /api/weekend-slots  (주말 타임 1/2/3, 배열 [1,2] 지원)
- GET /api/attend?date=YYYY-MM-DD  (특정 날짜 출석자)
- POST /api/submit-test (학생 테스트 성적 제출, logs + tests.json 동시 기록)
- GET/POST /api/tests-config (테스트 카테고리/시험/문항수 관리)

## 3) 프론트 핵심 기능
- 오늘표: 보강 자동 정렬, 당일 slot 수정 가능, 결석 복구 가능
- HoverTooltip: 영상 진도 + 단원평가/FINAL/HELL 응시 여부 색상 표시
- 내보내기: 오늘 변경 로그만 TXT로, 건너뜀 제외, 정렬 반영
- 자료 관리: 다중 파일 업로드 지원
- 테스트 관리(/tests): 카테고리·시험 추가/삭제, 문항수 수정, 통계 표시

## 4) 규칙
- 주말 타임: 토/일 → slot 1~3 (연강: 배열 [1,2] 허용)
- today_order, extra-attend, weekend-slots는 전부 문자열 sid 키
- 완료 표시: logs[date][sid].done === true
- 자유의 몸: archived === false 인 학생 전부 포함 (날짜 무관)
- 다크 모드: body.dark 클래스 토글, 흰색 UI 요소 제거 (전부 다크 톤 통일)
- 테스트 이름 정규화: 공백 제거 + lower-case → FINAL/HELL 매칭 보강

## 5) 열린 TODO
- [ ] tests.js 통계 갱신 성능 최적화 (logs.json 전수 스캔 최소화)
- [ ] tests-config UI 개선 (drag-sort, 검색 추가)
- [ ] HoverTooltip 성능 개선 (학생 수 많을 때 렉 최소화)
- [ ] exportLogs 포맷 사용자 커스터마이즈 옵션 제공
