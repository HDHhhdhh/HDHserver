from __future__ import annotations

import datetime as dt
import re
from collections import Counter
from pathlib import Path
from typing import Any

from core.paths import (
    ABS_PATH,
    ANNS_PATH,
    ARRIVE_TIME_PATH,
    ATTENDANCE_PATH,
    BASE,
    CAL_PATH,
    CONTACT_PATH,
    EXTRA_PATH,
    LOGS_PATH,
    PRG_PATH,
    STU_PATH,
    TESTS_CFG_PATH,
    TESTS_PATH,
    TODAY_ORDER_PATH,
    UPD_PATH,
    VID_PATH,
    WATCH_PATH,
    WEEKEND_SLOTS_PATH,
)
from core.storage import load

KST = dt.timezone(dt.timedelta(hours=9))
DATE_RE = re.compile(r"\b20\d{2}-\d{2}-\d{2}\b")
TOKEN_RE = re.compile(r"[0-9A-Za-z가-힣:_-]+")

MAX_QUERY_LEN = 600

STOPWORDS = {
    "검색",
    "관리",
    "관리자",
    "기능",
    "내용",
    "누구",
    "데이터",
    "목록",
    "상태",
    "알려줘",
    "어떻게",
    "오늘",
    "운영",
    "운영판",
    "정보",
    "챗봇",
    "학생",
    "확인",
}

