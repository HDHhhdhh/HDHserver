export const ASSISTANT_STUDENT_NOTES_COLLECTION_PATH = '/api/assistant-student-notes';

const AUTHORS = new Set(['귤', '세빈', '동훈', '하영']);
const MAX_CONTENT_LENGTH = 5000;

function response(status, payload, changed = false) {
  return { status, payload, changed };
}

function notesForStore(store) {
  return Array.isArray(store.assistantStudentNotes) ? store.assistantStudentNotes : [];
}

function studentExists(store, studentId) {
  return Array.isArray(store.students)
    && store.students.some(student => String(student?.id || '') === studentId);
}

function nextNoteId(notes) {
  return notes.reduce((max, note) => Math.max(max, Number(note?.id || 0)), 0) + 1;
}

function normalizeDate(value) {
  const date = String(value ?? '').trim();
  if (!date) return '';
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) return null;
  const parsed = new Date(`${date}T00:00:00Z`);
  return Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 10) === date
    ? date
    : null;
}

function validateStudent(store, rawStudentId) {
  const studentId = String(rawStudentId || '').trim();
  if (!studentId) return { error: response(400, { ok: false, error: 'missing student_id' }) };
  if (!studentExists(store, studentId)) {
    return { error: response(404, { ok: false, error: 'student not found' }) };
  }
  return { studentId };
}

function findOwnedNote(notes, noteId, studentId) {
  return notes.find(note => Number(note?.id) === noteId && String(note?.student_id || '') === studentId);
}

function parseItemPath(path) {
  if (!path.startsWith(`${ASSISTANT_STUDENT_NOTES_COLLECTION_PATH}/`)) return null;
  const parts = path.slice(ASSISTANT_STUDENT_NOTES_COLLECTION_PATH.length + 1).split('/');
  const noteId = Number(parts[0]);
  if (!Number.isInteger(noteId) || noteId < 1 || parts.length > 2) return null;
  return { noteId, action: parts[1] || '' };
}

export function isAssistantStudentNotesPath(path) {
  return path === ASSISTANT_STUDENT_NOTES_COLLECTION_PATH
    || path.startsWith(`${ASSISTANT_STUDENT_NOTES_COLLECTION_PATH}/`);
}

export function applyAssistantStudentNotesRequest({
  method,
  path,
  params,
  body = {},
  store,
  createdAt,
}) {
  if (!isAssistantStudentNotesPath(path)) return null;

  const notes = notesForStore(store);
  const rawStudentId = method === 'GET' ? params?.get?.('student_id') : body?.student_id;
  const validated = validateStudent(store, rawStudentId);
  if (validated.error) return validated.error;
  const { studentId } = validated;

  if (method === 'GET' && path === ASSISTANT_STUDENT_NOTES_COLLECTION_PATH) {
    const owned = notes
      .filter(note => String(note?.student_id || '') === studentId)
      .sort((a, b) => String(b?.created_at || '').localeCompare(String(a?.created_at || '')) || Number(b?.id || 0) - Number(a?.id || 0));
    return response(200, { ok: true, notes: owned });
  }

  if (method === 'POST' && path === ASSISTANT_STUDENT_NOTES_COLLECTION_PATH) {
    const content = String(body?.content || '').trim();
    const author = String(body?.author || '').trim();
    const remindOn = normalizeDate(body?.remind_on);
    if (content.length > MAX_CONTENT_LENGTH) return response(400, { ok: false, error: 'content too long' });
    if (!AUTHORS.has(author)) return response(400, { ok: false, error: 'invalid author' });
    if (remindOn === null) return response(400, { ok: false, error: 'remind_on must be an ISO date' });
    const timestamp = createdAt();
    const note = {
      id: nextNoteId(notes),
      student_id: studentId,
      content,
      created_by: author,
      updated_by: author,
      pinned: false,
      remind_on: remindOn,
      completed_at: '',
      created_at: timestamp,
      updated_at: timestamp,
    };
    store.assistantStudentNotes = [note, ...notes];
    return response(201, { ok: true, note }, true);
  }

  const item = parseItemPath(path);
  if (!item) return response(404, { ok: false, error: 'note not found' });
  const note = findOwnedNote(notes, item.noteId, studentId);
  if (!note) return response(404, { ok: false, error: 'note not found' });

  if (method === 'DELETE' && !item.action) {
    store.assistantStudentNotes = notes.filter(candidate => candidate !== note);
    return response(200, { ok: true }, true);
  }

  if (method !== 'PATCH') return response(405, { ok: false, error: 'method not allowed' });

  if (!item.action) {
    const content = String(body?.content || '').trim();
    const author = String(body?.author || '').trim();
    if (content.length > MAX_CONTENT_LENGTH) return response(400, { ok: false, error: 'content too long' });
    if (!AUTHORS.has(author)) return response(400, { ok: false, error: 'invalid author' });
    note.content = content;
    note.updated_by = author;
    note.updated_at = createdAt();
  } else if (item.action === 'pin') {
    if (typeof body?.pinned !== 'boolean') return response(400, { ok: false, error: 'pinned must be a boolean' });
    note.pinned = body.pinned;
  } else if (item.action === 'reminder' || item.action === 'remind') {
    const remindOn = normalizeDate(body?.remind_on);
    if (remindOn === null) return response(400, { ok: false, error: 'remind_on must be an ISO date' });
    note.remind_on = remindOn;
    note.updated_at = createdAt();
  } else if (item.action === 'complete') {
    if (typeof body?.completed !== 'boolean') return response(400, { ok: false, error: 'completed must be a boolean' });
    note.completed_at = body.completed ? createdAt() : '';
    note.updated_at = createdAt();
  } else {
    return response(404, { ok: false, error: 'note not found' });
  }

  return response(200, { ok: true, note }, true);
}
