// table.js — 전체 학생 테이블 렌더
// - "학교" 인라인 편집(자동 저장, 빈칸에서도 추가 가능)
// - "학년" 인라인 편집(자동 저장)
// - "커리큘럼/세부커리큘럼" 수정 가능 (고정 옵션 셀렉트)
// - "요일" 밑 "등원시간" 행 추가 (월1~일1=13:00 / 월2~일2=18:00 기본, 수정 가능)
// - "독스(docUrl)" 인라인 입력/저장 + 새 탭 열기 버튼
// - 테이블에서 관리자 상담 기록 팝업(기록 읽기 전용, 영상 진도 우클릭 수정)
// - 커리별 학생 수(이름+학교 기준으로 중복 제거)

import { $, toast } from '../core/utils.js';
import { patchField } from '../core/api.js';
import { state } from '../core/state.js';
import { applySearchPlaceholder, matchesSearchKey, searchKeyForText } from '../../shared/search.js';
import { SELF_STUDY_DAYS_FIELD, isSelfStudyDayField, nextSelfStudyDays } from '../../shared/selfStudy.js';

const subCurrOptions = ['A:Ble', 'APEX'];
const CURRICULUM_OPTIONS = ['공수1', '공수2', '대수', '미적분1', '미적분2', '기하', '확통'];
const EMPTY_SCHOOL_LABEL = '학교 입력';
const AUTO_VIDEO_ASSIGN_FIELD = 'autoVideoAssignCount';
const ABLE_AUTO_VIDEO_ASSIGN_COUNT = 1;
const ABLE_CURRICULUM_KEY = 'a:ble';

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

function normalizeInlineCellText(value = '') {
  return String(value ?? '').replace(/\u00a0/g, ' ').trim();
}

function isAbleCurriculumValue(value) {
  return String(value ?? '').trim().toLowerCase() === ABLE_CURRICULUM_KEY;
}

function usesAbleCurriculum(stu) {
  return isAbleCurriculumValue(stu?.curriculum) || isAbleCurriculumValue(stu?.subCurriculum);
}

