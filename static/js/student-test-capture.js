import { fetchJsonChecked, sendJson } from './shared/api.js';
import { questionSourceRegion } from './student-test-capture-geometry.js';

const API_ROOT = '/api/student-test-ocr';
const STORAGE_PREFIX = 'student-test-ocr-launch:';
const FULL_CAPTURE_MESSAGE = '답안지 네 모서리가 모두 화면 안에 들어오도록, 밝은 곳에서 흔들림 없이 정면으로 비춰 주세요. 화면이 안정되면 자동 촬영됩니다.';
const POLL_INTERVAL_MS = 1000;
const QUALITY_INTERVAL_MS = 250;
const REQUIRED_STABLE_FRAMES = 5;
const CAPTURE_FRAME_COUNT = 3;
const CAPTURE_FRAME_GAP_MS = 80;

const elements = {
  back: document.getElementById('captureBack'),
  testName: document.getElementById('captureTestName'),
  testMeta: document.getElementById('captureTestMeta'),
  cameraStage: document.getElementById('cameraStage'),
  preview: document.getElementById('cameraPreview'),
  guide: document.getElementById('cameraGuide'),
  quality: document.getElementById('cameraQuality'),
  cameraMessage: document.getElementById('cameraMessage'),
  capture: document.getElementById('cameraCapture'),
  canvas: document.getElementById('captureCanvas'),
  processing: document.getElementById('processingView'),
  processingMessage: document.getElementById('processingMessage'),
  actions: document.getElementById('actionView'),
  actionList: document.getElementById('studentActionList'),
  retake: document.getElementById('retakeView'),
  retakeStart: document.getElementById('retakeStart'),
  result: document.getElementById('resultView'),
  resultTitle: document.getElementById('resultTitle'),
  resultSummary: document.getElementById('resultSummary'),
  resultCorrect: document.getElementById('resultCorrect'),
  resultIncorrect: document.getElementById('resultIncorrect'),
  resultPending: document.getElementById('resultPending'),
  resultWrong: document.getElementById('resultWrong'),
  resultPendingNote: document.getElementById('resultPendingNote'),
  resultAnswerLink: document.getElementById('resultAnswerLink'),
  error: document.getElementById('errorView'),
  errorTitle: document.getElementById('errorTitle'),
  errorMessage: document.getElementById('errorMessage'),
  errorCode: document.getElementById('errorCode'),
  errorRetry: document.getElementById('errorRetry'),
};

const views = [elements.cameraStage, elements.processing, elements.actions, elements.retake, elements.result, elements.error];
let launch = null;
let launchId = '';
let stream = null;
let qualityTimer = 0;
let pollTimer = 0;
let captureMode = null;
let captureBusy = false;
let priorQualityFrame = null;
let stableQualityFrames = 0;
let latestQuality = null;
let autoCaptureStarted = false;

function randomId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  return `${Date.now()}-${Math.random().toString(36).slice(2)}-${Math.random().toString(36).slice(2)}`;
}

function showView(target) {
  views.forEach(view => { if (view) view.hidden = view !== target; });
}

function responseError(payload, status) {
  const error = new Error(String(payload?.message || `요청 실패 (${status})`));
  error.code = String(payload?.code || 'request_failed');
  error.status = status;
  return error;
}

async function postJson(url, body) {
  const response = await sendJson(url, body, { cache: 'no-store' });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok || payload?.ok === false) throw responseError(payload, response.status);
  return payload;
}

async function postCapture(url, fields, blob) {
  const form = new FormData();
  Object.entries(fields).forEach(([key, value]) => form.set(key, String(value)));
  form.set('capture', blob, 'camera-capture.jpg');
  const response = await fetch(url, { method: 'POST', body: form, cache: 'no-store' });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok || payload?.ok === false) throw responseError(payload, response.status);
  return payload;
}

function saveLaunch() {
  if (!launchId || !launch) return;
  sessionStorage.setItem(`${STORAGE_PREFIX}${launchId}`, JSON.stringify(launch));
}

