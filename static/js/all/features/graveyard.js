import { getJSONChecked, postJSON } from '../core/api.js';
import { state } from '../core/state.js';
import { matchesSearchText, applySearchPlaceholder } from '../../shared/search.js';

let dialog, list, detail, message, search, refresh, closeButton;
let rows = [], revision = null, selectedSid = '', generation = 0, selection = 0;
let restoring = false, onRestored = null, listLimit = 50;

const object = value => !!value && typeof value === 'object' && !Array.isArray(value);
const course = student => [student.curriculum, student.subCurriculum, student.level].filter(Boolean).join(' · ') || '과목 미지정';
const statusText = value => ({ done: '완료', assigned: '배정', interrupted: '진행 중', skip: '제외', none: '미완료', '': '해제' }[object(value) ? value.status : value] ?? String(object(value) ? value.status || '' : value ?? ''));

function el(tag, text = '', className = '') {
  const node = document.createElement(tag);
  if (text) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function button(text, action) {
  const node = el('button', text);
  node.type = 'button';
  node.addEventListener('click', action);
  return node;
}

function notify(text, error = false) {
  message.textContent = text;
  message.dataset.error = String(error);
}

function dateText(value) {
  if (!value) return '삭제일 미상';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString('ko-KR', { timeZone: 'Asia/Seoul', hour12: false });
}

function errorText(error) {
  if (error.status === 404) return '서버에 무덤 기능이 아직 적용되지 않았습니다. 서버 적용 후 다시 열어 주세요.';
  if (error.status === 401 || error.status === 403) return '관리자 인증을 확인한 뒤 다시 열어 주세요.';
  return '기록을 불러오지 못했습니다. 새로고침으로 다시 시도하세요.';
}

function mount() {
  if (dialog) return;
  dialog = el('dialog', '', 'graveyard');
  dialog.setAttribute('aria-labelledby', 'graveyardTitle');
  const header = el('div', '', 'graveyard-header');
  const titleBox = el('div');
  const title = el('h2', '무덤');
  title.id = 'graveyardTitle';
  titleBox.append(title, el('p', '삭제된 학생과 과목의 기록을 확인하고 복원합니다.', 'graveyard-muted'));
  closeButton = button('닫기', () => dialog.close());
  header.append(titleBox, closeButton);
  const toolbar = el('div', '', 'graveyard-toolbar');
  const label = el('label', '보관 기록 검색');
  search = el('input');
  search.type = 'search';
  applySearchPlaceholder(search, '이름 · 학교 · 과목 · 학생 ID');
  search.addEventListener('input', () => { listLimit = 50; renderList(); });
  label.append(search);
  refresh = button('새로고침', () => loadRows());
  toolbar.append(label, refresh);
  message = el('p', '', 'graveyard-message');
  message.setAttribute('role', 'status');
  message.setAttribute('aria-live', 'polite');
  const body = el('div', '', 'graveyard-body');
  list = el('div', '', 'graveyard-list');
  list.setAttribute('aria-label', '보관된 학생과 과목');
  detail = el('div', '', 'graveyard-detail');
  body.append(list, detail);
  dialog.append(header, toolbar, message, body);
  dialog.addEventListener('keydown', event => { if (event.key === 'Escape') event.stopPropagation(); });
  dialog.addEventListener('cancel', event => { if (restoring) event.preventDefault(); });
  dialog.addEventListener('close', () => { generation++; selection++; });
  document.body.append(dialog);
}

function renderList() {
  list.replaceChildren();
  const filtered = rows.filter(row => matchesSearchText(
    [row.student.name, row.student.school, row.student.grade, row.student.id, course(row.student)].join(' '), search.value,
  ));
  list.append(el('p', `${filtered.length}건 / 전체 ${rows.length}건`, 'graveyard-muted'));
  if (!filtered.length) list.append(el('p', rows.length ? '검색 결과가 없습니다.' : '보관된 기록이 없습니다.', 'graveyard-empty'));
  for (const row of filtered.slice(0, listLimit)) {
    const node = button('', () => selectRow(row));
    node.disabled = restoring;
    node.setAttribute('aria-pressed', String(String(row.student.id) === selectedSid));
    node.append(el('strong', row.student.name || row.student.id), el('span', course(row.student)),
      el('span', [row.student.school, row.student.grade].filter(Boolean).join(' · '), 'graveyard-muted'),
      el('span', row.activeCourses.length ? '다른 과목 재원 중' : '활성 과목 없음', 'graveyard-muted'));
    list.append(node);
  }
  if (filtered.length > listLimit) list.append(button('보관 기록 더 보기', () => { listLimit += 50; renderList(); }));
}

async function loadRows(successMessage = '') {
  if (restoring) return;
  const token = ++generation;
  selection++;
  revision = null;
  refresh.disabled = true;
  rows = [];
  list.replaceChildren(el('p', '보관 기록을 불러오는 중입니다.', 'graveyard-empty'));
  detail.replaceChildren();
  notify(successMessage || '보관 기록을 불러오는 중입니다.');
  try {
    const data = await getJSONChecked('/api/students/graveyard');
    if (!dialog.open || token !== generation) return;
    if (data?.ok !== true || !Array.isArray(data.students) ||
      data.students.some(row => !object(row.student) || !String(row.student.id ?? '').trim() || !Array.isArray(row.activeCourses)) ||
      (data.configured && !Number.isInteger(data.revision))) throw new Error('invalid graveyard response');
    rows = data.students;
    revision = data.revision;
    renderList();
    notify(successMessage || (data.configured
      ? '운영 기록은 보존됩니다. 복원하면 같은 학생 ID로 전체 명단에 다시 표시됩니다.'
      : '학생 연결 정보가 아직 설정되지 않아 무덤을 사용할 수 없습니다.'));
    const next = rows.find(row => String(row.student.id) === selectedSid) || rows[0];
    if (next) void selectRow(next);
    else detail.append(el('p', '삭제한 학생·과목이 여기에 보관됩니다.', 'graveyard-empty'));
  } catch (error) {
    if (dialog.open && token === generation) {
      list.replaceChildren();
      notify(errorText(error), true);
    }
  } finally {
    if (token === generation) refresh.disabled = false;
  }
}

function infoRow(parent, label, value) {
  parent.append(el('dt', label), el('dd', String(value || '—')));
}

async function selectRow(row) {
  if (restoring) return;
  selectedSid = String(row.student.id);
  const token = ++selection;
  const session = generation;
  renderList();
  detail.replaceChildren(el('h3', row.student.name || selectedSid), el('p', course(row.student)));
  const info = el('dl', '', 'graveyard-info');
  infoRow(info, '학교·학년', [row.student.school, row.student.grade].filter(Boolean).join(' · '));
  infoRow(info, '학생 ID', selectedSid);
  infoRow(info, '삭제일', dateText(row.retiredAt));
  infoRow(info, '현재 재원', row.activeCourses.map(course).join('\n') || '활성 과목 없음');
  const schedule = [1, 2, 3, 4, 5].map(i => [row.student[`day${i}`], row.student[`visitTime${i}`]].filter(Boolean).join(' ')).filter(Boolean).join(' · ');
  infoRow(info, '보관 일정', schedule || (row.snapshotComplete ? '등록된 일정 없음' : '보관 정보 없음'));
  detail.append(info);
  if (!row.snapshotComplete) detail.append(el('p', '이전 삭제 기록에는 전체 설정이 없습니다. 기본 정보와 과목만 복원되므로 등원 일정 등 수업 설정을 다시 확인하세요.', 'graveyard-notice'));
  const restore = button('전체 학생 명단으로 복원', () => restoreRow(row));
  restore.className = 'graveyard-restore';
  restore.disabled = !row.restorable || !Number.isInteger(revision);
  detail.append(restore);
  if (!row.restorable) detail.append(el('p', '통합된 사람 정보에 속한 기록은 여기서 복원할 수 없습니다.', 'graveyard-notice'));
  detail.append(el('h3', '수업·진도 기록'));
  const history = el('div', '기록을 불러오는 중입니다.', 'graveyard-history');
  detail.append(history);
  const sid = selectedSid;
  const query = new URLSearchParams({ sid });
  try {
    const [logs, progress] = await Promise.all([
      getJSONChecked(`/api/logs?${query}`), getJSONChecked(`/api/progress?${query}`),
    ]);
    if (!dialog.open || token !== selection || session !== generation) return;
    if (!object(logs) || !object(progress) || logs.ok === false || progress.ok === false ||
      [...Object.keys(logs), ...Object.keys(progress)].some(key => !/^\d{4}-\d{2}-\d{2}$/.test(key))) throw new Error('invalid history response');
    renderHistory(history, logs, progress, sid);
  } catch (error) {
    if (!dialog.open || token !== selection || session !== generation) return;
    history.replaceChildren(el('p', '수업·진도 기록을 불러오지 못했습니다.'));
    history.append(button('기록 다시 불러오기', () => selectRow(row)));
  }
}

function addSection(parent, title, lines) {
  if (!lines.length) return;
  const section = el('section');
  section.append(el('strong', title));
  const values = el('ul');
  lines.forEach(text => values.append(el('li', text)));
  section.append(values);
  parent.append(section);
}

function renderHistory(target, logs, progress, sid) {
  target.replaceChildren();
  const dates = [...new Set([...Object.keys(logs), ...Object.keys(progress)])]
    .filter(date => object(logs[date]?.[sid]) || object(progress[date]?.[sid])).sort().reverse();
  if (!dates.length) { target.append(el('p', '보관된 수업·진도 기록이 없습니다.', 'graveyard-muted')); return; }
  target.append(el('p', `${dates.length}일의 기록 · 최신 날짜순`, 'graveyard-muted'));
  let shown = 0;
  const more = button('이전 기록 더 보기', () => appendBatch());
  function appendBatch() {
    more.remove();
    for (const date of dates.slice(shown, shown + 30)) {
      const log = logs[date]?.[sid] || {};
      const entry = progress[date]?.[sid] || {};
      const record = el('details', '', 'graveyard-record');
      record.append(el('summary', date));
      const flags = [['done', '하원'], ['hwChecked', '숙제 검사 완료'], ['archived', '기록 정리 완료'], ['selfStudy', '자습']]
        .filter(([key]) => log[key] === true || log[key] === 1 || log[key] === 'true').map(([, label]) => label);
      addSection(record, '수업 상태', flags);
      if (log.notes) { const notes = el('section'); notes.append(el('strong', '특이사항'), el('p', String(log.notes))); record.append(notes); }
      addSection(record, '숙제', (Array.isArray(log.homeworkTable) ? log.homeworkTable : []).map(item =>
        object(item) ? Object.entries(item).filter(([key, value]) => !key.startsWith('__') && value !== null && value !== '')
          .map(([key, value]) => `${({ book: '교재', this: '이번 숙제', next: '다음 숙제', pct: '완료율', comment: '메모', rem: '메모', range: '범위', page: '쪽', pages: '쪽', progress: '진도', percent: '완료율', checked: '검사', note: '메모' })[key] || key}: ${typeof value === 'boolean' ? (value ? '예' : '아니요') : String(value)}${key === 'pct' && /^\d+(\.\d+)?$/.test(String(value)) ? '%' : ''}`).join(' · ') : String(item),
      ));
      const tests = object(entry.tests) ? entry.tests : {};
      const testNames = new Map((Array.isArray(log.assignedTests) ? log.assignedTests : []).map(test => [String(test.id || test.testId || ''), test.title || test.name]));
      addSection(record, '시험 진도', Object.entries(tests).filter(([key]) => !key.startsWith('__')).map(([id, value]) => `${value?.title || value?.name || testNames.get(id) || id} · ${statusText(value)}`));
      addSection(record, '영상 진도', Object.entries(entry).filter(([key, value]) => key !== 'tests' && !key.startsWith('__') && (typeof value === 'string' || object(value) && typeof value.status === 'string'))
        .map(([id, value]) => {
          const video = state.videos.find(item => String(item.mid || item.id) === id || String(item.url || '').includes(`/s/${id}`));
          return `${video?.title || video?.name || id} · ${statusText(value)}`;
        }));
      if (record.children.length === 1) record.append(el('p', '이 날짜의 저장 기록이 있습니다.'));
      target.append(record);
    }
    shown += 30;
    if (shown < dates.length) target.append(more);
  }
  appendBatch();
}

async function restoreRow(row) {
  if (restoring || !dialog.open) return;
  const warning = row.snapshotComplete ? '삭제 당시 과목 설정과 기존 운영 기록을 다시 연결합니다.' : '기본 정보와 과목만 복원합니다. 등원 일정 등 누락된 설정은 복원 후 확인하세요.';
  if (!confirm(`"${row.student.name || row.student.id}" · ${course(row.student)}\n전체 학생 명단으로 복원할까요?\n${warning}`)) return;
  restoring = true;
  refresh.disabled = closeButton.disabled = search.disabled = true;
  dialog.querySelectorAll('button').forEach(node => { node.disabled = true; });
  notify('전체 학생 명단으로 복원하는 중입니다.');
  let restored = false;
  let resultMessage = '';
  try {
    const response = await postJSON(`/api/students/${encodeURIComponent(row.student.id)}/restore`, { revision });
    const data = await response.json();
    if (!response.ok || data?.ok !== true || String(data.student?.id) !== String(row.student.id)) {
      throw new Error(data?.error || '복원에 실패했습니다. 목록을 새로고침하고 다시 시도하세요.');
    }
    restored = true;
    resultMessage = `${row.student.name || row.student.id} · ${course(row.student)} 복원 완료. ${row.snapshotComplete ? '전체 학생 명단에 반영했습니다.' : '전체 학생 명단에서 등원 일정을 확인하세요.'}`;
    await onRestored?.(data.student);
  } catch (error) {
    resultMessage = restored ? '복원은 완료했습니다. 최신 명단을 불러오지 못했으므로 페이지를 새로고침하세요.' : error.message;
    if (!restored) {
      try { await onRestored?.(); }
      catch { resultMessage += ' 최신 명단 확인을 위해 페이지를 새로고침하세요.'; }
    }
  } finally {
    restoring = false;
    refresh.disabled = closeButton.disabled = search.disabled = false;
  }
  // Always discard the old revision, including when a response was lost after commit.
  await loadRows(resultMessage);
}

export async function openGraveyard(options = {}) {
  mount();
  onRestored = options.onRestored;
  if (!dialog.open) dialog.showModal();
  search.focus();
  await loadRows();
}