FEATURE_TOPICS: list[dict[str, Any]] = [
    {
        "title": "관리자 운영판",
        "keywords": ["관리자", "운영판", "admin", "오늘 학생", "하원", "캘린더", "simple"],
        "answer": (
            "관리자 운영판은 /admin에서 오늘 학생, 출결, 하원 완료, 보강/결석, "
            "학교 일정, 공지/설문, 로그/숙제/영상/테스트 흐름을 한 화면에서 처리합니다. "
            "운영 날짜는 관리자 선택 날짜를 기준으로 동작해야 합니다. "
            "관리자 row action은 row의 tr.dataset.date(data-date)를 먼저 쓰고, 없을 때만 getAdminDate()를 fallback으로 씁니다. "
            "운영판 캘린더의 기본 보기는 오늘이 포함된 주를 가운데 줄로 둡니다."
        ),
        "sources": ["static/admin.html", "static/js/admin/main.js", "static/js/admin/core/adminDate.js", "static/js/admin/features/calendar.js"],
    },
    {
        "title": "학생 명단",
        "keywords": ["학생", "명단", "전체학생", "students", "school", "grade", "curriculum", "교재", "등원"],
        "answer": (
            "학생 정보는 students.json을 기준으로 이름, sid, 학교, 학년, 과정, 레벨, "
            "교재, 등원 요일/시간, 학습문서 링크 등을 관리합니다. 전체학생 화면은 /students입니다."
        ),
        "sources": ["students.json", "static/all.html", "static/js/all/main.js"],
    },
    {
        "title": "출결과 오늘 학생",
        "keywords": ["출결", "등원", "출석", "오늘", "하원", "완료", "attendance", "done", "arrive"],
        "answer": (
            "오늘 학생 목록은 선택 날짜 기준 수업 학생, 보강, 결석 정보를 합쳐 렌더링합니다. "
            "출석/연락/도착 시간은 날짜와 학생 sid별 JSON에 저장되고, 완료 상태는 수업 로그의 done 값과 연결됩니다."
        ),
        "sources": ["routes/api_attend.py", "routes/api_arrive_time.py", "static/js/admin/features/today.js"],
    },
    {
        "title": "보강과 결석",
        "keywords": ["보강", "보강잡기", "결석 추가", "보강 명단", "내보내기", "결석", "복구", "연강", "선보강", "extra", "absent", "weekend", "carryover"],
        "answer": (
            "보강 잡기 명단은 미해결 결석/직접 추가한 결석 수요를 계속 유지하며, 결석일보다 앞선 날짜에도 보강을 잡을 수 있습니다. "
            "결석 추가는 보강 서비스 추가와 구분되는 기능으로, 학생 이름과 과목을 먼저 고른 뒤 기존 관리자 운영판 캘린더에서 여러 결석 날짜를 선택해 날짜 단위 결석분을 명단에 직접 추가합니다. "
            "결석 복구는 관리자 운영판 상단에서 선택한 날짜를 기준으로 해당 날짜의 결석 학생을 불러옵니다. "
            "같은 날짜 정규수업과 보강/결석이 이어지면 연강으로 표시하고, 연강 결석은 타임별로 분리 처리할 수 있습니다."
        ),
        "sources": ["routes/api_attend.py", "routes/api_makeup_carryover.py", "static/js/admin/features/calendar.js", "static/js/admin/features/makeupPending.js", "static/js/admin/features/absentRecovery.js"],
    },
    {
        "title": "수업 로그와 숙제",
        "keywords": ["로그", "수업기록", "숙제", "homework", "homeworkTable", "notes", "완료"],
        "answer": (
            "수업 로그는 날짜와 학생 sid별로 notes, homeworkTable, 완료 상태, 숙제 확인/배정 상태를 보관합니다. "
            "학생 bootstrap은 오늘 로그의 homeworkTable 교재명을 homeworkBooks top-level 배열로 내려 학생 개인페이지에서 영상 목록 위에 보여줍니다. "
            "로그 저장은 기존 값을 안전하게 병합해야 하며 빈 값이 의미 있는 기존 데이터를 지우면 안 됩니다. "
            "SQLite 저장은 성공했지만 legacy logs.json 동기화가 실패하면 저장 응답에 json:false warning이 붙을 수 있으며, 이는 저장소 동기화 문제로 봐야 합니다."
        ),
        "sources": ["routes/api_basic.py", "core/log_repository.py", "core/log_rules.py", "static/js/admin/features/logModal.js", "static/js/student.js"],
    },
    {
        "title": "영상 배정과 진도",
        "keywords": ["영상", "진도", "progress", "updates", "watch", "자동배정", "수동"],
        "answer": (
            "영상 목록은 videos.json, 날짜별 배정은 updates.json, 시청/진도 상태는 progress.json과 watch.json에 있습니다. "
            "학생 개인페이지는 학원 밖에서도 목록을 보여주지만, /api/get-url 영상 재생과 테스트 답지 링크는 학원 Wi-Fi 네트워크에서만 허용합니다. "
            "자동 시청 진도는 수동 white/skip 설정을 덮어쓰지 않아야 합니다. "
            "관리자 오늘 목록과 명단 내보내기는 필요한 학생의 progress 이력만 묶음으로 조회해 전체 progress.json 다운로드를 피합니다. "
            "정규 커리큘럼 영상이 모두 초록(done) 또는 빨강(skip)이면 진도 완료로 보며, 학생 개인페이지에는 완료 안내를 보여주고 자동 영상 배정은 멈춥니다."
        ),
        "sources": ["app.py", "core/network_access.py", "routes/api_basic.py", "routes/api_kollus.py", "routes/api_watch.py", "static/js/admin/features/videoModal.js", "static/js/student.js"],
    },
    {
        "title": "Video assignment date safety",
        "keywords": ["video assignment", "row date", "data-date", "watch sync", "watch-status", "progress"],
        "answer": (
            "Admin video assignment saves use the row data-date captured when the modal opens, not the live admin date after that. "
            "Student watch sync posts to /api/watch, which stores watch state and automatic progress together; /api/watch-status is kept for explicit status updates. "
            "Automatic watch/progress transitions are centralized in core/progress_rules.py so manual white/skip progress stays authoritative."
        ),
        "sources": ["core/progress_rules.py", "static/js/admin/features/videoModal.js", "static/js/student.js", "routes/api_watch.py"],
    },
    {
        "title": "테스트 관리",
        "keywords": ["테스트", "성적", "채점", "assignedTests", "tests", "시험", "오답", "OCR", "ocr", "답안지"],
        "answer": (
            "테스트 카탈로그는 tests-config.json, 제출 성적은 tests.json에 저장됩니다. "
            "학생 bootstrap에서는 progress[date][sid].tests 상태가 authoritative이고, 로그의 assignedTests는 메타데이터/폴백입니다. "
            "학생 화면의 오늘 테스트는 assigned(배정)와 interrupted(배부) 상태를 날짜/신규 여부와 무관하게 보여주며, 명단 내보내기는 assigned(배정) 상태를 계속 출력합니다. "
            "하원/숙검하원/기록 정리는 결석 학생을 제외하고 assigned 테스트를 done으로 바꾸며, 결석 처리는 assigned 테스트를 interrupted(배부)로 바꿉니다. "
            "테스트 배정 팝업은 좌클릭/드래그로 없음→배정→배부→완료를 순환하고, 우클릭/드래그로 없음↔제외를 토글합니다. "
            "상담 기록 자동 블록은 당일 배부/완료 테스트를 한 줄씩 남기며, 완료는 오늘 assigned(초록)에서 done(파랑)으로 바뀐 경우만 표시합니다. "
            "일산 기출은 학생 레벨과 무관하게 대수 전체 시험지를 중, 중상, 그래프 포함 순서로 보여주며 기존 상 난이도는 중상으로 취급합니다. "
            "단원평가/복습 테스트/학군지 기출/일산 기출은 학원 Wi-Fi에서만 Drive 해설지를 엽니다. "
            "REVIEW/SCHOOL_PAST/ILSAN_PAST는 tests-config.json의 sourceFiles.solutionFileId 또는 동등한 해설 메타데이터를 보존하고, UNIT은 Drive explanation 파일 기준으로 static/js/test_answer_link_map.json을 갱신해 /api/student/bootstrap assignedTests[].answerUrl과 학생 오늘-test 카드의 Drive explanation 링크를 확인해야 합니다. "
            "학생 답안지 OCR은 기본 OFF이며 학생 페이지 URL의 ?ocr=1에서만 촬영 UI를 켭니다. /api/ocr-test-sheet는 answersText와 score/wrong/pct 채점 미리보기만 반환하고 저장하지 않으며, 최종 /api/submit-test 저장은 학생이 확인 후 제출 버튼을 눌렀을 때만 진행합니다."
        ),
        "sources": ["routes/api_tests.py", "static/js/tests.js", "static/js/admin/features/testModal.js", "static/js/student.js"],
    },
    {
        "title": "공지와 설문",
        "keywords": ["공지", "설문", "announcement", "응답", "답장", "이미지"],
        "answer": (
            "공지/설문은 관리자에서 대상 학생을 골라 발행하고 학생 화면에서 확인/응답합니다. "
            "관리자는 실시간 답장, 익명 표시명, 설문 결과, 이미지 첨부를 확인할 수 있습니다."
        ),
        "sources": ["routes/api_announcements.py", "static/js/admin/features/announcements.js", "static/js/student.js"],
    },
    {
        "title": "학교 일정",
        "keywords": ["학교", "일정", "내신", "중간", "기말", "교과서", "수학시험", "school-calendar"],
        "answer": (
            "학교 일정은 school_calendar.json에 연도/학기/시험 구분별로 저장됩니다. "
            "학교별 공통 시험 기간과 학년/과목별 교과서, 시험 범위, 비고를 관리합니다. "
            "관리자 캘린더의 수학시험 표시는 전체학생 등록정보에 해당 학교/학년/과목 학생이 있을 때만 보이며, "
            "하루 3개 이상이면 첫 시험과 외 N개로 요약하고 클릭하면 당일 시험별 학생 명단 팝업을 엽니다."
        ),
        "sources": ["school_calendar.json", "static/school-cal.html", "static/js/school-cal.js", "static/js/admin/features/calendar.js"],
    },
    {
        "title": "파일과 자료",
        "keywords": ["파일", "자료", "업로드", "다운로드", "materials", "file"],
        "answer": (
            "파일관리는 /file-manage와 /api/fs/*에서 폴더, 업로드, 이동, 이름 변경, 삭제, 페이지별 폴더 설정을 다룹니다. "
            "운영 자료 파일과 런타임 파일은 실제 데이터로 취급해야 합니다."
        ),
        "sources": ["routes/api_fs.py", "static/file-manage.html", "static/js/file-manage.js"],
    },
    {
        "title": "학생 화면과 로그인",
        "keywords": ["학생화면", "student", "로그인", "bootstrap", "auth", "접근", "토큰"],
        "answer": (
            "학생 화면은 /student/<sid>와 /student-test/<sid>에서 동작하고, /api/auth/* 토큰으로 학생 계정을 관리합니다. "
            "학생 bootstrap 응답 형태는 유지해야 하며 assignedTests는 top-level 배열입니다. "
            "외부 네트워크에서는 academyAccessAllowed=false와 안내 문구를 내려 목록은 유지하되 영상 재생과 테스트 답지 열람만 막습니다. "
            "ghost-outside-test는 students.json에 넣지 않는 코드 전용 외부접속 테스트 학생이라 전체 학생 명단과 집계에 포함되지 않으며, 관련 저장 API도 읽기 전용으로 차단됩니다."
        ),
        "sources": ["app.py", "core/ghost_student.py", "core/network_access.py", "routes/api_auth.py", "routes/api_basic.py", "routes/api_kollus.py", "static/js/student.js", "static/js/auth.js"],
    },
    {
        "title": "백업과 런타임 데이터",
        "keywords": ["백업", "runtime", "데이터", "sqlite", "json", "복구", "마이그레이션"],
        "answer": (
            "students.json, progress.json, logs.json, app.sqlite 같은 런타임 데이터는 실제 운영 데이터입니다. "
            "마이그레이션이나 bulk repair 전에는 scripts/backup_runtime_data.py로 백업해야 합니다."
        ),
        "sources": ["AGENTS.md", "scripts/backup_runtime_data.py", "core/storage.py"],
    },
    {
        "title": "저장 잠금 오류",
        "keywords": ["lock", "잠금", "저장오류", "409", "progress.json.lock", "watch.json.lock"],
        "answer": (
            "progress.json, watch.json, logs.json, updates.json 같은 운영 JSON 저장은 core/storage.py의 공통 파일 잠금으로 보호됩니다. "
            "저장 중 프로세스가 종료되어 .lock 파일이 남으면 stale lock을 자동 회수하고, 살아있는 프로세스의 잠금은 기다렸다가 재시도해야 합니다."
        ),
        "sources": ["core/storage.py", "routes/api_basic.py", "static/js/admin/features/testModal.js"],
    },
    {
        "title": "관리자 챗봇",
        "keywords": ["챗봇", "내부검색", "검색형", "api 없이", "assistant"],
        "answer": (
            "관리자 챗봇 1차 버전은 외부 AI API 없이 내부 자료를 검색하고 규칙 기반으로 답변합니다. "
            "기능 변경이 생기면 AGENTS.md 지침에 따라 챗봇 지식과 답변 범위도 함께 갱신해야 합니다."
        ),
        "sources": ["core/admin_chat.py", "routes/api_admin_chat.py", "AGENTS.md"],
    },
]

