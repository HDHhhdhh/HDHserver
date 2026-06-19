// /js/admin/features/exportLogs.js
// 수업 기록 텍스트 내보내기
// - ✅ 대상: 날짜 상관없이 "done=true && archived!=true" 인 기록들(학생별 최신 1건)
// - 해당 기록 날짜 기준으로, 그 날짜 이전 누적 진도와 비교해 "그날 바뀐 것"만 출력
// - ✅ '건너뜀(skip)'은 내보내기에서 제외
// - ✅ 진도 항목은 '챕터 숫자' 기준으로 정렬해서 출력
// - 테스트/숙제/특이사항 포함
//
// ✅ 숙제 출력: 괄호 없이 "교재 / 이번숙제 / 진행률 / 코멘트 / 다음숙제"  (빈칸은 공백으로 유지)
// ✅ 숙제 블록에 컬럼명(헤더) 라인을 항상 출력
// ✅ (추가) 다운로드 파일명에 관리자 선택 날짜(YYYY-MM-DD) 포함
// ✅ (추가) 특이사항(notes/memo/special 등) 내용 있으면 출력

import { $, toast } from '../core/utils.js';
import { state } from '../core/state.js';
import { getAdminDate } from '../core/adminDate.js';
import {
  loadWeekendSlots,
  hasWeekday,
  yoilOf,
  truthy,
  labelFor,
  getSlots,
} from './today.state.js';

const ALL_STUDENTS_PROGRESS_META = '__allStudentsProgressMids';
const ROSTER_TEXT_DEFAULT = '📢도착 예정 시간 알려주세요!';
const ROSTER_DAILY_TESTS_KEY = 'testAssignmentDailyTests';
const ROSTER_TEST_CLEAR_KEY = '__testsClearedAt';
const ROSTER_TEST_STATUS_EXPORT = new Set(['assigned']);
const ROSTER_TEST_STATUS_ACTIVE = new Set(['assigned', 'interrupted']);
const ROSTER_TEST_CATEGORY_ORDER = ['REVIEW', 'UNIT', 'SCHOOL_PAST', 'ILSAN_PAST'];
const ROSTER_HISTORY_CACHE_SEP = '\u241f';

let rosterHistoryCache = null;

function resetRosterHistoryCache() {
  rosterHistoryCache = {
    progressRef: state.progress || null,
    logsRef: state.logs || null,
    datesByTarget: new Map(),
    testRelevantDatesByTarget: new Map(),
    previousAssignedByKey: new Map(),
    previousActiveByKey: new Map(),
  };
}

function ensureRosterHistoryCache() {
  if (
    !rosterHistoryCache ||
    rosterHistoryCache.progressRef !== (state.progress || null) ||
    rosterHistoryCache.logsRef !== (state.logs || null)
  ) {
    resetRosterHistoryCache();
  }
  return rosterHistoryCache;
}

/* ─────────────────────────────────────────────
 * ✅ 숙제 출력(헤더 포함, 괄호 제거 버전)
 *  - 5칸: 교재 / 이번숙제 / 진행률 / 코멘트 / 다음숙제
 *  - 빈칸은 ''로 두되, 구분자는 항상 유지(형태 고정)
 * ────────────────────────────────────────────*/
const HW_HEADER_LINE = '교재 / 이번 숙제 / 진행률 / 코멘트 / 다음숙제';

function normStr(v) { return String(v ?? '').trim(); }

function hwRowToFields(r) {
  const book = normStr(r?.book ?? r?.textbook ?? r?.name ?? r?.교재 ?? '');

  const thisHw = normStr(
    r?.thisHw ?? r?.this ?? r?.current ?? r?.unit ?? r?.이번숙제 ?? r?.이번 ?? r?.숙제 ?? ''
  );

  let pct = (r?.pct ?? r?.progress ?? r?.percent ?? r?.진행률 ?? '');
  pct = (pct === '' || pct == null) ? '' : String(pct).trim();
  if (pct && !pct.includes('%')) pct = `${pct}%`;

  const comment = normStr(r?.comment ?? r?.memo ?? r?.note ?? r?.코멘트 ?? r?.비고 ?? '');
  const nextHw  = normStr(r?.nextHw ?? r?.next ?? r?.nextHomework ?? r?.다음숙제 ?? r?.다음 ?? '');

  return { book, thisHw, pct, comment, nextHw };
}

function hwFieldsHaveContent(fields) {
  if (!fields || typeof fields !== 'object') return false;
  return !!(fields.book || fields.thisHw || fields.pct || fields.comment || fields.nextHw);
}

function hwRowToLine(r) {
  const fields = hwRowToFields(r);

  // 전부 비면 출력 X
  if (!hwFieldsHaveContent(fields)) return '';

  // ✅ 5칸 고정 (빈칸도 자리 유지)
  return `${fields.book} / ${fields.thisHw} / ${fields.pct} / ${fields.comment} / ${fields.nextHw}`;
}

function buildHwBlockFromTable(rows) {
  const lines = (rows || [])
    .map(hwRowToLine)
    .filter(Boolean);

  // ✅ 헤더는 항상 찍고, 내용 없으면 빈칸만
  if (!lines.length) {
    return `숙제 :\n${HW_HEADER_LINE}\n`;
  }
  return `숙제 :\n${HW_HEADER_LINE}\n${lines.join('\n')}`;
}

function buildHwBlockFromLegacyString(str) {
  const s = String(str || '').replace(/\r?\n/g, ' ').trim();

  // ✅ 구형 문자열도 포맷 통일: "이번 숙제" 칸에 넣기
  // (교재 / [구형문자열] / 진행률 / 코멘트 / 다음숙제)
  const line = s ? ` / ${s} /  /  / ` : '';

  if (!line) {
    return `숙제 :\n${HW_HEADER_LINE}\n`;
  }
  return `숙제 :\n${HW_HEADER_LINE}\n${line}`;
}

function homeworkRowsForCsv(entry) {
  if (Array.isArray(entry?.homeworkTable) && entry.homeworkTable.length) {
    return entry.homeworkTable
      .map(hwRowToFields)
      .filter(hwFieldsHaveContent);
  }

  const legacy = String(entry?.homework || '').replace(/\r?\n/g, ' ').trim();
  if (!legacy) return [];

  return [{
    book: '',
    thisHw: legacy,
    pct: '',
    comment: '',
    nextHw: '',
  }];
}

