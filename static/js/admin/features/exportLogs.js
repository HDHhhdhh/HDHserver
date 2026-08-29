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
import { fetchJsonChecked } from '../../shared/api.js';
import { downloadTextFile } from '../../shared/download.js?v=20260828-1';
import { getAdminDate } from '../core/adminDate.js';
import {
  HW_HEADER_LINE,
  csvCell,
  defaultExportLogOptions,
  normalizeExportLogOptions,
  recordsToCsv,
  renderClassLogText,
  validateExportLogOptions,
} from './exportLogFormat.js?v=20260823-no-done-exports1';
import {
  loadWeekendSlots,
  hasWeekday,
  yoilOf,
  truthy,
  labelFor,
  getSlots,
} from './today.state.js';
import {
  collectUnarchivedDoneLatestPerStudent,
  collectUnarchivedLogsForDate,
} from './exportLogTargets.js?v=20260823-export-perf1';

const EXPORT_TARGET_DONE = 'done';
const EXPORT_TARGET_DATE = 'date';

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
    videoStatusesByTargetSid: new Map(),
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

function canonicalSid(value) {
  const sid = String(value ?? '').trim();
  return /^\d+$/.test(sid) ? sid.replace(/^0+(?=\d)/, '') : sid;
}

function replaceSidHistories(current, incoming, sids) {
  const wanted = new Set((sids || []).flatMap(sid => {
    const raw = String(sid ?? '').trim();
    return raw ? [raw, canonicalSid(raw)] : [];
  }));
  const out = {};

  Object.entries(current || {}).forEach(([date, bySid]) => {
    if (!bySid || typeof bySid !== 'object' || Array.isArray(bySid)) return;
    const kept = {};
    Object.entries(bySid).forEach(([sid, entry]) => {
      if (wanted.has(String(sid)) || wanted.has(canonicalSid(sid))) return;
      kept[sid] = entry;
    });
    if (Object.keys(kept).length) out[date] = kept;
  });

  Object.entries(incoming || {}).forEach(([date, bySid]) => {
    if (!bySid || typeof bySid !== 'object' || Array.isArray(bySid)) return;
    out[date] = { ...(out[date] || {}), ...bySid };
  });
  return out;
}

function summaryTargetRefs(summary) {
  if (summary?.rowsAvailable !== true || !Array.isArray(summary?.rows)) return null;
  return summary.rows
    .map(row => ({
      sid: String(row?.sid ?? '').trim(),
      date: String(row?.date ?? '').trim(),
    }))
    .filter(row => row.sid && /^\d{4}-\d{2}-\d{2}$/.test(row.date));
}

function historyUrl(path, sids, targetRefs = null) {
  const params = new URLSearchParams({ sids: sids.join(',') });
  if (Array.isArray(targetRefs)) {
    params.set('exportTargets', JSON.stringify(
      targetRefs.map(row => [String(row.sid), String(row.date)]),
    ));
  }
  return `${path}?${params.toString()}`;
}

