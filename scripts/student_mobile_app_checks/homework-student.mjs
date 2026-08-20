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
  const end = source.indexOf(endMarker, start + startMarker.length);
  assert.ok(start >= 0 && end > start, `${label} markers must exist`);
  return source.slice(start + startMarker.length, end);
}

function loadContract(source) {
  const contract = extract(
    source,
    '/* STUDENT_APP_HOMEWORK_START */',
    '/* STUDENT_APP_HOMEWORK_END */',
    'student homework contract',
  );
  const context = { URLSearchParams, Date };
  vm.createContext(context);
  vm.runInContext(`${contract}\nglobalThis.__homeworkExports = {
    studentHomeworkOpaqueId,
    normalizeStudentHomeworkPayload,
    studentHomeworkDeepLink,
    studentHomeworkViewModel,
  };`, context, { filename: 'static/js/student.js#homework' });
  return { contract, ...context.__homeworkExports };
}

class FakeClassList {
  constructor(owner) {
    this.owner = owner;
    this.values = new Set();
  }

  add(...values) {
    values.forEach(value => this.values.add(String(value)));
    this.owner.className = [...this.values].join(' ');
  }

  contains(value) { return this.values.has(String(value)); }
}

class FakeElement {
  constructor(tagName = 'div') {
    this.tagName = String(tagName).toUpperCase();
    this.children = [];
    this.hidden = false;
    this.disabled = false;
    this.tabIndex = 0;
    this.className = '';
    this.attributes = new Map();
    this.classList = new FakeClassList(this);
    this.listeners = new Map();
    this.focused = false;
    this.scrolled = false;
    this._textContent = '';
  }

  get textContent() {
    return this._textContent + this.children.map(child => child.textContent).join('');
  }

  set textContent(value) {
    this._textContent = String(value ?? '');
    this.children = [];
  }

  append(...children) { children.forEach(child => this.appendChild(child)); }
  appendChild(child) { this.children.push(child); return child; }
  setAttribute(name, value) { this.attributes.set(String(name), String(value)); }
  addEventListener(type, callback) { this.listeners.set(String(type), callback); }
  focus() { this.focused = true; }
  scrollIntoView() { this.scrolled = true; }
}

function fakeElements() {
  return Object.fromEntries([
    'studentHomeworkPanel',
    'studentHomeworkTitle',
    'studentHomeworkAssignments',
    'studentHomeworkBooks',
    'studentHomeworkStatus',
    'studentHomeworkRetry',
  ].map(id => [id, new FakeElement(id === 'studentHomeworkAssignments' || id === 'studentHomeworkBooks' ? 'ul' : 'div')]));
}

function loadDomScope(source, options = {}) {
  const start = source.indexOf('function restoreLegacyHomeworkFallback()');
  const end = source.indexOf('function assignedTestAnswerUrl(', start);
  assert.ok(start >= 0 && end > start, 'canonical homework DOM scope must exist');
  const domSource = source.slice(start, end);
  const elements = options.elements || fakeElements();
  const calls = { request: [], fallback: 0, overview: 0, recovery: 0 };
  const context = {
    Object,
    Map,
    Promise,
    console,
    canonicalHomeworkState: null,
    canonicalHomeworkLoading: false,
    canonicalHomeworkElements: new Map(),
    STUDENT_APP_PUBLIC_MODE: options.publicMode !== false,
    location: { search: options.search || '' },
    document: { createElement: tagName => new FakeElement(tagName) },
    requestAnimationFrame: callback => callback(),
    $: id => elements[id] || null,
    renderHomeworkBooks: () => { calls.fallback += 1; },
    renderStudentTodayOverview: () => { calls.overview += 1; },
    normalizeStudentHomeworkPayload: options.normalizeStudentHomeworkPayload,
    studentHomeworkViewModel: options.studentHomeworkViewModel,
    studentHomeworkDeepLink: options.studentHomeworkDeepLink,
    StudentAppSessionError: class StudentAppSessionError extends Error {
      constructor(code, status) { super(code); this.code = code; this.status = status; }
    },
    handleStudentAppSessionFailure: error => {
      if (error?.status === 401 || error?.status === 403) calls.recovery += 1;
      return error?.status === 401 || error?.status === 403;
    },
    studentAppRequest: async (url, init) => {
      calls.request.push({ url, init });
      return options.response;
    },
  };
  vm.createContext(context);
  vm.runInContext(`${domSource}\nglobalThis.__homeworkDomExports = {
    restoreLegacyHomeworkFallback,
    renderCanonicalHomework,
    showCanonicalHomeworkError,
    focusCanonicalHomeworkDeepLink,
    loadCanonicalStudentHomework,
  };`, context, { filename: 'static/js/student.js#homework-dom' });
  return { domSource, elements, calls, context, ...context.__homeworkDomExports };
}