/* ─────────────────────────────────────────────
 * ✅ 특이사항 텍스트 추출 (키 여러 개 대응)
 * ────────────────────────────────────────────*/
function pickSpecialText(entry) {
  if (!entry || typeof entry !== 'object') return '';

  const candidates = [
    entry.notes,
    entry.note,
    entry.memo,
    entry.special,
    entry.specialNote,
    entry.remark,
    entry['특이사항'],
  ];

  for (const v of candidates) {
    if (Array.isArray(v)) {
      const s = v.map(x => String(x ?? '').trim()).filter(Boolean).join(' / ');
      if (s) return s;
    } else if (typeof v === 'string') {
      const s = v.trim();
      if (s) return s;
    } else if (v != null && typeof v === 'number') {
      const s = String(v).trim();
      if (s) return s;
    }
  }
  return '';
}

function schoolForStudent(stu) {
  if (!stu || typeof stu !== 'object') return '';
  return normStr(
    stu.school ?? stu.schoolName ?? stu.highSchool ?? stu.middleSchool ??
    stu.high ?? stu.middle ?? stu.schoolHigh ?? stu.schoolMiddle ?? ''
  );
}

function curriculumForStudent(stu) {
  if (!stu || typeof stu !== 'object') return '';
  return normStr(`${stu.curriculum || ''}${stu.subCurriculum ? ` ${stu.subCurriculum}` : ''}`);
}

/* ─────────────────────────────────────────────
 * ✅ 날짜 상관없이 "done=true && archived!=true" 인 로그들 중
 *    학생별 최신 1건만 수집
 *   반환: [{ sid, date, entry }]
 * ────────────────────────────────────────────*/
function collectUnarchivedDoneLatestPerStudent() {
  const logs = state.logs || {};
  const dates = Object.keys(logs).sort(); // ISO 오름차순

  const latestBySid = new Map(); // sid -> { date, entry }
  for (const date of dates) {
    const dayMap = logs[date] || {};
    for (const sid of Object.keys(dayMap)) {
      const e = dayMap[sid] || {};
      const done = e.done === true || e.done === 'true';
      const archived = e.archived === true || e.archived === 'true';
      if (!done || archived) continue;
      latestBySid.set(String(sid), { date, entry: e });
    }
  }

  const out = [];
  for (const [sid, v] of latestBySid.entries()) out.push({ sid, date: v.date, entry: v.entry });
  return out;
}

/* ─────────────────────────────────────────────
 * 특정 date 이전 누적 진도(prior) 만들기 (sid별)
 * ────────────────────────────────────────────*/
function buildPriorBefore(dateStr, sid) {
  const prior = {};
  Object.keys(state.progress || {})
    .filter(d => d < dateStr)
    .sort()
    .forEach(d => {
      const day = state.progress[d] || {};
      const prog = day?.[sid] || {};
      Object.entries(prog || {}).forEach(([mid, st]) => {
        if (String(mid).startsWith('__') || mid === 'tests') return;
        prior[mid] = st;
      });
    });
  return prior;
}

function allStudentsProgressMids(entry) {
  const raw = entry?.[ALL_STUDENTS_PROGRESS_META];
  if (!raw || typeof raw !== 'object') return new Set();
  return new Set(
    Object.entries(raw)
      .filter(([, on]) => on === true || on === 'true' || on === 1 || on === '1')
      .map(([mid]) => String(mid))
  );
}

function exportDateStamp() {
  return String(getAdminDate() || '').trim() || new Date().toISOString().slice(0, 10);
}