function queryLaunch() {
  const query = new URLSearchParams(location.search);
  return {
    sid: String(query.get('sid') || '').trim(),
    date: String(query.get('date') || '').trim(),
    testId: String(query.get('testId') || '').trim(),
    assignmentLabel: String(query.get('assignmentLabel') || '').trim(),
    testName: String(query.get('testName') || '테스트').trim(),
    round: String(query.get('round') || '').trim(),
    studentPageUrl: query.get('sid') ? `/student/${encodeURIComponent(query.get('sid'))}` : '/',
  };
}

async function loadLaunch() {
  const query = new URLSearchParams(location.search);
  launchId = String(query.get('launch') || '').trim() || randomId();
  try {
    const stored = JSON.parse(sessionStorage.getItem(`${STORAGE_PREFIX}${launchId}`) || 'null');
    if (stored && typeof stored === 'object' && stored.sid && stored.testId) return stored;
  } catch {}
  const fallback = queryLaunch();
  if (!fallback.sid || !fallback.date || !fallback.testId || !fallback.assignmentLabel) {
    throw responseError({ code: 'missing_launch', message: '학생 페이지에서 답안 촬영을 다시 시작해 주세요.' }, 400);
  }
  const session = await postJson(`${API_ROOT}/session`, {
    sid: fallback.sid,
    date: fallback.date,
    testId: fallback.testId,
    assignmentLabel: fallback.assignmentLabel,
  });
  const created = {
    ...fallback,
    testName: String(session.testName || fallback.testName || '테스트'),
    round: String(session.round || fallback.round || ''),
    token: String(session.token || ''),
    tokenExpiresAt: String(session.expiresAt || ''),
    requestId: randomId(),
  };
  sessionStorage.setItem(`${STORAGE_PREFIX}${launchId}`, JSON.stringify(created));
  return created;
}

function isEmbeddedBrowser() {
  return /(KAKAOTALK|NAVER|Instagram|FBAN|FBAV|Line\/|DaumApps)/i.test(navigator.userAgent || '');
}

function externalBrowserUrl() {
  if (!/Android/i.test(navigator.userAgent || '')) return '';
  const scheme = location.protocol.replace(':', '');
  return `intent://${location.host}${location.pathname}${location.search}#Intent;scheme=${scheme};package=com.android.chrome;end`;
}

async function showEmbeddedBrowserBlock() {
  showView(elements.error);
  elements.errorTitle.textContent = '기본 브라우저에서 열어 주세요';
  elements.errorMessage.textContent = /Android/i.test(navigator.userAgent || '')
    ? '카메라 촬영은 Chrome에서 진행합니다.'
    : '공유 메뉴에서 Safari로 열어 주세요. 이 화면의 주소를 복사할 수 있습니다.';
  elements.errorCode.textContent = '';
  elements.errorRetry.hidden = false;
  elements.errorRetry.textContent = /Android/i.test(navigator.userAgent || '') ? 'Chrome에서 열기' : '주소 복사';
  elements.errorRetry.onclick = async () => {
    const external = externalBrowserUrl();
    if (external) {
      location.href = external;
      return;
    }
    try {
      await navigator.clipboard.writeText(location.href);
      elements.errorRetry.textContent = '주소 복사 완료';
    } catch {
      elements.errorMessage.textContent = 'Safari 주소창에 현재 주소를 직접 붙여 넣어 주세요.';
    }
  };
}

function stopQualityAnalysis() {
  if (qualityTimer) window.clearInterval(qualityTimer);
  qualityTimer = 0;
  priorQualityFrame = null;
  stableQualityFrames = 0;
  latestQuality = null;
  autoCaptureStarted = false;
}

function stopCamera() {
  stopQualityAnalysis();
  if (stream) stream.getTracks().forEach(track => track.stop());
  stream = null;
  if (elements.preview) elements.preview.srcObject = null;
  if (elements.capture) elements.capture.disabled = true;
}

