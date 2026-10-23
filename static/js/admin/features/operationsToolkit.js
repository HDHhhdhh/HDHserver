import { state } from '../core/state.js';
import { api } from '../core/api.js';
import { getAdminDate } from '../core/adminDate.js';
import { matchesSearchText, SEARCH_HELP_TEXT } from '../../shared/search.js';
import { loadToolkitLibrary } from './toolkitLibraries.js';
import { projectPendingWork, projectDailyMetrics, trailingDates } from './operationsProjection.js';
import { getSaveOperations, saveStageLabel } from './saveOperations.js';

let dialog, table, chart, chartData = [], currentTab = 'pending', generation = 0, healthTimer;
let queueFlight = null, statsFlight = null;
const $ = id => document.getElementById(id);
const textNode = (tag, text) => { const node = document.createElement(tag); node.textContent = text; return node; };
const isDemo = () => location.pathname.startsWith('/demo/');

function liveRows() {
  return Array.from(document.querySelectorAll('#todayWrap tr[data-sid], #doneWrap tr[data-sid]')).map(row => ({
    sid: row.dataset.sid, date: row.dataset.date, done: Boolean(row.closest('#doneWrap')),
    attended: row.dataset.att === '1' || Boolean(row.querySelector('.attChk')?.checked),
    selfStudy: row.dataset.selfStudy === '1', hwChecked: row.dataset.hw === '1' || Boolean(row.querySelector('.hwCheckChk')?.checked),
    hwRequested: row.dataset.hwRequest === '1',
  }));
}

function openStudent(item) {
  if (window.isStudentPopupSavePending?.()) return;
  const row = Array.from(document.querySelectorAll('#todayWrap tr[data-sid], #doneWrap tr[data-sid]'))
    .find(candidate => candidate.dataset.sid === item.sid && candidate.dataset.date === item.date);
  if (!row || typeof window.openStudentPopupsForRow !== 'function') {
    $('opsToolkitNotice').textContent = '명단이 바뀌었습니다. 새로고침한 뒤 다시 선택하세요.'; return;
  }
  dialog.close();
  void window.openStudentPopupsForRow(row).catch(error => alert(error.message));
}

function filterQueue() {
  const query = $('opsWorkSearch').value, kind = $('opsWorkKind').value;
  table?.setFilter(item => (!kind || item.kind === kind) && matchesSearchText(`${item.name} ${item.subject} ${item.label}`, query));
}

function updateQueue() {
  if (!dialog?.open || currentTab !== 'pending') return Promise.resolve();
  if (queueFlight) return queueFlight;
  queueFlight = (async () => {
    try {
      const Tabulator = await loadToolkitLibrary('tabulator');
      if (!dialog.open || currentTab !== 'pending') return;
      if (!table) {
        table = new Tabulator($('opsWorkTable'), {
          data: [], layout: 'fitColumns', height: '360px', pagination: 'local', paginationSize: 12,
          paginationCounter: 'rows', locale: 'ko', langs: { ko: { pagination: { first: '처음', last: '마지막', prev: '이전', next: '다음', counter: { showing: '표시', of: '/', rows: '건', pages: '페이지' } } } },
          placeholder: '현재 처리할 일이 없습니다.', movableColumns: true,
          columnDefaults: { formatter: 'plaintext', headerSort: true, resizable: true },
          columns: [
            { title: '학생', field: 'name', minWidth: 95 },
            { title: '할 일', field: 'label', minWidth: 125 },
            { title: '과목', field: 'subject', minWidth: 85 },
            { title: '날짜', field: 'date', width: 110 },
            { title: '확인 내용', field: 'detail', minWidth: 200, widthGrow: 3 },
            { title: '작업', headerSort: false, width: 85, formatter(cell) {
              const button = textNode('button', '열기'); button.type = 'button'; button.className = 'ops-open-student';
              button.setAttribute('aria-label', `${cell.getRow().getData().name} 학생 팝업 열기`);
              button.addEventListener('click', () => openStudent(cell.getRow().getData())); return button;
            } },
          ],
        });
        await new Promise(resolve => table.on('tableBuilt', resolve));
      }
      const items = projectPendingWork({ rows: liveRows(), students: state.students, updates: state.updates, progress: state.progress });
      await table.replaceData(items);
      filterQueue();
      $('opsWorkCount').textContent = `${new Set(items.map(item => item.sid)).size}명 · ${items.length}건`;
      $('opsToolkitNotice').textContent = `${getAdminDate()} 운영 명단 기준 · 백지리뷰는 학생별 현재 표시입니다.`;
    } catch (error) { $('opsToolkitNotice').textContent = `목록을 불러오지 못했습니다. ${error.message}`; }
  })().finally(() => { queueFlight = null; });
  return queueFlight;
}

