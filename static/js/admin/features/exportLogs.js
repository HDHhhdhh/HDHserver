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
// ✅ (추가) 다운로드 파일명에 오늘 날짜(YYYY-MM-DD) 포함
// ✅ (추가) 특이사항(notes/memo/special 등) 내용 있으면 출력

import { $, toast } from '../core/utils.js';
import { state } from '../core/state.js';

/* ─────────────────────────────────────────────
 * ✅ 숙제 출력(헤더 포함, 괄호 제거 버전)
 *  - 5칸: 교재 / 이번숙제 / 진행률 / 코멘트 / 다음숙제
 *  - 빈칸은 ''로 두되, 구분자는 항상 유지(형태 고정)
 * ────────────────────────────────────────────*/
const HW_HEADER_LINE = '교재 / 이번 숙제 / 진행률 / 코멘트 / 다음숙제';

function normStr(v) { return String(v ?? '').trim(); }

function hwRowToLine(r) {
  const book = normStr(r?.book ?? r?.textbook ?? r?.name ?? r?.교재 ?? '');

  const thisHw = normStr(
    r?.thisHw ?? r?.this ?? r?.current ?? r?.unit ?? r?.이번숙제 ?? r?.이번 ?? r?.숙제 ?? ''
  );

  let pct = (r?.pct ?? r?.progress ?? r?.percent ?? r?.진행률 ?? '');
  pct = (pct === '' || pct == null) ? '' : String(pct).trim();
  if (pct && !pct.includes('%')) pct = `${pct}%`;

  const comment = normStr(r?.comment ?? r?.memo ?? r?.note ?? r?.코멘트 ?? r?.비고 ?? '');
  const nextHw  = normStr(r?.nextHw ?? r?.next ?? r?.nextHomework ?? r?.다음숙제 ?? r?.다음 ?? '');

  // 전부 비면 출력 X
  if (!book && !thisHw && !pct && !comment && !nextHw) return '';

  // ✅ 5칸 고정 (빈칸도 자리 유지)
  return `${book} / ${thisHw} / ${pct} / ${comment} / ${nextHw}`;
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
      Object.entries(prog || {}).forEach(([mid, st]) => { prior[mid] = st; });
    });
  return prior;
}

/* 오늘 날짜 YYYY-MM-DD (로컬) */
function todayYYYYMMDD() {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

export function initExport() {
  const btn = $('exportLogs');
  if (!btn) return;

  btn.addEventListener('click', () => {
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

    let out = '';

    targets.forEach(({ sid, date, entry: logEntry }) => {
      const stu = (state.students || []).find(s => String(s.id) === String(sid));
      if (!stu) return;

      // 해당 날짜의 진도/이전 누적
      const progThatDay = state.progress?.[date]?.[sid] || {};
      const before = buildPriorBefore(date, String(sid));

      // 변화만 + skip 제외 + 챕터순
      const diffObjs = Object.entries(progThatDay)
        .filter(([mid, st]) => before[mid] !== st && st !== 'none' && st !== 'skip')
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

      const curLabel = stu.curriculum + (stu.subCurriculum ? ` ${stu.subCurriculum}` : '');

      // 헤더 날짜는 "그 기록 날짜" 기준
      const d = new Date(date);
      const headerDate = `${d.getMonth() + 1}/${d.getDate()}`;

      out += `(${headerDate}) ${stu.name}\n`;

      if (hasSpecial) out += `특이사항 : ${special}\n\n`;
      if (hasTests) out += `테스트 : ${testLines.join(' / ')}\n\n`;

      out += `진도 (${curLabel}) : ${diffs.join(', ')}\n\n`;

      // ✅ 숙제 출력
      if (hwHasContent) {
        out += `${hwBlock}\n\n\n`;
      } else {
        out += `숙제 :\n${HW_HEADER_LINE}\n\n\n`;
      }
    });

    if (!out.trim()) {
      toast('내보낼 내용이 없습니다.');
      return;
    }

    // 다운로드
    const blob = new Blob([out], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;

    // ✅ 파일명 날짜 포함
    const stamp = todayYYYYMMDD();
    a.download = `수업기록_완료미정리_${stamp}.txt`;

    a.click();
    URL.revokeObjectURL(url);

    toast('수업 기록 내보내기 완료');
  });
}
