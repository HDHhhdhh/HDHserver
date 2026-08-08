import { state } from '../core/state.js';
import { getAdminDate } from '../core/adminDate.js';
import {
  applySearchPlaceholder,
  matchesSearchKey,
  searchKeyForText,
} from '../../shared/search.js';

const CT = { 'Content-Type': 'application/json' };
const ANN_IMAGE_MAX_BYTES = 8 * 1024 * 1024;
const ANN_IMAGE_MAX_COUNT = 10;
const ANN_IMAGE_EXTS = new Set(['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp']);
const SURVEY_QUESTION_TYPES = [
  { type: 'single', label: '객관식', detail: '하나만 선택', preview: '동그라미 선택' },
  { type: 'multiple', label: '체크박스', detail: '복수 선택', preview: '여러 개 선택' },
  { type: 'short', label: '단답형', detail: '짧은 답변', preview: '한 줄 입력' },
  { type: 'long', label: '장문형', detail: '긴 답변', preview: '여러 줄 입력' },
];
const SURVEY_QUESTION_TYPE_VALUES = new Set(SURVEY_QUESTION_TYPES.map(item => item.type));
const TARGET_LABELS = {
  slot1: '1타임',
  slot2: '2타임',
  today: '오늘 학생',
  all: '전체 학생',
  curriculum: '커리큘럼',
  grade: '학년',
  direct: '직접 선택',
};
const TARGET_MODE_ORDER = ['today', 'slot1', 'slot2', 'all', 'curriculum', 'grade', 'direct'];
const DEFAULT_EXPIRY_HOURS = 4;
const MAX_EXPIRY_HOURS = 24 * 30;

let latestRoster = [];
let todayRoster = [];
let allRoster = [];
let targetMode = 'today';
let targetFilters = { curriculum: '', subCurriculum: '', level: '', grade: '' };
let directSelected = new Set();
let selectedAnnouncementId = '';
let editingAnnouncementId = '';
let editingFallbackTargets = [];
let latestAnnouncements = [];
let refreshTimer = null;
let selectedAnnouncementImages = [];
let composeMode = 'announcement';
let surveyDraft = emptySurveyDraft();
let anonymousReplyNamePopover = null;
let anonymousReplyNameHideTimer = null;
let anonymousReplyNameRevealBound = false;
let expandedDirectQuery = '';
let expiryMode = 'hours';
let expiryHours = DEFAULT_EXPIRY_HOURS;
let expiryManual = makeDefaultManualExpiry();
let composeBackdropPointerDown = false;

const $ = (id) => document.getElementById(id);
const ANONYMOUS_REPLY_LABEL = '\uC775\uBA85';
const ANONYMOUS_REPLY_NAME_PATTERN = new RegExp(`^\\s*${ANONYMOUS_REPLY_LABEL}\\s*\\((.*)\\)\\s*$`);

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, ch => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
  }[ch]));
}

function toast(message) {
  const d = document.createElement('div');
  d.textContent = message;
  d.style.cssText = [
    'position:fixed',
    'bottom:18px',
    'left:50%',
    'transform:translateX(-50%)',
    'z-index:99999',
    'padding:8px 13px',
    'border-radius:12px',
    'background:#1e2f47',
    'color:#fff',
    'font-size:13px',
    'font-weight:700',
    'box-shadow:0 12px 30px rgba(0,0,0,.22)',
  ].join(';');
  document.body.appendChild(d);
  setTimeout(() => d.remove(), 1500);
}

function formatDateTime(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return String(iso);
  const mm = String(d.getMonth() + 1).padStart(2, '0');
  const dd = String(d.getDate()).padStart(2, '0');
  const hh = String(d.getHours()).padStart(2, '0');
  const mi = String(d.getMinutes()).padStart(2, '0');
  return `${mm}/${dd} ${hh}:${mi}`;
}

function anonymousReplyStudentName(reply) {
  const directName = String(reply?.studentName || '').trim();
  if (directName) return directName;
  const displayName = String(reply?.displayName || '').trim();
  const match = displayName.match(ANONYMOUS_REPLY_NAME_PATTERN);
  return match ? String(match[1] || '').trim() : '';
}

function isAnonymousReply(reply) {
  const displayName = String(reply?.displayName || '').trim();
  return !!reply?.anonymous || ANONYMOUS_REPLY_NAME_PATTERN.test(displayName);
}

function replyDisplayName(reply) {
  if (isAnonymousReply(reply)) return ANONYMOUS_REPLY_LABEL;
  return String(reply?.displayName || reply?.studentName || ANONYMOUS_REPLY_LABEL).trim() || ANONYMOUS_REPLY_LABEL;
}

function anonymousReplyNameAttributes(reply) {
  if (!isAnonymousReply(reply)) return '';
  const studentName = anonymousReplyStudentName(reply);
  if (!studentName) return '';
  return ` data-ann-anonymous-reply-name="${escapeHtml(studentName)}"`;
}

function ensureAnonymousReplyNamePopover() {
  if (anonymousReplyNamePopover?.isConnected) return anonymousReplyNamePopover;
  const popover = document.createElement('div');
  popover.hidden = true;
  popover.setAttribute('role', 'status');
  popover.setAttribute('aria-live', 'polite');
  popover.style.cssText = [
    'position:fixed',
    'z-index:100000',
    'max-width:min(220px, calc(100vw - 24px))',
    'padding:8px 10px',
    'border-radius:10px',
    'background:#111827',
    'color:#fff',
    'font-size:12px',
    'font-weight:800',
    'line-height:1.35',
    'box-shadow:0 12px 30px rgba(15,23,42,.28)',
    'pointer-events:none',
    'white-space:nowrap',
  ].join(';');
  document.body.appendChild(popover);
  anonymousReplyNamePopover = popover;
  return popover;
}

function hideAnonymousReplyNamePopover() {
  if (anonymousReplyNameHideTimer) {
    window.clearTimeout(anonymousReplyNameHideTimer);
    anonymousReplyNameHideTimer = null;
  }
  if (anonymousReplyNamePopover) anonymousReplyNamePopover.hidden = true;
}

function showAnonymousReplyNamePopover(studentName, clientX, clientY) {
  const name = String(studentName || '').trim();
  if (!name) return;
  const popover = ensureAnonymousReplyNamePopover();
  popover.textContent = `\uD559\uC0DD: ${name}`;
  popover.hidden = false;

  const margin = 10;
  popover.style.left = `${Math.max(margin, clientX + margin)}px`;
  popover.style.top = `${Math.max(margin, clientY + margin)}px`;

  requestAnimationFrame(() => {
    const rect = popover.getBoundingClientRect();
    const left = Math.min(Math.max(margin, clientX + margin), window.innerWidth - rect.width - margin);
    const top = Math.min(Math.max(margin, clientY + margin), window.innerHeight - rect.height - margin);
    popover.style.left = `${left}px`;
    popover.style.top = `${top}px`;
  });

  if (anonymousReplyNameHideTimer) window.clearTimeout(anonymousReplyNameHideTimer);
  anonymousReplyNameHideTimer = window.setTimeout(hideAnonymousReplyNamePopover, 3500);
}

function bindAnonymousReplyNameReveal() {
  if (anonymousReplyNameRevealBound) return;
  anonymousReplyNameRevealBound = true;

  document.addEventListener('contextmenu', (ev) => {
    const target = ev.target?.closest?.('[data-ann-anonymous-reply-name]');
    if (!target) {
      hideAnonymousReplyNamePopover();
      return;
    }
    const studentName = String(target.dataset.annAnonymousReplyName || '').trim();
    if (!studentName) return;
    ev.preventDefault();
    showAnonymousReplyNamePopover(studentName, ev.clientX, ev.clientY);
  });
  document.addEventListener('click', hideAnonymousReplyNamePopover, true);
  document.addEventListener('keydown', (ev) => {
    if (ev.key === 'Escape') hideAnonymousReplyNamePopover();
  }, true);
  document.addEventListener('scroll', hideAnonymousReplyNamePopover, true);
  window.addEventListener('resize', hideAnonymousReplyNamePopover);
}

function formatPreviewDateTime(date = new Date()) {
  const d = date instanceof Date ? date : new Date(date);
  if (Number.isNaN(d.getTime())) return '';
  const month = d.getMonth() + 1;
  const day = d.getDate();
  const hh = String(d.getHours()).padStart(2, '0');
  const mi = String(d.getMinutes()).padStart(2, '0');
  return `${month}월 ${day}일 ${hh}:${mi}`;
}

function makeDefaultManualExpiry(base = new Date(Date.now() + DEFAULT_EXPIRY_HOURS * 60 * 60 * 1000)) {
  return {
    month: String(base.getMonth() + 1),
    day: String(base.getDate()),
    hour: String(base.getHours()),
  };
}

function clampInt(value, fallback, min, max) {
  const num = Number.parseInt(String(value ?? ''), 10);
  if (!Number.isFinite(num)) return fallback;
  return Math.min(max, Math.max(min, num));
}

function pad2(value) {
  return String(value).padStart(2, '0');
}

function formatDeadlineDisplay(date) {
  const d = date instanceof Date ? date : new Date(date);
  if (Number.isNaN(d.getTime())) return '';
  return `${d.getMonth() + 1}월 ${d.getDate()}일 ${pad2(d.getHours())}시 마감`;
}

function expirySummaryText() {
  if (expiryMode === 'absolute') {
    const candidate = buildManualExpiryDate({ allowPast: true });
    return candidate ? formatDeadlineDisplay(candidate) : '월/일/시 마감';
  }
  return `${expiryHours || DEFAULT_EXPIRY_HOURS}시간 후 마감`;
}

function buildManualExpiryDate({ allowPast = false } = {}) {
  const month = clampInt(expiryManual.month, 0, 1, 12);
  const day = clampInt(expiryManual.day, 0, 1, 31);
  const hour = clampInt(expiryManual.hour, 0, 0, 23);
  if (!month || !day) return null;
  const now = new Date();
  const candidate = new Date(now.getFullYear(), month - 1, day, hour, 0, 0, 0);
  if (
    candidate.getMonth() !== month - 1 ||
    candidate.getDate() !== day ||
    candidate.getHours() !== hour
  ) {
    return null;
  }
  if (!allowPast && candidate.getTime() <= Date.now()) return null;
  return candidate;
}

function resolveExpiryDate() {
  if (expiryMode === 'absolute') {
    const candidate = buildManualExpiryDate();
    if (!candidate) {
      return { ok: false, message: '마감 시간을 현재보다 미래의 월/일/시로 입력해 주세요.' };
    }
    return { ok: true, date: candidate };
  }
  const hours = clampInt(expiryHours, DEFAULT_EXPIRY_HOURS, 1, MAX_EXPIRY_HOURS);
  expiryHours = hours;
  return { ok: true, date: new Date(Date.now() + hours * 60 * 60 * 1000) };
}

function resetExpiryDefaults() {
  expiryMode = 'hours';
  expiryHours = DEFAULT_EXPIRY_HOURS;
  expiryManual = makeDefaultManualExpiry();
  syncExpiryUi();
}

function setExpiryFromAnnouncement(item) {
  const parsed = new Date(item?.expiresAt || '');
  if (Number.isNaN(parsed.getTime())) {
    resetExpiryDefaults();
    return;
  }
  expiryMode = 'absolute';
  expiryManual = {
    month: String(parsed.getMonth() + 1),
    day: String(parsed.getDate()),
    hour: String(parsed.getHours()),
  };
  const diffHours = Math.ceil((parsed.getTime() - Date.now()) / (60 * 60 * 1000));
  expiryHours = diffHours > 0 ? Math.min(MAX_EXPIRY_HOURS, diffHours) : DEFAULT_EXPIRY_HOURS;
  syncExpiryUi();
}

function formatBytes(value) {
  const size = Number(value || 0);
  if (!Number.isFinite(size) || size <= 0) return '';
  if (size < 1024) return `${size}B`;
  if (size < 1024 * 1024) return `${Math.round(size / 1024)}KB`;
  return `${(size / (1024 * 1024)).toFixed(size >= 10 * 1024 * 1024 ? 0 : 1)}MB`;
}

function imageFileName(image) {
  return String(image?.originalName || image?.name || '첨부 이미지').trim() || '첨부 이미지';
}

function imageFileMeta(image) {
  return [imageFileName(image), formatBytes(image?.size)].filter(Boolean).join(' · ');
}

function imageCollectionMeta(images) {
  const list = Array.isArray(images) ? images : [];
  if (!list.length) return '';
  const totalSize = list.reduce((sum, image) => sum + (Number(image?.size || 0) || 0), 0);
  if (list.length === 1) return imageFileMeta(list[0]);
  return [`이미지 ${list.length}장`, formatBytes(totalSize)].filter(Boolean).join(' · ');
}

function isSupportedImageFile(file) {
  if (!file) return false;
  const ext = String(file.name || '').split('.').pop().toLowerCase();
  return String(file.type || '').startsWith('image/') || ANN_IMAGE_EXTS.has(ext);
}

function normalizeImage(image) {
  if (!image || typeof image !== 'object') return null;
  const url = String(image.url || '').trim();
  if (!url) return null;
  return {
    name: String(image.name || image.originalName || 'announcement-image').trim(),
    originalName: String(image.originalName || image.name || '첨부 이미지').trim(),
    path: String(image.path || '').trim(),
    url,
    mime: String(image.mime || '').trim(),
    size: Number(image.size || 0) || 0,
  };
}