function checkedMap(value, label) {
  if (!value || typeof value !== 'object' || Array.isArray(value) || value.ok === false) throw new Error(`${label} 응답 형식 오류`);
  return value;
}

async function loadStatistics(force = false) {
  if (statsFlight && !force) return statsFlight;
  const token = ++generation, end = getAdminDate();
  chart?.clear(); chartData = []; $('opsStatsRows').replaceChildren();
  $('opsStatsRefresh').disabled = true;
  $('opsStatsStatus').textContent = '최근 7일 기록을 불러오는 중…';
  statsFlight = (async () => {
    const values = [];
    try {
      // Limit the date batches to one at a time; only the three independent reads overlap.
      for (const date of trailingDates(end)) {
        if (token !== generation || !dialog.open || currentTab !== 'stats') return;
        const [attendance, logs, progress] = await Promise.all([
          api.getStrict(`/api/attendance?date=${date}`, '출석 통계', { cache: 'no-store' }),
          api.getStrict(`/api/logs?date=${date}`, '숙검 통계', { cache: 'no-store' }),
          api.getStrict(`/api/progress?date=${date}`, '진도 통계', { cache: 'no-store' }),
        ]);
        values.push(projectDailyMetrics({ date, attendance: checkedMap(attendance, '출석'), logs: checkedMap(logs, '숙검'), progress: checkedMap(progress, '진도') }));
      }
      const echarts = await loadToolkitLibrary('echarts');
      if (token !== generation || !dialog.open || currentTab !== 'stats' || end !== getAdminDate()) return;
      chartData = values;
      if (!chart) chart = echarts.init($('opsWeeklyChart'), null, { renderer: 'svg' });
      drawChart();
      renderStatisticsTable();
      $('opsStatsStatus').textContent = `${values[0].date} ~ ${end} · SID별 기록 기준 (과목이 다르면 별도 집계)`;
    } catch (error) {
      if (token === generation) {
        chart?.clear(); chartData = []; $('opsStatsRows').replaceChildren();
        $('opsStatsStatus').textContent = `통계를 불러오지 못했습니다. 새로고침으로 다시 시도하세요. ${error.message}`;
      }
    }
  })().finally(() => { if (token === generation) { statsFlight = null; $('opsStatsRefresh').disabled = false; } });
  return statsFlight;
}

function drawChart() {
  if (!chart) return;
  const dark = document.body.classList.contains('dark'), color = dark ? '#dbe4f0' : '#334155';
  chart.setOption({ backgroundColor: 'transparent', color: ['#2563eb', '#059669', '#d97706'],
    aria: { enabled: true }, textStyle: { color, fontFamily: 'Malgun Gothic, sans-serif' },
    tooltip: { trigger: 'axis', renderMode: 'richText' }, legend: { type: 'scroll', top: 6, left: 0, right: 0, textStyle: { color }, pageTextStyle: { color } },
    grid: { left: 48, right: 45, top: 60, bottom: 35 },
    xAxis: { type: 'category', data: chartData.map(day => day.date.slice(5)), axisLabel: { color } },
    yAxis: [{ type: 'value', name: '출석 건', minInterval: 1, axisLabel: { color } }, { type: 'value', name: '완료율 %', min: 0, max: 100, axisLabel: { color } }],
    series: [
      { name: '출석', type: 'bar', data: chartData.map(day => day.attended), barMaxWidth: 32 },
      { name: '숙검 완료율', type: 'line', yAxisIndex: 1, data: chartData.map(day => day.homeworkRate), connectNulls: false },
      { name: '영상 기록 완료율', type: 'line', yAxisIndex: 1, data: chartData.map(day => day.videoRate), connectNulls: false },
    ],
  }, true);
  chart.resize();
}