DOC_SOURCES = [
    BASE / "AGENTS.md",
    BASE / "PROJECT_SUMMARY.md",
    BASE / "DELTA_NOTES.md",
    BASE / "Design.md",
    BASE / "scripts" / "refactor_notes_logs_progress.md",
]


def answer_admin_chat(
    message: str,
    *,
    now: dt.datetime | None = None,
    context: Any = None,
    history: Any = None,
) -> dict[str, Any]:
    query = _clean_text(message)[:MAX_QUERY_LEN]
    today = _resolve_query_date(query, now=now)

    if not query:
        return _payload(
            "학생 이름, 날짜, 기능 키워드를 넣어 질문하면 내부 자료에서 찾아볼게요.",
            cards=[_overview_card(today)],
            suggestions=_default_suggestions(today),
            sources=["students.json", "videos.json", "AGENTS.md"],
        )

    demo_tokens = ("demo", "체험판", "/demo/rh3123", "/dh1130")
    if any(token in _norm(query) for token in demo_tokens):
        return _payload(
            "관리자 체험판은 /demo/rh3123에서 시작하며, 실제 /admin과 연계 페이지를 브라우저 안의 격리된 더미 데이터로 실행합니다.",
            cards=[
                {
                    "title": "관리자 체험판",
                    "lines": [
                        "/dh1130은 운영 관리자 화면 alias이고, /demo/rh3123, /demo/rh3123/students, /demo/rh3123/school-cal, /demo/rh3123/video-manage, /demo/rh3123/tests는 기존 UI를 그대로 쓰는 조교 교육용 체험판입니다.",
                        "체험판 API와 챗봇 요청은 demo fetch 계층에서 더미 학생, 학교일정, 영상, 로그, 테스트 데이터로 응답하며 운영 JSON이나 SQLite 데이터를 읽거나 노출하지 않아야 합니다.",
                        "이 백엔드 답변은 유지보수용 안내만 제공하고 실제 demo 모드의 /api/admin/chat 요청은 브라우저 fetch 인터셉터가 처리합니다.",
                    ],
                }
            ],
            suggestions=_default_suggestions(today),
            sources=["routes/pages.py", "static/js/admin/demo/bootstrap.js", "static/js/admin/demo/fetch.js", "static/js/admin/demo/tutorial.js", "static/js/admin/demo/store.js"],
        )

    students = _as_list(_safe_load(STU_PATH, []))
    student_matches = _find_students(query, students, limit=5)
    topic_hits = _feature_topic_hits(query, limit=3)

    cards: list[dict[str, Any]] = []
    sources: list[str] = []

    if _wants_overview(query):
        cards.append(_overview_card(today))
        sources.extend(["students.json", "videos.json", "tests-config.json", "school_calendar.json"])

    if student_matches and (_wants_student(query) or len(student_matches) == 1):
        for student, _score in student_matches[:2]:
            cards.append(_student_card(student))
            sources.append("students.json")
            if _wants_student_day_detail(query):
                detail = _student_day_card(student, today, query)
                if detail:
                    cards.append(detail)
                    sources.extend(detail.get("sources", []))
        if len(student_matches) > 2:
            cards.append({
                "title": "비슷한 학생",
                "lines": [_student_label(s) for s, _ in student_matches[2:5]],
            })

    if _wants_school(query):
        card = _school_calendar_card(query, students, today)
        if card:
            cards.append(card)
            sources.extend(card.get("sources", []))

    if _wants_video(query):
        card = _video_card(query, student_matches[:1], today)
        if card:
            cards.append(card)
            sources.extend(card.get("sources", []))

    if _wants_tests(query):
        card = _tests_card(query, student_matches[:1], today)
        if card:
            cards.append(card)
            sources.extend(card.get("sources", []))

    if _wants_attendance(query) and not any(c.get("kind") == "student-day" for c in cards):
        card = _attendance_card(today)
        if card:
            cards.append(card)
            sources.extend(card.get("sources", []))

    for hit in topic_hits:
        if not _has_card_title(cards, hit["title"]):
            cards.append({
                "title": hit["title"],
                "lines": [_clip(hit["answer"], 260)],
            })
            sources.extend(hit.get("sources", []))

    doc_card = _doc_search_card(query)
    if doc_card:
        cards.append(doc_card)
        sources.extend(doc_card.get("sources", []))

    if not cards:
        cards.append(_overview_card(today))
        cards.extend({
            "title": hit["title"],
            "lines": [_clip(hit["answer"], 260)],
        } for hit in _feature_topic_hits(" ".join(_tokens(query)), limit=2))
        sources.extend(["AGENTS.md", "PROJECT_SUMMARY.md"])

    cards = _dedupe_cards(cards)[:8]
    sources = _dedupe_sources(sources)

    answer = _summary_for_cards(cards, query)
    suggestions = _suggestions_for_query(query, student_matches, today)
    return _payload(answer, cards=cards, suggestions=suggestions, sources=sources)


