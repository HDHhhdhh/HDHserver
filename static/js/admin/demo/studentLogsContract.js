const MAX_SID_LENGTH = 120;
const MAX_NAME_LENGTH = 120;
const MAX_COMMENT_LENGTH = 300;
const ALLOWED_KINDS = new Set(['homework_insufficient']);

function cleanText(value) {
  return String(value || '').trim().replace(/\s+/g, ' ');
}

function validDate(value) {
  const raw = String(value || '').trim();
  const parsed = /^\d{4}-\d{2}-\d{2}$/.test(raw) ? new Date(`${raw}T00:00:00Z`) : null;
  return !!parsed && !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === raw;
}

function result(payload, status = 200, changed = false) {
  return { payload, status, changed };
}

export function applyStudentLogsRequest({ method, path, body = {}, store, createdAt, today }) {
  const basePath = '/api/student-logs';
  const deleteMatch = String(path || '').match(/^\/api\/student-logs\/(\d+)$/);
  if (path !== basePath && !deleteMatch) return null;
  const requestMethod = String(method || 'GET').toUpperCase();
  const rows = Array.isArray(store.studentOperationLogs) ? store.studentOperationLogs : [];

  if (deleteMatch) {
    if (requestMethod !== 'DELETE') return result({ ok: false, error: 'method not allowed' }, 405);
    const id = Number(deleteMatch[1]);
    if (!Number.isInteger(id) || id <= 0) return result({ ok: false, error: 'invalid student log id' }, 400);
    const index = rows.findIndex(row => Number(row?.id) === id);
    if (index < 0) return result({ ok: false, error: 'student log not found' }, 404);
    store.studentOperationLogs = rows.filter(row => Number(row?.id) !== id);
    return result({ ok: true, deleted: 1, id }, 200, true);
  }

  if (requestMethod === 'GET') {
    return result({ ok: true, logs: rows.map(row => ({ ...row })) });
  }
  if (requestMethod === 'DELETE') {
    const deleted = rows.length;
    store.studentOperationLogs = [];
    return result({ ok: true, deleted }, 200, deleted > 0);
  }
  if (requestMethod !== 'POST') {
    return result({ ok: false, error: 'method not allowed' }, 405);
  }

  if (!body || typeof body !== 'object' || Array.isArray(body)) {
    return result({ ok: false, error: 'JSON object is required' }, 400);
  }
  for (const field of ['sid', 'studentName', 'kind', 'comment']) {
    if (typeof body[field] !== 'string') {
      return result({ ok: false, error: `${field} must be text` }, 400);
    }
  }
  if (body.date != null && typeof body.date !== 'string') {
    return result({ ok: false, error: 'date must be text' }, 400);
  }

  const sid = cleanText(body.sid);
  const studentName = cleanText(body.studentName);
  const kind = cleanText(body.kind);
  const comment = cleanText(body.comment);
  const date = cleanText(body.date) || String(today || '').trim();
  if (!sid || sid.length > MAX_SID_LENGTH) return result({ ok: false, error: 'sid is required' }, 400);
  if (!studentName || studentName.length > MAX_NAME_LENGTH) return result({ ok: false, error: 'studentName is required' }, 400);
  if (!ALLOWED_KINDS.has(kind)) return result({ ok: false, error: 'unsupported log kind' }, 400);
  if (!comment) return result({ ok: false, error: 'comment is required' }, 400);
  if (comment.length > MAX_COMMENT_LENGTH) return result({ ok: false, error: 'comment too long' }, 400);
  if (!validDate(date)) return result({ ok: false, error: 'date must be YYYY-MM-DD' }, 400);

  const nextId = rows.reduce((max, row) => Math.max(max, Number(row?.id) || 0), 0) + 1;
  const log = {
    id: nextId,
    sid,
    student_name: studentName,
    kind,
    comment,
    date,
    created_at: typeof createdAt === 'function' ? createdAt() : new Date().toISOString(),
  };
  store.studentOperationLogs = [log, ...rows];
  return result({ ok: true, log: { ...log } }, 201, true);
}

export default applyStudentLogsRequest;
