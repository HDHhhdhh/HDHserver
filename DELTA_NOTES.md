# CHANGELOG

## 2026-08-23
### Removed
- 학생 시험 제출 버튼·모달·클라이언트 채점/OCR 캡처
- `/student-test/<sid>`, `/api/submit-test`, `/api/ocr-test-sheet`, `/api/ocr-test-sheet-review`
- `/api/tests` 쓰기와 제출 전용 로그/진도 연결
- 데이터 0건·코드 참조 0건인 구형 `vacation.db`를 검증 백업 후 제거하고 루트 `*.db` 무시 규칙 해제

### Preserved
- 시험 배정, 답지 링크, 카탈로그 관리, 통계, 기존 시험 기록 조회
- 별도 비학생 OCR 연구/캐시 경계(학생 제출과 연결하지 않음)

### Protected
- 영상 관리 일반 모드에서 기존 영상 MID 변경·삭제를 409로 차단
- 화면에서 위험 변경을 전송 전에 감지하고 마지막 저장 상태로 복구
- 같은 MID의 서명 URL·메타데이터 수정과 새 영상 추가는 유지

### Added
- 영상 관리 수정 모드: 마지막 저장본에서 별도 JSON 수정안 생성, 자동/수동 서버 저장 차단, 취소 복원
- 오프라인 적용기: dry-run, 참조 삭제 거부, Waitress 정지, 런타임 백업 hash 확인, 4-store MID 변환, readback·롤백, 자동 재시작
- `verify_video_catalog_correction.py`를 기본 safety suite에 연결
- 오늘 순서 저장소를 `data/today_order.json`으로 단일화하고, 빈 구형 루트 파일을 백업 후 제거; 충돌 거부·archive 회귀 검사 추가
- 구형 `test_answer_link_map.js`와 주소 허용을 제거하고, 그 파일에만 있던 현행 무리함수2 해설 3개를 canonical JSON으로 이관

## 2025-09-10
### Added
- 학생 페이지: 테스트 성적 제출 모달(/api/submit-test 연동)
- 캘린더: 주말(토/일) 타임 선택(1/2/3) + 연강 [1,2] 지원
### Changed
- 오늘표: ‘보강’ 라벨 제거, 주말은 '토1/토2/토3' 표기
### Fixed
- 내보내기에서 tests 병합 시 undefined 예외 처리

### Migration
- 없음

### Risks
- weekend-slots 스키마: { date: { sid: number | number[] } }
# CHANGELOG

## 2025-09-20
### Added
- /tests 페이지 신설: 카테고리·시험 관리, 문항수 수정, 응시 통계 확인
- HoverTooltip: 파이널/헬 응시 여부 색상 표시
- 결석 복구 기능 추가 (잘못 누른 경우 복구 가능)
- 자료 업로드: 다중 파일 선택 가능

### Changed
- FINAL 3회 → 문항수 24로 조정
- 내보내기: 건너뜀(skip) 항목 제외, 차시 정렬 후 출력
- HoverTooltip UI 개선 (단원평가/FINAL/HELL 모두 표시, 정규화 매칭)

### Fixed
- 오늘표: 저장 후 자동 재정렬 정상 동작
- 자유의 몸: archived=false 학생 전체 표시 (날짜 무관)
- 테스트 입력칸 스타일 → 문항수 input과 동일하게 통일

### Migration
- tests.json 별도 관리 (카테고리·시험·문항수 설정)

### Risks
- logs.json 전체 스캔 기반 통계 → 학생·로그 수가 많아지면 성능 저하 가능