def _payload(answer: str, *, cards: list[dict[str, Any]], suggestions: list[str], sources: list[str]) -> dict[str, Any]:
    return {
        "ok": True,
        "mode": "local-search",
        "answer": answer,
        "cards": [_public_card(card) for card in cards],
        "suggestions": suggestions[:6],
        "sources": _dedupe_sources(sources)[:12],
    }


def _public_card(card: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": str(card.get("title") or "결과"),
        "lines": [str(x) for x in card.get("lines", []) if str(x).strip()][:12],
    }


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _norm(value: Any) -> str:
    return _clean_text(value).casefold()


def _tokens(value: Any) -> list[str]:
    out = []
    for token in TOKEN_RE.findall(_norm(value)):
        if len(token) < 2 or token in STOPWORDS:
            continue
        out.append(token)
    return out


def _safe_load(path: Path, default: Any) -> Any:
    try:
        data = load(path)
    except Exception:
        return default
    if data is None:
        return default
    return data


def _as_list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _as_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _resolve_query_date(query: str, *, now: dt.datetime | None = None) -> str:
    found = DATE_RE.search(query or "")
    if found:
        return found.group(0)
    current = now.astimezone(KST) if now else dt.datetime.now(KST)
    base = current.date()
    q = _norm(query)
    if "어제" in q:
        base -= dt.timedelta(days=1)
    elif "내일" in q:
        base += dt.timedelta(days=1)
    return base.isoformat()


def _wants_overview(query: str) -> bool:
    q = _norm(query)
    return any(word in q for word in ("전체", "요약", "현황", "뭐 있어", "무엇", "통계", "목록", "학생 수", "인원", "몇명", "몇 명", "개수", "카운트"))


def _wants_student(query: str) -> bool:
    q = _norm(query)
    return any(word in q for word in ("학생", "정보", "누구", "학교", "등원", "교재", "수업", "숙제", "로그", "진도", "성적"))


def _wants_student_day_detail(query: str) -> bool:
    q = _norm(query)
    return any(word in q for word in (
        "오늘", "어제", "내일", "날짜", "로그", "숙제", "진도", "영상", "출석",
        "출결", "연락", "도착", "결석", "보강", "완료", "테스트", "성적",
    )) or bool(DATE_RE.search(query or ""))


def _wants_school(query: str) -> bool:
    q = _norm(query)
    return any(word in q for word in ("학교", "일정", "내신", "중간", "기말", "시험일", "교과서", "범위"))


def _wants_video(query: str) -> bool:
    q = _norm(query)
    return any(word in q for word in ("영상", "진도", "시청", "배정", "updates", "progress", "watch", "자동배정"))


def _wants_tests(query: str) -> bool:
    q = _norm(query)
    return any(word in q for word in ("테스트", "성적", "채점", "오답", "시험", "assignedtests"))


def _wants_attendance(query: str) -> bool:
    q = _norm(query)
    return any(word in q for word in ("출석", "출결", "결석", "보강", "연락", "도착", "하원", "완료"))


def _feature_topic_hits(query: str, *, limit: int = 5) -> list[dict[str, Any]]:
    q = _norm(query)
    toks = set(_tokens(query))
    hits: list[tuple[int, dict[str, Any]]] = []
    for topic in FEATURE_TOPICS:
        score = 0
        text = _norm(" ".join([
            topic.get("title", ""),
            topic.get("answer", ""),
            " ".join(topic.get("keywords", [])),
        ]))
        for keyword in topic.get("keywords", []):
            kw = _norm(keyword)
            if kw and kw in q:
                score += 8
        for token in toks:
            if token in text:
                score += 2
        if score:
            hits.append((score, topic))
    hits.sort(key=lambda item: item[0], reverse=True)
    return [topic for _, topic in hits[:limit]]


