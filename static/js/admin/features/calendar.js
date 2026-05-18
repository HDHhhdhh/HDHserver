// /js/admin/features/calendar.js
// FullCalendar 월 뷰 + 날짜별 인원 카운트 뱃지 + 출결 모달(+주말 슬롯 선택/보강 병합 저장 - 멀티 슬롯 지원)
import { $, toast } from '../core/utils.js';
import { state } from '../core/state.js';
import { renderTimeGraphForDate } from './timeGraph.js';
import { flattenSchoolCalendarRows, getActiveSchoolCalendarYear } from '../../shared/schoolCalendar.js';
import { applySearchPlaceholder, matchesSearchKey, studentSearchKey } from '../../shared/search.js';
import { buildPendingMakeups, formatMakeupDate, makeupPendingActivationDate } from './makeupPending.js';

export function initCalendar() {
  const calendarEl = $('calendar'); if (!calendarEl) return;

  const CT = { 'Content-Type': 'application/json' };
  const WCHR = '일월화수목금토';
  const MAKEUP_SLOTS = [1, 2];
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
    const pushRawEvent = ({ kind, label, school, grade, span, range, note, sourceText }) => {
      if (!school || !span?.start || !span?.end) return;
      rawEvents.push({
        kind,
        label,
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

      parseDateSpans(row?.midtermMath, activeYear, false).forEach((span) => {
        pushRawEvent({
          kind: 'math',
          label: '수학 시험일',
          school,
          grade,
          span,
          sourceText: row?.midtermMath,
        });
      });

      parseDateSpans(row?.finalMath, activeYear, false).forEach((span) => {
        pushRawEvent({
          kind: 'math',
          label: '수학 시험일',
          school,
          grade,
          span,
          sourceText: row?.finalMath,
        });
      });
    });

    const grouped = new Map();
    for (const row of rawEvents) {
      const key = `${row.kind}|${row.school}|${row.start}|${row.end}`;
      let bucket = grouped.get(key);
      if (!bucket) {
        bucket = {
          kind: row.kind,
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

    // 수학 시험일만 노출
    const order = { math: 1 };
    const subjectLabel = {
      math: '수학',
    };
    const palette = {
      math: { bg: '#0284c7', border: '#0369a1' },
    };

    return [...grouped.values()]
      .sort((a, b) => {
        const dateCmp = String(a.start).localeCompare(String(b.start));
        if (dateCmp !== 0) return dateCmp;
        const typeCmp = (order[a.kind] || 99) - (order[b.kind] || 99);
        if (typeCmp !== 0) return typeCmp;
        return String(a.school).localeCompare(String(b.school), 'ko');
      })
      .map((row) => {
        const gradeToken = compactGradeToken(row.grades);
        const shortSchool = shortSchoolName(row.school);
        const title = `${shortSchool}${gradeToken ? gradeToken : ''} ${subjectLabel[row.kind] || row.label}`;

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

  // 슬롯 버튼 클릭 핸들러 중복 방지 플래그
  let slotClickBound = false;
  let makeupSelection = null;

  // 유틸: 학생이 해당 요일 정규 등원하는지
  function hasWeekday(s, w) {
    return Object.keys(s).some(k => /^day\d+$/.test(k) && String(s[k]).startsWith(w));
  }

  // ✅ 정규 주말 슬롯 추출(학생 스키마에서 요일 숫자 파싱)
  function getRegularWeekendSlots(stu, dateStr) {
    const w = yoil(dateStr);
    if (w !== '토' && w !== '일') return [];
    const vals = Object.keys(stu)
      .filter(k => /^day\d+$/.test(k) && stu[k])
      .map(k => String(stu[k]))
      .filter(v => v.startsWith(w));
    const nums = vals.map(v => {
      const m = v.match(/\d+/);
      return m ? parseInt(m[0], 10) : null;
    }).filter(n => Number.isInteger(n));
    return Array.from(new Set(nums)).sort((a, b) => a - b);
  }

  async function preloadExtraWeekend() {
    try { EXTRA = await fetch('/api/extra-attend', { cache: 'no-store' }).then(r => r.json()); } catch { EXTRA = {}; }
    try { WEEKEND = await fetch('/api/weekend-slots', { cache: 'no-store' }).then(r => r.json()); } catch { WEEKEND = {}; }
  }

  // 월 뷰 범위 내 날짜별 인원 카운트 계산(정규+보강 - 결석)
  async function fetchCountsForRange(start, end) {
    await preloadExtraWeekend();
    const days = []; const cur = new Date(start);
    while (cur < end) { days.push(ymd(cur)); cur.setDate(cur.getDate() + 1); }
    countMap = {};
    for (const dateStr of days) {
      const wchr = yoil(dateStr);
      const regularIds = state.students.filter(s => hasWeekday(s, wchr)).map(s => String(s.id));
      const extraIds = (EXTRA[dateStr] || []).map(String);
      const ids = new Set([...regularIds, ...extraIds]);
      (state.absentByDate[dateStr] || []).map(String).forEach(id => ids.delete(id));
      countMap[dateStr] = ids.size;
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
      badge.textContent = `${countMap[dateStr] || 0}명`;
    });
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
    return `${item.sid}|${item.absenceDate}`;
  }

  function ensureMakeupPlanner() {
    if (document.getElementById('makeupPlanner')) return;
    calendarEl.insertAdjacentHTML('afterend', `
      <section id="makeupPlanner" class="makeup-planner" aria-label="보강 잡기">
        <div class="makeup-planner-head">
          <div>
            <h4>보강 잡기</h4>
            <p id="makeupPlannerHint">내일 이후 결석으로 보강이 필요한 학생입니다.</p>
          </div>
          <input id="makeupPlannerSearch" type="search" autocomplete="off" placeholder="보강 학생 검색">
        </div>
        <div id="makeupPlannerList" class="makeup-planner-list"></div>
      </section>
    `);

    const search = $('makeupPlannerSearch');
    applySearchPlaceholder(search, '보강 학생 검색');
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

    $('makeupPlannerList')?.addEventListener('click', (ev) => {
      const btn = ev.target.closest('[data-makeup-action="pick"]');
      if (!btn) return;
      const key = btn.dataset.key || '';
      const item = getPendingMakeups().find(row => makeupItemKey(row) === key);
      if (!item) return;
      makeupSelection = item;
      closeMakeupSlotPicker();
      renderMakeupPlanner();
      toast('캘린더에서 보강 날짜를 클릭하세요.');
    });
  }

  function getPendingMakeups() {
    return buildPendingMakeups({
      students: state.students || [],
      absentByDate: state.absentByDate || {},
      extra: EXTRA || state.extra || {},
      minAbsenceDate: makeupPendingActivationDate(),
    });
  }

  function renderMakeupPlanner() {
    ensureMakeupPlanner();
    const list = $('makeupPlannerList');
    const hint = $('makeupPlannerHint');
    const search = $('makeupPlannerSearch');
    if (!list) return;

    const queryText = search?.value || '';
    const items = getPendingMakeups();
    const visible = items.filter(item => {
      const key = studentSearchKey(item.student, [
        item.school,
        item.course,
        item.absenceDate,
        formatMakeupDate(item.absenceDate),
      ]);
      return matchesSearchKey(key, queryText);
    });

    if (hint) {
      const suffix = makeupSelection ? ' 날짜 선택 중' : '';
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
      const label = `${item.name || '-'} - ${item.school || '-'} - ${item.course || '-'} - ${formatMakeupDate(item.absenceDate)}`;
      const active = key === activeKey ? ' is-active' : '';
      return `
        <div class="makeup-row${active}" data-key="${escapeAttr(key)}">
          <div class="makeup-label">${escapeHtml(label)}</div>
          <button type="button" class="makeup-pick-btn" data-makeup-action="pick" data-key="${escapeAttr(key)}">보강</button>
        </div>
      `;
    }).join('');
  }

  async function refreshMakeupPlanner() {
    await preloadExtraWeekend();
    renderMakeupPlanner();
  }

  function closeMakeupSlotPicker() {
    document.querySelectorAll('.makeup-slot-popover').forEach(el => el.remove());
  }

  function cancelMakeupSelection() {
    makeupSelection = null;
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
    if (String(dateStr) <= String(makeupSelection.absenceDate)) {
      alert('결석일 이후 날짜를 선택해주세요.');
      return;
    }

    await preloadExtraWeekend();

    const sid = String(makeupSelection.sid);
    const dayIds = new Set((EXTRA[dateStr] || []).map(String));
    dayIds.add(sid);
    EXTRA[dateStr] = Array.from(dayIds);
    state.extra = EXTRA;
    window.extra = state.extra;

    const perDaySlots = WEEKEND[dateStr] || {};
    perDaySlots[sid] = [slot];
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
        value: MAKEUP_ARRIVE_BY_SLOT[slot] || '',
      }),
    });

    toast('보강 저장 완료');
    makeupSelection = null;
    closeMakeupSlotPicker();
    await refreshMakeupPlanner();
    await window.recalcCalendarCounts?.();
    document.dispatchEvent(new CustomEvent('admin:refresh', { detail: { force: true } }));
  }

  const calBadge = $('calTodayBadge');
  let schoolExamEvents = buildSchoolExamEvents();
  const firstExamDate = schoolExamEvents[0]?.start || undefined;
  let movedToExamMonth = !!firstExamDate;

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

  const calendar = new FullCalendar.Calendar(calendarEl, {
    initialView: 'dayGridMonth',
    initialDate: firstExamDate,
    locale: 'ko',
    dayMaxEvents: false,
    dayMaxEventRows: false,
    events: schoolExamEvents,
    dayCellContent: (arg) => ({ html: `<span class="cal-day-number">${arg.date.getDate()}</span>` }),
    eventOrderStrict: true,
    eventOrder: (a, b) => {
      const oa = Number(a.extendedProps?.order ?? 99);
      const ob = Number(b.extendedProps?.order ?? 99);
      if (oa !== ob) return oa - ob;
      return String(a.title || '').localeCompare(String(b.title || ''), 'ko');
    },
    dateClick: info => {
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
      fetchCountsForRange(range.start, range.end).then(refreshCountBadges);
      refreshMakeupPlanner();
    }
  });
  calendar.render();
  ensureMakeupPlanner();
  refreshMakeupPlanner();
  updateExamBadge(schoolExamEvents.length, 'cache');

  document.addEventListener('keydown', (ev) => {
    if (ev.key !== 'Escape' || !makeupSelection) return;
    ev.preventDefault();
    cancelMakeupSelection();
  });

  let wheelRowLocked = false;
  function calendarRowScrollAmount() {
    const row = calendarEl.querySelector('.fc-daygrid-body tr');
    const h = row?.getBoundingClientRect?.().height || 82;
    return Math.max(56, Math.round(h));
  }

  function canScrollCalendar(delta) {
    const max = calendarEl.scrollHeight - calendarEl.clientHeight;
    if (max <= 1) return false;
    if (delta > 0) return calendarEl.scrollTop < max - 1;
    return calendarEl.scrollTop > 1;
  }

  calendarEl.addEventListener('wheel', (ev) => {
    const delta = Math.abs(ev.deltaY) >= Math.abs(ev.deltaX) ? ev.deltaY : ev.deltaX;
    if (Math.abs(delta) < 24 || !canScrollCalendar(delta)) return;
    ev.preventDefault();
    ev.stopPropagation();
    if (wheelRowLocked) return;
    wheelRowLocked = true;
    calendarEl.scrollBy({
      top: (delta > 0 ? 1 : -1) * calendarRowScrollAmount(),
      behavior: 'smooth',
    });
    window.setTimeout(() => { wheelRowLocked = false; }, 180);
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
    if (!movedToExamMonth && events[0]?.start) {
      calendar.gotoDate(events[0].start);
      movedToExamMonth = true;
    }
    updateExamBadge(events.length, source);
  }

  // Run once after render in case initial bootstrap missed school calendar payload.
  refreshSchoolExamEvents();

  // 외부에서 새로고침 필요할 때 호출
  window.recalcCalendarCounts = function () {
    return fetchCountsForRange(calendar.view.currentStart, calendar.view.currentEnd)
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

      // 리스트: 주말이면 “정규+보강” 슬롯 합쳐서 표기(예: 일2·일3)
      listEl.innerHTML = att.map(s => {
        const sid = String(s.id);
        const isExtra = extras.includes(sid);

        let tail = '';
        if (isWeekend(dateStr)) {
          const regular = getRegularWeekendSlots(s, dateStr);               // 정규
          const raw = slotMap[sid];                                         // 보강
          const extraArr = Array.isArray(raw) ? raw.slice() : [Number.isInteger(raw) ? raw : undefined].filter(Boolean);
          const merged = Array.from(new Set([...regular, ...extraArr])).sort((a, b) => a - b);
          if (isExtra && merged.length) {
            const mark = merged.map(n => `${yoil(dateStr)}${n}`).join('·');
            tail = `<span style="color:#2563eb;margin-left:6px">[${mark}]</span>`;
          }
        }

        return `<li data-id="${s.id}" style="margin:4px 0;">
          ${s.name} (${s.curriculum}${s.subCurriculum ? ' ' + s.subCurriculum : ''}) ${tail}
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

  function slotLegend() {
    return `
      <div style="display:flex;gap:6px;align-items:center;
           padding:6px 8px;margin-bottom:8px;border:1px dashed #3b82f6;border-radius:8px;font-size:12px">
        <b>주말 타임 선택</b>
        <span>1</span><span>2</span><span>3</span>
        <small style="opacity:.7">여러 개 클릭 가능(예: 1·3 → 연강)</small>
      </div>`;
  }

  function studentRow(s, dateStr, preChecked, curSlots) {
    const weekend = isWeekend(dateStr);
    const has = new Set((Array.isArray(curSlots) ? curSlots : [curSlots]).filter(n => Number.isInteger(n)));
    return `
      <li data-id="${s.id}" style="display:flex;align-items:center;justify-content:space-between;gap:8px;margin:4px 0">
        <label style="display:flex;align-items:center;gap:8px;flex:1;cursor:pointer">
          <input type="checkbox" class="chk-sid" ${preChecked ? 'checked' : ''}>
          <span>${s.name}</span>
          <small style="opacity:.65">${s.curriculum || ''}${s.subCurriculum ? ' · ' + s.subCurriculum : ''}</small>
        </label>
        ${weekend ? `
          <div class="slot-box" style="display:flex;gap:6px">
            ${[1, 2, 3].map(n => `
              <button type="button" class="slot-btn ${has.has(n) ? 'on' : ''}" data-slot="${n}"
                style="min-width:32px;height:28px;border:1px solid #64748b;border-radius:6px;
                       background:${has.has(n) ? '#3b82f6' : 'transparent'};color:${has.has(n) ? '#fff' : 'inherit'}">${n}</button>
            `).join('')}
          </div>` : ``}
      </li>`;
  }

  function openSelectionUI(mode) {
    const dateStr = $('attendDateTitle').textContent.split(' ')[0]; // "YYYY-MM-DD (요일)" → 날짜만
    Promise.all([
      fetch(`/api/attend?date=${dateStr}`, { cache: 'no-store' }).then(r => r.json()),
      fetch('/api/extra-attend', { cache: 'no-store' }).then(r => r.json()),
      fetch('/api/weekend-slots', { cache: 'no-store' }).then(r => r.json()).catch(() => ({}))
    ]).then(([todayAtt, extraMap, weekendMap]) => {
      EXTRA = extraMap || {};
      WEEKEND = weekendMap || {};

      // 목록 소스: 결석 처리는 오늘 등원자만, 보강은 전체 학생
      const listSource = mode === 'absent' ? todayAtt : (state.students || []).slice()
        .sort((a, b) => String(a.name).localeCompare(String(b.name), 'ko'));

      const pre = new Set((EXTRA[dateStr] || []).map(String));
      const perDateSlot = WEEKEND[dateStr] || {};
      const weekend = isWeekend(dateStr);

      selectionListEl.innerHTML =
        (mode === 'extra' && weekend ? slotLegend() : '') +
        listSource.map(s => {
          const sid = String(s.id);
          const checked = mode === 'extra' ? pre.has(sid) : false;
          // ⚠️ UI의 기본 선택 슬롯은 "보강 슬롯"만 반영(정규는 안내용으로만 쓰고 저장은 따로)
          const curSlots = weekend ? (perDateSlot[sid] ?? 1) : 0;
          return studentRow(s, dateStr, checked, curSlots);
        }).join('');

      // 행 클릭 시 배경 토글
      selectionListEl.querySelectorAll('li').forEach(li => {
        const lab = li.querySelector('label');
        if (lab) {
          lab.addEventListener('click', () => {
            li.classList.toggle('selected', li.querySelector('.chk-sid').checked);
            li.style.background = li.classList.contains('selected') ? 'rgba(59,130,246,0.15)' : '';
          });
          if (li.querySelector('.chk-sid')?.checked) {
            li.classList.add('selected');
            li.style.background = 'rgba(59,130,246,0.15)';
          }
        }
      });

      // 슬롯 버튼 클릭 핸들러: 한 번만 바인딩(중복 방지)
      if (!slotClickBound) {
        selectionListEl.addEventListener('click', onSlotClick);
        slotClickBound = true;
      }

      selectionModal.dataset.mode = mode;
      selectionModal.dataset.date = dateStr;
      selectionModal.style.display = 'flex';
    });
  }

  // 슬롯 버튼 클릭 핸들러 (이벤트 위임)
  function onSlotClick(e) {
    const btn = e.target.closest('.slot-btn');
    if (!btn) return;
    const li = btn.closest('li[data-id]');
    if (!li) return;

    btn.classList.toggle('on');
    const on = btn.classList.contains('on');
    btn.style.background = on ? '#3b82f6' : 'transparent';
    btn.style.color = on ? '#fff' : 'inherit';

    // 자동 체크
    const chk = li.querySelector('.chk-sid');
    if (chk && !chk.checked) {
      chk.checked = true;
      li.classList.add('selected');
      li.style.background = 'rgba(59,130,246,0.15)';
    }
  }

  // 저장(보강: 체크된 학생만 남기고, 주말 슬롯은 배열로 저장 가능)
  selectionSaveBtn?.addEventListener('click', async () => {
    const mode = selectionModal.dataset.mode, dateStr = selectionModal.dataset.date;
    const weekend = isWeekend(dateStr);

    const items = [...selectionListEl.querySelectorAll('li[data-id]')];
    const selectedIds = items.filter(li => li.querySelector('.chk-sid')?.checked)
      .map(li => String(li.dataset.id));

    // ── 결석 처리 ──
    if (mode === 'absent') {
      selectedIds.forEach(id => { state.absences[id] = dateStr; });
      const set = new Set([...(state.absentByDate[dateStr] || []), ...selectedIds]);
      state.absentByDate[dateStr] = [...set];
      try {
        await fetch('/api/absent', {
          method: 'POST', headers: CT,
          body: JSON.stringify({ by_date: state.absentByDate, by_student: state.absences })
        });
        alert('결석 처리 완료');
        selectionModal.style.display = 'none';
        window.recalcCalendarCounts && window.recalcCalendarCounts();
        refreshMakeupPlanner();
      } catch { alert('요청에 실패했습니다.'); }
      return;
    }

    // ── 보강 추가/해제 ──
    await preloadExtraWeekend(); // 최신화
    const nextSet = new Set(selectedIds);
    EXTRA[dateStr] = Array.from(nextSet); // 체크 해제된 학생은 제거

    // 주말 슬롯 저장 (여러 개 가능) — 저장은 "보강 슬롯"만
    if (weekend) {
      const perDate = WEEKEND[dateStr] || {};
      // 먼저, 선택되지 않은 학생의 보강 슬롯 제거
      for (const sid of Object.keys(perDate)) {
        if (!nextSet.has(String(sid))) delete perDate[sid];
      }
      // 선택된 학생의 보강 슬롯 갱신
      for (const li of items) {
        const sid = String(li.dataset.id);
        if (!nextSet.has(sid)) continue;
        const sel = [...li.querySelectorAll('.slot-btn.on')].map(b => parseInt(b.dataset.slot, 10)).sort((a, b) => a - b);
        // 1개면 숫자, 2개 이상이면 배열로 저장(정규와 합치는 건 표시/정렬 시에만 처리)
        perDate[sid] = sel.length <= 1 ? (sel[0] || 1) : sel;
      }
      WEEKEND[dateStr] = perDate;
    }

    try {
      // 보강 맵 전체 저장
      await fetch('/api/extra-attend', { method: 'POST', headers: CT, body: JSON.stringify(EXTRA) });
      // 주말 슬롯도 전체 맵 저장 (한 날짜만 보내지 말고 전체)
      if (weekend) {
        await fetch('/api/weekend-slots', { method: 'POST', headers: CT, body: JSON.stringify(WEEKEND) });
      }
      alert('보강 저장 완료');
      selectionModal.style.display = 'none';
      // 모달 상단 리스트/뱃지 갱신
      $('attendModal').style.display = 'none';
      openAttendModal(dateStr);
      window.recalcCalendarCounts && window.recalcCalendarCounts();
      refreshMakeupPlanner();
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