function cameraSourceRegion() {
  const video = elements.preview;
  if (captureMode?.kind !== 'question') {
    return { x: 0, y: 0, width: video.videoWidth, height: video.videoHeight };
  }
  return questionSourceRegion(video.videoWidth, video.videoHeight,
    video.getBoundingClientRect(), elements.guide.getBoundingClientRect());
}

function qualitySnapshot() {
  const video = elements.preview;
  if (!video?.videoWidth || !video?.videoHeight) return null;
  const canvas = document.createElement('canvas');
  canvas.width = 96;
  canvas.height = 72;
  const context = canvas.getContext('2d', { willReadFrequently: true });
  let region;
  try { region = cameraSourceRegion(); } catch { return null; }
  context.drawImage(video, region.x, region.y, region.width, region.height, 0, 0, canvas.width, canvas.height);
  const pixels = context.getImageData(0, 0, canvas.width, canvas.height).data;
  const gray = new Uint8Array(canvas.width * canvas.height);
  let brightness = 0;
  for (let index = 0, offset = 0; index < gray.length; index += 1, offset += 4) {
    const value = Math.round(pixels[offset] * 0.299 + pixels[offset + 1] * 0.587 + pixels[offset + 2] * 0.114);
    gray[index] = value;
    brightness += value;
  }
  brightness /= gray.length;
  let edge = 0;
  for (let y = 1; y < canvas.height - 1; y += 1) {
    for (let x = 1; x < canvas.width - 1; x += 1) {
      const index = y * canvas.width + x;
      edge += Math.abs(gray[index + 1] - gray[index - 1]) + Math.abs(gray[index + canvas.width] - gray[index - canvas.width]);
    }
  }
  edge /= (canvas.width - 2) * (canvas.height - 2);
  let movement = 0;
  if (priorQualityFrame?.length === gray.length) {
    for (let index = 0; index < gray.length; index += 1) movement += Math.abs(gray[index] - priorQualityFrame[index]);
    movement /= gray.length;
  }
  priorQualityFrame = gray;
  return { brightness, edge, movement };
}

function updateQuality() {
  const sample = qualitySnapshot();
  if (!sample) {
    stableQualityFrames = 0;
    elements.capture.disabled = true;
    return;
  }
  let message = '촬영 가능';
  let ready = true;
  if (sample.brightness < 55) {
    message = '조금 더 밝은 곳에서 촬영해 주세요';
    ready = false;
  } else if (sample.brightness > 238 && sample.edge < 8) {
    message = '빛 반사를 피해 주세요';
    ready = false;
  } else if (sample.movement > 15) {
    message = '휴대폰을 잠시 고정해 주세요';
    ready = false;
  } else if (sample.edge < 8) {
    message = '답안에 초점을 맞춰 주세요';
    ready = false;
  }
  latestQuality = { ...sample, ready };
  stableQualityFrames = ready ? stableQualityFrames + 1 : 0;
  const stable = ready && stableQualityFrames >= REQUIRED_STABLE_FRAMES;
  if (stable) message = '화질 확인 완료 · 자동 촬영 중';
  else if (ready) message = `휴대폰을 그대로 유지해 주세요 (${stableQualityFrames}/${REQUIRED_STABLE_FRAMES})`;
  elements.quality.textContent = message;
  elements.quality.classList.toggle('is-ready', stable);
  elements.capture.disabled = !stable || captureBusy;
  if (stable && !captureBusy && !autoCaptureStarted) {
    autoCaptureStarted = true;
    void captureAndSubmit();
  }
}

function startQualityAnalysis() {
  stopQualityAnalysis();
  updateQuality();
  qualityTimer = window.setInterval(updateQuality, QUALITY_INTERVAL_MS);
}

