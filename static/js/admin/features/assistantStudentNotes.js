import { api } from '../core/api.js';

const MAX_NOTE_LENGTH = 5000;
const NOTE_MODES = ['general', 'reminder'];
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

function setNoteMode(root, mode, remindInput = null) {
  const selectedMode = NOTE_MODES.includes(mode) ? mode : 'general';
  root.dataset.noteMode = selectedMode;
  root.querySelectorAll('[data-note-mode]').forEach((button) => {
    const selected = button.dataset.noteMode === selectedMode;
    button.classList.toggle('is-selected', selected);
    button.setAttribute('aria-selected', selected ? 'true' : 'false');
  });
  const reminderFields = root.querySelector('[data-note-reminder-fields]');
  if (reminderFields) reminderFields.hidden = selectedMode !== 'reminder';
  if (selectedMode === 'reminder' && remindInput && !normalizeRemindOn(remindInput.value)) {
    const defaultDate = normalizeRemindOn(root.dataset.nextReminderDate);
    if (defaultDate) remindInput.value = defaultDate;
  }
}
function setComposerDisabled(input, saveButton, authorButtons, disabled, reminderInput = null, modeButtons = []) {
  input.disabled = disabled;
  saveButton.disabled = disabled;
  authorButtons.forEach((button) => {
    button.disabled = disabled;
  });
  if (reminderInput) reminderInput.disabled = disabled;
  modeButtons.forEach((button) => {
    button.disabled = disabled;
  });
}

function isNotePinned(note) {
  return note?.pinned === true || note?.pinned === 1 || note?.pinned === '1';
}

function normalizeRemindOn(value) {
  const raw = String(value || '').trim();
  return /^\d{4}-\d{2}-\d{2}$/.test(raw) ? raw : '';
}


