# CHANGELOG

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
