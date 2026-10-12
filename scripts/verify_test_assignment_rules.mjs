import assert from 'node:assert/strict';
import fs from 'node:fs';
import crypto from 'node:crypto';

const source = fs.readFileSync('static/js/admin/features/testAssignmentRules.js', 'utf8').replace(/\r\n/g, '\n');
const entry = fs.readFileSync('static/js/admin/features/testModal.js', 'utf8');
const rules = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);

// Reviewed 2026-09-07 ILSAN level contract snapshot. The literal cases below
// independently require 중 → 중상 compatibility while preserving explicit 상.
// Original pre-extraction snapshot: c15415e8192df20506221a1bcbdfac59d783cdff73de93d3f97fc9f329219d76.
const normalizedBody = source.slice(source.indexOf('export const ILSAN_GRAPH_DIFFICULTY'))
  .replace(/^export /gm, '')
  .replace("function collectTestCatalog(cfg, fallbackSubject = '공수1') {", 'function collectCatalog(cfg) {')
  .replace('rawTest.course || fallbackSubject', 'rawTest.course || activeSubject').trim();
assert.equal(crypto.createHash('sha256').update(normalizedBody).digest('hex'),
  '31fc0245dde181645a07a6dc16ecd331bc606730bb5742548dd7a196c8274048',
  'assignment rule bodies match the reviewed ILSAN level contract');
assert.doesNotMatch(source, /\b(?:window|document|localStorage|sessionStorage|fetch)\s*[.(]/);
assert.doesNotMatch(source, /(?:\/api\/|editingSid|editingDate|activeStudent)/);
assert.match(entry, /return collectTestCatalog\(cfg, activeSubject\);/);
assert.doesNotMatch(entry, /function (?:normalizeAssignmentStatus|normalizeSubject|normalizeConfig|nextStatusOf)\(/);

assert.deepEqual(['', 'none', 'assigned', 'interrupted', 'done', 'skip', 'legacy'].map(rules.normalizeAssignmentStatus),
  ['', '', 'assigned', 'interrupted', 'done', 'skip', 'assigned']);
assert.equal(rules.normalizeAssignmentStatus({status:'done', other:7}), 'done');
assert.deepEqual(['', 'assigned', 'interrupted', 'done', 'skip'].map(rules.nextStatusOf),
  ['assigned', 'interrupted', 'done', '', 'assigned']);
assert.deepEqual(['', 'assigned', 'skip'].map(rules.nextExcludedStatusOf), ['skip', 'skip', '']);
assert.deepEqual(['', 'interrupted', 'assigned', 'done', 'skip'].map(s => rules.nextKeyboardStatusOf(s)),
  ['interrupted', 'assigned', 'done', 'skip', '']);
assert.equal(rules.nextKeyboardStatusOf('', -1), 'skip');
assert.equal(rules.testStatusLabel('interrupted'), '배부');
assert.equal(rules.testStatusLabel('assigned', true), '완료');
assert.equal(rules.isExplicitBlankTestStatus({status:'none', explicitBlank:true}), true);
assert.equal(rules.isExplicitBlankTestStatus('none'), false);
assert.equal(rules.isResolvedTestStatus('skip'), true);
assert.equal(rules.isInProgressTestStatus('interrupted'), true);

assert.deepEqual(['공통 수학2', '미적분Ⅱ', '확률과통계'].map(rules.normalizeSubject), ['공수2', '미적분2', '확통']);
assert.equal(rules.normalizeDifficulty('ILSAN_PAST', '삼각함수 그래프 포함'), '그래프 포함');
assert.equal(rules.normalizeDifficulty('ILSAN_PAST', '중'), '중상');
assert.equal(rules.normalizeDifficulty('ILSAN_PAST', '중상'), '중상');
assert.equal(rules.normalizeDifficulty('ILSAN_PAST', '상'), '상');
assert.equal(rules.normalizeDifficulty('ILSAN_PAST', '상', '그래프 포함 일산'), '상');
assert.equal(rules.normalizeDifficulty('UNIT', '', '레벨 5'), 'Lv.5');
assert.equal(rules.normalizeTerm('mid'), '중간고사');
assert.equal(rules.normalizeTerm('unknown'), '기말고사');
assert.equal(rules.normalizeRound('', '12회'), '12');

const catalog = {categories:{UNIT:{tests:[
  {id:'later', name:'나중', curriculum:'대수', difficulty:'Lv.3', round:'2', sortOrder:0},
  {id:'second', name:'둘', curriculum:'대수', difficulty:'Lv.3', round:'1', sortOrder:9},
  {id:'first', name:'하나', difficulty:'Lv.3', round:'1', sortOrder:1, unknown:{keep:7}},
]}, SCHOOL_PAST:{tests:[{id:'school',name:'학교 기말고사 3회',curriculum:'대수',difficulty:'상'}]}}};
const original = JSON.stringify(catalog);
const projected = rules.collectTestCatalog(catalog, '대수');
assert.deepEqual(projected.map(x=>x.id), ['first','second','later','school']);
assert.equal(projected[0]._key, '단원평가 / 대수 / Lv.3 / 1회차 / 하나');
assert.equal(projected[3]._key, '학군지 기출 / 대수 / 상 / 기말고사 / 3회차 / 학교 기말고사 3회');
assert.deepEqual(projected[0].unknown, {keep:7});
assert.equal(projected[0].problems, 20);
assert.equal(JSON.stringify(catalog), original, 'catalog projection does not mutate its input');
assert.equal(rules.collectTestCatalog({categories:{UNIT:{tests:[{name:'fallback'}]}}}, '미적분2')[0].curriculum, '미적분2');

const config = {unknown:9, categories:{UNIT:{label:'기존 이름',tests:[]}},autoAssignRules:{ILSAN_PAST:{대수:{중:['중']}}}};
assert.equal(rules.normalizeConfig(config), config, 'legacy configuration repair deliberately retains identity');
assert.equal(config.unknown, 9);
assert.equal(config.categories.UNIT.label, '기존 이름');
assert.deepEqual(config.autoAssignRules.ILSAN_PAST.대수['그래프 포함'], ['하','중','중상','상']);
assert.deepEqual(config.autoAssignRules.ILSAN_PAST.대수['중상'], ['하','중','중상','상']);
assert.deepEqual(config.autoAssignRules.ILSAN_PAST.대수['상'], ['하','중','중상','상']);
assert.equal('중' in config.autoAssignRules.ILSAN_PAST.대수, false);
console.log('test assignment rules: literal transitions/catalog oracle, reviewed contract hash, input and ownership contracts passed');
