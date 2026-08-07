import { $, toast } from '../core/utils.js';
import { state } from '../core/state.js';

const TARGET_LABELS = {
  all: '전체',
  grade: '학년',
  subject: '과목',
  curriculum: '커리큘럼',
};

const TARGET_MODE_ORDER = ['all', 'grade', 'subject', 'curriculum'];

let targetMode = 'all';
let targetFilters = {
  grade: '',
  subject: '',
  curriculum: '',
  subCurriculum: '',
  level: '',
};
let refreshBound = false;

function normStr(value) {
  return String(value ?? '').trim();
}

function escapeHtml(value = '') {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function csvCell(value) {
  const text = String(value ?? '');
  return /[",\r\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
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

function schoolForRoster(stu = {}) {
  const raw = normStr(
    stu.school ?? stu.schoolName ?? stu.highSchool ?? stu.middleSchool ??
    stu.high ?? stu.middle ?? stu.schoolHigh ?? stu.schoolMiddle ??
    stu.highschool ?? stu.middleschool ?? stu.high_school ?? stu.middle_school ??
    stu.고등학교 ?? stu.중학교 ?? ''
  );
  return raw.replace(/고등학교$/u, '').replace(/고$/u, '');
}

function gradeNumberForRoster(stu = {}) {
  const raw = normStr(stu.grade ?? stu.gradeLevel ?? stu.studentGrade ?? stu.학년 ?? '');
  const match = raw.match(/\d+/);
  return match ? match[0] : raw;
}

export function chatNameForRoster(stu = {}) {
  const school = schoolForRoster(stu);
  const grade = gradeNumberForRoster(stu);
  const name = normStr(stu.name ?? '');
  return `A ${school}${grade}${school || grade ? ' ' : ''}${name}`.trim();
}

function studentSchool(stu = {}) {
  return normStr(
    stu.school ?? stu.schoolName ?? stu.highSchool ?? stu.middleSchool ??
    stu.high ?? stu.middle ?? stu.schoolHigh ?? stu.schoolMiddle ??
    stu.highschool ?? stu.middleschool ?? stu.high_school ?? stu.middle_school ??
    stu.고등학교 ?? stu.중학교 ?? ''
  );
}

export function rowForChatRosterExport(stu = {}) {
  const sid = normStr(stu.id);
  const curriculum = normStr(stu.curriculum ?? stu.subject ?? '');
  const subCurriculum = normStr(stu.subCurriculum ?? stu.course ?? '');
  const level = normStr(stu.level ?? stu.difficulty ?? '');
  const grade = normStr(stu.grade ?? stu.gradeLevel ?? stu.studentGrade ?? stu.학년 ?? '');

  return {
    sid,
    student: stu,
    name: normStr(stu.name ?? sid),
    school: studentSchool(stu),
    grade,
    curriculum,
    subCurriculum,
    level,
    chatName: chatNameForRoster(stu),
  };
}

function rosterBaseRows() {
  return (Array.isArray(state.students) ? state.students : [])
    .map(rowForChatRosterExport)
    .filter(row => row.sid || row.name || row.chatName);
}

function chatRosterDedupeKey(row = {}) {
  const chatName = normStr(row.chatName);
  if (chatName && chatName !== 'A') return `chat:${chatName}`;
  return `row:${normStr(row.sid) || normStr(row.name) || chatName}`;
}

export function uniqueChatRosterRows(rows = []) {
  const seen = new Set();
  const unique = [];
  rows.forEach((row) => {
    const key = chatRosterDedupeKey(row);
    if (!key || seen.has(key)) return;
    seen.add(key);
    unique.push(row);
  });
  return unique;
}

function uniqueSorted(values) {
  return Array.from(new Set(values.map(value => normStr(value)).filter(Boolean)))
    .sort((a, b) => a.localeCompare(b, 'ko', { numeric: true }));
}

function rowsForCurriculumFilterOption(key) {
  return rosterBaseRows().filter((row) => {
    if (key !== 'curriculum' && targetFilters.curriculum && row.curriculum !== targetFilters.curriculum) return false;
    if (key !== 'subCurriculum' && targetFilters.subCurriculum && row.subCurriculum !== targetFilters.subCurriculum) return false;
    if (key !== 'level' && targetFilters.level && row.level !== targetFilters.level) return false;
    return true;
  });
}

function filterValues(key) {
  if (key === 'grade') return uniqueSorted(rosterBaseRows().map(row => row.grade));
  if (key === 'subject') return uniqueSorted(rosterBaseRows().map(row => row.curriculum));
  return uniqueSorted(rowsForCurriculumFilterOption(key).map(row => row[key]));
}

function rowsForMode(mode = targetMode) {
  const rows = rosterBaseRows();
  if (mode === 'grade') {
    return uniqueChatRosterRows(rows.filter(row => !targetFilters.grade || row.grade === targetFilters.grade));
  }
  if (mode === 'subject') {
    return uniqueChatRosterRows(rows.filter(row => !targetFilters.subject || row.curriculum === targetFilters.subject));
  }
  if (mode === 'curriculum') {
    return uniqueChatRosterRows(rows.filter((row) => {
      if (targetFilters.curriculum && row.curriculum !== targetFilters.curriculum) return false;
      if (targetFilters.subCurriculum && row.subCurriculum !== targetFilters.subCurriculum) return false;
      if (targetFilters.level && row.level !== targetFilters.level) return false;
      return true;
    }));
  }
  return uniqueChatRosterRows(rows);
}

function renderSelectOptions(values, selected, allLabel = '전체') {
  return [
    `<option value="">${escapeHtml(allLabel)}</option>`,
    ...values.map(value => `<option value="${escapeHtml(value)}"${value === selected ? ' selected' : ''}>${escapeHtml(value)}</option>`),
  ].join('');
}

function reconcileTargetFilters() {
  if (targetFilters.grade && !filterValues('grade').includes(targetFilters.grade)) targetFilters.grade = '';
  if (targetFilters.subject && !filterValues('subject').includes(targetFilters.subject)) targetFilters.subject = '';
  if (targetFilters.curriculum && !filterValues('curriculum').includes(targetFilters.curriculum)) targetFilters.curriculum = '';
  if (targetFilters.subCurriculum && !filterValues('subCurriculum').includes(targetFilters.subCurriculum)) targetFilters.subCurriculum = '';
  if (targetFilters.level && !filterValues('level').includes(targetFilters.level)) targetFilters.level = '';
}

function targetSelectionLabel(mode = targetMode) {
  if (mode === 'grade') return `학년: ${targetFilters.grade || '전체'}`;
  if (mode === 'subject') return `과목: ${targetFilters.subject || '전체'}`;
  if (mode === 'curriculum') {
    const subject = targetFilters.curriculum || '과목 전체';
    const course = targetFilters.subCurriculum || '과정 전체';
    const level = targetFilters.level || '난이도 전체';
    return `커리큘럼: ${subject} / ${course} / ${level}`;
  }
  return TARGET_LABELS[mode] || '전체';
}

function filenameSafe(value) {
  return normStr(value)
    .replace(/[\\/:*?"<>|]+/g, '_')
    .replace(/\s+/g, '_')
    .replace(/^_+|_+$/g, '') || '전체';
}

function todayStamp() {
  const d = new Date();
  const pad = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

export function chatRosterRowsToCsv(rows) {
  const columns = ['타임', '대화명', '텍스트'];
  const lines = [columns.map(csvCell).join(',')];

  rows.forEach((row) => {
    lines.push(['', row.chatName || '', ''].map(csvCell).join(','));
  });

  return `\uFEFF${lines.join('\r\n')}\r\n`;
}

function ensureMount() {
  let host = $('chatRosterExportMount');
  if (host) return host;

  host = document.createElement('section');
  host.id = 'chatRosterExportMount';
  host.className = 'chatRosterExport';

  const newStudentMount = $('newStuMount');
  const yoilStats = $('yoilStats');
  const allWrap = $('allWrap');
  if (newStudentMount) {
    newStudentMount.insertAdjacentElement('afterend', host);
  } else if (yoilStats) {
    yoilStats.insertAdjacentElement('beforebegin', host);
  } else if (allWrap) {
    allWrap.insertAdjacentElement('beforebegin', host);
  } else {
    document.querySelector('main')?.appendChild(host);
  }
  return host;
}

function ensureStyles() {
  if ($('chatRosterExportStyles')) return;
  const style = document.createElement('style');
  style.id = 'chatRosterExportStyles';
  style.textContent = `
    .chatRosterExport{
      margin:0 0 18px;
      padding:14px;
      border:1px solid #dbe4ef;
      border-radius:12px;
      background:#ffffff;
      color:#0f172a;
      box-sizing:border-box;
    }
    body.dark .chatRosterExport{
      background:#111827;
      border-color:#22304a;
      color:#e5e7eb;
    }
    .chatRosterExport-head{
      display:flex;
      align-items:center;
      justify-content:space-between;
      gap:12px;
      flex-wrap:wrap;
    }
    .chatRosterExport-title{
      display:flex;
      align-items:center;
      gap:10px;
      flex-wrap:wrap;
      min-width:0;
    }
    .chatRosterExport-title strong{ font-size:16px; }
    .chatRosterExport-summary{
      color:#64748b;
      font-size:13px;
      font-weight:700;
    }
    body.dark .chatRosterExport-summary{ color:#cbd5e1; }
    .chatRosterExport-download{
      height:36px;
      padding:0 14px;
      border:1px solid #2563eb;
      border-radius:8px;
      background:#2563eb;
      color:#fff;
      font-weight:800;
      cursor:pointer;
      white-space:nowrap;
    }
    .chatRosterExport-download:hover{ filter:brightness(.96); }
    .chatRosterExport-targets{
      display:flex;
      gap:6px;
      flex-wrap:wrap;
      margin-top:12px;
    }
    .chatRosterExport-targets button{
      height:34px;
      padding:0 12px;
      border:1px solid #cbd5e1;
      border-radius:8px;
      background:#f8fafc;
      color:#0f172a;
      font-weight:800;
      cursor:pointer;
    }
    .chatRosterExport-targets button.is-active{
      border-color:#2563eb;
      background:#eff6ff;
      color:#1d4ed8;
    }
    body.dark .chatRosterExport-targets button{
      border-color:#334155;
      background:#1f2937;
      color:#e5e7eb;
    }
    body.dark .chatRosterExport-targets button.is-active{
      border-color:#60a5fa;
      background:#172554;
      color:#bfdbfe;
    }
    .chatRosterExport-filters{
      display:grid;
      grid-template-columns:repeat(auto-fit, minmax(180px, 1fr));
      gap:10px;
      margin-top:10px;
    }
    .chatRosterExport-filters[hidden]{ display:none !important; }
    .chatRosterExport-field{
      display:flex;
      flex-direction:column;
      gap:5px;
      min-width:0;
    }
    .chatRosterExport-field span{
      font-size:12px;
      color:#64748b;
      font-weight:800;
    }
    body.dark .chatRosterExport-field span{ color:#cbd5e1; }
    .chatRosterExport-field select{
      width:100%;
      height:36px;
      border:1px solid #cbd5e1;
      border-radius:8px;
      background:#fff;
      color:#0f172a;
      padding:0 9px;
      font:14px/36px system-ui, "Noto Sans KR", sans-serif;
      box-sizing:border-box;
    }
    body.dark .chatRosterExport-field select{
      background:#1f2937;
      border-color:#334155;
      color:#e5e7eb;
    }
  `;
  document.head.appendChild(style);
}

function renderControls() {
  reconcileTargetFilters();
  const host = ensureMount();
  const rows = rowsForMode();
  const filterHidden = targetMode === 'all';
  host.innerHTML = `
    <div class="chatRosterExport-head">
      <div class="chatRosterExport-title">
        <strong>대화명 CSV</strong>
        <span class="chatRosterExport-summary" id="chatRosterExportSummary">${escapeHtml(targetSelectionLabel())} · ${rows.length}명</span>
      </div>
      <button class="chatRosterExport-download" type="button" id="chatRosterExportBtn">CSV 내보내기</button>
    </div>
    <div class="chatRosterExport-targets" role="group" aria-label="CSV 대상">
      ${TARGET_MODE_ORDER.map(mode => `
        <button type="button" data-export-target-mode="${escapeHtml(mode)}" class="${mode === targetMode ? 'is-active' : ''}" aria-pressed="${mode === targetMode ? 'true' : 'false'}">
          ${escapeHtml(TARGET_LABELS[mode])}
        </button>
      `).join('')}
    </div>
    <div class="chatRosterExport-filters" ${filterHidden ? 'hidden' : ''}>
      ${targetMode === 'grade' ? `
        <label class="chatRosterExport-field">
          <span>학년</span>
          <select data-export-target-filter="grade">
            ${renderSelectOptions(filterValues('grade'), targetFilters.grade, '학년 전체')}
          </select>
        </label>
      ` : ''}
      ${targetMode === 'subject' ? `
        <label class="chatRosterExport-field">
          <span>과목</span>
          <select data-export-target-filter="subject">
            ${renderSelectOptions(filterValues('subject'), targetFilters.subject, '과목 전체')}
          </select>
        </label>
      ` : ''}
      ${targetMode === 'curriculum' ? `
        <label class="chatRosterExport-field">
          <span>과목</span>
          <select data-export-target-filter="curriculum">
            ${renderSelectOptions(filterValues('curriculum'), targetFilters.curriculum, '과목 전체')}
          </select>
        </label>
        <label class="chatRosterExport-field">
          <span>과정</span>
          <select data-export-target-filter="subCurriculum">
            ${renderSelectOptions(filterValues('subCurriculum'), targetFilters.subCurriculum, '과정 전체')}
          </select>
        </label>
        <label class="chatRosterExport-field">
          <span>난이도</span>
          <select data-export-target-filter="level">
            ${renderSelectOptions(filterValues('level'), targetFilters.level, '난이도 전체')}
          </select>
        </label>
      ` : ''}
    </div>
  `;
}

function exportSelectedRoster() {
  const rows = rowsForMode()
    .slice()
    .sort((a, b) =>
      a.chatName.localeCompare(b.chatName, 'ko', { numeric: true }) ||
      a.name.localeCompare(b.name, 'ko', { numeric: true })
    );

  if (!rows.length) {
    toast('내보낼 대상이 없습니다.');
    return;
  }

  const label = filenameSafe(targetSelectionLabel());
  const csv = chatRosterRowsToCsv(rows);
  downloadTextFile(`학생대화명_${label}_${todayStamp()}.csv`, csv, 'text/csv;charset=utf-8');
  toast(`대화명 CSV ${rows.length}명 내보내기 완료`);
}

function bindEvents() {
  const host = ensureMount();
  if (host.dataset.bound === '1') return;
  host.dataset.bound = '1';

  host.addEventListener('click', (ev) => {
    const modeBtn = ev.target?.closest?.('[data-export-target-mode]');
    if (modeBtn) {
      targetMode = modeBtn.dataset.exportTargetMode || 'all';
      renderControls();
      return;
    }

    if (ev.target?.closest?.('#chatRosterExportBtn')) {
      exportSelectedRoster();
    }
  });

  host.addEventListener('change', (ev) => {
    const select = ev.target?.closest?.('[data-export-target-filter]');
    if (!select) return;
    const key = select.dataset.exportTargetFilter;
    if (Object.prototype.hasOwnProperty.call(targetFilters, key)) {
      targetFilters = { ...targetFilters, [key]: select.value || '' };
      renderControls();
    }
  });
}

function bindRefreshEvents() {
  if (refreshBound) return;
  refreshBound = true;
  const refresh = () => {
    if (!$('chatRosterExportMount')) return;
    renderControls();
  };

  document.addEventListener('admin:refresh', refresh);
  document.addEventListener('change', (ev) => {
    if (!ev.target?.closest?.('#allWrap')) return;
    window.setTimeout(refresh, 0);
  });
  document.addEventListener('focusout', (ev) => {
    if (!ev.target?.matches?.('#allWrap .cell-grade, #allWrap .cell-school')) return;
    window.setTimeout(refresh, 0);
  });
}

export function mountChatRosterExport() {
  ensureStyles();
  ensureMount();
  renderControls();
  bindEvents();
  bindRefreshEvents();
}
