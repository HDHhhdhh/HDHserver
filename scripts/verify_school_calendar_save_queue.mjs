import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import {
  createSchoolCalendarSaveQueue,
  normalizeSchoolCalendarRevision,
} from '../static/js/shared/schoolCalendarSaveQueue.js';
import { createSchoolCalendarPersistence } from '../static/js/school-calendar/persistence.js';


const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const REVISION_HEADER = 'X-School-Calendar-Revision';
const rev = (character) => character.repeat(64);
const tick = () => new Promise((resolve) => setImmediate(resolve));

function mockResponse(status, revision = '', body = {}) {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: {
      get(name) {
        return String(name).toLowerCase() === REVISION_HEADER.toLowerCase()
          ? revision
          : null;
      },
    },
    async json() {
      return body;
    },
  };
}

function deferredTransport() {
  const calls = [];
  let active = 0;
  let maxActive = 0;

  function fetchImpl(url, options) {
    active += 1;
    maxActive = Math.max(maxActive, active);
    return new Promise((resolve, reject) => {
      calls.push({
        url,
        options,
        resolve(response) {
          active -= 1;
          resolve(response);
        },
        reject(error) {
          active -= 1;
          reject(error);
        },
      });
    });
  }

  return {
    calls,
    fetchImpl,
    get maxActive() {
      return maxActive;
    },
  };
}

async function verifySerializedRevisionChain() {
  const transport = deferredTransport();
  const successes = [];
  const queue = createSchoolCalendarSaveQueue({
    fetchImpl: transport.fetchImpl,
    initialRevision: rev('a'),
    onSuccess(job) {
      successes.push(job.mode);
    },
  });

  const first = queue.enqueue({ mode: 'auto', payload: { value: 1 }, snapshot: '{"value":1}' });
  const second = queue.enqueue({ mode: 'flush', payload: { value: 2 }, snapshot: '{"value":2}' });
  await tick();

  assert.equal(transport.calls.length, 1, 'only the head request may start');
  assert.equal(transport.calls[0].options.headers['If-Match'], rev('a'));
  assert.equal(transport.calls[0].options.keepalive, false);

  transport.calls[0].resolve(mockResponse(200, rev('b')));
  await tick();
  assert.equal(transport.calls.length, 2, 'the next request starts after the first response');
  assert.equal(transport.calls[1].options.headers['If-Match'], rev('b'));
  assert.equal(transport.calls[1].options.keepalive, true);
  assert.equal(transport.maxActive, 1, 'the transport never observes parallel saves');

  transport.calls[1].resolve(mockResponse(200, rev('c')));
  const results = await Promise.all([first, second]);
  assert.deepEqual(results.map((result) => result.ok), [true, true]);
  assert.deepEqual(successes, ['auto', 'flush']);
  assert.equal(queue.getRevision(), rev('c'));
}

async function verifyConflictBlocksFollowers() {
  const transport = deferredTransport();
  const conflicts = [];
  const queue = createSchoolCalendarSaveQueue({
    fetchImpl: transport.fetchImpl,
    initialRevision: rev('d'),
    onConflict(job, result) {
      conflicts.push([job.mode, result.status, result.revision]);
    },
  });

  const stale = queue.enqueue({ mode: 'manual', payload: { value: 1 }, snapshot: '{"value":1}' });
  const follower = queue.enqueue({ mode: 'metadata', payload: { value: 2 }, snapshot: '{"value":2}' });
  await tick();
  transport.calls[0].resolve(mockResponse(409, rev('e')));

  const [staleResult, followerResult] = await Promise.all([stale, follower]);
  assert.equal(staleResult.status, 409);
  assert.equal(staleResult.blocked, true);
  assert.equal(followerResult.blocked, true);
  assert.equal(transport.calls.length, 1, 'queued followers do not write after a conflict');
  assert.deepEqual(conflicts, [['manual', 409, rev('e')]]);
  assert.equal(queue.getRevision(), rev('e'));
  assert.equal(queue.isBlocked(), true);

  queue.setRevision(rev('f'));
  assert.equal(queue.isBlocked(), false, 'an explicit fresh load can unblock the queue');
}

