import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import fs from 'node:fs';
import vm from 'node:vm';

const moduleSource = fs.readFileSync('static/js/student/reviewPlaylist.js', 'utf8');
const studentSource = fs.readFileSync('static/js/student.js', 'utf8');
const htmlSource = fs.readFileSync('static/student.html', 'utf8');
const context = { window: {} };
vm.runInNewContext(moduleSource, context, { filename: 'static/js/student/reviewPlaylist.js' });

const api = context.window.StudentReviewPlaylist;
assert.ok(api && typeof api.createController === 'function', 'review playlist module contract was not published');
assert.deepEqual(
  Array.from(api.normalizeMids([null, ' first ', 'first', 0, '', 'second'])),
  ['first', '0', 'second'],
  'MID normalization must trim, dedupe, and preserve first-seen order',
);
assert.equal(
  api.storageKey('7', '2026-08-03'),
  'student:review-playlist:7:2026-08-03',
  'the existing SID/date-scoped key must remain stable',
);

class MemoryStorage {
  constructor(initial = {}) {
    this.values = new Map(Object.entries(initial));
    this.writes = [];
  }

  getItem(key) {
    return this.values.has(String(key)) ? this.values.get(String(key)) : null;
  }

  setItem(key, value) {
    const normalizedKey = String(key);
    const normalizedValue = String(value);
    this.values.set(normalizedKey, normalizedValue);
    this.writes.push([normalizedKey, normalizedValue]);
  }
}

function sha256(value) {
  return crypto.createHash('sha256').update(JSON.stringify(value)).digest('hex');
}

let sid = '7';
let date = '2026-08-03';
const firstKey = 'student:review-playlist:7:2026-08-03';
const fixtureInput = {
  authorized: ['first', 'second', 'third', 'fresh', 'fresh'],
  stored: ['stale', 'fresh', 'fresh', ' second '],
};
const inputHashBefore = sha256(fixtureInput);
const storage = new MemoryStorage({ [firstKey]: JSON.stringify(fixtureInput.stored) });
const controller = api.createController({
  storage,
  getSid: () => sid,
  getDate: () => date,
});

assert.equal(controller.currentStorageKey(), firstKey);
assert.deepEqual(
  Array.from(controller.hydrate(fixtureInput.authorized)),
  ['fresh', 'second'],
  'fresh bootstrap membership must prune stale storage while preserving stored order',
);
assert.deepEqual(
  storage.writes,
  [[firstKey, '["fresh","second"]']],
  'stale storage must be repaired only in the local SID/date key',
);
assert.equal(controller.setSelected('second', true), false, 'registered MIDs cannot enter pending selection');
assert.equal(controller.setSelected('rogue', true), false, 'unauthorized MIDs cannot enter pending selection');
assert.equal(controller.setSelected('third', true), true);
assert.equal(controller.setSelected('first', true), true);
assert.deepEqual(Array.from(controller.selectedMids()), ['third', 'first'], 'checkbox insertion order must be retained');
assert.deepEqual(Array.from(controller.registerSelected()), ['third', 'first']);
assert.deepEqual(
  Array.from(controller.registeredMids()),
  ['fresh', 'second', 'third', 'first'],
  'new review videos must append after stored registrations in selection order',
);
const writesAfterRegistration = storage.writes.length;
assert.deepEqual(Array.from(controller.registerSelected()), [], 'repeated registration must be idempotent');
assert.equal(storage.writes.length, writesAfterRegistration, 'idempotent registration must not rewrite storage');

assert.equal(controller.unregister('missing'), false);
assert.equal(controller.unregister('second'), true);
assert.deepEqual(Array.from(controller.registeredMids()), ['fresh', 'third', 'first']);
assert.equal(controller.setSelected('second', true), true, 'cancelled MIDs must be selectable again');
assert.deepEqual(Array.from(controller.registerSelected()), ['second']);
assert.deepEqual(Array.from(controller.registeredMids()), ['fresh', 'third', 'first', 'second']);
assert.equal(sha256(fixtureInput), inputHashBefore, 'controller must not mutate bootstrap/storage fixture inputs');

sid = '8';
date = '2026-08-04';
const secondKey = 'student:review-playlist:8:2026-08-04';
storage.values.set(secondKey, '["third","rogue"]');
controller.setSelected('first', true);
assert.deepEqual(
  Array.from(controller.hydrate(fixtureInput.authorized)),
  ['third'],
  'a new SID/date must hydrate only its own local playlist',
);
assert.deepEqual(Array.from(controller.selectedMids()), [], 'hydration must clear chooser-only pending state');
assert.equal(storage.values.get(firstKey), '["fresh","third","first","second"]');
assert.equal(storage.values.get(secondKey), '["third"]');

const brokenStorage = {
  getItem() { throw new Error('read blocked'); },
  setItem() { throw new Error('write blocked'); },
};
const fallback = api.createController({
  storage: brokenStorage,
  getSid: () => 'blocked',
  getDate: () => '2026-08-05',
});
assert.deepEqual(Array.from(fallback.hydrate(['allowed'])), []);
assert.equal(fallback.setSelected('allowed', true), true);
assert.deepEqual(Array.from(fallback.registerSelected()), ['allowed']);
assert.deepEqual(
  Array.from(fallback.registeredMids()),
  ['allowed'],
  'storage failure must not disable the in-memory local chooser',
);

for (const forbidden of ['document', 'fetch(', 'localStorage', '/api/']) {
  assert.equal(moduleSource.includes(forbidden), false, `review playlist module leaked an ambient dependency: ${forbidden}`);
}
for (const retired of [
  'const reviewSelection = new Set()',
  'let registeredReviewMids',
  'student:review-playlist',
  'function saveRegisteredReviewMids',
]) {
  assert.equal(studentSource.includes(retired), false, `student entrypoint still owns review state primitive: ${retired}`);
}
assert.ok(
  studentSource.includes('window.StudentReviewPlaylist.createController({'),
  'student entrypoint must compose the injected review playlist controller',
);

const playbackScript = '/js/student/playback.js?v=20261002-native-watch1';
const reviewPlaylistScript = '/js/student/reviewPlaylist.js?v=20260828-review-playlist-r1';
const announcementStateScript = '/js/student/announcementState.js?v=20260828-announcement-state-r1';
const testPresentationScript = '/js/student/testPresentation.js?v=20260907-ilsan-level-r1';
const studentScript = '/js/student.js?v=20260907-ilsan-level-r1';
assert.equal((htmlSource.match(/\/js\/student\/reviewPlaylist\.js/g) || []).length, 1);
assert.ok(htmlSource.indexOf(playbackScript) < htmlSource.indexOf(reviewPlaylistScript));
assert.ok(htmlSource.indexOf(reviewPlaylistScript) < htmlSource.indexOf(announcementStateScript));
assert.ok(htmlSource.indexOf(announcementStateScript) < htmlSource.indexOf(testPresentationScript));
assert.ok(htmlSource.indexOf(testPresentationScript) < htmlSource.indexOf(studentScript));

console.log('student review playlist checks passed: key scope, fresh prune, order, idempotence, cancellation, isolation, and shell order');
