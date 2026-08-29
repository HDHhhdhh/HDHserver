import { bootstrap, state } from './core/state.js';
import { initDarkmode } from './core/darkmode.js';
import { initAdminViewMode } from './core/viewMode.js';
import { initEscClose } from './features/escClose.js';
import { initHoverTooltip } from './features/hoverTooltip.js?v=20260819-subject-days1';
import { initVideoModal } from './features/videoModal.js?v=20260826-save-feedback1';
import { initLogModal } from './features/logModal.js?v=20260829-video-snapshot1';
import { initExtraModal } from './features/extraModal.js?v=20260821-safe-merge1';
import { initAbsentRegister } from './features/absentRegister.js';
import { initCalendar } from './features/calendar.js?v=20260824-sheet-sync3';
import { initExport } from './features/exportLogs.js?v=20260826-roster-current-content2&quickPrinter=1';
import { initQuickPrinterExport } from './features/quickPrinterExport.js?v=20260829-time-filter1';
import { initAnnouncements } from './features/announcements.js';
import { initClearAll } from './features/done.js?v=20260821-log-batch1';
import { loadTodayAndRender } from './features/today.js?v=20260824-linked-leave1';
import { initAbsentRecovery } from './features/absentRecovery.js';
import { initTimeGraph } from './features/timeGraph.js';
import { initAdminDateBar } from './core/adminDate.js';
import { initAdminUiEnhance } from './features/uiEnhance.js?v=20260824-sheet-sync2';
import { initStudentTestRecordDetails } from '../shared/testRecordDetails.js';
import { initAssistantStudentNotes } from './features/assistantStudentNotes.js?v=20260821-note-body-row2';
import { initAdminOperationNotes } from './features/adminOperationNotes.js';
import { initStudentLogs } from './features/studentLogs.js?v=20260816-student-log-restore2';
import { initStudentAccounts } from './features/studentAccounts.js';
import { initStudentFocus } from './features/studentFocus.js';
import { initStudentTestOcrReview } from './features/studentTestOcrReview.js?v=20260828-1';


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

// 3) 기능 초기화(순서 중요하지 않은 것들)
initHoverTooltip();
initAssistantStudentNotes();
initAdminOperationNotes();
initStudentLogs();
initStudentAccounts();
initStudentFocus();
initStudentTestOcrReview();
initVideoModal();
initLogModal();
initExtraModal();
initAbsentRegister();
initCalendar();
initExport();
initQuickPrinterExport();
initAnnouncements();
initClearAll();
initAbsentRecovery();
initTimeGraph();
initAdminDateBar({ mountId: 'adminDateMount' });
initAdminUiEnhance();
initStudentTestRecordDetails(document);


// 4) 최초 렌더 + 이벤트로 재렌더
loadTodayAndRender();

// 기존 전역 의존 로직을 위해 최소 노출(필요 시)
window.state = state;
