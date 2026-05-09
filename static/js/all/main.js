// static/js/all/main.js
import { $ } from './core/utils.js';
import { loadAll, state } from './core/state.js';
import { renderYoilStats } from './features/yoilStats.js';
import { renderTable } from './features/table.js';
import './features/progressModal.js';
import './features/hoverTooltip.js';
import './features/styles.js';
import { hookAllSort } from './features/sortHelpers.js';
import { hookDeleteButtons } from './features/deleteButtons.js';
import './features/escClose.js';
import { mountNewStudentBar } from './features/addStudent.js';
import { initCloneStudentModal } from './features/CloneStudentModal.js';

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
  updateAllCount();
  renderTable();
  renderYoilStats();
  hookAllSort();
  hookDeleteButtons();
  mountNewStudentBar();
}

(async function init() {
  try {
    await loadAll();
    renderAll();

    // ✅ 표 밖(상단 버튼)으로 "커리 복제" 모달 초기화
    initCloneStudentModal({
      onCloned: async () => {
        await loadAll();
        renderAll();
      }
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