async function startCamera(mode) {
  stopCamera();
  captureMode = mode;
  showView(elements.cameraStage);
  elements.guide.classList.toggle('is-question', mode.kind === 'question');
  elements.cameraMessage.textContent = mode.kind === 'question'
    ? `${mode.questionNo}번 답만 사각형 안에 크게 비춰 주세요. 화면이 안정되면 자동 촬영됩니다.`
    : FULL_CAPTURE_MESSAGE;
  elements.quality.textContent = '카메라 준비 중';
  elements.quality.classList.remove('is-ready');
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      audio: false,
      video: {
        facingMode: { ideal: 'environment' },
        width: { ideal: 2560 },
        height: { ideal: 1920 },
      },
    });
    elements.preview.srcObject = stream;
    await elements.preview.play();
    elements.capture.disabled = true;
    startQualityAnalysis();
  } catch (error) {
    stopCamera();
    showError(
      '카메라 권한이 필요합니다',
      '브라우저 설정에서 카메라 권한을 허용한 뒤 다시 시도해 주세요. 사진 앨범 업로드는 지원하지 않습니다.',
      error?.name || 'camera_unavailable',
      () => startCamera(mode),
    );
  }
}

function captureScore(sample) {
  if (!sample) return Number.NEGATIVE_INFINITY;
  return sample.edge - Math.abs(sample.brightness - 145) * 0.025 - sample.movement * 0.15;
}

function wait(milliseconds) {
  return new Promise(resolve => window.setTimeout(resolve, milliseconds));
}

async function cameraFrameBlob() {
  const video = elements.preview;
  if (!video?.videoWidth || !video?.videoHeight) throw new Error('카메라 화면이 준비되지 않았습니다.');
  const maximum = 2400;
  const region = cameraSourceRegion();
  const scale = Math.min(1, maximum / Math.max(region.width, region.height));
  elements.canvas.width = Math.max(1, Math.round(region.width * scale));
  elements.canvas.height = Math.max(1, Math.round(region.height * scale));
  const context = elements.canvas.getContext('2d');
  context.drawImage(video, region.x, region.y, region.width, region.height,
    0, 0, elements.canvas.width, elements.canvas.height);
  return new Promise((resolve, reject) => {
    elements.canvas.toBlob(blob => {
      if (blob) resolve(blob);
      else reject(new Error('촬영 이미지를 만들 수 없습니다.'));
    }, 'image/jpeg', 0.92);
  });
}

async function cameraBlob() {
  let best = null;
  for (let index = 0; index < CAPTURE_FRAME_COUNT; index += 1) {
    const sample = qualitySnapshot() || latestQuality;
    const blob = await cameraFrameBlob();
    const score = captureScore(sample);
    if (!best || score > best.score) best = { blob, score };
    if (index + 1 < CAPTURE_FRAME_COUNT) await wait(CAPTURE_FRAME_GAP_MS);
  }
  if (!best?.blob) throw new Error('촬영 이미지를 만들 수 없습니다.');
  return best.blob;
}

function showProcessing(message = '') {
  stopCamera();
  showView(elements.processing);
  elements.processingMessage.textContent = message || '20개 답을 확인하고 자동 채점하는 중입니다. 잠시만 기다려 주세요.';
}

function showError(title, message, code = '', retry = null) {
  stopCamera();
  if (pollTimer) window.clearTimeout(pollTimer);
  pollTimer = 0;
  showView(elements.error);
  elements.errorTitle.textContent = title;
  elements.errorMessage.textContent = message;
  elements.errorCode.textContent = code ? `오류 코드: ${code}` : '';
  elements.errorRetry.hidden = typeof retry !== 'function';
  elements.errorRetry.textContent = '다시 시도';
  elements.errorRetry.onclick = typeof retry === 'function' ? retry : null;
}

