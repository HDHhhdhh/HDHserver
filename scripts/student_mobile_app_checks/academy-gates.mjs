import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(import.meta.dirname, '..', '..');
const STUDENT_JS_PATH = path.join(ROOT, 'static', 'js', 'student.js');
const STUDENT_HTML_PATH = path.join(ROOT, 'static', 'student.html');
const KOLLUS_CONTROLLER_URL = 'https://file.kollus.com/vgcontroller/vg-controller-client.latest.min.js';

function contractSource(source) {
  const startMarker = '/* STUDENT_APP_ACADEMY_GATES_START */';
  const endMarker = '/* STUDENT_APP_ACADEMY_GATES_END */';
  const start = source.indexOf(startMarker);
  const end = source.indexOf(endMarker);
  assert.ok(start >= 0 && end > start, 'academy-gate contract markers must exist');
  return source.slice(start + startMarker.length, end);
}

function loadContract(source) {
  const context = vm.createContext({
    URL,
    URLSearchParams,
    Promise,
    Object,
    String,
    Error,
  });
  const code = `${contractSource(source)}\n;globalThis.__academyGateContract = Object.freeze({
    studentAppAcademyAccessFromBootstrap,
    studentAppQueryFeatureGates,
    studentAppShouldLoadKollusController,
    loadStudentAppKollusController,
    studentAppClassifySubmitFailure,
    studentAppResolveSubmitFailure,
  });`;
  new vm.Script(code, { filename: 'student-academy-gates.contract.js' }).runInContext(context);
  return context.__academyGateContract;
}

function fakeDocument(trace) {
  return {
    querySelector() { return null; },
    createElement(tagName) {
      assert.equal(tagName, 'script');
      return { dataset: {} };
    },
    head: {
      appendChild(script) {
        trace.push({
          kind: 'script',
          src: script.src,
          async: script.async,
          crossOrigin: script.crossOrigin,
          controller: script.dataset.studentAcademyController,
        });
        queueMicrotask(() => script.onload?.());
      },
    },
  };
}