function renderStatisticsTable() {
  const body = $('opsStatsRows'); body.replaceChildren();
  chartData.forEach(day => {
    const row = document.createElement('tr');
    [day.date, day.attended, day.homeworkTotal ? `${day.homeworkChecked}/${day.homeworkTotal} (${day.homeworkRate}%)` : '기록 없음',
      day.videoTotal ? `${day.videosDone}/${day.videoTotal} (${day.videoRate}%)` : '기록 없음'].forEach(value => row.append(textNode('td', value)));
    body.append(row);
  });
}

function renderHistory() {
  const host = $('opsSaveHistory'); host.replaceChildren();
  const records = getSaveOperations();
  if (!records.length) { host.append(textNode('p', '이 탭에서 진행한 통합 저장이 아직 없습니다.')); return; }
  for (const record of records) {
    const article = document.createElement('article'); article.className = 'ops-save-item';
    const name = state.students.find(student => String(student.id) === record.sid)?.name || record.sid;
    const label = { success: '완료', failed: '확인 필요', interrupted: '완료 확인 불가', running: '저장 중' }[record.status] || '확인 필요';
    article.dataset.status = record.status;
    article.append(textNode('strong', `${name} · ${record.date} · ${label}`));
    article.append(textNode('p', Object.entries(record.stages).map(([stage, result]) => `${saveStageLabel(stage)}: ${{ running: '진행 중', complete: '완료', failed: '실패·확인 필요' }[result] || result}`).join(' / ') || '저장 준비'));
    article.append(textNode('small', `${record.id} · ${new Date(record.startedAt).toLocaleTimeString('ko-KR')}`));
    host.append(article);
  }
}

async function checkHealth() {
  if (!dialog.open || currentTab !== 'health') return;
  if (isDemo()) { $('opsHealthStatus').textContent = '데모에서는 실제 서버 감시를 실행하지 않습니다.'; return; }
  const controller = new AbortController(), timeout = setTimeout(() => controller.abort(), 8000), start = performance.now();
  try {
    await api.getStrict('/api/ping', '서버 상태', { cache: 'no-store', signal: controller.signal });
    $('opsHealthStatus').textContent = `현재 접속 서버 응답 정상 · ${Math.round(performance.now() - start)}ms · ${new Date().toLocaleTimeString('ko-KR')}`;
  } catch { $('opsHealthStatus').textContent = '서버에 연결하지 못했습니다. 네트워크와 서버 상태를 확인하세요.'; }
  finally { clearTimeout(timeout); }
}