function syncAbleAutoVideoAssignDefault(stu, wasAble, changedValue) {
  if (!stu) return;
  if (usesAbleCurriculum(stu) && (!wasAble || isAbleCurriculumValue(changedValue))) {
    stu[AUTO_VIDEO_ASSIGN_FIELD] = ABLE_AUTO_VIDEO_ASSIGN_COUNT;
  }
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

  const rows = state.students.map(s => {
    const sub = s.subCurriculum || '';
    const level = s.level || '';
    const grade = s.grade ?? s.gradeLevel ?? s.studentGrade ?? s.학년 ?? '';
    const high = s.highSchool || s.schoolHigh || s.high || s.highschool || s.high_school || s.고등학교 || '';
    const middle = s.middleSchool || s.schoolMiddle || s.middle || s.middleschool || s.middle_school || s.중학교 || s.school || '';
    const schoolText = s.school || high || middle || '';
    const schoolValue = normalizeInlineCellText(schoolText);
    const doc = s.docUrl || '';
    const cur = s.curriculum || '';
    const homeworkBooks = Array.isArray(state.homeworkBooksBySid?.[String(s.id)])
      ? state.homeworkBooksBySid[String(s.id)]
      : [];

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
    <tr data-id="${s.id}" data-sid="${s.id}" data-date="${todayLocalKey()}" data-curriculum="${escapeHtml(cur)}" data-subcurriculum="${escapeHtml(sub)}" data-search-key="${escapeHtml(tableSearchKeyForStudent(s))}">
      <td class="cell-name">
        <a href="/student/${s.id}" target="_blank" class="stuName"
           data-id="${s.id}" data-grade="${escapeHtml(grade)}"
           data-high="${escapeHtml(high)}" data-middle="${escapeHtml(middle)}">
          ${escapeHtml(s.name)}
        </a>
      </td>

      <!-- 학교: 인라인 편집 전용(더블클릭) -->
      <td>
        <span class="cell-school${schoolValue ? '' : ' is-empty'}"
              data-id="${s.id}"
              data-empty="${schoolValue ? '0' : '1'}"
              contenteditable="false"
              tabindex="0"
              role="textbox"
              aria-label="학교"
              aria-readonly="true"
              title="${schoolValue ? '더블클릭하여 학교를 편집하세요' : '클릭하여 학교를 입력하세요'}">
          ${schoolValue ? escapeHtml(schoolValue) : EMPTY_SCHOOL_LABEL}
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
        <div class="sbBox linkedHomeworkBooks" title="관리자운영판 숙제 교재 등록과 연동">
          ${homeworkBooks.length
            ? homeworkBooks.map(book => `<span class="linkedHomeworkBook">${escapeHtml(book)}</span>`).join('')
            : '<span class="linkedHomeworkBook is-empty">미등록</span>'}
        </div>
      </td>

      <!-- 독스 URL: 인라인 편집 + 열기 + 영상진도(보기/수정) -->
      <td>
        <div class="docBox">
          <input type="url" class="docUrlInput" data-id="${s.id}"
                 placeholder="https://docs.google.com/..."
                 value="${escapeHtml(doc)}">
          <button type="button" class="docOpen" title="새 탭에서 열기" data-id="${s.id}">🔗</button>
          <button type="button" class="miniProgBtn" title="상담 기록 및 영상 진도 보기" data-id="${s.id}">상담</button>
          <button type="button" class="studentTestRecordBtn" title="테스트 기록 보기" data-test-result-sid="${escapeHtml(s.id)}" data-test-result-name="${escapeHtml(s.name || s.id)}">기록</button>
        </div>
      </td>
    </tr>`;
  }).join('');

  host.innerHTML = `<style>
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
        max-width:100%;
        overflow-wrap:anywhere;
        word-break:keep-all;
      }
      #allWrap .studentsTable .cell-school {
        min-width:4.5em;
        padding:2px 5px;
        border-radius:6px;
        cursor:text;
      }
      #allWrap .studentsTable .cell-grade {
        min-width:0;
      }
      #allWrap .studentsTable .cell-school[data-empty="1"] {
        color:#64748b;
        border:1px dashed #cbd5e1;
        background:rgba(148,163,184,.08);
      }
      body.dark #allWrap .studentsTable .cell-school[data-empty="1"] {
        color:#94a3b8;
        border-color:#475569;
        background:rgba(148,163,184,.12);
      }
      #allWrap .studentsTable .cell-school.editing {
        color:inherit;
        border:1px solid #2563eb;
        background:#fff;
        outline:2px solid rgba(37,99,235,.2);
      }
      body.dark #allWrap .studentsTable .cell-school.editing {
        background:#0b1220;
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
        display:flex;
        flex-wrap:wrap;
        gap:4px;
      }
      #allWrap .studentsTable .linkedHomeworkBook {
        min-width:0;
        padding:5px 7px;
        border:1px solid #e5e7eb;
        border-radius:8px;
        background:#f8fafc;
        font-size:11px;
        line-height:1.25;
        overflow-wrap:anywhere;
      }
      #allWrap .studentsTable .linkedHomeworkBook.is-empty { opacity:.58; }
      body.dark #allWrap .studentsTable .linkedHomeworkBook {
        border-color:#334155;
        background:#0b1220;
      }
      #allWrap .studentsTable .docBox {
        grid-template-columns:minmax(0, 1fr) 34px 34px;
        gap:4px;
      }
      #allWrap .studentsTable .docBox .studentTestRecordBtn {
        grid-column:1 / -1;
        width:100%;
        min-width:0;
        overflow:hidden;
        text-overflow:ellipsis;
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
        font-size:10px;
        font-weight:800;
      }
      body.dark #allWrap .studentsTable .miniProgBtn{
        border-color:#334155;
        background:#0b1220;
        color:#e5e7eb;
      }

      @media (max-width:900px){
        body.all-page #allWrap{
          overflow-x:auto !important;
          overscroll-behavior-inline:contain;
        }
        body.all-page #allWrap .studentsTable,
        #allWrap .studentsTable{
          width:1120px !important;
          min-width:1120px !important;
          max-width:none !important;
        }
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
  if (hint) hint.textContent = queryText.trim() ? `${visible}/${rows.length} 수업행` : '';
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
    if (stu) {
      const wasAble = usesAbleCurriculum(stu);
      stu.curriculum = value;
      syncAbleAutoVideoAssignDefault(stu, wasAble, value);
    }
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
    if (stu) {
      const wasAble = usesAbleCurriculum(stu);
      stu.subCurriculum = value;
      syncAbleAutoVideoAssignDefault(stu, wasAble, value);
    }
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

  // 독스 URL (change에서도 저장)
  if (e.target.classList.contains('docUrlInput')) { saveDocUrl(e.target); return; }
});

document.addEventListener('blur', (e) => {
  if (e.target.classList.contains('docUrlInput')) saveDocUrl(e.target);
  if (e.target.classList.contains('timeInput')) saveTimeInput(e.target);
}, true);

