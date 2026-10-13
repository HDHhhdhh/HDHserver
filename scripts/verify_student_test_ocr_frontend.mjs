import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const read = relative => fs.readFileSync(path.join(root, relative), 'utf8');

const studentHtml = read('static/student.html');
const captureHtml = read('static/student-test-capture.html');
const launcher = read('static/js/student-test-ocr-launcher.js');
const capture = read('static/js/student-test-capture.js');
const css = read('static/css/student-test-ocr.css');
const pages = read('routes/pages.py');

let assertions = 0;

assert.ok(studentHtml.includes('/js/student-test-ocr-launcher.js'));
assert.ok(studentHtml.indexOf('/js/student.js') < studentHtml.indexOf('/js/student-test-ocr-launcher.js'));
assert.ok(studentHtml.includes('/css/student-test-ocr.css'));
assertions += 3;

assert.ok(launcher.includes('/capabilities'));
assert.ok(launcher.includes('capabilities?.enabled !== true'));
assert.ok(launcher.includes("['assigned', 'interrupted']"));
assert.ok(launcher.includes("import { fetchJsonChecked, sendJson } from './shared/api.js'"));
assertions += 4;

assert.ok(captureHtml.includes('답안지 네 모서리가 모두 화면 안에 들어오도록'));
assert.ok(captureHtml.includes('화면이 안정되면 자동 촬영됩니다.'));
assert.ok(!/<input[^>]+type=["']?file/i.test(captureHtml));
assert.ok(captureHtml.includes('playsinline'));
assertions += 3;

assert.ok(capture.includes('navigator.mediaDevices.getUserMedia'));
assert.ok(capture.includes("facingMode: { ideal: 'environment' }"));
assert.ok(capture.includes('REQUIRED_STABLE_FRAMES'));
assert.ok(capture.includes('CAPTURE_FRAME_COUNT = 3'));
assert.ok(capture.includes('elements.capture.disabled = !stable || captureBusy'));
assert.ok(capture.includes('void captureAndSubmit()'));
assert.ok(capture.includes("form.set('capture', blob"));
assert.ok(capture.includes('/recapture'));
assert.ok(capture.includes('/retake'));
assert.ok(capture.includes('action.recaptureAttempts + 1}/2회'));
assert.ok(capture.includes('정답 여부는 선생님이 판별합니다.'));
assert.ok(!/answerKeys|correctAnswer/.test(capture));
assertions += 8;

assert.ok(css.includes('body.student-page .student-test-ocr-launch'));
assert.ok(css.includes('body.student-test-capture-page'));
assert.ok(!/^\s*(button|a|body)\s*\{/m.test(css));
assertions += 3;

assert.ok(pages.includes('@bp_pages.get("/student-test-capture")'));
assert.ok(pages.includes('send_static_file("student-test-capture.html")'));
assertions += 2;

const geometrySource = read('static/js/student-test-capture-geometry.js');
const { questionSourceRegion } = await import(`data:text/javascript;base64,${Buffer.from(geometrySource).toString('base64')}`);
const regionValues = region => [region.x, region.y, region.width, region.height];
const landscapeVideoRect = { left: 21, top: 37, width: 400, height: 600 };
const landscapeGuideRect = { left: 101, top: 247, width: 240, height: 105 };
assert.deepEqual(regionValues(questionSourceRegion(1920, 1080, landscapeVideoRect, landscapeGuideRect)), [744, 378, 432, 189]);
assert.deepEqual(regionValues(questionSourceRegion(1080, 1920, { left: 10, top: 20, width: 600, height: 400 },
  { left: 160, top: 170, width: 300, height: 100 })), [270, 870, 540, 180]);
assert.throws(() => questionSourceRegion(0, 1080, landscapeVideoRect, landscapeGuideRect), RangeError);
assert.throws(() => questionSourceRegion(1920, 1080, landscapeVideoRect, { ...landscapeGuideRect, left: 20 }), RangeError);
assert.throws(() => questionSourceRegion(1920, 1080, landscapeVideoRect, { ...landscapeGuideRect, height: Infinity }), RangeError);
assertions += 5;

function captureHarness() {
  const elements = new Map();
  const draws = [];
  const timers = [];
  const cleared = [];
  const posts = [];
  let statusError = null;
  let postError = null;
  let qualityMode = 'dark';
  function element(id) {
    if (elements.has(id)) return elements.get(id);
    const item = { hidden: false, disabled: false, textContent: '', handlers: new Map(),
      classList: { toggle() {} }, addEventListener(event, handler) { this.handlers.set(event, handler); } };
    elements.set(id, item);
    if (id.includes('Canvas') || id === 'qualityCanvas') {
      item.getContext = () => ({
        drawImage(...args) { draws.push(args); },
        getImageData() {
          const data = new Uint8Array(item.width * item.height * 4);
          for (let y = 0; y < item.height; y += 1) {
            for (let x = 0; x < item.width; x += 1) {
              const stroke = qualityMode === 'sharpWhite' && x >= 45 && x <= 49 && y >= 6 && y <= 65;
              const value = qualityMode === 'dark' || stroke ? 0 : 255;
              const offset = (y * item.width + x) * 4;
              data.set([value, value, value, 255], offset);
            }
          }
          return { data };
        },
      });
      item.toBlob = callback => callback(new Blob([JSON.stringify({ width: item.width, height: item.height })]));
    }
    return item;
  }
  const preview = element('cameraPreview');
  Object.assign(preview, { videoWidth: 1920, videoHeight: 1080, getBoundingClientRect: () => landscapeVideoRect });
  element('cameraGuide').getBoundingClientRect = () => landscapeGuideRect;
  const windowStub = {
    addEventListener() {}, clearInterval() {},
    clearTimeout(id) { cleared.push(id); },
    setTimeout(callback, delay) {
      if (delay === 80) queueMicrotask(callback);
      else timers.push({ callback, delay });
      return timers.length + 1;
    },
  };
  const context = vm.createContext({
    window: windowStub, document: { getElementById: element, createElement: () => element('qualityCanvas') },
    navigator: { userAgent: '' }, sessionStorage: { setItem() {} },
    location: { search: '', pathname: '/student-test-capture' }, console,
    Blob, FormData, URLSearchParams, Uint8Array, questionSourceRegion,
    fetchJsonChecked: async () => { if (statusError) throw statusError; return { status: 'failed' }; },
    sendJson: async () => { throw new Error('unexpected JSON POST'); },
    fetch: async (url, options) => {
      posts.push({ url, options });
      if (postError) return { ok: false, status: postError.status, json: async () => postError };
      return { ok: true, status: 200, json: async () => ({ submissionId: 'submission-1', status: 'processing' }) };
    },
  });
  const executable = capture.replace(/^import[^\n]*\n/gm, '').replace(/void init\(\);\s*$/, '');
  vm.runInContext(executable + `
    globalThis.captureFixture = {
      cameraFrameBlob, qualitySnapshot, updateQuality, refreshStatus,
      setMode(kind, ready = false) {
        captureMode = { kind, questionNo: 2 };
        launch = { sid: 'fixture', submissionId: 'submission-1', status: { revision: 1 } };
        stableQualityFrames = ready ? 5 : 0;
        priorQualityFrame = null;
        autoCaptureStarted = false;
        pollTimer = 99;
      }
    };
  `, context);
  return { api: context.captureFixture, elements, draws, timers, cleared, posts,
    setStatusError(error) { statusError = error; },
    setPostError(error) { postError = error; },
    setQualityMode(mode) { qualityMode = mode; } };
}

const harness = captureHarness();
harness.api.setMode('question');
let blob = await harness.api.cameraFrameBlob();
assert.deepEqual(JSON.parse(await blob.text()), { width: 432, height: 189 });
assert.deepEqual(harness.draws.at(-1).slice(1), [744, 378, 432, 189, 0, 0, 432, 189]);
harness.api.qualitySnapshot();
assert.deepEqual(harness.draws.at(-1).slice(1), [744, 378, 432, 189, 0, 0, 96, 72]);
assertions += 3;
for (const mode of ['initial', 'retake']) {
  harness.api.setMode(mode);
  blob = await harness.api.cameraFrameBlob();
  assert.deepEqual(JSON.parse(await blob.text()), { width: 1920, height: 1080 });
  assert.deepEqual(harness.draws.at(-1).slice(1), [0, 0, 1920, 1080, 0, 0, 1920, 1080]);
  assertions += 2;
}

harness.api.setMode('question', true);
harness.elements.get('cameraCapture').handlers.get('click')();
await new Promise(resolve => setImmediate(resolve));
assert.equal(harness.posts.length, 1);
assert.equal(harness.posts[0].url, '/api/student-test-ocr/submissions/submission-1/recapture');
assert.equal(harness.posts[0].options.body.get('questionNo'), '2');
assert.deepEqual(JSON.parse(await harness.posts[0].options.body.get('capture').text()), { width: 432, height: 189 });
assertions += 4;

const automatic = captureHarness();
automatic.api.setMode('question');
automatic.setQualityMode('sharpWhite');
const sharpWhite = automatic.api.qualitySnapshot();
assert.ok(sharpWhite.brightness > 238);
assert.ok(sharpWhite.edge > 8);
assert.equal(sharpWhite.movement, 0);
for (let frame = 0; frame < 4; frame += 1) automatic.api.updateQuality();
assert.equal(automatic.posts.length, 0);
automatic.api.updateQuality();
await new Promise(resolve => setImmediate(resolve));
assert.equal(automatic.posts.length, 1);
assert.deepEqual(JSON.parse(await automatic.posts[0].options.body.get('capture').text()), { width: 432, height: 189 });
assertions += 6;
for (const mode of ['flatWhite', 'dark']) {
  const rejected = captureHarness();
  rejected.api.setMode('question');
  rejected.setQualityMode(mode);
  for (let frame = 0; frame < 6; frame += 1) rejected.api.updateQuality();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(rejected.posts.length, 0);
  assert.equal(rejected.elements.get('cameraCapture').disabled, true);
  assertions += 2;
}

for (const mode of ['question', 'retake']) {
  const conflict = captureHarness();
  conflict.api.setMode(mode, true);
  conflict.setPostError({ status: 409, code: 'test_catalog_changed', message: 'catalog changed' });
  conflict.elements.get('cameraCapture').handlers.get('click')();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(conflict.posts.length, 1);
  assert.equal(conflict.elements.get('errorTitle').textContent, '시험 정보가 변경되었습니다');
  assert.equal(conflict.elements.get('errorRetry').hidden, true);
  assert.equal(conflict.elements.get('errorRetry').onclick, null);
  assert.equal(conflict.timers.length, 0);
  assertions += 5;
}

harness.api.setMode('question');
harness.setStatusError(Object.assign(new Error('conflict'), { status: 409, body: '{"code":"test_catalog_changed"}' }));
await harness.api.refreshStatus();
assert.equal(harness.elements.get('errorTitle').textContent, '시험 정보가 변경되었습니다');
assert.equal(harness.elements.get('errorView').hidden, false);
assert.equal(harness.elements.get('errorRetry').hidden, true);
assert.equal(harness.timers.length, 0);
assert.ok(harness.cleared.includes(99));
assertions += 5;
harness.setStatusError(new Error('network temporarily unavailable'));
await harness.api.refreshStatus();
assert.equal(harness.timers.at(-1).delay, 2000);
assert.equal(harness.elements.get('processingView').hidden, false);
assertions += 2;

console.log(`student-test-ocr-frontend passed: ${assertions} assertions`);
