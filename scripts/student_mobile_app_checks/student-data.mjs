import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import vm from 'node:vm';

const root = path.resolve(import.meta.dirname, '..', '..');
const studentJsPath = path.join(root, 'static', 'js', 'student.js');
const artifactPath = process.env.STUDENT_APP_STUDENT_DATA_EVIDENCE ?? path.join(
  root,
  '.omo',
  'evidence',
  'student-mobile-app-v2',
  'task-9',
  'student-data-check.json',
);

function loadPublicSessionContract(source) {
  const startMarker = '/* STUDENT_APP_PUBLIC_SESSION_START */';
  const endMarker = '/* STUDENT_APP_PUBLIC_SESSION_END */';
  const start = source.indexOf(startMarker);
  const end = source.indexOf(endMarker);
  assert.ok(start >= 0 && end > start, 'public-session contract markers must exist');
  const contract = source.slice(start + startMarker.length, end);
  const context = { console, URL, URLSearchParams, Headers, Request, Response };
  vm.createContext(context);
  vm.runInContext(`${contract}\nglobalThis.__studentDataExports = { StudentAppSessionError, studentAppIsPublicMode, createStudentAppSessionAdapter, loadPublicStudentBootstrap };`, context, {
    filename: 'static/js/student.js#public-session',
  });
  return context.__studentDataExports;
}