async function loadClassLogExportData({ selectedDateMode, selectedDate, signal }) {
  let seedLogs = {};
  let targetRefs = [];

  if (selectedDateMode) {
    seedLogs = await fetchJsonChecked(
      `/api/logs?date=${encodeURIComponent(selectedDate)}`,
      'selected-date export logs',
      { cache: 'no-store', signal },
    );
    targetRefs = collectUnarchivedLogsForDate(seedLogs, selectedDate);
  } else {
    const summary = await fetchJsonChecked(
      '/api/logs/unarchived-summary',
      'unarchived export summary',
      { cache: 'no-store', signal },
    );
    const refs = summaryTargetRefs(summary);
    if (refs === null) {
      const [logs, progress] = await Promise.all([
        fetchJsonChecked('/api/logs', 'export logs fallback', { cache: 'no-store', signal }),
        fetchJsonChecked('/api/progress', 'export progress fallback', { cache: 'no-store', signal }),
      ]);
      const targets = collectUnarchivedDoneLatestPerStudent(logs);
      return {
        logs,
        progress,
        targets,
        sids: Array.from(new Set(targets.map(row => String(row.sid)))),
      };
    }
    targetRefs = refs;
  }

  const sids = Array.from(new Set(targetRefs.map(row => String(row.sid)).filter(Boolean)));
  if (!sids.length) return { logs: seedLogs, progress: {}, targets: [], sids: [] };

  const [logs, progress] = await Promise.all([
    fetchJsonChecked(historyUrl('/api/logs', sids, targetRefs), 'export log history', { cache: 'no-store', signal }),
    fetchJsonChecked(historyUrl('/api/progress', sids), 'export progress history', { cache: 'no-store', signal }),
  ]);
  const historyLogs = { ...logs };
  Object.entries(seedLogs || {}).forEach(([date, bySid]) => {
    historyLogs[date] = { ...(historyLogs[date] || {}), ...(bySid || {}) };
  });
  const targets = selectedDateMode
    ? collectUnarchivedLogsForDate(historyLogs, selectedDate)
    : collectUnarchivedDoneLatestPerStudent(historyLogs);
  return { logs: historyLogs, progress, targets, sids };
}

/* ─────────────────────────────────────────────
 * ✅ 숙제 출력(헤더 포함, 괄호 제거 버전)
 *  - 5칸: 교재 / 이번숙제 / 진행률 / 코멘트 / 다음숙제
 *  - 빈칸은 ''로 두되, 구분자는 항상 유지(형태 고정)
 * ────────────────────────────────────────────*/
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

function normalizeRosterCurriculum(value) {
  const compact = normStr(value).replace(/\s+/g, '');
  const aliases = {
    '공통수학1': '공수1',
    '공통수학2': '공수2',
    '미적1': '미적분1',
    '미적분Ⅰ': '미적분1',
    '미적분I': '미적분1',
    '미적2': '미적분2',
    '미적분Ⅱ': '미적분2',
    '미적분II': '미적분2',
    '확률과통계': '확통',
  };
  return aliases[compact] || (compact === '미적분' ? '미적분1' : compact);
}

function rosterTestMatchesCurrentCurriculum(item, student) {
  const current = normalizeRosterCurriculum(student?.curriculum ?? student?.subject);
  if (!current) return true;
  const assigned = normalizeRosterCurriculum(item?.curriculum);
  return assigned === current;
}

function rosterAssignedVideoMids(dateStr, sid) {
  const day = state.updates?.[dateStr] || {};
  const assignment = lookupSidEntry(day, sid);
  const raw = Array.isArray(assignment) ? assignment : assignment?.videos;
  if (!Array.isArray(raw)) return [];
  return raw.map(mid => String(mid || '').trim()).filter(Boolean);
}

function normalizeRosterVideoStatus(status) {
  if (status && typeof status === 'object') status = status.status;
  return normStr(status);
}

