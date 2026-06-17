// /static/js/admin/features/hoverTooltip.js
import { state } from '../core/state.js';
import { ensureProgressForSid } from '../core/state.js';
import { resolveSchoolCalendarEntry, resolveSchoolCalendarEntries } from '../../shared/schoolCalendar.js';

let tipEl = null;
let mode = 'hover';          // 'hover' | 'fixed'
let fixedSource = null;      // 'log' 등

export function initHoverTooltip() {

  function ensureTip() {
    if (tipEl) return tipEl;
    tipEl = document.createElement('div');
    tipEl.id = 'adminSchoolTip';
    tipEl.style.cssText = `
      position: fixed;
      top: 0; left: 0;
      background: rgba(17,24,39,.98); color: #fff; border-radius: 14px;
      padding: 14px 16px; font-size: 14px; box-shadow: 0 10px 28px rgba(0,0,0,.4);
      z-index: 100000; pointer-events: none; display: none;
      max-width: min(1100px, 92vw);
      max-height: min(86vh, 900px);
      overflow-x: hidden;
      overflow-y: auto;
      line-height: 1.5;
      transform: translate(0, 0);
      box-sizing: border-box;
    `;
    document.body.appendChild(tipEl);
    return tipEl;
  }

  const pill = (label, value) => `
    <div style="
      display:flex; flex-direction:column; gap:2px;
      background:rgba(255,255,255,.06);
      border:1px solid rgba(255,255,255,.12);
      padding:6px 10px; border-radius:10px; min-width:92px;">
      <div style="font-size:11px; opacity:.85">${label}</div>
      <div style="font-weight:700; white-space:normal; line-height:1.25; word-break:keep-all;">${value || '-'}</div>
    </div>`;

  const em = (label, value) => `
    <div style="display:flex; gap:6px;">
      <div style="min-width:54px; opacity:.8">${label}</div>
      <div style="font-weight:700; word-break:break-word">${value || '-'}</div>
    </div>`;

  // ───────────────────────────────────────────
  // 학사일정: 현재 시점에 더 가까운 시험을 우선 표시
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

  // ───────────────────────────────────────────
  // 영상/테스트 표시 (가로 스크롤 제거: flex-wrap)
  // ───────────────────────────────────────────
  function renderProgressTables(stu) {
    const today = new Date().toISOString().slice(0, 10);

    // 누적 progress 병합(오늘 포함, 최신이 우선)
    const allDates = Object.keys(state.progress || {}).filter(d => d <= today).sort();
    const mergedProg = {};   // { mid: status }
    const mergedTests = {};  // { testName: 'done' | ... }

    allDates.forEach(d => {
      const per = state.progress[d]?.[stu.id] || {};
      Object.entries(per).forEach(([k, v]) => {
        if (String(k).startsWith('__') || k === 'tests') return;
        mergedProg[k] = v;
      });
      if (per.tests && typeof per.tests === 'object') {
        Object.entries(per.tests).forEach(([tname, st]) => {
          mergedTests[tname] = st;
        });
      }
    });

    // 해당 커리큘럼/서브 커리큘럼 영상만
    const vids = (state.videos || [])
      .filter(v => v.curriculum === stu.curriculum && v.subCurriculum === stu.subCurriculum)
      .sort((a, b) => (a.chapter ?? 0) - (b.chapter ?? 0));

    const colorFor = (st) =>
      st === 'done'        ? '#10b981' :
      st === 'interrupted' ? '#f59e0b' :
      st === 'skip'        ? '#6b7280' :
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

    const progBlock = `
      <div style="margin-top:10px;font-weight:800;font-size:13px">영상 진도</div>
      <div style="
        display:flex; flex-wrap:wrap; gap:0;
        align-items:center; max-width:100%;
      ">
        ${progCells || '<div style="padding:6px 8px;color:#bbb">해당 차시 없음</div>'}
      </div>
    `;

    // 테스트 완료 여부
    const logsDates = Object.keys(state.logs || {}).filter(d => d <= today).sort();
    const takenMap = {};
    logsDates.forEach(d => {
      const entry = state.logs[d]?.[stu.id];
      const tests = Array.isArray(entry?.tests) ? entry.tests : [];
      tests.forEach(t => {
        const nm = String(t.name || '').trim();
        if (nm) takenMap[nm] = true;
      });
    });

    const norm = (s) => {
      const raw = String(s || '').toLowerCase().replace(/\s+/g, '');
      const m = raw.match(/(final|파이널|hell|헬)\s*([0-9]+)/);
      if (m) return `${m[1].replace('파이널','final').replace('헬','hell')}${m[2]}`;
      return raw;
    };

    const doneSet = new Set([
      ...Object.entries(mergedTests).filter(([, st]) => st === 'done').map(([k]) => norm(k)),
      ...Object.keys(takenMap).map(norm),
    ]);

    const testChip = (name, label = name) => {
      const ok = doneSet.has(norm(name));
      const color = ok ? '#10b981' : '#1f2937';
      const tt = `${label} (${ok ? '완료' : '미응시'})`;
      return `
        <div title="${tt}"
             style="
               padding:4px 8px; margin:3px; border:1px solid #111; background:${color};
               color:#fff; font-size:11px; white-space:nowrap; border-radius:8px; flex:0 0 auto;">
          ${label}
        </div>`;
    };

    const UNIT_LIST = [
      '명제1','명제2'
    ].map(n => [n, n]);
    const FINAL_LIST = [1,2,3,4].map(n => [`final${n}`, `파이널 ${n}`]);
    const HELL_LIST  = [1,2,3,4].map(n => [`hell${n}`,  `헬 ${n}`]);

    const chipRow = (pairs) => `
      <div style="display:flex; flex-wrap:wrap; align-items:center; max-width:100%;">
        ${pairs.map(([k, label]) => testChip(k, label)).join('')}
      </div>`;

    const unitBlock = `
      <div style="margin-top:10px;font-weight:800;font-size:13px">테스트(단원평가)</div>
      ${chipRow(UNIT_LIST)}
    `;
    const finalBlock = `
      <div style="margin-top:8px;font-weight:800;font-size:13px">파이널</div>
      ${chipRow(FINAL_LIST)}
    `;
    const hellBlock = `
      <div style="margin-top:8px;font-weight:800;font-size:13px">헬</div>
      ${chipRow(HELL_LIST)}
    `;

    return progBlock + unitBlock + finalBlock + hellBlock;
  }

  // 툴팁 공통 HTML 빌더
  function buildTooltipHTML(stu, { includeProgress } = { includeProgress: true }) {
    const name = (stu.name || '').trim();
    const level = stu.level || '';
    const days = [stu.day1, stu.day2, stu.day3].filter(Boolean).join('·');
    const subBooks = [stu.subBook1, stu.subBook2].filter(Boolean).join(', ');

    const schoolName =
      stu.school ||
      stu.highSchool || stu.schoolHigh || stu.high || stu.highschool || stu.high_school || stu['고등학교'] ||
      stu.middleSchool || stu.schoolMiddle || stu.middle || stu.middleschool || stu.middle_school || stu['중학교'] || '';

    const scheduleEntries = resolveSchoolCalendarEntries(state.schoolCal, schoolName, stu.grade);
    const sc = scheduleEntries[0] || resolveSchoolCalendarEntry(state.schoolCal, schoolName, stu.grade);
    const textbook =
      sc.textbook || sc.mathTextbook || sc.book || sc.mathBook || sc['교과서'] || sc['수학교과서'] || '';

    const badgeColor =
      level === '상'   ? '#2563eb' :
      level === '중상' ? '#f59e0b' :
      level === '중'   ? '#16a34a' :
                         '#ef4444';

    const levelBadge = level
      ? `<span style="display:inline-block;margin-left:6px;padding:2px 8px;border-radius:999px;
                      background:${badgeColor}; color:#fff; font-size:12px; font-weight:700; vertical-align:middle;">
           ${level}
         </span>`
      : '';

    const mainBlock = `
      <div style="font-weight:900;font-size:17px; margin-bottom:6px">
        ${name}${levelBadge}
      </div>
      ${schoolName ? `<div style="font-size:14px; font-weight:600; margin-bottom:6px">${schoolName}</div>` : ''}
      <div style="font-size:13px; margin-bottom:4px">
        ${days ? `<span style="margin-right:8px">📅 ${days}</span>` : ''}
        ${subBooks ? `<span style="margin-right:8px">📘 ${subBooks}</span>` : ''}
        ${textbook ? `<span>📕 ${textbook}</span>` : ''}
      </div>
    `;

    const examRows = (scheduleEntries.length ? scheduleEntries : [sc]).map((entry, idx) => {
      const exam = pickExam(entry || {}, 'auto');
      const phase = String(entry?.phase || '').trim();
      const rowGrade = String(entry?.grade || stu.grade || '').trim();
      const rowLabel = phase
        ? (rowGrade ? `${rowGrade} · ${phase}` : phase)
        : (scheduleEntries.length > 1 ? (rowGrade || `트랙 ${idx + 1}`) : '');

      return `
        <div style="margin-top:${idx === 0 ? 6 : 10}px; display:block; font-size:12px; max-width:100%">
          ${rowLabel ? `<div style="margin-bottom:6px; font-size:11.5px; font-weight:800; opacity:.86">${rowLabel}</div>` : ''}
          <div style="display:flex; gap:8px; flex-wrap:wrap; margin-top:0; max-width:100%">
            ${pill(exam.label, exam.date || '-')}
            ${pill('수학시험일', exam.math || '-')}
          </div>
          <div style="margin-top:8px; border:1px solid rgba(255,255,255,.12); border-radius:10px; padding:8px">
            <div style="font-weight:800; margin-bottom:4px">${exam.label} 범위/특이사항</div>
            ${em('범위', exam.range)}
            ${em('비고', exam.note)}
          </div>
        </div>
      `;
    }).join('');

    const examTitle = scheduleEntries.length > 1 ? '학사일정 (과목/트랙별)' : '학사일정';
    const examBlock = schoolName
      ? `<div style="margin-top:10px; font-size:12.5px; font-weight:800; opacity:.9">${examTitle}</div>${examRows}`
      : '<div style="opacity:.8;margin-top:6px;font-size:12px">학교 정보 없음</div>';

    const progTables = includeProgress ? renderProgressTables(stu) : '';

    return `${mainBlock}${examBlock}${progTables}`;
  }

  // ───────────────────────────────────────────
  // hover 모드 위치
  // ───────────────────────────────────────────
  function placeTooltipFollowCursor(ev) {
    if (!tipEl) return;

    const pad = 12;
    const vw = window.innerWidth, vh = window.innerHeight;
    const rect = tipEl.getBoundingClientRect();

    let left = ev.clientX + 12;
    let top  = ev.clientY + 12;

    if (left + rect.width + pad > vw) {
      left = Math.max(pad, ev.clientX - rect.width - 12);
    }
    if (top + rect.height + pad > vh) {
      top = Math.max(pad, ev.clientY - rect.height - 12);
    }

    left = Math.min(Math.max(pad, left), vw - pad - rect.width);
    top  = Math.min(Math.max(pad, top),  vh - pad - rect.height);

    tipEl.style.left = `${left}px`;
    tipEl.style.top  = `${top}px`;
  }

  async function onOver(ev) {
    if (mode !== 'hover') return;
    if (!(ev.target instanceof Element)) return;
    const a = ev.target.closest('a.stuName');
    if (!a) return;

    const sid = a.dataset.sid;
    const name = (a.textContent || '').trim();

    const stu = (state.students || []).find(s => String(s.id) === String(sid))
      || (state.students || []).find(s => (s.name || '').trim() === name);
    if (!stu) return;

    const el = ensureTip();
    el.innerHTML = buildTooltipHTML(stu, { includeProgress: false });
    el.style.display = 'block';

    requestAnimationFrame(() => {
      placeTooltipFollowCursor(ev);
    });

    await ensureProgressForSid(stu.id);
    if (mode !== 'hover' || tipEl !== el || el.style.display === 'none') return;
    el.innerHTML = buildTooltipHTML(stu, { includeProgress: true });
    requestAnimationFrame(() => {
      placeTooltipFollowCursor(ev);
    });
  }

  function onMove(ev) {
    if (mode !== 'hover') return;
    if (!tipEl || tipEl.style.display === 'none') return;
    placeTooltipFollowCursor(ev);
  }

  function onOut(ev) {
    if (mode !== 'hover') return;
    if (!(ev.target instanceof Element)) return;
    const from = ev.target.closest('a.stuName');
    const to = (ev.relatedTarget instanceof Element) ? ev.relatedTarget.closest('a.stuName') : null;
    if (from && !to && tipEl) tipEl.style.display = 'none';
  }

  document.addEventListener('pointerover', onOver);
  document.addEventListener('pointermove', onMove);
  document.addEventListener('pointerout', onOut);
}

