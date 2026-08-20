import { chromium } from 'file:///C:/tmp/calendar-verifier-playwright/node_modules/playwright-core/index.mjs';
import { mkdir, writeFile } from 'node:fs/promises';
import { spawn } from 'node:child_process';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(fileURLToPath(new URL('..', import.meta.url)));
const chrome = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const baseUrl = process.env.ADMIN_MAKEUP_TEST_BASE_URL || 'http://127.0.0.1:8003';
const artifactsArgIndex = process.argv.indexOf('--artifacts-dir');
const artifactDir = artifactsArgIndex >= 0 && process.argv[artifactsArgIndex + 1]
  ? process.argv[artifactsArgIndex + 1]
  : resolve(root, '.omo/evidence/task-admin-makeup-panel');
const assert = (value, message) => { if (!value) throw new Error(message); };

const students = [
  { id: 'pending-1', name: '보라', school: '새봄고', curriculum: '대수', day1: '금 1' },
  { id: 'scheduled-1', name: '가람', school: '새봄고', curriculum: '기하', day1: '금 1' },
  { id: 'scheduled-2', name: '다온', school: '한빛고', curriculum: '미적분', day1: '토 2' },
  { id: 'scheduled-3', name: '라온', school: '한빛고', curriculum: '확률', day1: '일 1' },
];
let carryover = {
  by_absence: {
    '2026-07-01': { 'scheduled-1|1': { state: 'carried', scheduledMakeup: { originalAbsenceId: 'absence|2026-07-01|scheduled-1|1', studentId: 'scheduled-1', makeupDate: '2026-07-10', makeupTimes: [1], status: 'scheduled', ownedExtra: true, ownedSlots: [1], createdBy: 'makeup-planner' } } },
    '2026-07-02': { 'scheduled-2|2': { state: 'carried', scheduledMakeup: { originalAbsenceId: 'absence|2026-07-02|scheduled-2|2', studentId: 'scheduled-2', makeupDate: '2026-07-10', makeupTimes: [2], status: 'scheduled', ownedExtra: false, ownedSlots: [], createdBy: 'makeup-planner' } } },
    '2026-07-03': { 'scheduled-3|1': { state: 'carried', scheduledMakeup: { originalAbsenceId: 'absence|2026-07-03|scheduled-3|1', studentId: 'scheduled-3', makeupDate: '2026-07-11', makeupTimes: [1], status: 'scheduled' } } },
  }, manual: {},
};
let fixtureExtra = { '2026-07-10': ['scheduled-1'] };
let fixtureWeekend = { '2026-07-10': { 'scheduled-1': [1], 'scheduled-2': [2] } };

async function reachable() {
  try { return (await fetch(`${baseUrl}/admin`)).ok; } catch { return false; }
}
async function startServer() {
  if (await reachable()) return null;
  const child = spawn('python', ['app.py'], { cwd: root, stdio: 'ignore', windowsHide: true });
  for (let i = 0; i < 80; i += 1) {
    if (await reachable()) return child;
    await new Promise(resolveWait => setTimeout(resolveWait, 150));
  }
  child.kill(); throw new Error('verification server did not start');
}
function installCalendarFallback() {
  class Calendar {
    constructor(element, options) { this.element = element; this.options = options; this.view = { activeStart: new Date(2026, 5, 22), activeEnd: new Date(2026, 6, 27), currentStart: new Date(2026, 5, 22), currentEnd: new Date(2026, 6, 27) }; }
    render() {
      const grid = document.createElement('div'); grid.className = 'fc-daygrid-body';
      for (let date = new Date(this.view.activeStart); date < this.view.activeEnd; date.setDate(date.getDate() + 1)) {
        const day = new Date(date); const key = `${day.getFullYear()}-${String(day.getMonth() + 1).padStart(2, '0')}-${String(day.getDate()).padStart(2, '0')}`;
        const cell = document.createElement('div'); cell.className = 'fc-daygrid-day'; cell.dataset.date = key;
        const frame = document.createElement('div'); frame.className = 'fc-daygrid-day-frame'; frame.innerHTML = this.options.dayCellContent?.({ date: day, view: this.view })?.html || key;
        cell.append(frame); cell.addEventListener('click', () => this.options.dateClick?.({ dateStr: key, dayEl: cell })); grid.append(cell);
      }
      this.element.replaceChildren(grid); this.options.datesSet?.({ start: this.view.activeStart, end: this.view.activeEnd });
    }
    changeView() { this.render(); } removeAllEvents() {} addEventSource() {}
  }
  window.FullCalendar = { Calendar }; window.Sortable = { create: () => ({ destroy() {} }) };
}

