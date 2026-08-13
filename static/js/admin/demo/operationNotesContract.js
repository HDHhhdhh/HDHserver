export const OPERATION_NOTES_COLLECTION_PATH = '/api/admin-operation-notes';


export function isOperationNotesPath(path) {
  return path === OPERATION_NOTES_COLLECTION_PATH
    || path.startsWith(`${OPERATION_NOTES_COLLECTION_PATH}/`);
}


function nextNoteId(notes) {
  return notes.reduce((max, note) => Math.max(max, Number(note?.id || 0)), 0) + 1;
}


function response(status, payload, changed = false) {
  return { status, payload, changed };
}


export function applyOperationNotesRequest({ method, path, body = {}, store, createdAt }) {
  if (!isOperationNotesPath(path)) return null;

  const notes = Array.isArray(store.operationNotes) ? store.operationNotes : [];

  if (method === 'GET' && path === OPERATION_NOTES_COLLECTION_PATH) {
    return response(200, { ok: true, notes });
  }

  if (method === 'POST' && path === OPERATION_NOTES_COLLECTION_PATH) {
    if (typeof body?.content !== 'string') {
      return response(400, { ok: false, error: 'content must be text' });
    }
    const content = body.content.trim().replace(/\s+/g, ' ');
    if (!content) return response(400, { ok: false, error: 'content is required' });
    if (content.length > 300) return response(400, { ok: false, error: 'content too long' });

    const note = {
      id: nextNoteId(notes),
      content,
      created_at: createdAt(),
    };
    store.operationNotes = [note, ...notes];
    return response(201, { ok: true, note }, true);
  }

  if (method === 'DELETE' && path.startsWith(`${OPERATION_NOTES_COLLECTION_PATH}/`)) {
    const id = Number(path.slice(OPERATION_NOTES_COLLECTION_PATH.length + 1));
    if (!Number.isInteger(id) || id <= 0) {
      return response(404, { ok: false, error: 'note not found' });
    }
    const remaining = notes.filter(note => Number(note?.id) !== id);
    if (remaining.length === notes.length) {
      return response(404, { ok: false, error: 'note not found' });
    }
    store.operationNotes = remaining;
    return response(200, { ok: true, deleted: true, id }, true);
  }

  return response(405, { ok: false, error: 'method not allowed' });
}