async function captureAndSubmit() {
  if (captureBusy || !captureMode || stableQualityFrames < REQUIRED_STABLE_FRAMES) return;
  captureBusy = true;
  elements.capture.disabled = true;
  try {
    const blob = await cameraBlob();
    const mode = captureMode;
    showProcessing(mode.kind === 'question' ? `${mode.questionNo}번 답을 다시 읽고 있습니다.` : '답안지를 서버로 보내고 있습니다.');
    let payload;
    if (mode.kind === 'initial') {
      payload = await postCapture(`${API_ROOT}/capture`, {
        token: launch.token,
        requestId: launch.requestId,
      }, blob);
      launch.submissionId = payload.submissionId;
      saveLaunch();
    } else if (mode.kind === 'retake') {
      payload = await postCapture(`${API_ROOT}/submissions/${encodeURIComponent(launch.submissionId)}/retake`, {
        sid: launch.sid,
        revision: launch.status.revision,
      }, blob);
    } else {
      payload = await postCapture(`${API_ROOT}/submissions/${encodeURIComponent(launch.submissionId)}/recapture`, {
        sid: launch.sid,
        questionNo: mode.questionNo,
        revision: launch.status.revision,
      }, blob);
    }
    if (payload?.submissionId) launch.submissionId = payload.submissionId;
    launch.status = payload;
    saveLaunch();
    await refreshStatus();
  } catch (error) {
    if (error?.code === 'revision_conflict' && launch?.submissionId) {
      await refreshStatus().catch(() => showRequestError(error));
    } else {
      showRequestError(error, () => startCamera(captureMode));
    }
  } finally {
    captureBusy = false;
  }
}

function showRequestError(error, retry = null) {
  if (requestErrorCode(error) === 'test_catalog_changed') {
    showTerminalRequestError(error);
    return;
  }
  showError(
    '처리를 완료하지 못했습니다',
    error?.message || '잠시 후 다시 시도해 주세요.',
    error?.code || '',
    retry,
  );
}

function requestErrorCode(error) {
  let code = String(error?.code || 'request_failed');
  try { code = String(JSON.parse(error.body)?.code || code); } catch {}
  return code;
}

function showTerminalRequestError(error) {
  const code = requestErrorCode(error);
  const changed = code === 'test_catalog_changed';
  showError(changed ? '시험 정보가 변경되었습니다' : '제출 상태를 확인할 수 없습니다',
    changed ? '선생님께 제출 상태를 확인받아 주세요. 촬영한 답안은 보존됩니다.'
      : '학생 페이지로 돌아가 제출 상태를 확인해 주세요.', code);
}

async function submitChoice(questionNo, choice, button) {
  button.disabled = true;
  try {
    const payload = await postJson(`${API_ROOT}/submissions/${encodeURIComponent(launch.submissionId)}/choice`, {
      sid: launch.sid,
      questionNo,
      choice,
      revision: launch.status.revision,
    });
    launch.status = payload;
    saveLaunch();
    renderStatus(payload);
  } catch (error) {
    if (error?.code === 'revision_conflict') await refreshStatus();
    else showRequestError(error, () => refreshStatus());
  }
}

function renderActions(status) {
  elements.actionList.textContent = '';
  (Array.isArray(status.studentActions) ? status.studentActions : []).forEach(action => {
    const card = document.createElement('section');
    card.className = 'student-test-action-card';
    const title = document.createElement('h3');
    title.textContent = `${action.questionNo}번 문항`;
    card.appendChild(title);
    if (action.action === 'student_choice') {
      const choices = document.createElement('div');
      choices.className = 'student-test-choice-grid';
      for (let choice = 1; choice <= 5; choice += 1) {
        const button = document.createElement('button');
        button.type = 'button';
        button.textContent = String(choice);
        button.setAttribute('aria-label', `${action.questionNo}번 답 ${choice}`);
        button.addEventListener('click', () => submitChoice(action.questionNo, choice, button));
        choices.appendChild(button);
      }
      card.appendChild(choices);
    } else if (action.action === 'question_recapture') {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'student-test-primary';
      button.textContent = `${action.questionNo}번 답 촬영 (${action.recaptureAttempts + 1}/2회)`;
      button.addEventListener('click', () => startCamera({ kind: 'question', questionNo: action.questionNo }));
      card.appendChild(button);
    }
    elements.actionList.appendChild(card);
  });
  showView(elements.actions);
}

