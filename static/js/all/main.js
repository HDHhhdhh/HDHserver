// static/js/all/main.js
import { $ } from './core/utils.js';
import { loadAll, loadHomeworkBooks, state } from './core/state.js';
import { renderYoilStats } from './features/yoilStats.js';
import { dedupKeyForStudent, renderHomeworkBooks, renderTable } from './features/table.js?v=20260907-ilsan-level-r1&watchRearm=20260912&youtube=20260913&bookSleep=4&homeworkOpenStable=1&whiteRetest=20260928&hubSave=20261001&testSaveReady=20261002&scheduleTab=20261002&uiPerf=20261002&dragScroll=20261007';
import './features/progressModal.js';
import './features/styles.js';
import { hookAllSort } from './features/sortHelpers.js';
import { hookDeleteButtons } from './features/deleteButtons.js';
import { hookCloneButtons } from './features/cloneButtons.js';
import './features/escClose.js?v=20260929-search-visibility1';
import { mountNewStudentBar } from './features/addStudent.js';
import { mountChatRosterExport } from './features/chatRosterExport.js';
import { decorateStudentTestRecordButtons, initStudentTestRecordDetails } from '../shared/testRecordDetails.js';
import { state as adminTooltipState } from '../admin/core/state.js';
import { initHoverTooltip as initAdminHoverTooltip } from '../admin/features/hoverTooltip.js?v=20260906-exam-pending-color1';

function syncAdminTooltipState() {
  adminTooltipState.students = state.students;
  adminTooltipState.videos = state.videos;
  adminTooltipState.progress = state.progress;
  adminTooltipState.schoolCal = state.schoolCal;
  adminTooltipState.homeworkBooksBySid = state.homeworkBooksBySid;
}

/** 전체 학생 수 라벨 갱신 (state.students 기준) */
function updateAllCount() {
  const studs = (state?.students && state.students.length ? state.students : window.students) || [];
  const uniq = new Set();

  for (const s of studs) {
    const key = dedupKeyForStudent(s);
    if (key.trim()) uniq.add(key);
  }

  const el = $('allCount');
  if (el) el.textContent = `전체 학생 수: ${uniq.size}명`;
}

function renderAll() {
  syncAdminTooltipState();
  updateAllCount();
  renderTable();
  document.dispatchEvent(new CustomEvent('all:rendered'));
  renderYoilStats();
  hookAllSort();
  hookDeleteButtons();
  hookCloneButtons({
    onCloned: async () => {
      await loadAll();
      renderAll();
    },
  });
  mountNewStudentBar();
  mountChatRosterExport();
  decorateStudentTestRecordButtons(document).catch(console.warn);
}

document.addEventListener('all:student-deleted', (event) => {
  const sid = String(event.detail?.sid || '').trim();
  if (!sid) return;
  state.students = state.students.filter(student => String(student?.id || '') !== sid);
  window.students = state.students;
  syncAdminTooltipState();
  document.dispatchEvent(new CustomEvent('all:rendered'));
  updateAllCount();
  renderYoilStats();
});

(async function init() {
  try {
    await loadAll({ waitForHomeworkBooks: false });
    syncAdminTooltipState();
    initAdminHoverTooltip();
    initStudentTestRecordDetails(document);
    renderAll();

    void loadHomeworkBooks().then(() => {
      syncAdminTooltipState();
      renderHomeworkBooks();
      document.dispatchEvent(new CustomEvent('all:homework-books-loaded'));
    });

    document.addEventListener('admin:refresh', () => {
      updateAllCount();
    });
  } catch (e) {
    console.error(e);
    const wrap = $('allWrap');
    if (wrap) wrap.textContent = '데이터 로드 중 오류가 발생했습니다.';
  }
})();
