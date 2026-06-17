// table.js — 전체 학생 테이블 렌더
// - "학교" 인라인 편집(자동 저장, 빈칸에서도 추가 가능)
// - "학년" 인라인 편집(자동 저장)
// - "커리큘럼/세부커리큘럼" 수정 가능 (고정 옵션 셀렉트)
// - "요일" 밑 "등원시간" 행 추가 (월1~일1=13:00 / 월2~일2=18:00 기본, 수정 가능)
// - "독스(docUrl)" 인라인 입력/저장 + 새 탭 열기 버튼
// - 테이블에서 "영상 진도 보기/수정" 팝업
// - 커리별 학생 수(이름+학교 기준으로 중복 제거)

import { $, toast } from '../core/utils.js';
import { patchField } from '../core/api.js';
import { ensureProgressForSid, state } from '../core/state.js';
import { applySearchPlaceholder, matchesSearchKey, searchKeyForText } from '../../shared/search.js';
import { SELF_STUDY_DAYS_FIELD, isSelfStudyDayField, nextSelfStudyDays } from '../../shared/selfStudy.js';

const subCurrOptions = ['A:Ble', 'APEX'];
const CURRICULUM_OPTIONS = ['공수1', '공수2', '대수', '미적분1', '미적분2', '기하', '확통'];

// 다양한 응답 형태를 '성공'으로 인정
const ok = (r) =>
  r == null ||                                                // ✅ 204/빈 응답(undef/null)도 성공으로 취급
  r?.ok === true ||                                           // fetch Response 2xx
  (typeof r?.status === 'number' && r.status >= 200 && r.status < 400) || // 3xx 포함
  r?.redirected === true ||                                   // 리다이렉트 추종
  r?.type === 'opaqueredirect' ||                             // CORS 리다이렉트
  r === true || r === 'ok' || r?.success === true ||          // 커스텀 성공 패턴
  r?.status === 'ok' || r?.status === 'success' ||            // ✅ {status:"ok"} 류
  r?.result === 'ok' || r?.result === 'success' ||            // ✅ {result:"ok"} 류
  r?.message === 'ok' || r?.message === 'success';            // ✅ {message:"ok"} 류