function renderResult(status) {
  const result = status.result || {};
  const pendingCount = Number(result.pendingCount || 0);
  elements.resultTitle.textContent = pendingCount ? '채점 접수 완료' : '채점 완료';
  elements.resultSummary.textContent = pendingCount
    ? '보류 문항을 제외한 결과입니다. 최종 점수는 선생님 확인 후 표시됩니다.'
    : `점수 ${Number(result.score || 0)} / ${Number(result.problemCount || 20)}`;
  elements.resultCorrect.textContent = String(Number(result.correctCount || 0));
  elements.resultIncorrect.textContent = String(Number(result.incorrectCount || 0));
  elements.resultPending.textContent = String(pendingCount);
  const wrong = Array.isArray(result.wrongQuestionNos) ? result.wrongQuestionNos : [];
  elements.resultWrong.hidden = wrong.length === 0;
  elements.resultWrong.textContent = wrong.length ? `오답 문항: ${wrong.join(', ')}번` : '';
  elements.resultPendingNote.hidden = pendingCount === 0;
  elements.resultPendingNote.textContent = status.pendingMessage || '정답 여부는 선생님이 판별합니다.';
  const answerUrl = String(status.answerUrl || '').trim();
  elements.resultAnswerLink.hidden = !answerUrl;
  if (answerUrl) elements.resultAnswerLink.href = answerUrl;
  showView(elements.result);
}

function renderStatus(status) {
  launch.status = status;
  saveLaunch();
  if (pollTimer) window.clearTimeout(pollTimer);
  if (status.status === 'processing' || status.status === 'ready_to_grade') {
    showProcessing();
    pollTimer = window.setTimeout(() => void refreshStatus(), POLL_INTERVAL_MS);
    return;
  }
  if (status.retakeRequired === true || status.status === 'retake_required') {
    showView(elements.retake);
    return;
  }
  if (status.status === 'student_action_required') {
    renderActions(status);
    return;
  }
  if (status.status === 'pending_teacher' || status.status === 'finalized') {
    renderResult(status);
    return;
  }
  if (status.status === 'failed') {
    showError('OCR 처리가 중단되었습니다', '선생님께 알려 주세요. 제출 데이터는 자동으로 변경되지 않았습니다.', 'ocr_processing_failed');
    return;
  }
  showError('알 수 없는 제출 상태입니다', '학생 페이지로 돌아가 다시 확인해 주세요.', String(status.status || 'unknown_status'));
}

async function refreshStatus() {
  if (!launch?.submissionId) return;
  try {
    const query = new URLSearchParams({ sid: launch.sid });
    const status = await fetchJsonChecked(
      `${API_ROOT}/submissions/${encodeURIComponent(launch.submissionId)}?${query.toString()}`,
      'student test OCR status',
      { cache: 'no-store' },
    );
    renderStatus(status);
  } catch (error) {
    if ([400, 401, 403, 404, 409, 410, 422].includes(error?.status)) {
      showTerminalRequestError(error);
      return;
    }
    pollTimer = window.setTimeout(() => void refreshStatus(), 2000);
    elements.processingMessage.textContent = '서버 연결을 다시 확인하고 있습니다. 이 화면을 닫지 말아 주세요.';
    showProcessing(elements.processingMessage.textContent);
  }
}

async function init() {
  try {
    launch = await loadLaunch();
    elements.back.href = launch.studentPageUrl || `/student/${encodeURIComponent(launch.sid)}`;
    elements.testName.textContent = launch.testName || '테스트 답안 촬영';
    elements.testMeta.textContent = [launch.round ? `${launch.round}회차` : '', '20문항'].filter(Boolean).join(' · ');
    if (isEmbeddedBrowser()) {
      await showEmbeddedBrowserBlock();
      return;
    }
    if (launch.submissionId) {
      showProcessing();
      await refreshStatus();
    } else {
      await startCamera({ kind: 'initial' });
    }
  } catch (error) {
    showRequestError(error);
  }
}

elements.capture.addEventListener('click', () => void captureAndSubmit());
elements.retakeStart.addEventListener('click', () => void startCamera({ kind: 'retake' }));
window.addEventListener('pagehide', stopCamera);

void init();
