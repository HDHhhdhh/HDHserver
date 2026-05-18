// /js/all/yoilStats.js
import { $ } from '../core/utils.js';
import { state } from '../core/state.js';
import { applySearchPlaceholder, matchesSearchKey, searchKeyForText } from '../../shared/search.js';

function escapeHtml(s = '') {
  return String(s)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function normText(v) {
  return String(v ?? '').trim();
}

function schoolForStudent(s) {
  return normText(
    s?.school ||
    s?.highSchool ||
    s?.schoolHigh ||
    s?.high ||
    s?.highschool ||
    s?.high_school ||
    s?.고등학교 ||
    s?.schoolMiddle ||
    s?.middle ||
    s?.middleschool ||
    s?.middle_school ||
    s?.중학교 ||
    ''
  );
}

function dedupKeyForStudent(s) {
  const name = normText(s?.name);
  const school = schoolForStudent(s);
  if (!name) return '';
  return `${name}::${school}`;
}

function studentListLine(rec) {
  const subjects = Array.from(rec.curricula).filter(Boolean).join(', ') || '-';
  return `${rec.name} - ${rec.grade} - ${subjects}`;
}

function compareSchoolGradeRows(a, b) {
  const schoolCmp = a.school.localeCompare(b.school, 'ko', { numeric: true });
  if (schoolCmp !== 0) return schoolCmp;
  return a.grade.localeCompare(b.grade, 'ko', { numeric: true });
}

function searchText(v) {
  return searchKeyForText(normText(v));
}

export function renderYoilStats() {
  // ── 요일/슬롯 집계 ─────────────────────────────────
  const YOILS = ['월', '화', '수', '목', '금', '토', '일'];
  const counts = Object.fromEntries(
    YOILS.flatMap(y => [`${y}1`, `${y}2`].map(k => [k, 0]))
  );
  const mapping = Object.fromEntries(Object.keys(counts).map(k => [k, []]));
  const dayKeys = ['day1', 'day2', 'day3', 'day4', 'day5'];

  const slotKeyFor = (stu, dayKey, raw) => {
    const text = String(raw || '').trim();
    const yoil = text.match(/[일월화수목금토]/)?.[0];
    if (!yoil) return '';

    const n = Number(text.match(/[1-3]/)?.[0] || 0);
    if (n === 1) return `${yoil}1`;
    if (n >= 2) return `${yoil}2`;

    const idx = String(dayKey || '').match(/[1-5]/)?.[0] || '';
    const visitTime = String(stu?.[`visitTime${idx}`] || '').trim();
    return visitTime.startsWith('13') ? `${yoil}1` : `${yoil}2`;
  };

  for (const s of state.students) {
    dayKeys.forEach(k => {
      const d = slotKeyFor(s, k, s[k]);
      if (d && counts[d] != null) {
        counts[d]++;
        mapping[d].push(s.name);
      }
    });
  }

  const host = $('yoilStats');
  if (!host) return;

  const yoilRow  = YOILS;
  const slotRow1 = yoilRow.map(y => `${y}1`);
  const slotRow2 = yoilRow.map(y => `${y}2`);

  const sumRow = yoilRow.map(y => {
    return (counts[`${y}1`] || 0) + (counts[`${y}2`] || 0);
  });
  const totalYoil = Object.values(counts).reduce((a, b) => a + b, 0);
  sumRow.push(totalYoil);

  // 안전하게 data-names 넣기
  const cellYoil = (key) => {
    const num = counts[key] || 0;
    const safe = encodeURIComponent(JSON.stringify(mapping[key] || []));
    return `
      <td class="yoil-cell"
          data-yoil="${key}"
          data-names="${safe}"
          style="border:1px solid #e5e7eb;padding:6px;cursor:pointer">
        ${num}
      </td>`;
  };

  const yoilTableHtml = `
    <table class="yoil-stats-table" style="border-collapse:collapse;text-align:center;width:100%;max-width:560px;border:2px solid #e5e7eb;margin-bottom:1rem">
      <tr>
        ${yoilRow.map(y => `<th style="border:1px solid #e5e7eb;padding:6px">${y}</th>`).join('')}
        <th>합계</th>
      </tr>
      <tr>${slotRow1.map(cellYoil).join('')}<td style="border:1px solid #e5e7eb;padding:6px;font-weight:600">${slotRow1.reduce((acc, key) => acc + (counts[key] || 0), 0)}</td></tr>
      <tr>${slotRow2.map(cellYoil).join('')}<td style="border:1px solid #e5e7eb;padding:6px;font-weight:600">${slotRow2.reduce((acc, key) => acc + (counts[key] || 0), 0)}</td></tr>
      <tr>
        ${sumRow.map(n => `
          <td style="border:1px solid #e5e7eb;padding:6px;font-weight:600">
            ${n}
          </td>`).join('')}
      </tr>
    </table>
  `;

  // ── 과목별 난이도 집계(상/중상/중/하) ──────────────────────
  const CURRICULUM_OPTIONS = ['공수1', '공수2', '대수', '미적분1', '미적분2', '기하', '확통'];
  const LEVELS = ['상', '중상', '중', '하'];
  const subjectStats = Object.fromEntries(CURRICULUM_OPTIONS.map(cur => [
    cur,
    {
      counts: Object.fromEntries(LEVELS.map(lv => [lv, 0])),
      mapping: Object.fromEntries(LEVELS.map(lv => [lv, []])),
    }
  ]));

  for (const s of state.students) {
    const cur = String(s.curriculum || '').trim();
    const lv = String(s.level || '').trim();
    if (!subjectStats[cur] || !LEVELS.includes(lv)) continue;
    subjectStats[cur].counts[lv]++;
    subjectStats[cur].mapping[lv].push(s.name);
  }

  const rowLevel = (cur, lv) => {
    const stat = subjectStats[cur];
    const num = stat.counts[lv] || 0;
    const safe = encodeURIComponent(JSON.stringify(stat.mapping[lv] || []));
    return `
      <tr class="level-row"
          data-curriculum="${cur}"
          data-level="${lv}"
          data-names="${safe}"
          style="cursor:pointer">
        <th style="text-align:left;border:1px solid #e5e7eb;padding:6px">${lv}</th>
        <td style="text-align:right;border:1px solid #e5e7eb;padding:6px;font-weight:600">${num}</td>
      </tr>`;
  };

  const levelTablesHtml = CURRICULUM_OPTIONS.map(cur => {
    const total = LEVELS.reduce((acc, lv) => acc + (subjectStats[cur].counts[lv] || 0), 0);
    return `
      <table class="subject-level-table" style="border-collapse:collapse;width:220px;border:2px solid #e5e7eb;margin:0">
        <caption style="caption-side:top;text-align:left;font-weight:800;margin:0 0 6px">${cur}</caption>
        <tr>
          <th style="text-align:left;border:1px solid #e5e7eb;padding:6px">난이도</th>
          <th style="text-align:right;border:1px solid #e5e7eb;padding:6px">학생 수</th>
        </tr>
        ${LEVELS.map(lv => rowLevel(cur, lv)).join('')}
        <tr>
          <td style="text-align:left;border:1px solid #e5e7eb;padding:6px">합계</td>
          <td style="text-align:right;border:1px solid #e5e7eb;padding:6px;font-weight:700">${total}</td>
        </tr>
      </table>`;
  }).join('');

  // ── 학교/학년별 고유 학생 집계 ─────────────────────────────
  const uniqueStudents = new Map();
  for (const s of state.students) {
    const key = dedupKeyForStudent(s);
    if (!key) continue;

    const name = normText(s.name);
    const school = schoolForStudent(s) || '미입력';
    const grade = normText(s.grade) || '미입력';
    const cur = normText(s.curriculum);

    if (!uniqueStudents.has(key)) {
      uniqueStudents.set(key, {
        name,
        school,
        grade,
        curricula: new Set(),
      });
    }

    const rec = uniqueStudents.get(key);
    if (rec.grade === '미입력' && grade !== '미입력') rec.grade = grade;
    if (cur) rec.curricula.add(cur);
  }

  const schoolMap = new Map();
  const schoolGradeMap = new Map();
  for (const rec of uniqueStudents.values()) {
    if (!schoolMap.has(rec.school)) schoolMap.set(rec.school, []);
    schoolMap.get(rec.school).push(rec);

    const rowKey = `${rec.school}::${rec.grade}`;
    if (!schoolGradeMap.has(rowKey)) {
      schoolGradeMap.set(rowKey, {
        school: rec.school,
        grade: rec.grade,
        students: [],
      });
    }
    schoolGradeMap.get(rowKey).students.push(rec);
  }

  const listPayload = (records) => encodeURIComponent(JSON.stringify(
    records
      .slice()
      .sort((a, b) => a.name.localeCompare(b.name, 'ko', { numeric: true }))
      .map(studentListLine)
  ));

  const schoolGradeRows = Array.from(schoolGradeMap.values()).sort(compareSchoolGradeRows);
  const schoolGradeRowsHtml = schoolGradeRows.length
    ? schoolGradeRows.map(row => {
      const schoolRecords = schoolMap.get(row.school) || [];
      const gradeRecords = row.students || [];
      return `
        <tr class="school-grade-row" data-school-search="${escapeHtml(searchText(row.school))}">
          <td class="school-grade-cell"
              data-title="${escapeHtml(row.school)}"
              data-names="${listPayload(schoolRecords)}"
              style="border:1px solid #e5e7eb;padding:7px;cursor:pointer;color:#2563eb;font-weight:700">
            ${escapeHtml(row.school)}
          </td>
          <td class="school-grade-cell"
              data-title="${escapeHtml(row.school)} ${escapeHtml(row.grade)}"
              data-names="${listPayload(gradeRecords)}"
              style="border:1px solid #e5e7eb;padding:7px;cursor:pointer;color:#2563eb;font-weight:700">
            ${escapeHtml(row.grade)}
          </td>
          <td style="border:1px solid #e5e7eb;padding:7px;text-align:right;font-weight:700">
            ${gradeRecords.length}
          </td>
        </tr>`;
    }).join('')
    : '<tr><td colspan="3" style="border:1px solid #e5e7eb;padding:12px;text-align:center;opacity:.7">표시할 학생이 없습니다.</td></tr>';

  const schoolGradeTableHtml = `
    <div class="school-grade-stats" style="margin-top:1.1rem">
      <h3 style="margin:.2rem 0 .4rem 0; font-size:14px; opacity:.75">학교/학년별 학생 수</h3>
      <div style="max-height:260px;overflow:auto;border:2px solid #e5e7eb;border-radius:8px;background:#fff">
        <table class="school-grade-table" style="border-collapse:collapse;width:100%;min-width:420px">
          <thead>
            <tr>
              <th style="position:sticky;top:0;z-index:1;text-align:left;border:1px solid #e5e7eb;padding:7px;background:#f8fafc">
                <div style="font-weight:800;margin-bottom:6px">학교</div>
                <input class="school-grade-search"
                       type="search"
                       placeholder="학교 검색"
                       aria-label="학교 검색"
                       style="width:100%;height:28px;box-sizing:border-box;border:1px solid #cbd5e1;border-radius:7px;padding:0 8px;background:#fff;color:#0f172a">
              </th>
              <th style="position:sticky;top:0;z-index:1;text-align:left;border:1px solid #e5e7eb;padding:7px;background:#f8fafc">학년</th>
              <th style="position:sticky;top:0;z-index:1;text-align:right;border:1px solid #e5e7eb;padding:7px;background:#f8fafc">학생 수</th>
            </tr>
          </thead>
          <tbody>${schoolGradeRowsHtml}</tbody>
        </table>
      </div>
    </div>`;

  // ── 통계 표를 가로 배치 ────────────────────────────────────
  host.innerHTML = `
    <div id="yoilStatsInner"
         style="display:flex; gap:28px; align-items:flex-start; flex-wrap:wrap">
      <section style="flex:0 0 560px; min-width:300px">
        <h3 style="margin:.2rem 0 .4rem 0; font-size:14px; opacity:.75">요일별 학생 수</h3>
        ${yoilTableHtml}
        ${schoolGradeTableHtml}
      </section>
      <section style="flex:1 1 860px; min-width:300px">
        <h3 style="margin:.2rem 0 .6rem 0; font-size:14px; opacity:.75">과목별 난이도 학생 수</h3>
        <div style="display:flex;gap:18px;flex-wrap:wrap;align-items:flex-start">
          ${levelTablesHtml}
        </div>
      </section>
    </div>`;

  // 렌더마다 클릭 핸들러를 다시 붙이지 않도록 플래그 체크
  const inner = document.getElementById('yoilStatsInner');
  if (inner && !inner._yoilBound) {
    inner._yoilBound = true;
    bindYoilClick(inner);
  }

  // 모달도 이 시점에서 보장
  ensureYoilModal();
}

// ── 모달 DOM 만들기 ─────────────────────────────────
let _yoilModal = null;
let _yoilTitle = null;
let _yoilList  = null;

function ensureYoilModal() {
  if (_yoilModal) return;

  if (!document.body) return; // 아주 이른 시점 보호

  if (!document.getElementById('yoilModal')) {
    document.body.insertAdjacentHTML('beforeend', `
      <div id="yoilModal"
           style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.45);justify-content:center;align-items:center;z-index:99999">
        <div style="background:#fff;padding:1rem;border-radius:10px;width:280px;max-height:80%;overflow:auto;color:#111">
          <div id="yoilTitle" style="font-weight:700;margin-bottom:.5rem"></div>
          <div id="yoilList"
               style="white-space:pre-line;min-height:200px;border:1px solid #eee;border-radius:6px;padding:8px"></div>
          <div style="text-align:right;margin-top:.8rem">
            <button id="yoilClose"
                    style="background:#3b82f6;color:#fff;border:none;padding:6px 12px;border-radius:6px">
              닫기
            </button>
          </div>
        </div>
      </div>
    `);
  }

  _yoilModal = document.getElementById('yoilModal');
  _yoilTitle = document.getElementById('yoilTitle');
  _yoilList  = document.getElementById('yoilList');

  if (!_yoilModal) return;

  if (!_yoilModal.dataset.bound) {
    _yoilModal.dataset.bound = '1';
    _yoilModal.addEventListener('click', (e) => {
      if (e.target.id === 'yoilClose' || e.target === _yoilModal) {
        _yoilModal.style.display = 'none';
      }
    });
  }
}

function openYoilModal(title, names, opts = {}) {
  ensureYoilModal();
  if (!_yoilModal || !_yoilTitle || !_yoilList) return;

  _yoilTitle.textContent = `${title} – ${names.length}명`;
  _yoilList.textContent  = names.join('\n');
  _yoilList.style.fontSize = opts.largeList ? '18.2px' : '14px';
  _yoilList.style.lineHeight = opts.largeList ? '1.55' : '1.45';
  _yoilModal.style.display = 'flex';
}

// ── 클릭 위임 핸들러 ─────────────────────────────────
function bindYoilClick(container) {
  container.addEventListener('click', (e) => {
    // 요일 셀
    const yoilCell = e.target.closest('.yoil-cell');
    if (yoilCell) {
      let names = [];
      try {
        names = JSON.parse(decodeURIComponent(yoilCell.dataset.names || '[]'));
      } catch {
        names = [];
      }
      const t = yoilCell.dataset.yoil || '';
      openYoilModal(t, names);
      return;
    }

    // 난이도 행
    const levelRow = e.target.closest('.level-row');
    if (levelRow) {
      let names = [];
      try {
        names = JSON.parse(decodeURIComponent(levelRow.dataset.names || '[]'));
      } catch {
        names = [];
      }
      const cur = levelRow.dataset.curriculum || '';
      const lv = levelRow.dataset.level || '';
      openYoilModal(`${cur} 난이도 ${lv}`, names);
      return;
    }

    // 학교/학년별 집계 셀
    const schoolGradeCell = e.target.closest('.school-grade-cell');
    if (schoolGradeCell) {
      let names = [];
      try {
        names = JSON.parse(decodeURIComponent(schoolGradeCell.dataset.names || '[]'));
      } catch {
        names = [];
      }
      openYoilModal(schoolGradeCell.dataset.title || '학생 명단', names, { largeList: true });
    }
  });

  container.addEventListener('input', (e) => {
    const search = e.target.closest('.school-grade-search');
    if (!search) return;
    applySearchPlaceholder(search, '학교/학년 검색');

    container.querySelectorAll('.school-grade-row').forEach(row => {
      const school = row.dataset.schoolSearch || '';
      row.style.display = matchesSearchKey(school, search.value) ? '' : 'none';
    });
  });

  container.querySelectorAll('.school-grade-search').forEach(input => {
    applySearchPlaceholder(input, '학교/학년 검색');
  });
}
