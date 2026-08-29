const REVISION_HEADER = 'X-School-Calendar-Revision';

export function normalizeSchoolCalendarRevision(value) {
  const revision = String(value || '').trim().replace(/^W\//, '').replace(/^"|"$/g, '').toLowerCase();
  return /^[0-9a-f]{64}$/.test(revision) ? revision : '';
}

export function schoolCalendarRevisionFromResponse(response) {
  return normalizeSchoolCalendarRevision(response?.headers?.get?.(REVISION_HEADER));
}

export function createSchoolCalendarSaveQueue({
  fetchImpl = globalThis.fetch,
  endpoint = '/api/school-calendar',
  initialRevision = '',
  onStart = () => {},
  onSuccess = () => {},
  onConflict = () => {},
  onFailure = () => {},
} = {}) {
  if (typeof fetchImpl !== 'function') throw new TypeError('fetchImpl must be a function');

  let revision = normalizeSchoolCalendarRevision(initialRevision);
  let blocked = false;
  let tail = Promise.resolve();

  async function run(job) {
    if (blocked) {
      return { ok: false, status: 409, blocked: true, revision };
    }

    onStart(job, { revision });
    const headers = { 'Content-Type': 'application/json' };
    if (revision) headers['If-Match'] = revision;

    let response;
    try {
      response = await fetchImpl(endpoint, {
        method: 'POST',
        headers,
        body: job.snapshot,
        keepalive: job.mode === 'flush',
      });
    } catch (error) {
      const result = { ok: false, status: 0, error, revision };
      onFailure(job, result);
      return result;
    }

    const responseRevision = schoolCalendarRevisionFromResponse(response);
    if (responseRevision) revision = responseRevision;

    const result = {
      ok: Boolean(response.ok),
      status: Number(response.status || 0),
      revision,
    };
    if (response.ok) {
      onSuccess(job, result);
      return result;
    }

    if (response.status === 409 || response.status === 428) {
      blocked = true;
      onConflict(job, result);
      return { ...result, blocked: true };
    }

    onFailure(job, result);
    return result;
  }

  function enqueue(job) {
    if (!job || typeof job.snapshot !== 'string') {
      return Promise.resolve({
        ok: false,
        status: 0,
        error: new TypeError('calendar save job requires a snapshot'),
        revision,
      });
    }
    const queuedJob = Object.freeze({
      mode: String(job.mode || 'manual'),
      payload: job.payload,
      snapshot: job.snapshot,
    });
    const pending = tail.then(() => run(queuedJob), () => run(queuedJob));
    tail = pending.then(() => undefined, () => undefined);
    return pending;
  }

  return Object.freeze({
    enqueue,
    getRevision: () => revision,
    isBlocked: () => blocked,
    setRevision(value) {
      revision = normalizeSchoolCalendarRevision(value);
      blocked = false;
    },
    whenIdle: () => tail,
  });
}