async function verifyOldBackendCompatibilityAndRetry() {
  const calls = [];
  let attempt = 0;
  const failures = [];
  const queue = createSchoolCalendarSaveQueue({
    fetchImpl: async (_url, options) => {
      calls.push(options);
      attempt += 1;
      if (attempt === 1) throw new Error('offline');
      return mockResponse(200);
    },
    onFailure(_job, result) {
      failures.push(result.status);
    },
  });

  const failed = await queue.enqueue({ mode: 'auto', payload: {}, snapshot: '{}' });
  const retried = await queue.enqueue({ mode: 'manual', payload: {}, snapshot: '{}' });
  assert.equal(failed.status, 0);
  assert.equal(retried.ok, true);
  assert.deepEqual(failures, [0]);
  assert.equal('If-Match' in calls[0].headers, false);
  assert.equal('If-Match' in calls[1].headers, false);
  assert.equal(queue.isBlocked(), false, 'ordinary network failure remains retryable');
}

async function verifyRestartTransitionFailsClosed() {
  const conflicts = [];
  const queue = createSchoolCalendarSaveQueue({
    fetchImpl: async () => mockResponse(428, rev('9')),
    onConflict(_job, result) {
      conflicts.push(result.status);
    },
  });
  const result = await queue.enqueue({ mode: 'auto', payload: {}, snapshot: '{}' });
  assert.equal(result.status, 428);
  assert.equal(result.blocked, true);
  assert.equal(queue.getRevision(), rev('9'));
  assert.deepEqual(conflicts, [428]);
}

async function verifyPersistenceLoadSeedsSaveRevision() {
  const calls = [];
  const document = {
    version: 2,
    activeYear: '2028',
    years: { 2028: { activeSemester: '1' } },
  };
  const persistence = createSchoolCalendarPersistence({
    fetchImpl: async (url, options) => {
      calls.push({ url, options });
      if (!options.method) return mockResponse(200, rev('7'), document);
      return mockResponse(200, rev('8'), document);
    },
  });

  const loaded = await persistence.load();
  assert.deepEqual(loaded, document, 'load returns the endpoint document unchanged');
  assert.equal(calls[0].url, '/api/school-calendar');
  assert.deepEqual(calls[0].options, { cache: 'no-store' });

  const snapshot = JSON.stringify(document);
  const saved = await persistence.enqueue({ mode: 'manual', payload: document, snapshot });
  assert.equal(saved.ok, true);
  assert.equal(calls[1].url, '/api/school-calendar');
  assert.equal(calls[1].options.method, 'POST');
  assert.equal(calls[1].options.headers['If-Match'], rev('7'));
  assert.equal(calls[1].options.body, snapshot);
}

function verifyNormalizationAndPageIntegration() {
  assert.equal(normalizeSchoolCalendarRevision(`W/"${rev('a')}"`), rev('a'));
  assert.equal(normalizeSchoolCalendarRevision('not-a-revision'), '');

  const source = fs.readFileSync(path.join(ROOT, 'static/js/school-cal.js'), 'utf8');
  const persistenceSource = fs.readFileSync(
    path.join(ROOT, 'static/js/school-calendar/persistence.js'),
    'utf8',
  );
  assert.match(source, /createSchoolCalendarPersistence/);
  assert.match(source, /calendarPersistence\.load\(\)/);
  assert.match(source, /calendarPersistence\.enqueue\(\{ mode, payload, snapshot \}\)/);
  assert.match(source, /calendarPersistence\.enqueue\(\{ mode: 'metadata', payload, snapshot \}\)/);
  assert.match(source, /const saved = await saveCalendar\('switch'\);[\s\S]*?if \(!saved\)/);
  assert.doesNotMatch(source, /createSchoolCalendarSaveQueue/);
  assert.doesNotMatch(source, /schoolCalendarRevisionFromResponse/);
  assert.doesNotMatch(
    source,
    /fetch\(['"]\/api\/school-calendar/,
    'the page delegates calendar transport to the persistence module',
  );
  assert.match(persistenceSource, /createSchoolCalendarSaveQueue/);
  assert.match(persistenceSource, /schoolCalendarRevisionFromResponse\(response\)/);
}

await verifySerializedRevisionChain();
await verifyConflictBlocksFollowers();
await verifyOldBackendCompatibilityAndRetry();
await verifyRestartTransitionFailsClosed();
await verifyPersistenceLoadSeedsSaveRevision();
verifyNormalizationAndPageIntegration();

console.log(JSON.stringify({
  ok: true,
  independentObservations: [
    'max concurrent transport requests = 1',
    'response revision feeds the next If-Match',
    '409 blocks queued followers',
    'old backend without revision remains temporarily compatible',
    'backend restart transition without a revision fails closed',
    'network failures remain retryable',
    'a no-store GET revision seeds the first persistence-module save',
    'the page owns no direct school-calendar transport',
  ],
}, null, 2));
