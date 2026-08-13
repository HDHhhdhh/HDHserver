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
  - features/exportLogs.js : TXT/CSV 내보내기 (건너뜀 제외, 정렬·항목 선택 반영)
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
- 내보내기: 완료·미정리 로그를 TXT/CSV로, 건너뜀 제외, 정렬 및 TXT 항목 선택 반영
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
- [x] tests.js 통계 갱신 성능 최적화 (Phase 8: 변경 없는 logs.json 레거시 시험 후보 재파싱·전수 정규화 제거)
- [x] tests-config UI 개선 (Phase 9: 목록 검색, 그룹 내 drag/키보드 순서 저장, 메타데이터 보존·실패 rollback)
- [x] HoverTooltip 성능 개선 (Phase 10: 학생 O(1) 조회, 동일 행 재렌더 억제, pointer 위치 계산 프레임 병합)
- [x] HoverTooltip 반응형·키보드 접근성 (Phase 11: 모바일 내부 폭 제한, focus/blur/Escape, ARIA 설명 연결, 전체학생 초기화)
- [x] exportLogs 포맷 사용자 커스터마이즈 (Phase 12: TXT/CSV 선택, TXT 항목 선택, CSV 고정 스키마·수식 중화)
- [x] 학생 PWA 설치 안내 진입 UX (Phase 13: 초기 닫힘, 명시적 버튼 열기, 설치 완료·Escape·포커스 정리)
- [x] 학생 앱 배포 계약 자동검증 (Phase 14: Todo 14 temp fixture를 기본 suite+Windows CI에 편입, snapshot 완전성·격리 mutex·실패 경로 process/runtime 불변)
