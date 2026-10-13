# PROJECT SUMMARY

이 파일은 비정본 진입점이다. 규칙 본문과 실시간 운영 상태를 복사하지 않는다.

`C:/server`는 학생 명단, 출결, 오늘 순서, 수업·숙제 로그, 영상
배정·시청, 시험 배정·답지·과거 기록, 보강, 공지, 학교 일정과 자료
파일을 운영하는 Flask + 정적 JavaScript 학원 운영 허브다. 저장소 옆
JSON과 `app.sqlite`는 실제 운영 데이터다.

## 주요 화면

- `/`: 학생 로그인
- `/admin`, `/dh1130`: 날짜별 관리자 운영판
- `/students`: 전체 학생
- `/student/<sid>`: 학생 개인 페이지
- `/video-manage`, `/tests`, `/school-cal`, `/file-manage`: 운영 관리 화면
- `/demo/rh3123/*`: 합성 데이터 데모

## 현재 규칙을 읽는 순서

1. [Server Rules Index](docs/SERVER_RULES_INDEX.md)
2. [기능·로직 기준서](docs/PROJECT_FUNCTIONS_AND_LOGIC.md)
3. [코드·데이터 흐름 지도](docs/CODE_FLOW_MAP.md)
4. [로직 결정 원장](docs/LOGIC_DECISION_LEDGER.md)
5. 루트와 대상 폴더의 `AGENTS.md`

변경·복구·배포 전에는 위 문서가 가리키는 데이터 안전 및 검증 규칙을
따른다. 이 요약과 정본이 다르면 요약을 근거로 동작을 바꾸지 않는다.