export async function runChecks() {
  const source = fs.readFileSync(STUDENT_JS_PATH, 'utf8');
  const html = fs.readFileSync(STUDENT_HTML_PATH, 'utf8');
  const checks = [];
  const check = async (name, fn) => {
    await fn();
    checks.push(name);
  };

  await check('student shell has no unconditional Kollus controller', async () => {
    assert.doesNotMatch(html, /<script[^>]+file\.kollus\.com\/vgcontroller/i);
  });

  await check('public academy access requires an explicit true bootstrap flag', async () => {
    const gate = loadContract(source);
    assert.equal(gate.studentAppAcademyAccessFromBootstrap(true, {}), false);
    assert.equal(gate.studentAppAcademyAccessFromBootstrap(true, { academyAccessAllowed: true }), true);
    assert.equal(gate.studentAppAcademyAccessFromBootstrap(true, { academyAccessAllowed: true, networkBlocked: true }), false);
    assert.equal(gate.studentAppAcademyAccessFromBootstrap(false, {}), true);
  });

  await check('external public mode makes zero Kollus network requests', async () => {
    const gate = loadContract(source);
    const trace = [];
    const loaded = await gate.loadStudentAppKollusController({
      publicMode: true,
      academyAccessAllowed: false,
      documentRef: fakeDocument(trace),
      globalRef: {},
    });
    assert.equal(loaded, false);
    assert.deepEqual(trace, []);
  });

  await check('academy public mode loads the pinned Kollus controller once', async () => {
    const gate = loadContract(source);
    const trace = [];
    const options = {
      publicMode: true,
      academyAccessAllowed: true,
      documentRef: fakeDocument(trace),
      globalRef: {},
    };
    assert.equal(await gate.loadStudentAppKollusController(options), true);
    assert.equal(await gate.loadStudentAppKollusController(options), true);
    assert.deepEqual(trace, [{
      kind: 'script',
      src: KOLLUS_CONTROLLER_URL,
      async: true,
      crossOrigin: 'anonymous',
      controller: 'kollus',
    }]);
  });

  await check('local academy mode keeps Kollus controller loading', async () => {
    const gate = loadContract(source);
    const trace = [];
    assert.equal(await gate.loadStudentAppKollusController({
      publicMode: false,
      academyAccessAllowed: true,
      documentRef: fakeDocument(trace),
      globalRef: {},
    }), true);
    assert.equal(trace.length, 1);
  });

  await check('public OCR and QA query switches are ignored', async () => {
    const gate = loadContract(source);
    const publicQuery = gate.studentAppQueryFeatureGates(true, '?ocr=1&freshPhase2E=1&qaDate=2026-08-08');
    assert.deepEqual({ ...publicQuery }, { ocrEnabled: false, freshPhase2E: false, qaDate: '' });
    const callTrace = [];
    if (publicQuery.ocrEnabled) callTrace.push('/api/ocr-test-sheet-review');
    assert.deepEqual(callTrace, []);
    const localQuery = gate.studentAppQueryFeatureGates(false, '?ocr=1&freshPhase2E=1&qaDate=2026-08-08');
    assert.deepEqual({ ...localQuery }, { ocrEnabled: true, freshPhase2E: true, qaDate: '2026-08-08' });
  });

  await check('public submit failure never invokes legacy write fallbacks', async () => {
    const gate = loadContract(source);
    for (const error of [
      { status: 403, code: 'academy_only' },
      { status: 500, code: 'server_error' },
      new Error('network down'),
    ]) {
      const trace = ['/api/submit-test'];
      const result = await gate.studentAppResolveSubmitFailure({
        publicMode: true,
        error,
        runLegacyFallback: async () => {
          trace.push('/api/logs/patch', '/api/tests');
        },
      });
      assert.equal(result.mayUseLegacyFallback, false);
      assert.deepEqual(trace, ['/api/submit-test']);
    }
  });

  await check('public submit failures distinguish academy-only and retry UI', async () => {
    const gate = loadContract(source);
    assert.equal(gate.studentAppClassifySubmitFailure({ status: 403, code: 'academy_only' }).state, 'academy_only');
    assert.equal(gate.studentAppClassifySubmitFailure({ status: 500, code: 'server_error' }).state, 'retry');
    assert.equal(gate.studentAppClassifySubmitFailure(new Error('offline')).state, 'retry');
  });

  await check('local mode retains the legacy submit fallback contract', async () => {
    const gate = loadContract(source);
    const trace = [];
    const result = await gate.studentAppResolveSubmitFailure({
      publicMode: false,
      error: new Error('old server'),
      runLegacyFallback: async () => trace.push('legacy-fallback'),
    });
    assert.equal(result.mayUseLegacyFallback, true);
    assert.deepEqual(trace, ['legacy-fallback']);
  });

  await check('sensitive public requests use the session adapter', async () => {
    assert.match(source, /studentAppRequest\('\/api\/watch'/);
    assert.match(source, /studentAppRequest\(`\/api\/get-url\?/);
    assert.match(source, /studentAppRequest\('\/api\/submit-test'/);
    assert.match(source, /studentAppRequest\('\/js\/test_answer_link_map\.json'/);
    assert.match(source, /studentAppRequest\(OCR_PHASE2B_REVIEW_ENDPOINT/);
  });

  await check('public submit gate precedes every local-only direct write fallback', async () => {
    const gateMarker = source.indexOf('/* STUDENT_APP_PUBLIC_SUBMIT_FAILURE_GATE */');
    const fallbackMarker = source.indexOf('/* STUDENT_APP_LOCAL_SUBMIT_FALLBACK_START */');
    assert.ok(gateMarker > 0 && fallbackMarker > gateMarker);
    const gateBranch = source.slice(gateMarker, fallbackMarker);
    assert.match(gateBranch, /studentAppResolveSubmitFailure/);
    assert.match(gateBranch, /if \(!failureDecision\.mayUseLegacyFallback\)[\s\S]*?return;/);
    const fallbackSource = source.slice(fallbackMarker);
    assert.match(fallbackSource, /fetch\('\/api\/logs\/patch'/);
    assert.match(fallbackSource, /fetch\('\/api\/tests'/);
  });

  await check('public tests config never falls back to the static JSON file', async () => {
    assert.match(source, /if \(STUDENT_APP_PUBLIC_MODE\) \{\s*TEST_CFG = \{ categories: \{\} \};\s*return;\s*\}[\s\S]{0,180}\/api\/tests-config\.json/);
  });

  await check('public query gates drive all OCR switches', async () => {
    assert.match(source, /const STUDENT_APP_QUERY_FEATURES = studentAppQueryFeatureGates\(STUDENT_APP_PUBLIC_MODE, location\.search\)/);
    assert.match(source, /window\.__OCR_TEST_SHEET_ENABLED__ = STUDENT_APP_QUERY_FEATURES\.ocrEnabled/);
    assert.match(source, /const OCR_PHASE2E_FRESH_REVIEW_REQUESTED = STUDENT_APP_QUERY_FEATURES\.freshPhase2E/);
    const submitHook = source.indexOf("window.openAssignedTestSubmit = (testId = '') => open(testId)");
    const ocrInitGate = source.indexOf('if (OCR_TEST_SHEET_ENABLED) {', submitHook);
    const ocrHook = source.indexOf('window.ocrTestSheetStartCapture =', submitHook);
    assert.ok(submitHook > 0 && ocrInitGate > submitHook && ocrHook > ocrInitGate);
  });

  await check('Kollus loading happens only after bootstrap access is applied', async () => {
    const assignment = source.indexOf('academyAccessAllowed = studentAppAcademyAccessFromBootstrap');
    const load = source.indexOf('loadStudentAppKollusController({', assignment);
    assert.ok(assignment > 0 && load > assignment);
  });

  console.log(`academy-gates checks passed: ${checks.length}`);
  return { suite: 'student-mobile-app-academy-gates', checks: checks.length, passed: true };
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  runChecks().catch((error) => {
    console.error(`academy-gates checks failed: ${error instanceof Error ? error.message : String(error)}`);
    process.exitCode = 1;
  });
}
