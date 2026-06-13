// /js/admin/features/calendar.js
// FullCalendar 월 뷰 + 날짜별 인원 카운트 뱃지 + 출결 모달(+주말 슬롯 선택/보강 병합 저장 - 멀티 슬롯 지원)
import { $, toast } from '../core/utils.js';
import { state } from '../core/state.js';
import { getAdminDate } from '../core/adminDate.js';
import { renderTimeGraphForDate } from './timeGraph.js';
import { flattenSchoolCalendarRows, getActiveSchoolCalendarYear } from '../../shared/schoolCalendar.js';
import { applySearchPlaceholder, matchesSearchKey, normalizeSearch, studentSearchKey } from '../../shared/search.js';
import { buildMakeupExportRows, buildPendingMakeups, formatMakeupDate, makeupExportRowsToCsv } from './makeupPending.js';

export function initCalendar() {
  const calendarEl = $('calendar'); if (!calendarEl) return;

  const CT = { 'Content-Type': 'application/json' };
  const WCHR = '일월화수목금토';
  const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
  const WEEK_START_DAY = 1;
  const MAKEUP_SLOTS = [1, 2];
  const MAIN_WEEK_INDEX = 2;
  const MAKEUP_ARRIVE_BY_SLOT = { 1: '13:00', 2: '18:00' };
  const ymd = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  const yoil = dateStr => WCHR[new Date(dateStr).getDay()];
  const isWeekend = dateStr => ['토', '일'].includes(yoil(dateStr));

  function toSafeDate(year, month, day) {
    const y = Number.parseInt(String(year), 10);
    const m = Number.parseInt(String(month), 10);
    const d = Number.parseInt(String(day), 10);
    if (!Number.isFinite(y) || !Number.isFinite(m) || !Number.isFinite(d)) return null;
    const dt = new Date(y, m - 1, d);
    if (dt.getFullYear() !== y || dt.getMonth() !== (m - 1) || dt.getDate() !== d) return null;
    return dt;
  }

  function addDays(date, days) {
    const next = new Date(date.getFullYear(), date.getMonth(), date.getDate());
    next.setDate(next.getDate() + days);
    return next;
  }

  function startOfWeek(date) {
    const d = new Date(date.getFullYear(), date.getMonth(), date.getDate());
    const offset = (d.getDay() - WEEK_START_DAY + 7) % 7;
    d.setDate(d.getDate() - offset);
    return d;
  }

  function rollingFiveWeekRange(currentDate) {
    const middleWeekStart = startOfWeek(currentDate);
    const start = addDays(middleWeekStart, -7 * MAIN_WEEK_INDEX);
    return { start, end: addDays(start, 35) };
  }

  function weekTitleForRange(startDate) {
    const middleWeekStart = addDays(startOfWeek(startDate), 7 * MAIN_WEEK_INDEX);
    const titleDate = middleWeekStart;
    const year = String(titleDate.getFullYear()).slice(2);
    const month = titleDate.getMonth() + 1;
    const week = Math.floor((titleDate.getDate() - 1) / 7) + 1;
    return `${year}년 ${month}월 ${week}주차`;
  }

  function isMainWeekDate(date, rangeStart) {
    if (!date || !rangeStart) return false;
    const mainWeekStart = addDays(startOfWeek(rangeStart), 7 * MAIN_WEEK_INDEX);
    return ymd(startOfWeek(date)) === ymd(mainWeekStart);
  }

  function parseMonthDayTokens(raw) {
    const txt = String(raw || '').trim();
    if (!txt) return [];
    const out = [];
    const re = /(\d{1,2})\s*[/.]\s*(\d{1,2})|(\d{1,2})\s*월\s*(\d{1,2})\s*일?/g;
    let m = null;
    while ((m = re.exec(txt)) !== null) {
      const month = Number.parseInt(m[1] || m[3], 10);
      const day = Number.parseInt(m[2] || m[4], 10);
      if (!Number.isFinite(month) || !Number.isFinite(day)) continue;
      out.push({
        month,
        day,
        index: m.index,
      });
    }
    return out;
  }

  function parseDateSpans(raw, year, preferRange = false) {
    const txt = String(raw || '').trim();
    if (!txt) return [];

    const tokens = parseMonthDayTokens(txt);
    if (!tokens.length) return [];

    const out = [];
    const addSpan = (startDate, endDate) => {
      if (!startDate || !endDate) return;
      if (startDate > endDate) return;
      out.push({
        start: ymd(startDate),
        end: ymd(addDays(endDate, 1)), // FullCalendar all-day end is exclusive.
      });
    };

    const hasRangeMark = /[~\-–—∼～]/.test(txt);
    if (preferRange && hasRangeMark && tokens.length >= 2) {
      const first = tokens[0];
      const second = tokens[1];
      const startDate = toSafeDate(year, first.month, first.day);
      const endYear = second.month < first.month ? year + 1 : year;
      const endDate = toSafeDate(endYear, second.month, second.day);
      addSpan(startDate, endDate);

      // Handle extra dates in same cell text (rare but possible).
      for (let i = 2; i < tokens.length; i += 1) {
        const t = tokens[i];
        const d = toSafeDate(year, t.month, t.day);
        addSpan(d, d);
      }
    } else {
      for (const t of tokens) {
        const d = toSafeDate(year, t.month, t.day);
        addSpan(d, d);
      }
    }

    const seen = new Set();
    return out.filter((span) => {
      const key = `${span.start}|${span.end}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  }

  function buildSchoolExamEvents(payload = state.schoolCal) {
    const activeYearRaw = getActiveSchoolCalendarYear(payload) || new Date().getFullYear();
    const activeYear = Number.parseInt(String(activeYearRaw), 10) || new Date().getFullYear();
    const rows = flattenSchoolCalendarRows(payload, String(activeYear), { splitByGrade: true });
    if (!Array.isArray(rows) || !rows.length) return [];

    const schoolHasGradeRows = new Map();
    rows.forEach((row) => {
      const school = String(row?.school || '').trim();
      if (!school) return;
      const grade = String(row?.grade || '').trim();
      if (grade) schoolHasGradeRows.set(school, true);
      else if (!schoolHasGradeRows.has(school)) schoolHasGradeRows.set(school, false);
    });

    const rawEvents = [];
    const examSubjectForRow = (row) => String(
      row?.phase ||
      row?.subject ||
      row?.curriculum ||
      row?.course ||
      '수학'
    ).trim() || '수학';
    const pushRawEvent = ({ kind, subject, label, school, grade, span, range, note, sourceText }) => {
      if (!school || !span?.start || !span?.end) return;
      const subjectName = String(subject || '').trim() || '수학';
      rawEvents.push({
        kind,
        subject: subjectName,
        label: label || `${subjectName} 시험일`,
        school,
        grade: String(grade || '').trim(),
        start: span.start,
        end: span.end,
        range: String(range || '').trim(),
        note: String(note || '').trim(),
        sourceText: String(sourceText || '').trim(),
      });
    };

    rows.forEach((row) => {
      const school = String(row?.school || '').trim();
      if (!school) return;

      const grade = String(row?.grade || '').trim();
      if (!grade && schoolHasGradeRows.get(school)) return; // avoid common+grade duplicates
      const subject = examSubjectForRow(row);

      parseDateSpans(row?.midtermMath, activeYear, false).forEach((span) => {
        pushRawEvent({
          kind: 'math',
          subject,
          label: `${subject} 시험일`,
          school,
          grade,
          span,
          sourceText: row?.midtermMath,
        });
      });

      parseDateSpans(row?.finalMath, activeYear, false).forEach((span) => {
        pushRawEvent({
          kind: 'math',
          subject,
          label: `${subject} 시험일`,
          school,
          grade,
          span,
          sourceText: row?.finalMath,
        });
      });
    });

    const grouped = new Map();
    for (const row of rawEvents) {
      const key = `${row.kind}|${row.school}|${row.subject}|${row.start}|${row.end}`;
      let bucket = grouped.get(key);
      if (!bucket) {
        bucket = {
          kind: row.kind,
          subject: row.subject,
          label: row.label,
          school: row.school,
          start: row.start,
          end: row.end,
          grades: new Set(),
          ranges: new Set(),
          notes: new Set(),
          sourceTexts: new Set(),
        };
        grouped.set(key, bucket);
      }

      if (row.grade) bucket.grades.add(row.grade);
      if (row.range) bucket.ranges.add(row.range);
      if (row.note) bucket.notes.add(row.note);
      if (row.sourceText) bucket.sourceTexts.add(row.sourceText);
    }

    function shortSchoolName(name) {
      const s = String(name || '').trim();
      if (!s) return '';
      // 특수 교명(외고/국제고 등)은 그대로, 일반 학교는 끝 글자(고/중)만 축약
      if (/(외고|국제고|과학고|영재고)$/.test(s)) return s;
      return s.replace(/[고중]$/, '');
    }

    function compactGradeToken(gradeSet) {
      const grades = [...gradeSet].map((g) => String(g || '').trim()).filter(Boolean);
      if (!grades.length) return '';
      const nums = grades
        .map((g) => {
          const m = g.match(/\d+/);
          return m ? Number.parseInt(m[0], 10) : NaN;
        })
        .filter((n) => Number.isFinite(n));
      if (nums.length === grades.length) {
        const uniq = [...new Set(nums)].sort((a, b) => a - b);
        return uniq.join('·');
      }
      return grades.join('·');
    }

    const order = { math: 1 };
    const palette = {
      math: { bg: '#0284c7', border: '#0369a1' },
    };

    return [...grouped.values()]
      .sort((a, b) => {
        const dateCmp = String(a.start).localeCompare(String(b.start));
        if (dateCmp !== 0) return dateCmp;
        const typeCmp = (order[a.kind] || 99) - (order[b.kind] || 99);
        if (typeCmp !== 0) return typeCmp;
        const subjectCmp = String(a.subject || '').localeCompare(String(b.subject || ''), 'ko');
        if (subjectCmp !== 0) return subjectCmp;
        return String(a.school).localeCompare(String(b.school), 'ko');
      })
      .map((row) => {
        const gradeToken = compactGradeToken(row.grades);
        const shortSchool = shortSchoolName(row.school);
        const subject = String(row.subject || '').trim() || '수학';
        const title = `${shortSchool}${gradeToken ? gradeToken : ''} ${subject}`;

        const gradeList = [...row.grades].sort((a, b) => String(a).localeCompare(String(b), 'ko')).join(', ');
        const headline = gradeList
          ? `${row.school} ${gradeList} ${row.label}`
          : `${row.school} ${row.label}`;
        const tooltipParts = [headline.trim()];

        if (row.ranges.size === 1) tooltipParts.push(`범위: ${[...row.ranges][0]}`);
        else if (row.ranges.size > 1) tooltipParts.push(`범위: 학교별 상이 (${row.ranges.size}개)`);

        if (row.notes.size === 1) tooltipParts.push(`비고: ${[...row.notes][0]}`);
        else if (row.notes.size > 1) tooltipParts.push(`비고: 학교별 상이 (${row.notes.size}개)`);

        if (row.sourceTexts.size === 1) tooltipParts.push(`일정: ${[...row.sourceTexts][0]}`);

        const color = palette[row.kind] || { bg: '#64748b', border: '#475569' };
        return {
          title,
          start: row.start,
          end: row.end,
          allDay: true,
          classNames: ['school-exam-event', `school-exam-${row.kind}`],
          backgroundColor: color.bg,
          borderColor: color.border,
          textColor: '#ffffff',
          extendedProps: {
            kind: row.kind,
            subject,
            order: order[row.kind] || 99,
            tooltip: tooltipParts.join('\n'),
          },
        };
      });
  }

  let countMap = {};
  // 보강/주말타임 맵 캐시
  let EXTRA = {};     // {"YYYY-MM-DD":[sid,...]}
  let WEEKEND = {};   // {"YYYY-MM-DD": {sid: 1|2|3 | [1,2,3]}}
  let CARRYOVER = {}; // {"by_absence":{"YYYY-MM-DD":{"sid":{state:"carried"}}}}

  // 슬롯 버튼 클릭 핸들러 중복 방지 플래그
  let slotClickBound = false;
  let makeupSelection = null;
  let manualMakeupSelectedSid = '';
  let manualMakeupSelectedDates = new Set();
  let manualAbsenceSelection = null;
  let manualAbsencePointerDate = '';
  let manualAbsencePointerAt = 0;

  // 유틸: 학생이 해당 요일 정규 등원하는지
  function hasWeekday(s, w) {
    return Object.keys(s).some(k => /^day\d+$/.test(k) && String(s[k]).startsWith(w));
  }

  function parseSlotNumbers(raw) {
    const values = Array.isArray(raw) ? raw : [raw];
    const slots = values.flatMap(value => {
      const matches = String(value ?? '').match(/\d+/g) || [];
      return matches.map(n => parseInt(n, 10));
    }).filter(n => MAKEUP_SLOTS.includes(n));
    return Array.from(new Set(slots)).sort((a, b) => a - b);
  }

  function slotGroupLabel(slots) {
    const nums = (slots || []).filter(slot => MAKEUP_SLOTS.includes(slot));
    return (nums.length ? nums : [1]).map(slot => `${slot}타임`).join('·');
  }

  function slotSortValue(slots) {
    const nums = (slots || []).filter(slot => MAKEUP_SLOTS.includes(slot));
    return nums.length ? Math.min(...nums) : 99;
  }

  function getRegularSlots(stu, dateStr) {
    const w = yoil(dateStr);
    const values = Object.keys(stu || {})
      .filter(k => /^day\d+$/.test(k) && stu[k])
      .map(k => String(stu[k]))
      .filter(v => v.startsWith(w));
    return parseSlotNumbers(values);
  }

  function getMakeupSlots(dateStr, sid) {
    const slots = parseSlotNumbers(WEEKEND?.[dateStr]?.[String(sid)]);
    return slots.length ? slots : [1];
  }

  function serializeSlots(slots) {
    const nums = parseSlotNumbers(slots);
    if (nums.length <= 1) return nums[0] || 1;
    return nums;
  }

  function combinedSlotsForStudent(stu, dateStr, slots = []) {
    const merged = Array.from(new Set([
      ...getRegularSlots(stu || {}, dateStr),
      ...parseSlotNumbers(slots),
    ])).sort((a, b) => a - b);
    return merged.length ? merged : [1];
  }

  function slotsForAttendStudent(stu, dateStr, extras = [], slotMap = {}) {
    const sid = String(stu?.id || '');
    const regular = getRegularSlots(stu, dateStr);
    const extraSlots = extras.includes(sid) ? parseSlotNumbers(slotMap?.[sid]) : [];
    const merged = Array.from(new Set([...regular, ...extraSlots])).sort((a, b) => a - b);
    return merged.length ? merged : [1];
  }

  function getAbsentSlots(dateStr, sid) {
    return parseSlotNumbers(state.absentSlotsByDate?.[dateStr]?.[String(sid)]);
  }

  function subtractAbsentSlots(dateStr, sid, slots) {
    const fullAbsent = new Set((state.absentByDate?.[dateStr] || []).map(String));
    if (fullAbsent.has(String(sid))) return [];
    const absentSlots = new Set(getAbsentSlots(dateStr, sid));
    if (!absentSlots.size) return slots;
    return (slots || []).filter(slot => !absentSlots.has(slot));
  }

  function availableSlotsForAttendStudent(stu, dateStr, extras = [], slotMap = {}) {
    const slots = slotsForAttendStudent(stu, dateStr, extras, slotMap);
    return subtractAbsentSlots(dateStr, String(stu?.id || ''), slots);
  }

  function normalizeStudentIdentity(value) {
    return String(value || '')
      .trim()
      .replace(/\s*[\(\[][^()\[\]]+[\)\]]\s*$/u, '')
      .replace(/\s+/g, '');
  }

  function studentSchoolLabel(stu) {
    return String(
      stu?.school ||
      stu?.schoolName ||
      stu?.highSchool ||
      stu?.middleSchool ||
      stu?.high ||
      stu?.middle ||
      stu?.schoolHigh ||
      stu?.schoolMiddle ||
      ''
    ).trim();
  }

  function normalizeSchoolIdentity(value) {
    return normalizeStudentIdentity(value)
      .replace(/고등학교$/u, '고')
      .replace(/중학교$/u, '중');
  }

  function studentCourseLabel(stu) {
    return [
      stu?.curriculum || stu?.course || stu?.subject || stu?.className,
      stu?.subCurriculum,
    ].map(value => String(value || '').trim()).filter(Boolean).join(' ') || '수업';
  }

  function selectedMakeupStudentRecords() {
    if (!makeupSelection) return [];
    const selectedSid = String(makeupSelection.sid || '').trim();
    const selectedStudent = makeupSelection.student ||
      (state.students || []).find(stu => String(stu?.id || '') === selectedSid) ||
      {};
    const targetName = normalizeStudentIdentity(selectedStudent?.name || makeupSelection.name);
    const targetSchool = normalizeSchoolIdentity(studentSchoolLabel(selectedStudent) || makeupSelection.school);
    const seen = new Set();
    const records = [];

    (state.students || []).forEach(stu => {
      const sid = String(stu?.id || '').trim();
      const sameSid = selectedSid && sid === selectedSid;
      const sameName = targetName && normalizeStudentIdentity(stu?.name) === targetName;
      const school = normalizeSchoolIdentity(studentSchoolLabel(stu));
      const sameSchool = !!targetSchool && !!school && school === targetSchool;
      if (!sameSid && !(sameName && sameSchool)) return;
      const key = sid || `${normalizeStudentIdentity(stu?.name)}|${studentCourseLabel(stu)}`;
      if (seen.has(key)) return;
      seen.add(key);
      records.push(stu);
    });

    if (!records.length && (selectedSid || targetName)) records.push(selectedStudent);
    return records;
  }

  function selectedStudentScheduleLabels(dateStr) {
    const records = selectedMakeupStudentRecords();
    if (!records.length) return [];
    const extras = new Set((EXTRA[dateStr] || []).map(String));
    const absent = new Set((state.absentByDate?.[dateStr] || []).map(String));
    const labels = [];
    const seen = new Set();

    const addLabel = (stu, slot, kind = 'regular', note = '') => {
      if (!MAKEUP_SLOTS.includes(slot)) return;
      const course = studentCourseLabel(stu);
      const label = kind === 'makeup'
        ? `${course} 보강 ${slot}타임${note}`
        : `${course} ${slot}타임`;
      const sid = String(stu?.id || '').trim();
      const key = `${sid || normalizeStudentIdentity(stu?.name)}|${course}|${kind}|${slot}|${note}`;
      if (seen.has(key)) return;
      seen.add(key);
      labels.push(label);
    };

    records.forEach(stu => {
      const sid = String(stu?.id || '').trim();
      const isAbsent = sid && absent.has(sid);
      const absentSlots = new Set(getAbsentSlots(dateStr, sid));
      if (!isAbsent) {
        getRegularSlots(stu, dateStr)
          .filter(slot => !absentSlots.has(slot))
          .forEach(slot => addLabel(stu, slot, 'regular'));
      }
      if (sid && extras.has(sid)) {
        getMakeupSlots(dateStr, sid).forEach(slot => {
          const note = isAbsent || absentSlots.has(slot) ? ' (결석)' : '';
          addLabel(stu, slot, 'makeup', note);
        });
      }
    });

    return labels;
  }

  function refreshMakeupConflictHints() {
    document.querySelectorAll('.makeup-conflict-list').forEach(el => el.remove());
    document.querySelectorAll('.fc-daygrid-day.has-makeup-conflicts').forEach(cell => {
      cell.classList.remove('has-makeup-conflicts');
    });
    if (!makeupSelection) return;

    document.querySelectorAll('.fc-daygrid-day').forEach(cell => {
      const dateStr = cell.getAttribute('data-date');
      if (!dateStr) return;
      const labels = selectedStudentScheduleLabels(dateStr);
      if (!labels.length) return;
      const frame = cell.querySelector('.fc-daygrid-day-frame') || cell;
      const box = document.createElement('div');
      box.className = 'makeup-conflict-list';
      box.innerHTML = labels.map(label => `<span>${escapeHtml(label)}</span>`).join('');
      frame.appendChild(box);
      cell.classList.add('has-makeup-conflicts');
    });
  }

  function addSlotCounts(slotSets, sid, slots, fallbackSlots = []) {
    const validSlots = slots.filter(slot => MAKEUP_SLOTS.includes(slot));
    const finalSlots = validSlots.length
      ? validSlots
      : fallbackSlots.filter(slot => MAKEUP_SLOTS.includes(slot));
    (finalSlots.length ? finalSlots : [1]).forEach(slot => slotSets[slot].add(String(sid)));
  }

  async function preloadExtraWeekend() {
    try { EXTRA = await fetch('/api/extra-attend', { cache: 'no-store' }).then(r => r.json()); } catch { EXTRA = {}; }
    try { WEEKEND = await fetch('/api/weekend-slots', { cache: 'no-store' }).then(r => r.json()); } catch { WEEKEND = {}; }
    try { CARRYOVER = await fetch('/api/makeup-carryover', { cache: 'no-store' }).then(r => r.json()); } catch { CARRYOVER = {}; }
    try { applyAbsentPayload(await fetch('/api/absent', { cache: 'no-store' }).then(r => r.json())); } catch {}
    state.extra = EXTRA || {};
    window.extra = state.extra;
    CARRYOVER = normalizeCarryoverPayload(CARRYOVER);
  }

  function syncCalendarCellRatio() {
    const cell = calendarEl.querySelector('.fc-daygrid-day');
    if (!cell) return;
    const width = cell.getBoundingClientRect().width;
    if (!Number.isFinite(width) || width <= 0) return;
    calendarEl.style.setProperty('--calendar-cell-height', `${Math.round(width * 0.75)}px`);
  }

  // 캘린더 범위 내 날짜별 1/2타임 인원 카운트 계산(정규+보강 - 결석)
  async function fetchCountsForRange(start, end) {
    await preloadExtraWeekend();
    const days = []; const cur = new Date(start);
    while (cur < end) { days.push(ymd(cur)); cur.setDate(cur.getDate() + 1); }
    countMap = {};
    for (const dateStr of days) {
      const wchr = yoil(dateStr);
      const slotSets = Object.fromEntries(MAKEUP_SLOTS.map(slot => [slot, new Set()]));

      (state.students || []).forEach(stu => {
        if (!hasWeekday(stu, wchr)) return;
        addSlotCounts(slotSets, stu.id, getRegularSlots(stu, dateStr), [1]);
      });

      (EXTRA[dateStr] || []).map(String).forEach(sid => {
        addSlotCounts(slotSets, sid, getMakeupSlots(dateStr, sid), [1]);
      });

      (state.absentByDate?.[dateStr] || []).map(String).forEach(id => {
        MAKEUP_SLOTS.forEach(slot => slotSets[slot].delete(id));
      });
      const slotAbsences = state.absentSlotsByDate?.[dateStr] || {};
      Object.entries(slotAbsences).forEach(([sid, slotsRaw]) => {
        parseSlotNumbers(slotsRaw).forEach(slot => slotSets[slot]?.delete(String(sid)));
      });

      countMap[dateStr] = Object.fromEntries(MAKEUP_SLOTS.map(slot => [slot, slotSets[slot].size]));
    }
  }

  function refreshCountBadges() {
    document.querySelectorAll('.fc-daygrid-day').forEach(cell => {
      const dateStr = cell.getAttribute('data-date'); if (!dateStr) return;
      let badge = cell.querySelector('.att-count-badge');
      if (!badge) {
        badge = document.createElement('div'); badge.className = 'att-count-badge';
        cell.style.position = 'relative'; cell.appendChild(badge);
      }
      const counts = countMap[dateStr] || {};
      badge.textContent = `${counts[1] || 0}명 / ${counts[2] || 0}명`;
    });
    refreshMakeupConflictHints();
    syncCalendarCellRatio();
  }

  function escapeHtml(value) {
    return String(value ?? '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function escapeAttr(value) {
    return escapeHtml(value).replace(/"/g, '&quot;');
  }

  function makeupItemKey(item) {
    return `${item.source || 'absence'}|${item.sid}|${item.absenceDate}|${item.slot || ''}|${item.manualKey || ''}`;
  }

  function makeupCarryoverKey(item) {
    const sid = String(item?.sid || '').trim();
    const slot = parseSlotNumbers(item?.slot)[0];
    return slot ? `${sid}|${slot}` : sid;
  }

  function normalizeCarryoverPayload(data) {
    const byAbsence = data?.by_absence && typeof data.by_absence === 'object' ? data.by_absence : {};
    const manual = data?.manual && typeof data.manual === 'object' ? data.manual : {};
    return { by_absence: byAbsence, manual };
  }

  function normalizeAbsentSlotMap(value) {
    const out = {};
    if (!value || typeof value !== 'object') return out;
    for (const [date, sidMap] of Object.entries(value)) {
      if (!DATE_RE.test(String(date)) || !sidMap || typeof sidMap !== 'object') continue;
      const rows = {};
      for (const [sid, slots] of Object.entries(sidMap)) {
        const nums = parseSlotNumbers(slots);
        if (String(sid).trim() && nums.length) rows[String(sid)] = nums;
      }
      if (Object.keys(rows).length) out[date] = rows;
    }
    return out;
  }

  function getTodayPlannerSidSet() {
    return new Set(
      Array.from(document.querySelectorAll('#todayWrap tr[data-sid]'))
        .map(tr => String(tr.dataset.sid || '').trim())
        .filter(Boolean)
    );
  }

  function sortPlannerItems(items) {
    const todaySids = getTodayPlannerSidSet();
    return [...items].sort((a, b) => {
      const todayA = todaySids.has(String(a.sid)) ? 0 : 1;
      const todayB = todaySids.has(String(b.sid)) ? 0 : 1;
      if (todayA !== todayB) return todayA - todayB;
      const nameCmp = String(a.name || '').localeCompare(String(b.name || ''), 'ko', { numeric: true });
      if (nameCmp !== 0) return nameCmp;
      return String(a.absenceDate || '').localeCompare(String(b.absenceDate || '')) ||
        Number(a.slot || 0) - Number(b.slot || 0) ||
        String(a.sid).localeCompare(String(b.sid), 'ko', { numeric: true });
    });
  }

  function downloadTextFile(filename, contents, type) {
    const blob = new Blob([contents], { type });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  function exportMakeupRosterCsv() {
    const rows = buildMakeupExportRows(sortPlannerItems(getPendingMakeups()));
    if (!rows.length) {
      toast('내보낼 보강 명단이 없습니다.');
      return;
    }

    const dateStr = String(getAdminDate() || '').trim() || new Date().toISOString().slice(0, 10);
    downloadTextFile(`보강명단_${dateStr}.csv`, makeupExportRowsToCsv(rows), 'text/csv;charset=utf-8');
    toast('보강 명단 CSV 내보내기 완료');
  }

  function ensureManualMakeupModal() {
    if (document.getElementById('manualMakeupModal')) return;
    document.body.insertAdjacentHTML('beforeend', `
      <div id="manualMakeupModal" class="modal-backdrop manual-makeup-modal" role="dialog" aria-modal="true" aria-labelledby="manualMakeupTitle">
        <div class="modal-panel narrow column manual-makeup-panel">
          <div class="manual-makeup-header">
            <div>
              <h3 id="manualMakeupTitle">결석 추가</h3>
              <p>학생/과목을 고른 뒤 운영판 캘린더에서 결석 날짜를 선택합니다.</p>
            </div>
            <div class="manual-makeup-actions">
              <button type="button" id="manualMakeupSave" class="selection-btn primary">날짜 선택</button>
              <button type="button" id="manualMakeupClose" class="selection-btn">닫기</button>
            </div>
          </div>
          <div class="manual-makeup-flow">
            <section class="manual-makeup-student-step" aria-labelledby="manualMakeupStudentTitle">
              <div class="manual-step-title" id="manualMakeupStudentTitle">학생/과목</div>
              <div class="selection-search-wrap manual-makeup-search">
                <div class="selection-search-row">
                  <input id="manualMakeupSearch" type="search" autocomplete="off" placeholder="학생/과목 검색" aria-label="학생/과목 검색">
                  <button type="button" id="manualMakeupPick" class="selection-btn" disabled>선택</button>
                </div>
                <div id="manualMakeupHint" class="selection-search-hint" aria-live="polite"></div>
              </div>
              <ul id="manualMakeupList" class="manual-makeup-list"></ul>
            </section>
          </div>
        </div>
      </div>
    `);

    const modal = $('manualMakeupModal');
    const search = $('manualMakeupSearch');
    applySearchPlaceholder(search, '학생/과목 검색');
    $('manualMakeupClose')?.addEventListener('click', () => { modal.style.display = 'none'; });
    modal?.addEventListener('click', (ev) => {
      if (ev.target === modal) modal.style.display = 'none';
    });
    search?.addEventListener('input', applyManualMakeupSearchFilter);
    search?.addEventListener('search', applyManualMakeupSearchFilter);
    search?.addEventListener('compositionend', applyManualMakeupSearchFilter);
    search?.addEventListener('keydown', (ev) => {
      if (ev.key === 'Enter') {
        ev.preventDefault();
        pickManualMakeupStudent();
        return;
      }
      if (ev.key !== 'Escape') return;
      search.value = '';
      applyManualMakeupSearchFilter();
    });
    $('manualMakeupPick')?.addEventListener('click', pickManualMakeupStudent);
    $('manualMakeupList')?.addEventListener('click', (ev) => {
      const row = ev.target.closest('li[data-id]');
      if (!row) return;
      setManualMakeupRowSelected(row, true);
    });
    $('manualMakeupList')?.addEventListener('change', (ev) => {
      const chk = ev.target.closest('.chk-sid');
      if (!chk) return;
      setManualMakeupRowSelected(chk.closest('li[data-id]'), chk.checked);
    });
    $('manualMakeupSave')?.addEventListener('click', startManualAbsenceCalendarSelection);
  }

  function manualMakeupRows() {
    return Array.from(document.querySelectorAll('#manualMakeupList li[data-id]'));
  }

  function setManualMakeupRowSelected(row, selected) {
    if (!row) return;
    const chk = row.querySelector('.chk-sid');
    if (!chk) return;
    manualMakeupRows().forEach(other => {
      const isSelected = selected && other === row;
      const otherChk = other.querySelector('.chk-sid');
      if (otherChk) otherChk.checked = isSelected;
      other.classList.toggle('selected', isSelected);
    });
    manualMakeupSelectedSid = selected ? String(row.dataset.id || '') : '';
    updateManualMakeupSaveState();
  }

  function applyManualMakeupSearchFilter() {
    const input = $('manualMakeupSearch');
    const hint = $('manualMakeupHint');
    const pick = $('manualMakeupPick');
    const queryText = input?.value || '';
    const needle = normalizeSearch(queryText);
    let visible = 0;
    manualMakeupRows().forEach(row => {
      const matches = matchesSearchKey(row.dataset.searchKey || '', queryText);
      row.hidden = !matches;
      row.classList.toggle('is-search-hidden', !matches);
      row.setAttribute('aria-hidden', matches ? 'false' : 'true');
      if (matches) visible += 1;
    });
    if (pick) pick.disabled = !needle || visible === 0;
    if (hint) hint.textContent = needle ? (visible ? `${visible}명` : '검색 결과 없음') : '';
  }

  function pickManualMakeupStudent() {
    const input = $('manualMakeupSearch');
    const hint = $('manualMakeupHint');
    const needle = normalizeSearch(input?.value);
    if (!needle) return;
    const rows = manualMakeupRows().filter(row => !row.hidden && !row.classList.contains('is-search-hidden'));
    const exact = rows.find(row => normalizeSearch(row.querySelector('.student-name')?.textContent) === needle);
    const row = exact || rows[0];
    if (!row) return;
    setManualMakeupRowSelected(row, true);
    row.scrollIntoView({ block: 'nearest' });
    const label = row.querySelector('.student-name')?.textContent || '';
    if (hint) hint.textContent = label ? `${label} 선택됨` : '선택됨';
  }

  function manualMakeupStudentRow(stu) {
    const course = studentCourseLabel(stu);
    const school = studentSchoolLabel(stu);
    const searchKey = studentSearchKey(stu, [school, course]);
    return `
      <li data-id="${escapeAttr(stu.id)}" data-search-key="${escapeAttr(searchKey)}" class="selection-student-row ${String(stu.id) === manualMakeupSelectedSid ? 'selected' : ''}">
        <label class="selection-student-label">
          <input type="radio" name="manualMakeupStudent" class="chk-sid" ${String(stu.id) === manualMakeupSelectedSid ? 'checked' : ''}>
          <span class="student-name">${escapeHtml(stu.name || '')}</span>
          <small>${escapeHtml([school, course].filter(Boolean).join(' · '))}</small>
        </label>
      </li>`;
  }

  function renderManualMakeupRows() {
    const list = $('manualMakeupList');
    if (!list) return;
    const rows = (state.students || []).slice()
      .sort((a, b) =>
        String(a.name || '').localeCompare(String(b.name || ''), 'ko', { numeric: true }) ||
        String(studentCourseLabel(a)).localeCompare(String(studentCourseLabel(b)), 'ko', { numeric: true })
      );
    list.innerHTML = rows.map(manualMakeupStudentRow).join('');
    applyManualMakeupSearchFilter();
    updateManualMakeupSaveState();
  }

  function manualMakeupSelectedDateList() {
    return Array.from(manualMakeupSelectedDates).filter(date => DATE_RE.test(date)).sort();
  }

  function updateManualMakeupSaveState() {
    const save = $('manualMakeupSave');
    if (save) save.disabled = !manualMakeupSelectedSid;
  }

  function selectedManualMakeupRow() {
    return manualMakeupRows().find(item => item.querySelector('.chk-sid')?.checked) || null;
  }

  function ensureManualAbsenceFocusGuide() {
    if (document.getElementById('manualAbsenceCalendarGuide')) return;
    calendarEl.insertAdjacentHTML('afterbegin', `
      <div id="manualAbsenceCalendarGuide" class="makeup-calendar-guide manual-absence-calendar-guide" hidden>
        <strong>운영판 캘린더에서 결석 날짜를 선택하세요</strong>
        <span id="manualAbsenceCalendarGuideSub"></span>
        <span id="manualAbsenceCalendarGuideDates"></span>
        <div class="manual-absence-guide-actions">
          <button type="button" id="manualAbsenceSave" class="selection-btn primary">선택 날짜 저장</button>
          <button type="button" id="manualAbsenceCancel" class="selection-btn">취소</button>
        </div>
      </div>
    `);
    $('manualAbsenceSave')?.addEventListener('click', saveManualAbsenceSelection);
    $('manualAbsenceCancel')?.addEventListener('click', cancelManualAbsenceSelection);
  }

  function refreshManualAbsenceDateMarks() {
    calendarEl.querySelectorAll('.fc-daygrid-day.manual-absence-selected').forEach(cell => {
      cell.classList.remove('manual-absence-selected');
      cell.removeAttribute('aria-pressed');
    });
    if (!manualAbsenceSelection) return;
    manualMakeupSelectedDateList().forEach(dateStr => {
      const cell = calendarEl.querySelector(`.fc-daygrid-day[data-date="${dateStr}"]`);
      if (!cell) return;
      cell.classList.add('manual-absence-selected');
      cell.setAttribute('aria-pressed', 'true');
    });
  }

  function updateManualAbsenceFocusUI() {
    ensureManualAbsenceFocusGuide();
    const active = !!manualAbsenceSelection;
    document.body.classList.toggle('manual-absence-selecting', active);
    calendarEl.classList.toggle('is-manual-absence-selecting', active);

    const guide = $('manualAbsenceCalendarGuide');
    const sub = $('manualAbsenceCalendarGuideSub');
    const datesEl = $('manualAbsenceCalendarGuideDates');
    const save = $('manualAbsenceSave');
    const dates = manualMakeupSelectedDateList();
    if (guide) guide.hidden = !active;
    if (sub) {
      const student = manualAbsenceSelection?.student || {};
      sub.textContent = active
        ? [studentSchoolLabel(student), studentCourseLabel(student), student?.name || manualAbsenceSelection.sid].filter(Boolean).join(' · ')
        : '';
    }
    if (datesEl) {
      datesEl.textContent = active
        ? (dates.length ? dates.map(formatMakeupDate).join(', ') : '날짜를 여러 개 선택할 수 있습니다.')
        : '';
    }
    if (save) save.disabled = !active || !dates.length;
    refreshManualAbsenceDateMarks();
  }

  function toggleManualAbsenceDate(dateStr) {
    if (!manualAbsenceSelection || !DATE_RE.test(String(dateStr || ''))) return;
    if (manualMakeupSelectedDates.has(dateStr)) manualMakeupSelectedDates.delete(dateStr);
    else manualMakeupSelectedDates.add(dateStr);
    updateManualAbsenceFocusUI();
  }

  function manualAbsenceDateFromEvent(ev) {
    if (!manualAbsenceSelection) return '';
    const target = ev.target instanceof Element ? ev.target : ev.target?.parentElement;
    const dayCell = target?.closest('.fc-daygrid-day[data-date]');
    if (!dayCell || !calendarEl.contains(dayCell)) return '';
    return dayCell.getAttribute('data-date') || '';
  }

  function recentlyHandledManualAbsenceDate(dateStr) {
    return !!dateStr && manualAbsencePointerDate === dateStr && Date.now() - manualAbsencePointerAt < 700;
  }

  function stopManualAbsenceCalendarEvent(ev) {
    ev.preventDefault?.();
    ev.stopPropagation?.();
    ev.stopImmediatePropagation?.();
  }

  function handleManualAbsencePointerDown(ev) {
    const dateStr = manualAbsenceDateFromEvent(ev);
    if (!dateStr) return false;
    stopManualAbsenceCalendarEvent(ev);
    manualAbsencePointerDate = dateStr;
    manualAbsencePointerAt = Date.now();
    toggleManualAbsenceDate(dateStr);
    return true;
  }

  function handleManualAbsenceCalendarClick(ev) {
    const dateStr = manualAbsenceDateFromEvent(ev);
    if (!dateStr) return false;
    stopManualAbsenceCalendarEvent(ev);
    if (!recentlyHandledManualAbsenceDate(dateStr)) toggleManualAbsenceDate(dateStr);
    return true;
  }

  function startManualAbsenceCalendarSelection(ev) {
    ev?.preventDefault?.();
    const row = selectedManualMakeupRow();
    const sid = String(row?.dataset.id || '').trim();
    if (!sid) {
      toast('결석 추가할 학생/과목을 선택해주세요.');
      return;
    }

    const student = (state.students || []).find(item => String(item?.id || '') === sid) || {};
    manualAbsenceSelection = { sid, student };
    manualMakeupSelectedSid = sid;
    manualMakeupSelectedDates = new Set();

    if (makeupSelection) {
      setMakeupSelection(null);
      closeMakeupSlotPicker();
      renderMakeupPlanner();
    }

    const modal = $('manualMakeupModal');
    if (modal) modal.style.display = 'none';
    updateManualAbsenceFocusUI();
    window.requestAnimationFrame(() => {
      calendarEl.scrollIntoView({ block: 'start', inline: 'nearest', behavior: 'smooth' });
    });
    toast('운영판 캘린더에서 결석 날짜를 선택하세요.');
  }

  function cancelManualAbsenceSelection() {
    manualAbsenceSelection = null;
    manualMakeupSelectedDates = new Set();
    updateManualAbsenceFocusUI();
  }

  async function saveManualAbsenceSelection(ev) {
    const btn = ev?.currentTarget;
    const sid = String(manualAbsenceSelection?.sid || '').trim();
    const dates = manualMakeupSelectedDateList();
    if (!sid) {
      toast('결석 추가할 학생/과목을 선택해주세요.');
      return;
    }
    if (!dates.length) {
      toast('결석 날짜를 선택해주세요.');
      return;
    }

    if (btn) btn.disabled = true;
    try {
      await preloadExtraWeekend();
      const latestRes = await fetch('/api/makeup-carryover', { cache: 'no-store' });
      const latest = latestRes.ok ? await latestRes.json().catch(() => ({})) : {};
      const next = normalizeCarryoverPayload(latest);
      const now = new Date().toISOString();
      const stu = (state.students || []).find(item => String(item?.id || '') === sid) || {};
      const key = `${sid}|date`;

      dates.forEach(dateStr => {
        next.manual[dateStr] = { ...(next.manual[dateStr] || {}) };
        const prev = next.manual[dateStr][key] || {};
        next.manual[dateStr][key] = {
          ...prev,
          sid,
          slots: [],
          dateOnly: true,
          state: '',
          createdAt: prev.createdAt || now,
          updatedAt: now,
          note: prev.note || '',
          course: studentCourseLabel(stu),
        };
      });

      const res = await fetch('/api/makeup-carryover', {
        method: 'POST',
        headers: CT,
        body: JSON.stringify(next),
      });
      const data = await res.json().catch(() => null);
      if (!res.ok) throw new Error(`/api/makeup-carryover ${res.status}`);
      CARRYOVER = normalizeCarryoverPayload(data || next);
      cancelManualAbsenceSelection();
      await refreshMakeupPlanner();
      toast(`${dates.length}건의 결석분을 보강 잡기 명단에 추가했습니다.`);
    } catch (err) {
      console.error(err);
      alert('결석 추가 실패');
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  function openManualMakeupAddUI() {
    ensureManualMakeupModal();
    const modal = $('manualMakeupModal');
    const search = $('manualMakeupSearch');
    cancelManualAbsenceSelection();
    manualMakeupSelectedSid = '';
    manualMakeupSelectedDates = new Set();
    if (search) search.value = '';
    renderManualMakeupRows();
    modal.style.display = 'flex';
    requestAnimationFrame(() => search?.focus());
  }

  function ensureMakeupPlanner() {
    if (document.getElementById('makeupPlanner')) return;
    calendarEl.insertAdjacentHTML('afterend', `
      <section id="makeupPlanner" class="makeup-planner" aria-label="보강 잡기">
        <div class="makeup-planner-head">
          <div>
            <div class="makeup-planner-title-row">
              <h4>보강 잡기</h4>
              <button id="exportMakeupRoster" class="btn secondary makeup-export-btn" type="button">보강 명단 내보내기</button>
              <button id="openManualMakeup" class="btn secondary makeup-export-btn makeup-add-btn" type="button">결석 추가</button>
            </div>
            <p id="makeupPlannerHint">보강이 잡히기 전까지 유지되는 결석 보강 명단입니다.</p>
          </div>
          <input id="makeupPlannerSearch" type="search" autocomplete="off" placeholder="보강 학생 검색">
        </div>
        <div id="makeupPlannerList" class="makeup-planner-list"></div>
      </section>
    `);

    const search = $('makeupPlannerSearch');
    applySearchPlaceholder(search, '보강 학생 검색');
    $('exportMakeupRoster')?.addEventListener('click', exportMakeupRosterCsv);
    $('openManualMakeup')?.addEventListener('click', openManualMakeupAddUI);
    search?.addEventListener('input', renderMakeupPlanner);
    search?.addEventListener('search', renderMakeupPlanner);
    search?.addEventListener('compositionend', renderMakeupPlanner);
    search?.addEventListener('keydown', (ev) => {
      if (ev.key !== 'Escape') return;
      if (makeupSelection) {
        ev.preventDefault();
        cancelMakeupSelection();
        return;
      }
      search.value = '';
      renderMakeupPlanner();
    });

    ensureMakeupFocusGuide();

    $('makeupPlannerList')?.addEventListener('click', (ev) => {
      const btn = ev.target.closest('[data-makeup-action]');
      if (!btn) return;
      const key = btn.dataset.key || '';
      const item = getPendingMakeups().find(row => makeupItemKey(row) === key);
      if (!item) return;

      if (btn.dataset.makeupAction === 'remove') {
        removePendingMakeup(item).catch(err => {
          console.error(err);
          alert('결석 취소 실패');
        });
        return;
      }

      if (btn.dataset.makeupAction === 'carryover') {
        carryoverPendingMakeup(item).catch(err => {
          console.error(err);
          alert('이월 실패');
        });
        return;
      }

      setMakeupSelection(item);
      closeMakeupSlotPicker();
      renderMakeupPlanner();
      toast('캘린더에서 보강 날짜를 클릭하세요.');
    });
  }

  function getPendingMakeups() {
    return buildPendingMakeups({
      students: state.students || [],
      absentByDate: state.absentByDate || {},
      absentSlotsByDate: state.absentSlotsByDate || {},
      extra: EXTRA || state.extra || {},
      weekendSlots: WEEKEND || {},
      carryover: CARRYOVER || {},
      manualMakeups: CARRYOVER?.manual || {},
    });
  }

  function applyAbsentPayload(data) {
    if (!data || typeof data !== 'object') return;
    const byDate = data.by_date || data.absentByDate;
    const byStudent = data.by_student || data.absences;
    const bySlot = data.by_slot || data.absentSlotsByDate;

    if (byDate && typeof byDate === 'object') state.absentByDate = byDate;
    if (byStudent && typeof byStudent === 'object') state.absences = byStudent;
    if (bySlot && typeof bySlot === 'object') state.absentSlotsByDate = normalizeAbsentSlotMap(bySlot);

    window.absentByDate = state.absentByDate;
    window.absences = state.absences;
    window.absentSlotsByDate = state.absentSlotsByDate;
    if (window.state && typeof window.state === 'object') {
      window.state.absentByDate = state.absentByDate;
      window.state.absences = state.absences;
      window.state.absentSlotsByDate = state.absentSlotsByDate;
    }
  }

  function ensureMakeupFocusGuide() {
    if (document.getElementById('makeupCalendarGuide')) return;
    calendarEl.insertAdjacentHTML('afterbegin', `
      <div id="makeupCalendarGuide" class="makeup-calendar-guide" hidden>
        <strong>캘린더에서 보강 날짜를 선택하세요</strong>
        <span id="makeupCalendarGuideSub"></span>
      </div>
    `);
  }

  function updateMakeupFocusUI() {
    ensureMakeupFocusGuide();
    const active = !!makeupSelection;
    document.body.classList.toggle('makeup-selecting', active);
    calendarEl.classList.toggle('is-makeup-selecting', active);
    const guide = $('makeupCalendarGuide');
    const sub = $('makeupCalendarGuideSub');
    if (!guide) return;
    guide.hidden = !active;
    if (sub) {
      const slotLabel = makeupSelection?.slot ? ` ${makeupSelection.slot}타임` : '';
      sub.textContent = active
        ? `${makeupSelection.name || makeupSelection.sid} - ${formatMakeupDate(makeupSelection.absenceDate)}${slotLabel}`
        : '';
    }
  }

  function setMakeupSelection(item) {
    if (item && manualAbsenceSelection) cancelManualAbsenceSelection();
    makeupSelection = item || null;
    updateMakeupFocusUI();
    refreshMakeupConflictHints();
    if (makeupSelection) {
      preloadExtraWeekend().then(refreshMakeupConflictHints).catch(() => {});
      window.requestAnimationFrame(() => {
        calendarEl.scrollIntoView({ block: 'start', inline: 'nearest', behavior: 'smooth' });
      });
    }
  }

  async function removePendingMakeup(item) {
    if (!item) return;
    const sid = String(item.sid || '').trim();
    const absenceDate = String(item.absenceDate || '').trim();
    if (!sid || !absenceDate) return;

    if (item.source === 'manual') {
      const latestRes = await fetch('/api/makeup-carryover', { cache: 'no-store' });
      const latest = latestRes.ok ? await latestRes.json().catch(() => ({})) : {};
      const next = normalizeCarryoverPayload(latest);
      const rows = next.manual?.[absenceDate] || {};
      const manualKey = String(item.manualKey || '').trim();
      if (manualKey) delete rows[manualKey];
      else {
        Object.entries(rows).forEach(([key, row]) => {
          if (String(row?.sid || '') === sid && parseSlotNumbers(row?.slots).includes(Number(item.slot))) delete rows[key];
        });
      }
      if (Object.keys(rows).length) next.manual[absenceDate] = rows;
      else delete next.manual[absenceDate];

      const res = await fetch('/api/makeup-carryover', {
        method: 'POST',
        headers: CT,
        body: JSON.stringify(next),
      });
      const data = await res.json().catch(() => null);
      if (!res.ok) throw new Error(`/api/makeup-carryover ${res.status}`);
      CARRYOVER = normalizeCarryoverPayload(data || next);
      if (makeupSelection && makeupItemKey(makeupSelection) === makeupItemKey(item)) {
        setMakeupSelection(null);
        closeMakeupSlotPicker();
      }
      await refreshMakeupPlanner();
      document.dispatchEvent(new CustomEvent('admin:refresh', { detail: { force: true } }));
      toast('보강 대상을 삭제했습니다.');
      return;
    }

    const latestRes = await fetch('/api/absent', { cache: 'no-store' });
    const latest = await latestRes.json().catch(() => null);
    if (!latestRes.ok) throw new Error(`/api/absent ${latestRes.status}`);

    const byDateSource = latest?.by_date || latest?.absentByDate || state.absentByDate || {};
    const byStudentSource = latest?.by_student || latest?.absences || state.absences || {};
    const bySlotSource = latest?.by_slot || latest?.absentSlotsByDate || state.absentSlotsByDate || {};
    const byDate = Object.fromEntries(Object.entries(byDateSource).map(([date, ids]) => [
      date,
      Array.isArray(ids) ? ids.map(String) : [],
    ]));
    const byStudent = { ...byStudentSource };
    const bySlot = normalizeAbsentSlotMap(bySlotSource);

    const removedSlot = parseSlotNumbers(item.slot)[0];
    if (removedSlot) {
      const existingSlots = parseSlotNumbers(bySlot?.[absenceDate]?.[sid]);
      const sourceSlots = existingSlots.length
        ? existingSlots
        : (getRegularSlots(item.student || {}, absenceDate).length ? getRegularSlots(item.student || {}, absenceDate) : [removedSlot]);
      const remainingSlots = sourceSlots.filter(slot => slot !== removedSlot);
      if (remainingSlots.length) {
        bySlot[absenceDate] = bySlot[absenceDate] || {};
        bySlot[absenceDate][sid] = remainingSlots;
      } else if (bySlot[absenceDate]) {
        delete bySlot[absenceDate][sid];
        if (!Object.keys(bySlot[absenceDate]).length) delete bySlot[absenceDate];
      }
    } else if (bySlot[absenceDate]) {
      delete bySlot[absenceDate][sid];
      if (!Object.keys(bySlot[absenceDate]).length) delete bySlot[absenceDate];
    }

    const nextIds = (byDate[absenceDate] || []).map(String).filter(id => id !== sid);
    if (nextIds.length) byDate[absenceDate] = nextIds;
    else delete byDate[absenceDate];
    if (String(byStudent[sid] || '') === absenceDate) delete byStudent[sid];

    const res = await fetch('/api/absent', {
      method: 'POST',
      headers: CT,
      body: JSON.stringify({ by_date: byDate, by_student: byStudent, by_slot: bySlot }),
    });
    const data = await res.json().catch(() => null);
    if (!res.ok) throw new Error(`/api/absent ${res.status}`);

    applyAbsentPayload(data || { by_date: byDate, by_student: byStudent, by_slot: bySlot });
    if (makeupSelection && makeupItemKey(makeupSelection) === makeupItemKey(item)) {
      setMakeupSelection(null);
      closeMakeupSlotPicker();
    }
    await refreshMakeupPlanner();
    await window.recalcCalendarCounts?.();
    document.dispatchEvent(new CustomEvent('attendance:updated'));
    document.dispatchEvent(new CustomEvent('admin:refresh', { detail: { force: true } }));
    toast('결석을 취소했습니다.');
  }

  async function carryoverPendingMakeup(item) {
    if (!item) return;
    const sid = String(item.sid || '').trim();
    const absenceDate = String(item.absenceDate || '').trim();
    if (!sid || !absenceDate) return;

    const latestRes = await fetch('/api/makeup-carryover', { cache: 'no-store' });
    const latest = latestRes.ok ? await latestRes.json().catch(() => ({})) : {};
    const next = normalizeCarryoverPayload(latest);
    if (item.source === 'manual') {
      const manualKey = String(item.manualKey || '').trim();
      next.manual[absenceDate] = next.manual[absenceDate] || {};
      const prev = manualKey ? (next.manual[absenceDate][manualKey] || {}) : {};
      if (manualKey) {
        next.manual[absenceDate][manualKey] = {
          ...prev,
          sid,
          slots: item.dateOnly ? [] : parseSlotNumbers(item.slot),
          dateOnly: item.dateOnly === true,
          state: 'carried',
          updatedAt: new Date().toISOString(),
          note: '',
          course: prev.course || item.course || '',
        };
      }
    } else {
      next.by_absence[absenceDate] = {
        ...(next.by_absence[absenceDate] || {}),
        [makeupCarryoverKey(item)]: {
          state: 'carried',
          updatedAt: new Date().toISOString(),
          note: '',
        },
      };
    }

    const res = await fetch('/api/makeup-carryover', {
      method: 'POST',
      headers: CT,
      body: JSON.stringify(next),
    });
    const data = await res.json().catch(() => null);
    if (!res.ok) throw new Error(`/api/makeup-carryover ${res.status}`);

    CARRYOVER = normalizeCarryoverPayload(data || next);
    if (makeupSelection && makeupItemKey(makeupSelection) === makeupItemKey(item)) {
      setMakeupSelection(null);
      closeMakeupSlotPicker();
    }
    await refreshMakeupPlanner();
    await window.recalcCalendarCounts?.();
    document.dispatchEvent(new CustomEvent('admin:refresh', { detail: { force: true } }));
    toast('보강 없이 이월 처리했습니다.');
  }

  async function resolveManualMakeupDemand(item) {
    if (!item || item.source !== 'manual') return;
    const sid = String(item.sid || '').trim();
    const absenceDate = String(item.absenceDate || '').trim();
    const manualKey = String(item.manualKey || '').trim();
    if (!sid || !absenceDate || !manualKey) return;

    const latestRes = await fetch('/api/makeup-carryover', { cache: 'no-store' });
    const latest = latestRes.ok ? await latestRes.json().catch(() => ({})) : {};
    const next = normalizeCarryoverPayload(latest);
    next.manual[absenceDate] = next.manual[absenceDate] || {};
    const prev = next.manual[absenceDate][manualKey] || {};
    next.manual[absenceDate][manualKey] = {
      ...prev,
      sid,
      slots: item.dateOnly ? [] : parseSlotNumbers(item.slot),
      dateOnly: item.dateOnly === true,
      state: 'carried',
      createdAt: prev.createdAt || '',
      updatedAt: new Date().toISOString(),
      note: prev.note || '',
      course: prev.course || item.course || studentCourseLabel(item.student || {}) || '',
    };

    const res = await fetch('/api/makeup-carryover', {
      method: 'POST',
      headers: CT,
      body: JSON.stringify(next),
    });
    const data = await res.json().catch(() => null);
    if (!res.ok) throw new Error(`/api/makeup-carryover ${res.status}`);
    CARRYOVER = normalizeCarryoverPayload(data || next);
  }

  async function resolveAbsenceMakeupDemand(item) {
    if (!item || item.source === 'manual') return;
    const sid = String(item.sid || '').trim();
    const absenceDate = String(item.absenceDate || '').trim();
    if (!sid || !absenceDate) return;

    const latestRes = await fetch('/api/makeup-carryover', { cache: 'no-store' });
    const latest = latestRes.ok ? await latestRes.json().catch(() => ({})) : {};
    const next = normalizeCarryoverPayload(latest);
    const carryKey = makeupCarryoverKey(item);
    const prev = next.by_absence[absenceDate]?.[carryKey] || {};
    next.by_absence[absenceDate] = {
      ...(next.by_absence[absenceDate] || {}),
      [carryKey]: {
        ...prev,
        state: 'carried',
        updatedAt: new Date().toISOString(),
        note: prev.note || '',
      },
    };

    const res = await fetch('/api/makeup-carryover', {
      method: 'POST',
      headers: CT,
      body: JSON.stringify(next),
    });
    const data = await res.json().catch(() => null);
    if (!res.ok) throw new Error(`/api/makeup-carryover ${res.status}`);
    CARRYOVER = normalizeCarryoverPayload(data || next);
  }

  async function resolveScheduledMakeupDemand(item) {
    if (item?.source === 'manual') {
      await resolveManualMakeupDemand(item);
      return;
    }
    await resolveAbsenceMakeupDemand(item);
  }

  async function markAbsenceMakeupOpen(absenceDate, items) {
    const date = String(absenceDate || '').trim();
    const rowsToOpen = (items || []).map(item => ({
      sid: String(item?.sid || '').trim(),
      slots: parseSlotNumbers(item?.slots ?? item?.slot),
    })).filter(item => item.sid);
    if (!date || !rowsToOpen.length) return;

    const latestRes = await fetch('/api/makeup-carryover', { cache: 'no-store' });
    const latest = latestRes.ok ? await latestRes.json().catch(() => ({})) : {};
    const next = normalizeCarryoverPayload(latest);
    const dateRows = { ...(next.by_absence[date] || {}) };
    const updatedAt = new Date().toISOString();

    rowsToOpen.forEach(({ sid, slots }) => {
      const slotList = slots.length ? slots : [''];
      slotList.forEach(slot => {
        const key = slot ? `${sid}|${slot}` : sid;
        const prev = dateRows[key] || {};
        dateRows[key] = {
          ...prev,
          state: 'open',
          updatedAt,
          note: prev.note || '',
        };
      });
    });

    next.by_absence[date] = dateRows;
    const res = await fetch('/api/makeup-carryover', {
      method: 'POST',
      headers: CT,
      body: JSON.stringify(next),
    });
    const data = await res.json().catch(() => null);
    if (!res.ok) throw new Error(`/api/makeup-carryover ${res.status}`);
    CARRYOVER = normalizeCarryoverPayload(data || next);
  }

  async function resolveFirstOpenMakeupDemandsForSids(sids) {
    const targets = new Set((sids || []).map(sid => String(sid || '').trim()).filter(Boolean));
    if (!targets.size) return;

    const latestRes = await fetch('/api/makeup-carryover', { cache: 'no-store' });
    const latest = latestRes.ok ? await latestRes.json().catch(() => ({})) : {};
    const next = normalizeCarryoverPayload(latest);
    const consumed = new Set();
    let changed = false;
    const updatedAt = new Date().toISOString();

    for (const date of Object.keys(next.by_absence || {}).sort()) {
      const rows = next.by_absence[date];
      if (!rows || typeof rows !== 'object') continue;
      for (const key of Object.keys(rows).sort()) {
        const sid = String(key).split('|')[0];
        if (!targets.has(sid) || consumed.has(sid)) continue;
        const row = rows[key];
        const isOpen = row && typeof row === 'object' && (row.state === 'open' || row.open === true || row.pending === true);
        if (!isOpen) continue;
        rows[key] = {
          ...row,
          state: 'carried',
          updatedAt,
          note: row.note || '',
        };
        consumed.add(sid);
        changed = true;
        if (consumed.size === targets.size) break;
      }
      if (consumed.size === targets.size) break;
    }

    if (!changed) return;
    const res = await fetch('/api/makeup-carryover', {
      method: 'POST',
      headers: CT,
      body: JSON.stringify(next),
    });
    const data = await res.json().catch(() => null);
    if (!res.ok) throw new Error(`/api/makeup-carryover ${res.status}`);
    CARRYOVER = normalizeCarryoverPayload(data || next);
  }

  function renderMakeupPlanner() {
    ensureMakeupPlanner();
    updateMakeupFocusUI();
    const list = $('makeupPlannerList');
    const hint = $('makeupPlannerHint');
    const search = $('makeupPlannerSearch');
    if (!list) return;

    const queryText = search?.value || '';
    const items = getPendingMakeups();
    const visible = sortPlannerItems(items.filter(item => {
      const key = studentSearchKey(item.student, [
        item.school,
        item.course,
        item.absenceDate,
        item.slot ? `${item.slot}타임` : '',
        item.source === 'manual' ? '추가 결석' : '결석',
        formatMakeupDate(item.absenceDate),
      ]);
      return matchesSearchKey(key, queryText);
    }));

    if (hint) {
      const suffix = manualAbsenceSelection ? ' 결석 날짜 선택 중' : (makeupSelection ? ' 날짜 선택 중' : '');
      hint.textContent = queryText.trim()
        ? `${visible.length}/${items.length}명${suffix}`
        : `${items.length}건${suffix}`;
    }

    if (!visible.length) {
      list.innerHTML = `<div class="makeup-empty">${queryText.trim() ? '검색 결과가 없습니다.' : '보강 잡을 학생이 없습니다.'}</div>`;
      return;
    }

    const activeKey = makeupSelection ? makeupItemKey(makeupSelection) : '';
    list.innerHTML = visible.map(item => {
      const key = makeupItemKey(item);
      const sourceLabel = item.source === 'manual' ? '추가 결석' : '결석';
      const slotLabel = item.dateOnly
        ? ` - ${sourceLabel}`
        : item.slot ? ` - ${sourceLabel} ${item.slot}타임` : '';
      const label = `${item.name || '-'} - ${item.school || '-'} - ${item.course || '-'} - ${formatMakeupDate(item.absenceDate)}${slotLabel}`;
      const active = key === activeKey ? ' is-active' : '';
      const removeText = item.source === 'manual' ? '삭제' : '결석 취소';
      return `
        <div class="makeup-row${active}" data-key="${escapeAttr(key)}">
          <div class="makeup-label">${escapeHtml(label)}</div>
          <div class="makeup-actions">
            <button type="button" class="makeup-pick-btn" data-makeup-action="pick" data-key="${escapeAttr(key)}">보강</button>
            <button type="button" class="makeup-remove-btn" data-makeup-action="remove" data-key="${escapeAttr(key)}">${removeText}</button>
            <button type="button" class="makeup-carryover-btn" data-makeup-action="carryover" data-key="${escapeAttr(key)}">이월</button>
          </div>
        </div>
      `;
    }).join('');
  }

  async function refreshMakeupPlanner() {
    await preloadExtraWeekend();
    renderMakeupPlanner();
    refreshMakeupConflictHints();
  }

  function closeMakeupSlotPicker() {
    document.querySelectorAll('.makeup-slot-popover').forEach(el => el.remove());
  }

  function cancelMakeupSelection() {
    setMakeupSelection(null);
    closeMakeupSlotPicker();
    renderMakeupPlanner();
  }

  function openMakeupSlotPicker(dateStr, dayEl) {
    if (!makeupSelection || !dayEl) return;
    closeMakeupSlotPicker();
    dayEl.style.position = 'relative';

    const pop = document.createElement('div');
    pop.className = 'makeup-slot-popover';
    pop.innerHTML = `
      <div class="makeup-slot-head">
        <div class="makeup-slot-title">${escapeHtml(makeupSelection.name || '')}</div>
        <button type="button" class="makeup-slot-close" data-makeup-action="cancel" aria-label="닫기">×</button>
      </div>
      <div class="makeup-slot-sub">${escapeHtml(formatMakeupDate(makeupSelection.absenceDate))}${makeupSelection.dateOnly ? ' · 결석분' : makeupSelection.slot ? ` · ${makeupSelection.slot}타임 결석분` : ''}</div>
      <div class="makeup-slot-actions">
        ${MAKEUP_SLOTS.map(slot => `
          <button type="button" data-slot="${slot}">${slot}타임</button>
        `).join('')}
      </div>
    `;
    dayEl.appendChild(pop);

    pop.addEventListener('click', (ev) => {
      const closeBtn = ev.target.closest('[data-makeup-action="cancel"]');
      if (closeBtn) {
        ev.preventDefault();
        ev.stopPropagation();
        cancelMakeupSelection();
        return;
      }

      const btn = ev.target.closest('button[data-slot]');
      if (!btn) return;
      const slot = parseInt(btn.dataset.slot, 10);
      scheduleSelectedMakeup(dateStr, slot).catch(err => {
        console.error(err);
        alert('보강 저장 실패');
      });
    });
  }

  async function scheduleSelectedMakeup(dateStr, slot) {
    if (!makeupSelection) return;
    if (!MAKEUP_SLOTS.includes(slot)) return;
    const selectedDemand = makeupSelection;

    await preloadExtraWeekend();

    const sid = String(selectedDemand.sid);
    const stu = selectedDemand.student ||
      (state.students || []).find(row => String(row?.id || '') === sid) ||
      {};
    const dayIds = new Set((EXTRA[dateStr] || []).map(String));
    dayIds.add(sid);
    EXTRA[dateStr] = Array.from(dayIds);
    state.extra = EXTRA;
    window.extra = state.extra;

    const perDaySlots = WEEKEND[dateStr] || {};
    const existingSlots = parseSlotNumbers(perDaySlots[sid]);
    const mergedSlots = combinedSlotsForStudent(stu, dateStr, [...existingSlots, slot]);
    perDaySlots[sid] = serializeSlots(mergedSlots);
    WEEKEND[dateStr] = perDaySlots;

    await fetch('/api/extra-attend', {
      method: 'POST',
      headers: CT,
      body: JSON.stringify(EXTRA),
    });
    await fetch('/api/weekend-slots', {
      method: 'POST',
      headers: CT,
      body: JSON.stringify({ [dateStr]: perDaySlots }),
    });
    await fetch('/arrive-time/patch', {
      method: 'POST',
      headers: CT,
      body: JSON.stringify({
        date: dateStr,
        sid,
        value: MAKEUP_ARRIVE_BY_SLOT[Math.min(...mergedSlots)] || '',
      }),
    });
    await resolveScheduledMakeupDemand(selectedDemand);

    toast('보강 저장 완료');
    setMakeupSelection(null);
    closeMakeupSlotPicker();
    await refreshMakeupPlanner();
    await window.recalcCalendarCounts?.();
    document.dispatchEvent(new CustomEvent('admin:refresh', { detail: { force: true } }));
  }

  const calBadge = $('calTodayBadge');
  let schoolExamEvents = buildSchoolExamEvents();
  let calendarFocusDate = new Date();

  function updateExamBadge(count, source = 'cache') {
    if (!calBadge) return;
    if (!count) {
      calBadge.textContent = '시험 일정 0건';
      calBadge.hidden = false;
      calBadge.style.opacity = '.75';
      return;
    }
    calBadge.textContent = `시험 일정 ${count}건`;
    calBadge.hidden = false;
    calBadge.style.opacity = '1';
    calBadge.title = source === 'api' ? '학교일정 API 재조회 반영' : '초기 로드 반영';
  }

  let calendar = null;
  function currentVisibleRange() {
    return rollingFiveWeekRange(calendarFocusDate || new Date());
  }

  function applyCalendarFocusDate() {
    if (!calendar) return;
    const range = currentVisibleRange();
    calendar.changeView('rollingFiveWeek', range);
    window.requestAnimationFrame(syncCalendarCellRatio);
  }

  function setCalendarFocusDate(date) {
    const next = date instanceof Date
      ? new Date(date.getFullYear(), date.getMonth(), date.getDate())
      : toSafeDate(...String(date || '').split('-'));
    if (!next) return;
    calendarFocusDate = next;
    applyCalendarFocusDate();
  }

  function goToTodayMainWeek() {
    if (!calendar) return;
    setCalendarFocusDate(new Date());
  }

  calendar = new FullCalendar.Calendar(calendarEl, {
    initialView: 'rollingFiveWeek',
    initialDate: ymd(calendarFocusDate),
    views: {
      rollingFiveWeek: {
        type: 'dayGrid',
      },
    },
    visibleRange: currentVisibleRange,
    headerToolbar: { left: 'title', center: '', right: 'centerToday' },
    customButtons: {
      centerToday: {
        text: 'today',
        click: goToTodayMainWeek,
      },
    },
    dateIncrement: { weeks: 1 },
    height: 'auto',
    contentHeight: 'auto',
    expandRows: true,
    stickyHeaderDates: true,
    locale: 'ko',
    firstDay: WEEK_START_DAY,
    dayMaxEvents: false,
    dayMaxEventRows: false,
    events: schoolExamEvents,
    dayCellClassNames: (arg) => {
      const viewStart = arg.view?.activeStart || arg.view?.currentStart;
      return isMainWeekDate(arg.date, viewStart) ? ['cal-main-week'] : ['cal-side-week'];
    },
    dayCellContent: (arg) => ({
      html: `<span class="cal-day-number">${arg.date.getMonth() + 1}/${arg.date.getDate()}</span>`,
    }),
    eventOrderStrict: true,
    eventOrder: (a, b) => {
      const oa = Number(a.extendedProps?.order ?? 99);
      const ob = Number(b.extendedProps?.order ?? 99);
      if (oa !== ob) return oa - ob;
      return String(a.title || '').localeCompare(String(b.title || ''), 'ko');
    },
    dateClick: info => {
      if (manualAbsenceSelection) {
        if (!recentlyHandledManualAbsenceDate(info.dateStr)) toggleManualAbsenceDate(info.dateStr);
        return;
      }
      if (makeupSelection) {
        openMakeupSlotPicker(info.dateStr, info.dayEl);
        return;
      }
      openAttendModal(info.dateStr);
    },
    eventDidMount: (info) => {
      const tooltip = String(info.event?.extendedProps?.tooltip || info.event?.title || '').trim();
      if (tooltip) info.el.setAttribute('title', tooltip);
    },
    datesSet: range => {
      const titleEl = calendarEl.querySelector('.fc-toolbar-title');
      if (titleEl) titleEl.textContent = weekTitleForRange(range.start);
      syncCalendarCellRatio();
      bindCenterTodayButton();
      fetchCountsForRange(range.start, range.end).then(refreshCountBadges);
      refreshManualAbsenceDateMarks();
      refreshMakeupPlanner();
    }
  });
  calendar.render();
  function bindCenterTodayButton() {
    calendarEl.querySelector('#calendarTodayButton')?.remove();
    const buttons = Array.from(calendarEl.querySelectorAll('.fc-centerToday-button'));
    buttons.slice(1).forEach(btn => btn.remove());
    const btn = buttons[0];
    if (!btn) return;
    btn.classList.add('calendar-today-button');
    btn.textContent = 'today';
    btn.setAttribute('title', 'today');
    if (btn.dataset.centerTodayBound === '1') return;
    btn.dataset.centerTodayBound = '1';
    const handleTodayButton = (ev) => {
      ev.preventDefault?.();
      ev.stopImmediatePropagation?.();
      goToTodayMainWeek();
    };
    btn.addEventListener('pointerdown', handleTodayButton, true);
    btn.addEventListener('mousedown', handleTodayButton, true);
    btn.addEventListener('click', handleTodayButton, true);
  }

  bindCenterTodayButton();
  ensureMakeupPlanner();
  refreshMakeupPlanner();
  updateExamBadge(schoolExamEvents.length, 'cache');

  calendarEl.addEventListener('pointerdown', handleManualAbsencePointerDown, true);

  calendarEl.addEventListener('click', (ev) => {
    if (handleManualAbsenceCalendarClick(ev)) return;
    const target = ev.target instanceof Element ? ev.target : ev.target?.parentElement;
    if (target?.closest('.calendar-today-button')) return;
    if (!target?.closest('.fc-centerToday-button')) return;
    ev.preventDefault();
    ev.stopPropagation();
    goToTodayMainWeek();
  }, true);

  document.addEventListener('keydown', (ev) => {
    if (ev.key !== 'Escape' || (!makeupSelection && !manualAbsenceSelection)) return;
    ev.preventDefault();
    if (manualAbsenceSelection) cancelManualAbsenceSelection();
    else cancelMakeupSelection();
  });

  let wheelWeekLocked = false;
  calendarEl.addEventListener('wheel', (ev) => {
    const delta = Math.abs(ev.deltaY) >= Math.abs(ev.deltaX) ? ev.deltaY : ev.deltaX;
    if (Math.abs(delta) < 24) return;
    ev.preventDefault();
    ev.stopPropagation();
    if (wheelWeekLocked) return;
    wheelWeekLocked = true;
    setCalendarFocusDate(addDays(calendarFocusDate || calendar.view.currentStart, delta > 0 ? 7 : -7));
    window.setTimeout(() => { wheelWeekLocked = false; }, 180);
  }, { passive: false });

  async function refreshSchoolExamEvents() {
    let events = buildSchoolExamEvents(state.schoolCal);
    let source = 'cache';
    if (!events.length) {
      try {
        const latest = await fetch('/api/school-calendar', { cache: 'no-store' }).then((r) => r.json());
        if (latest && typeof latest === 'object') {
          state.schoolCal = latest;
          window.schoolCal = latest;
          events = buildSchoolExamEvents(latest);
          source = 'api';
        }
      } catch {
        // Keep cached events when refresh fails.
      }
    }

    schoolExamEvents = events;
    calendar.removeAllEvents();
    if (events.length) calendar.addEventSource(events);
    updateExamBadge(events.length, source);
  }

  // Run once after render in case initial bootstrap missed school calendar payload.
  refreshSchoolExamEvents();

  // 외부에서 새로고침 필요할 때 호출
  window.recalcCalendarCounts = function () {
    const viewStart = calendar.view.activeStart || calendar.view.currentStart;
    const viewEnd = calendar.view.activeEnd || calendar.view.currentEnd;
    return fetchCountsForRange(viewStart, viewEnd)
      .then(() => {
        refreshCountBadges();
        return refreshMakeupPlanner();
      });
  };

  // ───────────────── 출결 모달 ─────────────────
  function openAttendModal(dateStr) {
    const attendModal = $('attendModal'), titleEl = $('attendDateTitle'), listEl = $('attendList');
    if (!attendModal || !titleEl || !listEl) return;

    titleEl.textContent = `${dateStr} (${yoil(dateStr)})`;

    // 모달 안에 "그 날짜용 시간 그래프" 컨테이너 보장
    if (listEl.parentElement && !$('timeGraphWrapForDate')) {
      const g = document.createElement('div');
      g.id = 'timeGraphWrapForDate';
      g.style.margin = '8px 0 10px';
      listEl.parentElement.insertBefore(g, listEl);
    }

    Promise.all([
      fetch(`/api/attend?date=${dateStr}`, { cache: 'no-store' }).then(r => r.json()),
      fetch('/api/extra-attend', { cache: 'no-store' }).then(r => r.json()),
      fetch('/api/weekend-slots', { cache: 'no-store' }).then(r => r.json()).catch(() => ({}))
    ]).then(([att, extraMap, weekendMap]) => {
      EXTRA = extraMap || {};
      WEEKEND = weekendMap || {};
      const extras = (EXTRA[dateStr] || []).map(String);
      const slotMap = WEEKEND[dateStr] || {};

      const rows = [...att].sort((a, b) => {
        const slotsA = availableSlotsForAttendStudent(a, dateStr, extras, slotMap);
        const slotsB = availableSlotsForAttendStudent(b, dateStr, extras, slotMap);
        const slotCmp = slotSortValue(slotsA) - slotSortValue(slotsB);
        if (slotCmp !== 0) return slotCmp;
        return String(a.name || '').localeCompare(String(b.name || ''), 'ko', { numeric: true }) ||
          String(a.id).localeCompare(String(b.id), 'ko', { numeric: true });
      });

      listEl.innerHTML = rows.map(s => {
        const sid = String(s.id);
        const isExtra = extras.includes(sid);
        const slots = availableSlotsForAttendStudent(s, dateStr, extras, slotMap);
        if (!slots.length) return '';

        let tail = '';
        if (isExtra) {
          const raw = slotMap[sid];                                         // 보강
          const extraArr = parseSlotNumbers(raw);
          if (extraArr.length) {
            const mark = extraArr.map(n => `${yoil(dateStr)}${n}`).join('·');
            tail = `<span style="color:#2563eb;margin-left:6px">[${mark}]</span>`;
          }
        }

        return `<li data-id="${s.id}" class="attend-roster-row">
          <span class="attend-slot-label">${slotGroupLabel(slots)}</span>
          <span class="attend-student-label">${s.name} (${s.curriculum}${s.subCurriculum ? ' ' + s.subCurriculum : ''}) ${tail}</span>
        </li>`;
      }).join('');

      // 🔹 이 날짜의 attend 명단으로 시간대 그래프 그리기
      renderTimeGraphForDate(dateStr, att, 'timeGraphWrapForDate');

      attendModal.style.display = 'flex';
    }).catch(() => alert('출결 정보를 불러올 수 없습니다.'));
  }

  // 닫기
  $('attendClose')?.addEventListener('click', () => $('attendModal').style.display = 'none');
  document.body.addEventListener('click', (e) => { if (e.target.id === 'attendModal') $('attendModal').style.display = 'none'; });

  // ───────────── 보강/결석 선택 모달 ─────────────
  const selectionModal = $('selectionModal'),
    selectionListEl = $('selectionList'),
    selectionSaveBtn = $('selectionSave'),
    selectionClose = $('selectionClose');

  $('addExtraBtn')?.addEventListener('click', () => openSelectionUI('extra'));
  $('markAbsentBtn')?.addEventListener('click', () => openSelectionUI('absent'));

  function makeupSlotLabel(dateStr, slot) {
    return `${yoil(dateStr)}${slot}`;
  }

  function slotLegend(dateStr) {
    return `
      <li class="selection-slot-legend">
        <b>타임 선택</b>
        ${MAKEUP_SLOTS.map(slot => `<span>${makeupSlotLabel(dateStr, slot)}</span>`).join('')}
        <small style="opacity:.7">여러 개 클릭 가능(예: 1·2 → 연강)</small>
      </li>`;
  }

  function ensureSelectionModalChrome() {
    if (!selectionModal) return;
    const panel = selectionModal.querySelector('.modal-panel');
    const title = $('selectionTitle');
    if (!panel || !title) return;
    panel.classList.add('selection-panel');

    let header = $('selectionHeader');
    if (!header) {
      header = document.createElement('div');
      header.id = 'selectionHeader';
      header.className = 'selection-header';
      const actions = document.createElement('div');
      actions.className = 'selection-actions selection-actions-top';

      panel.insertAdjacentElement('afterbegin', header);
      header.appendChild(title);
      header.appendChild(actions);

      selectionSaveBtn?.classList.add('selection-btn', 'primary');
      selectionClose?.classList.remove('modal-close');
      selectionClose?.classList.add('selection-btn');
      if (selectionSaveBtn) actions.appendChild(selectionSaveBtn);
      if (selectionClose) actions.appendChild(selectionClose);
      panel.querySelector('.modal-footer')?.remove();
    }

    if (selectionSaveBtn) selectionSaveBtn.textContent = '저장';
    if (selectionClose) selectionClose.textContent = '닫기';
  }

  function ensureSelectionSearchUI() {
    ensureSelectionModalChrome();
    if (!selectionModal || !selectionListEl) return null;
    let wrap = $('selectionSearchWrap');
    if (!wrap) {
      wrap = document.createElement('div');
      wrap.id = 'selectionSearchWrap';
      wrap.className = 'selection-search-wrap';
      wrap.innerHTML = `
        <div class="selection-search-row">
          <input id="selectionSearchInput" type="search" autocomplete="off" placeholder="학생 이름 검색" aria-label="학생 이름 검색">
          <button type="button" id="selectionSearchPick" class="selection-btn" disabled>선택</button>
        </div>
        <div id="selectionSearchHint" class="selection-search-hint" aria-live="polite"></div>
      `;
      selectionListEl.insertAdjacentElement('beforebegin', wrap);
      const input = $('selectionSearchInput');
      applySearchPlaceholder(input, '학생 이름 검색');
      input?.addEventListener('input', applySelectionSearchFilter);
      input?.addEventListener('search', applySelectionSearchFilter);
      input?.addEventListener('compositionend', applySelectionSearchFilter);
      input?.addEventListener('keydown', (ev) => {
        if (ev.key === 'Enter') {
          ev.preventDefault();
          pickSelectionSearchStudent();
          return;
        }
        if (ev.key !== 'Escape') return;
        input.value = '';
        applySelectionSearchFilter();
      });
      $('selectionSearchPick')?.addEventListener('click', pickSelectionSearchStudent);
    }
    return $('selectionSearchInput');
  }

  function applySelectionSearchFilter() {
    const input = $('selectionSearchInput');
    const hint = $('selectionSearchHint');
    const pick = $('selectionSearchPick');
    const rows = Array.from(selectionListEl?.querySelectorAll('li[data-id]') || []);
    const queryText = input?.value || '';
    const needle = normalizeSearch(queryText);
    let visible = 0;
    rows.forEach(row => {
      const matches = matchesSearchKey(row.dataset.searchKey || '', queryText);
      row.hidden = !matches;
      row.style.display = matches ? '' : 'none';
      row.classList.toggle('is-search-hidden', !matches);
      row.setAttribute('aria-hidden', matches ? 'false' : 'true');
      if (matches) visible += 1;
    });
    if (pick) pick.disabled = !needle || visible === 0;
    if (hint) hint.textContent = needle ? (visible ? `${visible}명` : '검색 결과 없음') : '';
  }

  function setSelectionRowSelected(row, selected, ensureDefaultSlot = false) {
    const chk = row?.querySelector('.chk-sid');
    if (!chk) return;
    chk.checked = selected;
    row.classList.toggle('selected', selected);

    if (selected && ensureDefaultSlot && !row.querySelector('.slot-btn.on')) {
      (row.querySelector('.slot-btn[data-slot="1"]:not([disabled])') ||
        row.querySelector('.slot-btn:not([disabled])'))?.classList.add('on');
    }
  }

  function pickSelectionSearchStudent() {
    const input = $('selectionSearchInput');
    const hint = $('selectionSearchHint');
    const needle = normalizeSearch(input?.value);
    if (!needle) return;

    const rows = Array.from(selectionListEl?.querySelectorAll('li[data-id]') || []);
    const visibleRows = rows.filter(row => !row.hidden && !row.classList.contains('is-search-hidden'));
    const exact = visibleRows.find(row => normalizeSearch(row.querySelector('.student-name')?.textContent) === needle);
    const row = exact || visibleRows[0];
    if (!row) return;

    setSelectionRowSelected(row, true, true);
    row.scrollIntoView({ block: 'nearest' });
    const name = row.querySelector('.student-name')?.textContent || '';
    if (hint) hint.textContent = name ? `${name} 선택됨` : '선택됨';
  }

  function studentRow(s, dateStr, preChecked, curSlots, options = {}) {
    const showSlots = !!options.showSlots;
    const slots = parseSlotNumbers(curSlots);
    const has = new Set((slots.length ? slots : [1]).filter(n => MAKEUP_SLOTS.includes(n)));
    const allowedSlots = new Set(parseSlotNumbers(options.allowedSlots || MAKEUP_SLOTS));
    const allSlots = parseSlotNumbers(options.allSlots || curSlots || [1]);
    const searchKey = studentSearchKey(s, [
      s?.school,
      s?.schoolName,
      s?.curriculum,
      s?.subCurriculum,
      slotGroupLabel(Array.from(has)),
      dateStr,
    ]);
    return `
      <li data-id="${escapeAttr(s.id)}" data-search-key="${escapeAttr(searchKey)}" data-all-slots="${escapeAttr(allSlots.join(','))}" class="selection-student-row ${preChecked ? 'selected' : ''}">
        <label class="selection-student-label">
          <input type="checkbox" class="chk-sid" ${preChecked ? 'checked' : ''}>
          <span class="student-name">${escapeHtml(s.name || '')}</span>
          <small>${escapeHtml(s.curriculum || '')}${s.subCurriculum ? ' · ' + escapeHtml(s.subCurriculum) : ''}</small>
        </label>
        ${showSlots ? `
          <div class="slot-box" aria-label="타임 선택">
            ${MAKEUP_SLOTS.map(n => `
              <button type="button" class="slot-btn ${has.has(n) ? 'on' : ''}" data-slot="${n}"
                ${allowedSlots.has(n) ? '' : 'disabled aria-disabled="true"'}
                title="${makeupSlotLabel(dateStr, n)}">${makeupSlotLabel(dateStr, n)}</button>
            `).join('')}
          </div>` : ``}
      </li>`;
  }

  function openSelectionUI(mode) {
    const dateStr = $('attendDateTitle').textContent.split(' ')[0]; // "YYYY-MM-DD (요일)" → 날짜만
    const searchInput = ensureSelectionSearchUI();
    Promise.all([
      fetch(`/api/attend?date=${dateStr}`, { cache: 'no-store' }).then(r => r.json()),
      fetch('/api/extra-attend', { cache: 'no-store' }).then(r => r.json()),
      fetch('/api/weekend-slots', { cache: 'no-store' }).then(r => r.json()).catch(() => ({}))
    ]).then(([todayAtt, extraMap, weekendMap]) => {
      EXTRA = extraMap || {};
      WEEKEND = weekendMap || {};

      // 목록 소스: 결석 처리는 오늘 등원자만, 보강은 전체 학생
      const listSource = mode === 'absent'
        ? [...todayAtt].filter(stu =>
          availableSlotsForAttendStudent(stu, dateStr, (EXTRA[dateStr] || []).map(String), WEEKEND[dateStr] || {}).length
        ).sort((a, b) => {
          const slotsA = availableSlotsForAttendStudent(a, dateStr, (EXTRA[dateStr] || []).map(String), WEEKEND[dateStr] || {});
          const slotsB = availableSlotsForAttendStudent(b, dateStr, (EXTRA[dateStr] || []).map(String), WEEKEND[dateStr] || {});
          const slotCmp = slotSortValue(slotsA) - slotSortValue(slotsB);
          if (slotCmp !== 0) return slotCmp;
          return String(a.name || '').localeCompare(String(b.name || ''), 'ko', { numeric: true });
        })
        : (state.students || []).slice()
          .sort((a, b) => String(a.name || '').localeCompare(String(b.name || ''), 'ko', { numeric: true }));

      const pre = new Set((EXTRA[dateStr] || []).map(String));
      const perDateSlot = WEEKEND[dateStr] || {};
      const showSlots = mode === 'extra' || mode === 'absent';

      selectionListEl.innerHTML =
        (showSlots ? slotLegend(dateStr) : '') +
        listSource.map(s => {
          const sid = String(s.id);
          const checked = mode === 'extra' ? pre.has(sid) : false;
          const allSlots = slotsForAttendStudent(s, dateStr, (EXTRA[dateStr] || []).map(String), perDateSlot);
          const availableSlots = availableSlotsForAttendStudent(s, dateStr, (EXTRA[dateStr] || []).map(String), perDateSlot);
          const curSlots = mode === 'extra'
            ? combinedSlotsForStudent(s, dateStr, parseSlotNumbers(perDateSlot[sid] ?? [1]))
            : availableSlots;
          return studentRow(s, dateStr, checked, curSlots, {
            showSlots,
            allowedSlots: mode === 'absent' ? availableSlots : MAKEUP_SLOTS,
            allSlots,
          });
        }).join('');
      if (searchInput) searchInput.value = '';
      applySelectionSearchFilter();

      // 행 클릭 시 배경 토글
      selectionListEl.querySelectorAll('li[data-id]').forEach(li => {
        const chk = li.querySelector('.chk-sid');
        chk?.addEventListener('change', () => {
          const needsSlot = selectionModal.dataset.mode === 'extra' || selectionModal.dataset.mode === 'absent';
          setSelectionRowSelected(li, chk.checked, needsSlot);
        });
        setSelectionRowSelected(li, !!chk?.checked);
      });

      // 슬롯 버튼 클릭 핸들러: 한 번만 바인딩(중복 방지)
      if (!slotClickBound) {
        selectionListEl.addEventListener('click', onSlotClick);
        slotClickBound = true;
      }

      selectionModal.dataset.mode = mode;
      selectionModal.dataset.date = dateStr;
      $('selectionTitle').textContent = mode === 'extra' ? `${dateStr} 보강 추가` : `${dateStr} 결석 처리`;
      selectionModal.style.display = 'flex';
    });
  }

  // 슬롯 버튼 클릭 핸들러 (이벤트 위임)
  function onSlotClick(e) {
    const btn = e.target.closest('.slot-btn');
    if (!btn) return;
    if (btn.disabled) return;
    const li = btn.closest('li[data-id]');
    if (!li) return;

    btn.classList.toggle('on');

    // 자동 체크
    if (!li.querySelector('.chk-sid')?.checked) setSelectionRowSelected(li, true);
  }

  // 저장(보강: 체크된 학생만 남기고, 선택 타임은 배열로 저장 가능)
  selectionSaveBtn?.addEventListener('click', async () => {
    const mode = selectionModal.dataset.mode, dateStr = selectionModal.dataset.date;

    const items = [...selectionListEl.querySelectorAll('li[data-id]')];
    const selectedIds = items.filter(li => li.querySelector('.chk-sid')?.checked)
      .map(li => String(li.dataset.id));

    // ── 결석 처리 ──
    if (mode === 'absent') {
      state.absences = state.absences && typeof state.absences === 'object' ? state.absences : {};
      state.absentByDate = state.absentByDate && typeof state.absentByDate === 'object' ? state.absentByDate : {};
      state.absentSlotsByDate = state.absentSlotsByDate && typeof state.absentSlotsByDate === 'object' ? state.absentSlotsByDate : {};

      const fullDaySet = new Set((state.absentByDate[dateStr] || []).map(String));
      const slotDay = { ...(state.absentSlotsByDate[dateStr] || {}) };
      const openedDemands = [];

      for (const li of items.filter(row => selectedIds.includes(String(row.dataset.id)))) {
        const sid = String(li.dataset.id);
        const allSlots = parseSlotNumbers(li.dataset.allSlots || []);
        const selectedSlots = Array.from(li.querySelectorAll('.slot-btn.on:not([disabled])'))
          .map(btn => parseInt(btn.dataset.slot, 10))
          .filter(slot => MAKEUP_SLOTS.includes(slot))
          .sort((a, b) => a - b);
        const targetSlots = selectedSlots.length ? selectedSlots : allSlots;
        const previousSlots = parseSlotNumbers(slotDay[sid]);
        const nextSlots = Array.from(new Set([...(previousSlots || []), ...targetSlots])).sort((a, b) => a - b);
        const fullSlots = allSlots.length ? allSlots : nextSlots;
        const isFullAbsence = fullSlots.length > 0 && fullSlots.every(slot => nextSlots.includes(slot));
        if (targetSlots.length) openedDemands.push({ sid, slots: targetSlots });

        if (isFullAbsence) {
          fullDaySet.add(sid);
          state.absences[sid] = dateStr;
          if (fullSlots.length) slotDay[sid] = fullSlots;
          else delete slotDay[sid];
        } else if (nextSlots.length) {
          fullDaySet.delete(sid);
          if (String(state.absences[sid] || '') === dateStr) delete state.absences[sid];
          slotDay[sid] = nextSlots;
        }
      }

      if (fullDaySet.size) state.absentByDate[dateStr] = Array.from(fullDaySet);
      else delete state.absentByDate[dateStr];
      if (Object.keys(slotDay).length) state.absentSlotsByDate[dateStr] = slotDay;
      else delete state.absentSlotsByDate[dateStr];

      try {
        const res = await fetch('/api/absent', {
          method: 'POST', headers: CT,
          body: JSON.stringify({
            by_date: state.absentByDate,
            by_student: state.absences,
            by_slot: state.absentSlotsByDate,
          })
        });
        let data = null;
        try { data = await res.json(); } catch { }
        if (!res.ok) throw new Error(`/api/absent ${res.status}`);
        applyAbsentPayload(data);
        await markAbsenceMakeupOpen(dateStr, openedDemands);
        alert('결석 처리 완료');
        selectionModal.style.display = 'none';
        document.dispatchEvent(new CustomEvent('attendance:updated'));
        if (window.recalcCalendarCounts) await window.recalcCalendarCounts();
        else refreshMakeupPlanner();
      } catch (err) {
        console.error(err);
        alert('요청에 실패했습니다.');
      }
      return;
    }

    // ── 보강 추가/해제 ──
    await preloadExtraWeekend(); // 최신화
    const previousExtraSet = new Set((EXTRA[dateStr] || []).map(String));
    const nextSet = new Set(selectedIds);
    EXTRA[dateStr] = Array.from(nextSet); // 체크 해제된 학생은 제거
    const newlyAddedExtraIds = selectedIds.filter(sid => !previousExtraSet.has(String(sid)));

    const perDate = WEEKEND[dateStr] || {};
    for (const sid of Object.keys(perDate)) {
      if (!nextSet.has(String(sid))) delete perDate[sid];
    }
    for (const li of items) {
      const sid = String(li.dataset.id);
      if (!nextSet.has(sid)) continue;
      const sel = [...li.querySelectorAll('.slot-btn.on')]
        .map(b => parseInt(b.dataset.slot, 10))
        .filter(slot => MAKEUP_SLOTS.includes(slot))
        .sort((a, b) => a - b);
      const stu = (state.students || []).find(row => String(row?.id || '') === sid) || {};
      perDate[sid] = serializeSlots(combinedSlotsForStudent(stu, dateStr, sel.length ? sel : [1]));
    }
    WEEKEND[dateStr] = perDate;

    try {
      // 보강 맵 전체 저장
      await fetch('/api/extra-attend', { method: 'POST', headers: CT, body: JSON.stringify(EXTRA) });
      await fetch('/api/weekend-slots', { method: 'POST', headers: CT, body: JSON.stringify({ [dateStr]: perDate }) });
      const arrivePatch = {};
      for (const sid of selectedIds) {
        const slots = parseSlotNumbers(perDate[sid]);
        const first = slots.length ? Math.min(...slots) : 1;
        arrivePatch[sid] = MAKEUP_ARRIVE_BY_SLOT[first] || '';
      }
      if (Object.keys(arrivePatch).length) {
        await fetch('/arrive-time', {
          method: 'POST',
          headers: CT,
          body: JSON.stringify({ [dateStr]: arrivePatch }),
        });
      }
      await resolveFirstOpenMakeupDemandsForSids(newlyAddedExtraIds);
      alert('보강 저장 완료');
      selectionModal.style.display = 'none';
      // 모달 상단 리스트/뱃지 갱신
      $('attendModal').style.display = 'none';
      openAttendModal(dateStr);
      document.dispatchEvent(new CustomEvent('attendance:updated'));
      if (window.recalcCalendarCounts) await window.recalcCalendarCounts();
      else await refreshMakeupPlanner();
    } catch (e) {
      console.error(e);
      alert('요청에 실패했습니다.');
    }
  });

  selectionClose?.addEventListener('click', () => selectionModal.style.display = 'none');
  document.addEventListener('admin:refresh', () => refreshMakeupPlanner());
  document.addEventListener('attendance:updated', () => refreshMakeupPlanner());
  document.addEventListener('admin:date-change', () => refreshMakeupPlanner());
}

