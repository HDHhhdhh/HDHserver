export const PAGE_FEATURES = {
  admin: {
    title: '관리자 운영',
    subtitle: '오늘 수업 운영 흐름을 더미 데이터로 연습합니다.',
    features: [
      {
        id: 'admin-date',
        title: '운영 날짜 확인',
        body: '날짜를 바꾸면 오늘 목록과 로그 기준이 함께 바뀝니다. 먼저 기준일을 확인하세요.',
        target: ['#adminDateMount .adb-wrap', '#adb_date_display', '#adminDateMount', '#adminDate', '#selectedDate', 'input[type="date"]'],
      },
      {
        id: 'admin-today',
        title: '오늘 학생 목록 점검',
        body: '출석, 연락, 도착 시간, 보강 상태를 한 줄에서 처리하는 흐름을 익힙니다.',
        priority: -20,
        target: ['#todayWrap .today-table tbody tr[data-sid]', '#todayTable', '#todayBody', '.today-list', '.today-table'],
      },
      {
        id: 'admin-log',
        title: '학생 작업 팝업 열기',
        body: '상담 기록 버튼은 수업 기록, 영상 배정, 테스트 배정 팝업을 한 번에 엽니다.',
        target: ['.openStudentPopups', '.editLog', 'button[data-action*="log"]', '.log-btn', '.btn-log', '#logModal'],
      },
      {
        id: 'admin-attendance',
        title: '출석/연락/숙제 체크',
        body: '체크 버튼은 행 날짜의 출석, 연락, 숙제 완료, 자습, 숙검요청 상태를 더미 데이터로 바꿉니다.',
        target: ['.attendChk', '.contactChk', '.hwCheckChk', '.selfStudyChk', '.hwRequestChk', '.chk4', '.self-study-toggle', '.homework-request-toggle'],
      },
      {
        id: 'admin-row-actions',
        title: '결석과 하원 처리',
        body: '결석, 하원, 되돌리기, 기록 정리 버튼으로 하루 운영 마감 흐름을 연습합니다.',
        target: ['.markAbsent', '.markLeave', '.undoDone', '.clearDone', '#homeworkLeaveBtn'],
      },
      {
        id: 'admin-document',
        title: '학생 문서 열기',
        body: '문서 버튼은 더미 학생의 자료 링크 위치와 연결 상태를 확인하는 용도입니다.',
        target: ['.btn-doc', '.today-doc-cell'],
      },
      {
        id: 'admin-video',
        title: '영상 배정 확인',
        body: '영상 배정 모달에서 자동/수동 배정과 시청 진도 표시를 확인합니다.',
        target: ['button[data-action*="video"]', '.video-btn', '.btn-video', '#vidModal'],
      },
      {
        id: 'admin-test',
        title: '테스트 배정 확인',
        body: '테스트 배정 모달에서 단원평가, 복습, 학교 기출 배정 상태를 확인합니다.',
        target: ['button[data-action*="test"]', '.test-btn', '.btn-test', '#testModal'],
      },
      {
        id: 'admin-chat',
        title: '관리자 챗봇 활용',
        body: '데모 챗봇은 합성 데이터만 기준으로 답합니다. 운영 질문 예시를 연습하세요.',
        target: ['#adminChatbot', '#adminChatPanel', '#adminChatToggle', '.admin-chatbot'],
      },
      {
        id: 'admin-nav',
        title: '연계 페이지 이동',
        body: '전체학생, 학교일정, 영상관리, 테스트관리도 같은 더미 데이터로 이어집니다.',
        target: ['.global-links', 'nav', 'header'],
      },
    ],
  },
  students: {
    title: '전체학생',
    subtitle: '학생 명단과 운영 데이터가 다른 데모 페이지와 연결되는 방식을 익힙니다.',
    features: [
      {
        id: 'students-search',
        title: '명단 검색과 정렬',
        body: '이름, 학교, 과정 검색으로 원하는 더미 학생을 빠르게 찾습니다.',
        target: ['#allStudentSearchInput', '#searchInput', '#allSearch', 'input[type="search"]', '#studentSearch'],
      },
      {
        id: 'students-inline',
        title: '학생 정보 직접 수정',
        body: '학교, 학년, 요일, 교재 같은 셀을 수정하면 데모 세션에만 저장됩니다.',
        target: ['#studentsTable', '#allTable', 'table tbody tr', '.students-table'],
      },
      {
        id: 'students-add',
        title: '신규 학생 추가',
        body: '상단 추가 바에서 학생을 만들면 더미 명단에만 추가됩니다.',
        target: ['#newStuMount', '#ns_add', '.ns-wrap'],
      },
      {
        id: 'students-clone-delete',
        title: '복제와 삭제 연습',
        body: '복제/삭제 버튼은 실제 명단을 건드리지 않고 데모 store만 바꿉니다.',
        target: ['.btn-clone-stu', '.btn-delete-stu', '.btn-del-stu', 'table tbody tr'],
      },
      {
        id: 'students-progress',
        title: '누적 진도 확인',
        body: '학생별 진도 팝업에서 영상/테스트 진행 상태가 연결되는 방식을 확인합니다.',
        target: ['.progress-btn', '.btn-progress', '[data-progress]', '#progressModal'],
      },
      {
        id: 'students-export',
        title: '명단 요약 활용',
        body: '명단 내보내기와 요약 도구는 더미 학생만 대상으로 연습합니다.',
        target: ['#chatRosterExport', '#copyRoster', '.roster-export', 'header.topbar'],
      },
    ],
  },
  calendar: {
    title: '학교일정',
    subtitle: '학교, 학년, 시험 범위 정보를 더미 일정으로 편집합니다.',
    features: [
      {
        id: 'calendar-page',
        title: '연도와 시험 페이지 선택',
        body: '연도, 학기, 중간/기말 페이지를 바꾸며 일정 묶음을 확인합니다.',
        target: ['#yearSelect', '#semesterSelect', '#examSelect', '.page-controls'],
      },
      {
        id: 'calendar-school',
        title: '학교 행 추가',
        body: '학교 행을 추가하고 학교명을 입력하는 흐름을 연습합니다.',
        target: ['#addSchool', '[data-action="add-school"]', '.school-row'],
      },
      {
        id: 'calendar-grade',
        title: '학년/범위 입력',
        body: '학년별 시험 범위와 진도 메모를 입력해 전체학생 데이터와 맞춥니다.',
        target: ['.grade-row', '.gr-grade', 'tbody'],
      },
      {
        id: 'calendar-save',
        title: '자동 저장 확인',
        body: '수정 후 저장 상태 문구가 바뀌는지 확인합니다. 실제 school_calendar.json은 쓰지 않습니다.',
        target: ['#saveCalendar', '#saveStatus', '.save-status'],
      },
    ],
  },
  videos: {
    title: '영상관리',
    subtitle: '더미 영상 카탈로그가 관리자 배정 화면과 연결되는 방식을 익힙니다.',
    features: [
      {
        id: 'videos-filter',
        title: '과정별 영상 필터',
        body: '커리큘럼, 세부과정, 검색어로 필요한 더미 영상을 찾습니다.',
        target: ['#curriculumFilter', '#subCurriculumFilter', '#videoSearch'],
      },
      {
        id: 'videos-add',
        title: '영상 추가 흐름',
        body: '추가 폼으로 새 더미 영상을 만들고 목록에 반영되는지 확인합니다.',
        target: ['#addVid', '#vTitle', '#vUrl', '#videoSection'],
      },
      {
        id: 'videos-edit',
        title: '영상 메타데이터 수정',
        body: '챕터, 제목, URL 셀을 수정한 뒤 저장 버튼으로 데모 store에 저장합니다.',
        target: ['#vidTable', '#saveVid', 'td[contenteditable]'],
      },
      {
        id: 'videos-delete',
        title: '삭제와 복구 연습',
        body: '삭제 버튼을 눌러도 운영 영상 데이터는 바뀌지 않습니다. 필요하면 데모 초기화로 되돌립니다.',
        target: ['.delV', '#vidTable'],
      },
    ],
  },
  tests: {
    title: '테스트관리',
    subtitle: '더미 테스트 카탈로그와 배정 규칙, 통계를 연습합니다.',
    features: [
      {
        id: 'tests-filter',
        title: '테스트 분류 탐색',
        body: '단원평가, 복습, 학교 기출, 일산 기출을 바꾸며 카탈로그 구조를 확인합니다.',
        target: ['#cfgType', '#cfgCur', '#testList'],
      },
      {
        id: 'tests-editor',
        title: '테스트 항목 편집',
        body: '시험명, 문항 수, 정답 링크 메타데이터를 수정하고 저장 흐름을 확인합니다.',
        target: ['#testEditor', '#testName', '#saveTest', '#cfgName'],
      },
      {
        id: 'tests-rules',
        title: '자동 배정 규칙 확인',
        body: '레벨과 난이도 매칭 규칙을 바꾸면 데모 테스트 배정 기준이 바뀝니다.',
        target: ['#rulesGrid', '.rule-grid', '#autoAssignRules'],
      },
      {
        id: 'tests-csv',
        title: 'CSV 가져오기 흐름',
        body: '템플릿 다운로드와 가져오기 UI를 확인합니다. 데모에서는 합성 카탈로그만 저장됩니다.',
        target: ['#csvImport', '#csvFile', '#downloadTemplate'],
      },
      {
        id: 'tests-stats',
        title: '테스트 통계 읽기',
        body: '응시 수, 평균, 상세 기록은 더미 통계로 표시됩니다.',
        target: ['#statsSummary', '#statsTable', '#statsDetail'],
      },
    ],
  },
};

export function resolvePageKey(pathname) {
  const path = String(pathname || '').replace(/\/+$/, '') || '/';
  if (path === '/demo/rh3123/students') return 'students';
  if (path === '/demo/rh3123/school-cal') return 'calendar';
  if (path === '/demo/rh3123/video-manage') return 'videos';
  if (path === '/demo/rh3123/tests') return 'tests';
  return 'admin';
}
