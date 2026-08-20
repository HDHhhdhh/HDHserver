// /static/js/admin/features/hoverTooltip.js
import { state } from '../core/state.js';
import { getAdminDate } from '../core/adminDate.js';
import { resolveSchoolCalendarEntry, resolveSchoolCalendarEntries } from '../../shared/schoolCalendar.js?v=20260814-active-semester1';
import { regularAttendanceDaysForStudent } from '../../shared/selfStudy.js';

export function initHoverTooltip() {
  if (document._adminHoverTooltipInitialized) return;
  document._adminHoverTooltipInitialized = true;

  let tipEl = null;
  let tipMode = 'hover';        // 'hover' | 'fixed'
  let tipVariant = 'default';   // 'default' | 'log'  (log 모달용 축약 버전)
  let activeHoverAnchor = null;
  let pointerHoverAnchor = null;
  let focusHoverAnchor = null;
  let describedHoverAnchor = null;
  let focusTooltipDismissed = false;
  let focusTransitionEpoch = 0;
  let lastPointerPoint = null;
  let hoverPlacementFrame = 0;
  let resizePlacementFrame = 0;
  let pendingHoverPoint = null;
  let hoverTipSize = null;
  let indexedStudents = null;
  let indexedStudentCount = -1;
  let studentsBySid = new Map();
  let studentsByName = new Map();
  let placementEpoch = 0;

  const WCHR = '일월화수목금토';
  const LOG_TIP_POS_KEY = 'admin:logTipPos'; // 로그 모달 툴팁 위치 저장 키
  let dragState = null; // { pointerId, startX, startY, startLeft, startTop }

  function loadLogTipPos() {
    try {
      const raw = localStorage.getItem(LOG_TIP_POS_KEY);
      if (!raw) return null;
      const obj = JSON.parse(raw);
      if (typeof obj?.left === 'number' && typeof obj?.top === 'number') return obj;
    } catch { }
    return null;
  }

  function saveLogTipPos(left, top) {
    try {
      localStorage.setItem(LOG_TIP_POS_KEY, JSON.stringify({ left, top }));
    } catch { }
  }

  function ensureTip() {
    if (tipEl) return tipEl;
    tipEl = document.createElement('div');
    tipEl.id = 'adminSchoolTip';
    tipEl.setAttribute('aria-hidden', 'true');
    tipEl.style.cssText = `
      position: fixed;
      top: 0; left: 0;
      background: rgba(17,24,39,.98); color: #fff; border-radius: 18px;
      padding: 16px 18px; font-size: 15px; box-shadow: 0 18px 42px rgba(0,0,0,.44);
      z-index: 100000; pointer-events: none; display: none;
      max-width: min(1100px, 92vw);
      max-height: min(86vh, 900px);
      overflow-x: hidden;
      overflow-y: auto;
      line-height: 1.5;
      transform: translate(10px, 10px);
      box-sizing: border-box;
      cursor: default;
    `;

    // 드래그 시작
    tipEl.addEventListener('pointerdown', (ev) => {
      // 고정 모드에서만 드래그 허용 (로그 모달 고정 툴팁)
      if (tipMode !== 'fixed') return;
      if (tipEl.classList.contains('student-work-layout')) return;
      if (ev.button !== 0) return; // 좌클릭만

      const rect = tipEl.getBoundingClientRect();
      dragState = {
        pointerId: ev.pointerId,
        startX: ev.clientX,
        startY: ev.clientY,
        startLeft: rect.left,
        startTop: rect.top,
        currentLeft: rect.left,
        currentTop: rect.top,
        width: rect.width,
        height: rect.height,
      };

      try { tipEl.setPointerCapture(ev.pointerId); } catch { }
      tipEl.style.cursor = 'grabbing';
      ev.preventDefault();
    });

    document.addEventListener('pointermove', (ev) => {
      if (!dragState) return;
      if (ev.pointerId !== dragState.pointerId) return;
      if (!tipEl) return;

      const dx = ev.clientX - dragState.startX;
      const dy = ev.clientY - dragState.startY;

      const vw = window.innerWidth;
      const vh = window.innerHeight;
      let left = dragState.startLeft + dx;
      let top = dragState.startTop + dy;

      const pad = 12;
      const maxLeft = vw - dragState.width - pad;
      const maxTop = vh - dragState.height - pad;

      left = Math.max(pad, Math.min(left, maxLeft));
      top = Math.max(pad, Math.min(top, maxTop));

      tipEl.style.left = `${left}px`;
      tipEl.style.top = `${top}px`;
      dragState.currentLeft = left;
      dragState.currentTop = top;
    });

    function endDrag(ev) {
      if (!dragState) return;
      if (ev.pointerId !== dragState.pointerId) return;
      if (!tipEl) { dragState = null; return; }

      try { tipEl.releasePointerCapture(dragState.pointerId); } catch { }

      // 고정 툴팁 위치를 공통으로 저장 (로그 모달에서 재사용)
      saveLogTipPos(dragState.currentLeft, dragState.currentTop);

      tipEl.style.cursor = tipMode === 'fixed' ? 'grab' : 'default';
      dragState = null;
    }

    document.addEventListener('pointerup', endDrag);
    document.addEventListener('pointercancel', endDrag);

    document.body.appendChild(tipEl);
    return tipEl;
  }

  const pill = (label, value, opts = {}) => `
    <div style="
      display:flex; flex-direction:column; gap:2px;
      background:rgba(255,255,255,.06);
      border:1px solid rgba(255,255,255,.12);
      padding:6px 10px; border-radius:10px; min-width:92px;">
      <div style="font-size:11px; opacity:.85">${label}</div>
      <div style="
        font-weight:700; white-space:normal; line-height:1.25; word-break:keep-all;
        ${opts.big ? 'font-size:15px;' : ''}
      ">
        ${value || '-'}
      </div>
    </div>`;

  const em = (label, value) => `
    <div style="display:flex; gap:6px;">
      <div style="min-width:54px; opacity:.8">${label}</div>
      <div style="font-weight:700; word-break:break-word">${value || '-'}</div>
    </div>`;

  function classifySubjectExamTiming(value) {
    const text = String(value || '').trim();
    if (!text) return '';

    const withoutYear = text.replace(/\b(?:19|20)\d{2}\s*[-./]\s*/g, '');
    const numericDates = withoutYear.match(/\b\d{1,2}\s*[-./]\s*\d{1,2}\b/g) || [];
    const koreanDates = withoutYear.match(/\b\d{1,2}\s*월\s*\d{1,2}\s*일\b/g) || [];
    const dateCount = numericDates.length + koreanDates.length;
    const hasRangeMarker = /[~∼～〜]|(?:부터|에서).*까지/.test(text);

    if (dateCount >= 2 || hasRangeMarker) return 'range';
    if (dateCount === 1) return 'date';
    return '';
  }


  const escHtml = (value) => String(value ?? '').replace(/[&<>"']/g, (m) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
  }[m]));

  const tipRow = (label, value) => `
    <div style="display:grid; grid-template-columns:104px minmax(0,1fr); gap:12px; align-items:start;">
      <div style="opacity:.78; font-weight:800">${escHtml(label)}</div>
      <div style="font-weight:900; word-break:keep-all">${escHtml(value || '-')}</div>
    </div>`;


  function todayInfoRow(icon, label, value) {
    return `
      <div style="display:grid; grid-template-columns:38px minmax(92px,128px) minmax(0,1fr); gap:12px; align-items:center;">
        <span
          aria-hidden="true"
          style="
            width:38px; height:38px; border-radius:12px;
            display:inline-flex; align-items:center; justify-content:center;
            background:rgba(255,255,255,.1); border:1px solid rgba(255,255,255,.16);
            font-size:22px; line-height:1;
          "
        >${icon}</span>
        <span style="min-width:0; opacity:.82; font-size:16px; font-weight:850; word-break:normal; overflow-wrap:anywhere;">${escHtml(label)}</span>
        <span style="min-width:0; font-size:19px; font-weight:950; word-break:normal; overflow-wrap:anywhere;">${escHtml(value || '-')}</span>
      </div>`;
  }

  function pickTextbook(entry = {}) {
    return String(
      entry.textbook || entry.mathTextbook || entry.book || entry.mathBook ||
      entry['교과서'] || entry['수학교과서'] || ''
    ).trim();
  }

  function normalizeSubjectKey(value) {
    const compact = String(value ?? '')
      .trim()
      .replace(/[Ⅰⅰ]/g, '1')
      .replace(/[Ⅱⅱ]/g, '2')
      .toLowerCase()
      .replace(/\s+/g, '')
      .replace(/[():：·._-]/g, '');

    const aliases = {
      '공통수학1': '공수1',
      '공통수학2': '공수2',
      '미적1': '미적분1',
      '미적2': '미적분2',
      '확률과통계': '확통',
    };

    return aliases[compact] || compact;
  }

  function filterScheduleEntriesForStudent(scheduleEntries, stu) {
    if (!scheduleEntries.length) return scheduleEntries;

    const curriculumKey = normalizeSubjectKey(stu?.curriculum);
    if (!curriculumKey) return scheduleEntries;

    const exact = scheduleEntries.filter((entry) => (
      normalizeSubjectKey(entry?.phase) === curriculumKey
    ));
    if (exact.length) return exact;

    const loose = scheduleEntries.filter((entry) => {
      const phaseKey = normalizeSubjectKey(entry?.phase);
      return phaseKey && (phaseKey.includes(curriculumKey) || curriculumKey.includes(phaseKey));
    });

    if (loose.length) return loose;

    // 학교 공통/학년 일정은 과목명이 없을 수 있으므로 모든 과목에 적용한다.
    return scheduleEntries.filter(entry => !normalizeSubjectKey(entry?.phase));
  }

  function buildTextbookPublisherHtml(scheduleEntries, fallbackEntry) {
    const sourceEntries = scheduleEntries.length
      ? scheduleEntries
      : (fallbackEntry && Object.keys(fallbackEntry).length ? [fallbackEntry] : []);
    const items = [];
    const seen = new Set();

    sourceEntries.forEach((entry, idx) => {
      const textbook = pickTextbook(entry || {});
      if (!textbook) return;

      const phase = String(entry?.phase || '').trim();
      const grade = String(entry?.grade || '').trim();
      const label = phase || (sourceEntries.length > 1 ? (grade || `트랙 ${idx + 1}`) : '');
      const key = `${label}::${textbook}`;
      if (seen.has(key)) return;
      seen.add(key);
      items.push({ label, textbook });
    });

    if (!items.length) return '';

    return `
      <span class="student-tooltip-publisher" style="display:inline-flex; gap:6px; flex-wrap:wrap; align-items:center; margin:0; max-width:100%; font-size:12.5px; vertical-align:middle">
        ${items.map(({ label, textbook }) => `
          <span style="display:inline-flex; align-items:center; gap:5px; padding:3px 8px;
                       border:1px solid rgba(255,255,255,.14); border-radius:999px;
                       background:rgba(255,255,255,.07); font-weight:700;">
            <span aria-hidden="true">📕</span>
            ${label ? `<span style="opacity:.82">${escHtml(label)}</span>` : ''}
            <span>${escHtml(textbook)}</span>
          </span>
        `).join('')}
      </span>
    `;
  }

  // ───────────────────────────────────────────
  // 학사일정: 기말(final) 우선, 없으면 중간(midterm) 폴백
  // ───────────────────────────────────────────
  function pickExam(sc, prefer = 'auto') {
    const get = (obj, k, altKeys = []) => {
      for (const key of [k, ...altKeys]) {
        if (obj[key] != null && String(obj[key]).trim()) return obj[key];
      }
      return '';
    };

    const packs = {
      final: {
        label: '기말',
        date: get(sc, 'final', ['finalDate', '기말', '기말기간']),
        math: get(sc, 'finalMath', ['기말수학', 'final_math', '수학기말', '수학 기말']),
        range: get(sc, 'finalRange', ['기말범위']),
        note: get(sc, 'finalNote', ['기말비고']),
      },
      midterm: {
        label: '중간',
        date: get(sc, 'midterm', ['midtermDate', '중간', '중간기간']),
        math: get(sc, 'midtermMath', ['중간수학', 'midterm_math', '수학중간', '수학 중간']),
        range: get(sc, 'midtermRange', ['중간범위']),
        note: get(sc, 'midtermNote', ['중간비고']),
      }
    };

    const hasAny = (pack) => [pack.date, pack.math, pack.range, pack.note]
      .some(v => v && String(v).trim());

    if (prefer === 'auto') {
      const today = new Date();
      today.setHours(0, 0, 0, 0);

      const score = (pack, order) => {
        if (!hasAny(pack)) return [9, order];
        const source = pack.date || pack.math || '';
        const m = String(source).match(/(\d{1,2})\/(\d{1,2})/);
        if (!m) return [8, order];
        const month = parseInt(m[1], 10);
        const day = parseInt(m[2], 10);
        const d = new Date(today.getFullYear(), month - 1, day);
        d.setHours(0, 0, 0, 0);
        const diff = d.getTime() - today.getTime();
        return diff >= 0 ? [0, diff, order] : [1, Math.abs(diff), order];
      };

      const candidates = [
        { key: 'midterm', pack: packs.midterm, order: 0 },
        { key: 'final', pack: packs.final, order: 1 },
      ].filter(x => hasAny(x.pack));

      if (!candidates.length) return packs.midterm;
      candidates.sort((a, b) => {
        const sa = score(a.pack, a.order);
        const sb = score(b.pack, b.order);
        for (let i = 0; i < Math.max(sa.length, sb.length); i += 1) {
          const da = sa[i] ?? 0;
          const db = sb[i] ?? 0;
          if (da !== db) return da - db;
        }
        return 0;
      });
      return candidates[0].pack;
    }

    const primary = packs[prefer];
    const fallback = packs[prefer === 'final' ? 'midterm' : 'final'];
    const hasPrimary = hasAny(primary);
    return hasPrimary ? primary : fallback;
  }

  function hasExamSchedule(entry = {}) {
    return [
      'midterm', 'midtermMath',
      'final', 'finalMath',
    ].some((key) => String(entry?.[key] || '').trim());
  }

  function buildSharedExamPeriodEntry(scheduleEntries = []) {
    const pickSharedValue = (key) => {
      const values = [...new Set(
        scheduleEntries
          .map((entry) => String(entry?.[key] || '').trim())
          .filter(Boolean),
      )];
      return values.length === 1 ? values[0] : '';
    };

    const midterm = pickSharedValue('midterm');
    const final = pickSharedValue('final');
    return {
      ...(midterm ? { midterm } : {}),
      ...(final ? { final } : {}),
    };
  }

  // ───────────────────────────────────────────
  // 날짜 파싱 & 시험까지 남은 출석일 계산
  // ───────────────────────────────────────────
  function parseFirstMonthDay(str) {
    if (!str) return null;
    const m = String(str).match(/(\d{1,2})\/(\d{1,2})/);
    if (!m) return null;
    const month = parseInt(m[1], 10);
    const day = parseInt(m[2], 10);
    if (!month || !day) return null;

    const today = new Date();
    const year = today.getFullYear();
    const d = new Date(year, month - 1, day);
    d.setHours(0, 0, 0, 0);
    return d;
  }

  function extractAttendWeekdays(stu) {
    const set = new Set();
    Object.keys(stu || {}).forEach(k => {
      if (!/^day\d+$/.test(k)) return;
      const v = String(stu[k] || '').trim();
      if (!v) return;
      const ch = v[0];
      if ('월화수목금토일'.includes(ch)) set.add(ch);
    });
    return [...set];
  }

  function tooltipStudentSchool(student) {
    return String(
      student?.school ||
      student?.highSchool || student?.schoolHigh || student?.high || student?.highschool || student?.high_school || student?.['고등학교'] ||
      student?.middleSchool || student?.schoolMiddle || student?.middle || student?.middleschool || student?.middle_school || student?.['중학교'] ||
      '',
    ).trim();
  }

  function subjectMatchesTooltipContext(value, contextKey) {
    const key = normalizeSubjectKey(value);
    return Boolean(key && contextKey && (
      key === contextKey || key.includes(contextKey) || contextKey.includes(key)
    ));
  }

  function sameTooltipStudent(left, right) {
    const leftId = String(left?.id || '').trim();
    const rightId = String(right?.id || '').trim();
    if (leftId && rightId && leftId === rightId) return true;

    const leftName = String(left?.name || '').trim();
    const rightName = String(right?.name || '').trim();
    if (!leftName || leftName !== rightName) return false;

    const leftSchool = tooltipStudentSchool(left);
    const rightSchool = tooltipStudentSchool(right);
    if (leftSchool && rightSchool && leftSchool !== rightSchool) return false;

    const leftGrade = String(left?.grade || '').trim();
    const rightGrade = String(right?.grade || '').trim();
    if (leftGrade && rightGrade && leftGrade !== rightGrade) return false;
    return true;
  }

  function attendanceDaysForTooltip(stu, subjectContext = '') {
    const fallback = regularAttendanceDaysForStudent(stu);
    const contextKey = normalizeSubjectKey(subjectContext);
    if (!contextKey || subjectMatchesTooltipContext(stu?.curriculum, contextKey)) return fallback;

    const records = Array.isArray(state.students) ? state.students : [];
    const subjectRecords = records.filter((record) => (
      sameTooltipStudent(record, stu) && subjectMatchesTooltipContext(record?.curriculum, contextKey)
    ));
    if (!subjectRecords.length) return fallback;

    return [...new Set(subjectRecords.flatMap(record => regularAttendanceDaysForStudent(record)))];
  }
  // "시험 시작일" 직전까지 등원 요일만 카운트
  function calcRemainingSessions(sc, stu) {
    if (!sc || !stu) return null;

    // 툴팁에 쓰는 것과 동일한 학사일정 패키지
    const examPack = pickExam(sc, 'auto');

    // 1순위: 기말 시작일(기간) → 예: "12/3(수)~12/9(화)"
    // 2순위: 수학시험일 → 예: "12/4(목)"
    let examDate = null;
    if (examPack.date) {
      examDate = parseFirstMonthDay(examPack.date);
    }
    if (!examDate && examPack.math) {
      examDate = parseFirstMonthDay(examPack.math);
    }
    if (!examDate) return null;

    const today = new Date();
    today.setHours(0, 0, 0, 0);

    // 시험이 오늘이거나 이미 시작한 경우: 남은 등원 0회
    if (examDate <= today) return 0;

    // "시험 시작일" 전날까지만 포함
    const end = new Date(examDate);
    end.setDate(end.getDate() - 1);
    end.setHours(0, 0, 0, 0);

    const daysOfWeek = extractAttendWeekdays(stu);
    if (!daysOfWeek.length) return null;

    let count = 0;
    const cur = new Date(today);

    // 오늘 ~ (시험 시작 전날)까지, 등원 요일 카운트
    while (cur <= end) {
      const w = WCHR[cur.getDay()];
      if (daysOfWeek.includes(w)) count++;
      cur.setDate(cur.getDate() + 1);
      cur.setHours(0, 0, 0, 0);
    }

    return count;
  }



  // ───────────────────────────────────────────
  // 영상/테스트 표시 (옵션으로 영상/테스트 각각 on/off)
  // ───────────────────────────────────────────
  function renderProgressTables(stu, opts = {}) {
    const { includeVideo = true } = opts;
    if (!includeVideo) return '';
    const today = getAdminDate();

    const allDates = Object.keys(state.progress || {}).filter(d => d <= today).sort();
    const mergedProg = {};

    allDates.forEach(d => {
      const per = state.progress[d]?.[stu.id] || {};
      Object.entries(per).forEach(([k, v]) => {
        if (String(k).startsWith('__') || k === 'tests') return;
        mergedProg[k] = v;
      });
    });

    const vids = (state.videos || [])
      .filter(v => v.curriculum === stu.curriculum && v.subCurriculum === stu.subCurriculum)
      .sort((a, b) => (a.chapter ?? 0) - (b.chapter ?? 0));

    const colorFor = (st) =>
      st === 'done' ? '#10b981' :
        st === 'interrupted' ? '#f59e0b' :
          st === 'skip' ? '#6b7280' :
            '#1f2937';

    const progCells = vids.map(v => {
      const st = mergedProg[String(v.mid)] || 'none';
      const color = colorFor(st);
      return `
          <div title="${v.chapter}차시 (${st})"
               style="
                 width: 26px; height: 26px; margin: 2px;
                 background:${color}; border:1px solid #111; color:#fff;
                 font-size:11px; display:flex; align-items:center; justify-content:center;
                 border-radius:6px; flex: 0 0 auto;">
            ${v.chapter}
          </div>`;
    }).join('');

    return `
        <div style="margin-top:10px;font-weight:800;font-size:13px">영상 진도</div>
        <div style="
          display:flex; flex-wrap:wrap; gap:0;
          align-items:center; max-width:100%;
        ">
          ${progCells || '<div style="padding:6px 8px;color:#bbb">해당 차시 없음</div>'}
        </div>
      `;
  }

  // ───────────────────────────────────────────
  // 학생 찾기
  // ───────────────────────────────────────────
  function refreshStudentIndex() {
    const studs = Array.isArray(state.students) ? state.students : [];
    if (studs === indexedStudents && studs.length === indexedStudentCount) return;

    studentsBySid = new Map();
    studentsByName = new Map();
    studs.forEach((student) => {
      if (!student || typeof student !== 'object') return;
      if (student.id != null) studentsBySid.set(String(student.id), student);
      const studentName = String(student.name || '').trim();
      if (studentName && !studentsByName.has(studentName)) studentsByName.set(studentName, student);
    });
    indexedStudents = studs;
    indexedStudentCount = studs.length;
  }

  function findStudent(sid, name) {
    refreshStudentIndex();
    if (sid != null) {
      const hit = studentsBySid.get(String(sid));
      if (hit) return hit;
    }
    if (name) {
      const nm = String(name).trim();
      const hit2 = studentsByName.get(nm);
      if (hit2) return hit2;
    }
    return null;
  }

  function studentSidForAnchor(anchorEl) {
    return anchorEl?.dataset?.sid
      || anchorEl?.dataset?.id
      || anchorEl?.closest?.('tr[data-sid]')?.dataset?.sid
      || null;
  }

  // ───────────────────────────────────────────

  function tooltipSubjectForAnchor(anchorEl, explicitSubject = '') {
    return String(
      explicitSubject ||
      anchorEl?.dataset?.curriculum ||
      anchorEl?.closest?.('tr[data-curriculum]')?.dataset?.curriculum ||
      '',
    ).trim();
  }
  // 위치 계산
  // ───────────────────────────────────────────
  function placeTooltipAt(x, y, measuredSize = null) {
    if (!tipEl) return;

    const pad = 12;
    const vw = window.innerWidth, vh = window.innerHeight;
    const rect = measuredSize || tipEl.getBoundingClientRect();

    let left = x + 12;
    let top = y + 12;

    if (left + rect.width + pad > vw) {
      left = Math.max(pad, x - rect.width - 12);
    }
    if (top + rect.height + pad > vh) {
      top = Math.max(pad, y - rect.height - 12);
    }

    left = Math.min(Math.max(pad, left), vw - pad - rect.width);
    top = Math.min(Math.max(pad, top), vh - pad - rect.height);

    tipEl.style.left = `${left}px`;
    tipEl.style.top = `${top}px`;
  }

  function cancelHoverPlacement() {
    if (hoverPlacementFrame) cancelAnimationFrame(hoverPlacementFrame);
    if (resizePlacementFrame) cancelAnimationFrame(resizePlacementFrame);
    hoverPlacementFrame = 0;
    resizePlacementFrame = 0;
    pendingHoverPoint = null;
  }

  function scheduleHoverPlacement(x, y, { remeasure = false } = {}) {
    pendingHoverPoint = { x: Number(x) || 0, y: Number(y) || 0 };
    if (remeasure) hoverTipSize = null;
    if (hoverPlacementFrame) return;

    hoverPlacementFrame = requestAnimationFrame(() => {
      hoverPlacementFrame = 0;
      const point = pendingHoverPoint;
      pendingHoverPoint = null;
      if (!point || !tipEl || tipMode !== 'hover' || tipEl.style.display === 'none') return;
      if (!hoverTipSize) {
        const rect = tipEl.getBoundingClientRect();
        hoverTipSize = { width: rect.width, height: rect.height };
      }
      placeTooltipAt(point.x, point.y, hoverTipSize);
    });
  }

  function placeForLogModal() {
    if (!tipEl) return;

    tipEl.style.transform = 'none';
    tipEl.style.maxWidth = 'min(1200px, 94vw)';

    const pad = 16;
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const rect = tipEl.getBoundingClientRect();
    const maxLeft = Math.max(pad, vw - rect.width - pad);
    const maxTop = Math.max(pad, vh - rect.height - pad);

    // 저장된 위치 있으면 우선 사용
    const stored = loadLogTipPos();
    if (stored) {
      tipEl.style.left = `${Math.min(Math.max(pad, stored.left), maxLeft)}px`;
      tipEl.style.top = `${Math.min(Math.max(pad, stored.top), maxTop)}px`;
      return;
    }

    const card =
      document.querySelector('#logModal .log-card') ||
      document.querySelector('#logModal .modal-card') ||
      document.querySelector('#logModal');

    let left;
    let top;

    if (card) {
      const c = card.getBoundingClientRect();

      left = c.left - rect.width + 850;
      if (left < pad) left = pad;

      top = c.top + 150;
      if (top + rect.height + pad > vh) {
        top = Math.max(pad, vh - rect.height - pad);
      }
    } else {
      left = pad;
      top = vh * 0.15;
      if (top + rect.height + pad > vh) {
        top = Math.max(pad, vh - rect.height - pad);
      }
    }

    tipEl.style.left = `${Math.min(Math.max(pad, left), maxLeft)}px`;
    tipEl.style.top = `${Math.min(Math.max(pad, top), maxTop)}px`;
  }

  function resetStudentWorkTooltipPlacement() {
    if (!tipEl) return;
    tipEl.classList.remove('student-work-layout');
    tipEl.style.right = 'auto';
    tipEl.style.width = '';
    tipEl.style.maxWidth = 'min(1100px, 92vw)';
    tipEl.style.transform = 'translate(10px, 10px)';
  }

  function placeForStudentWorkLayout() {
    if (!tipEl) return;
    tipEl.classList.add('student-work-layout');
    tipEl.style.transform = 'none';
    tipEl.style.right = '';
    tipEl.style.left = '';
    tipEl.style.top = '';
    tipEl.style.width = '';
    tipEl.style.maxWidth = '';
  }

  // ───────────────────────────────────────────
  // HTML 구성
  // ───────────────────────────────────────────
  function nextRegularAttendanceDate(student) {
    const days = regularAttendanceDaysForStudent(student);
    if (!days.length) return '';
    const weekdayChars = '\uC77C\uC6D4\uD654\uC218\uBAA9\uAE08\uD1A0';
    const now = new Date();
    const pad = (value) => String(value).padStart(2, '0');
    for (let offset = 1; offset <= 7; offset += 1) {
      const candidate = new Date(now.getFullYear(), now.getMonth(), now.getDate() + offset);
      const weekday = weekdayChars[candidate.getDay()];
      if (!days.some((value) => String(value || '').includes(weekday))) continue;
      return `${candidate.getFullYear()}-${pad(candidate.getMonth() + 1)}-${pad(candidate.getDate())}`;
    }
    return '';
  }
  function buildTipHtml(stu, opts = {}) {
    const { includeVideo = true, includeTests = false, studentWorkLayout = false, attendanceSubject = "" } = opts;

    const name = (stu.name || '').trim();
    const days = attendanceDaysForTooltip(stu, attendanceSubject).join('·');
    const subBooks = (state.homeworkBooksBySid?.[String(stu.id)] || []).filter(Boolean).join(', ');

    const schoolName =
      stu.school ||
      stu.highSchool || stu.schoolHigh || stu.high || stu.highschool || stu.high_school || stu['고등학교'] ||
      stu.middleSchool || stu.schoolMiddle || stu.middle || stu.middleschool || stu.middle_school || stu['중학교'] || '';

    const allScheduleEntries = resolveSchoolCalendarEntries(state.schoolCal, schoolName, stu.grade);
    const scheduleEntries = filterScheduleEntriesForStudent(allScheduleEntries, stu);
    const fallbackScheduleEntry = !allScheduleEntries.length
      ? resolveSchoolCalendarEntry(state.schoolCal, schoolName, stu.grade)
      : {};
    const sc = scheduleEntries[0] || fallbackScheduleEntry;
    const textbookEntries = scheduleEntries.length
      ? scheduleEntries
      : allScheduleEntries.map((entry) => ({ ...entry, phase: '', grade: '' }));
    const textbookPublisherBlock = buildTextbookPublisherHtml(textbookEntries, sc);
    const sharedExamPeriodEntry = buildSharedExamPeriodEntry(allScheduleEntries);
    const examEntries = scheduleEntries.length
      ? scheduleEntries
      : (Object.keys(sharedExamPeriodEntry).length
          ? [sharedExamPeriodEntry]
          : (sc && Object.keys(sc).length ? [sc] : []));
    const visibleExamEntries = examEntries.filter(hasExamSchedule);



    const mainBlock = `
      <div class="student-tooltip-identity-row" style="display:flex; flex-wrap:wrap; align-items:center; gap:4px 5px; margin-bottom:6px">
        <span class="student-tooltip-name-group">
          <span class="student-tooltip-name">${escHtml(name)}</span>
        </span>
        ${textbookPublisherBlock}
      </div>
      <div class="student-tooltip-schedule-row" style="display:flex; flex-wrap:wrap; align-items:center; gap:4px 8px; margin-bottom:4px; font-size:13px">
        ${days ? `<span>📅 ${days}</span>` : ''}
        ${schoolName ? `<span class="student-tooltip-school">${escHtml(schoolName)}</span>` : ''}
        ${subBooks ? `<span>📘 ${escHtml(subBooks)}</span>` : ''}
      </div>
    `;

    const examDetailMinHeight = studentWorkLayout
      ? '82px'
      : (!includeVideo && !includeTests ? '260px' : (!includeTests ? '128px' : '92px'));

    const examRows = visibleExamEntries.map((entry, idx) => {
      const exam = pickExam(entry || {}, 'auto');
      const remain = calcRemainingSessions(entry || {}, stu);
      const attendanceBlock = (remain != null)
        ? `<div class="student-tooltip-exam-attendance" style="margin-top:8px;font-size:12px;font-weight:800;">
             시험 전 출석 횟수 : <strong>${remain}회</strong>
           </div>`
        : '';
      const examInfoBlock = `
        <div class="student-tooltip-exam-info" style="margin-top:6px;padding:8px 10px;border:1px solid rgba(255,255,255,.16);border-radius:9px;line-height:1.45;">
          <span style="display:block;font-size:11px;font-weight:900;opacity:.72;">시험 정보</span>
          <strong style="display:block;margin-top:2px;font-size:12px;white-space:pre-wrap;overflow-wrap:anywhere;">${escHtml(exam.note || '-')}</strong>
        </div>`;

      const phase = String(entry?.phase || '').trim();
      const examSubject = phase || '수학';
      const subjectExamTimingKind = classifySubjectExamTiming(exam.math);
      const subjectExamPill = subjectExamTimingKind
        ? pill(
            `${examSubject} ${subjectExamTimingKind === 'date' ? '시험일' : '시험 기간'}`,
            exam.math,
            { big: true },
          )
        : '';
      const examTimingPills = exam.label === '중간'
        ? (subjectExamPill || pill('중간 시험 기간', exam.date || '-', { big: true }))
        : `${pill(exam.label, exam.date || '-')}${subjectExamPill}`;
      const detailsBlock = exam.label === '중간' ? '' : `
          <details class="student-exam-details" style="margin-top:8px; border:1px solid rgba(255,255,255,.12); border-radius:10px; padding:10px 12px">
            <summary style="cursor:pointer; font-weight:800">${exam.label} 범위/특이사항</summary>
            <div class="student-exam-details-body" style="padding-top:8px; min-height:${examDetailMinHeight}">
              ${em('범위', exam.range)}
              ${em('비고', exam.note)}
            </div>
          </details>
        `;

      return `
        <div class="student-tooltip-exam-row" style="margin-top:${idx === 0 ? 6 : 10}px; display:block; font-size:12px; max-width:100%">
          <div class="student-tooltip-exam-timing-row" style="display:flex; gap:10px; flex-wrap:wrap; align-items:center; margin-top:0; max-width:100%">
            ${examTimingPills}
          </div>
          ${attendanceBlock}
          ${examInfoBlock}
          ${detailsBlock}
        </div>
      `;
    }).join('');

    const examBlock = schoolName
      ? examRows
      : '<div style="opacity:.8;margin-top:6px;font-size:12px">학교 정보 없음</div>';

    const homeworkBlock = studentWorkLayout ? `
      <section class="student-tooltip-homework" aria-labelledby="studentTooltipHomeworkTitle">
        <div class="student-tooltip-homework-heading">
          <h3 id="studentTooltipHomeworkTitle">숙제</h3>
          <div id="tooltipHomeworkActions" class="student-tooltip-homework-actions" aria-label="숙제 작업"></div>
        </div>
        <div id="tooltipHomeworkHost" class="student-tooltip-homework-host">
          <p class="student-tooltip-homework-loading">숙제 불러오는 중...</p>
        </div>
      </section>
    ` : '';

    const progBlock = renderProgressTables(stu, { includeVideo, includeTests });

    return `${mainBlock}${examBlock}${homeworkBlock}${progBlock}`;
  }

  function buildTodayNameTipHtml(stu, opts = {}) {
    const name = String(stu?.name || '').trim();
    const days = attendanceDaysForTooltip(stu, opts.attendanceSubject).join(' · ');

    const schoolName =
      stu.school ||
      stu.highSchool || stu.schoolHigh || stu.high || stu.highschool || stu.high_school || stu['고등학교'] ||
      stu.middleSchool || stu.schoolMiddle || stu.middle || stu.middleschool || stu.middle_school || stu['중학교'] || '';

    const allScheduleEntries = resolveSchoolCalendarEntries(state.schoolCal, schoolName, stu.grade);
    const scheduleEntries = filterScheduleEntriesForStudent(allScheduleEntries, stu);
    const fallbackScheduleEntry = !allScheduleEntries.length
      ? resolveSchoolCalendarEntry(state.schoolCal, schoolName, stu.grade)
      : {};
    const sc = scheduleEntries[0] || fallbackScheduleEntry;
    const remainEntries = scheduleEntries.length
      ? scheduleEntries
      : (sc && Object.keys(sc).length ? [sc] : []);
    const remain = remainEntries
      .map(entry => calcRemainingSessions(entry || {}, stu))
      .find(value => value != null);
    const remainText = remain == null ? '-' : `${remain}회`;

    return `
      <div style="width:min(420px, calc(92vw - 36px)); max-width:100%; box-sizing:border-box; padding:4px 2px 6px;">
        <div style="display:flex; align-items:center; gap:14px; margin-bottom:20px;">
          <div style="font-weight:950; font-size:30px; line-height:1.12; letter-spacing:0; word-break:keep-all;">${escHtml(name || '-')}</div>
        </div>
        <div style="display:grid; gap:14px; line-height:1.35">
          ${todayInfoRow('📅', '등원요일', days)}
          ${todayInfoRow('⏱️', '남은출석횟수', remainText)}
          ${todayInfoRow('🏫', '학교', schoolName)}
        </div>
      </div>
    `;
  }

  // ───────────────────────────────────────────
  // 핵심: 특정 요소 기준으로 툴팁 표시
  // ───────────────────────────────────────────
  function describedByTokens(anchorEl) {
    return String(anchorEl?.getAttribute?.('aria-describedby') || '').trim().split(/\s+/).filter(Boolean);
  }

  function linkTooltipDescription(anchorEl) {
    if (!(anchorEl instanceof Element)) return;
    const tokens = describedByTokens(anchorEl);
    if (!tokens.includes('adminSchoolTip')) tokens.push('adminSchoolTip');
    anchorEl.setAttribute('aria-describedby', tokens.join(' '));
  }

  function unlinkTooltipDescription(anchorEl) {
    if (!(anchorEl instanceof Element)) return;
    const tokens = describedByTokens(anchorEl).filter(token => token !== 'adminSchoolTip');
    if (tokens.length) anchorEl.setAttribute('aria-describedby', tokens.join(' '));
    else anchorEl.removeAttribute('aria-describedby');
  }

  function setTooltipDescriptionOwner(anchorEl) {
    if (describedHoverAnchor && describedHoverAnchor !== anchorEl) {
      unlinkTooltipDescription(describedHoverAnchor);
    }
    describedHoverAnchor = anchorEl instanceof Element ? anchorEl : null;
    linkTooltipDescription(describedHoverAnchor);
  }

  function clearTooltipDescriptionOwner() {
    unlinkTooltipDescription(describedHoverAnchor);
    describedHoverAnchor = null;
  }

  function hideHoverPresentation() {
    if (tipMode !== 'hover') return;
    placementEpoch += 1;
    clearTooltipDescriptionOwner();
    if (tipEl) {
      tipEl.style.display = 'none';
      tipEl.setAttribute('aria-hidden', 'true');
    }
    activeHoverAnchor = null;
    hoverTipSize = null;
    cancelHoverPlacement();
  }

  function showTooltipForElement(anchorEl, ev, opts = {}) {
    if (!(anchorEl instanceof Element)) return false;

    const sid = studentSidForAnchor(anchorEl);
    const name = (anchorEl.textContent || '').trim();
    const stu = findStudent(sid, name);
    const attendanceSubject = tooltipSubjectForAnchor(anchorEl, opts.subject);
    if (!stu) return false;

    const variant = opts.variant || 'default';
    tipVariant = variant;
    tipMode = opts.fixed ? 'fixed' : 'hover';
    const renderEpoch = ++placementEpoch;

    let includeVideo = true;
    let includeTests = false;

    if (variant === 'log') {
      includeVideo = false;
    }

    const el = ensureTip();
    if (tipMode === 'fixed') {
      focusTransitionEpoch += 1;
      clearTooltipDescriptionOwner();
      focusHoverAnchor = null;
      focusTooltipDismissed = false;
      pointerHoverAnchor = null;
      lastPointerPoint = null;
      el.setAttribute('role', 'region');
      el.setAttribute('aria-label', '학생 정보 팝업');
    } else {
      el.setAttribute('role', 'tooltip');
      el.removeAttribute('aria-label');
    }
    el.setAttribute('aria-hidden', 'false');
    const useStudentWorkLayout = opts.layout === 'student-work';
    if (!useStudentWorkLayout) resetStudentWorkTooltipPlacement();
    el.innerHTML = variant === 'today'
      ? buildTodayNameTipHtml(stu, { attendanceSubject })
      : buildTipHtml(stu, { includeVideo, includeTests, studentWorkLayout: useStudentWorkLayout, attendanceSubject });
    el.style.display = 'block';

    // 고정 모드(로그 모달 등)에서는 드래그 가능해야 하므로 pointer-events: auto
    if (tipMode === 'fixed') {
      el.style.pointerEvents = 'auto';
      el.style.cursor = 'grab';
    } else {
      el.style.pointerEvents = 'none';
      el.style.cursor = 'default';
    }

    if (tipMode === 'hover') {
      activeHoverAnchor = anchorEl;
      setTooltipDescriptionOwner(anchorEl);
      hoverTipSize = null;
      if (ev) {
        scheduleHoverPlacement(ev.clientX, ev.clientY, { remeasure: true });
      } else {
        requestAnimationFrame(() => {
          if (placementEpoch !== renderEpoch || !tipEl || tipMode !== 'hover' || tipEl.style.display === 'none') return;
          const r = anchorEl.getBoundingClientRect();
          scheduleHoverPlacement(r.right, r.top, { remeasure: true });
        });
      }
    } else {
      activeHoverAnchor = null;
      cancelHoverPlacement();
      requestAnimationFrame(() => {
        if (placementEpoch !== renderEpoch || !tipEl || tipMode !== 'fixed' || tipEl.style.display === 'none') return;
        if (useStudentWorkLayout) placeForStudentWorkLayout();
        else placeForLogModal();
      });
    }
    return true;
  }

  // ───────────────────────────────────────────
  // 전역 헬퍼
  // ───────────────────────────────────────────
  window.showStudentTooltipForElement = function (anchorEl, opts) {
    try {
      showTooltipForElement(anchorEl, null, {
        fixed: !!(opts && opts.fixed),
        variant: opts?.variant || 'default',
        layout: opts?.layout,
        subject: opts?.subject
      });
    } catch (e) { console.warn(e); }
  };

  window.showStudentTooltipForSid = function (sid, opts) {
    const safeSid = window.CSS?.escape ? CSS.escape(String(sid)) : String(sid).replace(/"/g, '\\"');
    const el =
      document.querySelector(`a.stuName[data-sid="${safeSid}"]`)
      || document.querySelector(`tr[data-sid="${safeSid}"] .stuName`);
    if (el) {
      try {
        if (!el.dataset.sid) el.dataset.sid = String(sid);
        showTooltipForElement(el, null, {
          fixed: !!(opts && opts.fixed),
          variant: opts?.variant || 'default',
          layout: opts?.layout,
          subject: opts?.subject || tooltipSubjectForAnchor(el)
        });
      } catch (e) { console.warn(e); }
    }
  };

  window.hideStudentTooltip = function () {
    if (!tipEl) return;
    focusTransitionEpoch += 1;
    clearTooltipDescriptionOwner();
    placementEpoch += 1;
    tipEl.style.display = 'none';
    tipEl.setAttribute('aria-hidden', 'true');
    tipMode = 'hover';
    tipVariant = 'default';
    tipEl.style.pointerEvents = 'none';
    tipEl.style.cursor = 'default';
    resetStudentWorkTooltipPlacement();
    dragState = null;
    activeHoverAnchor = null;
    pointerHoverAnchor = null;
    focusHoverAnchor = null;
    focusTooltipDismissed = false;
    lastPointerPoint = null;
    hoverTipSize = null;
    cancelHoverPlacement();
  };

  // ───────────────────────────────────────────
  // 기존 hover 모드
  // ───────────────────────────────────────────
  function getHoverTooltipHost(el) {
    return el?.closest?.('#todayWrap, #doneWrap, #allWrap') || null;
  }

  function onOver(ev) {
    if (!(ev.target instanceof Element)) return;
    const a = ev.target.closest('a.stuName');
    if (!a) return;
    if (!getHoverTooltipHost(a)) return;
    if (tipMode === 'fixed') return;
    pointerHoverAnchor = a;
    lastPointerPoint = { x: ev.clientX, y: ev.clientY };
    if (focusHoverAnchor) return;
    if (activeHoverAnchor === a && tipEl?.style.display !== 'none') {
      scheduleHoverPlacement(ev.clientX, ev.clientY);
      return;
    }
    showTooltipForElement(a, ev, { fixed: false, variant: 'today' });
  }

  function onMove(ev) {
    if (!(ev.target instanceof Element)) return;
    const a = ev.target.closest('a.stuName');
    if (!a || !getHoverTooltipHost(a)) return;
    pointerHoverAnchor = a;
    lastPointerPoint = { x: ev.clientX, y: ev.clientY };
    if (focusHoverAnchor) return;
    if (!tipEl || tipEl.style.display === 'none') return;
    if (tipMode !== 'hover') return;
    scheduleHoverPlacement(ev.clientX, ev.clientY);
  }

  function onOut(ev) {
    if (!(ev.target instanceof Element)) return;
    if (tipMode !== 'hover') return;
    const from = ev.target.closest('a.stuName');
    const fromHost = getHoverTooltipHost(from);
    if (from && !fromHost) return;
    const to = (ev.relatedTarget instanceof Element) ? ev.relatedTarget.closest('a.stuName') : null;
    const toHost = getHoverTooltipHost(to);
    if (from && toHost === fromHost) return;
    if (from) {
      if (pointerHoverAnchor === from) pointerHoverAnchor = null;
      lastPointerPoint = null;
      if (focusHoverAnchor && !focusTooltipDismissed) return;
      hideHoverPresentation();
    }
  }

  function onFocusIn(ev) {
    if (!(ev.target instanceof Element)) return;
    const a = ev.target.closest('a.stuName');
    if (!a || !getHoverTooltipHost(a)) return;
    if (tipMode === 'fixed') return;

    focusTransitionEpoch += 1;
    if (focusHoverAnchor && focusHoverAnchor !== a) unlinkTooltipDescription(focusHoverAnchor);
    focusHoverAnchor = a;
    focusTooltipDismissed = false;
    if (showTooltipForElement(a, null, { fixed: false, variant: 'today' })) {
      setTooltipDescriptionOwner(a);
    } else {
      focusHoverAnchor = null;
      hideHoverPresentation();
    }
  }

  function onFocusOut(ev) {
    if (!(ev.target instanceof Element)) return;
    const from = ev.target.closest('a.stuName');
    if (!from || !getHoverTooltipHost(from) || focusHoverAnchor !== from) return;
    const transitionEpoch = ++focusTransitionEpoch;
    queueMicrotask(() => {
      if (transitionEpoch !== focusTransitionEpoch || focusHoverAnchor !== from) return;
      const active = document.activeElement;
      const activeAnchor = active instanceof Element ? active.closest('a.stuName') : null;
      if (activeAnchor && getHoverTooltipHost(activeAnchor)) return;

      const wasDismissed = focusTooltipDismissed;
      focusHoverAnchor = null;
      focusTooltipDismissed = false;
      if (tipMode === 'fixed') return;

      if (!wasDismissed && pointerHoverAnchor && lastPointerPoint) {
        showTooltipForElement(pointerHoverAnchor, lastPointerPoint, { fixed: false, variant: 'today' });
        return;
      }
      hideHoverPresentation();
    });
  }

  function onKeyDown(ev) {
    if (ev.key !== 'Escape' || tipMode === 'fixed') return;
    if (!(ev.target instanceof Element)) return;
    const a = ev.target.closest('a.stuName');
    if (!a || !getHoverTooltipHost(a) || focusHoverAnchor !== a) return;
    if (focusTooltipDismissed || !tipEl || tipEl.style.display === 'none') return;

    focusTransitionEpoch += 1;
    focusTooltipDismissed = true;
    pointerHoverAnchor = null;
    lastPointerPoint = null;
    hideHoverPresentation();
    ev.preventDefault();
    ev.stopPropagation();
  }

  function bindTooltipHosts() {
    ['todayWrap', 'doneWrap', 'allWrap'].forEach((id) => {
      const host = document.getElementById(id);
      if (!host || host._studentTooltipBound) return;
      host._studentTooltipBound = true;
      host.addEventListener('pointerover', onOver);
      host.addEventListener('pointermove', onMove);
      host.addEventListener('pointerout', onOut);
      host.addEventListener('focusin', onFocusIn);
      host.addEventListener('focusout', onFocusOut);
      host.addEventListener('keydown', onKeyDown);
    });
  }
  function onTodayRendered() {
    focusTransitionEpoch += 1;
    if (tipMode === 'hover') {
      hideHoverPresentation();
    }
    pointerHoverAnchor = null;
    focusHoverAnchor = null;
    focusTooltipDismissed = false;
    lastPointerPoint = null;
    bindTooltipHosts();
  }
  function onAllRendered() {
    focusTransitionEpoch += 1;
    if (tipMode === 'hover') {
      hideHoverPresentation();
    }
    pointerHoverAnchor = null;
    focusHoverAnchor = null;
    focusTooltipDismissed = false;
    lastPointerPoint = null;
    bindTooltipHosts();
  }
  bindTooltipHosts();
  document.addEventListener('today:rendered', onTodayRendered);
  document.addEventListener('all:rendered', onAllRendered);
  window.addEventListener('resize', () => {
    hoverTipSize = null;
    if (!tipEl || tipMode !== 'hover' || tipEl.style.display === 'none') return;
    if (!focusHoverAnchor && lastPointerPoint) {
      scheduleHoverPlacement(lastPointerPoint.x, lastPointerPoint.y, { remeasure: true });
      return;
    }
    const anchor = focusHoverAnchor || activeHoverAnchor;
    if (!anchor || resizePlacementFrame) return;
    const resizeEpoch = placementEpoch;
    resizePlacementFrame = requestAnimationFrame(() => {
      resizePlacementFrame = 0;
      if (resizeEpoch !== placementEpoch || !tipEl || tipMode !== 'hover' || tipEl.style.display === 'none') return;
      const r = anchor.getBoundingClientRect();
      scheduleHoverPlacement(r.right, r.top, { remeasure: true });
    });
  });
  // the fixed student-operation tooltip explicitly through showStudentTooltipForSid().
}
