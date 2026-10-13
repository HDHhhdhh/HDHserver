import {
  createSchoolCalendarSaveQueue,
  schoolCalendarRevisionFromResponse,
} from '../shared/schoolCalendarSaveQueue.js';


export function createSchoolCalendarPersistence({
  fetchImpl = globalThis.fetch,
  endpoint = '/api/school-calendar',
  onStart = () => {},
  onSuccess = () => {},
  onConflict = () => {},
  onFailure = () => {},
} = {}) {
  if (typeof fetchImpl !== 'function') throw new TypeError('fetchImpl must be a function');

  const saveQueue = createSchoolCalendarSaveQueue({
    fetchImpl,
    endpoint,
    onStart,
    onSuccess,
    onConflict,
    onFailure,
  });

  async function load() {
    const response = await fetchImpl(endpoint, { cache: 'no-store' });
    if (!response.ok) throw new Error(String(response.status));
    const data = await response.json();
    saveQueue.setRevision(schoolCalendarRevisionFromResponse(response));
    return data && typeof data === 'object' ? data : {};
  }

  return Object.freeze({
    load,
    enqueue: saveQueue.enqueue,
    isBlocked: saveQueue.isBlocked,
    whenIdle: saveQueue.whenIdle,
  });
}
