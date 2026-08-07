import { api } from '../core/api.js';

const MAX_NOTE_LENGTH = 5000;
const AUTHORS = ['귤', '세빈', '동훈', '하영'];
const AUTHOR_TAGS = {
  귤: '규리',
  세빈: '세빈',
  동훈: '동훈',
  하영: '하영',
};

function formatMemoDate(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value || '');
  return `${date.getMonth() + 1}.${date.getDate()}`;
}

async function sendRequest(url, method, body) {
  const response = await api.post(url, body, { method, cache: 'no-store' });
  const data = await response.json().catch(() => ({}));
  if (!response.ok || data?.ok === false) {
    throw new Error(data?.error || `요청 실패 (${response.status})`);
  }
  return data;
}

function setStatus(root, message, kind = '') {
  const status = root.querySelector('[data-note-status]');
  if (!status) return;
  status.textContent = message;
  status.className = `assistant-note-status${kind ? ` is-${kind}` : ''}`;
}

function setMeta(root, note) {
  const meta = root.querySelector('[data-note-meta]');
  if (!meta) return;
  if (!note) {
    meta.textContent = '저장된 메모 없음';
    return;
  }
  const savedAuthor = String(note.updated_by || note.created_by || '');
  const authorTag = AUTHOR_TAGS[savedAuthor];
  const dateLabel = formatMemoDate(note.updated_at || note.created_at);
  meta.textContent = authorTag
    ? `마지막 저장 ${dateLabel} [${authorTag}]`
    : `마지막 저장 ${dateLabel}`;
}

function setSelectedAuthor(root, author) {
  if (AUTHORS.includes(author)) {
    root.dataset.noteSelectedAuthor = author;
  } else {
    delete root.dataset.noteSelectedAuthor;
  }
  root.querySelectorAll('[data-note-author]').forEach((button) => {
    const selected = button.dataset.noteAuthor === author;
    button.classList.toggle('is-selected', selected);
    button.setAttribute('aria-pressed', selected ? 'true' : 'false');
  });
}

function setNoteColorAuthor(root, author) {
  if (AUTHORS.includes(author)) {
    root.dataset.noteColorAuthor = author;
  } else {
    delete root.dataset.noteColorAuthor;
  }
}

function syncAuthorTag(input, author, previousAuthor = '', now = new Date()) {
  const tagName = AUTHOR_TAGS[author];
  if (!tagName) return false;
  const tag = `${formatMemoDate(now)} [${tagName}]`;
  const value = input.value || '';
  const hasExistingContent = Boolean(value.trim());
  const switchesAuthor = hasExistingContent && author !== previousAuthor;
  const nextValue = !hasExistingContent
    ? `${tag} `
    : switchesAuthor
      ? `${value}${value.endsWith('\n') ? '' : '\n'}${tag} `
      : value;

  if (nextValue.length > MAX_NOTE_LENGTH) return false;
  input.value = nextValue;
  input.focus();
  const cursorPosition = switchesAuthor || !hasExistingContent
    ? nextValue.length
    : value.length;
  input.setSelectionRange(cursorPosition, cursorPosition);
  return true;
}

async function mountMemo(root, studentId) {
  if (!(root instanceof Element) || !studentId) return;
  const mountKey = `${studentId}:${Date.now()}:${Math.random()}`;
  root.dataset.mountKey = mountKey;
  const input = root.querySelector('[data-note-input]');
  const saveButton = root.querySelector('[data-note-save]');
  const authorButtons = [...root.querySelectorAll('[data-note-author]')];
  let currentNote = null;
  let selectedAuthor = '';
  let savedAuthor = '';
  let draftAuthor = '';

  if (!input || !saveButton || authorButtons.length !== AUTHORS.length) return;
  input.disabled = true;
  saveButton.disabled = true;
  const isCurrent = () => root.isConnected && root.dataset.mountKey === mountKey;

  authorButtons.forEach((button) => {
    button.addEventListener('click', () => {
      const author = String(button.dataset.noteAuthor || '');
      if (!AUTHORS.includes(author)) return;
      if (!syncAuthorTag(input, author, draftAuthor)) {
        setStatus(root, '메모가 너무 길어 작성자 이름을 추가할 수 없습니다.', 'error');
        return;
      }
      selectedAuthor = author;
      draftAuthor = author;
      setSelectedAuthor(root, author);
      if (!currentNote) setNoteColorAuthor(root, author);
      setStatus(root, '');
    });
  });

  saveButton.addEventListener('click', async () => {
    const content = input.value.trim();
    if (!AUTHORS.includes(selectedAuthor)) {
      setStatus(root, '작성자를 선택해 주세요.', 'error');
      authorButtons[0].focus();
      return;
    }

    input.disabled = true;
    saveButton.disabled = true;
    setStatus(root, '저장 중...', 'saving');
    try {
      const url = currentNote
        ? `/api/assistant-student-notes/${currentNote.id}`
        : '/api/assistant-student-notes';
      const method = currentNote ? 'PATCH' : 'POST';
      const data = await sendRequest(url, method, {
        student_id: studentId,
        content,
        author: selectedAuthor,
      });
      if (!isCurrent()) return;
      currentNote = data.note;
      input.value = currentNote.content;
      savedAuthor = String(currentNote.updated_by || currentNote.created_by || '');
      selectedAuthor = AUTHORS.includes(savedAuthor) ? savedAuthor : selectedAuthor;
      draftAuthor = '';
      setSelectedAuthor(root, selectedAuthor);
      setNoteColorAuthor(root, savedAuthor);
      setMeta(root, currentNote);
      setStatus(root, '저장 완료', 'success');
    } catch (error) {
      if (isCurrent()) setStatus(root, '저장 실패. 다시 시도해 주세요.', 'error');
    } finally {
      if (isCurrent()) {
        input.disabled = false;
        saveButton.disabled = false;
      }
    }
  });

  setStatus(root, '불러오는 중...', 'loading');
  try {
    const data = await api.getStrict(
      `/api/assistant-student-notes?student_id=${encodeURIComponent(studentId)}`,
      'assistant notes',
      { cache: 'no-store' },
    );
    if (!isCurrent()) return;
    const notes = Array.isArray(data?.notes) ? data.notes : [];
    currentNote = notes[0] || null;
    input.value = currentNote?.content || '';
    savedAuthor = String(currentNote?.updated_by || currentNote?.created_by || '');
    selectedAuthor = AUTHORS.includes(savedAuthor) ? savedAuthor : '';
    draftAuthor = '';
    setSelectedAuthor(root, selectedAuthor);
    setNoteColorAuthor(root, savedAuthor);
    setMeta(root, currentNote);
    setStatus(root, '');
    input.disabled = false;
    saveButton.disabled = false;
  } catch (error) {
    if (!isCurrent()) return;
    setMeta(root, null);
    setStatus(root, '메모를 불러오지 못했습니다. 새로고침해 주세요.', 'error');
  }
}

export function initAssistantStudentNotes() {
  document.addEventListener('admin:assistant-notes-mount', (event) => {
    const root = event.detail?.root;
    const studentId = String(event.detail?.studentId || '').trim();
    mountMemo(root, studentId);
  });
}
