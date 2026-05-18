import { loadAll, state } from '../core/state.js';

const CT = { 'Content-Type': 'application/json' };

let onClonedCallback = null;
let delegated = false;

function getWrap() {
  return document.getElementById('allWrap')
    || document.getElementById('studentsWrap')
    || document.getElementById('listWrap')
    || document.body;
}

function getTable() {
  const w = getWrap();
  return w ? (w.querySelector('table') || w.querySelector('.all-table')) : null;
}

function parseRowInfo(tr) {
  let sid = tr.dataset.sid
    || tr.querySelector('.stuName, .stu-name, a[data-sid]')?.dataset?.sid
    || (tr.querySelector('a[href*="/student/"]')?.getAttribute('href') || '').split('/').pop()
    || tr.querySelector('[data-id]')?.dataset?.id || '';
  sid = (sid || '').trim();
  const name = (tr.querySelector('.stuName, .stu-name, a[href*="/student/"]')?.textContent || tr.cells?.[0]?.textContent || '').trim();
  return { sid, name };
}

function getStudents() {
  return (state?.students && state.students.length ? state.students : window.students) || [];
}

function schoolFor(stu = {}) {
  return (stu.school
    || stu.highSchool
    || stu.schoolHigh
    || stu.high
    || stu.highschool
    || stu.high_school
    || stu.고등학교
    || stu.middleSchool
    || stu.schoolMiddle
    || stu.middle
    || stu.middleschool
    || stu.middle_school
    || stu.중학교
    || '').trim();
}

function gradeFor(stu = {}) {
  return String(stu.grade ?? stu.gradeLevel ?? stu.studentGrade ?? stu.학년 ?? '').trim();
}

function buildCloneBody(stu) {
  return {
    name: String(stu.name || '').trim(),
    school: schoolFor(stu),
    grade: gradeFor(stu),
    level: String(stu.level || '').trim(),
    docUrl: String(stu.docUrl || '').trim(),
    curriculum: '',
    subCurriculum: '',
    day1: '',
    day2: '',
    day3: '',
    day4: '',
    day5: '',
    visitTime1: '',
    visitTime2: '',
    visitTime3: '',
    visitTime4: '',
    visitTime5: '',
    subBook1: '',
    subBook2: '',
  };
}

function insertAfter(parent, node, afterNode) {
  if (afterNode?.nextSibling) parent.insertBefore(node, afterNode.nextSibling);
  else parent.appendChild(node);
}

function injectCloneColumn() {
  const table = getTable();
  if (!table) return;

  const theadRow = table.tHead?.rows?.[0] || table.querySelector('thead tr');
  if (theadRow && !theadRow.querySelector('.col-clone')) {
    const th = document.createElement('th');
    th.textContent = '복제';
    th.className = 'col-clone';
    th.style.width = '58px';
    insertAfter(theadRow, th, theadRow.querySelector('.col-del'));
  }

  const tb = table.tBodies?.[0] || table.querySelector('tbody');
  if (!tb) return;

  Array.from(tb.rows).forEach((tr) => {
    if (tr.classList.contains('grp') || tr.querySelector('.btn-clone-stu')) return;

    const td = document.createElement('td');
    td.className = 'col-clone-cell';
    td.style.textAlign = 'center';

    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'btn-clone-stu';
    btn.title = '이름/학교/학년/레벨/독스만 복제';
    btn.textContent = '복제';
    btn.style.cssText = [
      'height:30px',
      'padding:0 8px',
      'border-radius:8px',
      'border:1px solid #93c5fd',
      'background:#eff6ff',
      'color:#1d4ed8',
      'cursor:pointer',
      'font-weight:800',
      'font-size:12px',
      'white-space:nowrap',
    ].join(';');

    const { sid } = parseRowInfo(tr);
    if (sid) btn.dataset.sid = sid;
    td.appendChild(btn);

    const delCell = tr.querySelector('.btn-del-stu')?.closest('td');
    insertAfter(tr, td, delCell);
  });
}

async function refreshAfterClone() {
  if (typeof onClonedCallback === 'function') {
    await onClonedCallback();
    return;
  }
  await loadAll();
}

export function hookCloneButtons({ onCloned } = {}) {
  onClonedCallback = onCloned || null;

  const tryOnce = () => {
    const t = getTable();
    if (!t) return false;
    injectCloneColumn();
    return true;
  };

  if (!tryOnce()) {
    const wrap = getWrap();
    const mo = new MutationObserver(() => {
      if (tryOnce()) mo.disconnect();
    });
    mo.observe(wrap, { childList: true, subtree: true });
  }

  if (delegated) return;
  delegated = true;
  document.addEventListener('click', async (e) => {
    const btn = e.target.closest('.btn-clone-stu');
    if (!btn) return;

    const tr = btn.closest('tr');
    const { sid, name } = parseRowInfo(tr);
    if (!sid) {
      alert('학생 ID를 찾을 수 없습니다.');
      return;
    }

    const stu = getStudents().find((s) => String(s.id) === String(sid));
    if (!stu) {
      alert('학생 정보를 찾지 못했습니다. 새로고침 후 다시 시도해 주세요.');
      return;
    }

    try {
      btn.disabled = true;
      btn.textContent = '중...';
      const res = await fetch('/api/add-student', {
        method: 'POST',
        headers: CT,
        credentials: 'same-origin',
        body: JSON.stringify(buildCloneBody(stu)),
      });
      if (!res.ok) throw new Error(String(res.status));

      await refreshAfterClone();
      if (window.toast) window.toast(`${name || stu.name || '학생'} 복제 완료`);
    } catch (err) {
      console.error('[clone student failed]', err);
      alert(`복제 실패: ${err?.message || err}`);
    } finally {
      btn.disabled = false;
      btn.textContent = '복제';
    }
  });
}