document.addEventListener('keydown', (e) => {
  const t = e.target;
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
    ...(state.homeworkBooksBySid?.[String(s?.id)] || []),
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
function setSchoolCellDisplay(el, value) {
  const text = normalizeInlineCellText(value);
  el.textContent = text || EMPTY_SCHOOL_LABEL;
  el.dataset.empty = text ? '0' : '1';
  el.classList.toggle('is-empty', !text);
  el.contentEditable = 'false';
  el.setAttribute('aria-readonly', 'true');
  el.title = text ? '더블클릭하여 학교를 편집하세요' : '클릭하여 학교를 입력하세요';
}

function getSchoolCellValue(el) {
  return el?.dataset.empty === '1' ? '' : normalizeInlineCellText(el?.textContent || '');
}

function focusEditableEnd(el) {
  const range = document.createRange();
  range.selectNodeContents(el);
  range.collapse(false);
  const sel = window.getSelection();
  sel.removeAllRanges();
  sel.addRange(range);
  el.focus();
}

function startSchoolEdit(el) {
  if (!el || el.isContentEditable) return;

  const prev = getSchoolCellValue(el);
  el.dataset.orig = prev;
  el.textContent = prev;
  el.dataset.empty = '0';
  el.classList.remove('is-empty');
  el.contentEditable = 'true';
  el.setAttribute('aria-readonly', 'false');
  el.classList.add('editing');
  focusEditableEnd(el);
}

function initSchoolInlineEdit() {
  const tbody = document.querySelector('#allWrap table tbody');
  if (!tbody) return;

  tbody.addEventListener('click', (e) => {
    const el = e.target.closest('.cell-school');
    if (!el || el.isContentEditable || el.dataset.empty !== '1') return;
    e.preventDefault();
    startSchoolEdit(el);
  });

  // 편집 시작
  tbody.addEventListener('dblclick', (e) => {
    const el = e.target.closest('.cell-school'); if (!el) return;
    startSchoolEdit(el);
  });

  // 저장(commit)
  const commit = async (el) => {
    const sid = el.dataset.id;
    const next = normalizeInlineCellText(el.textContent || '');
    const prev = normalizeInlineCellText(el.dataset.orig || '');
    el.contentEditable = 'false';
    el.classList.remove('editing');
    el.removeAttribute('data-orig');

    if (next === prev) {
      setSchoolCellDisplay(el, prev);
      return;
    }

    const stu = state.students.find(s => String(s.id) === String(sid));
    if (stu) {
      stu.school = next;
    }

    try {
      const res = await patchField(sid, 'school', next);
      if (!ok(res)) throw new Error(res?.status || 'save-failed');
      setSchoolCellDisplay(el, next);
      toast('학교 저장됨');
      renderCurStats();
    } catch (err) {
      if (stu) stu.school = prev;
      setSchoolCellDisplay(el, prev);
      alert('학교 저장 실패');
    }
  };

  // 취소(rollback)
  const cancel = (el) => {
    const prev = el.dataset.orig || '';
    setSchoolCellDisplay(el, prev);
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
    if (!el) return;

    if (!el.isContentEditable) {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        startSchoolEdit(el);
      }
      return;
    }

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

/* 행의 상담 기록 팝업 날짜는 실제 로컬 오늘을 사용한다. */
function todayLocalKey() {
  if (typeof window.todayLocalKey === 'function') return window.todayLocalKey();
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

let studentRecordPopupModulePromise = null;

async function ensureStudentRecordPopupReady() {
  if (!studentRecordPopupModulePromise) {
    studentRecordPopupModulePromise = import('./studentRecordPopup.js').catch((error) => {
      studentRecordPopupModulePromise = null;
      throw error;
    });
  }
  const { initAllStudentsRecordPopup } = await studentRecordPopupModulePromise;
  await initAllStudentsRecordPopup(state);
}

// 관리자 통합 팝업은 첫 상담 클릭 때만 불러와 전체학생 초기 렌더를 막지 않는다.
document.addEventListener('click', async (e) => {
  const btn = e.target.closest('.miniProgBtn');
  if (!btn) return;
  const sid = btn.dataset.id;
  if (!sid) return;
  const row = btn.closest('tr[data-sid]');
  if (!row) return;

  const originalText = btn.textContent;
  btn.disabled = true;
  btn.textContent = '로딩…';
  try {
    await ensureStudentRecordPopupReady();
    if (typeof window.openStudentPopupsForRow !== 'function') {
      throw new Error('unified student popup launcher unavailable');
    }
    await window.openStudentPopupsForRow(row, {
      accessMode: 'all-students-readonly',
    });
  } catch (error) {
    console.error('[all students popup load failed]', error);
    alert('학생 통합 팝업을 불러오지 못했습니다. 새로고침 후 다시 시도해 주세요.');
  } finally {
    if (btn.isConnected) {
      btn.disabled = false;
      btn.textContent = originalText;
    }
  }
});
