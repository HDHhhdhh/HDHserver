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

    studentAppShouldLoadKollusController,
    loadStudentAppKollusController,


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

  await check('retired student submit and OCR surfaces stay absent', async () => {
    assert.doesNotMatch(html, /openTestSubmit|testSubmitModal|testAnswerPreviewModal/);
    for (const retired of [
      '/api/submit-test',
      '/api/ocr-test-sheet',
      'openAssignedTestSubmit',
      'ocrTestSheetStartCapture',
      'STUDENT_APP_LOCAL_SUBMIT_FALLBACK',
      '__OCR_TEST_SHEET_ENABLED__',
    ]) {
      assert.equal(source.includes(retired), false, `retired student surface returned: ${retired}`);
    }
  });

  await check('sensitive video requests use the session adapter', async () => {
    assert.match(source, /studentAppRequest\('\/api\/watch'/);
    assert.match(source, /studentAppRequest\(`\/api\/get-url\?/);
  });

  await check('retired static tests-config fallback stays absent', async () => {
    assert.doesNotMatch(source, /\/api\/tests-config\.json/);
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
