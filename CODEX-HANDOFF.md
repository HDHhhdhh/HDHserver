# 운영 서버 코드 후보

이 변경 묶음은 검증된 `retry2` 서버 export를 기준본과 대조해, 운영에 남길 변경만 선택 병합한 코드 전용 후보입니다. 런타임 데이터는 변경하지 않았습니다.

- 포함: 관리자 Basic 인증 게이트, 조교 학생 메모, 학생 운영 로그 복원·개별 삭제, 시험 카탈로그 표시명, 영상 ID 생성, 일반 접근성·터치 보완, 알 수 없는 숙제 행 메타데이터 보존.
- 제외: 학생 앱/PWA 구현, 참조 없는 `material_state`, 기존 복습·트레이닝팩·시청 동기화를 후퇴시키는 서버 export 변경.
- 런타임 JSON/SQLite/업로드 파일: 포함하지 않음.
- SQL migration과 `migrate_today_order_store.py --apply`: 실행하지 않음.
- 관리자 페이지군은 학원 외부 네트워크에서도 Basic 인증 후 접속할 수 있습니다. `ACADEMY_ADMIN_USERNAME` 및 `ACADEMY_ADMIN_PASSWORD_HASH` Machine 환경 변수가 없으면 401로 닫히며, 학생 영상·답지의 학원 Wi-Fi 제한은 유지됩니다.

배포 전 `python scripts/backup_runtime_data.py`로 별도 백업하고, 프록시/직접 접속 구조와 위 환경 변수를 확인해야 합니다. 삭제 대상 학생 앱/PWA 경로는 `CODEX-REMOVALS.txt`에 기록되어 있으며, 디렉터리 단위 재귀 삭제용 목록이 아닙니다.

선택 변경과 제외 정책은 이 문서와 `CODEX-REMOVALS.txt`에, 실행 가능한 회귀 검증은 `scripts/verify_*.py` 및 `scripts/verify_*.mjs`에 기록되어 있습니다.