function jsonResponse(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function requestRecord(input, init = {}) {
  const headers = new Headers(init.headers || {});
  return {
    url: typeof input === 'string' ? input : input.url,
    method: String(init.method || 'GET').toUpperCase(),
    credentials: init.credentials,
    authorization: headers.get('Authorization'),
    csrf: headers.get('X-CSRF-Token'),
    body: typeof init.body === 'string' ? init.body : '',
  };
}

export async function runChecks() {
  const source = await fs.readFile(studentJsPath, 'utf8');
  const { studentAppIsPublicMode, createStudentAppSessionAdapter, loadPublicStudentBootstrap } = loadPublicSessionContract(source);
  const passed = [];
  const check = (name, callback) => { callback(); passed.push(name); };
  const checkAsync = async (name, callback) => { await callback(); passed.push(name); };

  check('public-mode classification is limited to exact app hosts', () => {
    assert.equal(studentAppIsPublicMode({ protocol: 'https:', hostname: 'app.5a-math.com' }), true);
    assert.equal(studentAppIsPublicMode({ protocol: 'https:', hostname: 'dev-app.5a-math.com' }), true);
    assert.equal(studentAppIsPublicMode({ protocol: 'https:', hostname: '5a-math.com' }), false);
    assert.equal(studentAppIsPublicMode({ protocol: 'https:', hostname: 'student-canary.example' }), false);
    assert.equal(studentAppIsPublicMode({ protocol: 'http:', hostname: 'app.5a-math.com' }), false);
    assert.equal(studentAppIsPublicMode({ protocol: 'https:', hostname: 'localhost' }), false);
    assert.equal(studentAppIsPublicMode({ protocol: 'https:', hostname: '192.168.0.8' }), false);
  });

  await checkAsync('public load uses session SID and one authoritative bootstrap payload', async () => {
    const calls = [];
    const assignedTests = [{ id: 'test-1', answerUrl: 'https://drive.example/answer' }];
    const fetchImpl = async (input, init) => {
      calls.push(requestRecord(input, init));
      if (input === '/api/mobile/auth/session') {
        return jsonResponse({ state: 'ready', sid: 'sid-session', csrfToken: 'csrf-one' });
      }
      if (String(input).startsWith('/api/student/bootstrap?')) {
        return jsonResponse({
          student: { id: 'sid-session', name: '학생' },
          assignedTests,
          watch: { ok: true, sid: 'sid-session', date: '2026-08-08', watch: { mid1: { last: 10 } } },
        });
      }
      throw new Error(`unexpected request ${input}`);
    };
    const adapter = createStudentAppSessionAdapter({ fetchImpl });
    const loaded = await loadPublicStudentBootstrap({ adapter, pageSid: 'sid-session', date: '2026-08-08' });
    assert.deepEqual(calls.map(call => call.url), [
      '/api/mobile/auth/session',
      '/api/student/bootstrap?sid=sid-session&date=2026-08-08',
    ]);
    assert.equal(calls.every(call => call.credentials === 'same-origin'), true);
    assert.equal(calls.every(call => call.authorization === null), true);
    assert.equal(loaded.activeSid, 'sid-session');
    assert.equal(loaded.bootstrap.assignedTests[0].answerUrl, assignedTests[0].answerUrl);
    assert.equal(loaded.watch.watch.mid1.last, 10);
  });

  await checkAsync('URL SID mismatch stops before bootstrap', async () => {
    const calls = [];
    const adapter = createStudentAppSessionAdapter({
      fetchImpl: async (input, init) => {
        calls.push(requestRecord(input, init));
        return jsonResponse({ state: 'ready', sid: 'sid-session', csrfToken: 'csrf-one' });
      },
    });
    await assert.rejects(
      loadPublicStudentBootstrap({ adapter, pageSid: 'sid-forged', date: '2026-08-08' }),
      error => error?.code === 'sid_rotated' && error?.activeSid === 'sid-session',
    );
    assert.deepEqual(calls.map(call => call.url), ['/api/mobile/auth/session']);
  });

  await checkAsync('bootstrap HTTP failure never calls the seven-endpoint fallback', async () => {
    const calls = [];
    const adapter = createStudentAppSessionAdapter({
      fetchImpl: async (input, init) => {
        calls.push(requestRecord(input, init));
        return input === '/api/mobile/auth/session'
          ? jsonResponse({ state: 'ready', sid: 'sid-session', csrfToken: 'csrf-one' })
          : jsonResponse({ code: 'server_error' }, 500);
      },
    });
    await assert.rejects(
      loadPublicStudentBootstrap({ adapter, pageSid: 'sid-session', date: '2026-08-08' }),
      error => error?.code === 'bootstrap_failed' && error?.status === 500,
    );
    assert.equal(calls.length, 2);
    assert.equal(calls.some(call => /\/api\/(?:students|videos|updates|materials|mat-assign|absent|logs|watch\/latest)/.test(call.url)), false);
  });

  await checkAsync('bootstrap network failure remains retryable without legacy calls', async () => {
    const calls = [];
    const adapter = createStudentAppSessionAdapter({
      fetchImpl: async (input, init) => {
        calls.push(requestRecord(input, init));
        if (input === '/api/mobile/auth/session') return jsonResponse({ state: 'ready', sid: 'sid-session', csrfToken: 'csrf-one' });
        throw new Error('timeout');
      },
    });
    await assert.rejects(
      loadPublicStudentBootstrap({ adapter, pageSid: 'sid-session', date: '2026-08-08' }),
      error => error?.code === 'request_unavailable',
    );
    assert.deepEqual(calls.map(call => call.url), [
      '/api/mobile/auth/session',
      '/api/student/bootstrap?sid=sid-session&date=2026-08-08',
    ]);
  });

  await checkAsync('curriculum rotation refreshes session and redirects instead of reusing URL SID', async () => {
    const calls = [];
    let sessionCount = 0;
    const adapter = createStudentAppSessionAdapter({
      fetchImpl: async (input, init) => {
        calls.push(requestRecord(input, init));
        if (input === '/api/mobile/auth/session') {
          sessionCount += 1;
          return jsonResponse({ state: 'ready', sid: sessionCount === 1 ? 'sid-old' : 'sid-new', csrfToken: `csrf-${sessionCount}` });
        }
        return jsonResponse({ code: 'sid_mismatch' }, 403);
      },
    });
    await assert.rejects(
      loadPublicStudentBootstrap({ adapter, pageSid: 'sid-old', date: '2026-08-08' }),
      error => error?.code === 'sid_rotated' && error?.activeSid === 'sid-new',
    );
    assert.deepEqual(calls.map(call => call.url), [
      '/api/mobile/auth/session',
      '/api/student/bootstrap?sid=sid-old&date=2026-08-08',
      '/api/mobile/auth/session',
    ]);
  });

  await checkAsync('announcement mutation carries memory CSRF and refreshes once after rotation', async () => {
    const calls = [];
    let sessionCount = 0;
    let mutationCount = 0;
    const adapter = createStudentAppSessionAdapter({
      fetchImpl: async (input, init) => {
        calls.push(requestRecord(input, init));
        if (input === '/api/mobile/auth/session') {
          sessionCount += 1;
          return jsonResponse({ state: 'ready', sid: 'sid-session', csrfToken: sessionCount === 1 ? 'csrf-one' : 'csrf-two' });
        }
        mutationCount += 1;
        return mutationCount === 1 ? jsonResponse({ code: 'csrf_invalid' }, 403) : jsonResponse({ ok: true });
      },
    });
    const response = await adapter.request('/api/announce-submit', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: 'Bearer legacy-token' },
      body: JSON.stringify({ sid: 'sid-session', id: 'ann-1', reply: '확인' }),
    });
    assert.equal(response.ok, true);
    assert.equal(sessionCount, 2);
    const mutations = calls.filter(call => call.url === '/api/announce-submit');
    assert.deepEqual(mutations.map(call => call.csrf), ['csrf-one', 'csrf-two']);
    assert.equal(mutations.every(call => call.authorization === null && call.credentials === 'same-origin'), true);
  });

  await checkAsync('foreign body SID is rejected before a mutation request', async () => {
    const calls = [];
    const adapter = createStudentAppSessionAdapter({
      fetchImpl: async (input, init) => {
        calls.push(requestRecord(input, init));
        return jsonResponse({ state: 'ready', sid: 'sid-session', csrfToken: 'csrf-one' });
      },
    });
    await assert.rejects(
      adapter.request('/api/announce-ack', { method: 'POST', body: JSON.stringify({ sid: 'sid-other', id: 'ann-1' }) }),
      error => error?.code === 'sid_mismatch' && error?.status === 403,
    );
    assert.deepEqual(calls.map(call => call.url), ['/api/mobile/auth/session']);
  });

  check('source keeps local recovery but closes public storage, bearer, write, and static fallbacks', () => {
    assert.match(source, /window\.__STU_SID__\s*=\s*STUDENT_APP_PUBLIC_MODE\s*\?\s*''/);
    assert.match(source, /!STUDENT_APP_PUBLIC_MODE\s*&&\s*window\.__STU_SID__[\s\S]{0,120}localStorage\.setItem\("studentSid"/);
    assert.match(source, /async function recoverStudentSid[\s\S]{0,100}if \(STUDENT_APP_PUBLIC_MODE\) return ''/);
    assert.match(source, /async function ensureTodayAssignmentIfMissing\(\)[\s\S]{0,100}if \(STUDENT_APP_PUBLIC_MODE\) return false/);
    assert.match(source, /if \(STUDENT_APP_PUBLIC_MODE\)[\s\S]{0,120}TEST_CFG = \{ categories: \{\} \}/);
    assert.match(source, /const res = await studentAppRequest\(url, init\)/);
    assert.match(source, /const requestSid = await announcementSid\(\)/);
    assert.match(source, /student-session-recovery/);
    assert.match(source, /fetch\("\/api\/students"\)/, 'local legacy recovery must remain');
  });

  const artifact = {
    suite: 'student-mobile-app-student-data',
    generatedAt: new Date().toISOString(),
    checks: passed.length,
    checksPassed: passed,
    files: { student: path.relative(root, studentJsPath) },
  };
  await fs.mkdir(path.dirname(artifactPath), { recursive: true });
  await fs.writeFile(artifactPath, `${JSON.stringify(artifact, null, 2)}\n`, 'utf8');
  return artifact;
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  runChecks().then(
    result => console.log(`student-mobile-app student-data: ${result.checks} assertions passed`),
    error => { console.error(error); process.exitCode = 1; },
  );
}
