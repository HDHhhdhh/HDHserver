import { bootstrap, state } from './core/state.js';
import { initDarkmode } from './core/darkmode.js';
import { initAdminViewMode } from './core/viewMode.js';
import { initEscClose } from './features/escClose.js?v=20260929-search-visibility1&hubSave=20261001&escScope=20261009';
import { loadTodayAndRender } from './features/today.js?v=20260830-warning-visual1&leaveLabel=20260905b&ilsanLevel=20260907&doneWhiteReview=20260912&youtube=20260913&missingLeaveRefresh=20260927&schoolSearch=20260929&manualOrder=20261002&adminSpeed=20261003&leaveDetails=20261011&stabilityBase=20261013';
import { initAdminDateBar } from './core/adminDate.js';

async function loadCriticalAdminFeatures() {
  return Promise.all([
    import('./features/hoverTooltip.js?v=20260906-exam-pending-color1').then(module => module.initHoverTooltip),
    import('./features/assistantStudentNotes.js?v=20260821-note-body-row2').then(module => module.initAssistantStudentNotes),
    import('./features/videoModal.js?v=20260912-watch-rearm1&youtube=20260913&hubSave=20261001&uiPerf=20261002&dragScroll=20261007').then(module => module.initVideoModal),
    import('./features/logModal.js?v=20260914-homework-open-stable1&whiteRetest=20260928&hubSave=20261001&testSaveReady=20261002&uiPerf=20261002&dragScroll=20261007').then(module => module.initLogModal),
    import('./features/extraModal.js?v=20260929-retired-extra1&hubSave=20261001&adminSpeed=20261003').then(module => module.initExtraModal),
    import('./features/absentRegister.js?hubSave=20261001').then(module => module.initAbsentRegister),
    import('./features/exportLogs.js?v=20260907-ilsan-level-r1&quickPrinter=1&latency=1').then(module => module.initExport),
    import('./features/quickPrinterExport.js?v=20260920-reprint-default1').then(module => module.initQuickPrinterExport),
    import('./features/done.js?v=20260912-done-white-review1&youtube=20260913').then(module => module.initClearAll),
    import('./features/absentRecovery.js').then(module => module.initAbsentRecovery),
    import('./features/timeGraph.js').then(module => module.initTimeGraph),
    Promise.resolve(() => initAdminDateBar({ mountId: 'adminDateMount' })),
    import('./features/uiEnhance.js?v=20260824-sheet-sync2&stabilityBase=20261013').then(module => module.initAdminUiEnhance),
    import('../shared/testRecordDetails.js').then(module => () => module.initStudentTestRecordDetails(document)),
  ]);
}

// 1) 공통 초기화
initDarkmode();
initAdminViewMode();
initEscClose();

// 2) 데이터 로드
let criticalInitializers;
try {
  [, criticalInitializers] = await Promise.all([bootstrap(), loadCriticalAdminFeatures()]);
} catch (err) {
  console.error('[admin] bootstrap failed:', err);
  alert('관리자 초기 데이터를 불러오지 못했습니다. 새로고침 후 다시 시도해 주세요.');
  throw err;
}

// 3) 첫 운영 명단에 필요한 상호작용부터 연결
for (const initialize of criticalInitializers) {
  initialize();
}
// 기존 전역 의존 로직을 위해 최소 노출
window.state = state;

// 4) 최초 명단을 먼저 그린 뒤, 독립 패널/캘린더의 네트워크 요청을 시작한다.
// 기능은 모두 그대로 초기화하되 F5 직후의 연결 대기열에서 오늘 명단을 우선한다.
async function initDeferredAdminFeatures() {
  const jobs = [
    ['calendar', () => import('./features/calendar.js?v=20260929-retired-extra1&uiPerf=20261002&adminSpeed=20261003&examTextbook=20261012b').then(module => module.initCalendar())],
    ['admin operation notes', () => import('./features/adminOperationNotes.js').then(module => module.initAdminOperationNotes())],
    ['student logs', () => import('./features/studentLogs.js?v=20260816-student-log-restore2').then(module => module.initStudentLogs())],
    ['student accounts', () => import('./features/studentAccounts.js').then(module => module.initStudentAccounts())],
    ['student focus', () => import('./features/studentFocus.js?uiPerf=20261002').then(module => module.initStudentFocus())],
    ['student test OCR', () => import('./features/studentTestOcrReview.js?v=20260828-1&uiPerf=20261002').then(module => module.initStudentTestOcrReview())],
    ['announcements', () => import('./features/announcements.js?uiPerf=20261002').then(module => module.initAnnouncements())],
  ];
  const results = await Promise.allSettled(jobs.map(([_label, start]) => start()));
  results.forEach((result, index) => {
    if (result.status === 'rejected') {
      console.error(`[admin] deferred ${jobs[index][0]} initialization failed:`, result.reason);
    }
  });
}

void loadTodayAndRender()
  .catch((error) => {
    console.error('[admin] initial today render failed:', error);
  })
  .then(initDeferredAdminFeatures);
