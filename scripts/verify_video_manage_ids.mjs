import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { nextVideoId } from '../static/js/shared/videoIds.js';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const source = fs.readFileSync(path.join(root, 'static/js/video-manage.js'), 'utf8');

assert.equal(nextVideoId([]), 1);
assert.equal(nextVideoId([{ id: 1 }, { id: '2' }, { id: 7 }]), 8);
assert.equal(nextVideoId([{ id: 'demo-v001' }, { id: 'demo-v021' }]), 1);
assert.equal(nextVideoId([{ id: 'demo-v001' }, { id: 3 }, { id: 'NaN' }]), 4);
assert.equal(nextVideoId(null), 1);
assert.match(source, /import\s+\{\s*nextVideoId\s*\}.*shared\/videoIds\.js/);
assert.match(source, /id:\s*nextVideoId\(videos\)/);
assert.doesNotMatch(source, /Math\.max\(\.\.\.videos\.map/);

console.log('video-manage id checks passed: 8');
