import { bootstrap, state } from './core/state.js';
import { initDarkmode } from './core/darkmode.js';
import { initEscClose } from './features/escClose.js';
import { initHoverTooltip } from './features/hoverTooltip.js';
import { initVideoModal } from './features/videoModal.js';
import { initLogModal } from './features/logModal.js';
import { initExtraModal } from './features/extraModal.js';
//import { initMaterials } from './features/materials.js';
import { initAssignModal } from './features/assignModal.js';
import { initCalendar } from './features/calendar.js';
import { initExport } from './features/exportLogs.js';
import { initClearAll } from './features/done.js';
import { loadTodayAndRender } from './features/today.js';
import { initTestModal } from './features/testModal.js';
import { initAbsentRecovery } from './features/absentRecovery.js';
import { initTimeGraph } from './features/timeGraph.js';
import { initAdminDateBar } from './core/adminDate.js';
import { initAdminUiEnhance } from './features/uiEnhance.js';


// 1) 공통 초기화
initDarkmode();
initEscClose();

// 2) 데이터 로드
await bootstrap();

// 3) 기능 초기화(순서 중요하지 않은 것들)
initHoverTooltip();
initVideoModal();
initLogModal();
initExtraModal();
//initMaterials();
initAssignModal();
initCalendar();
initExport();
initClearAll();
initTestModal();
initAbsentRecovery();
initTimeGraph();
initAdminDateBar({ mountId: 'adminDateMount' });
initAdminUiEnhance();


// 4) 최초 렌더 + 이벤트로 재렌더
loadTodayAndRender();
document.addEventListener('admin:refresh', loadTodayAndRender);

// 기존 전역 의존 로직을 위해 최소 노출(필요 시)
window.state = state;