function rosterVideoStatusesBeforeDate(dateStr, sid) {
  const cache = ensureRosterHistoryCache();
  const target = String(dateStr || '');
  const studentId = String(sid ?? '').trim();
  const cacheKey = `${target}${ROSTER_HISTORY_CACHE_SEP}${studentId}`;
  if (cache.videoStatusesByTargetSid.has(cacheKey)) {
    return cache.videoStatusesByTargetSid.get(cacheKey);
  }

  const statuses = {};
  Object.keys(state.progress || {})
    .filter(date => /^\d{4}-\d{2}-\d{2}$/.test(String(date)) && String(date) < target)
    .sort()
    .forEach(date => {
      const entry = lookupSidEntry(state.progress?.[date], studentId);
      if (!entry || typeof entry !== 'object') return;
      Object.entries(entry).forEach(([mid, status]) => {
        if (String(mid).startsWith('__') || mid === 'tests') return;
        statuses[String(mid)] = normalizeRosterVideoStatus(status);
      });
    });

  cache.videoStatusesByTargetSid.set(cacheKey, statuses);
  return statuses;
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
  const statuses = rosterVideoStatusesBeforeDate(dateStr, sid);
  const targetEntry = lookupSidEntry(state.progress?.[dateStr], sid);
  const videos = rosterAssignedVideoMids(dateStr, sid)
    .filter(mid => {
      if (statuses[mid] !== 'done') return true;
      if (!targetEntry || !Object.prototype.hasOwnProperty.call(targetEntry, mid)) return false;
      return normalizeRosterVideoStatus(targetEntry[mid]) !== 'done';
    })
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

function rosterAssignedTests(dateStr, sid, student = null) {
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
    return rosterSortTests(dedupeRosterTests(items)).filter(item => rosterTestMatchesCurrentCurriculum(item, student));
  }

  const active = rosterActiveTestsForDate(dateStr, sid);
  if (rosterTestsCleared(dateStr, sid)) return [];
  if (!active.length) {
    if (rosterHasProgressTests(dateStr, sid)) return [];
    return rosterSortTests(previousRosterAssignedTests(dateStr, sid))
      .filter(item => rosterTestMatchesCurrentCurriculum(item, student));
  }

  return rosterSortTests(active).filter(item => rosterTestMatchesCurrentCurriculum(item, student));
}

function rosterSortTests(items) {
  return (items || []).slice().sort((a, b) =>
    ROSTER_TEST_CATEGORY_ORDER.indexOf(a.categoryKey) - ROSTER_TEST_CATEGORY_ORDER.indexOf(b.categoryKey) ||
    normStr(a.difficulty).localeCompare(normStr(b.difficulty), 'ko') ||
    Number(cleanRosterRound(a.round) || 0) - Number(cleanRosterRound(b.round) || 0) ||
    normStr(a.name).localeCompare(normStr(b.name), 'ko')
  );
}

function rosterTestName(item) {
  const label = normStr(item?.label);
  let name = normStr(item?.name);
  if (!name && label) {
    name = label.split('/').map(part => part.trim()).filter(Boolean).pop() || label;
  }
  if (!name) return '';

  const source = item?.categoryKey === 'SCHOOL_PAST'
    ? '학군지'
    : item?.categoryKey === 'ILSAN_PAST'
      ? '일산'
      : '';
  if (!source) return name;

  const difficulty = normStr(item?.difficulty);
  const round = cleanRosterRound(item?.round);
  if (item?.categoryKey === 'ILSAN_PAST' && difficulty === '그래프 포함') {
    name = name.replace(/^삼각함수\s*그래프\s*포함\s*/u, '').trim();
  }
  const nameRound = name.match(/(\d{1,2})\s*회차/u)?.[1] || '';
  const hasRound = round && nameRound === round;
  if (round && !hasRound) name = `${round}회차 ${name}`;
  return `${source}${difficulty ? `(${difficulty})` : ''} ${name}`.trim();
}

function rosterAssignedTestNames(dateStr, sid, student = null) {
  return Array.from(new Set(
    rosterAssignedTests(dateStr, sid, student).map(rosterTestName).filter(Boolean)
  ));
}

