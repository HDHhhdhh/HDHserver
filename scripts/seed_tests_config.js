const fs = require('fs');
const path = require('path');

const cfgPath = path.resolve(__dirname, '..', 'tests-config.json');

const TARGET_SPECS = {
  '공수1': {
    prefix: 'gongsu1',
    levels: {
      3: [
        '다항식의 연산1',
        '다항식의 연산2',
        '항등식과 나머지정리1',
        '항등식과 나머지정리2',
        '인수분해',
        '복소수1',
        '복소수2',
        '이차방정식1',
        '이차방정식2',
        '이차함수',
        '여러가지 방정식1',
        '여러가지 방정식2',
        '일차부등식',
        '이차부등식1',
        '이차부등식2',
        '순열',
        '조합',
        '행렬',
      ],
      4: [
        '다항식의 연산',
        '항등식과 나머지정리',
        '인수분해',
        '복소수',
        '이차방정식1',
        '이차방정식2',
        '이차함수',
        '여러가지 방정식1',
        '여러가지 방정식2',
        '일차부등식',
        '이차부등식1',
        '이차부등식2',
        '순열1',
        '순열2',
        '조합',
        '행렬',
      ],
      5: [
        '다항식의 연산1',
        '다항식의 연산2',
        '항등식과 나머지정리1',
        '항등식과 나머지정리2',
        '인수분해',
        '복소수',
        '이차방정식1',
        '이차방정식2',
        '이차함수',
        '여러가지 방정식1',
        '여러가지 방정식2',
        '일차부등식',
        '이차부등식1',
        '이차부등식2',
        '순열1',
        '순열2',
        '조합',
        '행렬',
      ],
      6: [
        '다항식의 연산1',
        '다항식의 연산2',
        '항등식과 나머지정리1',
        '항등식과 나머지정리2',
        '인수분해1',
        '인수분해2',
        '복소수1',
        '복소수2',
        '이차방정식1',
        '이차방정식2',
        '이차함수1',
        '이차함수2',
        '여러가지방정식1',
        '여러가지방정식2',
        '부등식1',
        '부등식2',
        '순열1',
        '순열2',
        '조합1',
        '조합2',
        '행렬1',
        '행렬2',
      ],
    },
  },
  '대수': {
    prefix: 'daesu',
    levels: {
      3: [
        '지수1',
        '지수2',
        '로그1',
        '로그2',
        '지수함수1',
        '지수함수2',
        '로그함수1',
        '로그함수2',
        '삼각함수',
        '삼각함수의 그래프1',
        '삼각함수의 그래프2',
        '삼각함수의 활용',
        '등차수열',
        '등비수열',
        '수열의 합',
        '수학적 귀납법',
      ],
      4: [
        '지수',
        '로그',
        '지수함수1',
        '지수함수2',
        '로그함수1',
        '로그함수2',
        '삼각함수',
        '삼각함수의 그래프1',
        '삼각함수의 그래프2',
        '삼각함수의 활용',
        '등차수열',
        '등비수열',
        '수열의 합',
        '수학적 귀납법',
      ],
      5: [
        '지수1',
        '지수2',
        '로그1',
        '로그2',
        '지수함수',
        '지수함수의 활용',
        '로그함수',
        '로그함수의 활용',
        '삼각함수',
        '삼각함수의 그래프1',
        '삼각함수의 그래프2',
        '삼각함수의 활용1',
        '삼각함수의 활용2',
        '등차수열과 등비수열1',
        '등차수열과 등비수열2',
        '수열의 합1',
        '수열의 합2',
        '수학적 귀납법',
      ],
      6: [
        '지수1',
        '지수2',
        '로그',
        '지수함수',
        '로그함수1',
        '로그함수2',
        '삼각함수',
        '삼각함수의 그래프1',
        '삼각함수의 그래프2',
        '삼각함수의 활용1',
        '삼각함수의 활용2',
        '등차수열',
        '등비수열',
        '수열의 합1',
        '수열의 합2',
        '수학적 귀납법',
      ],
    },
  },
};

function readJson(filePath) {
  try {
    return JSON.parse(fs.readFileSync(filePath, 'utf8'));
  } catch (err) {
    return {};
  }
}