function normalizeImages(images, fallback = null) {
  const source = Array.isArray(images) ? images : [];
  const normalized = source.map(normalizeImage).filter(Boolean);
  if (!normalized.length) {
    const single = normalizeImage(fallback);
    if (single) normalized.push(single);
  }
  const seen = new Set();
  return normalized.filter((image) => {
    const key = image.url || image.path || image.name;
    if (!key || seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function makeSurveyOption(text = '') {
  return {
    id: `o_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 7)}`,
    text,
  };
}

function normalizeSurveyQuestionType(type) {
  const value = String(type || '').trim();
  return SURVEY_QUESTION_TYPE_VALUES.has(value) ? value : 'single';
}

function isChoiceSurveyType(type) {
  const value = normalizeSurveyQuestionType(type);
  return value === 'single' || value === 'multiple';
}

function surveyTypeMeta(type) {
  const value = normalizeSurveyQuestionType(type);
  return SURVEY_QUESTION_TYPES.find(item => item.type === value) || SURVEY_QUESTION_TYPES[0];
}

function makeSurveyQuestion(type = 'single') {
  const safeType = normalizeSurveyQuestionType(type);
  const question = {
    id: `q_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 7)}`,
    text: '',
    type: safeType,
    required: true,
    options: [],
  };
  if (isChoiceSurveyType(safeType)) {
    question.options = [makeSurveyOption(''), makeSurveyOption('')];
  }
  return question;
}

function emptySurveyDraft() {
  return {
    status: 'public',
    anonymous: false,
    allowMultiple: false,
    questions: [makeSurveyQuestion('single')],
  };
}

function isSurveyItem(item) {
  return !!item?.survey || item?.kind === 'survey';
}

function surveyStatusLabel(status) {
  if (status === 'draft') return '작성 중';
  if (status === 'closed') return '마감';
  return '공개';
}

function surveyTypeLabel(type) {
  return {
    single: '객관식 단일',
    multiple: '객관식 복수',
    short: '주관식 단답',
    long: '주관식 장문',
  }[normalizeSurveyQuestionType(type)] || '질문';
}

function normalizeSurveyDraft({ showAlert = false } = {}) {
  const draft = surveyDraft && typeof surveyDraft === 'object' ? surveyDraft : emptySurveyDraft();
  const questions = Array.isArray(draft.questions) ? draft.questions : [];
  const normalized = [];

  for (let idx = 0; idx < questions.length; idx += 1) {
    const question = questions[idx] || {};
    const text = String(question.text || '').trim();
    const type = normalizeSurveyQuestionType(question.type);
    if (!text) {
      if (showAlert) alert(`${idx + 1}번 질문 문구를 입력해 주세요.`);
      return null;
    }
    const row = {
      id: String(question.id || `q_${idx + 1}`),
      text,
      type,
      required: question.required !== false,
      options: [],
    };
    if (isChoiceSurveyType(type)) {
      const options = (Array.isArray(question.options) ? question.options : [])
        .map((option, optIdx) => ({
          id: String(option?.id || `o_${optIdx + 1}`),
          text: String(option?.text || '').trim(),
        }))
        .filter(option => option.text);
      if (options.length < 2) {
        if (showAlert) alert(`${idx + 1}번 객관식 질문은 선택지가 최소 2개 필요합니다.`);
        return null;
      }
      row.options = options;
    }
    normalized.push(row);
  }

  if (!normalized.length) {
    if (showAlert) alert('설문 질문을 1개 이상 추가해 주세요.');
    return null;
  }

  return {
    status: ['draft', 'public', 'closed'].includes(draft.status) ? draft.status : 'public',
    anonymous: !!draft.anonymous,
    allowMultiple: !!draft.allowMultiple,
    questions: normalized,
  };
}

function cloneSurveyForDraft(survey) {
  if (!survey || typeof survey !== 'object') return emptySurveyDraft();
  const draft = {
    status: ['draft', 'public', 'closed'].includes(survey.status) ? survey.status : 'public',
    anonymous: !!survey.anonymous,
    allowMultiple: !!survey.allowMultiple,
    questions: (Array.isArray(survey.questions) ? survey.questions : []).map(question => {
      const type = normalizeSurveyQuestionType(question?.type);
      return {
        id: String(question?.id || makeSurveyQuestion(type).id),
        text: String(question?.text || ''),
        type,
        required: question?.required !== false,
        options: (Array.isArray(question?.options) ? question.options : []).map(option => ({
          id: String(option?.id || makeSurveyOption('').id),
          text: String(option?.text || ''),
        })),
      };
    }),
  };
  if (!draft.questions.length) draft.questions.push(makeSurveyQuestion('single'));
  return draft;
}

function ensureChoiceOptions(question) {
  if (!Array.isArray(question.options)) question.options = [];
  while (question.options.length < 2) {
    question.options.push(makeSurveyOption(''));
  }
}

function setSurveyQuestionType(question, type) {
  if (!question) return;
  question.type = normalizeSurveyQuestionType(type);
  if (isChoiceSurveyType(question.type)) {
    ensureChoiceOptions(question);
  } else {
    question.options = [];
  }
}

function duplicateSurveyQuestion(qIndex) {
  const source = surveyDraft.questions?.[qIndex];
  if (!source) return;
  const copy = {
    ...source,
    id: makeSurveyQuestion(source.type).id,
    text: source.text ? `${source.text} 복사본` : '',
    options: (Array.isArray(source.options) ? source.options : []).map(option => ({
      id: makeSurveyOption('').id,
      text: String(option?.text || ''),
    })),
  };
  surveyDraft.questions.splice(qIndex + 1, 0, copy);
}

function renderSurveyChip() {
  const openBtn = $('annSurveyBuilderOpen');
  const chip = $('annSurveyChip');
  const isSurvey = composeMode === 'survey';
  if (openBtn) openBtn.hidden = !isSurvey;
  if (!chip) return;
  chip.hidden = !isSurvey;
  if (!isSurvey) return;
  const count = Array.isArray(surveyDraft.questions) ? surveyDraft.questions.length : 0;
  const valid = !!normalizeSurveyDraft();
  chip.textContent = valid ? `질문 ${count}개 준비` : `질문 ${count}개 편집 필요`;
  chip.classList.toggle('needs-work', !valid);
}

function renderSurveyBuilder() {
  const host = $('annSurveyQuestions');
  if (!host) return;

  const status = $('annSurveyStatus');
  const anonymous = $('annSurveyAnonymous');
  const allowMultiple = $('annSurveyAllowMultiple');
  if (status) status.value = surveyDraft.status || 'public';
  if (anonymous) anonymous.checked = !!surveyDraft.anonymous;
  if (allowMultiple) allowMultiple.checked = !!surveyDraft.allowMultiple;

  const questions = Array.isArray(surveyDraft.questions) ? surveyDraft.questions : [];
  host.innerHTML = questions.map((question, qIndex) => {
    const type = normalizeSurveyQuestionType(question.type);
    const needsOptions = isChoiceSurveyType(type);
    const options = needsOptions ? (Array.isArray(question.options) ? question.options : []) : [];
    return `
      <article class="ann-survey-question-card" data-survey-q="${qIndex}">
        <div class="ann-survey-question-head">
          <strong>질문 ${qIndex + 1}</strong>
          <div class="ann-survey-question-actions">
            <button type="button" data-survey-move="up" ${qIndex === 0 ? 'disabled' : ''}>↑</button>
            <button type="button" data-survey-move="down" ${qIndex === questions.length - 1 ? 'disabled' : ''}>↓</button>
            <button type="button" data-survey-delete-question ${questions.length <= 1 ? 'disabled' : ''}>삭제</button>
          </div>
        </div>
        <label class="ann-survey-field">
          <span>질문 문구</span>
          <input type="text" data-survey-question-text value="${escapeHtml(question.text || '')}" placeholder="학생에게 물어볼 내용을 입력">
        </label>
        <div class="ann-survey-question-meta">
          <label class="ann-survey-field">
            <span>질문 유형</span>
            <select data-survey-question-type>
              <option value="single" ${type === 'single' ? 'selected' : ''}>객관식 단일 선택</option>
              <option value="multiple" ${type === 'multiple' ? 'selected' : ''}>객관식 복수 선택</option>
              <option value="short" ${type === 'short' ? 'selected' : ''}>주관식 단답형</option>
              <option value="long" ${type === 'long' ? 'selected' : ''}>주관식 장문형</option>
            </select>
          </label>
          <label class="ann-survey-check">
            <input type="checkbox" data-survey-required ${question.required !== false ? 'checked' : ''}>
            필수 응답
          </label>
        </div>
        ${needsOptions ? `
          <div class="ann-survey-options" data-survey-options>
            ${options.map((option, optIndex) => `
              <div class="ann-survey-option-row" data-survey-option="${optIndex}">
                <span>${optIndex + 1}</span>
                <input type="text" data-survey-option-text value="${escapeHtml(option.text || '')}" placeholder="선택지 내용">
                <button type="button" data-survey-delete-option ${options.length <= 2 ? 'disabled' : ''}>삭제</button>
              </div>
            `).join('')}
            <button class="ann-survey-add-option" type="button" data-survey-add-option>+ 선택지 추가</button>
          </div>
        ` : `
          <div class="ann-survey-text-preview">${type === 'long' ? '학생에게 장문 입력 박스가 표시됩니다.' : '학생에게 짧은 답변 입력칸이 표시됩니다.'}</div>
        `}
      </article>
    `;
  }).join('');

  renderSurveyChip();
}

function surveyQuestionCompleteness(question) {
  if (!question || !String(question.text || '').trim()) return false;
  if (!isChoiceSurveyType(question.type)) return true;
  const options = Array.isArray(question.options) ? question.options : [];
  return options.filter(option => String(option?.text || '').trim()).length >= 2;
}

function expandedSurveyReadyState() {
  const title = String($('annTitle')?.value || '').trim();
  const content = String($('annContent')?.value || '').trim();
  const questions = Array.isArray(surveyDraft.questions) ? surveyDraft.questions : [];
  const targetCount = rowsForMode().length;
  const validSurvey = !!normalizeSurveyDraft();
  return {
    title,
    content,
    questions,
    targetCount,
    requiredCount: questions.filter(question => question?.required !== false).length,
    validSurvey,
    ready: !!title && !!content && targetCount > 0 && validSurvey,
  };
}

function renderExpandedTargetModeButton(mode) {
  const label = TARGET_LABELS[mode] || '대상';
  const count = rowsForMode(mode).length;
  const active = targetMode === mode;
  return `
    <button type="button" data-expanded-target-mode="${escapeHtml(mode)}" class="${active ? 'is-active' : ''}" aria-pressed="${active ? 'true' : 'false'}">
      <strong>${escapeHtml(label)}</strong>
      <span>${count}명</span>
    </button>
  `;
}

function renderExpandedDirectList() {
  const host = document.querySelector('[data-expanded-direct-list]');
  if (!host) return;
  const rows = rosterBaseRows().filter(row => matchesSearchKey(row.key, expandedDirectQuery));
  if (!rows.length) {
    host.innerHTML = '<div class="ann-empty">선택 가능한 학생이 없습니다.</div>';
    return;
  }
  host.innerHTML = rows.map(row => `
    <label class="ann-survey-expanded-direct-row">
      <input type="checkbox" value="${escapeHtml(row.sid)}" ${directSelected.has(row.sid) ? 'checked' : ''}>
      <span>
        <strong>${escapeHtml(row.name)}</strong>
        <em>${escapeHtml([row.slot, row.school, row.grade, rowCurriculumLabel(row)].filter(Boolean).join(' · '))}</em>
      </span>
    </label>
  `).join('');
}

function renderExpandedQuestionCard(question, qIndex, questions) {
  const type = normalizeSurveyQuestionType(question.type);
  const meta = surveyTypeMeta(type);
  const needsOptions = isChoiceSurveyType(type);
  const options = needsOptions ? (Array.isArray(question.options) ? question.options : []) : [];
  const complete = surveyQuestionCompleteness(question);
  return `
    <article class="ann-survey-expanded-question ${complete ? '' : 'needs-work'}" data-survey-q="${qIndex}">
      <div class="ann-survey-expanded-question-head">
        <div>
          <span>질문 ${qIndex + 1}</span>
          <strong>${escapeHtml(meta.label)}</strong>
          <em>${escapeHtml(meta.detail)}</em>
        </div>
        <div class="ann-survey-expanded-question-actions">
          <button type="button" data-survey-move="up" ${qIndex === 0 ? 'disabled' : ''} aria-label="질문 위로 이동">↑</button>
          <button type="button" data-survey-move="down" ${qIndex === questions.length - 1 ? 'disabled' : ''} aria-label="질문 아래로 이동">↓</button>
          <button type="button" data-survey-duplicate-question>복제</button>
          <button type="button" data-survey-delete-question ${questions.length <= 1 ? 'disabled' : ''}>삭제</button>
        </div>
      </div>

      <label class="ann-survey-field ann-survey-expanded-question-text">
        <span>질문</span>
        <input type="text" data-survey-question-text value="${escapeHtml(question.text || '')}" placeholder="학생에게 물어볼 내용을 입력">
      </label>

      <div class="ann-survey-expanded-question-meta">
        <label class="ann-survey-field">
          <span>유형</span>
          <select data-survey-question-type>
            ${SURVEY_QUESTION_TYPES.map(item => `
              <option value="${escapeHtml(item.type)}" ${type === item.type ? 'selected' : ''}>${escapeHtml(item.label)} · ${escapeHtml(item.detail)}</option>
            `).join('')}
          </select>
        </label>
        <label class="ann-survey-check">
          <input type="checkbox" data-survey-required ${question.required !== false ? 'checked' : ''}>
          필수 응답
        </label>
      </div>

      ${needsOptions ? `
        <div class="ann-survey-expanded-options" data-survey-options>
          ${options.map((option, optIndex) => `
            <div class="ann-survey-option-row" data-survey-option="${optIndex}">
              <span>${optIndex + 1}</span>
              <input type="text" data-survey-option-text value="${escapeHtml(option.text || '')}" placeholder="선택지 내용">
              <button type="button" data-survey-delete-option ${options.length <= 2 ? 'disabled' : ''}>삭제</button>
            </div>
          `).join('')}
          <button class="ann-survey-add-option" type="button" data-survey-add-option>+ 선택지 추가</button>
        </div>
      ` : `
        <div class="ann-survey-expanded-text-preview">${type === 'long' ? '학생 화면에는 여러 줄 답변 박스가 표시됩니다.' : '학생 화면에는 한 줄 답변 입력칸이 표시됩니다.'}</div>
      `}
    </article>
  `;
}

function renderExpandedSurveyPreviewQuestion(question, qIndex) {
  const qid = String(question.id || `q${qIndex + 1}`);
  const type = normalizeSurveyQuestionType(question.type);
  const required = question.required !== false;
  const meta = surveyTypeMeta(type);
  const options = Array.isArray(question.options) ? question.options : [];
  if (isChoiceSurveyType(type)) {
    const inputType = type === 'single' ? 'radio' : 'checkbox';
    return `
      <fieldset class="ann-survey-preview-question">
        <legend>
          <span>${escapeHtml(question.text || `질문 ${qIndex + 1}`)}</span>
          <em>${required ? '필수' : '선택'} · ${escapeHtml(meta.detail)}</em>
        </legend>
        <div class="ann-survey-preview-options">
          ${options.map((option, optIndex) => `
            <label>
              <input type="${inputType}" name="preview_${escapeHtml(qid)}" disabled>
              <span>${escapeHtml(option.text || `선택지 ${optIndex + 1}`)}</span>
            </label>
          `).join('')}
        </div>
      </fieldset>
    `;
  }
  return `
    <fieldset class="ann-survey-preview-question">
      <legend>
        <span>${escapeHtml(question.text || `질문 ${qIndex + 1}`)}</span>
        <em>${required ? '필수' : '선택'} · ${escapeHtml(meta.detail)}</em>
      </legend>
      ${type === 'long'
        ? '<textarea rows="3" placeholder="답변을 입력하세요." disabled></textarea>'
        : '<input type="text" placeholder="답변을 입력하세요." disabled>'}
    </fieldset>
  `;
}

function renderExpandedSurveyPreviewHtml(readyState) {
  const questions = Array.isArray(surveyDraft.questions) ? surveyDraft.questions : [];
  const status = surveyStatusLabel(surveyDraft.status);
  const title = readyState.title || '설문 제목';
  const content = readyState.content || '학생에게 보여줄 설문 설명';
  return `
    <div class="ann-survey-preview-paper">
      <div class="ann-survey-preview-head">
        <strong>${escapeHtml(title)}</strong>
        <p>${escapeHtml(content)}</p>
        <span>${escapeHtml(status)} · ${surveyDraft.anonymous ? '익명 응답' : '실명 응답'} · ${surveyDraft.allowMultiple ? '여러 번 제출' : '1회 제출'}</span>
      </div>
      <div class="ann-survey-preview-list">
        ${questions.map((question, qIndex) => renderExpandedSurveyPreviewQuestion(question, qIndex)).join('')}
      </div>
      <button type="button" disabled>설문 제출</button>
    </div>
  `;
}

function renderExpiryControls({ compact = false } = {}) {
  const rootClass = compact ? 'announcement-expiry' : 'ann-survey-expanded-block ann-survey-expanded-expiry';
  return `
    <div class="${rootClass}">
      <div class="announcement-expiry-head">
        <strong>마감 시간</strong>
        <span data-ann-expiry-summary>${escapeHtml(expirySummaryText())}</span>
      </div>
      <div class="announcement-expiry-modes" role="group" aria-label="마감 시간 방식">
        <button type="button" data-ann-expiry-mode="hours" class="${expiryMode === 'hours' ? 'is-active' : ''}">#시간 후</button>
        <button type="button" data-ann-expiry-mode="absolute" class="${expiryMode === 'absolute' ? 'is-active' : ''}">월/일/시</button>
      </div>
      <div class="announcement-expiry-panel" data-ann-expiry-panel="hours" ${expiryMode === 'hours' ? '' : 'hidden'}>
        <label>
          <span>몇 시간 후</span>
          <input type="number" min="1" max="${MAX_EXPIRY_HOURS}" step="1" data-ann-expiry-hours value="${escapeHtml(expiryHours)}">
        </label>
      </div>
      <div class="announcement-expiry-panel is-absolute" data-ann-expiry-panel="absolute" ${expiryMode === 'absolute' ? '' : 'hidden'}>
        <label>
          <span>월</span>
          <input type="number" min="1" max="12" step="1" data-ann-expiry-month value="${escapeHtml(expiryManual.month)}">
        </label>
        <label>
          <span>일</span>
          <input type="number" min="1" max="31" step="1" data-ann-expiry-day value="${escapeHtml(expiryManual.day)}">
        </label>
        <label>
          <span>시</span>
          <input type="number" min="0" max="23" step="1" data-ann-expiry-hour value="${escapeHtml(expiryManual.hour)}">
        </label>
      </div>
    </div>
  `;
}

function renderExpandedSurveyBuilder() {
  const mount = $('annComposeExpandMount');
  if (!mount || composeMode !== 'survey') return;
  const readyState = expandedSurveyReadyState();
  const targetLabel = targetSelectionLabel();
  mount.innerHTML = `
    <div class="ann-survey-expanded-builder" data-expanded-survey-builder>
      <section class="ann-survey-expanded-setup" aria-label="설문 기본 설정">
        <div class="ann-survey-expanded-block">
          <div class="ann-survey-expanded-block-head">
            <strong>양식</strong>
            <span>${readyState.validSurvey ? '문항 준비됨' : '문항 확인 필요'}</span>
          </div>
          <label class="ann-survey-field">
            <span>설문 제목</span>
            <input type="text" data-expanded-title value="${escapeHtml($('annTitle')?.value || '')}" placeholder="예: 5월 수업 만족도 조사">
          </label>
          <label class="ann-survey-field">
            <span>설문 설명</span>
            <textarea rows="5" data-expanded-content placeholder="학생에게 보여줄 안내 문구">${escapeHtml($('annContent')?.value || '')}</textarea>
          </label>
        </div>

        <div class="ann-survey-expanded-block">
          <div class="ann-survey-expanded-block-head">
            <strong>대상</strong>
            <span>${escapeHtml(targetLabel)} · ${readyState.targetCount}명</span>
          </div>
          <div class="ann-survey-expanded-target-tabs" role="group" aria-label="설문 대상">
            ${TARGET_MODE_ORDER.map(renderExpandedTargetModeButton).join('')}
          </div>
          <div class="ann-survey-expanded-filter" ${targetMode === 'curriculum' ? '' : 'hidden'}>
            <label>
              <span>과목</span>
              <select data-ann-target-filter="curriculum"></select>
            </label>
            <label>
              <span>과정</span>
              <select data-ann-target-filter="subCurriculum"></select>
            </label>
            <label>
              <span>난이도</span>
              <select data-ann-target-filter="level"></select>
            </label>
          </div>
          <div class="ann-survey-expanded-filter" ${targetMode === 'grade' ? '' : 'hidden'}>
            <label>
              <span>학년</span>
              <select data-ann-target-filter="grade"></select>
            </label>
          </div>
          <div class="ann-survey-expanded-direct" ${targetMode === 'direct' ? '' : 'hidden'}>
            <input type="search" data-expanded-direct-search value="${escapeHtml(expandedDirectQuery)}" placeholder="학생 검색">
            <div>
              <button type="button" data-expanded-select-visible>보이는 학생 선택</button>
              <button type="button" data-expanded-clear-selected>선택 해제</button>
            </div>
            <div class="ann-survey-expanded-direct-list" data-expanded-direct-list></div>
          </div>
        </div>

        ${renderExpiryControls()}

        <div class="ann-survey-expanded-block">
          <div class="ann-survey-expanded-block-head">
            <strong>응답 설정</strong>
            <span>${escapeHtml(surveyStatusLabel(surveyDraft.status))}</span>
          </div>
          <label class="ann-survey-field">
            <span>공개 상태</span>
            <select data-expanded-survey-status>
              <option value="public" ${surveyDraft.status === 'public' ? 'selected' : ''}>공개</option>
              <option value="draft" ${surveyDraft.status === 'draft' ? 'selected' : ''}>작성 중</option>
              <option value="closed" ${surveyDraft.status === 'closed' ? 'selected' : ''}>마감</option>
            </select>
          </label>
          <label class="ann-survey-switch">
            <input type="checkbox" data-expanded-survey-anonymous ${surveyDraft.anonymous ? 'checked' : ''}>
            <span>
              <strong>익명 응답</strong>
              <em>결과에서 이름을 숨깁니다.</em>
            </span>
          </label>
          <label class="ann-survey-switch">
            <input type="checkbox" data-expanded-survey-multiple ${surveyDraft.allowMultiple ? 'checked' : ''}>
            <span>
              <strong>중복 제출 허용</strong>
              <em>학생이 추가 응답을 보낼 수 있습니다.</em>
            </span>
          </label>
        </div>
      </section>

      <section class="ann-survey-expanded-workbench" aria-label="설문 질문 편집">
        <div class="ann-survey-expanded-toolbar">
          <div>
            <strong>질문 구성</strong>
            <span>총 ${readyState.questions.length}개 · 필수 ${readyState.requiredCount}개</span>
          </div>
          <div class="ann-survey-type-palette" role="group" aria-label="질문 추가">
            ${SURVEY_QUESTION_TYPES.map(item => `
              <button type="button" data-expanded-add-question="${escapeHtml(item.type)}">
                <strong>${escapeHtml(item.label)}</strong>
                <span>${escapeHtml(item.detail)}</span>
              </button>
            `).join('')}
          </div>
        </div>
        <div class="ann-survey-expanded-questions" data-expanded-survey-questions>
          ${readyState.questions.map((question, qIndex) => renderExpandedQuestionCard(question, qIndex, readyState.questions)).join('')}
        </div>
      </section>

      <aside class="ann-survey-expanded-preview" aria-label="학생 화면 미리보기">
        <div class="ann-survey-expanded-block-head">
          <strong>미리보기</strong>
          <span>${readyState.ready ? '등록 가능' : '작성 중'}</span>
        </div>
        ${renderExpandedSurveyPreviewHtml(readyState)}
      </aside>

      <div class="ann-survey-expanded-footer">
        <div>
          <strong>${readyState.ready ? '설문을 등록할 수 있습니다.' : '제목, 설명, 대상, 질문을 확인해 주세요.'}</strong>
          <span>현재 작은 설문 박스 위치는 유지되고, 이 화면의 입력값이 등록에 사용됩니다.</span>
        </div>
        <button type="button" class="btn secondary" data-expanded-reset>초기화</button>
        <button type="button" class="btn secondary" data-expanded-apply>작게 보기</button>
        <button type="button" class="btn" data-expanded-publish>${editingAnnouncementId ? '수정 완료' : '설문 등록'}</button>
      </div>
    </div>
  `;
  renderTargetFilterOptions();
  syncExpiryUi();
  renderExpandedDirectList();
}

function refreshExpandedSurveyDerivedViews() {
  const builder = document.querySelector('[data-expanded-survey-builder]');
  if (!builder) return;
  const readyState = expandedSurveyReadyState();
  const preview = builder.querySelector('.ann-survey-expanded-preview');
  if (preview) {
    preview.innerHTML = `
      <div class="ann-survey-expanded-block-head">
        <strong>미리보기</strong>
        <span>${readyState.ready ? '등록 가능' : '작성 중'}</span>
      </div>
      ${renderExpandedSurveyPreviewHtml(readyState)}
    `;
  }
  const footerText = builder.querySelector('.ann-survey-expanded-footer > div');
  if (footerText) {
    footerText.innerHTML = `
      <strong>${readyState.ready ? '설문을 등록할 수 있습니다.' : '제목, 설명, 대상, 질문을 확인해 주세요.'}</strong>
      <span>현재 작은 설문 박스 위치는 유지되고, 이 화면의 입력값이 등록에 사용됩니다.</span>
    `;
  }
  const questionCount = builder.querySelector('.ann-survey-expanded-toolbar > div span');
  if (questionCount) questionCount.textContent = `총 ${readyState.questions.length}개 · 필수 ${readyState.requiredCount}개`;
  const formState = builder.querySelector('.ann-survey-expanded-setup .ann-survey-expanded-block:first-child .ann-survey-expanded-block-head span');
  if (formState) formState.textContent = readyState.validSurvey ? '문항 준비됨' : '문항 확인 필요';
  const targetState = builder.querySelector('.ann-survey-expanded-setup .ann-survey-expanded-block:nth-child(2) .ann-survey-expanded-block-head span');
  if (targetState) targetState.textContent = `${targetSelectionLabel()} · ${readyState.targetCount}명`;
}

function openSurveyBuilder() {
  if (composeMode !== 'survey') setComposeMode('survey');
  renderSurveyBuilder();
  const modal = $('annSurveyModal');
  if (modal) modal.hidden = false;
  requestAnimationFrame(() => {
    $('annSurveyQuestions')?.querySelector('input, select, button')?.focus?.();
  });
}

function closeSurveyBuilder() {
  const modal = $('annSurveyModal');
  if (modal) modal.hidden = true;
  $('annSurveyBuilderOpen')?.focus();
}

function ensureAnnouncementControls() {
  const targetOptions = document.querySelector('#annTargetMenu .announcement-target-options');
  if (targetOptions) {
    targetOptions.innerHTML = TARGET_MODE_ORDER.map(mode => `
      <button type="button" data-target-mode="${escapeHtml(mode)}">${escapeHtml(TARGET_LABELS[mode] || mode)}</button>
    `).join('');
  }

  const directPicker = $('annDirectPicker');
  if (directPicker && !$('annCurriculumPicker')) {
    directPicker.insertAdjacentHTML('afterend', `
      <div id="annCurriculumPicker" class="announcement-target-filter" hidden>
        <label>
          <span>과목</span>
          <select data-ann-target-filter="curriculum"></select>
        </label>
        <label>
          <span>과정</span>
          <select data-ann-target-filter="subCurriculum"></select>
        </label>
        <label>
          <span>난이도</span>
          <select data-ann-target-filter="level"></select>
        </label>
      </div>
      <div id="annGradePicker" class="announcement-target-filter is-grade" hidden>
        <label>
          <span>학년</span>
          <select data-ann-target-filter="grade"></select>
        </label>
      </div>
    `);
  }

  const compose = document.querySelector('.announcement-compose');
  const target = compose?.querySelector('.announcement-target');
  if (compose && target && !compose.querySelector('.announcement-expiry')) {
    target.insertAdjacentHTML('afterend', renderExpiryControls({ compact: true }));
  }
  renderTargetFilterOptions();
  syncExpiryUi();
}

function syncExpiryUi() {
  document.querySelectorAll('[data-ann-expiry-mode]').forEach((button) => {
    const active = button.dataset.annExpiryMode === expiryMode;
    button.classList.toggle('is-active', active);
    button.setAttribute('aria-pressed', active ? 'true' : 'false');
  });
  document.querySelectorAll('[data-ann-expiry-panel]').forEach((panel) => {
    panel.hidden = panel.dataset.annExpiryPanel !== expiryMode;
  });
  document.querySelectorAll('[data-ann-expiry-hours]').forEach((input) => { input.value = String(expiryHours); });
  document.querySelectorAll('[data-ann-expiry-month]').forEach((input) => { input.value = String(expiryManual.month); });
  document.querySelectorAll('[data-ann-expiry-day]').forEach((input) => { input.value = String(expiryManual.day); });
  document.querySelectorAll('[data-ann-expiry-hour]').forEach((input) => { input.value = String(expiryManual.hour); });
  document.querySelectorAll('[data-ann-expiry-summary]').forEach((summary) => {
    summary.textContent = expirySummaryText();
    summary.title = expirySummaryText();
  });
}

function setComposeMode(mode) {
  composeMode = mode === 'survey' ? 'survey' : 'announcement';
  const isSurvey = composeMode === 'survey';
  if (!isSurvey) {
    editingAnnouncementId = '';
    editingFallbackTargets = [];
  }
  const heading = $('announcement-title');
  const sub = document.querySelector('.announcement-sub');
  const toggle = $('annModeToggle');
  const title = $('annTitle');
  const content = $('annContent');
  const publish = $('annPublish');
  const boardSummary = document.querySelector('#annBoardShell summary');
  const boardTitle = document.querySelector('.announcement-board-title');

  if (heading) heading.textContent = isSurvey ? '설문조사' : '공지';
  if (sub) sub.textContent = isSurvey ? '대상과 마감 시간을 선택해 설문 표시' : '대상과 마감 시간을 선택해 표시';
  if (toggle) {
    toggle.textContent = isSurvey ? '공지' : '설문조사';
    toggle.setAttribute('aria-pressed', isSurvey ? 'true' : 'false');
  }
  if (title) title.placeholder = isSurvey ? '설문 제목' : '공지 제목';
  if (content) content.placeholder = isSurvey ? '학생에게 보여줄 설문 설명' : '학생에게 전달할 내용';
  if (publish) publish.textContent = isSurvey ? '등록' : '등록';
  if (boardSummary) boardSummary.textContent = isSurvey ? '발행한 설문 · 결과 확인' : '발행한 공지 · 답장 확인';
  if (boardTitle) boardTitle.textContent = isSurvey ? '발행한 설문' : '발행한 공지';

  renderSurveyChip();
  selectedAnnouncementId = '';
  renderAnnouncementList(latestAnnouncements);
  syncEditStateUi();
}

function isComposeExpandOpen() {
  const modal = $('annComposeExpandModal');
  return !!modal && !modal.hidden;
}

function syncComposeExpandUi() {
  const isSurvey = composeMode === 'survey';
  const isEditing = !!editingAnnouncementId;
  const title = $('annComposeExpandTitle');
  const meta = $('annComposeExpandMeta');
  const toggle = $('annComposeModeToggle');
  if (title) title.textContent = isSurvey ? '설문조사 등록' : '공지 등록';
  if (title && isEditing) title.textContent = isSurvey ? '설문조사 수정' : '공지 수정';
  if (meta) {
    meta.textContent = isSurvey
      ? '질문 구성과 대상을 넓은 화면에서 확인하고 설문을 등록합니다.'
      : '제목, 내용, 대상, 이미지를 넓은 화면에서 확인하고 공지를 등록합니다.';
  }
  if (meta && isEditing) {
    meta.textContent = '수정한 내용은 학생 페이지의 공지/설문 팝업과 관리자 답장판에 바로 반영됩니다.';
  }
  if (toggle) {
    toggle.textContent = isSurvey ? '공지' : '설문조사';
    toggle.setAttribute('aria-pressed', isSurvey ? 'true' : 'false');
  }
}

function syncEditStateUi() {
  const isEditing = !!editingAnnouncementId;
  const publish = $('annPublish');
  if (publish) publish.textContent = isEditing ? '수정 완료' : '등록';
  [$('annModeToggle'), $('annComposeModeToggle')].forEach((btn) => {
    if (!btn) return;
    btn.disabled = isEditing;
    if (isEditing) {
      btn.title = '수정 중에는 공지/설문 전환을 할 수 없습니다.';
    } else {
      btn.removeAttribute('title');
    }
  });
  syncComposeExpandUi();
}

function ensureComposeHomeMarker(compose) {
  if (!compose) return;
  if (!window.__annComposeHomeMarker) {
    window.__annComposeHomeMarker = document.createComment('announcement-compose-home');
  }
  if (!window.__annComposeHomeMarker.parentNode && compose.parentNode) {
    compose.parentNode.insertBefore(window.__annComposeHomeMarker, compose);
  }
}

function returnComposeHome() {
  const compose = document.querySelector('#annComposeExpandMount .announcement-compose');
  const marker = window.__annComposeHomeMarker;
  if (compose && marker?.parentNode) {
    marker.parentNode.insertBefore(compose, marker.nextSibling);
  }
}

function ensureAnnouncementExpandShell(mount) {
  let shell = mount.querySelector('.ann-compose-expanded-shell');
  let editor = shell?.querySelector('[data-ann-compose-editor]');
  let preview = shell?.querySelector('#annComposeStudentPreview');
  if (shell && editor && preview) return { shell, editor, preview };

  returnComposeHome();
  mount.innerHTML = `
    <div class="ann-compose-expanded-shell">
      <div class="ann-compose-expanded-editor" data-ann-compose-editor></div>
      <aside id="annComposeStudentPreview" class="ann-compose-student-preview" aria-label="학생 공지 팝업 미리보기" hidden></aside>
    </div>
  `;
  shell = mount.querySelector('.ann-compose-expanded-shell');
  editor = mount.querySelector('[data-ann-compose-editor]');
  preview = mount.querySelector('#annComposeStudentPreview');
  return { shell, editor, preview };
}

function renderAnnouncementStudentPreview() {
  const host = $('annComposeStudentPreview');
  if (!host) return;
  const images = normalizeImages(selectedAnnouncementImages);
  if (composeMode !== 'announcement' || !images.length) {
    host.hidden = true;
    host.innerHTML = '';
    return;
  }

  const image = images[0];
  const title = String($('annTitle')?.value || '').trim() || '공지 제목';
  const content = String($('annContent')?.value || '').trim() || '학생에게 전달할 내용';
  const sourceItem = editingAnnouncementId
    ? latestAnnouncements.find(row => String(row?.id || '') === String(editingAnnouncementId))
    : null;
  const previewTime = formatPreviewDateTime(sourceItem?.createdAt || new Date());
  host.hidden = false;
  host.innerHTML = `
    <div class="ann-student-preview-card">
      <div class="ann-student-preview-head">
        <span class="ann-student-preview-icon" aria-hidden="true">
          <svg viewBox="0 0 24 24" focusable="false">
            <path d="M4 10v4h3l6 4V6l-6 4H4Z"></path>
            <path d="M16 9.5c1.2.8 1.8 1.6 1.8 2.5s-.6 1.7-1.8 2.5"></path>
            <path d="M18.5 7c1.7 1.4 2.5 3 2.5 5s-.8 3.6-2.5 5"></path>
          </svg>
        </span>
        <strong>공지 !!</strong>
      </div>
      <div class="ann-student-preview-meta">
        <div class="ann-student-preview-title">${escapeHtml(title)}</div>
        <div class="ann-student-preview-time">
          <span>등록 시간</span>
          <time>${escapeHtml(previewTime)}</time>
        </div>
      </div>
      <figure class="ann-student-preview-image">
        <img src="${escapeHtml(image.url)}" alt="공지 이미지">
      </figure>
      <section class="ann-student-preview-content">
        <span>내용</span>
        <p>${escapeHtml(content)}</p>
      </section>
      <button type="button" class="ann-student-preview-remove" data-ann-preview-remove-image>첨부 이미지 제거</button>
    </div>
  `;
}

function renderComposeExpandBody() {
  const mount = $('annComposeExpandMount');
  const compose = document.querySelector('.announcement-compose');
  if (!mount) return;

  if (composeMode === 'survey') {
    returnComposeHome();
    mount.innerHTML = '';
    document.body.classList.add('ann-compose-expanded', 'ann-survey-expanded');
    renderExpandedSurveyBuilder();
    return;
  }

  document.body.classList.add('ann-compose-expanded');
  document.body.classList.remove('ann-survey-expanded');
  mount.querySelector('[data-expanded-survey-builder]')?.remove();
  if (!compose) return;
  const { editor } = ensureAnnouncementExpandShell(mount);
  ensureComposeHomeMarker(compose);
  if (!editor.contains(compose)) editor.appendChild(compose);
  renderAnnouncementStudentPreview();
}

function openComposeExpandModal() {
  const modal = $('annComposeExpandModal');
  const mount = $('annComposeExpandMount');
  const compose = document.querySelector('.announcement-compose');
  if (!modal || !mount || !compose) return;

  modal.hidden = false;
  renderComposeExpandBody();
  syncEditStateUi();
  requestAnimationFrame(() => {
    if (composeMode === 'survey') {
      document.querySelector('[data-expanded-title]')?.focus?.();
    } else {
      $('annTitle')?.focus?.();
    }
  });
}

function closeComposeExpandModal({ focusTrigger = true } = {}) {
  const modal = $('annComposeExpandModal');
  const mount = $('annComposeExpandMount');
  $('annTargetMenu')?.setAttribute('hidden', '');
  returnComposeHome();
  if (mount) mount.innerHTML = '';
  if (modal) modal.hidden = true;
  document.body.classList.remove('ann-compose-expanded', 'ann-survey-expanded');
  if (focusTrigger) $('annComposeExpand')?.focus?.();
}

function renderSelectedImage() {
  const chip = $('annImagePreview');
  const thumb = $('annImageThumb');
  const name = $('annImageName');
  if (!chip || !thumb || !name) return;

  if (!selectedAnnouncementImages.length) {
    chip.hidden = true;
    thumb.removeAttribute('src');
    thumb.alt = '';
    name.textContent = '';
    chip.removeAttribute('title');
    renderAnnouncementStudentPreview();
    return;
  }

  const firstImage = selectedAnnouncementImages[0];
  chip.hidden = false;
  thumb.src = firstImage.url;
  thumb.alt = '첨부 이미지';
  name.textContent = '';
  chip.removeAttribute('title');
  renderAnnouncementStudentPreview();
}

function setSelectedImages(images) {
  selectedAnnouncementImages = normalizeImages(images);
  renderSelectedImage();
  renderAnnouncementStudentPreview();
}

async function parseJsonResponse(res, fallback) {
  let data = null;
  try { data = await res.json(); } catch {}
  if (!res.ok) {
    throw new Error(data?.error || fallback || `요청 실패 (${res.status})`);
  }
  return data || {};
}

function timeLeftText(expiresAt) {
  const end = new Date(expiresAt).getTime();
  if (!Number.isFinite(end)) return '4시간 휘발';
  const ms = end - Date.now();
  if (ms <= 0) return '만료됨';
  const mins = Math.ceil(ms / 60000);
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  if (h <= 0) return `${m}분 남음`;
  return `${h}시간 ${m}분 남음`;
}

function rowCurriculumLabel(row) {
  return String(row?.curriculumLabel || [row?.curriculum, row?.subCurriculum, row?.level].filter(Boolean).join(' · ') || row?.curriculum || '').trim();
}

function rowText(row) {
  return [
    row.name,
    row.sid,
    row.slot,
    row.school,
    row.grade,
    rowCurriculumLabel(row),
  ].filter(Boolean).join(' ');
}

function refreshRowKey(row) {
  return { ...row, key: searchKeyForText(rowText(row)) };
}

function studentById(sid) {
  return (state.students || []).find(stu => String(stu?.id) === String(sid)) || null;
}

function studentSchool(stu) {
  return String(stu?.school || stu?.schoolName || stu?.highSchool || stu?.middleSchool || stu?.high || stu?.middle || '').trim();
}

function studentRow(stu) {
  const sid = String(stu?.id || '').trim();
  const name = String(stu?.name || sid).trim() || sid;
  const curriculum = String(stu?.curriculum || stu?.subject || '').trim();
  const subCurriculum = String(stu?.subCurriculum || stu?.course || '').trim();
  const level = String(stu?.level || stu?.difficulty || '').trim();
  const grade = String(stu?.grade || stu?.gradeLevel || stu?.studentGrade || stu?.['학년'] || '').trim();
  const school = studentSchool(stu);
  return refreshRowKey({
    sid,
    name,
    slot: '',
    school,
    grade,
    curriculum,
    subCurriculum,
    level,
    curriculumLabel: [curriculum, subCurriculum, level].filter(Boolean).join(' · '),
    slots: [],
  });
}

function slotNumsFromText(value) {
  const nums = (String(value || '').match(/[12]/g) || []).map(Number);
  return Array.from(new Set(nums)).sort((a, b) => a - b);
}

function mergeRow(base, extra) {
  return refreshRowKey({
    ...base,
    ...extra,
    school: extra.school || base.school || '',
    grade: extra.grade || base.grade || '',
    curriculum: extra.curriculum || base.curriculum || '',
    subCurriculum: extra.subCurriculum || base.subCurriculum || '',
    level: extra.level || base.level || '',
    curriculumLabel: extra.curriculumLabel || base.curriculumLabel || rowCurriculumLabel({ ...base, ...extra }),
    slots: Array.isArray(extra.slots) ? extra.slots : (Array.isArray(base.slots) ? base.slots : []),
  });
}

function buildAllRoster(rows = null) {
  const source = Array.isArray(state.students) && state.students.length
    ? state.students
    : (Array.isArray(rows) && rows.length ? rows : []);
  const seen = new Set();
  return source.map(studentRow).filter((row) => {
    if (!row.sid || seen.has(row.sid)) return false;
    seen.add(row.sid);
    return true;
  });
}

function collectRosterFromDom() {
  const rows = Array.from(document.querySelectorAll('#todayWrap tr[data-sid]'));
  return rows.map((tr) => {
    const sid = String(tr.dataset.sid || '').trim();
    const stu = studentById(sid);
    const base = stu ? studentRow(stu) : studentRow({ id: sid });
    const slot = (tr.querySelector('.slotLabel')?.textContent || tr.querySelector('.today-slot-cell')?.textContent || '').trim();
    const school = (tr.querySelector('.today-school-cell')?.textContent || '').trim();
    const curriculumText = (tr.querySelector('.today-curriculum-cell')?.textContent || '').trim();
    const name = (tr.querySelector('.stuName')?.textContent || base.name || sid).trim();
    const slots = slotNumsFromText(slot || tr.dataset.slotGroup || '');
    return mergeRow(base, {
      name,
      slot,
      school: school || base.school,
      curriculumLabel: curriculumText || base.curriculumLabel,
      slots,
    });
  }).filter(row => row.sid);
}

function normalizedEditingFallbackRows() {
  if (!editingAnnouncementId || !Array.isArray(editingFallbackTargets) || !editingFallbackTargets.length) {
    return [];
  }
  return editingFallbackTargets.map((row) => {
    const sid = String(row?.sid || '').trim();
    const name = String(row?.name || sid).trim() || sid;
    const slot = String(row?.slot || '').trim();
    const school = String(row?.school || '').trim();
    const curriculum = String(row?.curriculum || '').trim();
    const subCurriculum = String(row?.subCurriculum || '').trim();
    const level = String(row?.level || '').trim();
    const grade = String(row?.grade || '').trim();
    return refreshRowKey({
      sid,
      name,
      slot,
      school,
      grade,
      curriculum,
      subCurriculum,
      level,
      curriculumLabel: rowCurriculumLabel({ curriculum, subCurriculum, level }),
      slots: Array.isArray(row?.slots) ? row.slots : [],
    });
  }).filter(row => row.sid);
}

function mergeEditingFallbackRows() {
  const fallbackRows = normalizedEditingFallbackRows();
  if (!fallbackRows.length) return;
  const seen = new Set(allRoster.map(row => row.sid));
  fallbackRows.forEach((row) => {
    if (seen.has(row.sid)) return;
    seen.add(row.sid);
    allRoster.push(row);
  });
}

function reconcileDirectSelection() {
  const valid = new Set(rosterBaseRows().map(row => row.sid));
  normalizedEditingFallbackRows().forEach(row => valid.add(row.sid));
  directSelected = new Set([...directSelected].filter(sid => valid.has(sid)));
}

function syncRoster(rows = null) {
  const fromDom = collectRosterFromDom();
  const nextAllRoster = buildAllRoster(rows);
  if (nextAllRoster.length) {
    allRoster = nextAllRoster;
  }
  if (fromDom.length) {
    todayRoster = fromDom;
  }
  const todayBySid = new Map(todayRoster.map(row => [row.sid, row]));
  allRoster = allRoster.map(row => todayBySid.has(row.sid) ? mergeRow(row, todayBySid.get(row.sid)) : row);
  mergeEditingFallbackRows();
  latestRoster = rosterBaseRows();
  reconcileDirectSelection();
  renderTargetFilterOptions();
  renderDirectList();
  updateTargetSummary();
  renderExpandedDirectList();
  refreshExpandedSurveyDerivedViews();
}

function rosterBaseRows() {
  return allRoster.length ? allRoster : todayRoster;
}

function targetFilterRows() {
  return rosterBaseRows().filter((row) => {
    if (targetFilters.curriculum && row.curriculum !== targetFilters.curriculum) return false;
    if (targetFilters.subCurriculum && row.subCurriculum !== targetFilters.subCurriculum) return false;
    if (targetFilters.level && row.level !== targetFilters.level) return false;
    return true;
  });
}

function rowsForMode(mode = targetMode) {
  if (mode === 'slot1') {
    return todayRoster.filter(row => row.slots.includes(1));
  }
  if (mode === 'slot2') {
    return todayRoster.filter(row => row.slots.includes(2) && !row.slots.includes(1));
  }
  if (mode === 'today') {
    return [...todayRoster];
  }
  if (mode === 'all') {
    return [...rosterBaseRows()];
  }
  if (mode === 'curriculum') {
    return targetFilterRows();
  }
  if (mode === 'grade') {
    return rosterBaseRows().filter(row => !targetFilters.grade || row.grade === targetFilters.grade);
  }
  if (mode === 'direct') {
    return rosterBaseRows().filter(row => directSelected.has(row.sid));
  }
  return [...todayRoster];
}

function targetSnapshot(rows) {
  return rows.map(row => ({
    sid: row.sid,
    name: row.name,
    slot: row.slot,
    school: row.school,
    grade: row.grade,
    curriculum: row.curriculum,
    subCurriculum: row.subCurriculum,
    level: row.level,
  }));
}

function uniqueSorted(values) {
  return Array.from(new Set(values.map(value => String(value || '').trim()).filter(Boolean)))
    .sort((a, b) => a.localeCompare(b, 'ko', { numeric: true }));
}

function rowsForFilterOption(key) {
  return rosterBaseRows().filter((row) => {
    if (key !== 'curriculum' && targetFilters.curriculum && row.curriculum !== targetFilters.curriculum) return false;
    if (key !== 'subCurriculum' && targetFilters.subCurriculum && row.subCurriculum !== targetFilters.subCurriculum) return false;
    if (key !== 'level' && targetFilters.level && row.level !== targetFilters.level) return false;
    return true;
  });
}

function targetFilterValues(key) {
  return uniqueSorted(rowsForFilterOption(key).map(row => row?.[key]));
}

function gradeValues() {
  return uniqueSorted(rosterBaseRows().map(row => row.grade));
}

function renderSelectOptions(values, selected, allLabel = '전체') {
  return [
    `<option value="">${escapeHtml(allLabel)}</option>`,
    ...values.map(value => `<option value="${escapeHtml(value)}" ${value === selected ? 'selected' : ''}>${escapeHtml(value)}</option>`),
  ].join('');
}

function targetSelectionLabel(mode = targetMode) {
  if (mode === 'curriculum') {
    const subject = targetFilters.curriculum || '과목 전체';
    const course = targetFilters.subCurriculum || '과정 전체';
    const level = targetFilters.level || '난이도 전체';
    return `커리큘럼: ${subject} / ${course} / ${level}`;
  }
  if (mode === 'grade') {
    return `학년: ${targetFilters.grade || '전체'}`;
  }
  return TARGET_LABELS[mode] || '대상';
}

function reconcileTargetFilters() {
  if (targetFilters.curriculum && !targetFilterValues('curriculum').includes(targetFilters.curriculum)) {
    targetFilters.curriculum = '';
  }
  if (targetFilters.subCurriculum && !targetFilterValues('subCurriculum').includes(targetFilters.subCurriculum)) {
    targetFilters.subCurriculum = '';
  }
  if (targetFilters.level && !targetFilterValues('level').includes(targetFilters.level)) {
    targetFilters.level = '';
  }
  if (targetFilters.grade && !gradeValues().includes(targetFilters.grade)) {
    targetFilters.grade = '';
  }
}

function renderTargetFilterOptions() {
  reconcileTargetFilters();
  document.querySelectorAll('[data-ann-target-filter="curriculum"]').forEach((select) => {
    select.innerHTML = renderSelectOptions(targetFilterValues('curriculum'), targetFilters.curriculum, '과목 전체');
    select.value = targetFilters.curriculum;
  });
  document.querySelectorAll('[data-ann-target-filter="subCurriculum"]').forEach((select) => {
    select.innerHTML = renderSelectOptions(targetFilterValues('subCurriculum'), targetFilters.subCurriculum, '과정 전체');
    select.value = targetFilters.subCurriculum;
  });
  document.querySelectorAll('[data-ann-target-filter="level"]').forEach((select) => {
    select.innerHTML = renderSelectOptions(targetFilterValues('level'), targetFilters.level, '난이도 전체');
    select.value = targetFilters.level;
  });
  document.querySelectorAll('[data-ann-target-filter="grade"]').forEach((select) => {
    select.innerHTML = renderSelectOptions(gradeValues(), targetFilters.grade, '학년 전체');
    select.value = targetFilters.grade;
  });
}

function updateTargetSummary() {
  const count = rowsForMode().length;
  const label = targetSelectionLabel();
  const summary = $('annTargetSummary');
  if (summary) {
    const text = `${label} · ${count}명`;
    summary.textContent = text;
    summary.title = text;
    summary.setAttribute('aria-label', `공지 대상 ${text}`);
  }

  document.querySelectorAll('#annTargetMenu [data-target-mode]').forEach((btn) => {
    btn.classList.toggle('is-active', btn.dataset.targetMode === targetMode);
  });

  const directBox = $('annDirectPicker');
  if (directBox) directBox.hidden = targetMode !== 'direct';
  const curriculumBox = $('annCurriculumPicker');
  if (curriculumBox) curriculumBox.hidden = targetMode !== 'curriculum';
  const gradeBox = $('annGradePicker');
  if (gradeBox) gradeBox.hidden = targetMode !== 'grade';
}

function renderDirectList() {
  const host = $('annDirectList');
  if (!host) return;

  const query = $('annDirectSearch')?.value || '';
  const rows = rosterBaseRows().filter(row => matchesSearchKey(row.key, query));
  if (!rows.length) {
    host.innerHTML = '<div class="ann-empty">선택 가능한 학생이 없습니다.</div>';
    return;
  }

  host.innerHTML = rows.map(row => `
    <label class="ann-direct-row">
      <input type="checkbox" value="${escapeHtml(row.sid)}" ${directSelected.has(row.sid) ? 'checked' : ''}>
      <span>
        <strong>${escapeHtml(row.name)}</strong>
        <em>${escapeHtml([row.slot, row.school, row.grade, rowCurriculumLabel(row)].filter(Boolean).join(' · '))}</em>
      </span>
    </label>
  `).join('');
}

async function uploadAnnouncementImageFile(file) {
  if (!file) return null;
  if (!isSupportedImageFile(file)) {
    throw new Error('이미지 파일만 첨부할 수 있습니다.');
  }
  if (file.size > ANN_IMAGE_MAX_BYTES) {
    throw new Error('이미지는 8MB 이하만 첨부할 수 있습니다.');
  }

  const form = new FormData();
  form.append('file', file);
  const res = await fetch('/api/announcements/image', {
    method: 'POST',
    body: form,
  });
  const data = await parseJsonResponse(res, '이미지 업로드 실패');
  return normalizeImage(data.image);
}

async function uploadAnnouncementImageFiles(files) {
  const picked = Array.from(files || []).filter(Boolean);
  if (!picked.length) return;
  if (picked.length > ANN_IMAGE_MAX_COUNT) {
    throw new Error(`이미지는 최대 ${ANN_IMAGE_MAX_COUNT}장까지 첨부할 수 있습니다.`);
  }

  const pickBtn = $('annImagePick');
  const publishBtn = $('annPublish');
  if (pickBtn) pickBtn.disabled = true;
  if (publishBtn) publishBtn.disabled = true;
  try {
    const uploaded = [];
    for (const file of picked) {
      const image = await uploadAnnouncementImageFile(file);
      if (image) uploaded.push(image);
    }
    setSelectedImages(uploaded);
    toast(uploaded.length > 1 ? `이미지 ${uploaded.length}장 첨부 완료` : '이미지 첨부 완료');
  } finally {
    if (pickBtn) pickBtn.disabled = false;
    if (publishBtn) publishBtn.disabled = false;
  }
}

function bindImageTools() {
  const file = $('annImageFile');
  const pickBtn = $('annImagePick');
  const removeBtn = $('annImageRemove');

  renderSelectedImage();

  pickBtn?.addEventListener('click', (ev) => {
    ev.preventDefault();
    ev.stopPropagation();
    if (!file) return;
    $('annTargetMenu')?.setAttribute('hidden', '');
    composeBackdropPointerDown = false;
    file.value = '';
    file.click();
  });

  file?.addEventListener('change', async () => {
    try {
      await uploadAnnouncementImageFiles(file.files);
    } catch (err) {
      console.error(err);
      alert(err?.message || '이미지를 첨부하지 못했습니다.');
    } finally {
      file.value = '';
    }
  });

  removeBtn?.addEventListener('click', () => {
    setSelectedImages([]);
    toast('첨부 이미지를 제거했습니다.');
  });

  $('annTitle')?.addEventListener('input', renderAnnouncementStudentPreview);
  $('annContent')?.addEventListener('input', renderAnnouncementStudentPreview);
}

function bindExpiryControls() {
  document.addEventListener('click', (ev) => {
    const modeBtn = ev.target.closest('[data-ann-expiry-mode]');
    if (!modeBtn) return;
    expiryMode = modeBtn.dataset.annExpiryMode === 'absolute' ? 'absolute' : 'hours';
    syncExpiryUi();
    refreshExpandedSurveyDerivedViews();
  });

  document.addEventListener('input', (ev) => {
    if (ev.target.matches('[data-ann-expiry-hours]')) {
      expiryHours = clampInt(ev.target.value, expiryHours || DEFAULT_EXPIRY_HOURS, 1, MAX_EXPIRY_HOURS);
      syncExpiryUi();
      return;
    }
    if (ev.target.matches('[data-ann-expiry-month]')) {
      expiryManual = { ...expiryManual, month: String(ev.target.value || '') };
      syncExpiryUi();
      return;
    }
    if (ev.target.matches('[data-ann-expiry-day]')) {
      expiryManual = { ...expiryManual, day: String(ev.target.value || '') };
      syncExpiryUi();
      return;
    }
    if (ev.target.matches('[data-ann-expiry-hour]')) {
      expiryManual = { ...expiryManual, hour: String(ev.target.value || '') };
      syncExpiryUi();
    }
  });

  document.addEventListener('change', (ev) => {
    if (!ev.target.matches('[data-ann-expiry-hours], [data-ann-expiry-month], [data-ann-expiry-day], [data-ann-expiry-hour]')) return;
    if (ev.target.matches('[data-ann-expiry-hours]')) {
      expiryHours = clampInt(ev.target.value, expiryHours || DEFAULT_EXPIRY_HOURS, 1, MAX_EXPIRY_HOURS);
    } else if (ev.target.matches('[data-ann-expiry-month]')) {
      expiryManual = { ...expiryManual, month: String(clampInt(ev.target.value, expiryManual.month || 1, 1, 12)) };
    } else if (ev.target.matches('[data-ann-expiry-day]')) {
      expiryManual = { ...expiryManual, day: String(clampInt(ev.target.value, expiryManual.day || 1, 1, 31)) };
    } else if (ev.target.matches('[data-ann-expiry-hour]')) {
      expiryManual = { ...expiryManual, hour: String(clampInt(ev.target.value, expiryManual.hour || 0, 0, 23)) };
    }
    syncExpiryUi();
  });
}

function bindSurveyBuilder() {
  const modal = $('annSurveyModal');
  const questionsHost = $('annSurveyQuestions');

  const toggleComposeMode = () => {
    setComposeMode(composeMode === 'survey' ? 'announcement' : 'survey');
    if (isComposeExpandOpen()) renderComposeExpandBody();
  };

  $('annModeToggle')?.addEventListener('click', toggleComposeMode);
  $('annComposeModeToggle')?.addEventListener('click', toggleComposeMode);

  $('annSurveyBuilderOpen')?.addEventListener('click', openSurveyBuilder);
  $('annSurveyClose')?.addEventListener('click', closeSurveyBuilder);
  $('annSurveyApply')?.addEventListener('click', () => {
    if (!normalizeSurveyDraft({ showAlert: true })) return;
    renderSurveyChip();
    closeSurveyBuilder();
    toast('설문 문항을 반영했습니다.');
  });
  $('annSurveyReset')?.addEventListener('click', () => {
    if (!confirm('설문 문항을 초기화할까요?')) return;
    surveyDraft = emptySurveyDraft();
    renderSurveyBuilder();
  });
  $('annSurveyAddQuestion')?.addEventListener('click', () => {
    surveyDraft.questions.push(makeSurveyQuestion('single'));
    renderSurveyBuilder();
    requestAnimationFrame(() => {
      questionsHost?.querySelector('[data-survey-q]:last-child input')?.focus?.();
    });
  });

  $('annSurveyStatus')?.addEventListener('change', (ev) => {
    surveyDraft.status = ev.target.value || 'public';
    renderSurveyChip();
  });
  $('annSurveyAnonymous')?.addEventListener('change', (ev) => {
    surveyDraft.anonymous = !!ev.target.checked;
  });
  $('annSurveyAllowMultiple')?.addEventListener('change', (ev) => {
    surveyDraft.allowMultiple = !!ev.target.checked;
  });

  questionsHost?.addEventListener('input', (ev) => {
    const card = ev.target.closest('[data-survey-q]');
    if (!card) return;
    const qIndex = Number(card.dataset.surveyQ);
    const question = surveyDraft.questions[qIndex];
    if (!question) return;
    if (ev.target.matches('[data-survey-question-text]')) {
      question.text = ev.target.value;
    } else if (ev.target.matches('[data-survey-option-text]')) {
      const row = ev.target.closest('[data-survey-option]');
      const optIndex = Number(row?.dataset.surveyOption);
      if (question.options?.[optIndex]) question.options[optIndex].text = ev.target.value;
    }
    renderSurveyChip();
  });

  questionsHost?.addEventListener('change', (ev) => {
    const card = ev.target.closest('[data-survey-q]');
    if (!card) return;
    const qIndex = Number(card.dataset.surveyQ);
    const question = surveyDraft.questions[qIndex];
    if (!question) return;
    if (ev.target.matches('[data-survey-question-type]')) {
      setSurveyQuestionType(question, ev.target.value || 'single');
      renderSurveyBuilder();
    } else if (ev.target.matches('[data-survey-required]')) {
      question.required = !!ev.target.checked;
      renderSurveyChip();
    }
  });

  questionsHost?.addEventListener('click', (ev) => {
    const card = ev.target.closest('[data-survey-q]');
    if (!card) return;
    const qIndex = Number(card.dataset.surveyQ);
    const question = surveyDraft.questions[qIndex];
    if (!question) return;

    if (ev.target.closest('[data-survey-add-option]')) {
      ensureChoiceOptions(question);
      question.options.push(makeSurveyOption(''));
      renderSurveyBuilder();
      requestAnimationFrame(() => {
        questionsHost.querySelector(`[data-survey-q="${qIndex}"] [data-survey-option]:last-of-type input`)?.focus?.();
      });
      return;
    }

    if (ev.target.closest('[data-survey-delete-option]')) {
      const row = ev.target.closest('[data-survey-option]');
      const optIndex = Number(row?.dataset.surveyOption);
      if (Array.isArray(question.options) && question.options.length > 2) {
        question.options.splice(optIndex, 1);
        renderSurveyBuilder();
      }
      return;
    }

    if (ev.target.closest('[data-survey-delete-question]')) {
      if (surveyDraft.questions.length > 1) {
        surveyDraft.questions.splice(qIndex, 1);
        renderSurveyBuilder();
      }
      return;
    }

    const move = ev.target.closest('[data-survey-move]')?.dataset.surveyMove;
    if (move === 'up' && qIndex > 0) {
      [surveyDraft.questions[qIndex - 1], surveyDraft.questions[qIndex]] = [surveyDraft.questions[qIndex], surveyDraft.questions[qIndex - 1]];
      renderSurveyBuilder();
    } else if (move === 'down' && qIndex < surveyDraft.questions.length - 1) {
      [surveyDraft.questions[qIndex + 1], surveyDraft.questions[qIndex]] = [surveyDraft.questions[qIndex], surveyDraft.questions[qIndex + 1]];
      renderSurveyBuilder();
    }
  });

  modal?.addEventListener('click', (ev) => {
    if (ev.target === modal) closeSurveyBuilder();
  });

  document.addEventListener('keydown', (ev) => {
    if (ev.key !== 'Escape' || !modal || modal.hidden) return;
    ev.preventDefault();
    ev.stopPropagation();
    ev.stopImmediatePropagation?.();
    closeSurveyBuilder();
  }, true);

  renderSurveyChip();
}

function validateExpandedSurveyBeforePublish() {
  const title = String($('annTitle')?.value || '').trim();
  const content = String($('annContent')?.value || '').trim();
  if (!title) {
    alert('설문 제목을 입력해 주세요.');
    document.querySelector('[data-expanded-title]')?.focus?.();
    return false;
  }
  if (!content) {
    alert('설문 설명을 입력해 주세요.');
    document.querySelector('[data-expanded-content]')?.focus?.();
    return false;
  }
  if (!normalizeSurveyDraft({ showAlert: true })) {
    document.querySelector('.ann-survey-expanded-question.needs-work input, .ann-survey-expanded-question input')?.focus?.();
    return false;
  }
  if (!rowsForMode().length) {
    alert('설문 대상 학생을 선택해 주세요.');
    document.querySelector('[data-expanded-target-mode="direct"]')?.focus?.();
    return false;
  }
  return true;
}

function bindExpandedSurveyBuilder() {
  const mount = $('annComposeExpandMount');
  if (!mount) return;

  mount.addEventListener('input', (ev) => {
    if (!ev.target.closest('[data-expanded-survey-builder]')) return;
    if (ev.target.matches('[data-expanded-title]')) {
      const title = $('annTitle');
      if (title) title.value = ev.target.value;
      refreshExpandedSurveyDerivedViews();
      return;
    }
    if (ev.target.matches('[data-expanded-content]')) {
      const content = $('annContent');
      if (content) content.value = ev.target.value;
      refreshExpandedSurveyDerivedViews();
      return;
    }
    if (ev.target.matches('[data-expanded-direct-search]')) {
      expandedDirectQuery = ev.target.value || '';
      renderExpandedDirectList();
      return;
    }

    const card = ev.target.closest('[data-survey-q]');
    if (!card) return;
    const qIndex = Number(card.dataset.surveyQ);
    const question = surveyDraft.questions?.[qIndex];
    if (!question) return;
    if (ev.target.matches('[data-survey-question-text]')) {
      question.text = ev.target.value;
    } else if (ev.target.matches('[data-survey-option-text]')) {
      const row = ev.target.closest('[data-survey-option]');
      const optIndex = Number(row?.dataset.surveyOption);
      if (question.options?.[optIndex]) question.options[optIndex].text = ev.target.value;
    }
    card.classList.toggle('needs-work', !surveyQuestionCompleteness(question));
    renderSurveyChip();
    refreshExpandedSurveyDerivedViews();
  });

  mount.addEventListener('change', (ev) => {
    if (!ev.target.closest('[data-expanded-survey-builder]')) return;

    const targetFilter = ev.target.closest('[data-ann-target-filter]');
    if (targetFilter) {
      const key = targetFilter.dataset.annTargetFilter;
      if (key && Object.prototype.hasOwnProperty.call(targetFilters, key)) {
        targetFilters = { ...targetFilters, [key]: targetFilter.value || '' };
        renderExpandedSurveyBuilder();
      }
      return;
    }

    if (ev.target.matches('[data-expanded-survey-status]')) {
      surveyDraft.status = ev.target.value || 'public';
      renderSurveyBuilder();
      renderExpandedSurveyBuilder();
      return;
    }
    if (ev.target.matches('[data-expanded-survey-anonymous]')) {
      surveyDraft.anonymous = !!ev.target.checked;
      refreshExpandedSurveyDerivedViews();
      return;
    }
    if (ev.target.matches('[data-expanded-survey-multiple]')) {
      surveyDraft.allowMultiple = !!ev.target.checked;
      refreshExpandedSurveyDerivedViews();
      return;
    }

    const directInput = ev.target.closest('[data-expanded-direct-list] input[type="checkbox"]');
    if (directInput) {
      if (directInput.checked) directSelected.add(String(directInput.value));
      else directSelected.delete(String(directInput.value));
      updateTargetSummary();
      renderDirectList();
      renderExpandedSurveyBuilder();
      return;
    }

    const card = ev.target.closest('[data-survey-q]');
    if (!card) return;
    const qIndex = Number(card.dataset.surveyQ);
    const question = surveyDraft.questions?.[qIndex];
    if (!question) return;
    if (ev.target.matches('[data-survey-question-type]')) {
      setSurveyQuestionType(question, ev.target.value || 'single');
      renderSurveyBuilder();
      renderExpandedSurveyBuilder();
    } else if (ev.target.matches('[data-survey-required]')) {
      question.required = !!ev.target.checked;
      renderSurveyChip();
      refreshExpandedSurveyDerivedViews();
    }
  });

  mount.addEventListener('click', async (ev) => {
    const builder = ev.target.closest('[data-expanded-survey-builder]');
    if (!builder) return;

    const addType = ev.target.closest('[data-expanded-add-question]')?.dataset.expandedAddQuestion;
    if (addType) {
      surveyDraft.questions.push(makeSurveyQuestion(addType));
      renderSurveyBuilder();
      renderExpandedSurveyBuilder();
      requestAnimationFrame(() => {
        mount.querySelector('[data-survey-q]:last-child [data-survey-question-text]')?.focus?.();
      });
      return;
    }

    const targetBtn = ev.target.closest('[data-expanded-target-mode]');
    if (targetBtn) {
      targetMode = targetBtn.dataset.expandedTargetMode || 'today';
      updateTargetSummary();
      renderDirectList();
      renderExpandedSurveyBuilder();
      return;
    }

    if (ev.target.closest('[data-expanded-select-visible]')) {
      rosterBaseRows()
        .filter(row => matchesSearchKey(row.key, expandedDirectQuery))
        .forEach(row => directSelected.add(row.sid));
      updateTargetSummary();
      renderDirectList();
      renderExpandedSurveyBuilder();
      return;
    }

    if (ev.target.closest('[data-expanded-clear-selected]')) {
      directSelected.clear();
      updateTargetSummary();
      renderDirectList();
      renderExpandedSurveyBuilder();
      return;
    }

    if (ev.target.closest('[data-expanded-reset]')) {
      if (!confirm('설문 문항을 초기화할까요?')) return;
      surveyDraft = emptySurveyDraft();
      renderSurveyBuilder();
      renderExpandedSurveyBuilder();
      return;
    }

    if (ev.target.closest('[data-expanded-apply]')) {
      renderSurveyChip();
      closeComposeExpandModal();
      toast('설문 작성 내용을 반영했습니다.');
      return;
    }

    if (ev.target.closest('[data-expanded-publish]')) {
      if (!validateExpandedSurveyBeforePublish()) return;
      try {
        await publishAnnouncement();
      } catch (err) {
        console.error(err);
        alert(err?.message || '설문 등록 실패');
      }
      return;
    }

    const card = ev.target.closest('[data-survey-q]');
    if (!card) return;
    const qIndex = Number(card.dataset.surveyQ);
    const question = surveyDraft.questions?.[qIndex];
    if (!question) return;

    if (ev.target.closest('[data-survey-add-option]')) {
      ensureChoiceOptions(question);
      question.options.push(makeSurveyOption(''));
      renderSurveyBuilder();
      renderExpandedSurveyBuilder();
      requestAnimationFrame(() => {
        mount.querySelector(`[data-survey-q="${qIndex}"] [data-survey-option]:last-of-type input`)?.focus?.();
      });
      return;
    }

    if (ev.target.closest('[data-survey-delete-option]')) {
      const row = ev.target.closest('[data-survey-option]');
      const optIndex = Number(row?.dataset.surveyOption);
      if (Array.isArray(question.options) && question.options.length > 2) {
        question.options.splice(optIndex, 1);
        renderSurveyBuilder();
        renderExpandedSurveyBuilder();
      }
      return;
    }

    if (ev.target.closest('[data-survey-duplicate-question]')) {
      duplicateSurveyQuestion(qIndex);
      renderSurveyBuilder();
      renderExpandedSurveyBuilder();
      return;
    }

    if (ev.target.closest('[data-survey-delete-question]')) {
      if (surveyDraft.questions.length > 1) {
        surveyDraft.questions.splice(qIndex, 1);
        renderSurveyBuilder();
        renderExpandedSurveyBuilder();
      }
      return;
    }

    const move = ev.target.closest('[data-survey-move]')?.dataset.surveyMove;
    if (move === 'up' && qIndex > 0) {
      [surveyDraft.questions[qIndex - 1], surveyDraft.questions[qIndex]] = [surveyDraft.questions[qIndex], surveyDraft.questions[qIndex - 1]];
      renderSurveyBuilder();
      renderExpandedSurveyBuilder();
    } else if (move === 'down' && qIndex < surveyDraft.questions.length - 1) {
      [surveyDraft.questions[qIndex + 1], surveyDraft.questions[qIndex]] = [surveyDraft.questions[qIndex], surveyDraft.questions[qIndex + 1]];
      renderSurveyBuilder();
      renderExpandedSurveyBuilder();
    }
  });
}

async function publishAnnouncement() {
  syncRoster();

  const isSurvey = composeMode === 'survey';
  const title = ($('annTitle')?.value || '').trim();
  const content = ($('annContent')?.value || '').trim();
  const isEditing = !!editingAnnouncementId;
  let rows = rowsForMode();
  if (isEditing && targetMode === 'direct' && editingFallbackTargets.length) {
    const fallbackRows = editingFallbackTargets.filter(row => directSelected.has(row.sid));
    if (fallbackRows.length > rows.length) rows = fallbackRows;
  }
  const survey = isSurvey ? normalizeSurveyDraft({ showAlert: true }) : null;

  if (!title) {
    alert(isSurvey ? '설문 제목을 입력해 주세요.' : '공지 제목을 입력해 주세요.');
    $('annTitle')?.focus();
    return;
  }
  if (!content) {
    alert(isSurvey ? '설문 설명을 입력해 주세요.' : '공지 내용을 입력해 주세요.');
    $('annContent')?.focus();
    return;
  }
  if (isSurvey && !survey) {
    openSurveyBuilder();
    return;
  }
  if (!rows.length) {
    alert(isSurvey ? '설문 대상 학생을 선택해 주세요.' : '공지 대상 학생을 선택해 주세요.');
    return;
  }
  const expiry = resolveExpiryDate();
  if (!expiry.ok) {
    alert(expiry.message || '마감 시간을 확인해 주세요.');
    document.querySelector('[data-ann-expiry-hours], [data-ann-expiry-month]')?.focus?.();
    return;
  }

  const images = normalizeImages(selectedAnnouncementImages);
  const payload = {
    kind: isSurvey ? 'survey' : 'announcement',
    title,
    content,
    targetMode,
    targetLabel: `${targetSelectionLabel()} · ${rows.length}명`,
    targetSids: rows.map(row => row.sid),
    targetSnapshot: targetSnapshot(rows),
    date: getAdminDate(),
    expiresAt: expiry.date.toISOString(),
    image: images[0] || null,
    images,
    survey,
    requireCompletion: isSurvey,
  };

  const res = await fetch(isEditing ? `/api/announcements/${encodeURIComponent(editingAnnouncementId)}` : '/api/announcements', {
    method: isEditing ? 'PUT' : 'POST',
    headers: CT,
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    let text = '';
    try { text = await res.text(); } catch {}
    throw new Error(text || `공지 등록 실패 (${res.status})`);
  }
  const created = await res.json();
  selectedAnnouncementId = String(created?.id || '');
  editingAnnouncementId = '';
  editingFallbackTargets = [];
  syncEditStateUi();
  $('annTitle').value = '';
  $('annContent').value = '';
  setSelectedImages([]);
  resetExpiryDefaults();
  $('annTargetMenu')?.setAttribute('hidden', '');
  document.querySelector('#annBoardShell')?.setAttribute('open', '');
  if (isSurvey) {
    surveyDraft = emptySurveyDraft();
    renderSurveyBuilder();
  }
  toast(isEditing ? '설문 수정 완료' : (isSurvey ? '설문 등록 완료' : '공지 등록 완료'));
  await loadAndRenderAnnouncements();
  if (isComposeExpandOpen()) {
    closeComposeExpandModal();
  } else {
    $('annTitle')?.focus();
  }
}

async function deleteAnnouncement(id) {
  if (!id) return;
  const item = latestAnnouncements.find(row => String(row?.id) === String(id));
  if (!confirm(`이 ${isSurveyItem(item) ? '설문' : '공지'}을 삭제할까요? 학생 페이지에서도 바로 사라집니다.`)) return;
  const res = await fetch(`/api/announcements/${encodeURIComponent(id)}`, { method: 'DELETE' });
  if (!res.ok) throw new Error(`공지 삭제 실패 (${res.status})`);
  if (String(selectedAnnouncementId) === String(id)) selectedAnnouncementId = '';
  if (String(editingAnnouncementId) === String(id)) editingAnnouncementId = '';
  editingFallbackTargets = [];
  syncEditStateUi();
  toast(isSurveyItem(item) ? '설문 삭제 완료' : '공지 삭제 완료');
  await loadAndRenderAnnouncements();
}

function beginSurveyEdit(id) {
  const item = latestAnnouncements.find(row => String(row?.id) === String(id));
  if (!item || !isSurveyItem(item)) return;
  setComposeMode('survey');
  editingAnnouncementId = String(item.id || '');
  selectedAnnouncementId = editingAnnouncementId;
  $('annTitle').value = item.title || '';
  $('annContent').value = item.content || '';
  setSelectedImages(normalizeImages(item.images, item.image));
  surveyDraft = cloneSurveyForDraft(item.survey);

  const sids = Array.isArray(item.targetSids) ? item.targetSids.map(String) : [];
  editingFallbackTargets = sids.map((sid) => {
    const stu = studentById(sid) || {};
    const snap = (Array.isArray(item.targetSnapshot) ? item.targetSnapshot : []).find(row => String(row?.sid || row?.id) === sid) || {};
    return {
      sid,
      name: String(snap.name || stu.name || sid).trim() || sid,
      slot: String(snap.slot || '').trim(),
      school: String(snap.school || stu.school || '').trim(),
      grade: String(snap.grade || stu.grade || stu.gradeLevel || stu.studentGrade || stu['학년'] || '').trim(),
      curriculum: String(snap.curriculum || stu.curriculum || '').trim(),
      subCurriculum: String(snap.subCurriculum || stu.subCurriculum || '').trim(),
      level: String(snap.level || stu.level || '').trim(),
      slots: [],
      key: '',
    };
  });
  targetMode = 'direct';
  directSelected = new Set(sids);
  setExpiryFromAnnouncement(item);
  syncRoster();
  updateTargetSummary();
  renderSurveyBuilder();
  toast('설문 수정 모드입니다.');
  $('annTitle')?.focus();
}

function beginAnnouncementEdit(id) {
  const item = latestAnnouncements.find(row => String(row?.id) === String(id));
  if (!item) return;
  const isSurvey = isSurveyItem(item);
  setComposeMode(isSurvey ? 'survey' : 'announcement');
  editingAnnouncementId = String(item.id || '');
  selectedAnnouncementId = editingAnnouncementId;
  $('annTitle').value = item.title || '';
  $('annContent').value = item.content || '';
  setSelectedImages(normalizeImages(item.images, item.image));
  surveyDraft = isSurvey ? cloneSurveyForDraft(item.survey) : emptySurveyDraft();

  const sids = Array.isArray(item.targetSids) ? item.targetSids.map(String) : [];
  editingFallbackTargets = sids.map((sid) => {
    const stu = studentById(sid) || {};
    const snap = (Array.isArray(item.targetSnapshot) ? item.targetSnapshot : []).find(row => String(row?.sid || row?.id) === sid) || {};
    return {
      sid,
      name: String(snap.name || stu.name || sid).trim() || sid,
      slot: String(snap.slot || '').trim(),
      school: String(snap.school || stu.school || '').trim(),
      grade: String(snap.grade || stu.grade || stu.gradeLevel || stu.studentGrade || stu['학년'] || '').trim(),
      curriculum: String(snap.curriculum || stu.curriculum || '').trim(),
      subCurriculum: String(snap.subCurriculum || stu.subCurriculum || '').trim(),
      level: String(snap.level || stu.level || '').trim(),
      slots: [],
      key: '',
    };
  });
  targetMode = 'direct';
  directSelected = new Set(sids);
  setExpiryFromAnnouncement(item);
  syncRoster();
  updateTargetSummary();
  renderSurveyBuilder();
  syncEditStateUi();
  openComposeExpandModal();
  toast(isSurvey ? '설문 수정 모드입니다.' : '공지 수정 모드입니다.');
}

function renderAnnouncementList(items) {
  const host = $('annList');
  if (!host) return;

  const visibleItems = (Array.isArray(items) ? items : [])
    .filter(item => (composeMode === 'survey') === isSurveyItem(item));

  if (!visibleItems.length) {
    selectedAnnouncementId = '';
    host.innerHTML = `<div class="ann-empty">최근 4시간 안에 발행한 ${composeMode === 'survey' ? '설문' : '공지'}가 없습니다.</div>`;
    renderReplyDock(null);
    renderExpandedAnnouncementList([]);
    return;
  }

  if (!selectedAnnouncementId || !visibleItems.some(item => String(item.id) === String(selectedAnnouncementId))) {
    selectedAnnouncementId = String(visibleItems[0]?.id || '');
  }

  host.innerHTML = visibleItems.map(item => renderAnnouncementListItem(item)).join('');

  renderReplyDock(visibleItems.find(item => String(item.id) === String(selectedAnnouncementId)) || visibleItems[0]);
  renderExpandedAnnouncementList(visibleItems);
}

function visibleAnnouncementItems() {
  return (Array.isArray(latestAnnouncements) ? latestAnnouncements : [])
    .filter(item => (composeMode === 'survey') === isSurveyItem(item));
}

function renderAnnouncementListItem(item, { compact = false } = {}) {
  const active = String(item.id) === String(selectedAnnouncementId);
  const images = normalizeImages(item.images, item.image);
  const image = images[0] || null;
  const isSurvey = isSurveyItem(item);
  const survey = item.survey || {};
  const surveyResults = item.surveyResults || {};
  const responseCount = Number(surveyResults.responseCount || item.surveyResponseCount || 0);
  const imagePrefix = images.length > 1 ? `이미지 ${images.length}장 · ` : (image ? '이미지 첨부 · ' : '');
  const meta = isSurvey
    ? `설문 · ${surveyStatusLabel(survey.status)} · ${escapeHtml(item.targetLabel || `${item.targetCount || 0}명`)} · 응답 ${responseCount}/${Number(item.targetCount || 0)}`
    : `${imagePrefix}${escapeHtml(item.targetLabel || `${item.targetCount || 0}명`)} · 읽음 ${Number(item.readCount || 0)}/${Number(item.targetCount || 0)} · 답장 ${Number(item.replyCount || 0)}`;
  return `
    <button class="ann-list-item ${compact ? 'is-compact' : ''} ${active ? 'is-active' : ''} ${image ? 'has-image' : ''} ${isSurvey ? 'is-survey' : ''}" type="button" data-ann-id="${escapeHtml(item.id)}">
      ${image ? `<img class="ann-list-thumb" src="${escapeHtml(image.url)}" alt="">` : ''}
      <span>
        <strong>${escapeHtml(item.title || (isSurvey ? '설문조사' : '공지'))}</strong>
        <em>${meta}</em>
      </span>
      <small>${escapeHtml(timeLeftText(item.expiresAt))}</small>
    </button>
  `;
}

function renderExpandedAnnouncementList(items = visibleAnnouncementItems()) {
  const host = $('annReplyExpandList');
  const count = $('annReplyExpandListCount');
  if (!host) return;
  const visibleItems = Array.isArray(items) ? items : [];
  if (count) count.textContent = `${visibleItems.length}건`;
  if (!visibleItems.length) {
    host.innerHTML = `<div class="ann-empty">최근 4시간 안에 발행한 ${composeMode === 'survey' ? '설문' : '공지'}가 없습니다.</div>`;
    return;
  }
  host.innerHTML = visibleItems.map(item => renderAnnouncementListItem(item, { compact: true })).join('');
}

function selectAnnouncement(id) {
  if (!id) return;
  selectedAnnouncementId = String(id);
  renderAnnouncementList(latestAnnouncements);
}

function renderReplyDock(item) {
  const dock = $('annReplyDock');
  const title = $('annReplyTitle');
  const meta = $('annReplyMeta');
  const content = $('annReplyContent');
  const count = $('annReplyCount');
  const feed = $('annLiveReplies');
  const deleteBtn = $('annReplyDelete');
  const editBtn = $('annReplyEdit');
  const imageLink = $('annReplyImage');
  const imagePreview = $('annReplyImagePreview');
  if (!dock || !title || !meta || !content || !count || !feed) return;

  if (!item) {
    const isSurveyMode = composeMode === 'survey';
    title.textContent = isSurveyMode ? '설문 결과' : '공지 답장';
    meta.textContent = isSurveyMode ? '발행한 설문을 선택하면 결과가 표시됩니다.' : '발행한 공지를 선택하면 답장이 표시됩니다.';
    content.textContent = isSurveyMode ? '아직 선택된 설문이 없습니다.' : '아직 선택된 공지가 없습니다.';
    count.textContent = '0건';
    if (imageLink) {
      imageLink.hidden = true;
      imageLink.removeAttribute('href');
    }
    if (imagePreview) {
      imagePreview.removeAttribute('src');
      imagePreview.alt = '';
    }
    feed.innerHTML = `<div class="ann-empty">${isSurveyMode ? '설문' : '공지'} 목록에서 항목을 선택하세요.</div>`;
    if (deleteBtn) {
      deleteBtn.hidden = true;
      delete deleteBtn.dataset.annDelete;
    }
    if (editBtn) {
      editBtn.hidden = true;
      delete editBtn.dataset.annEdit;
    }
    syncExpandedReplyModal();
    return;
  }

  if (isSurveyItem(item)) {
    renderSurveyResultDock(item, { title, meta, content, count, feed, deleteBtn, editBtn, imageLink, imagePreview });
    return;
  }

  const replies = (Array.isArray(item.replies) ? item.replies : [])
    .slice()
    .sort((a, b) => new Date(b?.repliedAt || 0).getTime() - new Date(a?.repliedAt || 0).getTime());
  const images = normalizeImages(item.images, item.image);
  const image = images[0] || null;

  title.textContent = item.title || '공지';
  meta.textContent = `${formatDateTime(item.createdAt)} 발행 · ${timeLeftText(item.expiresAt)} · 읽음 ${Number(item.readCount || 0)}/${Number(item.targetCount || 0)}`;
  content.textContent = item.content || '';
  count.textContent = `${replies.length}건`;
  if (image && imageLink && imagePreview) {
    imageLink.hidden = false;
    imageLink.href = image.url;
    imageLink.removeAttribute('title');
    imagePreview.src = image.url;
    imagePreview.alt = item.title || '공지 이미지';
  } else {
    if (imageLink) {
      imageLink.hidden = true;
      imageLink.removeAttribute('href');
      imageLink.removeAttribute('title');
    }
    if (imagePreview) {
      imagePreview.removeAttribute('src');
      imagePreview.alt = '';
    }
  }
  if (deleteBtn) {
    deleteBtn.hidden = false;
    deleteBtn.dataset.annDelete = String(item.id || '');
  }
  if (editBtn) {
    editBtn.hidden = false;
    editBtn.dataset.annEdit = String(item.id || '');
  }

  const feedKey = `announcement:${item.id || ''}`;
  const previousFeedKey = feed.dataset.annFeedKey || '';
  const previousScrollTop = previousFeedKey === feedKey ? feed.scrollTop : 0;
  const shouldPinTop = previousFeedKey !== feedKey || previousScrollTop < 8;

  feed.innerHTML = replies.length ? replies.map(reply => `
    <article class="ann-chat-message" data-reply-id="${escapeHtml(reply.id || '')}"${anonymousReplyNameAttributes(reply)}>
      <div class="ann-chat-meta">
        <strong>${escapeHtml(replyDisplayName(reply))}</strong>
        <time>${escapeHtml(formatDateTime(reply.repliedAt))}</time>
      </div>
      <p>${escapeHtml(reply.reply || '')}</p>
    </article>
  `).join('') : '<div class="ann-empty">아직 도착한 답장이 없습니다.</div>';
  feed.dataset.annFeedKey = feedKey;

  requestAnimationFrame(() => {
    feed.scrollTop = shouldPinTop ? 0 : previousScrollTop;
  });
  syncExpandedReplyModal();
}

function renderSurveyResultDock(item, els) {
  const { title, meta, content, count, feed, deleteBtn, editBtn, imageLink, imagePreview } = els;
  const survey = item.survey || {};
  const results = item.surveyResults || {};
  const responseCount = Number(results.responseCount || item.surveyResponseCount || 0);
  const questions = Array.isArray(results.questions) ? results.questions : [];
  const submissions = Array.isArray(results.submissions) ? results.submissions : [];
  const images = normalizeImages(item.images, item.image);
  const image = images[0] || null;

  title.textContent = item.title || '설문조사';
  meta.textContent = `${formatDateTime(item.createdAt)} 발행 · ${timeLeftText(item.expiresAt)} · ${surveyStatusLabel(survey.status)} · 응답 ${responseCount}/${Number(item.targetCount || 0)}`;
  content.textContent = item.content || '';
  count.textContent = `${responseCount}건`;

  if (image && imageLink && imagePreview) {
    imageLink.hidden = false;
    imageLink.href = image.url;
    imageLink.removeAttribute('title');
    imagePreview.src = image.url;
    imagePreview.alt = item.title || '공지 이미지';
  } else {
    if (imageLink) {
      imageLink.hidden = true;
      imageLink.removeAttribute('href');
      imageLink.removeAttribute('title');
    }
    if (imagePreview) {
      imagePreview.removeAttribute('src');
      imagePreview.alt = '';
    }
  }
  if (deleteBtn) {
    deleteBtn.hidden = false;
    deleteBtn.dataset.annDelete = String(item.id || '');
  }
  if (editBtn) {
    editBtn.hidden = false;
    editBtn.dataset.annEdit = String(item.id || '');
  }

  if (!questions.length) {
    feed.innerHTML = '<div class="ann-empty">아직 설문 결과가 없습니다.</div>';
    syncExpandedReplyModal();
    return;
  }

  const latest = submissions.slice(0, 6).map(submission => `
    <div class="ann-survey-submission">
      <strong>${escapeHtml(submission.displayName || '익명')}</strong>
      <time>${escapeHtml(formatDateTime(submission.submittedAt))}</time>
    </div>
  `).join('');

  const feedKey = `survey:${item.id || ''}`;
  const previousFeedKey = feed.dataset.annFeedKey || '';
  const previousScrollTop = previousFeedKey === feedKey ? feed.scrollTop : 0;
  const shouldPinTop = previousFeedKey !== feedKey || previousScrollTop < 8;

  feed.innerHTML = `
    <div class="ann-survey-result-summary">
      <strong>${responseCount}</strong>
      <span>전체 응답</span>
      <em>${survey.anonymous ? '익명 응답' : '실명 응답'} · ${survey.allowMultiple ? '중복 허용' : '1회 제출'}</em>
    </div>
    ${questions.map(question => {
      const type = question.type || '';
      if (type === 'single' || type === 'multiple') {
        const options = Array.isArray(question.options) ? question.options : [];
        return `
          <article class="ann-survey-result-card">
            <div class="ann-survey-result-card-head">
              <strong>${escapeHtml(question.text || '질문')}</strong>
              <span>${escapeHtml(surveyTypeLabel(type))} · ${Number(question.responseCount || 0)}명</span>
            </div>
            <div class="ann-survey-result-options">
              ${options.map(option => {
                const percent = Number(option.percent || 0);
                return `
                  <div class="ann-survey-result-option">
                    <div>
                      <span>${escapeHtml(option.text || '')}</span>
                      <em>${Number(option.count || 0)}명 · ${percent}%</em>
                    </div>
                    <i style="--survey-bar:${Math.max(0, Math.min(100, percent))}%"></i>
                  </div>
                `;
              }).join('')}
            </div>
          </article>
        `;
      }
      const answers = Array.isArray(question.answers) ? question.answers : [];
      return `
        <article class="ann-survey-result-card">
          <div class="ann-survey-result-card-head">
            <strong>${escapeHtml(question.text || '질문')}</strong>
            <span>${escapeHtml(surveyTypeLabel(type))} · ${answers.length}건</span>
          </div>
          <div class="ann-survey-text-answers">
            ${answers.length ? answers.map(answer => `
              <div class="ann-survey-text-answer">
                <div>
                  <strong>${escapeHtml(answer.displayName || '익명')}</strong>
                  <time>${escapeHtml(formatDateTime(answer.submittedAt))}</time>
                </div>
                <p>${escapeHtml(answer.answer || '')}</p>
              </div>
            `).join('') : '<div class="ann-empty">아직 주관식 답변이 없습니다.</div>'}
          </div>
        </article>
      `;
    }).join('')}
    <div class="ann-survey-latest">
      <strong>최근 제출</strong>
      ${latest || '<span>아직 제출된 응답이 없습니다.</span>'}
    </div>
  `;
  feed.dataset.annFeedKey = feedKey;

  requestAnimationFrame(() => {
    feed.scrollTop = shouldPinTop ? 0 : previousScrollTop;
  });
  syncExpandedReplyModal();
}

function selectedReplyItem() {
  return latestAnnouncements.find(item => String(item?.id) === String(selectedAnnouncementId)) || null;
}

function syncExpandedReplyModal() {
  const modal = $('annReplyExpandModal');
  if (!modal || modal.hidden) return;

  const item = selectedReplyItem();
  const isSurvey = isSurveyItem(item);
  const sourceImage = $('annReplyImage');
  const sourceImagePreview = $('annReplyImagePreview');
  const image = $('annReplyExpandImage');
  const imagePreview = $('annReplyExpandImagePreview');
  const feed = $('annReplyExpandFeed');

  const kicker = $('annReplyExpandKicker');
  const title = $('annReplyExpandTitle');
  const meta = $('annReplyExpandMeta');
  const content = $('annReplyExpandContent');
  const count = $('annReplyExpandCount');
  const feedLabel = $('annReplyExpandFeedLabel');
  const editBtn = $('annReplyExpandEdit');
  const deleteBtn = $('annReplyExpandDelete');

  if (kicker) kicker.textContent = isSurvey ? '설문 결과' : '실시간 답장';
  if (title) title.textContent = $('annReplyTitle')?.textContent || (isSurvey ? '설문 결과' : '공지 답장');
  if (meta) meta.textContent = $('annReplyMeta')?.textContent || '';
  if (content) content.textContent = $('annReplyContent')?.textContent || '';
  if (count) count.textContent = $('annReplyCount')?.textContent || '0건';
  if (feedLabel) feedLabel.textContent = isSurvey ? '설문 결과' : '답장 피드';
  if (item) {
    if (editBtn) {
      editBtn.hidden = false;
      editBtn.dataset.annEdit = String(item.id || '');
    }
    if (deleteBtn) {
      deleteBtn.hidden = false;
      deleteBtn.dataset.annDelete = String(item.id || '');
    }
  } else {
    if (editBtn) {
      editBtn.hidden = true;
      delete editBtn.dataset.annEdit;
    }
    if (deleteBtn) {
      deleteBtn.hidden = true;
      delete deleteBtn.dataset.annDelete;
    }
  }
  if (feed) {
    const feedKey = `${isSurvey ? 'survey' : 'announcement'}:${item?.id || ''}:expanded`;
    const previousFeedKey = feed.dataset.annFeedKey || '';
    const previousScrollTop = previousFeedKey === feedKey ? feed.scrollTop : 0;
    const shouldPinTop = previousFeedKey !== feedKey || previousScrollTop < 8;
    feed.innerHTML = $('annLiveReplies')?.innerHTML || '<div class="ann-empty">표시할 내용이 없습니다.</div>';
    feed.dataset.annFeedKey = feedKey;
    requestAnimationFrame(() => {
      feed.scrollTop = shouldPinTop ? 0 : previousScrollTop;
    });
  }

  if (image && imagePreview && sourceImage && sourceImagePreview && !sourceImage.hidden && sourceImagePreview.getAttribute('src')) {
    image.hidden = false;
    image.href = sourceImage.getAttribute('href') || '#';
    image.removeAttribute('title');
    imagePreview.src = sourceImagePreview.getAttribute('src') || '';
    imagePreview.alt = sourceImagePreview.getAttribute('alt') || '공지 이미지';
  } else {
    if (image) {
      image.hidden = true;
      image.removeAttribute('href');
      image.removeAttribute('title');
    }
    if (imagePreview) {
      imagePreview.removeAttribute('src');
      imagePreview.alt = '';
    }
  }
}

function openExpandedReplyModal() {
  const modal = $('annReplyExpandModal');
  if (!modal) return;
  modal.hidden = false;
  syncExpandedReplyModal();
  requestAnimationFrame(() => {
    $('annReplyExpandClose')?.focus();
  });
}

function closeExpandedReplyModal() {
  const modal = $('annReplyExpandModal');
  if (!modal || modal.hidden) return;
  modal.hidden = true;
  $('annReplyExpand')?.focus();
}

async function loadAndRenderAnnouncements() {
  const res = await fetch('/api/announce-status', { cache: 'no-store' });
  if (!res.ok) throw new Error(`공지 목록 로드 실패 (${res.status})`);
  const data = await res.json();
  latestAnnouncements = Array.isArray(data) ? data : [];
  renderAnnouncementList(latestAnnouncements);
}

function bindTargetMenu() {
  const targetBtn = $('annTargetBtn');
  const menu = $('annTargetMenu');
  if (!targetBtn || !menu) return;

  targetBtn.addEventListener('click', () => {
    syncRoster();
    menu.hidden = !menu.hidden;
  });

  document.addEventListener('click', (ev) => {
    if (menu.hidden) return;
    if (ev.target?.closest?.('#annTargetMenu, #annTargetBtn')) return;
    menu.hidden = true;
  });

  menu.addEventListener('click', (ev) => {
    const modeBtn = ev.target.closest('[data-target-mode]');
    if (!modeBtn) return;
    targetMode = modeBtn.dataset.targetMode || 'today';
    if (!['direct', 'curriculum', 'grade'].includes(targetMode)) menu.hidden = true;
    updateTargetSummary();
    renderExpandedSurveyBuilder();
  });

  menu.addEventListener('change', (ev) => {
    const filter = ev.target.closest('[data-ann-target-filter]');
    if (!filter) return;
    const key = filter.dataset.annTargetFilter;
    if (key && Object.prototype.hasOwnProperty.call(targetFilters, key)) {
      targetFilters = { ...targetFilters, [key]: filter.value || '' };
      renderTargetFilterOptions();
      updateTargetSummary();
      refreshExpandedSurveyDerivedViews();
    }
  });

  const search = $('annDirectSearch');
  applySearchPlaceholder(search, '학생 검색');
  search?.addEventListener('input', renderDirectList);
  search?.addEventListener('search', renderDirectList);
  search?.addEventListener('compositionend', renderDirectList);
  document.addEventListener('keydown', (ev) => {
    if (ev.key !== 'Escape') return;
    if (menu.hidden) return;
    ev.preventDefault();
    ev.stopPropagation();
    ev.stopImmediatePropagation?.();
    if (targetMode !== 'direct') {
      menu.hidden = true;
      targetBtn.focus();
      return;
    }
    const hasSearchText = !!String(search?.value || '').trim();
    if (search && hasSearchText) {
      search.value = '';
      renderDirectList();
      search.focus();
      search.select?.();
      return;
    }
    if (search && document.activeElement !== search) {
      search.focus();
      search.select?.();
      return;
    }
    menu.hidden = true;
    targetBtn.focus();
  }, true);

  $('annDirectList')?.addEventListener('change', (ev) => {
    const input = ev.target.closest('input[type="checkbox"]');
    if (!input) return;
    if (input.checked) directSelected.add(String(input.value));
    else directSelected.delete(String(input.value));
    updateTargetSummary();
  });

  $('annSelectAllVisible')?.addEventListener('click', () => {
    const query = $('annDirectSearch')?.value || '';
    rosterBaseRows()
      .filter(row => matchesSearchKey(row.key, query))
      .forEach(row => directSelected.add(row.sid));
    renderDirectList();
    updateTargetSummary();
  });

  $('annClearSelected')?.addEventListener('click', () => {
    directSelected.clear();
    renderDirectList();
    updateTargetSummary();
  });
}

function bindAnnouncementBoard() {
  $('annPublish')?.addEventListener('click', async () => {
    try {
      await publishAnnouncement();
    } catch (err) {
      console.error(err);
      alert(err?.message || '공지 등록 실패');
    }
  });

  $('annComposeExpand')?.addEventListener('click', openComposeExpandModal);
  $('annComposeCompactOpen')?.addEventListener('click', openComposeExpandModal);
  $('annComposeExpandClose')?.addEventListener('click', () => closeComposeExpandModal());
  $('annComposeExpandModal')?.addEventListener('pointerdown', (ev) => {
    composeBackdropPointerDown = ev.target === $('annComposeExpandModal');
  });
  $('annComposeExpandModal')?.addEventListener('click', (ev) => {
    if (ev.target.closest('[data-ann-preview-remove-image]')) {
      setSelectedImages([]);
      toast('첨부 이미지를 제거했습니다.');
      return;
    }
    if (ev.target === $('annComposeExpandModal') && composeBackdropPointerDown) {
      closeComposeExpandModal();
    }
    composeBackdropPointerDown = false;
  });
  $('annReplyExpand')?.addEventListener('click', openExpandedReplyModal);
  $('annReplyExpandClose')?.addEventListener('click', closeExpandedReplyModal);
  $('annReplyExpandModal')?.addEventListener('click', (ev) => {
    if (ev.target === $('annReplyExpandModal')) closeExpandedReplyModal();
  });

  $('annReplyExpandEdit')?.addEventListener('click', (ev) => {
    const id = ev.currentTarget?.dataset?.annEdit || '';
    if (!id) return;
    closeExpandedReplyModal();
    beginAnnouncementEdit(id);
  });

  $('annReplyExpandDelete')?.addEventListener('click', async (ev) => {
    const id = ev.currentTarget?.dataset?.annDelete || '';
    if (!id) return;
    try {
      await deleteAnnouncement(id);
    } catch (err) {
      console.error(err);
      alert('공지 삭제 실패');
    }
  });

  $('annList')?.addEventListener('click', (ev) => {
    const item = ev.target.closest('[data-ann-id]');
    if (!item) return;
    selectAnnouncement(item.dataset.annId || '');
  });

  $('annReplyExpandList')?.addEventListener('click', (ev) => {
    const item = ev.target.closest('[data-ann-id]');
    if (!item) return;
    selectAnnouncement(item.dataset.annId || '');
  });

  $('annReplyDock')?.addEventListener('click', async (ev) => {
    const edit = ev.target.closest('[data-ann-edit]');
    if (edit) {
      beginAnnouncementEdit(edit.dataset.annEdit || '');
      return;
    }
    const btn = ev.target.closest('[data-ann-delete]');
    if (!btn) return;
    try {
      await deleteAnnouncement(btn.dataset.annDelete || '');
    } catch (err) {
      console.error(err);
      alert('공지 삭제 실패');
    }
  });

  document.addEventListener('keydown', (ev) => {
    if (ev.key !== 'Escape') return;
    const composeExpanded = $('annComposeExpandModal');
    if (!composeExpanded?.hidden) {
      ev.preventDefault();
      ev.stopPropagation();
      ev.stopImmediatePropagation?.();
      closeComposeExpandModal();
      return;
    }
    const expanded = $('annReplyExpandModal');
    if (!expanded?.hidden) {
      ev.preventDefault();
      ev.stopPropagation();
      ev.stopImmediatePropagation?.();
      closeExpandedReplyModal();
      return;
    }
  }, true);

  document.addEventListener('keydown', (ev) => {
    if (ev.key !== 'Escape') return;
    const shell = $('annBoardShell');
    if (!shell?.open) return;
    ev.preventDefault();
    ev.stopPropagation();
    ev.stopImmediatePropagation?.();
    shell.open = false;
    shell.querySelector('summary')?.focus?.();
  }, true);
}

export function initAnnouncements() {
  if (!$('announcementSection')) return;
  ensureAnnouncementControls();
  bindImageTools();
  bindExpiryControls();
  bindTargetMenu();
  bindSurveyBuilder();
  bindExpandedSurveyBuilder();
  bindAnnouncementBoard();
  bindAnonymousReplyNameReveal();
  setComposeMode('announcement');
  syncRoster();
  loadAndRenderAnnouncements().catch((err) => {
    console.warn('[announcements] initial load failed:', err);
    const host = $('annList');
    if (host) host.innerHTML = '<div class="ann-empty">공지 목록을 불러오지 못했습니다.</div>';
  });

  document.addEventListener('today:rendered', (ev) => {
    syncRoster(ev?.detail?.students || null);
  });

  if (!refreshTimer) {
    refreshTimer = window.setInterval(() => {
      if (document.hidden) return;
      loadAndRenderAnnouncements().catch(() => {});
    }, 10000);
  }
}