function localDateKey() {
  const now = new Date();
  const pad = (value) => String(value).padStart(2, '0');
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

function formatReminderDate(value) {
  const raw = normalizeRemindOn(value);
  if (!raw) return '';
  const [year, month, day] = raw.split('-').map(Number);
  const date = new Date(year, month - 1, day);
  if (Number.isNaN(date.getTime())) return raw;
  const weekday = new Intl.DateTimeFormat('ko-KR', { weekday: 'short' }).format(date);
  return `${month}/${day}(${weekday})`;
}

function formatNoteDay(value) {
  const raw = String(value || '').trim();
  const dateOnly = raw.slice(0, 10);
  if (normalizeRemindOn(dateOnly)) return formatReminderDate(dateOnly);

  const date = new Date(raw);
  if (Number.isNaN(date.getTime())) return '';
  const month = date.getMonth() + 1;
  const day = date.getDate();
  const weekday = new Intl.DateTimeFormat('ko-KR', { weekday: 'short' }).format(date);
  return `${month}/${day}(${weekday})`;
}

function getReminderInfo(note, today = localDateKey()) {
  const remindOn = normalizeRemindOn(note?.remind_on);
  if (!remindOn) return null;
  const state = remindOn === today ? 'due' : remindOn > today ? 'upcoming' : 'past';
  const prefix = state === 'due'
    ? '\uD655\uC778 \uD544\uC694'
    : state === 'upcoming'
      ? '\uD655\uC778 \uC608\uC815'
      : '\uC9C0\uB09C \uD655\uC778\uC77C';
  const writtenOn = formatNoteDay(note?.created_at || note?.updated_at);
  const targetDate = formatReminderDate(remindOn);
  return {
    date: remindOn,
    state,
    prefix,
    writtenOn,
    targetDate,
    label: `[${prefix}] ${writtenOn ? `${writtenOn} \u2192 ` : ''}${targetDate}`,
  };
}

function reminderRank(note, today) {
  const info = getReminderInfo(note, today);
  if (!info) return 2;
  if (info.state === 'due') return 0;
  if (info.state === 'upcoming') return 1;
  return 3;
}
function renderNotes(
  root,
  notes,
  {
    scrollToLatest = true,
    scrollTop = null,
    onDelete = null,
    onTogglePin = null,
    onEdit = null,
  } = {},
) {
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

  const today = localDateKey();
  const chronological = notes.slice().reverse();
  const displayNotes = [
    ...chronological.filter((note) => isNotePinned(note)),
    ...chronological.filter((note) => !isNotePinned(note)),
  ].sort((left, right) => {
    const leftReminderRank = reminderRank(left, today);
    const rightReminderRank = reminderRank(right, today);
    const leftDue = leftReminderRank === 0;
    const rightDue = rightReminderRank === 0;
    if (leftDue !== rightDue) return leftDue ? -1 : 1;
    const pinDiff = Number(isNotePinned(right)) - Number(isNotePinned(left));
    if (pinDiff) return pinDiff;
    const reminderDiff = leftReminderRank - rightReminderRank;
    if (reminderDiff) return reminderDiff;
    const leftDate = normalizeRemindOn(left.remind_on);
    const rightDate = normalizeRemindOn(right.remind_on);
    if (leftDate && rightDate && leftDate !== rightDate) return leftDate.localeCompare(rightDate);
    return 0;
  });

  displayNotes.forEach((note) => {
    const reminderInfo = getReminderInfo(note, today);
    const author = String(note.updated_by || note.created_by || '');
    const pinned = isNotePinned(note);
    const article = document.createElement('article');
    article.className = 'assistant-note-item';
    article.dataset.noteId = String(note.id || '');
    article.dataset.notePinned = pinned ? 'true' : 'false';
    article.classList.toggle('is-pinned', pinned);
    article.classList.toggle('has-reminder', Boolean(reminderInfo));
    if (AUTHORS.includes(author)) article.dataset.noteAuthor = author;

    const header = document.createElement('div');
    header.className = 'assistant-note-item-header';

    const authorName = document.createElement('strong');
    authorName.className = 'assistant-note-item-author';
    const authorLabel = AUTHOR_LABELS[author] || author || '이전 메모';
    authorName.textContent = authorLabel;

    const pinButton = document.createElement('button');
    pinButton.type = 'button';
    pinButton.className = 'assistant-note-pin';
    pinButton.dataset.notePin = String(note.id || '');
    pinButton.setAttribute('aria-pressed', pinned ? 'true' : 'false');
    pinButton.setAttribute('aria-label', pinned ? `${authorLabel} 메모 고정 해제` : `${authorLabel} 메모 고정`);
    pinButton.title = pinned ? '메모 고정 해제' : '메모 고정';
    pinButton.innerHTML = `
      <svg class="assistant-note-pin-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
        <path d="M9 3h6v2l-1 1v3.5l4 3.5v1H6v-1l4-3.5V6L9 5V3Z"></path>
        <path d="M12 14v7"></path>
      </svg>`;
    pinButton.addEventListener('click', (event) => {
      event.preventDefault();
      event.stopPropagation();
      onTogglePin?.(note, pinButton);
    });

    const time = document.createElement('time');
    time.className = 'assistant-note-item-time';
    const savedAt = String(note.updated_at || note.created_at || '');
    if (savedAt) time.dateTime = savedAt;
    if (!reminderInfo) {
      time.textContent = formatNoteDay(savedAt) || formatNoteDate(savedAt);
    }

    const deleteButton = document.createElement('button');
    deleteButton.type = 'button';
    deleteButton.className = 'assistant-note-delete';
    deleteButton.dataset.noteDelete = String(note.id || '');
    deleteButton.setAttribute('aria-label', `${authorLabel} 댓글 삭제`);
    deleteButton.title = '댓글 삭제';
    deleteButton.textContent = '삭제';
    deleteButton.addEventListener('click', () => onDelete?.(note, deleteButton));

    const editButton = document.createElement('button');
    editButton.type = 'button';
    editButton.className = 'assistant-note-edit';
    editButton.dataset.noteEdit = String(note.id || '');
    editButton.setAttribute('aria-label', `${authorLabel} \uB313\uAE00 \uC218\uC815`);
    editButton.title = '\uB313\uAE00 \uC218\uC815';
    editButton.textContent = '\uC218\uC815';
    editButton.addEventListener('click', () => onEdit?.(note, editButton));

    const actionGroup = document.createElement('div');
    actionGroup.className = 'assistant-note-action-group';
    if (reminderInfo) actionGroup.append(deleteButton, editButton);
    else actionGroup.append(editButton, deleteButton);

    const meta = document.createElement('div');
    meta.className = 'assistant-note-item-meta';
    meta.append(time, actionGroup);

    const content = document.createElement('p');
    content.className = 'assistant-note-item-content';
    content.textContent = String(note.content || '') || '내용 없는 이전 메모';

    const authorGroup = document.createElement('div');
    authorGroup.className = 'assistant-note-item-author-group';
    authorGroup.append(authorName, pinButton);

    if (reminderInfo) {
      const reminderInfoRow = document.createElement('div');
      reminderInfoRow.className = 'assistant-note-reminder-info';
      reminderInfoRow.dataset.reminderState = reminderInfo.state;

      const reminderBadge = document.createElement('span');
      reminderBadge.className = 'assistant-note-reminder-badge';
      reminderBadge.textContent = `[${reminderInfo.prefix}]`;

      const reminderDates = document.createElement('span');
      reminderDates.className = 'assistant-note-reminder-dates';
      const writtenDate = document.createElement('span');
      writtenDate.textContent = reminderInfo.writtenOn;
      const arrow = document.createElement('span');
      arrow.className = 'assistant-note-reminder-arrow';
      arrow.textContent = '\u2192';
      const targetDate = document.createElement('span');
      targetDate.textContent = reminderInfo.targetDate;
      reminderDates.append(writtenDate, arrow, targetDate);
      reminderInfoRow.append(reminderBadge, reminderDates);

      header.classList.add('is-reminder');
      header.append(reminderInfoRow, actionGroup);
      article.append(header, authorGroup, content);
    } else {
      header.append(authorGroup, meta);
      article.append(header, content);
    }
    list.appendChild(article);
  });

  if (scrollTop !== null && Number.isFinite(Number(scrollTop))) {
    requestAnimationFrame(() => {
      if (list.isConnected) list.scrollTop = Number(scrollTop);
    });
  } else if (scrollToLatest) {
    const hasCurrentOrUpcomingReminder = displayNotes.some((note) => {
      const remindOn = normalizeRemindOn(note.remind_on);
      return remindOn && remindOn >= today;
    });
    requestAnimationFrame(() => {
      if (!list.isConnected) return;
      if (hasCurrentOrUpcomingReminder) {
        list.scrollTop = 0;
      } else {
        list.scrollTop = list.scrollHeight;
      }
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
  const modeButtons = [...root.querySelectorAll('[data-note-mode]')];
  const remindInput = root.querySelector('[data-note-remind-input]');
  let notes = [];
  let selectedAuthor = '';
  let selectedMode = 'general';

  if (!input || !saveButton || authorButtons.length !== AUTHORS.length) return;
  setNoteMode(root, selectedMode, remindInput);
  setComposerDisabled(input, saveButton, authorButtons, true, remindInput, modeButtons);
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
      renderNotes(root, notes, { onDelete: deleteNote, onTogglePin: togglePin, onEdit: editNote });
      setStatus(root, '댓글이 삭제되었습니다.', 'success');
    } catch (error) {
      if (isCurrent()) {
        deleteButton.disabled = false;
        setStatus(root, '댓글 삭제 실패. 다시 시도해 주세요.', 'error');
      }
    }
  };

  const togglePin = async (note, pinButton) => {
    const noteId = Number(note?.id);
    if (!Number.isInteger(noteId) || noteId < 1 || !isCurrent()) return;

    const nextPinned = !isNotePinned(note);
    const list = root.querySelector('[data-note-list]');
    const previousScrollTop = list?.scrollTop || 0;
    pinButton.disabled = true;
    setStatus(root, nextPinned ? '메모를 고정하는 중...' : '메모 고정을 해제하는 중...', 'saving');
    try {
      const data = await sendRequest(`/api/assistant-student-notes/${noteId}/pin`, 'PATCH', {
        student_id: studentId,
        pinned: nextPinned,
      });
      if (!isCurrent()) return;
      notes = notes.map((item) => Number(item.id) === noteId ? data.note : item);
      renderNotes(root, notes, {
        scrollToLatest: false,
        scrollTop: nextPinned ? 0 : previousScrollTop,
        onDelete: deleteNote,
        onTogglePin: togglePin,
        onEdit: editNote,
      });
      setStatus(root, nextPinned ? '메모를 고정했습니다.' : '메모 고정을 해제했습니다.', 'success');
    } catch (error) {
      if (isCurrent()) {
        pinButton.disabled = false;
        setStatus(root, '메모 고정 변경 실패. 다시 시도해 주세요.', 'error');
      }
    }
  };

  const editNote = async (note, editButton) => {
    const noteId = Number(note?.id);
    if (!Number.isInteger(noteId) || noteId < 1 || !isCurrent()) return;

    const article = editButton?.closest?.('.assistant-note-item');
    const content = article?.querySelector('.assistant-note-item-content');
    if (!article || !content || article.querySelector('.assistant-note-edit-input')) return;

    const editor = document.createElement('textarea');
    editor.className = 'assistant-note-edit-input';
    editor.rows = 3;
    editor.maxLength = MAX_NOTE_LENGTH;
    editor.value = String(note.content || '');
    editor.setAttribute('aria-label', '\uBA54\uBAA8 \uC218\uC815');

    const editActions = document.createElement('div');
    editActions.className = 'assistant-note-edit-actions';
    const cancelButton = document.createElement('button');
    cancelButton.type = 'button';
    cancelButton.className = 'assistant-note-edit-cancel';
    cancelButton.textContent = '\uCDE8\uC18C';
    const saveEditButton = document.createElement('button');
    saveEditButton.type = 'button';
    saveEditButton.className = 'assistant-note-edit-save';
    saveEditButton.textContent = '\uC800\uC7A5';
    editActions.append(cancelButton, saveEditButton);

    content.replaceWith(editor);
    editor.after(editActions);
    editButton.disabled = true;
    editor.focus();

    const closeEditor = () => {
      if (!editor.isConnected) return;
      editor.replaceWith(content);
      editActions.remove();
      editButton.disabled = false;
    };
    cancelButton.addEventListener('click', () => {
      closeEditor();
      setStatus(root, '');
    });
    saveEditButton.addEventListener('click', async () => {
      const nextContent = editor.value.trim();
      if (!nextContent) {
        setStatus(root, '\uBA54\uBAA8 \uB0B4\uC6A9\uC744 \uC785\uB825\uD574 \uC8FC\uC138\uC694.', 'error');
        editor.focus();
        return;
      }
      if (nextContent.length > MAX_NOTE_LENGTH) {
        setStatus(root, `\uBA54\uBAA8\uB294 ${MAX_NOTE_LENGTH.toLocaleString()}\uC790\uAE4C\uC9C0 \uC800\uC7A5\uD560 \uC218 \uC788\uC2B5\uB2C8\uB2E4.`, 'error');
        editor.focus();
        return;
      }

      const author = [note.updated_by, note.created_by, selectedAuthor]
        .map((value) => String(value || '').trim())
        .find((value) => AUTHORS.includes(value));
      if (!author) {
        setStatus(root, '\uC791\uC131\uC790\uB97C \uC120\uD0DD\uD574 \uC8FC\uC138\uC694.', 'error');
        return;
      }

      const list = root.querySelector('[data-note-list]');
      const previousScrollTop = list?.scrollTop || 0;
      saveEditButton.disabled = true;
      cancelButton.disabled = true;
      setStatus(root, '\uBA54\uBAA8\uB97C \uC218\uC815\uD558\uB294 \uC911...', 'saving');
      try {
        const data = await sendRequest(`/api/assistant-student-notes/${noteId}`, 'PATCH', {
          student_id: studentId,
          content: nextContent,
          author,
        });
        if (!isCurrent()) return;
        notes = notes.map((item) => Number(item.id) === noteId ? data.note : item);
        renderNotes(root, notes, {
          scrollToLatest: false,
          scrollTop: previousScrollTop,
          onDelete: deleteNote,
          onTogglePin: togglePin,
          onEdit: editNote,
        });
        setStatus(root, '\uBA54\uBAA8\uB97C \uC218\uC815\uD588\uC2B5\uB2C8\uB2E4.', 'success');
      } catch (error) {
        if (isCurrent()) {
          saveEditButton.disabled = false;
          cancelButton.disabled = false;
          setStatus(root, '\uBA54\uBAA8 \uC218\uC815\uC5D0 \uC2E4\uD328\ud588\uc2b5\ub2C8\ub2E4.', 'error');
        }
      }
    });
  };

  modeButtons.forEach((button) => {
    button.addEventListener('click', () => {
      const mode = String(button.dataset.noteMode || '');
      if (!NOTE_MODES.includes(mode)) return;
      selectedMode = mode;
      setNoteMode(root, selectedMode, remindInput);
      setStatus(root, '');
      if (selectedMode === 'reminder') remindInput?.focus();
      else input.focus();
    });
  });
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

    const remindOn = selectedMode === 'reminder'
      ? normalizeRemindOn(remindInput?.value)
      : '';
    if (selectedMode === 'reminder' && !remindOn) {
      setStatus(root, '\uD655\uC778\uC77C\uC744 \uC120\uD0DD\uD574 \uC8FC\uC138\uC694.', 'error');
      setNoteMode(root, selectedMode, remindInput);
      remindInput?.focus();
      return;
    }

    setComposerDisabled(input, saveButton, authorButtons, true, remindInput, modeButtons);
    setStatus(root, '댓글 등록 중...', 'saving');
    try {
      const data = await sendRequest('/api/assistant-student-notes', 'POST', {
        student_id: studentId,
        content,
        author: selectedAuthor,
        remind_on: remindOn,
      });
      if (!isCurrent()) return;
      notes = [data.note, ...notes.filter((note) => note.id !== data.note?.id)];
      renderNotes(root, notes, { onDelete: deleteNote, onTogglePin: togglePin, onEdit: editNote });
      input.value = '';
      if (remindInput) remindInput.value = '';
      setNoteMode(root, selectedMode, remindInput);
      selectedAuthor = '';
      setSelectedAuthor(root, '');
      setStatus(root, '새 댓글이 등록되었습니다.', 'success');
    } catch (error) {
      if (isCurrent()) setStatus(root, '댓글 등록 실패. 다시 시도해 주세요.', 'error');
    } finally {
      if (isCurrent()) {
        setComposerDisabled(input, saveButton, authorButtons, false, remindInput, modeButtons);
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
    renderNotes(root, notes, { onDelete: deleteNote, onTogglePin: togglePin, onEdit: editNote });
    input.value = '';
    selectedAuthor = '';
    setSelectedAuthor(root, '');
    setStatus(root, '');
    setComposerDisabled(input, saveButton, authorButtons, false, remindInput, modeButtons);
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
