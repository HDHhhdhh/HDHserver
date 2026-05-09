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

const ALL_STUDENTS_PROGRESS_META = '__allStudentsProgressMids';

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

export function initExport() {
  const btn = $('exportLogs');
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
      }
      if (progress && typeof progress === 'object') {
        state.progress = progress;
        window.progressData = state.progress;
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