function csvCell(value) {
  const s = String(value ?? '');
  if (/[",\r\n]/.test(s)) return `"${s.replace(/"/g, '""')}"`;
  return s;
}

function recordsToCsv(records) {
  const columns = [
    'date',
    'sid',
    'name',
    'school',
    'curriculum',
    'notes',
    'tests',
    'progress',
    'homework_row',
    'homework_book',
    'homework_current',
    'homework_progress',
    'homework_comment',
    'homework_next',
  ];

  const lines = [columns.map(csvCell).join(',')];

  for (const record of records) {
    const hwRows = record.homeworkRows.length ? record.homeworkRows : [null];
    hwRows.forEach((hw, idx) => {
      lines.push([
        record.date,
        record.sid,
        record.name,
        record.school,
        record.curriculum,
        record.notes,
        record.testLines.join(' / '),
        record.diffs.join(', '),
        hw ? String(idx + 1) : '',
        hw?.book || '',
        hw?.thisHw || '',
        hw?.pct || '',
        hw?.comment || '',
        hw?.nextHw || '',
      ].map(csvCell).join(','));
    });
  }

  return `\uFEFF${lines.join('\r\n')}\r\n`;
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

function rosterToCsv(rows) {
  const columns = ['타임', '대화명', '텍스트'];
  const lines = [columns.map(csvCell).join(',')];

  rows.forEach(row => {
    lines.push([
      row.time || '',
      row.chatName || '',
      row.text || ROSTER_TEXT_DEFAULT,
    ].map(csvCell).join(','));
  });

  return `\uFEFF${lines.join('\r\n')}\r\n`;
}

function schoolForRoster(stu) {
  const raw = normStr(
    stu?.school ?? stu?.schoolName ?? stu?.highSchool ?? stu?.middleSchool ??
    stu?.high ?? stu?.middle ?? stu?.schoolHigh ?? stu?.schoolMiddle ?? ''
  );
  return raw.replace(/고등학교$/u, '').replace(/고$/u, '');
}

function gradeNumberForRoster(stu) {
  const raw = normStr(stu?.grade ?? '');
  const m = raw.match(/\d+/);
  return m ? m[0] : raw;
}

function chatNameForRoster(stu) {
  const school = schoolForRoster(stu);
  const grade = gradeNumberForRoster(stu);
  const name = normStr(stu?.name ?? '');
  return `A ${school}${grade}${school || grade ? ' ' : ''}${name}`.trim();
}

function rosterTimeLabel(dateStr, sid) {
  return normStr(labelFor(dateStr, sid)).replace(/[·]/g, ', ');
}

function rosterSlots(dateStr, sid) {
  const slots = getSlots(dateStr, sid);
  if (slots.length) return slots;

  return (rosterTimeLabel(dateStr, sid).match(/[1-2]/g) || [])
    .map(n => parseInt(n, 10))
    .filter(n => n === 1 || n === 2);
}

function lookupSidEntry(map, sid) {
  if (!map || typeof map !== 'object') return undefined;
  const key = String(sid ?? '').trim();
  if (!key) return undefined;
  if (Object.prototype.hasOwnProperty.call(map, key)) return map[key];
  if (/^\d+$/.test(key)) {
    const alt = String(parseInt(key, 10));
    if (Object.prototype.hasOwnProperty.call(map, alt)) return map[alt];
  }
  return undefined;
}

function mergeRosterDateSidMap(target, source) {
  const out = (target && typeof target === 'object') ? target : {};
  let changed = false;
  Object.entries(source || {}).forEach(([date, day]) => {
    if (!day || typeof day !== 'object') return;
    const nextDay = (out[date] && typeof out[date] === 'object') ? out[date] : {};
    Object.entries(day).forEach(([sid, entry]) => {
      if (!sid || !entry || typeof entry !== 'object') return;
      nextDay[String(sid)] = entry;
      changed = true;
    });
    out[date] = nextDay;
  });
  if (changed) resetRosterHistoryCache();
  return out;
}

function rosterSubjectFor(stu, fallback = '') {
  const raw = normStr(stu?.curriculum ?? stu?.course ?? fallback);
  if (!raw) return '';
  const first = raw.split(/\s+/)[0] || raw;
  return first.split(':')[0].trim() || first;
}

function rosterAssignedVideoMids(dateStr, sid) {
  const day = state.updates?.[dateStr] || {};
  const assignment = lookupSidEntry(day, sid);
  const raw = Array.isArray(assignment) ? assignment : assignment?.videos;
  if (!Array.isArray(raw)) return [];
  return raw.map(mid => String(mid || '').trim()).filter(Boolean);
}

function rosterDateKeysBefore(dateStr, source) {
  return Object.keys(source || {})
    .filter(date => /^\d{4}-\d{2}-\d{2}$/.test(String(date)) && String(date) < String(dateStr))
    .sort()
    .reverse();
}

function rosterHistoryDateKeysBefore(dateStr) {
  const cache = ensureRosterHistoryCache();
  const target = String(dateStr || '');
  if (cache.datesByTarget.has(target)) return cache.datesByTarget.get(target);
  const dates = Array.from(new Set([
    ...rosterDateKeysBefore(target, state.progress),
    ...rosterDateKeysBefore(target, state.logs),
  ])).sort().reverse();
  cache.datesByTarget.set(target, dates);
  return dates;
}

function rosterLogEntryHasTestMetadata(entry) {
  if (!entry || typeof entry !== 'object') return false;
  return (
    (Array.isArray(entry[ROSTER_DAILY_TESTS_KEY]) && entry[ROSTER_DAILY_TESTS_KEY].length > 0) ||
    (Array.isArray(entry.assignedTests) && entry.assignedTests.length > 0)
  );
}

function rosterProgressEntryHasTestMetadata(entry) {
  if (!entry || typeof entry !== 'object') return false;
  const tests = entry.tests;
  return (
    !!entry[ROSTER_TEST_CLEAR_KEY] ||
    (tests && typeof tests === 'object' && Object.keys(tests).length > 0)
  );
}

function addRosterRelevantDate(index, sidRaw, date) {
  const sid = String(sidRaw ?? '').trim();
  if (!sid) return;
  if (!index.has(sid)) index.set(sid, []);
  index.get(sid).push(date);
}

function rosterTestRelevantDateIndexBefore(dateStr) {
  const cache = ensureRosterHistoryCache();
  const target = String(dateStr || '');
  if (cache.testRelevantDatesByTarget.has(target)) return cache.testRelevantDatesByTarget.get(target);

  const index = new Map();
  Object.entries(state.progress || {}).forEach(([date, day]) => {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(String(date)) || String(date) >= target || !day || typeof day !== 'object') {
      return;
    }
    Object.entries(day).forEach(([sid, entry]) => {
      if (rosterProgressEntryHasTestMetadata(entry)) addRosterRelevantDate(index, sid, date);
    });
  });
  Object.entries(state.logs || {}).forEach(([date, day]) => {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(String(date)) || String(date) >= target || !day || typeof day !== 'object') {
      return;
    }
    Object.entries(day).forEach(([sid, entry]) => {
      if (rosterLogEntryHasTestMetadata(entry)) addRosterRelevantDate(index, sid, date);
    });
  });

  index.forEach((dates, sid) => {
    index.set(sid, Array.from(new Set(dates)).sort().reverse());
  });
  cache.testRelevantDatesByTarget.set(target, index);
  return index;
}

function rosterTestRelevantDateKeysBefore(dateStr, sid) {
  const index = rosterTestRelevantDateIndexBefore(dateStr);
  const key = String(sid ?? '').trim();
  const dates = index.get(key) || (/^\d+$/.test(key) ? index.get(String(parseInt(key, 10))) : null) || [];
  return dates;
}

function videoMapForRoster() {
  return new Map((state.videos || [])
    .map(video => [String(video?.mid || '').trim(), video])
    .filter(([mid]) => mid));
}

function rosterVideoText(dateStr, sid, videoMap) {
  const seen = new Set();
  const videos = rosterAssignedVideoMids(dateStr, sid)
    .map(mid => videoMap.get(mid))
    .filter(Boolean)
    .filter(video => {
      const mid = String(video?.mid || '').trim();
      if (!mid || seen.has(mid)) return false;
      seen.add(mid);
      return true;
    })
    .sort((a, b) => {
      const ac = Number(a?.chapter);
      const bc = Number(b?.chapter);
      if (Number.isFinite(ac) && Number.isFinite(bc) && ac !== bc) return ac - bc;
      return normStr(a?.title).localeCompare(normStr(b?.title), 'ko');
    });

  const chapters = videos
    .map(video => Number(video?.chapter))
    .filter(chapter => Number.isFinite(chapter))
    .map(chapter => `${chapter}차시`);
  return Array.from(new Set(chapters)).join(', ');
}

function normalizeRosterTestStatus(status) {
  if (status && typeof status === 'object') status = status.status;
  const s = normStr(status);
  if (!s || s === 'none') return '';
  if (['assigned', 'done', 'interrupted', 'skip'].includes(s)) return s;
  return 'assigned';
}

function rosterCategoryKey(category, label = '') {
  const raw = `${category || ''} ${label || ''}`.toUpperCase();
  const ko = `${category || ''} ${label || ''}`.replace(/\s+/g, '');
  if (raw.includes('REVIEW') || ko.includes('복습')) return 'REVIEW';
  if (raw.includes('UNIT') || ko.includes('단원')) return 'UNIT';
  if (raw.includes('SCHOOL') || ko.includes('학군지')) return 'SCHOOL_PAST';
  if (raw.includes('ILSAN') || ko.includes('일산')) return 'ILSAN_PAST';
  return '';
}

function normalizeRosterDifficulty(categoryKey, difficulty, name = '') {
  const raw = normStr(difficulty);
  const source = `${raw} ${name}`;
  const lv = source.match(/(?:Lv\.?|LV\.?|레벨)\s*\.?\s*([3-6])/);
  if (lv) return `Lv.${lv[1]}`;
  if (categoryKey === 'ILSAN_PAST' && source.includes('그래프')) return '그래프 포함';
  if (categoryKey === 'ILSAN_PAST' && source.includes('중상')) return '중상';
  if (categoryKey === 'ILSAN_PAST' && source.includes('상')) return '중상';
  if (categoryKey === 'ILSAN_PAST' && source.includes('중')) return '중';
  if (source.includes('중상')) return '중상';
  if (source.includes('중')) return '중';
  if (source.includes('상')) return '상';
  return raw;
}

function cleanRosterRound(value) {
  const raw = normStr(value);
  const m = raw.match(/(\d{1,2})/);
  return m ? m[1] : raw.replace(/회차|회/g, '').trim();
}

function roundListText(rounds) {
  const uniq = Array.from(new Set(rounds.map(cleanRosterRound).filter(Boolean)))
    .sort((a, b) => {
      const an = Number(a);
      const bn = Number(b);
      if (Number.isFinite(an) && Number.isFinite(bn) && an !== bn) return an - bn;
      return String(a).localeCompare(String(b), 'ko');
    });
  if (!uniq.length) return '';
  if (uniq.length === 1) return `${uniq[0]}회차`;
  return `${uniq.slice(0, -1).join(', ')}, ${uniq[uniq.length - 1]}회차`;
}

function stripRosterUnitLevel(name, level) {
  let out = normStr(name);
  const lv = normStr(level).replace('.', '\\.');
  if (lv) out = out.replace(new RegExp(`\\s*${lv}\\s*$`, 'i'), '').trim();
  return out;
}

function rosterPastDifficultyLabel(categoryKey, difficulty) {
  if (categoryKey === 'ILSAN_PAST' && difficulty === '그래프 포함') return '그래프부터';
  return difficulty;
}

function rosterPastRowLabel(item) {
  const round = cleanRosterRound(item.round);
  let name = normStr(item.name);
  if (item.categoryKey === 'ILSAN_PAST' && item.difficulty === '그래프 포함') {
    name = name.replace(/^삼각함수\s*그래프\s*포함\s*/u, '').trim();
  }
  if (round) {
    name = name.replace(new RegExp(`^${round}\\s*회차\\s*`, 'u'), '').trim();
  }
  if (!round && !name) return '';
  return `${round ? `${round}회차` : ''}${name ? ` ${name}` : ''}`.trim();
}

function parseRosterTestLabel(label, status = 'assigned', meta = {}) {
  const parts = String(label || '').split('/').map(part => part.trim()).filter(Boolean);
  const categoryLabel = normStr(meta.categoryLabel ?? meta.category ?? parts[0] ?? '');
  const categoryKey = rosterCategoryKey(meta.categoryKey, categoryLabel);
  const isPast = categoryKey === 'SCHOOL_PAST' || categoryKey === 'ILSAN_PAST';
  const difficultyRaw = normStr(meta.difficulty ?? (isPast ? parts[2] : parts[2]) ?? '');
  const nameFromLabel = isPast ? parts.slice(5).join(' / ') : parts.slice(4).join(' / ');
  const name = normStr(meta.name ?? nameFromLabel);
  return {
    categoryKey,
    categoryLabel,
    curriculum: normStr(meta.curriculum ?? parts[1] ?? ''),
    difficulty: normalizeRosterDifficulty(categoryKey, difficultyRaw, name || label),
    term: isPast ? normStr(meta.term ?? meta.examTerm ?? parts[3] ?? '') : '',
    round: cleanRosterRound(meta.round ?? (isPast ? parts[4] : parts[3]) ?? ''),
    name,
    label: normStr(meta.label ?? label),
    status: normalizeRosterTestStatus(status || meta.status || 'assigned'),
  };
}

function parseRosterTestItems(items) {
  if (!Array.isArray(items)) return [];
  return items
    .filter(item => item && typeof item === 'object')
    .map(item => parseRosterTestLabel(item.label || '', item.status || 'assigned', item));
}

function logTestSnapshotForRoster(dateStr, sid) {
  const entry = lookupSidEntry(state.logs?.[dateStr] || {}, sid);
  if (!entry || typeof entry !== 'object') {
    return { hasDaily: false, items: [], dailyLabels: null };
  }

  // progress.tests can intentionally carry unresolved tests from previous days.
  // The roster export is a per-date handout, so prefer the daily assignment slice.
  if (Array.isArray(entry[ROSTER_DAILY_TESTS_KEY])) {
    const dailyItems = parseRosterTestItems(entry[ROSTER_DAILY_TESTS_KEY]);
    return {
      hasDaily: true,
      items: dailyItems,
      dailyLabels: new Set(dailyItems.map(item => item.label).filter(Boolean)),
    };
  }

  return {
    hasDaily: false,
    items: parseRosterTestItems(entry.assignedTests),
    dailyLabels: null,
  };
}

function dedupeRosterTests(items) {
  const byKey = new Map();
  items.forEach(item => {
    if (!item || !item.categoryKey) return;
    const key = item.label || [
      item.categoryKey,
      item.curriculum,
      item.difficulty,
      item.term,
      item.round,
      item.name,
    ].map(normStr).join('\u241f');
    byKey.set(key, { ...(byKey.get(key) || {}), ...item });
  });
  return Array.from(byKey.values());
}

function rosterProgressTestStatuses(dateStr, sid) {
  const progressEntry = lookupSidEntry(state.progress?.[dateStr] || {}, sid);
  const progressTests = progressEntry?.tests;
  return (progressTests && typeof progressTests === 'object') ? progressTests : {};
}

function rosterHasProgressTests(dateStr, sid) {
  return Object.keys(rosterProgressTestStatuses(dateStr, sid)).length > 0;
}

function rosterTestsCleared(dateStr, sid) {
  const progressEntry = lookupSidEntry(state.progress?.[dateStr] || {}, sid);
  return !!(progressEntry && typeof progressEntry === 'object' && progressEntry[ROSTER_TEST_CLEAR_KEY]);
}

function rosterHasStudentDayActivity(dateStr, sid) {
  const progressEntry = lookupSidEntry(state.progress?.[dateStr] || {}, sid);
  if (progressEntry && typeof progressEntry === 'object') {
    const hasProgressContent = Object.keys(progressEntry).some(key =>
      key !== 'tests' && !String(key).startsWith('__')
    );
    if (hasProgressContent || rosterHasProgressTests(dateStr, sid) || rosterTestsCleared(dateStr, sid)) {
      return true;
    }
  }

  const logEntry = lookupSidEntry(state.logs?.[dateStr] || {}, sid);
  return !!(logEntry && typeof logEntry === 'object' && Object.keys(logEntry).length);
}

function rosterActiveTestsForDate(dateStr, sid, statusSet = ROSTER_TEST_STATUS_EXPORT) {
  const { items: logItems } = logTestSnapshotForRoster(dateStr, sid);
  const logByLabel = new Map(logItems.map(item => [item.label, item]));
  const progressTests = rosterProgressTestStatuses(dateStr, sid);
  const hasProgressTests = rosterHasProgressTests(dateStr, sid);
  const items = [];

  Object.entries(progressTests).forEach(([label, status]) => {
    const labelKey = normStr(label);
    const normalized = normalizeRosterTestStatus(status);
    if (!statusSet.has(normalized)) return;
    items.push(parseRosterTestLabel(labelKey, normalized, logByLabel.get(labelKey) || {}));
  });

  if (!items.length && !hasProgressTests) {
    logItems.forEach(item => {
      if (statusSet.has(normalizeRosterTestStatus(item.status))) items.push(item);
    });
  }

  return dedupeRosterTests(items)
    .sort((a, b) =>
      ROSTER_TEST_CATEGORY_ORDER.indexOf(a.categoryKey) - ROSTER_TEST_CATEGORY_ORDER.indexOf(b.categoryKey) ||
      normStr(a.difficulty).localeCompare(normStr(b.difficulty), 'ko') ||
      Number(cleanRosterRound(a.round) || 0) - Number(cleanRosterRound(b.round) || 0) ||
      normStr(a.name).localeCompare(normStr(b.name), 'ko')
    );
}

function previousRosterActiveTests(dateStr, sid) {
  const cache = ensureRosterHistoryCache();
  const cacheKey = `${dateStr}${ROSTER_HISTORY_CACHE_SEP}${sid}`;
  if (cache.previousActiveByKey.has(cacheKey)) {
    return cache.previousActiveByKey.get(cacheKey).slice();
  }

  const dates = rosterHistoryDateKeysBefore(dateStr);
  for (const date of dates) {
    if (rosterTestsCleared(date, sid)) {
      cache.previousActiveByKey.set(cacheKey, []);
      return [];
    }
    const items = rosterActiveTestsForDate(date, sid, ROSTER_TEST_STATUS_ACTIVE);
    if (items.length) {
      cache.previousActiveByKey.set(cacheKey, items);
      return items.slice();
    }
    if (rosterHasStudentDayActivity(date, sid)) {
      cache.previousActiveByKey.set(cacheKey, []);
      return [];
    }
  }
  cache.previousActiveByKey.set(cacheKey, []);
  return [];
}

function previousRosterActiveTestLabels(dateStr, sid) {
  return new Set(previousRosterActiveTests(dateStr, sid).map(item => item.label).filter(Boolean));
}

function rosterAssignmentDeltaForDate(dateStr, sid) {
  const active = rosterActiveTestsForDate(dateStr, sid);
  if (!active.length) return [];
  const previousLabels = previousRosterActiveTestLabels(dateStr, sid);
  if (!previousLabels.size) return active;
  return active.filter(item => item.label && !previousLabels.has(item.label));
}

function rosterNewProgressTestsForDate(dateStr, sid, logByLabel, excludeLabels = new Set()) {
  const progressTests = rosterProgressTestStatuses(dateStr, sid);
  const items = [];

  Object.entries(progressTests).forEach(([label, status]) => {
    const labelKey = normStr(label);
    const normalized = normalizeRosterTestStatus(status);
    if (!labelKey || !ROSTER_TEST_STATUS_EXPORT.has(normalized)) return;
    if (excludeLabels.has(labelKey)) return;
    items.push(parseRosterTestLabel(labelKey, normalized, logByLabel.get(labelKey) || {}));
  });

  return items;
}

function previousRosterAssignedTests(dateStr, sid) {
  const cache = ensureRosterHistoryCache();
  const cacheKey = `${dateStr}${ROSTER_HISTORY_CACHE_SEP}${sid}`;
  if (cache.previousAssignedByKey.has(cacheKey)) {
    return cache.previousAssignedByKey.get(cacheKey).slice();
  }

  const dates = rosterTestRelevantDateKeysBefore(dateStr, sid);
  for (const date of dates) {
    if (rosterTestsCleared(date, sid)) {
      cache.previousAssignedByKey.set(cacheKey, []);
      return [];
    }
    const active = rosterActiveTestsForDate(date, sid);
    if (active.length) {
      cache.previousAssignedByKey.set(cacheKey, active);
      return active.slice();
    }
    if (rosterHasProgressTests(date, sid)) {
      cache.previousAssignedByKey.set(cacheKey, []);
      return [];
    }
  }
  cache.previousAssignedByKey.set(cacheKey, []);
  return [];
}

function rosterAssignedTests(dateStr, sid) {
  const { hasDaily, items: logItems, dailyLabels } = logTestSnapshotForRoster(dateStr, sid);
  const logByLabel = new Map(logItems.map(item => [item.label, item]));
  const progressTests = rosterProgressTestStatuses(dateStr, sid);
  const hasProgressTests = Object.keys(progressTests).length > 0;

  if (hasDaily) {
    const items = [];
    (dailyLabels || new Set()).forEach(label => {
      if (hasProgressTests && !(label in progressTests)) return;
      const normalized = normalizeRosterTestStatus(progressTests[label] || logByLabel.get(label)?.status || 'assigned');
      if (!ROSTER_TEST_STATUS_EXPORT.has(normalized)) return;
      items.push(parseRosterTestLabel(label, normalized, logByLabel.get(label) || {}));
    });
    items.push(...rosterNewProgressTestsForDate(dateStr, sid, logByLabel, dailyLabels || new Set()));
    return rosterSortTests(dedupeRosterTests(items));
  }

  const active = rosterActiveTestsForDate(dateStr, sid);
  if (rosterTestsCleared(dateStr, sid)) return [];
  if (!active.length) {
    if (rosterHasProgressTests(dateStr, sid)) return [];
    return rosterSortTests(previousRosterAssignedTests(dateStr, sid));
  }

  return rosterSortTests(active);
}

function rosterSortTests(items) {
  return (items || []).slice().sort((a, b) =>
    ROSTER_TEST_CATEGORY_ORDER.indexOf(a.categoryKey) - ROSTER_TEST_CATEGORY_ORDER.indexOf(b.categoryKey) ||
    normStr(a.difficulty).localeCompare(normStr(b.difficulty), 'ko') ||
    Number(cleanRosterRound(a.round) || 0) - Number(cleanRosterRound(b.round) || 0) ||
    normStr(a.name).localeCompare(normStr(b.name), 'ko')
  );
}

function appendRosterTestSections(lines, tests) {
  const byCategory = tests.reduce((acc, item) => {
    (acc[item.categoryKey] ||= []).push(item);
    return acc;
  }, {});

  const reviewRounds = (byCategory.REVIEW || []).map(item => item.round);
  if (reviewRounds.length) {
    lines.push('', `복테 : ${roundListText(reviewRounds)}`);
  }

  const appendUnitGroups = () => {
    const groups = new Map();
    (byCategory.UNIT || []).forEach(item => {
      const key = item.difficulty || 'Lv.';
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(stripRosterUnitLevel(item.name, key));
    });
    Array.from(groups.entries())
      .sort(([a], [b]) => a.localeCompare(b, 'ko', { numeric: true }))
      .forEach(([level, names]) => {
        lines.push('', `단원평가(${level})(30분) :`);
        Array.from(new Set(names.filter(Boolean))).forEach(name => lines.push(name));
      });
  };

  const appendPastGroups = (categoryKey, title, difficultyOrder) => {
    const groups = new Map();
    (byCategory[categoryKey] || []).forEach(item => {
      const key = item.difficulty || '';
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(item);
    });
    Array.from(groups.entries())
      .sort(([a], [b]) => {
        const ai = difficultyOrder.indexOf(a);
        const bi = difficultyOrder.indexOf(b);
        return (ai < 0 ? 99 : ai) - (bi < 0 ? 99 : bi) || a.localeCompare(b, 'ko');
      })
      .forEach(([difficulty, items]) => {
        const rows = rosterSortTests(items)
          .map(rosterPastRowLabel)
          .filter(Boolean);
        lines.push('', `${title}(${rosterPastDifficultyLabel(categoryKey, difficulty)})(50분) :`);
        Array.from(new Set(rows)).forEach(row => lines.push(row));
      });
  };

  appendUnitGroups();
  appendPastGroups('SCHOOL_PAST', '학군지기출', ['상', '중상', '중']);
  appendPastGroups('ILSAN_PAST', '일산기출', ['중', '중상', '그래프 포함']);
}

function rosterTaskText(dateStr, stu, videoMap) {
  const sid = String(stu?.id ?? '');
  const subject = rosterSubjectFor(stu);
  const lines = [ROSTER_TEXT_DEFAULT, '', `오늘 할 일${subject ? ` (${subject})` : ''}`];
  const videos = rosterVideoText(dateStr, sid, videoMap);
  if (videos) lines.push('', `영상 : ${videos}`);
  appendRosterTestSections(lines, rosterAssignedTests(dateStr, sid));
  return lines.join('\n');
}

async function loadExtraAttendMap() {
  try {
    const extra = await fetch('/api/extra-attend', { cache: 'no-store' }).then(r => r.json());
    return (extra && typeof extra === 'object') ? extra : {};
  } catch {
    return {};
  }
}

async function ensureLogsForRosterDate(dateStr) {
  if (state.logs?.[dateStr]) return;
  try {
    const data = await fetch(`/api/logs?date=${encodeURIComponent(dateStr)}`, { cache: 'no-store' })
      .then(r => r.ok ? r.json() : Promise.reject(r.status));
    if (data && typeof data === 'object') {
      state.logs = state.logs || {};
      state.logs[dateStr] = (data[dateStr] && typeof data[dateStr] === 'object') ? data[dateStr] : {};
      window.logs = state.logs;
      resetRosterHistoryCache();
    }
  } catch { /* keep current state.logs */ }
}

async function ensureAbsentForRosterDate() {
  try {
    const data = await fetch('/api/absent', { cache: 'no-store' }).then(r => r.json());
    if (data && typeof data === 'object') {
      state.absentByDate = (data.by_date && typeof data.by_date === 'object') ? data.by_date : (state.absentByDate || {});
      state.absences = (data.by_student && typeof data.by_student === 'object') ? data.by_student : (state.absences || {});
      window.absentByDate = state.absentByDate;
      if (window.state) {
        window.state.absentByDate = state.absentByDate;
        window.state.absences = state.absences;
      }
    }
  } catch { /* keep current absence state */ }
}

async function loadRosterStudents(dateStr) {
  const students = Array.isArray(state.students) ? state.students : [];
  const extraMap = await loadExtraAttendMap();
  const wchr = yoilOf(dateStr);

  const regular = students.filter(stu => hasWeekday(stu, wchr));
  const extraIds = (extraMap[dateStr] || []).map(x => String(x).trim()).filter(Boolean);
  const extraStudents = extraIds
    .map(id => students.find(stu => String(stu?.id) === id))
    .filter(Boolean);

  const seen = new Set();
  let list = [...regular, ...extraStudents].filter(stu => {
    const sid = String(stu?.id ?? '');
    if (!sid || seen.has(sid)) return false;
    seen.add(sid);
    return true;
  });

  const absentSet = new Set((state.absentByDate?.[dateStr] || []).map(String));
  list = list.filter(stu => !absentSet.has(String(stu?.id)));

  await ensureLogsForRosterDate(dateStr);
  const logsDay = state.logs?.[dateStr] || {};
  list = list.filter(stu => !truthy((logsDay[String(stu?.id)] || {}).done));

  return list.sort((a, b) => {
    const aSlots = rosterSlots(dateStr, a.id);
    const bSlots = rosterSlots(dateStr, b.id);
    const aRank = aSlots.includes(1) ? 1 : aSlots.includes(2) ? 2 : 9;
    const bRank = bSlots.includes(1) ? 1 : bSlots.includes(2) ? 2 : 9;
    if (aRank !== bRank) return aRank - bRank;
    return normStr(a?.name).localeCompare(normStr(b?.name), 'ko');
  });
}

function buildRosterRows(dateStr, students) {
  const videos = videoMapForRoster();
  return students.map(stu => ({
    time: rosterTimeLabel(dateStr, stu.id),
    chatName: chatNameForRoster(stu),
    text: rosterTaskText(dateStr, stu, videos),
    slots: rosterSlots(dateStr, stu.id),
  }));
}

function rosterRowSlotNumbers(row) {
  const fromSlots = Array.isArray(row?.slots) ? row.slots : [];
  const fromLabel = String(row?.time || '').match(/[1-2]/g) || [];
  return Array.from(new Set([...fromSlots, ...fromLabel]
    .map(n => parseInt(n, 10))
    .filter(n => n === 1 || n === 2)))
    .sort((a, b) => a - b);
}

async function ensureRosterProgressHistory(students) {
  const ids = Array.from(new Set((students || [])
    .map(stu => String(stu?.id ?? '').trim())
    .filter(Boolean)));
  if (!ids.length) return;

  const chunkSize = 60;
  state.progress = state.progress || {};

  for (let i = 0; i < ids.length; i += chunkSize) {
    const chunk = ids.slice(i, i + chunkSize);
    try {
      const q = new URLSearchParams({ sids: chunk.join(',') }).toString();
      const data = await fetch(`/api/progress?${q}`, { cache: 'no-store' })
        .then(r => r.ok ? r.json() : Promise.reject(r.status));
      if (data && typeof data === 'object') {
        state.progress = mergeRosterDateSidMap(state.progress, data);
        continue;
      }
    } catch (err) {
      console.warn('[exportRoster] batch progress history load failed:', err);
    }

    const results = await Promise.all(chunk.map(async sid => {
      try {
        const res = await fetch(`/api/progress?sid=${encodeURIComponent(sid)}`, { cache: 'no-store' });
        if (!res.ok) throw new Error(String(res.status));
        return await res.json();
      } catch (err) {
        console.warn('[exportRoster] progress history load failed:', sid, err);
        return null;
      }
    }));

    results.forEach(data => {
      if (data && typeof data === 'object') {
        state.progress = mergeRosterDateSidMap(state.progress, data);
      }
    });
  }

  window.progressData = state.progress;
}

async function exportRosterCsv() {
  const dateStr = exportDateStamp();
  try {
    const [students, videos, updates, progress] = await Promise.all([
      fetch('/api/students', { cache: 'no-store' }).then(r => r.ok ? r.json() : Promise.reject(r.status)),
      fetch('/api/videos', { cache: 'no-store' }).then(r => r.ok ? r.json() : Promise.reject(r.status)).catch(() => null),
      fetch('/api/updates', { cache: 'no-store' }).then(r => r.ok ? r.json() : Promise.reject(r.status)).catch(() => null),
      fetch(`/api/progress?date=${encodeURIComponent(dateStr)}`, { cache: 'no-store' })
        .then(r => r.ok ? r.json() : Promise.reject(r.status))
        .catch(() => null),
    ]);
    if (Array.isArray(students)) {
      state.students = students;
      window.students = students;
    }
    if (Array.isArray(videos)) {
      state.videos = videos;
      window.videos = videos;
    }
    if (updates && typeof updates === 'object') {
      state.updates = updates;
      window.updates = updates;
    }
    if (progress && typeof progress === 'object') {
      state.progress = mergeRosterDateSidMap(state.progress || {}, progress);
      window.progressData = state.progress;
    }
  } catch (err) {
    console.warn('[exportRoster] roster task data load failed:', err);
  }

  await loadWeekendSlots();
  await ensureAbsentForRosterDate();

  const students = await loadRosterStudents(dateStr);
  if (!students.length) {
    toast('내보낼 명단이 없습니다.');
    return;
  }

  await ensureRosterProgressHistory(students);
  resetRosterHistoryCache();

  const rows = buildRosterRows(dateStr, students);
  const wchr = yoilOf(dateStr);
  const firstRows = rows.filter(row => {
    const slots = rosterRowSlotNumbers(row);
    return slots.includes(1) || !slots.length;
  });
  const secondRows = rows.filter(row => {
    const slots = rosterRowSlotNumbers(row);
    return slots.includes(2) && !slots.includes(1);
  });

  downloadTextFile(`학생명단_${dateStr}_${wchr}1.csv`, rosterToCsv(firstRows), 'text/csv;charset=utf-8');
  downloadTextFile(`학생명단_${dateStr}_${wchr}2.csv`, rosterToCsv(secondRows), 'text/csv;charset=utf-8');
  toast('명단 CSV 2개 내보내기 완료');
}

export function initExport() {
  const btn = $('exportLogs');
  const rosterButtons = [
    $('exportRoster'),
    $('exportRosterRail'),
    $('exportTodayCsv'),
  ].filter(Boolean);

  rosterButtons.forEach(button => {
    button.addEventListener('click', exportRosterCsv);
  });

  if (!btn) return;

  btn.addEventListener('click', async () => {
    try {
      const [logs, progress] = await Promise.all([
        fetch('/api/logs', { cache: 'no-store' }).then(r => r.ok ? r.json() : Promise.reject(r.status)),
        fetch('/api/progress', { cache: 'no-store' }).then(r => r.ok ? r.json() : Promise.reject(r.status)),
      ]);
      if (logs && typeof logs === 'object') {
        state.logs = logs;
        window.logs = state.logs;
        resetRosterHistoryCache();
      }
      if (progress && typeof progress === 'object') {
        state.progress = progress;
        window.progressData = state.progress;
        resetRosterHistoryCache();
      }
    } catch (err) {
      console.warn('[exportLogs] full history load failed:', err);
      toast('내보내기 데이터 로드 실패');
      return;
    }

    // 비디오 인덱스 (mid -> video)
    const videoMap = new Map((state.videos || []).map(v => [String(v.mid), v || {}]));
    const chapterNum = (v) => {
      const c = v?.chapter ?? 0;
      const n = Number(c);
      if (!Number.isNaN(n)) return n;
      const parsed = parseFloat(String(c).replace(/[^0-9.]/g, ''));
      return Number.isNaN(parsed) ? 0 : parsed;
    };

    // 라벨러
    const labelFor = (mid, st) => {
      const v = videoMap.get(String(mid));
      if (!v) return null;
      const base = `${v.chapter}차시`;
      if (st === 'done') return base;
      if (st === 'interrupted') return `${base}(중단)`;
      return null;
    };

    // ✅ 대상: 자유의 몸(done=true && archived!=true) 학생들(학생별 최신 1건)
    const targets = collectUnarchivedDoneLatestPerStudent();

    if (!targets.length) {
      toast('내보낼 (완료 & 미정리) 기록이 없습니다.');
      return;
    }

    // 이름순 정렬 (동일하면 날짜)
    targets.sort((a, b) => {
      const sa = (state.students || []).find(s => String(s.id) === String(a.sid));
      const sb = (state.students || []).find(s => String(s.id) === String(b.sid));
      const na = String(sa?.name || '');
      const nb = String(sb?.name || '');
      const cmp = na.localeCompare(nb, 'ko');
      if (cmp !== 0) return cmp;
      return String(a.date).localeCompare(String(b.date));
    });

    const records = [];

    targets.forEach(({ sid, date, entry: logEntry }) => {
      const stu = (state.students || []).find(s => String(s.id) === String(sid));
      if (!stu) return;

      // 해당 날짜의 진도/이전 누적
      const progThatDay = state.progress?.[date]?.[sid] || {};
      const before = buildPriorBefore(date, String(sid));
      const exportSkipMids = allStudentsProgressMids(progThatDay);

      // 변화만 + skip 제외 + 챕터순
      const diffObjs = Object.entries(progThatDay)
        .filter(([mid, st]) =>
          !String(mid).startsWith('__') &&
          mid !== 'tests' &&
          !exportSkipMids.has(String(mid)) &&
          before[mid] !== st &&
          st !== 'none' &&
          st !== 'skip'
        )
        .map(([mid, st]) => {
          const v = videoMap.get(String(mid)) || {};
          return { mid, st, chap: chapterNum(v) };
        })
        .sort((a, b) => a.chap - b.chap);

      const diffs = diffObjs
        .map(o => labelFor(o.mid, o.st))
        .filter(Boolean);

      // ✅ 숙제 블록 만들기(헤더 포함)
      let hwBlock = '';
      if (Array.isArray(logEntry.homeworkTable) && logEntry.homeworkTable.length) {
        hwBlock = buildHwBlockFromTable(logEntry.homeworkTable);
      } else {
        hwBlock = buildHwBlockFromLegacyString(logEntry.homework || '');
      }

      // 테스트
      const tests = Array.isArray(logEntry.tests) ? logEntry.tests : [];
      const testLines = tests.map(t => {
        const nm = t.name || '';
        const sc = t.score || '';
        const wrong = Array.isArray(t.wrong) ? t.wrong.join(', ') : '';
        const memo = (t.memo || '').trim();
        const wrongPart = wrong ? ` (오답: ${wrong})` : '';
        const memoPart = memo ? ` – ${memo}` : '';
        return `${nm} ${sc}${wrongPart}${memoPart}`.trim();
      }).filter(Boolean);

      const hasTests = testLines.length > 0;
      const homeworkRows = homeworkRowsForCsv(logEntry);

      // 숙제 실제 내용 여부(헤더 제외)
      const hwHasContent = (() => {
        const lines = String(hwBlock || '').split('\n').map(s => s.trim());
        return lines.length >= 3 && !!lines.slice(2).join('').trim();
      })();

      // ✅ 특이사항
      const special = pickSpecialText(logEntry);
      const hasSpecial = !!special;

      // 정책: 진도/숙제내용/테스트/특이사항 다 비면 출력 제외
      if (diffs.length === 0 && !hwHasContent && !hasTests && !hasSpecial) return;

      const curLabel = curriculumForStudent(stu);

      // 헤더 날짜는 "그 기록 날짜" 기준
      const d = new Date(date);
      const headerDate = `${d.getMonth() + 1}/${d.getDate()}`;

      records.push({
        date,
        sid: String(sid),
        name: normStr(stu.name),
        school: schoolForStudent(stu),
        curriculum: curLabel,
        notes: special,
        testLines,
        diffs,
        homeworkRows,
        hwBlock,
        hwHasContent,
        hasSpecial,
        hasTests,
        headerDate,
      });
    });

    let out = '';
    records.forEach((record) => {
      out += `(${record.headerDate}) ${record.name}\n`;

      if (record.hasSpecial) out += `특이사항 : ${record.notes}\n\n`;
      if (record.hasTests) out += `테스트 : ${record.testLines.join(' / ')}\n\n`;

      out += `진도 (${record.curriculum}) : ${record.diffs.join(', ')}\n\n`;

      // ✅ 숙제 출력
      if (record.hwHasContent) {
        out += `${record.hwBlock}\n\n\n`;
      } else {
        out += `숙제 :\n${HW_HEADER_LINE}\n\n\n`;
      }
    });

    if (!out.trim()) {
      toast('내보낼 내용이 없습니다.');
      return;
    }

    // ✅ 파일명 날짜 포함
    const stamp = exportDateStamp();
    downloadTextFile(`수업기록_완료미정리_${stamp}.txt`, out, 'text/plain;charset=utf-8');
    downloadTextFile(`수업기록_완료미정리_${stamp}.csv`, recordsToCsv(records), 'text/csv;charset=utf-8');

    toast('수업 기록 TXT/CSV 내보내기 완료');
  });
}