let browser; let server;
let allowScheduledCarryover = false;
let evidencePhase = 'initial-load';
const diagnostics = { mutations: [], apiRequests: [], directRequests: [], pageErrors: [], dialogs: [], requestFailures: [] };
try {
  await mkdir(artifactDir, { recursive: true }); server = await startServer();
  browser = await chromium.launch({ executablePath: chrome, headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } });
  page.on('pageerror', error => diagnostics.pageErrors.push(String(error.stack || error)));
  page.on('dialog', dialog => {
    diagnostics.dialogs.push(`${dialog.type()}: ${dialog.message()}`);
    dialog.dismiss().catch(() => {});
  });
  page.on('requestfailed', request => diagnostics.requestFailures.push(`${request.method()} ${request.url()} ${request.failure()?.errorText || ''}`));
  await page.addInitScript(installCalendarFallback);
  await page.route('https://cdn.jsdelivr.net/**', route => route.fulfill({ status: 200, body: '' }));
  await page.route('**/arrive-time/patch', async route => {
    const request = route.request();
    diagnostics.directRequests.push({ phase: evidencePhase, method: request.method(), path: '/arrive-time/patch', fixture: true });
    if (!allowScheduledCarryover) { await route.abort(); return; }
    await route.fulfill({ status: 200, contentType: 'application/json', body: '{}' });
  });
  await page.route('**/api/**', async route => {
    const request = route.request(); const path = new URL(request.url()).pathname;
    diagnostics.apiRequests.push({ phase: evidencePhase, method: request.method(), path, fixture: true });
    if (request.method() !== 'GET') {
      diagnostics.mutations.push(`${request.method()} ${path}`);
      if (!allowScheduledCarryover) { await route.abort(); return; }
      if (path === '/api/makeup-carryover') {
        carryover = JSON.parse(request.postData() || '{}');
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(carryover) });
        return;
      }
      if (path === '/api/extra-attend') {
        const patch = JSON.parse(request.postData() || '{}');
        const dates = patch?.dates || (patch?.date ? { [patch.date]: patch.sids } : {});
        for (const [date, sids] of Object.entries(dates)) {
          if (Array.isArray(sids) && sids.length) fixtureExtra[date] = [...sids];
          else delete fixtureExtra[date];
        }
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ ok: true, dates }),
        });
        return;
      }
      if (path === '/api/weekend-slots') {
        const patch = JSON.parse(request.postData() || '{}');
        for (const [date, mapping] of Object.entries(patch || {})) {
          if (!mapping || typeof mapping !== 'object') continue;
          const day = { ...(fixtureWeekend[date] || {}) };
          for (const [sid, value] of Object.entries(mapping)) {
            if (value === null || value === false || (Array.isArray(value) && value.length === 0)) delete day[sid];
            else day[sid] = value;
          }
          if (Object.keys(day).length) fixtureWeekend[date] = day;
          else delete fixtureWeekend[date];
        }
        await route.fulfill({ status: 200, contentType: 'application/json', body: '{}' });
        return;
      }
      await route.abort();
      return;
    }
    const data = path === '/api/students' ? students : path === '/api/videos' ? [] : path === '/api/absent' ? { by_date: { '2026-07-02': ['pending-1'] }, by_student: {}, by_slot: {} } : path === '/api/makeup-carryover' ? carryover : path === '/api/extra-attend' ? fixtureExtra : path === '/api/weekend-slots' ? fixtureWeekend : path === '/api/attend' ? [] : {};
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      headers: path === '/api/makeup-carryover'
        ? { 'X-Makeup-Carryover-Revision': 'fixture-revision' }
        : {},
      body: JSON.stringify(data),
    });
  });
  await page.goto(`${baseUrl}/admin`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('#makeupStatus', { timeout: 8000 });
  await page.waitForSelector('.makeup-panel-stack', { timeout: 8000 });
  const panelLayout = await page.locator('#makeupPlanner').evaluate(planner => {
    const status = document.querySelector('#makeupStatus');
    const plannerRect = planner.getBoundingClientRect();
    const statusRect = status?.getBoundingClientRect();
    const attendanceCheck = document.querySelector('#attendanceCheckToggle');
    const manualAbsence = document.querySelector('#openManualMakeup');
    const actionGroup = document.querySelector('.makeup-planner-control-group');
    return {
      statusBelowPlanner: !!statusRect && statusRect.top >= plannerRect.bottom,
      sameWidth: !!statusRect && Math.abs(statusRect.width - plannerRect.width) < 1,
      headerActionsShareRow: !!attendanceCheck && !!manualAbsence && Math.abs(attendanceCheck.getBoundingClientRect().top - manualAbsence.getBoundingClientRect().top) < 1,
      headerActionsGrouped: !!actionGroup && actionGroup.contains(attendanceCheck) && actionGroup.contains(manualAbsence),
    };
  });
  assert(panelLayout.statusBelowPlanner, '보강 현황이 보강 잡기 아래에 배치되지 않았습니다.');
  assert(panelLayout.sameWidth, '보강 현황이 보강 잡기와 같은 너비가 아닙니다.');
  assert(panelLayout.headerActionsShareRow, '등원일 확인과 결석 추가가 같은 행에 배치되지 않았습니다.');
  assert(panelLayout.headerActionsGrouped, '등원일 확인과 결석 추가가 같은 제어 그룹에 있지 않습니다.');
  assert(await page.locator('#attendanceCheckExit').count() === 0, '확인 종료 버튼이 남아 있습니다.');
  assert(await page.locator('#makeupPlanner').innerText().then(text => text.includes('보라')), 'pending makeup is missing from 보강 잡기');
  assert(!(await page.locator('#makeupPlanner').innerText()).includes('가람'), 'scheduled makeup leaked into 보강 잡기');
  assert((await page.locator('#makeupStatus').innerText()).includes('가람'), 'scheduled makeup is missing from 보강 현황');
  assert(await page.locator('#makeupStatus [data-makeup-action="pick"]').count() >= 2, '보강 변경 actions are missing');
  assert(await page.locator('#makeupStatus [data-makeup-action="carryover-scheduled"]').count() >= 2, '보강 현황 이월 actions are missing');
  assert(await page.locator('#makeupStatus [data-makeup-action="cancel-schedule"]').count() === 0, '보강 취소 action is still rendered');
  assert(await page.locator('#calendarMakeupSearch, .scheduled-makeup-list, .scheduled-makeup-chip, .attend-makeup-origin-badge').count() === 0, 'removed calendar makeup UI is still rendered');
  evidencePhase = 'attendance-check';
  await page.locator('#attendanceCheckToggle').click();
  assert((await page.locator('#makeupPlannerHint').innerText()).includes('ESC를 누르면 확인 모드가 종료됩니다.'), 'ESC 종료 안내가 표시되지 않았습니다.');
  await page.locator('#makeupPlannerSearch').fill('보라');
  await page.locator('#makeupPlannerList [data-makeup-action="check"]').click();
  await page.waitForFunction(() => document.querySelectorAll('.makeup-conflict-list').length > 0);
  const labels = await page.locator('.makeup-conflict-list').allTextContents();
  assert(labels.some(text => text.includes('대수 - 정규 - 1타임')), '등원일 확인 라벨이 표시되지 않았습니다.');
  assert(await page.locator('.makeup-slot-popover').count() === 0, '등원일 확인이 보강 슬롯 선택을 열었습니다.');
  assert(diagnostics.mutations.length === 0, `읽기 전용 확인 중 저장 요청 발생: ${diagnostics.mutations.join(', ')}`);
  const mutationsBeforeEscape = diagnostics.mutations.length;
  evidencePhase = 'escape';
  await page.keyboard.press('Escape');
  assert(await page.locator('#attendanceCheckToggle').isVisible(), 'ESC로 등원일 확인 모드가 종료되지 않았습니다.');
  const mutationsAfterEscape = diagnostics.mutations.length;
  const escapeApiRequests = diagnostics.apiRequests.filter(request => request.phase === 'escape');
  assert(mutationsAfterEscape === mutationsBeforeEscape, 'ESC 종료 중 저장 요청이 발생했습니다.');
  assert(escapeApiRequests.every(request => request.method === 'GET'), 'ESC 종료 중 변경 API 요청이 발생했습니다.');
  assert(diagnostics.apiRequests.every(request => request.fixture === true), 'fixture 외부 API 요청이 발생했습니다.');
  evidencePhase = 'scheduled-carryover';
  allowScheduledCarryover = true;
  await page.locator('#makeupStatus .makeup-row').filter({ hasText: '가람' }).locator('[data-makeup-action="carryover-scheduled"]').click();
  await page.waitForFunction(() => !document.querySelector('#makeupStatus')?.textContent?.includes('가람'), undefined, { timeout: 8000 });
  const carried = carryover.by_absence?.['2026-07-01']?.['scheduled-1|1'];
  assert(carried?.scheduledMakeup?.originalAbsenceId === 'absence|2026-07-01|scheduled-1|1', 'scheduled makeup originalAbsenceId was not preserved.');
  assert(!(fixtureExtra['2026-07-10'] || []).includes('scheduled-1'), 'scheduled-1 remained in fixture extra-attend after carryover.');
  assert(!Object.prototype.hasOwnProperty.call(fixtureWeekend['2026-07-10'] || {}, 'scheduled-1'), 'scheduled-1 remained in fixture weekend-slots after carryover.');
  assert(diagnostics.mutations.includes('PATCH /api/extra-attend'), 'PATCH /api/extra-attend was not recorded for scheduled carryover cleanup.');
  assert(diagnostics.mutations.includes('POST /api/weekend-slots'), 'POST /api/weekend-slots was not recorded for scheduled carryover cleanup.');
  assert(carried?.state === 'carried', '보강 현황 이월이 원본 결석을 이월 처리하지 않았습니다.');
  assert(carried?.scheduledMakeup?.status === 'cancelled', '보강 현황 이월이 기존 보강 일정을 해제하지 않았습니다.');
  assert(diagnostics.mutations.includes('POST /api/makeup-carryover'), '보강 현황 이월 저장 요청이 없습니다.');
  assert(diagnostics.pageErrors.length === 0, `페이지 오류 발생: ${diagnostics.pageErrors.join('\n')}`);
  await page.locator('.makeup-panel-stack').screenshot({ path: resolve(artifactDir, 'admin-makeup-panel.png') });
  await writeFile(resolve(artifactDir, 'admin-makeup-panel-dom.json'), JSON.stringify({
    panels: await page.locator('.makeup-panel-stack h4').allTextContents(),
    panelLayout,
    labels,
    diagnostics,
    escapeEvidence: {
      mutationsBeforeEscape,
      mutationsAfterEscape,
      apiRequests: escapeApiRequests,
    },
    fixtureRouting: {
      allApiRequestsFulfilledByFixture: diagnostics.apiRequests.every(request => request.fixture === true),
      apiRequests: diagnostics.apiRequests,
    },
    fixtureState: {
      carried: carried ? {
        state: carried.state,
        originalAbsenceId: carried.scheduledMakeup?.originalAbsenceId,
        scheduledStatus: carried.scheduledMakeup?.status,
      } : null,
      extraAttend: fixtureExtra,
      weekendSlots: fixtureWeekend,
    },
  }, null, 2));
  console.log(JSON.stringify({ ok: true, artifactDir, panels: 2, labels, cleanup: 'browser=closing; server=owned-only' }));
} catch (error) {
  console.error(JSON.stringify({ error: String(error?.stack || error), carryover, diagnostics }, null, 2));
  throw error;
} finally {
  await browser?.close();
  if (server) server.kill();
}
