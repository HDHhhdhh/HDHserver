import { fetchJsonChecked, sendJson } from './shared/api.js';

const API_ROOT = '/api/student-test-ocr';
const STORAGE_PREFIX = 'student-test-ocr-launch:';

function todayLocalKey() {
  if (typeof window.todayLocalKey === 'function') return window.todayLocalKey();
  const now = new Date();
  return new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
}

function studentSid() {
  const published = String(window.__STU_SID__ || '').trim();
  if (published) return published;
  const match = location.pathname.match(/^\/student\/([^/]+)\/?$/);
  return match ? decodeURIComponent(match[1]) : '';
}

function randomId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  return `${Date.now()}-${Math.random().toString(36).slice(2)}-${Math.random().toString(36).slice(2)}`;
}

function responseError(payload, fallback) {
  const error = new Error(String(payload?.message || fallback));
  error.code = String(payload?.code || 'request_failed');
  return error;
}

async function postJson(url, body) {
  const response = await sendJson(url, body, { cache: 'no-store' });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok || payload?.ok === false) throw responseError(payload, `요청 실패 (${response.status})`);
  return payload;
}

function testForButton(button) {
  const id = String(button?.dataset?.testId || '').trim();
  return (Array.isArray(window.__ASSIGNED_TESTS__) ? window.__ASSIGNED_TESTS__ : []).find(item => (
    String(item?.id || item?.testId || '').trim() === id
  ));
}

async function launchCapture(button, test) {
  const sid = studentSid();
  const assignmentLabel = String(test?.label || '').trim();
  const testId = String(test?.id || test?.testId || '').trim();
  if (!sid || !assignmentLabel || !testId) {
    throw new Error('배정 테스트 정보를 확인할 수 없습니다. 학생 페이지를 새로고침해 주세요.');
  }
  button.disabled = true;
  button.textContent = '촬영 준비 중…';
  try {
    const session = await postJson(`${API_ROOT}/session`, {
      sid,
      date: todayLocalKey(),
      testId,
      assignmentLabel,
    });
    const launchId = randomId();
    const launch = {
      sid,
      date: todayLocalKey(),
      testId,
      assignmentLabel,
      testName: String(session.testName || test.name || test.label || '테스트'),
      round: String(session.round || test.round || ''),
      token: String(session.token || ''),
      tokenExpiresAt: String(session.expiresAt || ''),
      requestId: randomId(),
      studentPageUrl: `/student/${encodeURIComponent(sid)}`,
    };
    sessionStorage.setItem(`${STORAGE_PREFIX}${launchId}`, JSON.stringify(launch));
    const query = new URLSearchParams({
      launch: launchId,
      sid,
      date: launch.date,
      testId,
      assignmentLabel,
      testName: launch.testName,
      round: launch.round,
    });
    location.assign(`/student-test-capture?${query.toString()}`);
  } finally {
    button.disabled = false;
    button.textContent = '답안 촬영';
  }
}

function installButtons() {
  const list = document.getElementById('assignedTestList');
  if (!list) return;
  list.querySelectorAll('.assigned-test-btn[data-test-id]').forEach(answerButton => {
    const row = answerButton.closest('li');
    const test = testForButton(answerButton);
    const status = String(test?.status || answerButton.dataset.status || '').trim();
    if (!row || !test || !test.label || !['assigned', 'interrupted'].includes(status)) return;
    if (row.querySelector('.student-test-ocr-launch')) return;
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'student-test-ocr-launch';
    button.textContent = '답안 촬영';
    button.addEventListener('click', async () => {
      try {
        await launchCapture(button, testForButton(answerButton) || test);
      } catch (error) {
        alert(error?.message || '촬영 화면을 열 수 없습니다.');
      }
    });
    row.appendChild(button);
  });
}

async function init() {
  let capabilities;
  try {
    capabilities = await fetchJsonChecked(`${API_ROOT}/capabilities`, 'student test OCR capabilities', {
      cache: 'no-store',
    });
  } catch {
    return;
  }
  if (capabilities?.enabled !== true || capabilities?.cameraOnly !== true) return;
  const list = document.getElementById('assignedTestList');
  if (!list) return;
  const observer = new MutationObserver(installButtons);
  observer.observe(list, { childList: true, subtree: true });
  installButtons();
}

void init();