def _find_students(query: str, students: list, *, limit: int = 5) -> list[tuple[dict, int]]:
    q = _norm(query)
    toks = _tokens(query)
    hits: list[tuple[int, dict]] = []
    for raw in students:
        if not isinstance(raw, dict):
            continue
        name = _norm(raw.get("name"))
        sid = _norm(raw.get("id"))
        hay = _norm(" ".join(str(raw.get(k) or "") for k in (
            "id", "name", "school", "grade", "curriculum", "subCurriculum",
            "level", "subBook1", "subBook2", "day1", "day2", "day3", "day4", "day5",
        )))
        score = 0
        if name and name in q:
            score += 40
        if sid and sid in q:
            score += 45
        for token in toks:
            if token == name or token == sid:
                score += 30
            elif token and token in name:
                score += 12
            elif token and token in sid:
                score += 12
            elif token and token in hay:
                score += 3
        if score:
            hits.append((score, raw))
    hits.sort(key=lambda item: item[0], reverse=True)
    return [(student, score) for score, student in hits[:limit]]


def _student_label(student: dict) -> str:
    name = _clean_text(student.get("name")) or "이름 없음"
    sid = _clean_text(student.get("id"))
    school = _clean_text(student.get("school"))
    grade = _clean_text(student.get("grade"))
    bits = [x for x in (sid, school, grade) if x]
    return f"{name} ({', '.join(bits)})" if bits else name


def _student_card(student: dict) -> dict[str, Any]:
    lines = []
    field_labels = [
        ("id", "SID"),
        ("school", "학교"),
        ("grade", "학년"),
        ("curriculum", "과정"),
        ("subCurriculum", "세부과정"),
        ("level", "레벨"),
        ("subBook1", "교재1"),
        ("subBook2", "교재2"),
        ("autoVideoAssignCount", "자동 영상 수"),
    ]
    for key, label in field_labels:
        value = _clean_text(student.get(key))
        if value:
            lines.append(f"{label}: {value}")

    schedule = _student_schedule(student)
    if schedule:
        lines.append("등원: " + " / ".join(schedule))

    doc_url = _clean_text(student.get("docUrl"))
    if doc_url:
        lines.append(f"학습문서: {doc_url}")

    return {"title": _student_label(student), "lines": lines or ["표시할 학생 세부 정보가 없습니다."]}


def _student_schedule(student: dict) -> list[str]:
    self_study = _as_dict(student.get("selfStudyDays"))
    rows = []
    for idx in range(1, 8):
        day = _clean_text(student.get(f"day{idx}"))
        visit = _clean_text(student.get(f"visitTime{idx}"))
        if not day and not visit:
            continue
        label = " ".join(x for x in (day or "요일 미정", visit) if x)
        if self_study.get(f"day{idx}") is True:
            label += " 자습"
        rows.append(label)
    return rows


def _overview_card(today: str) -> dict[str, Any]:
    students = _as_list(_safe_load(STU_PATH, []))
    videos = _as_list(_safe_load(VID_PATH, []))
    cfg = _as_dict(_safe_load(TESTS_CFG_PATH, {}))
    calendar = _as_dict(_safe_load(CAL_PATH, {}))
    announcements = _safe_load(ANNS_PATH, [])

    schools = Counter(_clean_text(s.get("school")) for s in students if isinstance(s, dict) and _clean_text(s.get("school")))
    curris = Counter(_clean_text(s.get("curriculum")) for s in students if isinstance(s, dict) and _clean_text(s.get("curriculum")))
    video_curris = Counter(_clean_text(v.get("curriculum")) for v in videos if isinstance(v, dict) and _clean_text(v.get("curriculum")))
    test_count = _tests_config_count(cfg)
    school_count = _school_calendar_count(calendar)
    ann_count = len(announcements) if isinstance(announcements, list) else 0

    lines = [
        f"기준 날짜: {today}",
        f"학생: {len(students)}명 / 학교: {len(schools)}곳 / 학교일정 등록 학교: {school_count}곳",
        f"영상: {len(videos)}개 / 테스트 카탈로그: {test_count}개 / 공지·설문: {ann_count}개",
    ]
    if curris:
        lines.append("과정 상위: " + _counter_line(curris))
    if video_curris:
        lines.append("영상 과정 상위: " + _counter_line(video_curris))
    if schools:
        lines.append("학교 상위: " + _counter_line(schools, limit=5))
    return {"title": "운영 데이터 요약", "lines": lines}


def _counter_line(counter: Counter, *, limit: int = 4) -> str:
    return ", ".join(f"{k} {v}" for k, v in counter.most_common(limit))


def _tests_config_count(cfg: dict) -> int:
    cats = _as_dict(cfg.get("categories"))
    total = 0
    for cat in cats.values():
        if isinstance(cat, dict) and isinstance(cat.get("tests"), list):
            total += len(cat["tests"])
    return total


def _school_calendar_count(calendar: dict) -> int:
    schools = _calendar_schools_for_active(calendar)
    return len(schools)


def _calendar_schools_for_active(calendar: dict) -> dict:
    year = str(calendar.get("activeYear") or "")
    years = _as_dict(calendar.get("years"))
    node = _as_dict(years.get(year)) if year else {}
    if not node and years:
        node = _as_dict(next(iter(years.values())))
    return _as_dict(node.get("schools"))


def _school_calendar_card(query: str, students: list, today: str) -> dict[str, Any] | None:
    calendar = _as_dict(_safe_load(CAL_PATH, {}))
    schools = _calendar_schools_for_active(calendar)
    if not schools:
        return None

    query_norm = _norm(query)
    student_schools = [_clean_text(s.get("school")) for s, _ in _find_students(query, students, limit=3)]
    candidates = []
    for school in schools.keys():
        school_s = str(school)
        if school_s and _norm(school_s) in query_norm:
            candidates.append(school_s)
    for school in student_schools:
        if school and school in schools and school not in candidates:
            candidates.append(school)

    if not candidates:
        q_tokens = _tokens(query)
        for school in schools.keys():
            if any(token in _norm(school) for token in q_tokens):
                candidates.append(str(school))
                break

    if not candidates:
        lines = [f"등록 학교: {len(schools)}곳", "학교명을 같이 입력하면 시험 기간, 교과서, 범위를 찾아줍니다."]
        return {"title": "학교 일정", "lines": lines, "sources": ["school_calendar.json"]}

    lines = []
    for school in candidates[:3]:
        node = _as_dict(schools.get(school))
        common = _as_dict(node.get("common"))
        bits = []
        for key, label in (("midterm", "중간"), ("midtermMath", "중간 수학"), ("final", "기말"), ("finalMath", "기말 수학")):
            value = _clean_text(common.get(key))
            if value:
                bits.append(f"{label} {value}")
        textbook = _clean_text(common.get("textbook"))
        if textbook:
            bits.append(f"공통 교과서 {textbook}")
        if not bits:
            bits.append("공통 일정 비어 있음")
        lines.append(f"{school}: " + " / ".join(bits))

        grade_lines = _matching_grade_calendar_lines(node, query)
        lines.extend(grade_lines[:3])

    return {"title": f"학교 일정 ({today} 기준 검색)", "lines": lines, "sources": ["school_calendar.json"]}


