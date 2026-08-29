import { getAdminDate } from '../core/adminDate.js';
import { api } from '../core/api.js';
import { state } from '../core/state.js';

const API_ROOT = '/api/student-test-ocr/admin';

function node(tag, className = '', text = '') {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text) element.textContent = text;
  return element;
}

function studentName(sid) {
  const student = (Array.isArray(state.students) ? state.students : []).find(item => String(item?.id || '') === String(sid));
  return student?.name ? `${student.name} (${sid})` : String(sid);
}

async function postStrict(url, body, label) {
  const response = await api.post(url, body, { cache: 'no-store' });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok || payload?.ok === false) {
    const error = new Error(payload?.message || `${label} failed`);
    error.code = payload?.code || 'request_failed';
    error.status = response.status;
    throw error;
  }
  return payload;
}

function gradeLabel(grade) {
  if (grade === 'pending') return '보류';
  if (grade === 'incorrect') return '오답';
  if (grade === 'correct') return '정답';
  return '미채점';
}

export function initStudentTestOcrReview() {
  const openButton = document.getElementById('studentTestOcrReviewOpen');
  const modal = document.getElementById('studentTestOcrReviewModal');
  const closeButton = document.getElementById('studentTestOcrReviewClose');
  const refreshButton = document.getElementById('studentTestOcrReviewRefresh');
  const dateNode = document.getElementById('studentTestOcrReviewDate');
  const statusNode = document.getElementById('studentTestOcrReviewStatus');
  const list = document.getElementById('studentTestOcrReviewList');
  const detail = document.getElementById('studentTestOcrReviewDetail');
  if (!openButton || !modal || !closeButton || !refreshButton || !dateNode || !statusNode || !list || !detail) return;

  let frozenDate = '';
  let activeSubmissionId = '';
  let opener = null;
  let requestSequence = 0;

  function setBusy(busy) {
    modal.setAttribute('aria-busy', busy ? 'true' : 'false');
    refreshButton.disabled = busy;
  }

  function renderEmpty(message = '왼쪽에서 학생 제출을 선택해 주세요.') {
    detail.replaceChildren(node('p', 'student-test-ocr-admin-empty', message));
  }

  function pendingButtons() {
    return [...list.querySelectorAll('.student-test-ocr-admin-submission')];
  }

  async function mutate(detailPayload, action, button) {
    button.disabled = true;
    try {
      const updated = await postStrict(
        `${API_ROOT}/submissions/${encodeURIComponent(detailPayload.submissionId)}/${action.endpoint}`,
        {
          questionNo: action.questionNo,
          revision: detailPayload.revision,
          ...(action.endpoint === 'resolve' ? { correct: action.correct } : {}),
        },
        'OCR review mutation',
      );
      renderDetail(updated);
      await loadPending({ preserveDetail: true });
    } catch (error) {
      if (error?.code === 'revision_conflict') {
        await loadDetail(detailPayload.submissionId);
      } else {
        statusNode.classList.add('is-error');
        statusNode.textContent = error?.message || '판정 결과를 저장하지 못했습니다.';
      }
    } finally {
      button.disabled = false;
    }
  }

  function renderQuestion(detailPayload, question) {
    const card = node('article', 'student-test-ocr-admin-question');
    const head = node('div', 'student-test-ocr-admin-question-head');
    const title = node('strong', '', `${question.questionNo}번 · ${question.answerMode === 'choice_number' ? '객관식 숫자' : '주관식 단답'}`);
    const grade = node('span', `student-test-ocr-admin-grade${question.effectiveGrade === 'incorrect' ? ' is-incorrect' : ''}`, gradeLabel(question.effectiveGrade));
    head.append(title, grade);
    card.append(head);

    const compare = node('div', 'student-test-ocr-admin-compare');
    const studentCrop = node('div', 'student-test-ocr-admin-crop');
    studentCrop.append(node('strong', '', `학생 촬영 · 인식 ${question.currentAnswer || '불확실'}`));
    if (question.studentCropUrl) {
      const image = node('img');
      image.src = question.studentCropUrl;
      image.alt = `${question.questionNo}번 학생 답안 crop`;
      image.loading = 'lazy';
      studentCrop.append(image);
    } else {
      studentCrop.append(node('p', 'student-test-ocr-admin-empty', '학생 crop이 만료되었거나 없습니다.'));
    }

    const solutionCrop = node('div', 'student-test-ocr-admin-crop');
    solutionCrop.append(node('strong', '', '실제 답지'));
    if (question.solutionCropUrl) {
      const image = node('img');
      image.src = question.solutionCropUrl;
      image.alt = `${question.questionNo}번 실제 답지 crop`;
      image.loading = 'lazy';
      solutionCrop.append(image);
    } else {
      solutionCrop.append(node('div', 'student-test-ocr-admin-answer', question.expectedAnswer || '확인 필요'));
      if (detailPayload.answerUrl) {
        const link = node('a', 'student-test-ocr-admin-answer-link', '답지 원본에서 확인');
        link.href = detailPayload.answerUrl;
        link.target = '_blank';
        link.rel = 'noopener noreferrer';
        solutionCrop.append(link);
      }
    }
    compare.append(studentCrop, solutionCrop);
    card.append(compare);

    const actions = node('div', 'student-test-ocr-admin-actions');
    if (question.effectiveGrade === 'pending') {
      const incorrect = node('button', 'btn secondary', '오답으로 확정');
      incorrect.type = 'button';
      incorrect.addEventListener('click', () => void mutate(detailPayload, {
        endpoint: 'resolve', questionNo: question.questionNo, correct: false,
      }, incorrect));
      const correct = node('button', 'btn', '정답으로 확정');
      correct.type = 'button';
      correct.addEventListener('click', () => void mutate(detailPayload, {
        endpoint: 'resolve', questionNo: question.questionNo, correct: true,
      }, correct));
      actions.append(incorrect, correct);
    } else if (question.effectiveGrade === 'incorrect') {
      const correct = node('button', 'btn', '오답 → 정답 수정');
      correct.type = 'button';
      correct.addEventListener('click', () => void mutate(detailPayload, {
        endpoint: 'correct', questionNo: question.questionNo,
      }, correct));
      actions.append(correct);
    }
    if (actions.childElementCount) card.append(actions);
    return card;
  }

  function renderDetail(payload) {
    detail.replaceChildren();
    const head = node('header', 'student-test-ocr-admin-detail-head');
    const identity = node('div');
    identity.append(
      node('h4', '', `${studentName(payload.sid)} · ${payload.testName}`),
      node('p', '', `${payload.assignmentDate} · ${payload.round}회차 · 제출 ${payload.submissionId}`),
    );
    const result = payload.result || {};
    head.append(identity, node('span', 'student-test-ocr-admin-result', `정답 ${result.correctCount || 0} · 오답 ${result.incorrectCount || 0} · 보류 ${result.pendingCount || 0}`));
    detail.append(head);
    const relevant = (Array.isArray(payload.questions) ? payload.questions : []).filter(question => (
      question.effectiveGrade === 'pending' || question.effectiveGrade === 'incorrect'
    ));
    if (!relevant.length) {
      detail.append(node('p', 'student-test-ocr-admin-empty', '현재 확인하거나 수정할 문항이 없습니다.'));
      return;
    }
    const questions = node('div', 'student-test-ocr-admin-question-list');
    relevant.forEach(question => questions.append(renderQuestion(payload, question)));
    detail.append(questions);
  }

  async function loadDetail(submissionId) {
    const sequence = ++requestSequence;
    activeSubmissionId = submissionId;
    pendingButtons().forEach(button => button.setAttribute('aria-current', String(button.dataset.submissionId === submissionId)));
    detail.replaceChildren(node('p', 'student-test-ocr-admin-empty', '제출 상세를 불러오는 중입니다.'));
    try {
      const payload = await api.getStrict(
        `${API_ROOT}/submissions/${encodeURIComponent(submissionId)}`,
        'student test OCR admin detail',
        { cache: 'no-store' },
      );
      if (sequence !== requestSequence) return;
      renderDetail(payload);
    } catch (error) {
      if (sequence !== requestSequence) return;
      renderEmpty('제출 상세를 불러오지 못했습니다. 새로고침 후 다시 시도해 주세요.');
    }
  }

  function renderPending(items) {
    list.replaceChildren();
    if (!items.length) {
      list.append(node('p', 'student-test-ocr-admin-empty', '이 날짜의 보류 제출이 없습니다.'));
      return;
    }
    items.forEach(item => {
      const button = node('button', 'student-test-ocr-admin-submission');
      button.type = 'button';
      button.dataset.submissionId = item.submissionId;
      button.setAttribute('aria-current', String(item.submissionId === activeSubmissionId));
      button.append(
        node('strong', '', studentName(item.sid)),
        node('span', '', `${item.testId} · ${item.round}회차`),
        node('span', '', `보류 ${item.pendingQuestionNos.join(', ')}번`),
      );
      button.addEventListener('click', () => void loadDetail(item.submissionId));
      list.append(button);
    });
  }

  async function loadPending({ preserveDetail = false } = {}) {
    const sequence = ++requestSequence;
    setBusy(true);
    statusNode.classList.remove('is-error');
    statusNode.textContent = '보류 제출을 불러오는 중입니다.';
    try {
      const payload = await api.getStrict(
        `${API_ROOT}/pending?date=${encodeURIComponent(frozenDate)}`,
        'student test OCR pending list',
        { cache: 'no-store' },
      );
      if (sequence !== requestSequence) return;
      const items = Array.isArray(payload.submissions) ? payload.submissions : [];
      renderPending(items);
      statusNode.textContent = items.length ? `${items.length}건을 당일 내 확인해 주세요.` : '확인 대기 중인 제출이 없습니다.';
      openButton.textContent = items.length ? `OCR 보류 ${items.length}` : 'OCR 보류';
      openButton.classList.toggle('has-pending', items.length > 0);
      if (!preserveDetail && activeSubmissionId && !items.some(item => item.submissionId === activeSubmissionId)) {
        activeSubmissionId = '';
        renderEmpty();
      }
    } catch (error) {
      if (sequence !== requestSequence) return;
      list.replaceChildren();
      statusNode.classList.add('is-error');
      statusNode.textContent = '보류 제출을 불러오지 못했습니다.';
    } finally {
      if (sequence === requestSequence) setBusy(false);
    }
  }

  async function refreshBadge() {
    try {
      const payload = await api.getStrict(
        `${API_ROOT}/pending?date=${encodeURIComponent(getAdminDate())}`,
        'student test OCR pending badge',
        { cache: 'no-store' },
      );
      const count = Array.isArray(payload.submissions) ? payload.submissions.length : 0;
      openButton.textContent = count ? `OCR 보류 ${count}` : 'OCR 보류';
      openButton.classList.toggle('has-pending', count > 0);
    } catch {}
  }

  function close() {
    requestSequence += 1;
    modal.hidden = true;
    modal.style.display = 'none';
    document.body.classList.remove('student-test-ocr-admin-open');
    if (opener instanceof HTMLElement && opener.isConnected) opener.focus();
  }

  function trap(event) {
    if (event.key === 'Escape') {
      event.preventDefault();
      close();
      return;
    }
    if (event.key !== 'Tab') return;
    const controls = [...modal.querySelectorAll('button:not([disabled]):not([hidden]), a[href]')];
    if (!controls.length) return;
    const first = controls[0];
    const last = controls[controls.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault(); last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault(); first.focus();
    }
  }

  openButton.addEventListener('click', () => {
    opener = document.activeElement;
    frozenDate = getAdminDate();
    activeSubmissionId = '';
    dateNode.textContent = `${frozenDate} · 보류 문항은 당일 확정 대상, crop은 7일 보관`;
    modal.hidden = false;
    modal.style.display = 'flex';
    document.body.classList.add('student-test-ocr-admin-open');
    renderEmpty();
    closeButton.focus();
    void loadPending();
  });
  closeButton.addEventListener('click', close);
  refreshButton.addEventListener('click', () => void loadPending());
  modal.addEventListener('keydown', trap);
  document.addEventListener('admin:date-change', () => {
    if (modal.hidden) void refreshBadge();
  });

  void api.getStrict(`${API_ROOT}/capabilities`, 'student test OCR admin capabilities', { cache: 'no-store' })
    .then(payload => {
      if (payload?.enabled !== true || payload?.review !== true) return;
      openButton.hidden = false;
      void refreshBadge();
    })
    .catch(() => {});
}
