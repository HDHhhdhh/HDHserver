import {
  getActiveSchoolCalendarYear,
  getSchoolCalendarSchoolMap,
  isSchoolCalendarV2,
} from './shared/schoolCalendar.js';

(() => {
  const CT = { 'Content-Type': 'application/json' };
  const SCHEDULE_KEYS = [
    'textbook',
    'semesterStart',
    'midterm',
    'midtermMath',
    'midtermRange',
    'midtermNote',
    'final',
    'finalMath',
    'finalRange',
    'finalNote',
  ];
  const GRADE_PHASE_DELIM = '::';

  const table = document.getElementById('calTable');
  const theadTr = document.getElementById('theadRow');
  const addBtn = document.getElementById('addRow');
  const saveBtn = document.getElementById('saveBtn');
  const statusEl = document.getElementById('status');
  const seg = document.getElementById('viewSeg');
  if (!table || !theadTr || !addBtn || !saveBtn || !statusEl || !seg) return;

  const tbody = table.querySelector('tbody');
  if (!tbody) return;
  const tableNoteEl = document.querySelector('.table-note');

  let calendarDoc = {};
  let schoolsData = [];
  let editingYear = String(new Date().getFullYear());
  let viewMode = 'mid';
  let autoSaveTimer = null;
  let lastSavedSnapshot = '';
  let schoolSeq = 1;
  let gradeSeq = 1;
  const expandedSchoolIds = new Set();

  (function injectStyle() {
    const css = `
      #wrap { overflow: auto; }
      #calTable {
        table-layout: auto;
        width: max(1120px, 100%);
        min-width: 1120px;
      }
      #calTable th, #calTable td {
        padding: 10px 8px;
        vertical-align: middle;
        font-size: 13px;
      }
      #calTable td { white-space: normal; }
      #calTable tbody tr:hover td {
        background: #eef6ff;
      }
      #calTable th:nth-child(1),
      #calTable td:nth-child(1) {
        position: sticky;
        left: 0;
        z-index: 6;
        background: #f3f8ff;
      }
      #calTable th:nth-child(2),
      #calTable td:nth-child(2) {
        position: sticky;
        left: 86px;
        z-index: 5;
        background: #f8fbff;
      }
      #calTable thead th:nth-child(1),
      #calTable thead th:nth-child(2) {
        z-index: 12;
      }
      .school-row td {
        border-top: 2px solid #d8e7fb;
      }
      #calTable input[type="text"] {
        width: 100%;
        min-width: 0;
        height: 38px;
        box-sizing: border-box;
        padding: 0 10px;
        border: 1px solid #c5d4e7;
        border-radius: 9px;
        background: #fff;
        line-height: 1.35;
        font-size: 13px;
      }
      #calTable input[type="text"]:focus {
        outline: none;
        border-color: #3b82f6;
        box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.2);
      }
      .btn-del {
        width: 30px;
        height: 30px;
        border-radius: 8px;
        cursor: pointer;
        border: 1px solid #cbd5e1;
        background: #fff;
      }
      .btn-toggle, .btn-add-grade {
        border: 1px solid #cbd5e1;
        border-radius: 8px;
        background: #f8fafc;
        cursor: pointer;
        color: #1f2937;
      }
      .btn-toggle { width: 30px; height: 30px; font-size: 12px; }
      .btn-add-grade {
        padding: 0 10px;
        font-size: 12px;
        font-weight: 700;
        height: 30px;
      }
      .school-name-wrap { display: grid; grid-template-columns: 1fr auto; gap: 6px; align-items: center; }
      .common-chip {
        display:inline-block;
        border:1px solid #cbd5e1;
        border-radius:999px;
        padding:4px 9px;
        font-size:12px;
        font-weight: 700;
        color:#475569;
        background:#f8fafc;
      }
      .grade-row td { background: #f8fafc; }
      .grade-hint {
        color:#475569;
        font-size:12px;
        font-weight: 700;
      }
      .row-index-wrap {
        display:flex;
        align-items:center;
        justify-content:center;
        gap:6px;
        white-space: nowrap;
      }
      body.dark .btn-toggle, body.dark .btn-add-grade {
        background:#0b1220;
        border-color:#334155;
        color:#e2e8f0;
      }
      body.dark .btn-del {
        background:#0b1220;
        border-color:#334155;
        color:#e2e8f0;
      }
      body.dark .common-chip {
        border-color:#334155;
        color:#cbd5e1;
        background:#0b1220;
      }
      body.dark .grade-row td { background:#111827; }
      body.dark .grade-hint { color:#cbd5e1; }
      body.dark #calTable tbody tr:hover td {
        background: #14243b;
      }
      body.dark #calTable th:nth-child(1),
      body.dark #calTable td:nth-child(1) {
        background:#13263f;
      }
      body.dark #calTable th:nth-child(2),
      body.dark #calTable td:nth-child(2) {
        background:#152b46;
      }
      body.dark .school-row td {
        border-top-color: #2a4a74;
      }
      body.dark #calTable input[type="text"] {
        background:#0b1220;
        border-color:#334155;
        color:#e2e8f0;
      }
      body.dark #calTable input[type="text"]:focus {
        border-color:#60a5fa;
        box-shadow: 0 0 0 3px rgba(96, 165, 250, 0.28);
      }
    `;
    const s = document.createElement('style');
    s.textContent = css;
    document.head.appendChild(s);
  })();

  function isObject(value) {
    return value && typeof value === 'object' && !Array.isArray(value);
  }

  function esc(value) {
    return String(value ?? '').replace(/[&<>"']/g, (m) => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#39;',
    }[m]));
  }

  function nextSchoolId() {
    const id = `s${schoolSeq}`;
    schoolSeq += 1;
    return id;
  }

  function nextGradeId() {
    const id = `g${gradeSeq}`;
    gradeSeq += 1;
    return id;
  }

  function normalizeScheduleFields(entry = {}) {
    const out = {};
    for (const key of SCHEDULE_KEYS) {
      out[key] = String(entry?.[key] ?? '').trim();
    }
    return out;
  }

  function hasScheduleValue(entry = {}) {
    return SCHEDULE_KEYS.some((key) => String(entry?.[key] ?? '').trim());
  }

  function parseGradeToken(rawKey, gradeEntry = {}) {
    const key = String(rawKey ?? '').trim();
    const explicitGrade = String(gradeEntry?.__grade ?? '').trim();
    const explicitPhase = String(gradeEntry?.__phase ?? '').trim();

    if (explicitGrade || explicitPhase) {
      return {
        grade: explicitGrade || key,
        phase: explicitPhase,
      };
    }

    const idx = key.indexOf(GRADE_PHASE_DELIM);
    if (idx < 0) {
      return { grade: key, phase: '' };
    }

    return {
      grade: key.slice(0, idx).trim(),
      phase: key.slice(idx + GRADE_PHASE_DELIM.length).trim(),
    };
  }

  function cloneSchoolEntry(school) {
    return {
      id: school.id,
      school: String(school.school || '').trim(),
      common: normalizeScheduleFields(school.common || {}),
      grades: (school.grades || []).map((gradeRow) => ({
        id: gradeRow.id || nextGradeId(),
        grade: String(gradeRow.grade || '').trim(),
        phase: String(gradeRow.phase || '').trim(),
        fields: normalizeScheduleFields(gradeRow.fields || {}),
      })),
    };
  }

  function sortLoadedSchools(rows) {
    return [...rows].sort((a, b) => String(a.school || '').localeCompare(String(b.school || ''), 'ko'));
  }

  function loadSchoolsFromDoc(payload, year) {
    const schoolMap = getSchoolCalendarSchoolMap(payload, year);
    const rows = [];

    for (const [schoolName, entry] of Object.entries(schoolMap)) {
      if (!isObject(entry)) continue;

      if (!isObject(entry.common) && !isObject(entry.grades)) {
        rows.push({
          id: nextSchoolId(),
          school: schoolName,
          common: normalizeScheduleFields(entry),
          grades: [],
        });
        continue;
      }

      const common = normalizeScheduleFields(isObject(entry.common) ? entry.common : {});
      const grades = [];

      const rawGrades = isObject(entry.grades) ? entry.grades : {};
      Object.entries(rawGrades).forEach(([gradeKey, gradeEntry]) => {
        if (!isObject(gradeEntry)) return;
        const token = parseGradeToken(gradeKey, gradeEntry);
        const fields = normalizeScheduleFields(gradeEntry);
        const hasMeta = token.grade || token.phase;
        if (!hasMeta && !hasScheduleValue(fields)) return;
        grades.push({
          id: nextGradeId(),
          grade: token.grade,
          phase: token.phase,
          fields,
        });
      });

      grades.sort((a, b) => {
        const gCmp = String(a.grade || '').localeCompare(String(b.grade || ''), 'ko');
        if (gCmp !== 0) return gCmp;
        return String(a.phase || '').localeCompare(String(b.phase || ''), 'ko');
      });

      const schoolId = nextSchoolId();
      rows.push({
        id: schoolId,
        school: schoolName,
        common,
        grades,
      });
      if (grades.length > 0) {
        expandedSchoolIds.add(schoolId);
      }
    }

    return sortLoadedSchools(rows);
  }

  function updateTitle() {
    document.title = editingYear ? `학교 일정 관리 (${editingYear})` : '학교 일정 관리';
  }

  function applyColgroup() {
    const widths = ['86px', '220px', '110px', '150px', '120px', '10.5rem', '12rem', '62px'];
    table.querySelector('colgroup')?.remove();
    const cg = document.createElement('colgroup');
    cg.innerHTML = widths.map((w) => (w ? `<col style="width:${w}">` : '<col>')).join('');
    table.insertBefore(cg, table.firstElementChild);
  }

  function renderHead() {
    const dynamicCols = [[viewMode === 'mid' ? '중간 수학시험일' : '기말 수학시험일', '12rem']];

    const cols = [
      ['열기/#', '86px'],
      ['학교명', '220px'],
      ['학년', '110px'],
      ['과목/트랙', '150px'],
      ['교과서', '120px'],
      ['개학(날짜)', '10.5rem'],
      ...dynamicCols,
      ['삭제', '62px'],
    ];

    theadTr.innerHTML = cols.map(([label, width]) => `<th style="${width ? `width:${width}` : ''}">${label}</th>`).join('');
    applyColgroup();
  }

  function buildModeCells(prefix, fields = {}, placeholders = {}) {
    if (viewMode === 'mid') {
      return `
        <td><input type="text" class="${prefix}-mid-math" value="${esc(fields.midtermMath || '')}" placeholder="${esc(placeholders.midtermMath || '예: 4/30(목), 5/1(금)')}"></td>
      `;
    }

    return `
      <td><input type="text" class="${prefix}-fin-math" value="${esc(fields.finalMath || '')}" placeholder="${esc(placeholders.finalMath || '예: 6/26(목), 6/27(금)')}"></td>
    `;
  }

  function buildSchoolRow(school, index) {
    const expanded = expandedSchoolIds.has(school.id);
    return `
      <tr class="school-row" data-school-id="${esc(school.id)}">
        <td>
          <div class="row-index-wrap">
            <button type="button" class="btn-toggle" data-action="toggle-school" title="학년 행 펼치기">${expanded ? '▼' : '▶'}</button>
            <span>${index}</span>
          </div>
        </td>
        <td>
          <div class="school-name-wrap">
            <input type="text" class="inp-school" value="${esc(school.school || '')}" placeholder="학교명">
            <button type="button" class="btn-add-grade" data-action="add-grade" title="학년 행 추가">+학년</button>
          </div>
        </td>
        <td><span class="common-chip">공통</span></td>
        <td><span class="grade-hint">-</span></td>
        <td><input type="text" class="sc-textbook" value="${esc(school.common.textbook || '')}" placeholder="예: YBM"></td>
        <td><input type="text" class="sc-sem" value="${esc(school.common.semesterStart || '')}" placeholder="예: 3/4(화)"></td>
        ${buildModeCells('sc', school.common)}
        <td style="text-align:center"><button type="button" class="btn-del" title="학교 삭제">X</button></td>
      </tr>
    `;
  }

  function buildGradeRow(school, gradeRow) {
    const placeholders = {
      midterm: school.common.midterm,
      midtermMath: school.common.midtermMath,
      midtermRange: school.common.midtermRange,
      midtermNote: school.common.midtermNote,
      final: school.common.final,
      finalMath: school.common.finalMath,
      finalRange: school.common.finalRange,
      finalNote: school.common.finalNote,
    };

    return `
      <tr class="grade-row" data-school-id="${esc(school.id)}" data-grade-id="${esc(gradeRow.id)}">
        <td><span class="grade-hint">└&gt;</span></td>
        <td><span class="grade-hint">학년별</span></td>
        <td><input type="text" class="gr-grade" value="${esc(gradeRow.grade || '')}" placeholder="예: 1학년"></td>
        <td><input type="text" class="gr-phase" value="${esc(gradeRow.phase || '')}" placeholder="예: 수학1 / 미적분"></td>
        <td><input type="text" class="gr-textbook" value="${esc(gradeRow.fields.textbook || '')}" placeholder="${esc(placeholders.textbook || '')}"></td>
        <td><input type="text" class="gr-sem" value="${esc(gradeRow.fields.semesterStart || '')}" placeholder="${esc(placeholders.semesterStart || '')}"></td>
        ${buildModeCells('gr', gradeRow.fields, placeholders)}
        <td style="text-align:center"><button type="button" class="btn-del" title="학년 행 삭제">X</button></td>
      </tr>
    `;
  }

  function ensureAtLeastOneSchool() {
    if (schoolsData.length) return;
    schoolsData.push({
      id: nextSchoolId(),
      school: '',
      common: normalizeScheduleFields({}),
      grades: [],
    });
  }

  function renderBody() {
    ensureAtLeastOneSchool();

    const chunks = [];
    schoolsData.forEach((school, index) => {
      chunks.push(buildSchoolRow(school, index + 1));
      if (!expandedSchoolIds.has(school.id)) return;
      school.grades.forEach((gradeRow) => {
        chunks.push(buildGradeRow(school, gradeRow));
      });
    });

    tbody.innerHTML = chunks.join('');
  }

  function render() {
    updateTitle();
    renderHead();
    renderBody();
  }

  function readModeFieldsFromRow(rowEl, prefix) {
    if (viewMode === 'mid') {
      return {
        midtermMath: rowEl.querySelector(`.${prefix}-mid-math`)?.value.trim() || '',
      };
    }

    return {
      finalMath: rowEl.querySelector(`.${prefix}-fin-math`)?.value.trim() || '',
    };
  }

  function syncFromView() {
    const prevMap = new Map(schoolsData.map((s) => [s.id, cloneSchoolEntry(s)]));
    const prevGradeMapBySchool = new Map();
    prevMap.forEach((school) => {
      const gmap = new Map();
      (school.grades || []).forEach((g) => gmap.set(g.id, g));
      prevGradeMapBySchool.set(school.id, gmap);
    });

    const next = [];
    const nextById = new Map();

    tbody.querySelectorAll('tr.school-row').forEach((tr) => {
      const schoolId = tr.dataset.schoolId;
      const prev = prevMap.get(schoolId) || {
        id: schoolId,
        school: '',
        common: normalizeScheduleFields({}),
        grades: [],
      };

      const commonPatch = {
        textbook: tr.querySelector('.sc-textbook')?.value.trim() || '',
        semesterStart: tr.querySelector('.sc-sem')?.value.trim() || '',
        ...readModeFieldsFromRow(tr, 'sc'),
      };

      const school = {
        id: schoolId,
        school: tr.querySelector('.inp-school')?.value.trim() || prev.school || '',
        common: normalizeScheduleFields({ ...prev.common, ...commonPatch }),
        grades: expandedSchoolIds.has(schoolId) ? [] : (prev.grades || []),
      };

      next.push(school);
      nextById.set(schoolId, school);
    });

    tbody.querySelectorAll('tr.grade-row').forEach((tr) => {
      const schoolId = tr.dataset.schoolId;
      const school = nextById.get(schoolId);
      if (!school) return;

      const gradeId = tr.dataset.gradeId || nextGradeId();
      const prevGrade = prevGradeMapBySchool.get(schoolId)?.get(gradeId);
      const grade = tr.querySelector('.gr-grade')?.value.trim() || '';
      const phase = tr.querySelector('.gr-phase')?.value.trim() || String(prevGrade?.phase || '').trim();
      const fieldsPatch = {
        textbook: tr.querySelector('.gr-textbook')?.value.trim() || '',
        semesterStart: tr.querySelector('.gr-sem')?.value.trim() || '',
        ...readModeFieldsFromRow(tr, 'gr'),
      };
      const fields = normalizeScheduleFields({ ...(prevGrade?.fields || {}), ...fieldsPatch });

      if (!grade && !phase && !hasScheduleValue(fields)) return;

      school.grades.push({ id: gradeId, grade, phase, fields });
    });

    schoolsData = next;
    ensureAtLeastOneSchool();
  }

  function scheduleAutoSave() {
    if (autoSaveTimer) clearTimeout(autoSaveTimer);
    autoSaveTimer = setTimeout(() => {
      autoSaveTimer = null;
      saveCalendar('auto');
    }, 800);
  }

  function buildPayloadFromState() {
    const activeYear = String(editingYear || getActiveSchoolCalendarYear(calendarDoc) || new Date().getFullYear());
    const existingSchools = getSchoolCalendarSchoolMap(calendarDoc, activeYear);
    const schools = {};

    schoolsData.forEach((schoolEntry) => {
      const schoolName = String(schoolEntry.school || '').trim();
      if (!schoolName) return;

      const existing = isObject(existingSchools[schoolName]) ? { ...existingSchools[schoolName] } : {};
      delete existing.common;
      delete existing.grades;

      const grades = {};
      (schoolEntry.grades || []).forEach((gradeRow) => {
        const grade = String(gradeRow.grade || '').trim();
        const phase = String(gradeRow.phase || '').trim();
        const fields = normalizeScheduleFields(gradeRow.fields || {});

        if (!grade && !phase && !hasScheduleValue(fields)) return;
        if (!grade) return;

        const key = phase ? `${grade}${GRADE_PHASE_DELIM}${phase}` : grade;
        if (!key) return;

        grades[key] = {
          ...fields,
          __grade: grade,
          __phase: phase,
        };
      });

      schools[schoolName] = {
        ...existing,
        common: normalizeScheduleFields(schoolEntry.common || {}),
        grades,
      };
    });

    const base = isSchoolCalendarV2(calendarDoc) ? calendarDoc : {};
    const years = { ...(base.years || {}) };
    const yearBundle = isObject(years[activeYear]) ? years[activeYear] : {};
    years[activeYear] = { ...yearBundle, schools };

    return {
      ...base,
      version: 2,
      activeYear,
      years,
    };
  }

  async function saveCalendar(mode = 'manual') {
    if (autoSaveTimer) {
      clearTimeout(autoSaveTimer);
      autoSaveTimer = null;
    }

    syncFromView();
    const payload = buildPayloadFromState();
    const snapshot = JSON.stringify(payload);

    if (statusEl) {
      if (mode === 'auto') statusEl.textContent = '자동 저장 중...';
      else if (mode === 'manual') statusEl.textContent = '저장 중...';
    }

    try {
      const res = await fetch('/api/school-calendar', {
        method: 'POST',
        headers: CT,
        body: snapshot,
        keepalive: mode === 'flush',
      });
      if (!res.ok) throw new Error(String(res.status));

      calendarDoc = payload;
      lastSavedSnapshot = snapshot;

      if (statusEl) {
        statusEl.textContent = mode === 'auto' ? '자동 저장됨' : '저장됨';
        if (mode !== 'flush') {
          setTimeout(() => {
            if (statusEl.textContent.includes('저장')) statusEl.textContent = '';
          }, 1500);
        }
      }
    } catch (err) {
      console.error('saveCalendar failed', err);
      if (statusEl) {
        statusEl.textContent = mode === 'auto' ? '자동 저장 실패' : '저장 실패';
      }
      if (mode === 'manual') {
        alert(`저장 실패: ${err.message}`);
      }
    }
  }

  function flushCalendarSave() {
    syncFromView();
    const snapshot = JSON.stringify(buildPayloadFromState());
    if (snapshot === lastSavedSnapshot) return;
    saveCalendar('flush');
  }

  function addSchoolRow() {
    syncFromView();
    const newSchool = {
      id: nextSchoolId(),
      school: '',
      common: normalizeScheduleFields({}),
      grades: [],
    };
    schoolsData.push(newSchool);
    render();
    const row = tbody.querySelector(`tr.school-row[data-school-id="${newSchool.id}"] .inp-school`);
    row?.focus();
    scheduleAutoSave();
  }

  function addGradeRow(schoolId) {
    syncFromView();
    const school = schoolsData.find((row) => row.id === schoolId);
    if (!school) return;

    expandedSchoolIds.add(schoolId);
    const newGrade = {
      id: nextGradeId(),
      grade: '',
      phase: '',
      fields: normalizeScheduleFields({}),
    };
    school.grades.push(newGrade);

    render();
    const input = tbody.querySelector(`tr.grade-row[data-grade-id="${newGrade.id}"] .gr-grade`);
    input?.focus();
    scheduleAutoSave();
  }

  function removeSchoolRow(schoolId) {
    syncFromView();
    schoolsData = schoolsData.filter((row) => row.id !== schoolId);
    expandedSchoolIds.delete(schoolId);
    ensureAtLeastOneSchool();
    render();
    scheduleAutoSave();
  }

  function removeGradeRow(schoolId, gradeId) {
    syncFromView();
    const school = schoolsData.find((row) => row.id === schoolId);
    if (!school) return;
    school.grades = (school.grades || []).filter((row) => row.id !== gradeId);
    render();
    scheduleAutoSave();
  }

  function toggleSchoolRow(schoolId) {
    syncFromView();
    if (expandedSchoolIds.has(schoolId)) expandedSchoolIds.delete(schoolId);
    else expandedSchoolIds.add(schoolId);
    render();
  }

  seg.addEventListener('click', (e) => {
    const btn = e.target.closest('button[data-mode]');
    if (!btn) return;
    const mode = btn.dataset.mode;
    if (viewMode === mode) return;

    syncFromView();
    viewMode = mode;
    seg.querySelectorAll('button').forEach((b) => b.classList.toggle('active', b === btn));
    render();
    scheduleAutoSave();
  });

  addBtn.addEventListener('click', addSchoolRow);

  saveBtn.addEventListener('click', () => {
    saveCalendar('manual');
  });

  tbody.addEventListener('click', (e) => {
    const toggleBtn = e.target.closest('.btn-toggle');
    if (toggleBtn) {
      const schoolId = toggleBtn.closest('tr.school-row')?.dataset.schoolId;
      if (schoolId) toggleSchoolRow(schoolId);
      return;
    }

    const addGradeBtn = e.target.closest('.btn-add-grade');
    if (addGradeBtn) {
      const schoolId = addGradeBtn.closest('tr.school-row')?.dataset.schoolId;
      if (schoolId) addGradeRow(schoolId);
      return;
    }

    const delBtn = e.target.closest('.btn-del');
    if (!delBtn) return;

    const gradeRow = delBtn.closest('tr.grade-row');
    if (gradeRow) {
      const schoolId = gradeRow.dataset.schoolId;
      const gradeId = gradeRow.dataset.gradeId;
      if (schoolId && gradeId) removeGradeRow(schoolId, gradeId);
      return;
    }

    const schoolRow = delBtn.closest('tr.school-row');
    if (schoolRow) {
      const schoolId = schoolRow.dataset.schoolId;
      if (schoolId) removeSchoolRow(schoolId);
    }
  });

  tbody.addEventListener('input', (e) => {
    if (!(e.target instanceof HTMLInputElement)) return;
    if (e.target.type !== 'text') return;
    scheduleAutoSave();
  });

  tbody.addEventListener('keydown', (e) => {
    if (e.key !== 'Enter') return;
    e.preventDefault();
    const inputs = [...tbody.querySelectorAll('input[type="text"]')];
    const idx = inputs.indexOf(e.target);
    (e.shiftKey ? inputs[idx - 1] : inputs[idx + 1])?.focus();
  });

  window.addEventListener('beforeunload', flushCalendarSave);
  window.addEventListener('pagehide', flushCalendarSave, { capture: true });
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') flushCalendarSave();
  });

  (async function init() {
    try {
      const data = await fetch('/api/school-calendar', { cache: 'no-store' }).then((r) => r.json());
      calendarDoc = (data && typeof data === 'object') ? data : {};
    } catch {
      calendarDoc = {};
    }

    editingYear = getActiveSchoolCalendarYear(calendarDoc) || String(calendarDoc.activeYear || new Date().getFullYear());
    schoolsData = loadSchoolsFromDoc(calendarDoc, editingYear);
    ensureAtLeastOneSchool();
    lastSavedSnapshot = JSON.stringify(buildPayloadFromState());
    if (tableNoteEl) {
      tableNoteEl.textContent = '가독성을 위해 수학시험일 중심으로 편집합니다. (중간/기말 탭에서 각각 입력)';
    }
    render();
  })();
})();