function normalizeAnswerKeys(raw) {
  const src = raw && typeof raw === 'object' ? raw : {};
  return {
    '1': Array.isArray(src['1']) ? src['1'] : [],
    '2': Array.isArray(src['2']) ? src['2'] : [],
    '3': Array.isArray(src['3']) ? src['3'] : [],
  };
}

function existingKey(curriculum, name) {
  return curriculum + '||' + name;
}

function makeDefaultTest(prefix, curriculum, level, index, name) {
  return {
    id: 't_unit_' + prefix + '_lv' + level + '_' + String(index + 1).padStart(2, '0'),
    name,
    problems: 20,
    curriculum,
    answerKeys: { '1': [], '2': [], '3': [] },
    answerKey: [],
  };
}

const cfg = readJson(cfgPath);
if (!cfg.categories || typeof cfg.categories !== 'object') cfg.categories = {};
if (!cfg.categories.UNIT || typeof cfg.categories.UNIT !== 'object') cfg.categories.UNIT = { label: '단원평가', tests: [] };
if (!cfg.categories.FINAL || typeof cfg.categories.FINAL !== 'object') cfg.categories.FINAL = { label: 'APEX FINAL', tests: [] };
if (!cfg.categories.HELL || typeof cfg.categories.HELL !== 'object') cfg.categories.HELL = { label: 'APEX HELL', tests: [] };

const currentUnitTests = Array.isArray(cfg.categories.UNIT.tests) ? cfg.categories.UNIT.tests.filter((t) => t && typeof t === 'object') : [];
const targetCurriculums = new Set(Object.keys(TARGET_SPECS));
const keepUnitTests = currentUnitTests.filter((t) => !targetCurriculums.has(String(t.curriculum || '').trim()));
const existingByName = new Map();

for (const test of currentUnitTests) {
  const curriculum = String(test.curriculum || '').trim();
  const name = String(test.name || '').trim();
  if (!targetCurriculums.has(curriculum) || !name) continue;
  const key = existingKey(curriculum, name);
  if (!existingByName.has(key)) existingByName.set(key, test);
}

function buildTests(curriculum, spec) {
  const out = [];
  const levels = spec.levels || {};
  for (const level of Object.keys(levels).map(Number).sort((a, b) => a - b)) {
    const units = Array.isArray(levels[level]) ? levels[level] : [];
    units.forEach((unit, index) => {
      const name = unit + ' Lv.' + level;
      const prev = existingByName.get(existingKey(curriculum, name));
      if (prev) {
        const answerKeys = normalizeAnswerKeys(prev.answerKeys);
        const problems = Number(prev.problems) > 0 ? Number(prev.problems) : 20;
        out.push({
          ...prev,
          name,
          problems,
          curriculum,
          answerKeys,
          answerKey: Array.isArray(prev.answerKey) ? prev.answerKey : answerKeys['1'],
        });
      } else {
        out.push(makeDefaultTest(spec.prefix, curriculum, level, index, name));
      }
    });
  }
  return out;
}

cfg.categories.UNIT.label = String(cfg.categories.UNIT.label || '단원평가');
cfg.categories.UNIT.tests = [
  ...keepUnitTests,
  ...buildTests('공수1', TARGET_SPECS['공수1']),
  ...buildTests('대수', TARGET_SPECS['대수']),
];

fs.writeFileSync(cfgPath, JSON.stringify(cfg, null, 2) + '\n', 'utf8');
console.log(JSON.stringify({
  unitTotal: cfg.categories.UNIT.tests.length,
  gong1: cfg.categories.UNIT.tests.filter((t) => t.curriculum === '공수1').length,
  daesu: cfg.categories.UNIT.tests.filter((t) => t.curriculum === '대수').length,
  gongsu2: cfg.categories.UNIT.tests.filter((t) => t.curriculum === '공수2').length,
  finals: Array.isArray(cfg.categories.FINAL.tests) ? cfg.categories.FINAL.tests.length : 0,
  hell: Array.isArray(cfg.categories.HELL.tests) ? cfg.categories.HELL.tests.length : 0,
}, null, 2));