function response(status, payload = null) {
  return {
    status,
    ok: status >= 200 && status < 300,
    json: async () => payload,
  };
}

function item(overrides = {}) {
  return {
    id: 'homework-1',
    title: '함수 문제 풀이',
    book: '개념서',
    scope: '42쪽부터 45쪽',
    assignedAt: '2026-08-08T12:00:00+09:00',
    dueAt: '2026-08-12T18:00:00+09:00',
    status: 'assigned',
    completedAt: null,
    legacy: false,
    notificationEligible: true,
    notificationEventIds: ['evt_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA', 'evt_BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB'],
    ...overrides,
  };
}

export async function runChecks() {
  const [html, css, js] = await Promise.all(Object.values(files).map(filename => fs.readFile(filename, 'utf8')));
  const contractExports = loadContract(js);
  const {
    contract,
    studentHomeworkOpaqueId,
    normalizeStudentHomeworkPayload,
    studentHomeworkDeepLink,
    studentHomeworkViewModel,
  } = contractExports;
  const now = Date.parse('2026-08-09T12:00:00+09:00');
  const passed = [];
  const check = (name, callback) => { callback(); passed.push(name); };
  const checkAsync = async (name, callback) => { await callback(); passed.push(name); };

  check('strict projection sorts due timestamps chronologically and keeps undated legacy rows last', () => {
    const payload = normalizeStudentHomeworkPayload({
      items: [
        item({ id: 'undated', dueAt: null, legacy: true, notificationEligible: false }),
        item({ id: 'future', dueAt: '2026-08-12T18:00:00+09:00' }),
        item({ id: 'overdue', dueAt: '2026-08-08T18:00:00+09:00', notificationEligible: false }),
      ],
      nextCursor: 'cursor_2-next',
    }, now);
    assert.ok(payload);
    assert.deepEqual(Array.from(payload.items, row => row.id), ['overdue', 'future', 'undated']);
    assert.equal(payload.nextCursor, 'cursor_2-next');
    assert.deepEqual(Object.keys(payload.items[0]), [
      'id', 'title', 'book', 'scope', 'assignedAt', 'dueAt', 'status', 'completedAt', 'legacy', 'notificationEligible',
      'notificationEventIds',
    ]);
  });

  check('overdue is derived from assigned dueAt while canonical status remains constrained', () => {
    const overdue = normalizeStudentHomeworkPayload({
      items: [item({ dueAt: '2026-08-09T11:59:59+09:00', notificationEligible: false })],
      nextCursor: null,
    }, now);
    assert.equal(overdue.items[0].status, 'assigned');
    const view = studentHomeworkViewModel(overdue.items[0], now);
    assert.equal(view.status, 'overdue');
    assert.equal(view.statusLabel, '기한 지남');
    assert.match(view.dueLabel, /^기한 8월 9일 11:59$/);
    assert.equal(normalizeStudentHomeworkPayload({
      items: [item({ status: 'overdue', notificationEligible: false })],
      nextCursor: null,
    }, now), null);
  });

  check('completed timestamps and notification eligibility fail closed', () => {
    const completed = normalizeStudentHomeworkPayload({
      items: [item({
        status: 'completed',
        completedAt: '2026-08-09T11:00:00+09:00',
        notificationEligible: false,
      })],
      nextCursor: null,
    }, now);
    assert.ok(completed);
    assert.equal(studentHomeworkViewModel(completed.items[0], now).statusLabel, '완료');
    assert.equal(normalizeStudentHomeworkPayload({
      items: [item({ status: 'completed', completedAt: null, notificationEligible: false })],
      nextCursor: null,
    }, now), null);
    assert.equal(normalizeStudentHomeworkPayload({
      items: [item({ dueAt: null, notificationEligible: true })],
      nextCursor: null,
    }, now), null);
    assert.equal(normalizeStudentHomeworkPayload({
      items: [item({ dueAt: '2026-08-08T18:00:00+09:00', notificationEligible: true })],
      nextCursor: null,
    }, now), null);
  });

  check('malformed identifiers, timestamps, booleans, duplicate IDs, and oversized pages are rejected', () => {
    const wrap = rows => ({ items: rows, nextCursor: null });
    assert.equal(studentHomeworkOpaqueId('https://private.example'), '');
    assert.equal(studentHomeworkOpaqueId('../student'), '');
    assert.equal(normalizeStudentHomeworkPayload(wrap([item({ id: 'bad/id' })]), now), null);
    assert.equal(normalizeStudentHomeworkPayload(wrap([item({ assignedAt: '2026-02-31T12:00:00+09:00' })]), now), null);
    assert.equal(normalizeStudentHomeworkPayload(wrap([item({ legacy: 'false' })]), now), null);
    assert.equal(normalizeStudentHomeworkPayload(wrap([item({ notificationEventIds: ['../secret'] })]), now), null);
    assert.equal(normalizeStudentHomeworkPayload(wrap([item({ notificationEventIds: [
      'evt_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA', 'evt_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA',
    ] })]), now), null);
    assert.equal(normalizeStudentHomeworkPayload(wrap([item(), item()]), now), null);
    assert.equal(normalizeStudentHomeworkPayload({ items: Array.from({ length: 51 }, (_, index) => item({ id: `h-${index}` })), nextCursor: null }, now), null);
    assert.equal(normalizeStudentHomeworkPayload({ items: [], nextCursor: 'https://cursor.example' }, now), null);
    assert.equal(normalizeStudentHomeworkPayload({ items: [] }, now), null);
    const missingScope = item();
    delete missingScope.scope;
    assert.equal(normalizeStudentHomeworkPayload(wrap([missingScope]), now), null);
  });

  check('deep links accept one strict opaque item only and never treat it as URL authority', () => {
    assert.equal(studentHomeworkDeepLink('?view=homework&item=homework-1'), 'homework-1');
    assert.equal(studentHomeworkDeepLink('?view=homework&item=https%3A%2F%2Fevil.example'), '');
    assert.equal(studentHomeworkDeepLink('?view=homework&item=..%2Fsecret'), '');
    assert.equal(studentHomeworkDeepLink('?view=homework&item=one&item=two'), '');
    assert.equal(studentHomeworkDeepLink('?view=board&item=homework-1'), '');
  });

  check('malicious display text is rendered through textContent without HTML or datasets', () => {
    const payload = normalizeStudentHomeworkPayload({
      items: [item({ title: '<img src=x onerror=alert(1)>', book: '<b>교재</b>', scope: '<script>x</script>' })],
      nextCursor: null,
    }, now);
    const loaded = loadDomScope(js, { ...contractExports, response: response(200, {}) });
    loaded.renderCanonicalHomework(payload);
    const card = loaded.elements.studentHomeworkAssignments.children[0];
    assert.equal(card.children[0].children[0].textContent, '<img src=x onerror=alert(1)>');
    assert.match(card.textContent, /<b>교재<\/b>/);
    assert.equal(card.attributes.has('data-homework-item'), false);
    assert.doesNotMatch(loaded.domSource, /innerHTML|outerHTML|insertAdjacentHTML|\.dataset\b|\.href\s*=|\.src\s*=/);
  });

  await checkAsync('200 response renders canonical cards, overrides fallback, and focuses a valid deep link', async () => {
    const raw = {
      items: [item({ notificationEligible: false })],
      nextCursor: null,
    };
    const normalized = normalizeStudentHomeworkPayload(raw, Date.now());
    assert.ok(normalized);
    const loaded = loadDomScope(js, {
      ...contractExports,
      search: '?view=homework&item=evt_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA',
      response: response(200, raw),
    });
    await loaded.loadCanonicalStudentHomework();
    assert.equal(loaded.calls.request.length, 1);
    assert.equal(loaded.calls.request[0].url, '/api/mobile/student/homework?status=open');
    assert.equal(loaded.calls.request[0].init.cache, 'no-store');
    assert.equal(Object.keys(loaded.calls.request[0].init).length, 1);
    assert.equal(loaded.elements.studentHomeworkPanel.hidden, false);
    assert.equal(loaded.elements.studentHomeworkBooks.hidden, true);
    assert.equal(loaded.elements.studentHomeworkAssignments.hidden, false);
    const card = loaded.elements.studentHomeworkAssignments.children[0];
    assert.equal(card.focused, true);
    assert.equal(card.scrolled, true);
    assert.equal(card.attributes.get('aria-current'), 'true');
  });

  await checkAsync('404 restores the untouched legacy view without a canonical error', async () => {
    const loaded = loadDomScope(js, { ...contractExports, response: response(404) });
    loaded.elements.studentHomeworkAssignments.hidden = false;
    loaded.elements.studentHomeworkBooks.hidden = true;
    await loaded.loadCanonicalStudentHomework();
    assert.equal(loaded.calls.fallback, 1);
    assert.equal(loaded.elements.studentHomeworkAssignments.hidden, true);
    assert.equal(loaded.elements.studentHomeworkBooks.hidden, false);
    assert.equal(loaded.elements.studentHomeworkStatus.hidden, true);
    assert.equal(loaded.elements.studentHomeworkRetry.hidden, true);
    assert.equal(loaded.elements.studentHomeworkTitle.textContent, '오늘 숙제');
  });

  await checkAsync('503 and malformed 200 keep the legacy display with a generic retry path', async () => {
    for (const failingResponse of [response(503), response(200, { internal: 'database secret' })]) {
      const loaded = loadDomScope(js, { ...contractExports, response: failingResponse });
      loaded.elements.studentHomeworkBooks.hidden = false;
      await loaded.loadCanonicalStudentHomework();
      assert.equal(loaded.elements.studentHomeworkBooks.hidden, false);
      assert.equal(loaded.elements.studentHomeworkPanel.hidden, false);
      assert.equal(loaded.elements.studentHomeworkStatus.hidden, false);
      assert.equal(loaded.elements.studentHomeworkRetry.hidden, false);
      assert.equal(loaded.elements.studentHomeworkStatus.textContent, '숙제 목록을 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.');
      assert.doesNotMatch(loaded.elements.studentHomeworkStatus.textContent, /database|secret|sqlite|trace/i);
    }
  });

  await checkAsync('401 and 403 use existing session recovery while nonpublic mode performs no request or DOM mutation', async () => {
    for (const status of [401, 403]) {
      const loaded = loadDomScope(js, { ...contractExports, response: response(status) });
      await loaded.loadCanonicalStudentHomework();
      assert.equal(loaded.calls.recovery, 1);
      assert.equal(loaded.elements.studentHomeworkStatus.textContent, '');
    }
    const local = loadDomScope(js, { ...contractExports, publicMode: false, response: response(200, { items: [], nextCursor: null }) });
    local.elements.studentHomeworkPanel.hidden = true;
    await local.loadCanonicalStudentHomework();
    assert.equal(local.calls.request.length, 0);
    assert.equal(local.elements.studentHomeworkPanel.hidden, true);
  });

  check('empty canonical result is explicit and overview gives canonical count priority', () => {
    const payload = normalizeStudentHomeworkPayload({ items: [], nextCursor: null }, now);
    const loaded = loadDomScope(js, { ...contractExports, response: response(200, {}) });
    loaded.renderCanonicalHomework(payload);
    assert.equal(loaded.elements.studentHomeworkAssignments.children.length, 1);
    assert.equal(loaded.elements.studentHomeworkAssignments.children[0].textContent, '등록된 숙제가 없습니다.');
    const overviewStart = js.indexOf('function renderStudentTodayOverview()');
    const overviewEnd = js.indexOf("document.addEventListener('student-app:announcement-summary'", overviewStart);
    const overview = js.slice(overviewStart, overviewEnd);
    assert.match(overview, /canonicalHomeworkCount\s*==\s*null[\s\S]*dashboardView\?\.homework\.countLabel/);
    assert.match(overview, /`\$\{canonicalHomeworkCount\}개`/);
    assert.match(overview, /등록된 숙제 없음/);
  });

  check('request contract is public-only, cookie-session based, and carries no SID, body, storage, or secret', () => {
    const start = js.indexOf('async function loadCanonicalStudentHomework()');
    const end = js.indexOf('function assignedTestAnswerUrl(', start);
    const loadScope = js.slice(start, end);
    assert.match(loadScope, /if\s*\(!STUDENT_APP_PUBLIC_MODE\s*\|\|\s*canonicalHomeworkLoading\)\s*return/);
    assert.match(loadScope, /studentAppRequest\(['"]\/api\/mobile\/student\/homework\?status=open['"],\s*\{\s*cache:\s*['"]no-store['"]\s*\}\)/);
    assert.doesNotMatch(loadScope, /(?:[?&](?:sid|studentSid)=|body\s*:|localStorage|sessionStorage|csrf|authorization|bearer)/i);
    assert.match(js, /if\s*\(STUDENT_APP_PUBLIC_MODE\)\s*void\s+loadCanonicalStudentHomework\(\)/);
    assert.doesNotMatch(contract, /\b(?:fetch|localStorage|sessionStorage|indexedDB|document|location)\b/);
  });

  check('HTML and CSS extend the panel with public-scoped responsive, dark-token, safe-area, and motion-safe controls', () => {
    assert.match(html, /student\.css\?v=20260809-homework-r1/);
    assert.match(html, /student\.js\?v=20260809-homework-r1/);
    assert.match(html, /id=["']studentHomeworkAssignments["'][^>]*aria-label=["']숙제 목록["'][^>]*hidden/i);
    assert.match(html, /id=["']studentHomeworkStatus["'][^>]*role=["']status["'][^>]*aria-live=["']polite["'][^>]*hidden/i);
    assert.match(html, /id=["']studentHomeworkRetry["'][^>]*hidden/i);
    assert.doesNotMatch(html, /data-(?:sid|csrf|token|url|homework-item)=/i);
    const cssStart = css.indexOf('body.student-page.student-app-mobile-surface .student-homework-heading');
    const cssEnd = css.indexOf('body.student-page.dark.student-app-mobile-surface', cssStart);
    assert.ok(cssStart >= 0 && cssEnd > cssStart);
    const homeworkCss = css.slice(cssStart, cssEnd);
    assert.match(homeworkCss, /\.student-homework-list\s*\{[^}]*width:\s*100%[^}]*min-width:\s*0[^}]*max-width:\s*100%/s);
    assert.match(homeworkCss, /\.student-homework-card,[\s\S]*box-sizing:\s*border-box[\s\S]*min-width:\s*0[\s\S]*max-width:\s*100%/);
    assert.match(homeworkCss, /\.student-homework-retry\s*\{[^}]*min-height:\s*44px/s);
    assert.match(homeworkCss, /overflow-wrap:\s*anywhere/);
    assert.match(homeworkCss, /safe-area-inset-top/);
    assert.doesNotMatch(homeworkCss, /#[0-9a-f]{3,8}\b/i);
    assert.match(css, /@media\s*\(max-width:\s*22rem\)[\s\S]*\.student-homework-card-heading\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)/s);
    assert.match(css, /@media\s*\(prefers-reduced-motion:\s*reduce\)/);
    assert.match(css, /body\.student-page\.dark\s*\{[^}]*--stu-card-soft:[^}]*--stu-text:[^}]*--stu-muted:/s);
  });

  return Object.freeze({
    suite: 'student-mobile-app-homework-student',
    checks: passed.length,
    checksPassed: Object.freeze(passed.slice()),
    files: Object.freeze(Object.fromEntries(Object.entries(files).map(([key, filename]) => [key, path.relative(root, filename)]))),
  });
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  try {
    const result = await runChecks();
    console.log(`student-mobile-app homework student: ${result.checks} assertions passed`);
  } catch (error) {
    console.error(`student-mobile-app homework student: ${error instanceof Error ? error.message : String(error)}`);
    process.exitCode = 1;
  }
}