def _matching_grade_calendar_lines(school_node: dict, query: str) -> list[str]:
    grades = _as_dict(school_node.get("grades"))
    if not grades:
        return []
    toks = _tokens(query)
    hits = []
    for key, row in grades.items():
        row_d = _as_dict(row)
        hay = _norm(" ".join([str(key), str(row_d.get("__grade") or ""), str(row_d.get("__phase") or "")]))
        if toks and not any(t in hay for t in toks):
            continue
        bits = []
        for fkey, label in (("textbook", "교과서"), ("midtermRange", "중간범위"), ("finalRange", "기말범위"), ("finalNote", "비고")):
            value = _clean_text(row_d.get(fkey))
            if value:
                bits.append(f"{label} {value}")
        if bits:
            hits.append(f"- {key}: " + " / ".join(bits))
    return hits


def _video_card(query: str, student_hits: list[tuple[dict, int]], today: str) -> dict[str, Any] | None:
    videos = _as_list(_safe_load(VID_PATH, []))
    if not videos:
        return None

    if student_hits and _wants_student_day_detail(query):
        student = student_hits[0][0]
        sid = _clean_text(student.get("id"))
        updates = _as_dict(_safe_load(UPD_PATH, {}))
        progress = _as_dict(_safe_load(PRG_PATH, {}))
        day_updates = _as_dict(updates.get(today))
        assignment = _sid_lookup(day_updates, sid)
        mids = _assignment_mids(assignment)
        video_by_mid = {_clean_text(v.get("mid")): v for v in videos if isinstance(v, dict)}
        lines = []
        if mids:
            labels = [_video_label(video_by_mid.get(mid), mid) for mid in mids[:8]]
            lines.append("배정 영상: " + " / ".join(labels))
        else:
            lines.append(f"{today} 배정 영상이 없습니다.")
        day_progress = _sid_lookup(_as_dict(progress.get(today)), sid)
        counts = _status_counts(_as_dict(day_progress))
        if counts:
            lines.append("진도 상태: " + ", ".join(f"{_status_label(k)} {v}" for k, v in counts.items()))
        return {"title": f"{_student_label(student)} 영상·진도", "lines": lines, "sources": ["updates.json", "progress.json", "videos.json"]}

    matches = _search_videos(query, videos, limit=8)
    if matches:
        lines = [_video_label(video, _clean_text(video.get("mid"))) for video, _ in matches]
    else:
        curris = Counter(_clean_text(v.get("curriculum")) for v in videos if isinstance(v, dict) and _clean_text(v.get("curriculum")))
        lines = [f"전체 영상: {len(videos)}개"]
        if curris:
            lines.append("과정별: " + _counter_line(curris, limit=6))
        lines.append("과정명, 단원명, mid를 같이 입력하면 개별 영상을 검색합니다.")
    return {"title": "영상 검색", "lines": lines, "sources": ["videos.json"]}


def _search_videos(query: str, videos: list, *, limit: int = 8) -> list[tuple[dict, int]]:
    toks = _tokens(query)
    hits = []
    for raw in videos:
        if not isinstance(raw, dict):
            continue
        hay = _norm(" ".join(str(raw.get(k) or "") for k in ("mid", "id", "title", "curriculum", "subCurriculum", "chapter")))
        score = sum(5 if token in hay else 0 for token in toks)
        if score:
            hits.append((raw, score))
    hits.sort(key=lambda item: item[1], reverse=True)
    return hits[:limit]


def _video_label(video: dict | None, fallback_mid: str) -> str:
    if not isinstance(video, dict):
        return fallback_mid
    parts = [
        _clean_text(video.get("curriculum")),
        _clean_text(video.get("subCurriculum")),
        _clean_text(video.get("chapter")),
        _clean_text(video.get("title")),
    ]
    label = " ".join(p for p in parts if p)
    mid = _clean_text(video.get("mid")) or fallback_mid
    return f"{label} ({mid})" if label and mid else label or mid


def _tests_card(query: str, student_hits: list[tuple[dict, int]], today: str) -> dict[str, Any] | None:
    cfg = _as_dict(_safe_load(TESTS_CFG_PATH, {}))
    if student_hits and _wants_student_day_detail(query):
        student = student_hits[0][0]
        sid = _clean_text(student.get("id"))
        tests = _as_dict(_safe_load(TESTS_PATH, {}))
        recent = _recent_tests_for_sid(tests, sid, today=today, limit=8)
        lines = []
        if recent:
            lines.extend(recent)
        else:
            lines.append(f"{today} 전후로 확인된 테스트 기록이 없습니다.")
        return {"title": f"{_student_label(student)} 테스트", "lines": lines, "sources": ["tests.json", "tests-config.json"]}

    cats = _as_dict(cfg.get("categories"))
    lines = [f"카테고리: {len(cats)}개", f"테스트 카탈로그: {_tests_config_count(cfg)}개"]
    for key, cat in list(cats.items())[:6]:
        if not isinstance(cat, dict):
            continue
        label = _clean_text(cat.get("label")) or str(key)
        tests = cat.get("tests") if isinstance(cat.get("tests"), list) else []
        lines.append(f"{label}: {len(tests)}개")
    return {"title": "테스트 관리", "lines": lines, "sources": ["tests-config.json", "tests.json"]}


