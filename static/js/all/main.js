// static/js/all/main.js
import { $ } from './core/utils.js';
import { loadAll, loadHomeworkBooks, state } from './core/state.js';
import { renderYoilStats } from './features/yoilStats.js';
import { renderHomeworkBooks, renderTable } from './features/table.js?v=20260831-all-notes1';
import './features/progressModal.js';
import './features/styles.js';
import { hookAllSort } from './features/sortHelpers.js';
import { hookDeleteButtons } from './features/deleteButtons.js';
import { hookCloneButtons } from './features/cloneButtons.js';
import './features/escClose.js';
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

/** 이름+학교 기준으로 학생 dedup용 키 (table.js와 동일 로직) */
function dedupKeyForStudent(s) {
  const name = (s.name || '').trim();

  const high =
    s.highSchool ||
    s.schoolHigh ||
    s.high ||
    s.highschool ||
    s.high_school ||
    s.고등학교 ||
    '';

  const middle =
    s.middleSchool ||
    s.schoolMiddle ||
    s.middle ||
    s.middleschool ||
    s.middle_school ||
    s.중학교 ||
    s.school ||
    '';

  const school = s.school || high || middle || '';

  return `${name}::${school}`;
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
