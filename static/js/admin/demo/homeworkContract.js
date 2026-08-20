const ADMIN_HOMEWORK_PATH = '/api/admin/student-homework';
const ADMIN_HOMEWORK_COMMIT_PATH = `${ADMIN_HOMEWORK_PATH}/commit`;
const HOMEWORK_STATUSES = new Set(['assigned', 'completed', 'cancelled']);

function clone(value) {
  if (typeof structuredClone === 'function') return structuredClone(value);
  return JSON.parse(JSON.stringify(value));
}

function cleanText(value, maxLength = 1000) {
  return String(value ?? '').trim().slice(0, maxLength);
}

function stableValue(value) {
  if (Array.isArray(value)) return value.map(stableValue);
  if (!value || typeof value !== 'object') return value;
  return Object.fromEntries(Object.keys(value).sort().map(key => [key, stableValue(value[key])]));
}

function requestSignature(value) {
  return JSON.stringify(stableValue(value));
}

function normalizeStatus(value) {
  const status = cleanText(value, 20);
  return HOMEWORK_STATUSES.has(status) ? status : 'assigned';
}

export function homeworkLocalDateTimeToKst(value) {
  const raw = cleanText(value, 32);
  if (!raw) return null;
  const match = raw.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/);
  if (!match) throw new Error('숙제 기한 형식이 올바르지 않습니다.');
  const [, year, month, day, hour, minute] = match;
  const dueAt = `${year}-${month}-${day}T${hour}:${minute}:00+09:00`;
  const parsed = Date.parse(dueAt);
  if (!Number.isFinite(parsed)) throw new Error('숙제 기한을 확인해 주세요.');
  const roundTrip = new Date(parsed + (9 * 60 * 60 * 1000)).toISOString().slice(0, 16);
  if (roundTrip !== raw) throw new Error('숙제 기한을 확인해 주세요.');
  return dueAt;
}

export function homeworkDueAtToLocalInput(value) {
  const raw = cleanText(value, 64);
  if (!raw) return '';
  const parsed = Date.parse(raw);
  if (!Number.isFinite(parsed)) return '';
  return new Date(parsed + (9 * 60 * 60 * 1000)).toISOString().slice(0, 16);
}

export function homeworkEffectiveStatus(assignment, now = new Date()) {
  const status = normalizeStatus(assignment?.status);
  if (status !== 'assigned') return status;
  const dueAt = Date.parse(String(assignment?.dueAt || ''));
  const nowMs = now instanceof Date ? now.getTime() : Date.parse(String(now || ''));
  return Number.isFinite(dueAt) && Number.isFinite(nowMs) && dueAt <= nowMs ? 'overdue' : 'assigned';
}

export function mergeHomeworkLogRow(originalRow, managedFields, assignmentId) {
  const original = originalRow && typeof originalRow === 'object' && !Array.isArray(originalRow)
    ? originalRow
    : {};
  const managed = managedFields && typeof managedFields === 'object' && !Array.isArray(managedFields)
    ? managedFields
    : {};
  const next = { ...clone(original), ...clone(managed) };
  delete next._ph;
  delete next._canonical;
  const id = cleanText(assignmentId, 200);
  if (id) next.assignmentId = id;
  else delete next.assignmentId;
  return next;
}

export function setHomeworkElementText(element, value, { asValue = false } = {}) {
  if (!element || typeof element !== 'object') throw new TypeError('homework element is required');
  if (asValue) element.value = String(value ?? '');
  else element.textContent = String(value ?? '');
  return element;
}