function escapeHtml(s = '') {
  return String(s)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

// 이름+학교로 중복 학생 묶기용 키
function dedupKeyForStudent(s) {
  const name = (s.name || '').trim();
  const high = s.highSchool || s.schoolHigh || s.high || s.highschool || s.high_school || s.고등학교 || '';
  const middle = s.middleSchool || s.schoolMiddle || s.middle || s.middleschool || s.middle_school || s.중학교 || s.school || '';
  const school = s.school || high || middle || '';
  return `${name}::${school}`;
}

/** 요일 문자열 -> 기본 등원시간
 *  - (신규 규칙) 월1~일1 → 13:00, 월2~일2 → 18:00
 *  - 숫자 없으면(구형 데이터) 기존처럼 18:00
 */
function baseTimeForDayValue(v) {
  if (!v) return '';
  const txt = String(v).trim();
  if (!txt) return '';

  // ✅ 월1~일1 / 월2~일2 우선 적용
  const m = txt.match(/[1-3]/);
  const slot = m ? parseInt(m[0], 10) : null;
  if (slot === 1) return '13:00';
  if (slot === 2) return '18:00';
  if (slot === 3) return '18:00'; // 3이 오면 일단 18:00(필요하면 바꿔줘)

  // 구형(숫자 없이 '월'만 등) 데이터는 18:00
  const ch = txt[0];
  if ('일월화수목금토'.includes(ch)) return '18:00';

  return '';
}

/** 시간 입력 정규화
 *  - "" => ""
 *  - "6" / "18" => "06:00" / "18:00"
 *  - "6:3" / "6:30" => "06:03" / "06:30"
 *  - 그 외는 그대로(양 끝 공백 제거만)
 */
function normalizeTimeInput(v) {
  const t = (v || '').trim();
  if (!t) return '';

  // hh 또는 hh:mm 또는 hhmm 형식 대충 허용
  const m = t.match(/^(\d{1,2})(?::?(\d{1,2}))?$/);
  if (!m) return t; // 이상한 형식은 사용자가 넣은대로 저장

  let hh = parseInt(m[1], 10);
  let mm = m[2] != null ? parseInt(m[2], 10) : 0;
  if (!Number.isFinite(hh)) hh = 0;
  if (!Number.isFinite(mm)) mm = 0;
  if (hh < 0) hh = 0;
  if (hh > 23) hh = hh % 24;
  if (mm < 0) mm = 0;
  if (mm > 59) mm = 0;

  const pad = (n) => (n < 10 ? '0' + n : '' + n);
  return `${pad(hh)}:${pad(mm)}`;
}

/* ─────────────────────────────────────────
   커리별 학생 수 렌더 (이름+학교 기준 dedup)
────────────────────────────────────────── */
function renderCurStats() {
  const box = document.getElementById('curStatsBox');
  if (!box) return;

  const curMap = new Map();    // cur -> Set<dedupKey>
  const globalSet = new Set(); // 전체 고유 학생 세기용

  for (const s of state.students) {
    const cur = (s.curriculum || '').trim();
    const key = dedupKeyForStudent(s);
    if (!key.trim()) continue; // 이름/학교 다 비어 있으면 스킵

    globalSet.add(key);

    if (!cur) continue;
    if (!curMap.has(cur)) curMap.set(cur, new Set());
    curMap.get(cur).add(key);
  }

  const totalUnique = globalSet.size;

  box.innerHTML = `
    <div class="curStats-title">
      커리별 학생 수 · 전체 ${totalUnique}명
    </div>
    <div class="curStats-items">
      ${CURRICULUM_OPTIONS.map(cur => {
        const set = curMap.get(cur);
        const cnt = set ? set.size : 0;
        return `<span class="curStats-item">${escapeHtml(cur)}: <strong>${cnt}</strong></span>`;
      }).join('')}
    </div>`;
}

export function renderTable() {
  const host = $('allWrap'); if (!host) return;

  state.students.sort((a, b) => a.name.localeCompare(b.name, 'ko'));

  const bookSet = new Set([
    ...state.students.flatMap(s => [s.subBook1, s.subBook2]).filter(Boolean),
    '바이블', '라이트쎈', '고쟁이', '유형반복R',
    '올림포스', '올림포스 고난도', '1등급의 자격',
    '마플시너지', '마플교과서', '올포유', '올포고', '올림포스 유형', '라인트쎈'
  ]);

  const datalist = `
    <datalist id="bookList">
      ${[...bookSet].map(v => `<option value="${escapeHtml(v)}"></option>`).join('')}
    </datalist>`;

  const rows = state.students.map(s => {
    const sub = s.subCurriculum || '';
    const level = s.level || '';
    const grade = s.grade ?? s.gradeLevel ?? s.studentGrade ?? s.학년 ?? '';
    const high = s.highSchool || s.schoolHigh || s.high || s.highschool || s.high_school || s.고등학교 || '';
    const middle = s.middleSchool || s.schoolMiddle || s.middle || s.middleschool || s.middle_school || s.중학교 || s.school || '';
    const schoolText = s.school || high || middle || '';
    const doc = s.docUrl || '';
    const cur = s.curriculum || '';

    // 요일/등원시간 렌더용
    const dayInputsHtml = [1, 2, 3, 4, 5].map(n => {
      const val = s[`day${n}`] || '';
      const dayField = `day${n}`;
      const selfStudy = isSelfStudyDayField(s, dayField);
      return `<input class="dayInput" data-id="${s.id}" data-day="${dayField}" data-self-study="${selfStudy ? '1' : '0'}" title="${selfStudy ? '자습' : ''}" value="${escapeHtml(val)}">`;
    }).join('');

    const timeInputsHtml = [1, 2, 3, 4, 5].map(n => {
      const dayVal = s[`day${n}`] || '';
      const field = `visitTime${n}`;
      const stored = s[field] || '';
      const base = baseTimeForDayValue(dayVal);
      const timeVal = stored || base || '';
      return `<input class="timeInput" data-id="${s.id}" data-field="${field}" placeholder="HH:MM" value="${escapeHtml(timeVal)}">`;
    }).join('');

    return `
    <tr data-id="${s.id}" data-curriculum="${escapeHtml(cur)}" data-subcurriculum="${escapeHtml(sub)}" data-search-key="${escapeHtml(tableSearchKeyForStudent(s))}">
      <td class="cell-name">
        <a href="/student/${s.id}" target="_blank" class="stuName"
           data-id="${s.id}" data-grade="${escapeHtml(grade)}"
           data-high="${escapeHtml(high)}" data-middle="${escapeHtml(middle)}">
          ${escapeHtml(s.name)}
        </a>
      </td>

      <!-- 학교: 인라인 편집 전용(더블클릭) -->
      <td>
        <span class="cell-school"
              data-id="${s.id}"
              contenteditable="false"
              title="더블클릭하여 학교를 편집하세요">
          ${schoolText ? escapeHtml(schoolText) : '&nbsp;'}
        </span>
      </td>

      <!-- 학년: 인라인 편집(더블클릭) -->
      <td>
        <span class="cell-grade"
              data-id="${s.id}"
              contenteditable="false"
              title="더블클릭하여 학년을 편집하세요 (예: 중3, 고2, N수 등)">
          ${grade ? escapeHtml(grade) : '&nbsp;'}
        </span>
      </td>

      <!-- 레벨 -->
      <td>
        <select class="levelSelect" data-id="${s.id}">
          <option value="상"${level === '상' ? ' selected' : ''}>상</option>
          <option value="중상"${level === '중상' ? ' selected' : ''}>중상</option>
          <option value="중"${level === '중' ? ' selected' : ''}>중</option>
          <option value="하"${level === '하' ? ' selected' : ''}>하</option>
        </select>
      </td>

      <!-- 커리큘럼 / 세부커리큘럼 -->
      <td>
        <div class="curCell">
          <select class="curSelect" data-id="${s.id}">
            <option value=""${cur === '' ? ' selected' : ''}></option>
            ${CURRICULUM_OPTIONS.map(opt =>
              `<option value="${escapeHtml(opt)}"${opt === cur ? ' selected' : ''}>${escapeHtml(opt)}</option>`
            ).join('')}
          </select>
          <select class="subCurrSelect" data-id="${s.id}">
            <option value=""${sub === '' ? ' selected' : ''}></option>
            ${subCurrOptions.map(opt =>
              `<option value="${opt}"${opt === sub ? ' selected' : ''}>${escapeHtml(opt)}</option>`
            ).join('')}
          </select>
        </div>
      </td>

      <!-- 요일 + 등원시간 -->
      <td>
        <div class="dayInputRow">
          ${dayInputsHtml}
        </div>
        <div class="timeInputRow">
          ${timeInputsHtml}
        </div>
      </td>

      <!-- 부교재 -->
      <td>
        <div class="sbBox">
          <input type="text" class="subBookInput" list="bookList" data-id="${s.id}" data-field="subBook1" placeholder="부1" value="${escapeHtml(s.subBook1 || '')}">
          <input type="text" class="subBookInput" list="bookList" data-id="${s.id}" data-field="subBook2" placeholder="부2" value="${escapeHtml(s.subBook2 || '')}">
        </div>
      </td>

      <!-- 독스 URL: 인라인 편집 + 열기 + 영상진도(보기/수정) -->
      <td>
        <div class="docBox">
          <input type="url" class="docUrlInput" data-id="${s.id}"
                 placeholder="https://docs.google.com/..."
                 value="${escapeHtml(doc)}">
          <button type="button" class="docOpen" title="새 탭에서 열기" data-id="${s.id}">🔗</button>
          <button type="button" class="miniProgBtn" title="영상 진도 보기/수정" data-id="${s.id}">🎬</button>
        </div>
      </td>
    </tr>`;
  }).join('');

  host.innerHTML = `${datalist}
    <style>
      /* 표 스타일 범위 한정 */
      body.all-page #allWrap {
        overflow-x:hidden !important;
      }
      body.all-page #allWrap .studentsTable,
      #allWrap .studentsTable {
        width:100% !important;
        min-width:0 !important;
        max-width:100% !important;
        table-layout:fixed !important;
        border-collapse:separate;
        border-spacing:0;
      }
      #allWrap .studentsTable th,
      #allWrap .studentsTable td {
        padding:7px 6px;
        vertical-align:middle;
        box-sizing:border-box;
      }

      #allWrap .studentsTable :where(input, select, button) {
        max-width:100%;
        box-sizing:border-box;
      }

      #allWrap .studentsTable th {
        white-space:nowrap;
        font-size:12px;
      }

      /* 한 화면에 모든 컬럼이 들어오도록 주요 컬럼 폭 고정 */
      #allWrap .studentsTable col.col-name       { width:6%; }
      #allWrap .studentsTable col.col-school     { width:7%; }
      #allWrap .studentsTable col.col-grade      { width:5%; }
      #allWrap .studentsTable col.col-level      { width:6%; }
      #allWrap .studentsTable col.col-curriculum { width:14%; }
      #allWrap .studentsTable col.col-schedule   { width:20%; }
      #allWrap .studentsTable col.col-books      { width:16%; }
      #allWrap .studentsTable col.col-docs       { width:16%; }
      #allWrap .studentsTable col.col-del        { width:4%; }
      #allWrap .studentsTable col.col-clone      { width:6%; }

      /* 내용 길이 대응 */
      #allWrap .studentsTable .cell-name a {
        display:inline-block;
        max-width:100%;
        overflow:hidden;
        text-overflow:ellipsis;
        white-space:nowrap;
      }

      /* 학교/학년 셀은 빈칸이어도 클릭 영역 확보 */
      #allWrap .studentsTable .cell-school,
      #allWrap .studentsTable .cell-grade {
        display:inline-block;
        min-width:0;
        max-width:100%;
        overflow-wrap:anywhere;
        word-break:keep-all;
      }

      /* 커리/세부커리 정렬 */
      #allWrap .studentsTable .curCell{
        display:grid;
        grid-template-columns:minmax(0, 1.05fr) minmax(0, .95fr);
        gap:6px;
        align-items:center;
      }
      #allWrap .studentsTable .levelSelect,
      #allWrap .studentsTable .curCell .curSelect,
      #allWrap .studentsTable .curCell .subCurrSelect{
        width:100%;
        min-width:0;
        padding-left:8px;
        padding-right:22px;
      }

      /* 요일 / 등원시간 행 스타일 */
      body.all-page #allWrap .studentsTable .dayInputRow,
      body.all-page #allWrap .studentsTable .timeInputRow,
      #allWrap .studentsTable .dayInputRow,
      #allWrap .studentsTable .timeInputRow{
        display:grid !important;
        grid-template-columns:repeat(5, minmax(0, 1fr)) !important;
        gap:4px;
        margin-bottom:3px;
      }
      body.all-page #allWrap .studentsTable .dayInputRow input.dayInput,
      #allWrap .studentsTable .dayInputRow input.dayInput{
        width:100% !important;
        min-width:0 !important;
      }
      body.all-page #allWrap .studentsTable .dayInputRow input.dayInput[data-self-study="1"],
      #allWrap .studentsTable .dayInputRow input.dayInput[data-self-study="1"]{
        background:#e5e7eb !important;
        border-color:#9ca3af !important;
        color:#374151 !important;
      }
      body.dark #allWrap .studentsTable .dayInputRow input.dayInput[data-self-study="1"]{
        background:#374151 !important;
        border-color:#64748b !important;
        color:#e5e7eb !important;
      }
      body.all-page #allWrap .studentsTable .timeInputRow input.timeInput,
      #allWrap .studentsTable .timeInputRow input.timeInput{
        width:100% !important;
        min-width:0 !important;
        font-size:10px !important;
        padding:0 2px !important;
      }

      /* 입력/버튼 정렬 */
      #allWrap .studentsTable .sbBox,
      #allWrap .studentsTable .docBox {
        display:grid;
        align-items:center;
        gap:6px;
      }
      #allWrap .studentsTable .sbBox {
        grid-template-columns:minmax(0, 1fr) minmax(0, 1fr);
      }
      #allWrap .studentsTable .subBookInput {
        width:100% !important;
        min-width:0 !important;
        padding-left:8px;
        padding-right:8px;
      }
      #allWrap .studentsTable .docBox {
        grid-template-columns:minmax(0, 1fr) 36px 36px;
      }
      /* ✅ 독스 칸 줄이기 */
      #allWrap .studentsTable .docUrlInput {
        width:100% !important;
        min-width:0 !important;
        max-width:none !important;
        padding-left:8px;
        padding-right:8px;
      }
      body.all-page #allWrap .studentsTable :where(th:nth-child(8), td:nth-child(8)) {
        width:auto !important;
        min-width:0 !important;
        max-width:none !important;
      }

      body.all-page #allWrap .studentsTable :where(th.col-del, td:has(.btn-del-stu)) {
        width:42px !important;
        min-width:42px !important;
        max-width:42px !important;
        padding-left:4px !important;
        padding-right:4px !important;
      }

      body.all-page #allWrap .studentsTable :where(th.col-clone, td.col-clone-cell) {
        width:54px !important;
        min-width:54px !important;
        max-width:54px !important;
        padding-left:4px !important;
        padding-right:4px !important;
      }

      body.all-page #allWrap .studentsTable .btn-clone-stu {
        width:100% !important;
        min-width:0 !important;
        padding:0 6px !important;
      }

      #allWrap .studentsTable .miniProgBtn{
        height:32px; width:36px;
        border-radius:10px;
        border:1px solid #e5e7eb;
        background:#fff;
        cursor:pointer;
      }
      body.dark #allWrap .studentsTable .miniProgBtn{
        border-color:#334155;
        background:#0b1220;
        color:#e5e7eb;
      }

      /* 커리별 집계 박스 */
      #allWrap .curStats{
        margin-bottom:10px;
        font-size:13px;
        line-height:1.5;
      }
      #allWrap .curStats-title{
        margin-bottom:4px;
        opacity:0.8;
      }
      #allWrap .curStats-items{
        display:flex;
        flex-wrap:wrap;
        gap:8px 16px;
      }
      #allWrap .curStats-item strong{
        font-weight:600;
      }
      #allWrap .allStudentSearch{
        display:flex;
        align-items:center;
        gap:10px;
        margin:0 0 12px;
      }
      #allWrap .allStudentSearch input{
        width:min(420px, 100%);
        height:38px;
        border:1px solid #cbd5e1;
        border-radius:9px;
        padding:0 12px;
        box-sizing:border-box;
      }
      #allWrap .allStudentSearch .allStudentSearchHint{
        min-width:78px;
        color:#64748b;
        font-size:13px;
        font-weight:700;
      }
      body.dark #allWrap .allStudentSearch input{
        border-color:#334155;
        background:#0b1220;
        color:#e5e7eb;
      }
    </style>

    <div class="allStudentSearch">
      <input id="allStudentSearchInput" type="search" autocomplete="off" placeholder="학생 검색">
      <span id="allStudentSearchHint" class="allStudentSearchHint" aria-live="polite"></span>
    </div>

    <div class="curStats" id="curStatsBox"></div>

    <table class="studentsTable">
      <colgroup>
        <col class="col-name" />
        <col class="col-school" />
        <col class="col-grade" />
        <col class="col-level" />
        <col class="col-curriculum" />
        <col class="col-schedule" />
        <col class="col-books" />
        <col class="col-docs" />
        <col class="col-del" />
        <col class="col-clone" />
      </colgroup>
      <thead>
        <tr>
          <th>이름</th>
          <th>학교</th>
          <th>학년</th>
          <th>레벨</th>
          <th>커리큘럼</th>
          <th>요일 / 등원시간</th>
          <th>부교재</th>
          <th>독스</th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>`;

  initSchoolInlineEdit(); // 학교 인라인 편집 활성화
  initGradeInlineEdit();  // 학년 인라인 편집 활성화

  // 커리 통계 최초 렌더
  renderCurStats();
  bindAllStudentSearch();
  applyAllStudentSearch();

  // ✅ 테이블 렌더 시점에 미니 진도 모달 준비(1회)
  ensureMiniProgModal();
}

function bindAllStudentSearch() {
  const input = document.getElementById('allStudentSearchInput');
  if (!input || input.dataset.bound === '1') return;
  input.dataset.bound = '1';
  applySearchPlaceholder(input, '학생 검색');
  input.addEventListener('input', applyAllStudentSearch);
  input.addEventListener('search', applyAllStudentSearch);
  input.addEventListener('compositionend', applyAllStudentSearch);
  input.addEventListener('keydown', (ev) => {
    if (ev.key !== 'Escape') return;
    input.value = '';
    applyAllStudentSearch();
  });
}

function applyAllStudentSearch() {
  const input = document.getElementById('allStudentSearchInput');
  const hint = document.getElementById('allStudentSearchHint');
  const rows = Array.from(document.querySelectorAll('#allWrap .studentsTable tbody tr[data-id]'));
  if (!input || !rows.length) {
    if (hint) hint.textContent = '';
    return;
  }

  const queryText = input.value || '';
  let visible = 0;
  rows.forEach(row => {
    const key = row.dataset.searchKey || searchKeyForText(row.textContent || '');
    const show = matchesSearchKey(key, queryText);
    row.hidden = !show;
    row.style.display = show ? '' : 'none';
    if (show) visible += 1;
  });
  if (hint) hint.textContent = queryText.trim() ? `${visible}/${rows.length}명` : '';
}

/* ─────────────────────────────────────────
   이벤트(요일/커리/세부/레벨/부교재/독스/등원시간)
────────────────────────────────────────── */
document.addEventListener('change', (e) => {
  // 요일
  if (e.target.classList.contains('dayInput')) {
    saveDayInput(e.target);
    return;
  }

  // 등원시간 (visitTime1~5)
  if (e.target.classList.contains('timeInput')) {
    saveTimeInput(e.target);
    return;
  }

  // 커리큘럼
  if (e.target.classList.contains('curSelect')) {
    const sid = e.target.dataset.id;
    const value = (e.target.value || '').trim();
    const stu = state.students.find(s => String(s.id) === String(sid));
    if (stu) stu.curriculum = value;
    patchField(sid, 'curriculum', value)
      .then(r => ok(r) ? toast('커리큘럼 저장됨') : Promise.reject(r))
      .then(() => { renderCurStats(); })
      .catch(() => alert('커리큘럼 저장 실패'));
    return;
  }

  // 세부과정
  if (e.target.classList.contains('subCurrSelect')) {
    const sid = e.target.dataset.id;
    const value = e.target.value;
    const stu = state.students.find(s => String(s.id) === String(sid));
    if (stu) stu.subCurriculum = value;
    patchField(sid, 'subCurriculum', value)
      .then(r => ok(r) ? toast('저장됨') : Promise.reject(r))
      .catch(() => alert('저장 실패'));
    return;
  }

  // 레벨
  if (e.target.classList.contains('levelSelect')) {
    const sid = e.target.dataset.id;
    const value = e.target.value;
    const stu = state.students.find(s => String(s.id) === String(sid));
    if (stu) stu.level = value;
    patchField(sid, 'level', value)
      .then(r => ok(r) ? toast('레벨 저장됨') : Promise.reject(r))
      .catch(() => alert('레벨 저장 실패'));
    return;
  }

  // 부교재
  if (e.target.classList.contains('subBookInput')) { saveSubBook(e.target); return; }

  // 독스 URL (change에서도 저장)
  if (e.target.classList.contains('docUrlInput')) { saveDocUrl(e.target); return; }
});

document.addEventListener('blur', (e) => {
  if (e.target.classList.contains('subBookInput')) saveSubBook(e.target);
  if (e.target.classList.contains('docUrlInput')) saveDocUrl(e.target);
  if (e.target.classList.contains('timeInput')) saveTimeInput(e.target);
}, true);

document.addEventListener('keydown', (e) => {
  const t = e.target;
  if (t.classList.contains('subBookInput') && e.key === 'Enter') {
    e.preventDefault(); saveSubBook(t); t.blur();
  }
  if (t.classList.contains('docUrlInput') && e.key === 'Enter') {
    e.preventDefault(); saveDocUrl(t); t.blur();
  }
  if (t.classList.contains('timeInput') && e.key === 'Enter') {
    e.preventDefault(); saveTimeInput(t); t.blur();
  }
});

document.addEventListener('contextmenu', (e) => {
  const input = e.target.closest?.('.dayInput');
  if (!input) return;
  e.preventDefault();
  toggleSelfStudyDay(input);
});

// 독스 열기 버튼: 같은 행의 input 값을 사용
document.addEventListener('click', (e) => {
  const btn = e.target.closest('.docOpen'); if (!btn) return;
  const wrap = btn.closest('.docBox');
  const input = wrap?.querySelector('.docUrlInput');
  const url = (input?.value || '').trim();
  if (!url) { alert('URL을 입력하세요.'); return; }
  const href = /^(https?:)?\/\//i.test(url) ? url : ('https://' + url);
  window.open(href, '_blank', 'noopener');
});

/* ─────────────────────────────────────────
   ✅ 부교재 저장: 중복/동시 저장 방지(큐잉)
   - change + blur + Enter로 saveSubBook가 여러 번 불려도
     "최종 값 1번"만 서버에 저장되게 만든다.
────────────────────────────────────────── */
const _subBookSaveState = new Map(); // key -> { inflight:boolean, lastSent:string, pending:string|null, timer:number|null }

function _subBookKey(sid, field) {
  return `${String(sid)}:${String(field)}`;
}

function saveSubBook(el) {
  const sid = el.dataset.id;
  const field = el.dataset.field;   // subBook1|subBook2
  if (!sid || !field) return;

  const value = (el.value || '').trim();
  const key = _subBookKey(sid, field);

  // 로컬 상태는 일단 반영
  const stu = state.students.find(s => String(s.id) === String(sid));
  if (stu) stu[field] = value;

  let st = _subBookSaveState.get(key);
  if (!st) {
    st = { inflight: false, lastSent: undefined, pending: null, timer: null };
    _subBookSaveState.set(key, st);
  }

  // 같은 값이면(이미 보냈거나, 보내려는 값이 동일) 아무것도 안 함
  if (st.pending === value) return;
  if (st.lastSent === value && !st.inflight) return;

  // 디바운스: 같은 틱에 change+blur 연달아 와도 1번만 실행
  if (st.timer) clearTimeout(st.timer);
  st.pending = value;
  st.timer = setTimeout(() => flushSubBookSave(sid, field), 0);
}

async function flushSubBookSave(sid, field) {
  const key = _subBookKey(sid, field);
  const st = _subBookSaveState.get(key);
  if (!st) return;

  if (st.inflight) return; // 이미 저장 중이면 끝난 뒤 pending으로 다시 실행될 것
  const value = st.pending;
  if (value == null) return;

  // pending을 비우고, 지금 값을 보낸다
  st.pending = null;
  st.inflight = true;

  try {
    const r = await patchField(sid, field, value);
    if (!ok(r)) throw r;
    st.lastSent = value;
    toast('부교재 저장됨');
  } catch (e) {
    // 실패했으면 pending에 다시 넣어서 "다음 트리거" 때 재시도 가능하게 둔다
    st.pending = value;
    alert('부교재 저장 실패');
  } finally {
    st.inflight = false;

    // 저장 중에 다른 값이 들어왔으면(사용자가 연속 수정) 바로 이어서 한 번 더 저장
    if (st.pending != null && st.pending !== st.lastSent) {
      // 다음 턴에 실행
      if (st.timer) clearTimeout(st.timer);
      st.timer = setTimeout(() => flushSubBookSave(sid, field), 0);
    }
  }
}

function saveDocUrl(el) {
  const sid = el.dataset.id;
  const value = (el.value || '').trim();
  const stu = state.students.find(s => String(s.id) === String(sid));
  if (stu) stu.docUrl = value;         // 로컬 상태 반영
  patchField(sid, 'docUrl', value)     // 서버 반영
    .then(r => ok(r) ? toast('독스 URL 저장됨') : Promise.reject(r))
    .catch(() => alert('독스 URL 저장 실패'));
}

function tableSearchKeyForStudent(s) {
  return searchKeyForText([
    s?.name,
    s?.id,
    s?.school,
    s?.schoolName,
    s?.highSchool,
    s?.middleSchool,
    s?.high,
    s?.middle,
    s?.schoolHigh,
    s?.schoolMiddle,
    s?.고등학교,
    s?.중학교,
    s?.grade,
    s?.gradeLevel,
    s?.studentGrade,
    s?.학년,
    s?.level,
    s?.curriculum,
    s?.subCurriculum,
    s?.day1,
    s?.day2,
    s?.day3,
    s?.day4,
    s?.day5,
    s?.subBook1,
    s?.subBook2,
  ].filter(Boolean).join(' '));
}

function getVisitTimeFieldForDayField(dayField = '') {
  const match = String(dayField).match(/^day([1-5])$/);
  return match ? `visitTime${match[1]}` : '';
}

async function renderYoilStatsSafe() {
  const { renderYoilStats } = await import('./yoilStats.js');
  renderYoilStats();
}

async function toggleSelfStudyDay(el) {
  const sid = el.dataset.id;
  const field = el.dataset.day;
  if (!sid || !field) return;

  const value = (el.value || '').trim();
  if (!value) {
    alert('요일을 먼저 입력하세요.');
    return;
  }

  const stu = state.students.find(s => String(s.id) === String(sid));
  const prevRaw = stu ? stu[SELF_STUDY_DAYS_FIELD] : undefined;
  const prevEnabled = stu ? isSelfStudyDayField(stu, field) : el.dataset.selfStudy === '1';
  const nextEnabled = !prevEnabled;
  const nextMap = nextSelfStudyDays(stu || {}, field, nextEnabled);

  if (stu) stu[SELF_STUDY_DAYS_FIELD] = nextMap;
  el.dataset.selfStudy = nextEnabled ? '1' : '0';
  el.title = nextEnabled ? '자습' : '';

  try {
    const res = await patchField(sid, SELF_STUDY_DAYS_FIELD, nextMap);
    if (!ok(res)) throw res;
    await renderYoilStatsSafe();
    toast(nextEnabled ? '자습으로 표시됨' : '자습 해제됨');
  } catch {
    if (stu) stu[SELF_STUDY_DAYS_FIELD] = prevRaw;
    el.dataset.selfStudy = prevEnabled ? '1' : '0';
    el.title = prevEnabled ? '자습' : '';
    alert('자습 저장 실패');
  }
}

async function saveDayInput(el) {
  const sid = el.dataset.id;
  const field = el.dataset.day;
  if (!sid || !field) return;

  const value = (el.value || '').trim();
  const timeField = getVisitTimeFieldForDayField(field);
  const autoTime = baseTimeForDayValue(value);
  const stu = state.students.find(s => String(s.id) === String(sid));

  if (stu) {
    stu[field] = value;
    if (timeField) stu[timeField] = autoTime;
    if (!value && isSelfStudyDayField(stu, field)) {
      stu[SELF_STUDY_DAYS_FIELD] = nextSelfStudyDays(stu, field, false);
      el.dataset.selfStudy = '0';
      el.title = '';
    }
  }

  const timeInput = timeField
    ? document.querySelector(`.timeInput[data-id="${sid}"][data-field="${timeField}"]`)
    : null;
  if (timeInput) timeInput.value = autoTime;

  try {
    const dayRes = await patchField(sid, field, value);
    if (!ok(dayRes)) throw dayRes;

    if (timeField) {
      const timeRes = await patchField(sid, timeField, autoTime);
      if (!ok(timeRes)) throw timeRes;
    }
    if (!value && stu) {
      const selfStudyRes = await patchField(sid, SELF_STUDY_DAYS_FIELD, stu[SELF_STUDY_DAYS_FIELD] || {});
      if (!ok(selfStudyRes)) throw selfStudyRes;
    }

    toast('요일/등원시간 저장됨');
    await renderYoilStatsSafe();
  } catch {
    alert('저장 실패');
  }
}

function saveTimeInput(el) {
  const sid = el.dataset.id;
  const field = el.dataset.field;
  if (!sid || !field) return;
  const raw = (el.value || '').trim();
  const value = normalizeTimeInput(raw);

  el.value = value;

  const stu = state.students.find(s => String(s.id) === String(sid));
  if (stu) stu[field] = value;

  patchField(sid, field, value)
    .then(() => {
      toast('등원시간 저장됨');
    })
    .catch(() => {
      alert('등원시간 저장 실패');
    });
}

/* ─────────────────────────────────────────
   "학교" 인라인 편집
────────────────────────────────────────── */
function initSchoolInlineEdit() {
  const tbody = document.querySelector('#allWrap table tbody');
  if (!tbody) return;

  // 편집 시작
  tbody.addEventListener('dblclick', (e) => {
    const el = e.target.closest('.cell-school'); if (!el) return;
    if (el.isContentEditable) return;

    el.dataset.orig = (el.textContent || '').trim();
    el.contentEditable = 'true';
    el.classList.add('editing');

    // 커서 끝으로
    const range = document.createRange();
    range.selectNodeContents(el);
    range.collapse(false);
    const sel = window.getSelection();
    sel.removeAllRanges(); sel.addRange(range);
    el.focus();
  });

  // 저장(commit)
  const commit = async (el) => {
    const sid = el.dataset.id;
    const next = (el.textContent || '').trim();
    const prev = (el.dataset.orig || '').trim();
    el.contentEditable = 'false';
    el.classList.remove('editing');
    el.removeAttribute('data-orig');

    if (next === prev) return; // 변경 없음

    const stu = state.students.find(s => String(s.id) === String(sid));
    if (stu) {
      stu.school = next;
    }

    try {
      const res = await patchField(sid, 'school', next);
      if (!ok(res)) throw new Error(res?.status || 'save-failed');
      toast('학교 저장됨');
      renderCurStats();
    } catch (err) {
      if (stu) stu.school = prev;
      el.textContent = prev || '\u00a0';
      alert('학교 저장 실패');
    }
  };

  // 취소(rollback)
  const cancel = (el) => {
    const prev = el.dataset.orig || '';
    el.textContent = prev || '\u00a0';
    el.contentEditable = 'false';
    el.classList.remove('editing');
    el.removeAttribute('data-orig');
  };

  tbody.addEventListener('blur', (e) => {
    const el = e.target.closest('.cell-school');
    if (!el || !el.isContentEditable) return;
    commit(el);
  }, true);

  tbody.addEventListener('keydown', (e) => {
    const el = e.target.closest('.cell-school');
    if (!el || !el.isContentEditable) return;

    if (e.key === 'Enter') {
      e.preventDefault();
      el.blur();
    } else if (e.key === 'Escape') {
      e.preventDefault();
      cancel(el);
    }
  });
}

/* ─────────────────────────────────────────
   "학년" 인라인 편집
────────────────────────────────────────── */
function initGradeInlineEdit() {
  const tbody = document.querySelector('#allWrap table tbody');
  if (!tbody) return;

  // 편집 시작
  tbody.addEventListener('dblclick', (e) => {
    const el = e.target.closest('.cell-grade'); if (!el) return;
    if (el.isContentEditable) return;

    el.dataset.orig = (el.textContent || '').trim();
    el.contentEditable = 'true';
    el.classList.add('editing');

    const range = document.createRange();
    range.selectNodeContents(el);
    range.collapse(false);
    const sel = window.getSelection();
    sel.removeAllRanges(); sel.addRange(range);
    el.focus();
  });

  const commit = async (el) => {
    const sid = el.dataset.id;
    const next = (el.textContent || '').trim();
    const prev = (el.dataset.orig || '').trim();

    el.contentEditable = 'false';
    el.classList.remove('editing');
    el.removeAttribute('data-orig');

    if (next === prev) return;

    const stu = state.students.find(s => String(s.id) === String(sid));
    if (stu) {
      stu.grade = next;
    }

    try {
      const res = await patchField(sid, 'grade', next);
      if (!ok(res)) throw new Error(res?.status || 'save-failed');
      toast('학년 저장됨');
    } catch (err) {
      if (stu) stu.grade = prev;
      el.textContent = prev || '\u00a0';
      alert('학년 저장 실패');
    }
  };

  const cancel = (el) => {
    const prev = el.dataset.orig || '';
    el.textContent = prev || '\u00a0';
    el.contentEditable = 'false';
    el.classList.remove('editing');
    el.removeAttribute('data-orig');
  };

  tbody.addEventListener('blur', (e) => {
    const el = e.target.closest('.cell-grade');
    if (!el || !el.isContentEditable) return;
    commit(el);
  }, true);

  tbody.addEventListener('keydown', (e) => {
    const el = e.target.closest('.cell-grade');
    if (!el || !el.isContentEditable) return;

    if (e.key === 'Enter') {
      e.preventDefault();
      el.blur();
    } else if (e.key === 'Escape') {
      e.preventDefault();
      cancel(el);
    }
  });
}

/* ─────────────────────────────────────────
   테이블용 "미니 영상 진도 보기/수정"
   - 전체학생 페이지 저장분은 로그 내보내기 진도 변경분에서 제외되도록 source를 분리
   - state.progress 최신 누적 상태를 펼쳐 보여주고, 오늘 날짜에 변경분만 PATCH
────────────────────────────────────────── */
function todayLocalKey() {
  if (typeof window.todayLocalKey === 'function') return window.todayLocalKey();
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

function nextProgressState(st) {
  if (st === 'none') return 'done';
  if (st === 'done') return 'interrupted';
  return 'none';
}

function ensureMiniProgModal() {
  if (document.getElementById('miniProgModal')) return;

  const s = document.createElement('style');
  s.id = 'miniProgStyles';
  s.textContent = `
    #miniProgModal{
      position:fixed; inset:0; z-index:99998;
      background:rgba(0,0,0,.45);
      display:none; align-items:center; justify-content:center;
    }
    #miniProgModal .card{
      width:720px; max-width:96vw; max-height:82vh; overflow:auto;
      padding:12px; border-radius:12px;
      border:1px solid #e5e7eb; background:#fff; color:#0f172a;
      box-shadow:0 12px 34px rgba(0,0,0,.34);
    }
    body.dark #miniProgModal .card{
      background:#0f172a; color:#e5e7eb; border-color:#334155;
    }
    #miniProgModal .top{
      display:flex; align-items:center; justify-content:space-between; gap:8px;
      margin-bottom:10px;
    }
    #miniProgModal .title{
      font-weight:900; font-size:16px;
    }
    #miniProgModal button{
      height:34px; padding:0 12px; border-radius:10px;
      border:1px solid #e5e7eb; background:#f8fafc; cursor:pointer; font-weight:900;
    }
    #miniProgModal button.primary{
      background:#3b82f6; border-color:#3b82f6; color:#fff;
    }
    body.dark #miniProgModal button{
      border-color:#334155; background:#1f2937; color:#e5e7eb;
    }
    body.dark #miniProgModal button.primary{
      background:#2563eb; border-color:#2563eb; color:#fff;
    }

    #miniProgGrid{
      display:grid; grid-template-columns:repeat(auto-fill, minmax(82px,1fr));
      gap:8px; margin:8px 0 2px;
    }
    #miniProgGrid .progress-cell{
      display:flex; align-items:center; justify-content:center;
      min-height:44px; padding:8px; border-radius:10px; box-sizing:border-box;
      border:1px solid #e5e7eb; background:#ffffff; color:#0f172a;
      font-size:14px; user-select:none; cursor:pointer; position:relative;
    }
    #miniProgGrid .progress-cell:hover{ box-shadow:0 0 0 2px rgba(59,130,246,.18); }
    body.dark #miniProgGrid .progress-cell{ border-color:#334155; background:#0b1220; color:#e5e7eb; }

    #miniProgGrid .progress-cell[data-state="done"]{ background:#10b98122; border-color:#10b98155; }
    body.dark #miniProgGrid .progress-cell[data-state="done"]{
      background:color-mix(in srgb, #008558ff 18%, transparent); border-color:#0ea56e;
    }
    #miniProgGrid .progress-cell[data-state="interrupted"]{ background:#f59e0b22; border-color:#f59e0b66; }
    body.dark #miniProgGrid .progress-cell[data-state="interrupted"]{
      background:color-mix(in srgb, #fffb00ff 20%, transparent); border-color:#d97706;
    }
    #miniProgGrid .progress-cell[data-state="skip"]{ background:#ef444422; border-color:#ef444466; color:#111; }
    body.dark #miniProgGrid .progress-cell[data-state="skip"]{
      background:color-mix(in srgb, #ff0000ff 20%, transparent); border-color:#b91c1c; color:#fee2e2;
    }
    #miniProgModal .hint{
      margin-top:8px; opacity:.75; font-size:12px;
    }
    #miniProgModal .miniProgActions{
      display:flex; justify-content:flex-end; gap:8px; margin-top:10px;
    }
  `;
  document.head.appendChild(s);

  document.body.insertAdjacentHTML('beforeend', `
    <div id="miniProgModal">
      <div class="card">
        <div class="top">
          <div class="title" id="miniProgTitle">영상 진도</div>
          <div class="miniProgActions" style="margin-top:0">
            <button type="button" id="miniProgSave" class="primary">저장</button>
            <button type="button" id="miniProgClose">닫기</button>
          </div>
        </div>
        <div id="miniProgGrid"></div>
        <div class="hint">좌클릭: 흰색 → 초록 → 노랑 → 흰색, 우클릭: 빨강. 저장 시 관리자 운영판 진도와 공유됩니다.</div>
      </div>
    </div>
  `);

  const modal = document.getElementById('miniProgModal');
  const close = () => { modal.style.display = 'none'; modal.dataset.sid = ''; };
  document.getElementById('miniProgClose')?.addEventListener('click', close);
  document.getElementById('miniProgSave')?.addEventListener('click', saveMiniProgress);
}

function shouldSkipForLow(stu, v) {
  if (!stu || stu.level !== '하') return false;
  const ex = v && v.exNum;
  if (!ex || typeof ex !== 'object') return false;
  return Number(ex['하']) === 0;
}

// sid의 누적 progress 최신 상태(오늘까지)를 한 번에 펼쳐서 계산
function buildLatestProgEntryForSid(sid) {
  const today = todayLocalKey();

  const dates = Object.keys(state.progress || {})
    .filter(d => /^\d{4}-\d{2}-\d{2}$/.test(d) && d <= today)
    .sort();

  const out = {};
  dates.forEach(d => {
    const day = (state.progress?.[d] || {})[sid] || {};
    Object.entries(day).forEach(([mid, st]) => {
      if (String(mid).startsWith('__') || mid === 'tests') return;
      out[String(mid)] = st;
    });
  });
  return out;
}

async function openMiniProgressForSid(sid) {
  ensureMiniProgModal();

  const stu = state.students.find(x => String(x.id) === String(sid));
  if (!stu) { alert('학생 없음'); return; }
  await ensureProgressForSid(sid);

  const modal = document.getElementById('miniProgModal');
  const title = document.getElementById('miniProgTitle');
  const grid = document.getElementById('miniProgGrid');

  title.textContent = `${stu.name} – ${stu.curriculum} (영상 진도 보기)`;
  modal.dataset.sid = String(sid);

  const latest = buildLatestProgEntryForSid(String(sid));

  grid.innerHTML = '';
  (state.videos || [])
    .filter(v => v.curriculum === stu.curriculum && v.subCurriculum === stu.subCurriculum)
    .sort((a, b) => (a.chapter ?? 0) - (b.chapter ?? 0))
    .forEach(v => {
      const cell = document.createElement('div');
      cell.className = 'progress-cell';
      cell.textContent = `${v.chapter}차시`;
      cell.dataset.mid = String(v.mid);

      const autoSkip = shouldSkipForLow(stu, v);
      const st = latest[String(v.mid)] || (autoSkip ? 'skip' : 'none');
      cell.dataset.state = st;
      cell.dataset.initial = st;

      cell.addEventListener('click', () => {
        const cur = cell.dataset.state || 'none';
        cell.dataset.state = nextProgressState(cur);
      });
      cell.addEventListener('contextmenu', (ev) => {
        ev.preventDefault();
        cell.dataset.state = 'skip';
      });

      grid.appendChild(cell);
    });

  modal.style.display = 'flex';
}

async function saveMiniProgress() {
  const modal = document.getElementById('miniProgModal');
  const grid = document.getElementById('miniProgGrid');
  const sid = modal?.dataset.sid;
  if (!sid || !grid) return;

  const changed = {};
  grid.querySelectorAll('.progress-cell[data-mid]').forEach(cell => {
    const mid = String(cell.dataset.mid || '');
    const st = cell.dataset.state || 'none';
    const initial = cell.dataset.initial || 'none';
    if (mid && st !== initial) changed[mid] = st;
  });

  if (!Object.keys(changed).length) {
    toast('변경된 진도가 없습니다.');
    return;
  }

  const date = todayLocalKey();
  try {
    const res = await fetch('/api/progress/patch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        date,
        sid: String(sid),
        progress: changed,
        source: 'allStudents',
      }),
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok || !body?.ok) throw new Error(body?.error || res.status);

    state.progress = state.progress || {};
    state.progress[date] = state.progress[date] || {};
    state.progress[date][sid] = body.progress || {
      ...(state.progress[date][sid] || {}),
      ...changed,
    };
    window.progressData = state.progress;

    grid.querySelectorAll('.progress-cell[data-mid]').forEach(cell => {
      cell.dataset.initial = cell.dataset.state || 'none';
    });
    toast('영상 진도 저장됨');
    modal.style.display = 'none';
  } catch (err) {
    console.error('[all students progress save failed]', err);
    alert('영상 진도 저장 실패');
  }
}

// 🎬 버튼 핸들러
document.addEventListener('click', async (e) => {
  const btn = e.target.closest('.miniProgBtn');
  if (!btn) return;
  const sid = btn.dataset.id;
  if (!sid) return;
  await openMiniProgressForSid(String(sid));
});
