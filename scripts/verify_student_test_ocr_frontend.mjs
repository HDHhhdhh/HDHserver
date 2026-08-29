import assert from 'node:assert/strict';
import fs from 'node:fs';
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

console.log(`student-test-ocr-frontend passed: ${assertions} assertions`);
