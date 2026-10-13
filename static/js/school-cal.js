import {
  applySearchPlaceholder,
  matchesSearchKey,
  searchKeyForText,
} from './shared/search.js';
import { createSchoolCalendarPersistence } from './school-calendar/persistence.js';
import {
  buildSchoolCalendarDocument,
  cloneSchoolCalendarRow,
  coerceSchoolCalendarExam as coerceExam,
  coerceSchoolCalendarSemester as coerceSemester,
  getSchoolCalendarYearBundle as getYearBundle,
  hasSchoolCalendarScheduleValue as hasScheduleValue,
  isSchoolCalendarRecord as isObject,
  loadSchoolCalendarRows,
  normalizeSchoolCalendarCommon as normalizeCommonFields,
  normalizeSchoolCalendarGrade as normalizeGradeFields,
  resolveSchoolCalendarPageSelection,
  withActiveSchoolCalendarPage,
} from './school-calendar/state.js';

(() => {
  const PAGE_STORAGE_KEY = 'schoolCal.selectedPage.v1';
  const DEFAULT_EXAM = 'final';
  const EXAMS = {
    mid: {
      label: '중간고사',
      periodLabel: '중간 지필고사 기간',
      mathLabel: '중간 수학시험일',
      period: 'midterm',
      math: 'midtermMath',
      note: 'midtermNote',
    },
    final: {
      label: '기말고사',
      periodLabel: '기말 지필고사 기간',
      mathLabel: '기말 수학시험일',
      period: 'final',
      math: 'finalMath',
      note: 'finalNote',
    },
  };

  const table = document.getElementById('calTable');
  const theadTr = document.getElementById('theadRow');
  const addBtn = document.getElementById('addRow');
  const saveBtn = document.getElementById('saveBtn');
  const statusEl = document.getElementById('status');
  const yearSelect = document.getElementById('yearSelect');
  const semesterSelect = document.getElementById('semesterSelect');
  const examSelect = document.getElementById('examSelect');
  const searchInput = document.getElementById('calSearch');
  const searchStatusEl = document.getElementById('searchStatus');
  applySearchPlaceholder(searchInput, '학교/과목/교과서 검색');
  if (!table || !theadTr || !addBtn || !saveBtn || !statusEl || !yearSelect || !semesterSelect || !examSelect) return;

  const tbody = table.querySelector('tbody');
  if (!tbody) return;
  const tableNoteEl = document.querySelector('.table-note');

  let calendarDoc = {};
  let schoolsData = [];
  let editingYear = String(new Date().getFullYear());
  let editingSemester = '1';
  let viewMode = DEFAULT_EXAM;
  let searchQuery = '';
  let autoSaveTimer = null;
  let lastSavedSnapshot = '';
  let saveStatusTimer = null;
  let conflictAlertShown = false;
  let pageSwitchInFlight = false;
  let schoolSeq = 1;
  let gradeSeq = 1;
  const expandedSchoolIds = new Set();

  function setSaveStatus(message, clearAfter = 0) {
    if (saveStatusTimer) {
      clearTimeout(saveStatusTimer);
      saveStatusTimer = null;
    }
    statusEl.textContent = message;
    if (clearAfter > 0) {
      const expected = message;
      saveStatusTimer = setTimeout(() => {
        saveStatusTimer = null;
        if (statusEl.textContent === expected) statusEl.textContent = '';
      }, clearAfter);
    }
  }

  function reportSaveConflict(mode) {
    setSaveStatus('다른 화면의 변경이 감지되었습니다. 페이지를 새로고침해 주세요.');
    if ((mode === 'manual' || mode === 'switch') && !conflictAlertShown) {
      conflictAlertShown = true;
      alert('다른 화면에서 학교 일정이 변경되었습니다. 현재 입력을 확인한 뒤 페이지를 새로고침해 주세요.');
    }
  }

  const calendarPersistence = createSchoolCalendarPersistence({
    onStart(job) {
      if (job.mode === 'auto') setSaveStatus('자동 저장 중...');
      else if (job.mode === 'switch') setSaveStatus('페이지 저장 중...');
      else if (job.mode === 'manual') setSaveStatus('저장 중...');
    },
    onSuccess(job) {
      calendarDoc = job.payload;
      lastSavedSnapshot = job.snapshot;
      if (job.mode === 'auto') setSaveStatus('자동 저장됨', 1500);
      else if (job.mode === 'switch' || job.mode === 'manual') setSaveStatus('저장됨', 1500);
    },
    onConflict(job) {
      reportSaveConflict(job.mode);
    },
    onFailure(job, result) {
      console.error('saveCalendar failed', result.error || result.status);
      if (job.mode === 'auto') setSaveStatus('자동 저장 실패');
      else if (job.mode === 'metadata') setSaveStatus('페이지 정보 저장 실패');
      else if (job.mode !== 'flush') setSaveStatus('저장 실패');
      if (job.mode === 'manual' || job.mode === 'switch') {
        alert(`저장 실패: ${result.status || result.error?.message || 'network error'}`);
      }
    },
  });

  (function injectStyle() {
    const css = `
      #wrap { overflow: auto; }
      #calTable {
        table-layout: auto;
        width: max(1420px, 100%);
        min-width: 1420px;
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
        border-top: 3px solid #7fb3f2;
        border-bottom: 1px solid #c7dcf6;
        background: #eaf4ff;
      }
      .school-row td:first-child {
        box-shadow: inset 5px 0 0 var(--sc-accent);
      }
      .grade-row td {
        background: #f8fafc;
      }
      .grade-row.is-last-grade td {
        border-bottom: 2px solid #c6ddf7;
      }
      .grade-row.search-match td,
      .school-row.search-match td {
        background: #fff7df;
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
        border: 1px solid var(--sc-accent);
        background: var(--sc-accent);
        color: #fff;
        font-weight: 900;
      }
      .btn-del:hover {
        filter: brightness(0.94);
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
      .common-chip,
      .muted-cell {
        display:inline-flex;
        min-height: 30px;
        align-items:center;
        border:1px solid #cbd5e1;
        border-radius:999px;
        padding:0 9px;
        font-size:12px;
        font-weight: 700;
        color:#475569;
        background:#f8fafc;
      }
      .muted-cell {
        border-style: dashed;
        color:#7b8ca3;
        background:#f6f9fd;
      }
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
        background:#2563eb;
        border-color:#3b82f6;
        color:#eff6ff;
      }
      body.dark .common-chip,
      body.dark .muted-cell {
        border-color:#334155;
        color:#cbd5e1;
        background:#0b1220;
      }
      body.dark .grade-row td { background:#111827; }
      body.dark .grade-row.is-last-grade td { border-bottom-color:#2a4a74; }
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
        background:#142b48;
        border-top-color: #4f83c7;
        border-bottom-color:#2a4a74;
      }
      body.dark .grade-row.search-match td,
      body.dark .school-row.search-match td {
        background:#352d16;
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

  function esc(value) {
    return String(value ?? '').replace(/[&<>"']/g, (m) => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#39;',
    }[m]));
  }

  function examConfig() {
    return EXAMS[viewMode] || EXAMS.mid;
  }

  function searchKeyFor(...values) {
    return searchKeyForText(values.filter((v) => v != null).join(' '));
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

  function cloneSchoolEntry(school) {
    return cloneSchoolCalendarRow(school, { nextGradeId });
  }

  function loadSchoolsFromDoc(payload, year, semester) {
    const loaded = loadSchoolCalendarRows(payload, {
      year,
      semester,
      nextSchoolId,
      nextGradeId,
    });
    loaded.expandedSchoolIds.forEach((schoolId) => expandedSchoolIds.add(schoolId));
    return loaded.rows;
  }

  function shortYear(year) {
    const y = String(year || '').trim();
    return /^\d{4}$/.test(y) ? y.slice(2) : y;
  }

  function pageLabel() {
    return `${shortYear(editingYear)}년 ${editingSemester}학기 ${examConfig().label}`;
  }

  function updateTitle() {
    document.title = `학교 일정 관리 (${pageLabel()})`;
    if (tableNoteEl) {
      tableNoteEl.textContent = `${pageLabel()} · 학교 행에는 개학/지필고사 기간을, 학년-과목 행에는 교과서/수학시험일/시험 정보를 입력합니다.`;
    }
  }

  function applyColgroup() {
    const widths = ['86px', '220px', '10.5rem', '12rem', '110px', '150px', '130px', '12rem', '14rem', '62px'];
    table.querySelector('colgroup')?.remove();
    const cg = document.createElement('colgroup');
    cg.innerHTML = widths.map((w) => (w ? `<col style="width:${w}">` : '<col>')).join('');
    table.insertBefore(cg, table.firstElementChild);
  }

  function renderHead() {
    const exam = examConfig();
    const cols = [
      ['열기/#', '86px'],
      ['학교명', '220px'],
      ['개학(날짜)', '10.5rem'],
      [exam.periodLabel, '12rem'],
      ['학년', '110px'],
      ['과목/트랙', '150px'],
      ['교과서', '130px'],
      [exam.mathLabel, '12rem'],
      ['시험 관련 정보', '14rem'],
      ['삭제', '62px'],
    ];

    theadTr.innerHTML = cols.map(([label, width]) => `<th style="${width ? `width:${width}` : ''}">${label}</th>`).join('');
    applyColgroup();
  }

  function buildSchoolRow(school, index, options = {}) {
    const expanded = expandedSchoolIds.has(school.id);
    const exam = examConfig();
    const matchClass = options.matched ? ' search-match' : '';
    return `
      <tr class="school-row${matchClass}" data-school-id="${esc(school.id)}">
        <td>
          <div class="row-index-wrap">
            <button type="button" class="btn-toggle" data-action="toggle-school" title="학년 행 펼치기">${expanded || searchQuery ? '▼' : '▶'}</button>
            <span>${index}</span>
          </div>
        </td>
        <td>
          <div class="school-name-wrap">
            <input type="text" class="inp-school" value="${esc(school.school || '')}" placeholder="학교명">
            <button type="button" class="btn-add-grade" data-action="add-grade" title="학년 행 추가">+학년</button>
          </div>
        </td>
        <td><input type="text" class="sc-sem" value="${esc(school.common.semesterStart || '')}" placeholder="예: 3/4(화)"></td>
        <td><input type="text" class="sc-period" value="${esc(school.common[exam.period] || '')}" placeholder="${esc(exam.period === 'midterm' ? '예: 4/27~4/30' : '예: 6/29~7/3')}"></td>
        <td><span class="common-chip">학교 공통</span></td>
        <td><span class="muted-cell">-</span></td>
        <td><span class="muted-cell">학년 행</span></td>
        <td><span class="muted-cell">학년 행</span></td>
        <td><span class="muted-cell">학년 행</span></td>
        <td style="text-align:center"><button type="button" class="btn-del" title="학교 삭제">X</button></td>
      </tr>
    `;
  }

  function buildGradeRow(school, gradeRow, options = {}) {
    const exam = examConfig();
    const rowClass = [
      'grade-row',
      options.last ? 'is-last-grade' : '',
      options.matched ? 'search-match' : '',
    ].filter(Boolean).join(' ');

    return `
      <tr class="${rowClass}" data-school-id="${esc(school.id)}" data-grade-id="${esc(gradeRow.id)}">
        <td><span class="grade-hint">└&gt;</span></td>
        <td><span class="grade-hint">${esc(school.school || '학년별')}</span></td>
        <td><span class="muted-cell">학교 행</span></td>
        <td><span class="muted-cell">학교 행</span></td>
        <td><input type="text" class="gr-grade" value="${esc(gradeRow.grade || '')}" placeholder="예: 1학년"></td>
        <td><input type="text" class="gr-phase" value="${esc(gradeRow.phase || '')}" placeholder="예: 수학1 / 미적분"></td>
        <td><input type="text" class="gr-textbook" value="${esc(gradeRow.fields.textbook || '')}" placeholder="예: YBM"></td>
        <td><input type="text" class="gr-exam-math" value="${esc(gradeRow.fields[exam.math] || '')}" placeholder="${esc(exam.mathLabel)}"></td>
        <td><input type="text" class="gr-exam-note" value="${esc(gradeRow.fields[exam.note] || '')}" placeholder="예: 서술형 포함 / 범위 추후 공지"></td>
        <td style="text-align:center"><button type="button" class="btn-del" title="학년 행 삭제">X</button></td>
      </tr>
    `;
  }

  function ensureAtLeastOneSchool() {
    if (schoolsData.length) return;
    schoolsData.push({
      id: nextSchoolId(),
      school: '',
      common: normalizeCommonFields({}),
      grades: [],
    });
  }

  function schoolMatchesQuery(school, queryText) {
    return matchesSearchKey(searchKeyFor(school.school), queryText);
  }

  function gradeMatchesQuery(school, gradeRow, queryText) {
    return matchesSearchKey(searchKeyFor(
      school.school,
      gradeRow.grade,
      gradeRow.phase,
      gradeRow.fields?.textbook,
      gradeRow.fields?.midtermMath,
      gradeRow.fields?.midtermNote,
      gradeRow.fields?.finalMath,
      gradeRow.fields?.finalNote,
    ), queryText);
  }

  function renderBody() {
    ensureAtLeastOneSchool();

    const query = String(searchQuery || '').trim();
    const chunks = [];
    let visibleSchools = 0;
    let visibleGrades = 0;

    schoolsData.forEach((school, index) => {
      const schoolMatch = schoolMatchesQuery(school, query);
      const gradeMatchResults = new Map();
      const matchesGrade = (gradeRow) => {
        if (!gradeMatchResults.has(gradeRow)) {
          gradeMatchResults.set(gradeRow, gradeMatchesQuery(school, gradeRow, query));
        }
        return gradeMatchResults.get(gradeRow);
      };
      const gradeMatches = (school.grades || []).filter((gradeRow) => schoolMatch || matchesGrade(gradeRow));
      const shouldShowSchool = !query || schoolMatch || gradeMatches.length > 0;
      if (!shouldShowSchool) return;

      visibleSchools += 1;
      chunks.push(buildSchoolRow(school, index + 1, { matched: !!query && schoolMatch }));

      const showGrades = query ? gradeMatches.length > 0 : expandedSchoolIds.has(school.id);
      if (!showGrades) return;

      gradeMatches.forEach((gradeRow, rowIndex) => {
        const matched = !!query && matchesGrade(gradeRow);
        visibleGrades += 1;
        chunks.push(buildGradeRow(school, gradeRow, {
          last: rowIndex === gradeMatches.length - 1,
          matched,
        }));
      });
    });

    tbody.innerHTML = chunks.join('');
    if (searchStatusEl) {
      searchStatusEl.textContent = query ? `${visibleSchools}개 학교 / ${visibleGrades}행` : '';
    }
  }

  function render() {
    updateTitle();
    renderHead();
    renderBody();
    syncPageSelectors();
  }

  function readSchoolFieldsFromRow(rowEl) {
    const exam = examConfig();
    return {
      semesterStart: rowEl.querySelector('.sc-sem')?.value.trim() || '',
      [exam.period]: rowEl.querySelector('.sc-period')?.value.trim() || '',
    };
  }

  function readGradeFieldsFromRow(rowEl) {
    const exam = examConfig();
    return {
      textbook: rowEl.querySelector('.gr-textbook')?.value.trim() || '',
      [exam.math]: rowEl.querySelector('.gr-exam-math')?.value.trim() || '',
      [exam.note]: rowEl.querySelector('.gr-exam-note')?.value.trim() || '',
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
        common: normalizeCommonFields({}),
        grades: [],
      };

      const commonPatch = readSchoolFieldsFromRow(tr);
      const preserveHiddenGrades = !!searchQuery || !expandedSchoolIds.has(schoolId);
      const school = {
        id: schoolId,
        school: tr.querySelector('.inp-school')?.value.trim() || prev.school || '',
        common: normalizeCommonFields({ ...prev.common, ...commonPatch }),
        grades: preserveHiddenGrades ? [...(prev.grades || [])] : [],
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
      const fieldsPatch = readGradeFieldsFromRow(tr);
      const fields = normalizeGradeFields({ ...(prevGrade?.fields || {}), ...fieldsPatch });

      if (!grade && !phase && !hasScheduleValue(fields)) return;

      const nextGrade = { id: gradeId, grade, phase, fields };
      const existingIndex = school.grades.findIndex((row) => String(row.id) === String(gradeId));
      if (existingIndex >= 0) school.grades[existingIndex] = nextGrade;
      else school.grades.push(nextGrade);
    });

    if (searchQuery) {
      const ordered = schoolsData.map((school) => nextById.get(school.id) || cloneSchoolEntry(school));
      next.forEach((school) => {
        if (!ordered.some((row) => String(row.id) === String(school.id))) ordered.push(school);
      });
      schoolsData = ordered;
    } else {
      schoolsData = next;
    }
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
    return buildSchoolCalendarDocument({
      calendarDoc,
      schools: schoolsData,
      activeYear: editingYear,
      activeSemester: editingSemester,
      activeExam: viewMode,
      fallbackYear: String(new Date().getFullYear()),
    });
  }

  async function saveCalendar(mode = 'manual') {
    if (autoSaveTimer) {
      clearTimeout(autoSaveTimer);
      autoSaveTimer = null;
    }

    if (calendarPersistence.isBlocked()) {
      reportSaveConflict(mode);
      return false;
    }

    syncFromView();
    const snapshot = JSON.stringify(buildPayloadFromState());
    const payload = JSON.parse(snapshot);
    const result = await calendarPersistence.enqueue({ mode, payload, snapshot });
    return result.ok;
  }

  function flushCalendarSave() {
    syncFromView();
    const snapshot = JSON.stringify(buildPayloadFromState());
    if (snapshot === lastSavedSnapshot) return;
    void saveCalendar('flush');
  }

  function addSchoolRow() {
    syncFromView();
    const newSchool = {
      id: nextSchoolId(),
      school: '',
      common: normalizeCommonFields({}),
      grades: [],
    };
    schoolsData.push(newSchool);
    expandedSchoolIds.add(newSchool.id);
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
      fields: normalizeGradeFields({}),
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

  function readStoredPage() {
    try {
      const stored = JSON.parse(localStorage.getItem(PAGE_STORAGE_KEY) || '{}');
      return isObject(stored) ? stored : {};
    } catch {
      return {};
    }
  }

  function persistPageSelection() {
    localStorage.setItem(PAGE_STORAGE_KEY, JSON.stringify({
      year: editingYear,
      semester: editingSemester,
      exam: viewMode,
    }));
  }

  function updateCalendarDocActivePage() {
    calendarDoc = withActiveSchoolCalendarPage(calendarDoc, {
      year: editingYear,
      semester: editingSemester,
      exam: viewMode,
    });
  }

  async function persistActivePageMetadata() {
    updateCalendarDocActivePage();
    const snapshot = JSON.stringify(calendarDoc);
    const payload = JSON.parse(snapshot);
    return calendarPersistence.enqueue({ mode: 'metadata', payload, snapshot });
  }

  function getAvailableYears() {
    const years = new Set();
    const current = new Date().getFullYear();
    [current - 1, current, current + 1].forEach((year) => years.add(String(year)));
    Object.keys(calendarDoc?.years || {}).forEach((year) => years.add(String(year)));
    if (editingYear) years.add(String(editingYear));
    return [...years].sort((a, b) => Number(a) - Number(b));
  }

  function syncPageSelectors() {
    const yearOptions = getAvailableYears();
    yearSelect.innerHTML = yearOptions
      .map((year) => `<option value="${esc(year)}">${esc(shortYear(year))}년</option>`)
      .join('');
    yearSelect.value = editingYear;
    semesterSelect.value = editingSemester;
    examSelect.value = viewMode;
  }

  async function switchPageFromSelectors() {
    if (pageSwitchInFlight) return;
    const nextYear = String(yearSelect.value || editingYear || new Date().getFullYear());
    const nextSemester = coerceSemester(semesterSelect.value);
    const nextExam = coerceExam(examSelect.value);
    if (nextYear === editingYear && nextSemester === editingSemester && nextExam === viewMode) return;

    pageSwitchInFlight = true;
    [yearSelect, semesterSelect, examSelect].forEach((element) => {
      element.disabled = true;
    });
    try {
      const saved = await saveCalendar('switch');
      if (!saved) {
        syncPageSelectors();
        return;
      }

      editingYear = nextYear;
      editingSemester = nextSemester;
      viewMode = nextExam;
      persistPageSelection();
      void persistActivePageMetadata();
      expandedSchoolIds.clear();
      schoolsData = loadSchoolsFromDoc(calendarDoc, editingYear, editingSemester);
      ensureAtLeastOneSchool();
      lastSavedSnapshot = JSON.stringify(buildPayloadFromState());
      render();
    } finally {
      [yearSelect, semesterSelect, examSelect].forEach((element) => {
        element.disabled = false;
      });
      pageSwitchInFlight = false;
    }
  }

  [yearSelect, semesterSelect, examSelect].forEach((el) => {
    el.addEventListener('change', () => {
      switchPageFromSelectors();
    });
  });

  addBtn.addEventListener('click', addSchoolRow);

  saveBtn.addEventListener('click', () => {
    saveCalendar('manual');
  });

  const updateSearch = () => {
    syncFromView();
    searchQuery = searchInput.value || '';
    renderBody();
  };
  searchInput?.addEventListener('input', updateSearch);
  searchInput?.addEventListener('search', updateSearch);

  searchInput?.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape') return;
    syncFromView();
    searchInput.value = '';
    searchQuery = '';
    renderBody();
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
      calendarDoc = await calendarPersistence.load();
    } catch {
      calendarDoc = {};
    }

    const stored = readStoredPage();
    const selected = resolveSchoolCalendarPageSelection(calendarDoc, stored, String(new Date().getFullYear()));
    editingYear = selected.year;
    editingSemester = selected.semester;
    viewMode = selected.exam;
    syncPageSelectors();
    persistPageSelection();

    schoolsData = loadSchoolsFromDoc(calendarDoc, editingYear, editingSemester);
    ensureAtLeastOneSchool();
    lastSavedSnapshot = JSON.stringify(buildPayloadFromState());
    render();
  })();
})();