/* ─────────────────────────────────────────────
 * 로그 모달용 고정 툴팁: 박스 왼쪽, 툴팁 오른쪽
 *  - 영상 진도 블록은 생략(텍스트만)
 *  - hoverTooltip 와 별개 모드라 마우스 따라다니지 않음
 *  - anchorRect: #logModal .log-card 의 getBoundingClientRect()
 * ────────────────────────────────────────────*/
export function showStudentTooltipForLog(stu, anchorRect) {
  const el = (tipEl || document.getElementById('adminSchoolTip')) || null;
  const ensure = () => {
    if (tipEl) return tipEl;
    tipEl = document.getElementById('adminSchoolTip');
    if (!tipEl) {
      tipEl = document.createElement('div');
      tipEl.id = 'adminSchoolTip';
      document.body.appendChild(tipEl);
    }
    return tipEl;
  };
  const box = ensure();

  mode = 'fixed';
  fixedSource = 'log';

  box.style.display = 'block';
  box.style.pointerEvents = 'none';
  box.innerHTML = buildTooltipHTML(stu, { includeProgress: false });

  requestAnimationFrame(() => {
    const pad = 16;
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const rect = box.getBoundingClientRect();

    const card = anchorRect || { left: vw / 2 - 200, right: vw / 2 + 200, top: vh / 2 - 200 };

    // 기본: 카드 오른쪽에 붙이기
    let left = card.right + pad;
    let top = card.top;

    // 오른쪽이 모자라면 카드 왼쪽으로 보내기
    if (left + rect.width + pad > vw) {
      left = Math.max(pad, card.left - rect.width - pad);
    }

    // 세로도 화면 안에 들어오도록
    if (top + rect.height + pad > vh) {
      top = Math.max(pad, vh - rect.height - pad);
    }

    box.style.left = `${left}px`;
    box.style.top  = `${top}px`;
  });
}

export function hideStudentTooltipForLog() {
  if (!tipEl) return;
  if (fixedSource === 'log') {
    tipEl.style.display = 'none';
    fixedSource = null;
    mode = 'hover';
  }
}