function selectTab(tab) {
  currentTab = tab; generation++; statsFlight = null; clearInterval(healthTimer);
  dialog.querySelectorAll('[data-ops-tab]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.opsTab === tab)));
  dialog.querySelectorAll('[data-ops-panel]').forEach(panel => { panel.hidden = panel.dataset.opsPanel !== tab; });
  $('opsToolkitNotice').textContent = '';
  if (tab === 'pending') void updateQueue();
  if (tab === 'stats') void loadStatistics();
  if (tab === 'history') renderHistory();
  if (tab === 'health') { void checkHealth(); healthTimer = setInterval(checkHealth, 30000); }
}

export function initOperationsToolkit() {
  if (dialog || !$('todayWrap')) return;
  const link = document.createElement('link'); link.rel = 'stylesheet'; link.href = '/css/admin-operations-toolkit.css'; document.head.append(link);
  const button = textNode('button', '운영 도구'); button.id = 'operationsToolkitOpen'; button.type = 'button'; button.className = 'btn secondary';
  document.querySelector('.global-links')?.append(button);
  dialog = document.createElement('dialog'); dialog.id = 'operationsToolkit'; dialog.setAttribute('aria-labelledby', 'opsToolkitTitle');
  dialog.innerHTML = `<header class="ops-toolkit-head"><div><p>학원 운영</p><h2 id="opsToolkitTitle">운영 도구</h2></div><button type="button" id="opsToolkitClose" class="btn secondary">닫기</button></header>
    <nav class="ops-toolkit-tabs" aria-label="운영 도구 선택"><button type="button" data-ops-tab="pending">처리 목록</button><button type="button" data-ops-tab="stats">주간 통계</button><button type="button" data-ops-tab="history">저장 이력</button><button type="button" data-ops-tab="health">서버 상태</button></nav>
    <p id="opsToolkitNotice" role="status"></p>
    <section data-ops-panel="pending"><div class="ops-work-controls"><label>학생 검색<input type="search" id="opsWorkSearch"></label><label>종류<select id="opsWorkKind"><option value="">전체</option><option value="homework">숙검</option><option value="review">백지리뷰</option><option value="video">영상</option></select></label><strong id="opsWorkCount"></strong><button type="button" id="opsWorkRefresh" class="btn secondary">새로고침</button></div><div id="opsWorkTable" aria-label="현재 처리 목록"></div></section>
    <section data-ops-panel="stats" hidden><div class="ops-stats-heading"><p id="opsStatsStatus" role="status"></p><button type="button" id="opsStatsRefresh" class="btn secondary">새로고침</button></div><div id="opsWeeklyChart" role="img" aria-label="최근 7일 출석과 완료율 추이"></div><p class="ops-explanation">숙검 완료율은 배부·요청·검사 기록이 있는 항목 중 검사 완료 비율입니다. 영상은 해당 날짜의 진도 기록 중 완료 비율이며 제외(skip)와 기록 없는 항목은 계산하지 않습니다. 기록이 없으면 빈 구간으로 표시합니다.</p><div class="ops-stats-table-wrap"><table class="ops-stats-table"><caption>날짜별 집계 원값</caption><thead><tr><th>날짜</th><th>출석 건</th><th>숙검 완료/기록</th><th>영상 완료/기록</th></tr></thead><tbody id="opsStatsRows"></tbody></table></div></section>
    <section data-ops-panel="history" hidden><p class="ops-explanation">이 브라우저 탭의 최근 30회 통합 저장입니다. 새로고침 후에도 유지되며 탭을 닫으면 사라집니다. 실패 단계 내부에서 일부 저장됐을 수 있습니다. 수정 내용을 확인한 뒤 기존 저장 버튼으로 재시도하세요.</p><div id="opsSaveHistory" aria-live="polite"></div></section>
    <section data-ops-panel="health" hidden><h3>현재 접속 서버</h3><p id="opsHealthStatus" role="status"></p><p>이 화면을 열어 두면 30초마다 응답을 확인합니다.</p><h3>서버 감시 기록</h3><p>서버 PC의 Uptime Kuma가 운영 서버와 공개 학생앱을 별도로 감시합니다. 외부 메시지는 발송하지 않습니다.</p><a id="opsKumaLink" href="http://127.0.0.1:3001/status/academy" target="_blank" rel="noopener noreferrer" class="btn secondary">Uptime Kuma 상태 화면</a><p class="ops-explanation">이 링크는 서버 PC에서 사용하세요. 다른 PC에서는 서버 PC의 로컬 화면을 열 수 없습니다. 서버 PC 자체가 꺼지면 감시도 멈춥니다.</p></section>`;
  document.body.append(dialog);
  $('opsWorkSearch').placeholder = SEARCH_HELP_TEXT;
  if (isDemo()) $('opsKumaLink').removeAttribute('href');
  button.addEventListener('click', () => { dialog.showModal(); selectTab('pending'); });
  $('opsToolkitClose').addEventListener('click', () => dialog.close());
  dialog.addEventListener('close', () => {
    // A queued close event from the previous opening must not cancel a newly opened view.
    if (dialog.open) return;
    generation++; statsFlight = null; clearInterval(healthTimer); button.focus();
  });
  dialog.querySelectorAll('[data-ops-tab]').forEach(item => item.addEventListener('click', () => selectTab(item.dataset.opsTab)));
  $('opsWorkSearch').addEventListener('input', filterQueue); $('opsWorkKind').addEventListener('change', filterQueue);
  $('opsWorkRefresh').addEventListener('click', () => { document.dispatchEvent(new CustomEvent('admin:refresh')); void updateQueue(); });
  $('opsStatsRefresh').addEventListener('click', () => { void loadStatistics(true); });
  document.addEventListener('today:rendered', updateQueue);
  document.addEventListener('admin:date-change', () => { if (dialog.open && currentTab === 'stats') void loadStatistics(true); });
  document.addEventListener('admin:save-history', () => { if (dialog.open && currentTab === 'history') renderHistory(); });
  new ResizeObserver(() => { if (dialog.open && currentTab === 'stats') chart?.resize(); }).observe($('opsWeeklyChart'));
  new MutationObserver(() => { if (dialog.open && currentTab === 'stats') drawChart(); }).observe(document.body, { attributes: true, attributeFilter: ['class'] });
}
