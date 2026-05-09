import { getAdminDate } from '../core/adminDate.js';
import { getLeaveTime, labelFor, plannedTimeFor } from './today.state.js';

console.log('[timeGraph] VERSION 2026-04-01 - Synced with today table');

const ARRIVE_TIME_MAP = { '1': '13:00', '2': '18:00' };

function minutesFromTimeStr(str) {
  if (!str) return null;
  const s = String(str).replace(/[^0-9:]/g, '');
  if (!s) return null;

  if (s.includes(':')) {
    const [h, m] = s.split(':');
    const hh = parseInt(h, 10);
    const mm = parseInt(m, 10);
    if (!Number.isFinite(hh) || !Number.isFinite(mm)) return null;
    return hh * 60 + mm;
  }

  const h = parseInt(s, 10);
  return (h >= 0 && h <= 24) ? h * 60 : null;
}

function injectStyles() {
  if (document.getElementById('timeGraphStyles')) return;
  const s = document.createElement('style');
  s.id = 'timeGraphStyles';
  s.textContent = `
    #timeGraphWrap, #timeGraphWrapForDate { padding:10px 12px; border-radius:10px; background:rgba(15,23,42,0.04); border:1px solid rgba(148,163,184,0.35); font-size:12px; margin-bottom:10px; }
    body.dark #timeGraphWrap, body.dark #timeGraphWrapForDate { background:rgba(15,23,42,0.75); border-color:rgba(148,163,184,0.5); }
    .tg-title { font-size:13px; font-weight:600; margin-bottom:6px; display:flex; align-items:center; gap:6px; }
    .tg-body { display:flex; flex-direction:column; gap:4px; }
    .tg-row { display:grid; grid-template-columns:75px 1fr 40px; align-items:center; gap:6px; }
    .tg-bar-bg { position:relative; height:8px; border-radius:999px; background:rgba(148,163,184,0.25); overflow:hidden; }
    .tg-bar-fill { position:absolute; inset:0; width:0; border-radius:999px; background:#0ea5e9; transition:width .18s; }
    body.dark .tg-bar-fill { background:#38bdf8; }
    .tg-count { text-align:right; font-variant-numeric:tabular-nums; opacity:.9; }
  `;
  document.head.appendChild(s);
}

function parseSlotNumbers(labelText) {
  const nums = (String(labelText || '').match(/[1-3]/g) || [])
    .map(n => parseInt(n, 10))
    .filter(n => Number.isInteger(n) && n >= 1 && n <= 3);
  return Array.from(new Set(nums)).sort((a, b) => a - b);
}

function buildGraphSources(dateStr, students) {
  if (!Array.isArray(students)) return [];

  return students
    .map(stu => {
      const sid = String(stu?.id ?? '').trim();
      if (!sid) return null;

      return {
        sid,
        labelText: String(labelFor(dateStr, sid) || '').trim(),
        arriveTime: String(plannedTimeFor(dateStr, sid) || '').trim(),
        leaveTime: String(getLeaveTime(dateStr, sid) || '').trim(),
      };
    })
    .filter(Boolean);
}

function getSourceSpans(source) {
  if (!source || source.leaveTime) return [];

  const slots = parseSlotNumbers(source.labelText);
  if (!slots.length) slots.push(1);

  const arriveMin = minutesFromTimeStr(source.arriveTime);
  const spans = [];

  slots.forEach(num => {
    const baseMin = minutesFromTimeStr(ARRIVE_TIME_MAP[String(num)] || '13:00');
    if (baseMin === null) return;

    let startMin = baseMin;
    if (arriveMin !== null) {
      if (num === 1) {
        startMin = arriveMin;
      } else {
        startMin = (arriveMin > baseMin - 60) ? Math.max(arriveMin, baseMin) : baseMin;
      }
    }

    spans.push({ start: startMin, end: startMin + 240 });
  });

  return spans;
}

function renderTimeGraphInto(dateStr, wrap, emptyLabel, students) {
  const sources = buildGraphSources(dateStr, students);
  const allSpans = sources.flatMap(getSourceSpans);

  if (!allSpans.length) {
    wrap.innerHTML = `<div class="tg-title">시간대별 인원 <small style="color:red; margin-left:5px;">${emptyLabel}</small></div>`;
    return;
  }

  const slots = [];
  for (let h = 10; h < 22; h++) {
    const s = h * 60;
    const e = (h + 1) * 60;
    const cnt = allSpans.filter(sp => sp.start < e && sp.end > s).length;
    slots.push({ hour: h, count: cnt });
  }

  const max = Math.max(...slots.map(s => s.count)) || 1;
  wrap.innerHTML = `
    <div class="tg-title">시간대별 예상/실제 인원 <small>(${dateStr})</small></div>
    <div class="tg-body">${slots.map(s => `
      <div class="tg-row">
        <div class="tg-label">${s.hour}~${s.hour + 1}시</div>
        <div class="tg-bar-bg"><div class="tg-bar-fill" style="width:${(s.count / max) * 100}%;"></div></div>
        <div class="tg-count">${s.count}명</div>
      </div>`).join('')}</div>`;
}

export function renderTimeGraphForDate(dateStr, students, wrapId = 'timeGraphWrapForDate') {
  injectStyles();
  const wrap = document.getElementById(wrapId);
  if (!wrap) return;
  renderTimeGraphInto(dateStr, wrap, '(데이터 없음)', students || []);
}

export function renderTimeGraph(dateStr = getAdminDate(), students = []) {
  injectStyles();
  const wrap = document.getElementById('timeGraphWrap');
  if (!wrap) return;
  renderTimeGraphInto(dateStr, wrap, '(오늘 학생 없음)', students || []);
}

export function initTimeGraph() {
  injectStyles();

  document.addEventListener('today:rendered', (ev) => {
    const detail = ev?.detail || {};
    renderTimeGraph(detail.dateKey || getAdminDate(), Array.isArray(detail.students) ? detail.students : []);
  });
}
