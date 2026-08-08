import { api } from '../core/api.js';

const MAX_NOTE_LENGTH = 5000;
const AUTHORS = ['귤', '세빈', '동훈', '하영'];
const AUTHOR_LABELS = {
  귤: '규리',
  세빈: '세빈',
  동훈: '동훈',
  하영: '하영',
};

function formatNoteDate(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value || '');
  return new Intl.DateTimeFormat('ko-KR', {
    year: 'numeric',
    month: 'numeric',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(date);
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

function setSelectedAuthor(root, author) {
  if (AUTHORS.includes(author)) {
    root.dataset.noteSelectedAuthor = author;
  } else {
    delete root.dataset.noteSelectedAuthor;
  }
  root.querySelectorAll('.assistant-note-author-buttons [data-note-author]').forEach((button) => {
    const selected = button.dataset.noteAuthor === author;
    button.classList.toggle('is-selected', selected);
    button.setAttribute('aria-pressed', selected ? 'true' : 'false');
  });
}

function setComposerDisabled(input, saveButton, authorButtons, disabled) {
  input.disabled = disabled;
  saveButton.disabled = disabled;
  authorButtons.forEach((button) => {
    button.disabled = disabled;
  });
}

function renderNotes(root, notes, { scrollToLatest = true, onDelete = null } = {}) {
  const list = root.querySelector('[data-note-list]');
  const count = root.querySelector('[data-note-count]');
  if (!list || !count) return;

  list.replaceChildren();
  count.textContent = `댓글 ${notes.length}개`;

  if (!notes.length) {
    const empty = document.createElement('p');
    empty.className = 'assistant-note-empty';
    empty.textContent = '아직 등록된 댓글이 없습니다.';
    list.appendChild(empty);
    return;
  }

  notes.slice().reverse().forEach((note) => {
    const author = String(note.updated_by || note.created_by || '');
    const article = document.createElement('article');
    article.className = 'assistant-note-item';
    article.dataset.noteId = String(note.id || '');
    if (AUTHORS.includes(author)) article.dataset.noteAuthor = author;

    const header = document.createElement('div');
    header.className = 'assistant-note-item-header';

    const authorName = document.createElement('strong');
    authorName.className = 'assistant-note-item-author';
    const authorLabel = AUTHOR_LABELS[author] || author || '이전 메모';
    authorName.textContent = authorLabel;

    const time = document.createElement('time');
    time.className = 'assistant-note-item-time';
    const savedAt = String(note.updated_at || note.created_at || '');
    if (savedAt) time.dateTime = savedAt;
    time.textContent = formatNoteDate(savedAt);

    const deleteButton = document.createElement('button');
    deleteButton.type = 'button';
    deleteButton.className = 'assistant-note-delete';
    deleteButton.dataset.noteDelete = String(note.id || '');
    deleteButton.setAttribute('aria-label', `${authorLabel} 댓글 삭제`);
    deleteButton.title = '댓글 삭제';
    deleteButton.textContent = '삭제';
    deleteButton.addEventListener('click', () => onDelete?.(note, deleteButton));

    const meta = document.createElement('div');
    meta.className = 'assistant-note-item-meta';
    meta.append(time, deleteButton);

    const content = document.createElement('p');
    content.className = 'assistant-note-item-content';
    content.textContent = String(note.content || '') || '내용 없는 이전 메모';

    header.append(authorName, meta);
    article.append(header, content);
    list.appendChild(article);
  });

  if (scrollToLatest) {
    requestAnimationFrame(() => {
      if (list.isConnected) list.scrollTop = list.scrollHeight;
    });
  }
}

function renderLoadError(root) {
  const list = root.querySelector('[data-note-list]');
  const count = root.querySelector('[data-note-count]');
  if (!list || !count) return;
  list.replaceChildren();
  count.textContent = '불러오기 실패';
  const message = document.createElement('p');
  message.className = 'assistant-note-empty is-error';
  message.textContent = '댓글을 불러오지 못했습니다.';
  list.appendChild(message);
}

async function mountMemo(root, studentId) {
  if (!(root instanceof Element) || !studentId) return;
  const mountKey = `${studentId}:${Date.now()}:${Math.random()}`;
  root.dataset.mountKey = mountKey;
  const input = root.querySelector('[data-note-input]');
  const saveButton = root.querySelector('[data-note-save]');
  const authorButtons = [...root.querySelectorAll('[data-note-author]')];
  let notes = [];
  let selectedAuthor = '';

  if (!input || !saveButton || authorButtons.length !== AUTHORS.length) return;
  setComposerDisabled(input, saveButton, authorButtons, true);
  const isCurrent = () => root.isConnected && root.dataset.mountKey === mountKey;

  const deleteNote = async (note, deleteButton) => {
    const noteId = Number(note?.id);
    if (!Number.isInteger(noteId) || noteId < 1 || !isCurrent()) return;
    if (!window.confirm('이 댓글을 삭제할까요?\n삭제 후 되돌릴 수 없습니다.')) return;

    deleteButton.disabled = true;
    setStatus(root, '댓글 삭제 중...', 'saving');
    try {
      await sendRequest(`/api/assistant-student-notes/${noteId}`, 'DELETE', {
        student_id: studentId,
      });
      if (!isCurrent()) return;
      notes = notes.filter((item) => Number(item.id) !== noteId);
      renderNotes(root, notes, { onDelete: deleteNote });
      setStatus(root, '댓글이 삭제되었습니다.', 'success');
    } catch (error) {
      if (isCurrent()) {
        deleteButton.disabled = false;
        setStatus(root, '댓글 삭제 실패. 다시 시도해 주세요.', 'error');
      }
    }
  };

  authorButtons.forEach((button) => {
    button.addEventListener('click', () => {
      const author = String(button.dataset.noteAuthor || '');
      if (!AUTHORS.includes(author)) return;
      selectedAuthor = author;
      setSelectedAuthor(root, author);
      setStatus(root, '');
      input.focus();
    });
  });

  saveButton.addEventListener('click', async () => {
    const content = input.value.trim();
    if (!AUTHORS.includes(selectedAuthor)) {
      setStatus(root, '작성자를 선택해 주세요.', 'error');
      authorButtons[0].focus();
      return;
    }
    if (!content) {
      setStatus(root, '댓글 내용을 입력해 주세요.', 'error');
      input.focus();
      return;
    }
    if (content.length > MAX_NOTE_LENGTH) {
      setStatus(root, '댓글은 5,000자까지 등록할 수 있습니다.', 'error');
      input.focus();
      return;
    }

    setComposerDisabled(input, saveButton, authorButtons, true);
    setStatus(root, '댓글 등록 중...', 'saving');
    try {
      const data = await sendRequest('/api/assistant-student-notes', 'POST', {
        student_id: studentId,
        content,
        author: selectedAuthor,
      });
      if (!isCurrent()) return;
      notes = [data.note, ...notes.filter((note) => note.id !== data.note?.id)];
      renderNotes(root, notes, { onDelete: deleteNote });
      input.value = '';
      selectedAuthor = '';
      setSelectedAuthor(root, '');
      setStatus(root, '새 댓글이 등록되었습니다.', 'success');
    } catch (error) {
      if (isCurrent()) setStatus(root, '댓글 등록 실패. 다시 시도해 주세요.', 'error');
    } finally {
      if (isCurrent()) {
        setComposerDisabled(input, saveButton, authorButtons, false);
      }
    }
  });

  input.addEventListener('keydown', (event) => {
    if (event.key !== 'Enter' || (!event.ctrlKey && !event.metaKey)) return;
    event.preventDefault();
    if (!saveButton.disabled) saveButton.click();
  });

  setStatus(root, '불러오는 중...', 'loading');
  try {
    const data = await api.getStrict(
      `/api/assistant-student-notes?student_id=${encodeURIComponent(studentId)}`,
      'assistant notes',
      { cache: 'no-store' },
    );
    if (!isCurrent()) return;
    notes = Array.isArray(data?.notes) ? data.notes : [];
    renderNotes(root, notes, { onDelete: deleteNote });
    input.value = '';
    selectedAuthor = '';
    setSelectedAuthor(root, '');
    setStatus(root, '');
    setComposerDisabled(input, saveButton, authorButtons, false);
  } catch (error) {
    if (!isCurrent()) return;
    renderLoadError(root);
    setStatus(root, '댓글을 불러오지 못했습니다. 새로고침해 주세요.', 'error');
  }
}

export function initAssistantStudentNotes() {
  document.addEventListener('admin:assistant-notes-mount', (event) => {
    const root = event.detail?.root;
    const studentId = String(event.detail?.studentId || '').trim();
    mountMemo(root, studentId);
  });
}