export function createHomeworkOperationId() {
  const randomUuid = globalThis?.crypto?.randomUUID;
  if (typeof randomUuid === 'function') return randomUuid.call(globalThis.crypto);
  return `hw-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
}

export function normalizeHomeworkAssignment(row, now = new Date()) {
  const assignment = row && typeof row === 'object' ? row : {};
  const revision = Number(assignment.revision);
  const normalized = {
    id: cleanText(assignment.id || assignment.assignmentId, 200),
    sourceRowId: cleanText(assignment.sourceRowId || assignment.source_row_id, 200),
    title: cleanText(assignment.title, 200),
    book: cleanText(assignment.book, 200),
    scope: cleanText(assignment.scope, 1000),
    dueAt: cleanText(assignment.dueAt, 64) || null,
    status: normalizeStatus(assignment.status),
    revision: Number.isInteger(revision) && revision >= 1 ? revision : null,
  };
  normalized.effectiveStatus = homeworkEffectiveStatus(normalized, now);
  return normalized;
}

function homeworkPathKind(path) {
  const normalized = String(path || '').replace(/\/+$/, '') || '/';
  if (normalized === ADMIN_HOMEWORK_PATH) return { kind: 'collection' };
  if (normalized === ADMIN_HOMEWORK_COMMIT_PATH) return { kind: 'commit' };
  const match = normalized.match(/^\/api\/admin\/student-homework\/([^/]+)$/);
  if (!match) return null;
  try {
    return { kind: 'item', id: decodeURIComponent(match[1]) };
  } catch {
    return null;
  }
}

function ensureDemoHomeworkState(store) {
  if (!Array.isArray(store.homeworkAssignments)) store.homeworkAssignments = [];
  if (!store.homeworkOperations || typeof store.homeworkOperations !== 'object' || Array.isArray(store.homeworkOperations)) {
    store.homeworkOperations = {};
  }
  if (!store.logs || typeof store.logs !== 'object' || Array.isArray(store.logs)) store.logs = {};
}

function paramsValue(params, key) {
  if (params && typeof params.get === 'function') return cleanText(params.get(key), 200);
  return cleanText(params?.[key], 200);
}

function adminProjection(row, now) {
  const normalized = normalizeHomeworkAssignment(row, now);
  return {
    id: normalized.id,
    sourceRowId: normalized.sourceRowId || normalized.id,
    title: normalized.title,
    book: normalized.book,
    scope: normalized.scope,
    dueAt: normalized.dueAt,
    status: normalized.status,
    effectiveStatus: normalized.effectiveStatus,
    revision: normalized.revision,
  };
}

function deterministicDemoAssignmentId(operationId, rowIndex) {
  const safeOperation = cleanText(operationId, 120).replace(/[^A-Za-z0-9_-]/g, '').slice(0, 72) || 'operation';
  return `demo-hw-${safeOperation}-${Number(rowIndex)}`;
}

function applyLogPatch(store, body, preparedRows) {
  const date = cleanText(body?.date, 10);
  const sid = cleanText(body?.sid, 200);
  const logPatch = body?.logPatch && typeof body.logPatch === 'object' ? body.logPatch : {};
  const bySid = store.logs[date] && typeof store.logs[date] === 'object' ? store.logs[date] : (store.logs[date] = {});
  const previous = bySid[sid] && typeof bySid[sid] === 'object' ? bySid[sid] : {};
  const expected = Array.isArray(logPatch.baseHomeworkTableExact) ? logPatch.baseHomeworkTableExact : [];
  const current = Array.isArray(previous.homeworkTable) ? previous.homeworkTable : [];
  if (requestSignature(expected) !== requestSignature(current)) {
    return { conflict: true, entry: clone(previous) };
  }

  const patchEntry = logPatch.entry && typeof logPatch.entry === 'object' ? clone(logPatch.entry) : {};
  if (Array.isArray(patchEntry.homeworkTable)) {
    patchEntry.homeworkTable = patchEntry.homeworkTable.map((row, rowIndex) => {
      const prepared = preparedRows.find(item => item.rowIndex === rowIndex);
      return mergeHomeworkLogRow(row, row, prepared?.id || row?.assignmentId);
    });
  }
  const next = { ...previous, ...patchEntry };
  (Array.isArray(logPatch.clearKeys) ? logPatch.clearKeys : []).forEach(key => delete next[String(key)]);
  bySid[sid] = next;
  return { conflict: false, entry: clone(next) };
}

function commitDemoHomework(store, body, now) {
  const operationId = cleanText(body?.operationId, 200);
  const date = cleanText(body?.date, 10);
  const sid = cleanText(body?.sid, 200);
  const homeworkRows = Array.isArray(body?.homeworkRows) ? body.homeworkRows : [];
  if (!operationId || !/^\d{4}-\d{2}-\d{2}$/.test(date) || !sid || homeworkRows.length > 50) {
    return { status: 400, payload: { ok: false, code: 'invalid_homework_commit', retryable: false }, changed: false };
  }

  const signature = requestSignature(body);
  const previousOperation = store.homeworkOperations[operationId];
  if (previousOperation) {
    if (previousOperation.signature !== signature) {
      return { status: 409, payload: { ok: false, code: 'operation_payload_mismatch', retryable: false, operationId }, changed: false };
    }
    return { status: previousOperation.status, payload: clone(previousOperation.payload), changed: false };
  }

  const preparedRows = homeworkRows.map((row, fallbackIndex) => {
    const rowIndex = Number.isInteger(Number(row?.rowIndex)) ? Number(row.rowIndex) : fallbackIndex;
    const sourceRowId = cleanText(row?.sourceRowId, 200) || cleanText(row?.assignmentId, 200) || `row-${operationId}-${rowIndex}`;
    const existingBySource = store.homeworkAssignments.find(item => (
      String(item.sid) === sid
      && String(item.sourceLogDate) === date
      && String(item.sourceRowId || item.id) === sourceRowId
    ));
    const id = cleanText(row?.assignmentId, 200)
      || cleanText(existingBySource?.id, 200)
      || deterministicDemoAssignmentId(sourceRowId, rowIndex);
    const existing = store.homeworkAssignments.find(item => String(item.id) === id);
    const comparable = {
      title: cleanText(row?.title, 200),
      book: cleanText(row?.book, 200),
      scope: cleanText(row?.scope, 1000),
      dueAt: cleanText(row?.dueAt, 64) || null,
      status: normalizeStatus(row?.status),
    };
    const unchanged = existing && requestSignature(comparable) === requestSignature({
      title: existing.title,
      book: existing.book,
      scope: existing.scope,
      dueAt: existing.dueAt,
      status: existing.status,
    });
    return {
      ...comparable,
      id,
      sid,
      sourceLogDate: date,
      sourceRowId,
      rowIndex,
      revision: unchanged ? Number(existing.revision || 1) : Number(existing?.revision || 0) + 1,
    };
  });

  const logResult = applyLogPatch(store, body, preparedRows);
  if (logResult.conflict) {
    const payload = {
      ok: false,
      code: 'log_semantic_conflict',
      retryable: false,
      operationId,
      entry: logResult.entry,
    };
    store.homeworkOperations[operationId] = { signature, status: 409, payload: clone(payload) };
    return { status: 409, payload, changed: true };
  }

  preparedRows.forEach(prepared => {
    const index = store.homeworkAssignments.findIndex(item => String(item.id) === prepared.id);
    if (index >= 0) store.homeworkAssignments[index] = prepared;
    else store.homeworkAssignments.push(prepared);
  });
  const removed = new Set((Array.isArray(body?.removedAssignmentIds) ? body.removedAssignmentIds : []).map(String));
  store.homeworkAssignments = store.homeworkAssignments.map(item => {
    if (!removed.has(String(item.id)) || item.status === 'cancelled') return item;
    return { ...item, status: 'cancelled', revision: Number(item.revision || 0) + 1 };
  });

  const assignments = preparedRows.map(row => adminProjection(row, now));
  const payload = {
    ok: true,
    state: 'committed',
    operationId,
    reconciliationId: `demo-reconcile-${operationId}`,
    log: { ok: true, sqlite: true, json: true, entry: logResult.entry },
    homework: { ok: true, assignments },
    entry: logResult.entry,
  };
  store.homeworkOperations[operationId] = { signature, status: 200, payload: clone(payload) };
  return { status: 200, payload, changed: true };
}

export function applyDemoHomeworkRequest({ method = 'GET', path = '', params = null, body = {}, store, now = new Date() } = {}) {
  const route = homeworkPathKind(path);
  if (!route) return null;
  ensureDemoHomeworkState(store);
  const verb = String(method || 'GET').toUpperCase();

  if (route.kind === 'collection' && verb === 'GET') {
    const sid = paramsValue(params, 'sid');
    const date = paramsValue(params, 'date');
    const assignments = store.homeworkAssignments
      .filter(item => (
        String(item.sid) === sid
        && String(item.sourceLogDate) === date
        && item.status !== 'cancelled'
      ))
      .sort((a, b) => Number(a.rowIndex || 0) - Number(b.rowIndex || 0))
      .map(item => adminProjection(item, now));
    return { status: 200, payload: { ok: true, assignments, pendingOperation: null }, changed: false };
  }

  if (route.kind === 'commit' && verb === 'POST') return commitDemoHomework(store, body, now);

  if (route.kind === 'item' && verb === 'PATCH') {
    const assignment = store.homeworkAssignments.find(item => String(item.id) === String(route.id));
    if (!assignment) return { status: 404, payload: { ok: false, code: 'homework_not_found' }, changed: false };
    if (Number(body?.expectedRevision) !== Number(assignment.revision)) {
      return { status: 409, payload: { ok: false, code: 'revision_conflict', retryable: false, assignment: adminProjection(assignment, now) }, changed: false };
    }
    const patch = body?.patch && typeof body.patch === 'object' ? body.patch : {};
    ['title', 'book', 'scope'].forEach(key => {
      if (Object.prototype.hasOwnProperty.call(patch, key)) assignment[key] = cleanText(patch[key], key === 'scope' ? 1000 : 200);
    });
    if (Object.prototype.hasOwnProperty.call(patch, 'dueAt')) assignment.dueAt = cleanText(patch.dueAt, 64) || null;
    if (Object.prototype.hasOwnProperty.call(patch, 'status')) assignment.status = normalizeStatus(patch.status);
    assignment.revision = Number(assignment.revision || 0) + 1;
    return { status: 200, payload: { ok: true, assignment: adminProjection(assignment, now) }, changed: true };
  }

  return { status: 405, payload: { ok: false, code: 'method_not_allowed' }, changed: false };
}
