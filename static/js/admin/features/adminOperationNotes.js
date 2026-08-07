import { ensureOk, fetchJsonChecked, sendJson } from '../../shared/api.js';


const API_URL = '/api/admin-operation-notes';

const noteState = {
  notes: [],
  loading: true,
  saving: false,
};


function setStatus(root, message, state = '') {
  const status = root.querySelector('#adminOperationNoteStatus');
  if (!status) return;
  status.textContent = message;
  status.dataset.state = state;
}


function syncFormState(root) {
  const input = root.querySelector('#adminOperationNoteInput');
  const submit = root.querySelector('#adminOperationNoteSubmit');
  if (!input || !submit) return;
  submit.disabled = noteState.loading || noteState.saving || !input.value.trim();
  input.disabled = noteState.loading || noteState.saving;
}


function renderNotes(root) {
  const list = root.querySelector('#adminOperationNoteList');
  if (!list) return;
  list.replaceChildren();

  if (!noteState.notes.length) {
    const empty = document.createElement('li');
    empty.className = 'admin-operation-note-empty';
    empty.textContent = '등록된 메모가 없습니다.';
    list.appendChild(empty);
    return;
  }

  noteState.notes.forEach(note => {
    const item = document.createElement('li');
    item.className = 'admin-operation-note-item';

    const row = document.createElement('div');
    row.className = 'admin-operation-note-row';

    const content = document.createElement('span');
    content.className = 'admin-operation-note-content';
    content.textContent = String(note?.content || '');

    const remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'admin-operation-note-remove';
    remove.dataset.operationNoteRemove = String(note?.id || '');
    remove.setAttribute('aria-label', '관리자 메모 제거');
    remove.textContent = '제거';

    row.append(content, remove);
    item.appendChild(row);
    list.appendChild(item);
  });
}


async function loadNotes(root) {
  noteState.loading = true;
  syncFormState(root);
  root.setAttribute('aria-busy', 'true');
  setStatus(root, '메모를 불러오는 중입니다.');
  try {
    const payload = await fetchJsonChecked(API_URL, 'operation note list', {
      cache: 'no-store',
      credentials: 'same-origin',
    });
    noteState.notes = Array.isArray(payload?.notes) ? payload.notes : [];
    renderNotes(root);
    setStatus(root, '');
  } catch (error) {
    console.error('[admin operation notes] load failed', error);
    noteState.notes = [];
    renderNotes(root);
    setStatus(root, '메모를 불러오지 못했습니다.', 'error');
  } finally {
    noteState.loading = false;
    syncFormState(root);
    root.removeAttribute('aria-busy');
  }
}


async function createNote(root) {
  const input = root.querySelector('#adminOperationNoteInput');
  if (!input || noteState.saving) return;
  const content = input.value.trim();
  if (!content) return;

  noteState.saving = true;
  syncFormState(root);
  setStatus(root, '메모를 등록하는 중입니다.');
  try {
    const response = await sendJson(API_URL, { content }, {
      cache: 'no-store',
      credentials: 'same-origin',
    });
    await ensureOk(response, 'operation note create');
    const payload = await response.json();
    if (!payload?.note) throw new Error('created operation note is missing');
    noteState.notes = [
      payload.note,
      ...noteState.notes.filter(note => Number(note?.id) !== Number(payload.note.id)),
    ];
    input.value = '';
    renderNotes(root);
    setStatus(root, '메모를 등록했습니다.', 'success');
  } catch (error) {
    console.error('[admin operation notes] create failed', error);
    setStatus(root, '메모를 등록하지 못했습니다.', 'error');
  } finally {
    noteState.saving = false;
    syncFormState(root);
    input.focus();
  }
}


async function deleteNote(root, button) {
  const noteId = Number(button.dataset.operationNoteRemove || 0);
  if (!Number.isInteger(noteId) || noteId <= 0) return;

  button.disabled = true;
  setStatus(root, '메모를 제거하는 중입니다.');
  try {
    const response = await fetch(`${API_URL}/${noteId}`, {
      method: 'DELETE',
      cache: 'no-store',
      credentials: 'same-origin',
    });
    await ensureOk(response, 'operation note delete');
    noteState.notes = noteState.notes.filter(note => Number(note?.id) !== noteId);
    renderNotes(root);
    setStatus(root, '메모를 제거했습니다.', 'success');
  } catch (error) {
    console.error('[admin operation notes] delete failed', error);
    button.disabled = false;
    setStatus(root, '메모를 제거하지 못했습니다.', 'error');
  }
}


export function initAdminOperationNotes() {
  const root = document.getElementById('adminOperationNotes');
  if (!root || root.dataset.operationNotesReady === '1') return;
  const form = root.querySelector('#adminOperationNoteForm');
  const input = root.querySelector('#adminOperationNoteInput');
  const list = root.querySelector('#adminOperationNoteList');
  if (!form || !input || !list) return;

  root.dataset.operationNotesReady = '1';
  form.addEventListener('submit', event => {
    event.preventDefault();
    void createNote(root);
  });
  input.addEventListener('input', () => syncFormState(root));
  list.addEventListener('click', event => {
    const button = event.target?.closest?.('[data-operation-note-remove]');
    if (!button || !list.contains(button)) return;
    void deleteNote(root, button);
  });

  syncFormState(root);
  void loadNotes(root);
}
