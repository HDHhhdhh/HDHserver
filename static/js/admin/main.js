import { bootstrap, state } from './core/state.js';
import { initDarkmode } from './core/darkmode.js';
import { initAdminViewMode } from './core/viewMode.js';
import { initEscClose } from './features/escClose.js';
import { initHoverTooltip } from './features/hoverTooltip.js?v=20260906-exam-pending-color1';
import { initVideoModal } from './features/videoModal.js?v=20260830-popup-load3';
import { initLogModal } from './features/logModal.js?v=20260905-save-context1';
import { initExtraModal } from './features/extraModal.js?v=20260821-safe-merge1';
import { initAbsentRegister } from './features/absentRegister.js';
import { initExport } from './features/exportLogs.js?v=20260826-roster-current-content2&quickPrinter=1&latency=1';
import { initQuickPrinterExport } from './features/quickPrinterExport.js?v=20260830-carryover-history1';
import { initClearAll } from './features/done.js?v=20260821-log-batch1';
import { loadTodayAndRender } from './features/today.js?v=20260830-warning-visual1&leaveLabel=20260905b';
import { initAbsentRecovery } from './features/absentRecovery.js';
import { initTimeGraph } from './features/timeGraph.js';
import { initAdminDateBar } from './core/adminDate.js';
import { initAdminUiEnhance } from './features/uiEnhance.js?v=20260824-sheet-sync2';
import { initStudentTestRecordDetails } from '../shared/testRecordDetails.js';
import { initAssistantStudentNotes } from './features/assistantStudentNotes.js?v=20260821-note-body-row2';


// 1) 공통 초기화
initDarkmode();
initAdminViewMode();
initEscClose();

// 2) 데이터 로드
try {
  await bootstrap();
} catch (err) {
  console.error('[admin] bootstrap failed:', err);
  alert('관리자 초기 데이터를 불러오지 못했습니다. 새로고침 후 다시 시도해 주세요.');
  throw err;
}

// 3) 첫 운영 명단에 필요한 상호작용부터 연결
initHoverTooltip();
initAssistantStudentNotes();
initVideoModal();
initLogModal();
initExtraModal();
initAbsentRegister();
initExport();
initQuickPrinterExport();
initClearAll();
initAbsentRecovery();
initTimeGraph();
initAdminDateBar({ mountId: 'adminDateMount' });
initAdminUiEnhance();
initStudentTestRecordDetails(document);

// 기존 전역 의존 로직을 위해 최소 노출
window.state = state;

// 4) 최초 명단을 먼저 그린 뒤, 독립 패널/캘린더의 네트워크 요청을 시작한다.
// 기능은 모두 그대로 초기화하되 F5 직후의 연결 대기열에서 오늘 명단을 우선한다.
async function initDeferredAdminFeatures() {
  const jobs = [
    ['calendar', () => import('./features/calendar.js?v=20260830-latency2').then(module => module.initCalendar())],
    ['admin operation notes', () => import('./features/adminOperationNotes.js').then(module => module.initAdminOperationNotes())],
    ['student logs', () => import('./features/studentLogs.js?v=20260816-student-log-restore2').then(module => module.initStudentLogs())],
    ['student accounts', () => import('./features/studentAccounts.js').then(module => module.initStudentAccounts())],
    ['student focus', () => import('./features/studentFocus.js').then(module => module.initStudentFocus())],
    ['student test OCR', () => import('./features/studentTestOcrReview.js?v=20260828-1').then(module => module.initStudentTestOcrReview())],
    ['announcements', () => import('./features/announcements.js').then(module => module.initAnnouncements())],
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
