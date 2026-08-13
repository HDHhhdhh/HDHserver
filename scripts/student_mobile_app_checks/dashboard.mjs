import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import vm from 'node:vm';

const root = path.resolve(import.meta.dirname, '..', '..');
const files = Object.freeze({
  html: path.join(root, 'static', 'student.html'),
  css: path.join(root, 'static', 'css', 'student.css'),
  js: path.join(root, 'static', 'js', 'student.js'),
});

function extract(source, startMarker, endMarker, label) {
  const start = source.indexOf(startMarker);
  const end = source.indexOf(endMarker);
  assert.ok(start >= 0 && end > start, `${label} markers must exist`);
  return source.slice(start + startMarker.length, end);
}

function loadDashboardContract(source) {
  const contract = extract(
    source,
    '/* STUDENT_APP_DASHBOARD_START */',
    '/* STUDENT_APP_DASHBOARD_END */',
    'dashboard contract',
  );
  const context = {};
  vm.createContext(context);
  vm.runInContext(`${contract}\nglobalThis.__dashboardExports = { normalizeStudentDashboard, studentDashboardViewModel };`, context, {
    filename: 'static/js/student.js#dashboard',
  });
  return { contract, ...context.__dashboardExports };
}

class FakeDashboardElement {
  constructor() {
    this.hidden = false;
    this.value = 0;
    this.textContent = '';
    this.attributes = new Map();
  }

  setAttribute(name, value) { this.attributes.set(String(name), String(value)); }
  removeAttribute(name) { this.attributes.delete(String(name)); }
}

function loadDashboardRenderer(source, elements) {
  const start = source.indexOf('function renderStudentDashboardDetails(view)');
  const end = source.indexOf('function renderStudentTodayOverview()', start);
  assert.ok(start >= 0 && end > start, 'dashboard DOM renderer must exist');
  const rendererSource = source.slice(start, end);
  const context = { $: id => elements[id] || null };
  vm.createContext(context);
  vm.runInContext(`${rendererSource}\nglobalThis.__renderDashboard = renderStudentDashboardDetails;`, context, {
    filename: 'static/js/student.js#dashboard-renderer',
  });
  return context.__renderDashboard;
}

function dashboardElements() {
  const ids = [
    'studentDashboardDetails',
    'studentCurriculumProgress',
    'studentCurriculumProgressCourse',
    'studentCurriculumProgressPercent',
    'studentCurriculumProgressMeta',
    'studentNextScheduleKind',
    'studentNextScheduleStatus',
    'studentNextScheduleWhen',
    'studentNextScheduleSlots',
  ];
  const elements = Object.fromEntries(ids.map(id => [id, new FakeDashboardElement()]));
  elements.studentDashboardDetails.hidden = true;
  elements.studentCurriculumProgress.hidden = true;
  elements.studentNextScheduleStatus.hidden = true;
  elements.studentNextScheduleSlots.hidden = true;
  return elements;
}

function dashboardFixture(overrides = {}) {
  return {
    enabled: true,
    curriculumProgress: {
      basis: 'curriculum_videos_v1',
      curriculum: '수학 I',
      subCurriculum: '개념',
      completed: 5,
      interrupted: 2,
      total: 10,
      percent: 50,
      state: 'available',
      calculatedAt: '2026-08-09T12:00:00+09:00',
    },
    nextSchedule: {
      date: '2026-08-10',
      kind: 'regular',
      status: 'scheduled',
      startAt: '2026-08-10T13:00:00+09:00',
      timeLabel: '13:00',
      slots: [1],
    },
    homeworkSummary: { count: 2, state: 'assigned' },
    unreadBoardCount: null,
    ...overrides,
  };
}