def _recent_tests_for_sid(tests: dict, sid: str, *, today: str, limit: int = 8) -> list[str]:
    rows = []
    for date_key, by_sid in tests.items():
        if not DATE_RE.fullmatch(str(date_key)):
            continue
        arr = _sid_lookup(_as_dict(by_sid), sid)
        if isinstance(arr, dict):
            arr = arr.get("tests")
        if not isinstance(arr, list):
            continue
        for rec in arr:
            if not isinstance(rec, dict):
                continue
            name = _clean_text(rec.get("name") or rec.get("testName"))
            score = _clean_text(rec.get("score"))
            wrong = rec.get("wrong") if isinstance(rec.get("wrong"), list) else []
            label = f"{date_key} {name or '테스트'}"
            if score:
                label += f" {score}"
            if wrong:
                label += f" 오답 {len(wrong)}개"
            rows.append((str(date_key), label))
    rows.sort(key=lambda item: (item[0] != today, item[0]), reverse=True)
    return [label for _, label in rows[:limit]]


def _attendance_card(today: str) -> dict[str, Any]:
    attendance = _as_dict(_safe_load(ATTENDANCE_PATH, {}))
    contact = _as_dict(_safe_load(CONTACT_PATH, {}))
    arrive = _as_dict(_safe_load(ARRIVE_TIME_PATH, {}))
    extra = _as_dict(_safe_load(EXTRA_PATH, {}))
    absent = _as_dict(_safe_load(ABS_PATH, {}))
    order = _as_dict(_safe_load(TODAY_ORDER_PATH, {}))
    weekend = _as_dict(_safe_load(WEEKEND_SLOTS_PATH, {}))

    day_att = _as_dict(attendance.get(today))
    day_contact = _as_dict(contact.get(today))
    day_arrive = _as_dict(arrive.get(today))
    extra_list = extra.get(today) if isinstance(extra.get(today), list) else []
    absent_by_date = _as_dict(absent.get("by_date"))
    absent_list = absent_by_date.get(today) if isinstance(absent_by_date.get(today), list) else []
    order_list = order.get(today) if isinstance(order.get(today), list) else []
    weekend_day = _as_dict(weekend.get(today))

    lines = [
        f"{today} 출석 체크: {sum(1 for v in day_att.values() if _truthy(v))}명",
        f"연락 체크: {sum(1 for v in day_contact.values() if _truthy(v))}명",
        f"도착 시간 기록: {len(day_arrive)}명",
        f"보강 등록: {len(extra_list)}명 / 결석 등록: {len(absent_list)}명",
    ]
    if order_list:
        lines.append(f"수동 정렬: {len(order_list)}명")
    if weekend_day:
        lines.append(f"주말 슬롯: {len(weekend_day)}명")
    return {"title": f"{today} 출결·보강 요약", "lines": lines, "sources": ["attendance.json", "contact.json", "arrive_time.json", "extra_attend.json", "absent.json"]}


def _student_day_card(student: dict, today: str, query: str) -> dict[str, Any] | None:
    sid = _clean_text(student.get("id"))
    if not sid:
        return None

    lines = []
    sources = []

    attendance = _as_dict(_safe_load(ATTENDANCE_PATH, {}))
    contact = _as_dict(_safe_load(CONTACT_PATH, {}))
    arrive = _as_dict(_safe_load(ARRIVE_TIME_PATH, {}))
    extra = _as_dict(_safe_load(EXTRA_PATH, {}))
    absent = _as_dict(_safe_load(ABS_PATH, {}))

    day_att = _sid_lookup(_as_dict(attendance.get(today)), sid)
    day_contact = _sid_lookup(_as_dict(contact.get(today)), sid)
    day_arrive = _sid_lookup(_as_dict(arrive.get(today)), sid)
    extra_list = extra.get(today) if isinstance(extra.get(today), list) else []
    absent_list = _as_dict(absent.get("by_date")).get(today)
    absent_list = absent_list if isinstance(absent_list, list) else []

    if _truthy(day_att):
        lines.append("출석: 체크됨")
    if _truthy(day_contact):
        lines.append("연락: 체크됨")
    if day_arrive:
        lines.append(f"도착 시간: {day_arrive}")
    if sid in {str(x) for x in extra_list}:
        lines.append("보강: 등록됨")
    if sid in {str(x) for x in absent_list}:
        lines.append("결석: 등록됨")
    sources.extend(["attendance.json", "contact.json", "arrive_time.json", "extra_attend.json", "absent.json"])

    logs = _as_dict(_safe_load(LOGS_PATH, {}))
    log_entry = _sid_lookup(_as_dict(logs.get(today)), sid)
    if isinstance(log_entry, dict) and log_entry:
        if _truthy(log_entry.get("done")):
            lines.append("수업 완료: 완료")
        notes = _clean_text(log_entry.get("notes"))
        if notes:
            lines.append("특이사항: " + _clip(notes, 180))
        hw_rows = log_entry.get("homeworkTable")
        if isinstance(hw_rows, list) and hw_rows:
            lines.extend(_homework_lines(hw_rows)[:4])
        elif _clean_text(log_entry.get("homework")):
            lines.append("숙제: " + _clip(log_entry.get("homework"), 180))
        sources.append("logs.json")

    progress = _as_dict(_safe_load(PRG_PATH, {}))
    day_progress = _sid_lookup(_as_dict(progress.get(today)), sid)
    counts = _status_counts(_as_dict(day_progress))
    if counts:
        lines.append("영상 진도: " + ", ".join(f"{_status_label(k)} {v}" for k, v in counts.items()))
        sources.append("progress.json")

    updates = _as_dict(_safe_load(UPD_PATH, {}))
    assignment = _sid_lookup(_as_dict(updates.get(today)), sid)
    mids = _assignment_mids(assignment)
    if mids:
        videos = _as_list(_safe_load(VID_PATH, []))
        video_by_mid = {_clean_text(v.get("mid")): v for v in videos if isinstance(v, dict)}
        labels = [_video_label(video_by_mid.get(mid), mid) for mid in mids[:5]]
        lines.append("배정 영상: " + " / ".join(labels))
        sources.extend(["updates.json", "videos.json"])

    tests = _as_dict(_safe_load(TESTS_PATH, {}))
    test_lines = _recent_tests_for_sid(tests, sid, today=today, limit=3)
    if test_lines:
        lines.append("테스트: " + " / ".join(test_lines[:3]))
        sources.append("tests.json")

    if not lines:
        lines.append(f"{today}에 확인된 출결·로그·진도 기록이 없습니다.")

    return {
        "kind": "student-day",
        "title": f"{_student_label(student)} {today}",
        "lines": lines,
        "sources": sources,
    }