function rosterTaskText(dateStr, stu, videoMap) {
  const sid = String(stu?.id ?? '');
  const subject = rosterSubjectFor(stu);
  const lines = [ROSTER_TEXT_DEFAULT, '', `오늘 할 일${subject ? ` (${subject})` : ''}`];
  const videos = rosterVideoText(dateStr, sid, videoMap);
  if (videos) lines.push('', `영상 : ${videos}`);
  const testNames = rosterAssignedTestNames(dateStr, sid, stu);
  if (testNames.length) lines.push('', '테스트 :', ...testNames);
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
  list = list.filter(stu => !truthy((logsDay[String(stu?.id)] || {}).selfStudy));

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
      fetch('/api/updates?readOnly=1', { cache: 'no-store' }).then(r => r.ok ? r.json() : Promise.reject(r.status)).catch(() => null),
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
  const modal = $('exportLogsModal');
  const form = $('exportLogsForm');
  const closeButton = $('exportLogsClose');
  const cancelButton = $('exportLogsCancel');
  const resetButton = $('exportLogsReset');
  const submitButton = $('exportLogsSubmit');
  const status = $('exportLogsStatus');
  const formatTxt = $('exportLogsFormatTxt');
  const formatCsv = $('exportLogsFormatCsv');
  const txtSections = $('exportLogsTxtSections');
  const sectionNotes = $('exportLogsSectionNotes');
  const sectionTests = $('exportLogsSectionTests');
  const sectionProgress = $('exportLogsSectionProgress');
  const sectionHomework = $('exportLogsSectionHomework');
  const targetDone = $('exportLogsTargetDone');
  const targetDate = $('exportLogsTargetDate');
  const targetDateLabel = $('exportLogsTargetDateLabel');
  const rosterButtons = [
    $('exportRoster'),
    $('exportRosterRail'),
    $('exportTodayCsv'),
  ].filter(Boolean);

  rosterButtons.forEach(button => {
    button.addEventListener('click', exportRosterCsv);
  });

  if (!btn) return;

  async function exportClassLogs(rawOptions, { signal, targetMode = EXPORT_TARGET_DONE, targetDate = '' } = {}) {
    const options = normalizeExportLogOptions(rawOptions);
    const selectedDateMode = targetMode === EXPORT_TARGET_DATE;
    const selectedDate = String(targetDate || getAdminDate() || '').trim();
    let exportData;
    try {
      exportData = await loadClassLogExportData({ selectedDateMode, selectedDate, signal });
      if (exportData.sids.length) {
        state.logs = replaceSidHistories(state.logs, exportData.logs, exportData.sids);
        state.progress = replaceSidHistories(state.progress, exportData.progress, exportData.sids);
        window.logs = state.logs;
        window.progressData = state.progress;
        resetRosterHistoryCache();
      }
    } catch (err) {
      if (err?.name === 'AbortError') throw err;
      console.warn('[exportLogs] scoped history load failed:', err);
      toast('내보내기 데이터 로드 실패');
      throw new Error('내보내기 데이터를 불러오지 못했습니다. 잠시 후 다시 시도하세요.');
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

    const targets = exportData.targets;

    if (!targets.length) {
      const message = selectedDateMode
        ? `${selectedDate}에 내보낼 저장 로그가 없습니다.`
        : '내보낼 완료·미정리 기록이 없습니다.';
      toast(message);
      return { downloaded: [], message };
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

      // 내보내기 공통 당일 변화 목록: done/skip/none 제외 + 챕터순
      const diffObjs = Object.entries(progThatDay)
        .map(([mid, status]) => ({ mid, st: normalizeRosterVideoStatus(status) }))
        .filter(({ mid, st }) =>
          !String(mid).startsWith('__') &&
          mid !== 'tests' &&
          !exportSkipMids.has(String(mid)) &&
          normalizeRosterVideoStatus(before[mid]) !== st &&
          st !== 'none' &&
          st !== 'skip'
        )
        .map(({ mid, st }) => {
          const v = videoMap.get(String(mid)) || {};
          return { mid, st, chap: chapterNum(v) };
        })
        .sort((a, b) => a.chap - b.chap);

      const diffs = diffObjs
        .filter(item => item.st !== 'done')
        .map(item => labelFor(item.mid, item.st))
        .filter(Boolean);

      // ✅ 숙제 블록 만들기(헤더 포함)
      let hwBlock = '';
      if (Array.isArray(logEntry.homeworkTable) && logEntry.homeworkTable.length) {
        hwBlock = buildHwBlockFromTable(logEntry.homeworkTable);
      } else {
        hwBlock = buildHwBlockFromLegacyString(logEntry.homework || '');
      }

      // 테스트: 진도 상태가 초록색(assigned)인 배정 이름만 내보낸다.
      const testLines = rosterAssignedTestNames(date, String(sid), stu);
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

    if (!records.length) {
      toast('내보낼 내용이 없습니다.');
      return { downloaded: [], message: '내보낼 내용이 없습니다.' };
    }

    const stamp = exportDateStamp();
    const fileStem = selectedDateMode
      ? `수업기록_선택일_${selectedDate}` : `수업기록_완료미정리_${stamp}`;
    const downloaded = [];
    let txtSkipped = false;

    if (options.formats.txt) {
      const out = renderClassLogText(records, options);
      if (out.trim()) {
        downloadTextFile(`${fileStem}.txt`, out, 'text/plain;charset=utf-8');
        downloaded.push('TXT');
      } else {
        txtSkipped = true;
      }
    }
    if (options.formats.csv) {
      downloadTextFile(`${fileStem}.csv`, recordsToCsv(records), 'text/csv;charset=utf-8');
      downloaded.push('CSV');
    }

    if (!downloaded.length) {
      toast('선택한 TXT 항목에 내보낼 내용이 없습니다.');
      return { downloaded, message: '선택한 TXT 항목에 내보낼 내용이 없습니다.' };
    }

    const suffix = txtSkipped ? ' · 선택한 TXT 항목은 내용 없음' : '';
    toast(`수업 기록 ${downloaded.join('/')} 내보내기 완료${suffix}`);
    return { downloaded, message: `${downloaded.join('/')} 파일을 내려받았습니다.${suffix}` };
  }

  let currentOptions = defaultExportLogOptions();
  let currentTargetMode = EXPORT_TARGET_DONE;
  let exportTargetDate = '';
  let exportInFlight = false;
  let activeExportController = null;
  let restoreFocus = null;

  const dialogReady = !!(
    modal && form && closeButton && cancelButton && resetButton && submitButton && status &&
    targetDone && targetDate && targetDateLabel && formatTxt && formatCsv &&
    txtSections && sectionNotes && sectionTests && sectionProgress && sectionHomework
  );

  if (!dialogReady) {
    btn.addEventListener('click', async () => {
      if (exportInFlight) return;
      exportInFlight = true;
      btn.disabled = true;
      try { await exportClassLogs(currentOptions); }
      catch { /* toast is emitted by exportClassLogs */ }
      finally {
        exportInFlight = false;
        btn.disabled = false;
      }
    });
    return;
  }

  const optionControls = [
    formatTxt,
    targetDone,
    targetDate,
    formatCsv,
    sectionNotes,
    sectionTests,
    sectionProgress,
    sectionHomework,
  ];

  function setStatus(message = '', kind = '') {
    status.textContent = message;
    status.classList.toggle('is-error', kind === 'error');
    status.classList.toggle('is-success', kind === 'success');
  }

  function syncTxtSectionState() {
    txtSections.disabled = !formatTxt.checked || exportInFlight;
    txtSections.classList.toggle('is-disabled', !formatTxt.checked);
  }

  function writeOptionsToForm(value) {
    const options = normalizeExportLogOptions(value);
    formatTxt.checked = options.formats.txt;
    formatCsv.checked = options.formats.csv;
    sectionNotes.checked = options.sections.notes;
    sectionTests.checked = options.sections.tests;
    sectionProgress.checked = options.sections.progress;
    sectionHomework.checked = options.sections.homework;
    syncTxtSectionState();
  }

  function writeTargetModeToForm(value) {
    const mode = value === EXPORT_TARGET_DATE ? EXPORT_TARGET_DATE : EXPORT_TARGET_DONE;
    targetDone.checked = mode === EXPORT_TARGET_DONE;
    targetDate.checked = mode === EXPORT_TARGET_DATE;
  }

  function readTargetModeFromForm() {
    return targetDate.checked ? EXPORT_TARGET_DATE : EXPORT_TARGET_DONE;
  }

  function readOptionsFromForm() {
    return normalizeExportLogOptions({
      formats: { txt: formatTxt.checked, csv: formatCsv.checked },
      sections: {
        notes: sectionNotes.checked,
        tests: sectionTests.checked,
        progress: sectionProgress.checked,
        homework: sectionHomework.checked,
      },
    });
  }

  function setBusy(busy) {
    if (
      busy &&
      modal.contains(document.activeElement) &&
      ![closeButton, cancelButton, submitButton].includes(document.activeElement)
    ) {
      submitButton.focus();
    }
    exportInFlight = busy;
    modal.setAttribute('aria-busy', busy ? 'true' : 'false');
    optionControls.forEach(control => { control.disabled = busy; });
    resetButton.disabled = busy;
    submitButton.setAttribute('aria-disabled', busy ? 'true' : 'false');
    submitButton.textContent = busy ? '준비 중…' : '선택 형식으로 내보내기';
    if (!busy) syncTxtSectionState();
  }

  function closeDialog() {
    if (exportInFlight) activeExportController?.abort();
    modal.style.display = 'none';
    modal.hidden = true;
    document.body.classList.remove('export-logs-open');
    setStatus();
    const target = restoreFocus;
    restoreFocus = null;
    if (target?.focus) requestAnimationFrame(() => target.focus());
  }

  function openDialog() {
    if (exportInFlight) return;
    restoreFocus = document.activeElement;
    exportTargetDate = String(getAdminDate() || '').trim();
    targetDateLabel.textContent = exportTargetDate;
    writeTargetModeToForm(currentTargetMode);
    writeOptionsToForm(currentOptions);
    setStatus('설정을 확인한 뒤 내보내기를 실행하세요.');
    modal.hidden = false;
    modal.style.display = 'flex';
    document.body.classList.add('export-logs-open');
    requestAnimationFrame(() => (targetDate.checked ? targetDate : targetDone).focus());
  }

  btn.addEventListener('click', openDialog);
  closeButton.addEventListener('click', closeDialog);
  cancelButton.addEventListener('click', closeDialog);
  resetButton.addEventListener('click', () => {
    writeOptionsToForm(defaultExportLogOptions());
    currentTargetMode = EXPORT_TARGET_DONE;
    writeTargetModeToForm(currentTargetMode);
    setStatus('기본 설정으로 되돌렸습니다. 내보내기를 실행하면 현재 페이지에 적용됩니다.', 'success');
  });
  formatTxt.addEventListener('change', syncTxtSectionState);
  modal.addEventListener('click', (event) => {
    if (event.target === modal) closeDialog();
  });
  modal.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
      event.preventDefault();
      event.stopPropagation();
      closeDialog();
      return;
    }
    if (event.key !== 'Tab') return;
    const focusable = Array.from(modal.querySelectorAll('button:not([disabled]), input:not([disabled])'))
      .filter(element => !element.hidden && element.offsetParent !== null);
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  });
  document.addEventListener('focusin', (event) => {
    if (modal.hidden || modal.contains(event.target)) return;
    submitButton.focus();
  });

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (exportInFlight) return;

    const validation = validateExportLogOptions(readOptionsFromForm());
    if (!validation.ok) {
      setStatus(validation.message, 'error');
      if (validation.code === 'format_required') formatTxt.focus();
      else sectionNotes.focus();
      return;
    }

    currentOptions = validation.options;
    const controller = new AbortController();
    currentTargetMode = readTargetModeFromForm();
    const targetDateForExport = exportTargetDate;
    activeExportController = controller;
    setBusy(true);
    setStatus('수업 기록을 안전하게 준비하고 있습니다.');
    let closeAfterExport = false;
    try {
      const result = await exportClassLogs(currentOptions, {
        signal: controller.signal,
        targetMode: currentTargetMode,
        targetDate: targetDateForExport,
      });
      if (result.downloaded.length) {
        setStatus(result.message, 'success');
        closeAfterExport = true;
      } else {
        setStatus(result.message, 'error');
      }
    } catch (err) {
      if (err?.name !== 'AbortError') {
        setStatus(err?.message || '내보내기에 실패했습니다.', 'error');
      }
    } finally {
      if (activeExportController === controller) activeExportController = null;
      setBusy(false);
      if (closeAfterExport && !modal.hidden) closeDialog();
    }
  });
}