export async function runChecks() {
  const [html, css, js] = await Promise.all(Object.values(files).map(filename => fs.readFile(filename, 'utf8')));
  const { contract, normalizeStudentDashboard, studentDashboardViewModel } = loadDashboardContract(js);
  const passed = [];
  const check = (name, callback) => { callback(); passed.push(name); };

  check('enabled dashboard projects server progress and a semantic 50 percent label', () => {
    const view = studentDashboardViewModel(dashboardFixture());
    assert.ok(view);
    assert.equal(view.progress.available, true);
    assert.equal(view.progress.courseLabel, '수학 I · 개념');
    assert.equal(view.progress.percent, 50);
    assert.equal(view.progress.percentLabel, '50%');
    assert.equal(view.progress.countLabel, '완료 5 · 중단 2 · 전체 10');
    assert.equal(view.homework.countLabel, '2권');
    assert.equal(view.unreadBoardCount, null);
  });

  check('DOM renderer applies enabled, unavailable, and disabled visibility with text-only output', () => {
    const elements = dashboardElements();
    const render = loadDashboardRenderer(js, elements);
    render(studentDashboardViewModel(dashboardFixture()));
    assert.equal(elements.studentDashboardDetails.hidden, false);
    assert.equal(elements.studentCurriculumProgress.hidden, false);
    assert.equal(elements.studentCurriculumProgress.value, 50);
    assert.equal(elements.studentCurriculumProgress.textContent, '50%');
    assert.equal(elements.studentCurriculumProgress.attributes.get('aria-valuetext'), '50%');
    assert.equal(elements.studentCurriculumProgressCourse.textContent, '수학 I · 개념');
    assert.equal(elements.studentNextScheduleKind.textContent, '정규 수업');
    assert.equal(elements.studentNextScheduleStatus.textContent, '예정');

    render(studentDashboardViewModel(dashboardFixture({
      curriculumProgress: {
        basis: 'curriculum_videos_v1',
        curriculum: '수학 II',
        subCurriculum: '',
        completed: 0,
        interrupted: 0,
        total: 0,
        percent: null,
        state: 'unavailable',
        calculatedAt: '2026-08-09T12:00:00+09:00',
      },
      nextSchedule: null,
      homeworkSummary: { count: 0, state: 'empty' },
    })));
    assert.equal(elements.studentDashboardDetails.hidden, false);
    assert.equal(elements.studentCurriculumProgress.hidden, true);
    assert.equal(elements.studentCurriculumProgressPercent.textContent, '확인 불가');
    assert.equal(elements.studentNextScheduleStatus.hidden, true);
    assert.equal(elements.studentNextScheduleKind.textContent, '예정된 수업 없음');

    render(null);
    assert.equal(elements.studentDashboardDetails.hidden, true);
    assert.equal(elements.studentCurriculumProgress.hidden, true);
    assert.equal(elements.studentCurriculumProgress.value, 0);
    assert.equal(elements.studentCurriculumProgress.attributes.has('aria-valuetext'), false);
    for (const element of Object.values(elements)) {
      for (const [name, value] of element.attributes) {
        assert.doesNotMatch(`${name}=${value}`, /(?:sid|csrf|token|url|https?:|\/\/)/i);
      }
    }
  });

  check('disabled, absent, and malformed dashboards preserve the legacy path', () => {
    assert.equal(studentDashboardViewModel(null), null);
    assert.equal(studentDashboardViewModel({}), null);
    assert.equal(studentDashboardViewModel(dashboardFixture({ enabled: false })), null);
    assert.equal(studentDashboardViewModel(dashboardFixture({ homeworkSummary: { count: 3, state: 'empty' } })), null);
    assert.equal(studentDashboardViewModel(dashboardFixture({ curriculumProgress: { state: 'unknown' } })), null);
  });

  check('malformed authoritative fields fail closed instead of displaying inferred values', () => {
    const progress = dashboardFixture().curriculumProgress;
    const schedule = dashboardFixture().nextSchedule;
    assert.equal(studentDashboardViewModel(dashboardFixture({
      curriculumProgress: { ...progress, basis: 'legacy_progress' },
    })), null, 'unexpected progress basis must fail closed');
    assert.equal(studentDashboardViewModel(dashboardFixture({
      curriculumProgress: { ...progress, completed: 0, interrupted: 0, total: 0, percent: 0 },
    })), null, 'available progress cannot use an empty denominator');
    assert.equal(studentDashboardViewModel(dashboardFixture({
      curriculumProgress: { ...progress, percent: 49 },
    })), null, 'server percentage must match rounded completed/total');
    assert.equal(studentDashboardViewModel(dashboardFixture({
      homeworkSummary: { count: 0, state: 'assigned' },
    })), null, 'assigned homework requires a positive count');
    assert.equal(studentDashboardViewModel(dashboardFixture({
      nextSchedule: { ...schedule, slots: [1, 1] },
    })), null, 'schedule slots cannot repeat');
    assert.equal(studentDashboardViewModel(dashboardFixture({
      nextSchedule: { ...schedule, slots: [4] },
    })), null, 'schedule slots stay within 1..3');
    assert.equal(studentDashboardViewModel(dashboardFixture({
      nextSchedule: { ...schedule, slots: [1, 2, 3, 1] },
    })), null, 'schedule slots are capped at three values');
    assert.equal(studentDashboardViewModel(dashboardFixture({
      nextSchedule: { ...schedule, date: '2026-02-31' },
    })), null, 'impossible calendar dates must fail closed');
  });

  check('unavailable progress is explicit and does not invent a percentage', () => {
    const view = studentDashboardViewModel(dashboardFixture({
      curriculumProgress: {
        basis: 'curriculum_videos_v1',
        curriculum: '수학 II',
        subCurriculum: '',
        completed: 0,
        interrupted: 0,
        total: 0,
        percent: null,
        state: 'unavailable',
        calculatedAt: '2026-08-09T12:00:00+09:00',
      },
      nextSchedule: null,
      homeworkSummary: { count: 0, state: 'empty' },
      unreadBoardCount: 0,
    }));
    assert.ok(view);
    assert.equal(view.progress.available, false);
    assert.equal(view.progress.percent, null);
    assert.equal(view.progress.percentLabel, '확인 불가');
    assert.match(view.progress.countLabel, /확인할 수 없습니다/);
    assert.equal(view.schedule.available, false);
    assert.equal(view.schedule.kindLabel, '예정된 수업 없음');
    assert.equal(view.homework.countLabel, '없음');
    assert.equal(view.unreadBoardCount, 0);
  });

  check('absence and makeup schedules use explicit Korean kind and status labels', () => {
    const absence = studentDashboardViewModel(dashboardFixture({
      nextSchedule: {
        date: '2026-08-11',
        kind: 'absence',
        status: 'cancelled',
        startAt: null,
        timeLabel: '',
        slots: [],
      },
    }));
    assert.equal(absence.schedule.kindLabel, '결석');
    assert.equal(absence.schedule.statusLabel, '취소');
    assert.equal(absence.schedule.whenLabel, '8월 11일');
    assert.equal(absence.schedule.slotsLabel, '');

    const makeup = studentDashboardViewModel(dashboardFixture({
      nextSchedule: {
        date: '2026-08-12',
        kind: 'makeup',
        status: 'scheduled',
        startAt: '2026-08-12T18:30:00+09:00',
        timeLabel: '18:30',
        slots: [2],
      },
    }));
    assert.equal(makeup.schedule.kindLabel, '보강');
    assert.equal(makeup.schedule.statusLabel, '예정');
    assert.equal(makeup.schedule.whenLabel, '8월 12일 · 18:30');
    assert.equal(makeup.schedule.slotsLabel, '2교시');
  });

  check('all schedule kinds and states have visible text rather than color-only meaning', () => {
    for (const [kind, label] of Object.entries({ regular: '정규 수업', extra: '추가 수업', makeup: '보강', absence: '결석' })) {
      const status = kind === 'absence' ? 'cancelled' : 'scheduled';
      const view = studentDashboardViewModel(dashboardFixture({
        nextSchedule: { date: '2026-08-13', kind, status, startAt: null, timeLabel: '', slots: [] },
      }));
      assert.equal(view.schedule.kindLabel, label);
      assert.ok(view.schedule.statusLabel);
    }
  });

  check('projection excludes SID, CSRF, URLs, deadlines, and browser-derived state', () => {
    const hostile = dashboardFixture({
      sid: 'sid-secret-value',
      csrfToken: 'csrf-secret-value',
      url: 'https://private.example/student',
      dueDate: '2026-08-31',
      curriculumProgress: {
        ...dashboardFixture().curriculumProgress,
        curriculum: '//private.example/course',
      },
    });
    const projected = JSON.stringify(normalizeStudentDashboard(hostile));
    assert.doesNotMatch(projected, /sid-secret|csrf-secret|private\.example|2026-08-31/);
    assert.doesNotMatch(contract, /\b(?:localStorage|sessionStorage|indexedDB|fetch)\b/);
    assert.doesNotMatch(contract, /\b(?:dueDate|deadline)\b|마감|기한/);
    assert.doesNotMatch(contract, /new\s+Date\s*\(/);
  });

  check('bootstrap projection is additive and local fallback stays transparent', () => {
    assert.match(js, /dashboard:\s*b\.dashboard\s*&&\s*typeof b\.dashboard === ['"]object['"]\s*\?\s*b\.dashboard\s*:\s*null/);
    assert.match(js, /studentDashboardCache\s*=\s*bootstrapMeta\?\.dashboard\s*\|\|\s*null/);
    assert.match(js, /reviewVideosMalformed:\s*false,[\s\S]{0,160}dashboard:\s*null/);
    const renderStart = js.indexOf('function renderStudentTodayOverview()');
    const renderEnd = js.indexOf("document.addEventListener('student-app:announcement-summary'", renderStart);
    assert.ok(renderStart >= 0 && renderEnd > renderStart);
    const renderScope = js.slice(renderStart, renderEnd);
    assert.match(renderScope, /if\s*\(!STUDENT_APP_PUBLIC_MODE\)\s*return/);
    assert.match(renderScope, /studentDashboardViewModel\(studentDashboardCache\)/);
    assert.match(renderScope, /dashboardView\?\.homework\.countLabel/);
    assert.match(renderScope, /dashboardView\?\.unreadBoardCount\s*\?\?\s*announcementPendingCount/);
  });

  check('dashboard DOM writes are text-only and never expose credentials or links', () => {
    const renderStart = js.indexOf('function renderStudentDashboardDetails(view)');
    const renderEnd = js.indexOf('function renderStudentTodayOverview()', renderStart);
    assert.ok(renderStart >= 0 && renderEnd > renderStart);
    const renderScope = js.slice(renderStart, renderEnd);
    assert.match(renderScope, /\.textContent\s*=/);
    assert.match(renderScope, /progressBar\.value\s*=/);
    assert.doesNotMatch(renderScope, /innerHTML|outerHTML|insertAdjacentHTML|\.href\s*=|\.src\s*=|\.dataset\b/);
    assert.doesNotMatch(renderScope, /\b(?:sid|csrf|token|url|localStorage|sessionStorage|fetch)\b/i);
  });

  check('HTML extends the existing hidden overview with semantic progress and schedule cells', () => {
    assert.match(html, /id=["']studentTodayOverview["'][^>]*hidden/i);
    assert.match(html, /id=["']studentDashboardDetails["'][^>]*hidden/i);
    assert.match(html, /<progress\b[^>]*id=["']studentCurriculumProgress["'][^>]*max=["']100["'][^>]*aria-labelledby=["']studentCurriculumProgressTitle["']/is);
    assert.match(html, /id=["']studentCurriculumProgressMeta["']/i);
    assert.match(html, /id=["']studentNextScheduleKind["']/i);
    assert.match(html, /id=["']studentNextScheduleStatus["'][^>]*hidden/i);
    assert.doesNotMatch(html, /data-(?:sid|csrf|token|url)=/i);
  });

  check('CSS remains public-scoped, responsive, dark-token based, and motion safe', () => {
    const dashboardCssStart = css.indexOf('body.student-page.student-app-mobile-surface .student-dashboard-details');
    const dashboardCssEnd = css.indexOf('body.student-page.student-app-mobile-surface .student-today-actions {', dashboardCssStart);
    assert.ok(dashboardCssStart >= 0 && dashboardCssEnd > dashboardCssStart);
    const dashboardCss = css.slice(dashboardCssStart, dashboardCssEnd);
    assert.match(dashboardCss, /grid-template-columns:\s*repeat\(2,\s*minmax\(0,\s*1fr\)\)/);
    assert.match(dashboardCss, /min-width:\s*0/);
    assert.match(dashboardCss, /max-width:\s*100%/);
    assert.match(dashboardCss, /overflow-wrap:\s*anywhere/);
    assert.match(dashboardCss, /var\(--stu-(?:card-soft|line|text|muted|accent|accent-2)\)/);
    assert.doesNotMatch(dashboardCss, /#[0-9a-f]{3,8}\b/i);
    assert.match(css, /@media\s*\(max-width:\s*22rem\)[\s\S]*\.student-dashboard-details,[\s\S]*grid-template-columns:\s*minmax\(0,\s*1fr\)/);
    assert.match(css, /\.student-today-actions\s+:is\(a,\s*button\)\s*\{[^}]*min-height:\s*44px/s);
    assert.match(css, /student-app-mobile-surface\s*\{[^}]*safe-area-inset-top[^}]*safe-area-inset-bottom/s);
    assert.match(css, /@media\s*\(prefers-reduced-motion:\s*reduce\)/);
    assert.match(css, /body\.student-page\.dark\s*\{[^}]*--stu-card-soft:[^}]*--stu-text:[^}]*--stu-muted:/s);
    assert.match(css, /\.student-shell\s*\{[^}]*width:\s*min\(100%,\s*32rem\)/s);
  });

  return Object.freeze({
    suite: 'student-mobile-app-dashboard',
    checks: passed.length,
    checksPassed: Object.freeze(passed.slice()),
    files: Object.freeze(Object.fromEntries(Object.entries(files).map(([key, filename]) => [key, path.relative(root, filename)]))),
  });
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  try {
    const result = await runChecks();
    console.log(`student-mobile-app dashboard: ${result.checks} assertions passed`);
  } catch (error) {
    console.error(`student-mobile-app dashboard: ${error instanceof Error ? error.message : String(error)}`);
    process.exitCode = 1;
  }
}