def _homework_lines(rows: list) -> list[str]:
    lines = []
    for row in rows:
        if not isinstance(row, dict) or row.get("_deleted"):
            continue
        book = _clean_text(row.get("book"))
        current = _clean_text(row.get("this"))
        pct = _clean_text(row.get("pct"))
        comment = _clean_text(row.get("comment"))
        nxt = _clean_text(row.get("next"))
        bits = []
        if current:
            bits.append(f"이번 {current}")
        if pct:
            bits.append(f"{pct}%")
        if comment:
            bits.append(comment)
        if nxt:
            bits.append(f"다음 {nxt}")
        if book or bits:
            prefix = f"숙제 {book}: " if book else "숙제: "
            lines.append(prefix + " / ".join(bits))
    return lines


def _assignment_mids(value: Any) -> list[str]:
    if isinstance(value, dict):
        value = value.get("videos")
    if not isinstance(value, list):
        return []
    out = []
    for item in value:
        if isinstance(item, dict):
            mid = _clean_text(item.get("mid"))
        else:
            mid = _clean_text(item)
        if mid and not mid.startswith("__"):
            out.append(mid)
    return out


def _status_counts(progress: dict) -> dict[str, int]:
    counter: Counter = Counter()
    for key, value in progress.items():
        if str(key).startswith("__") or key == "tests":
            continue
        status = _clean_text(value)
        if status:
            counter[status] += 1
    order = ["done", "assigned", "interrupted", "skip", "none"]
    out = {k: counter[k] for k in order if counter[k]}
    for key, value in counter.items():
        if key not in out:
            out[key] = value
    return out


def _status_label(status: str) -> str:
    return {
        "done": "완료",
        "assigned": "배정",
        "interrupted": "중단",
        "skip": "건너뜀",
        "none": "미완료",
    }.get(status, status)


def _truthy(value: Any) -> bool:
    if value is True:
        return True
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on", "checked"}


def _sid_lookup(mapping: dict, sid: str) -> Any:
    if not isinstance(mapping, dict):
        return None
    sid_s = str(sid or "").strip()
    if sid_s in mapping:
        return mapping.get(sid_s)
    if sid_s.isdigit():
        return mapping.get(str(int(sid_s)))
    return None


def _doc_search_card(query: str) -> dict[str, Any] | None:
    toks = _tokens(query)
    if not toks:
        return None
    hits: list[tuple[int, str, str]] = []
    for path in DOC_SOURCES:
        try:
            text = path.read_text("utf-8-sig")
        except Exception:
            continue
        current_heading = path.name
        for raw in text.splitlines():
            line = _clean_text(raw)
            if not line:
                continue
            if line.startswith("#"):
                current_heading = line.lstrip("#").strip() or path.name
            hay = _norm(line)
            score = sum(1 for token in toks if token in hay)
            if score:
                hits.append((score, _relative_source(path), f"{current_heading}: {_clip(line, 180)}"))
    if not hits:
        return None
    hits.sort(key=lambda item: item[0], reverse=True)
    lines = []
    sources = []
    for _score, source, line in hits[:5]:
        lines.append(line)
        sources.append(source)
    return {"title": "프로젝트 문서 검색", "lines": lines, "sources": sources}


def _relative_source(path: Path) -> str:
    try:
        return str(path.relative_to(BASE)).replace("\\", "/")
    except Exception:
        return str(path)


def _clip(value: Any, limit: int = 160) -> str:
    text = _clean_text(value)
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _has_card_title(cards: list[dict[str, Any]], title: str) -> bool:
    return any(_norm(card.get("title")) == _norm(title) for card in cards)


def _dedupe_cards(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    out = []
    for card in cards:
        title = _clean_text(card.get("title"))
        lines = tuple(_clean_text(x) for x in card.get("lines", []))
        key = (title, lines)
        if key in seen:
            continue
        seen.add(key)
        out.append(card)
    return out


def _dedupe_sources(sources: list[str]) -> list[str]:
    out = []
    seen = set()
    for source in sources:
        source_s = str(source or "").strip()
        if not source_s or source_s in seen:
            continue
        seen.add(source_s)
        out.append(source_s)
    return out


def _summary_for_cards(cards: list[dict[str, Any]], query: str) -> str:
    if not cards:
        return "일치하는 내부 자료를 찾지 못했습니다."
    first = cards[0].get("title") or "검색 결과"
    if len(cards) == 1:
        return f"{first} 기준으로 확인했습니다."
    return f"{first} 외 {len(cards) - 1}개 항목을 내부 자료에서 확인했습니다."


def _default_suggestions(today: str) -> list[str]:
    return [
        "보강 잡기 기능 설명",
        "학생 이름 정보",
        "학생 이름 오늘 숙제 진도",
        "학교명 기말 일정",
        "영상 배정 기능 설명",
        "테스트 관리 기능 설명",
    ]


def _suggestions_for_query(query: str, student_hits: list[tuple[dict, int]], today: str) -> list[str]:
    suggestions = []
    if student_hits:
        name = _clean_text(student_hits[0][0].get("name")) or "학생 이름"
        suggestions.extend([
            f"{name} {today} 숙제 진도",
            f"{name} 테스트 성적",
            f"{name} 학교 일정",
        ])
    if _wants_school(query):
        suggestions.append("학교명 기말 일정")
    if _wants_video(query):
        suggestions.append("과정명 영상 검색")
    suggestions.extend(_default_suggestions(today))
    out = []
    for item in suggestions:
        if item not in out:
            out.append(item)
    return out[:6]
