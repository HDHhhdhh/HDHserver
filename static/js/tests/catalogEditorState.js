export const ANSWER_MODE_OPTIONS = [
  { value: '', label: '미확인' },
  { value: 'choice_number', label: '객관식 번호' },
  { value: 'answer_value', label: '단답형 값' },
  { value: 'manual_review', label: '수동 검토' },
];

const VALID_ANSWER_MODES = new Set(
  ANSWER_MODE_OPTIONS.map(option => option.value).filter(Boolean),
);

const HEADER_ALIASES = Object.freeze({
  id: 'id',
  testid: 'id',
  테스트id: 'id',
  분류: 'category',
  구분: 'category',
  category: 'category',
  type: 'category',
  과목: 'subject',
  subject: 'subject',
  curriculum: 'subject',
  course: 'subject',
  난이도: 'difficulty',
  레벨: 'difficulty',
  difficulty: 'difficulty',
  level: 'difficulty',
  고사: 'term',
  시험기간: 'term',
  학기고사: 'term',
  term: 'term',
  examterm: 'term',
  examperiod: 'term',
  exam_period: 'term',
  period: 'term',
  회차: 'round',
  round: 'round',
  session: 'round',
  no: 'round',
  시험명: 'name',
  테스트명: 'name',
  name: 'name',
  title: 'name',
  순번: 'sourceOrder',
  정렬순서: 'sourceOrder',
  sourceorder: 'sourceOrder',
  source_order: 'sourceOrder',
  sortorder: 'sourceOrder',
  sort_order: 'sourceOrder',
  sourceid: 'sourceId',
  source_id: 'sourceId',
  문항수: 'problems',
  문제수: 'problems',
  problems: 'problems',
  '1회차정답': 'answers1',
  '1회정답': 'answers1',
  answer1: 'answers1',
  answers1: 'answers1',
  '2회차정답': 'answers2',
  '2회정답': 'answers2',
  answer2: 'answers2',
  answers2: 'answers2',
  '3회차정답': 'answers3',
  '3회정답': 'answers3',
  answer3: 'answers3',
  answers3: 'answers3',
  유형: 'modes',
  문항유형: 'modes',
  답안유형: 'modes',
  modes: 'modes',
  answermodes: 'modes',
  answer_modes: 'modes',
  '1회차유형': 'modes1',
  '1회유형': 'modes1',
  modes1: 'modes1',
  answermodes1: 'modes1',
  '2회차유형': 'modes2',
  '2회유형': 'modes2',
  modes2: 'modes2',
  answermodes2: 'modes2',
  '3회차유형': 'modes3',
  '3회유형': 'modes3',
  modes3: 'modes3',
  answermodes3: 'modes3',
  modesjson: 'modesJson',
  modes_json: 'modesJson',
  answermodesjson: 'modesJson',
  answer_modes_json: 'modesJson',
  정답: 'answers',
  answers: 'answers',
  answer: 'answers',
  answersjson: 'answersJson',
  answers_json: 'answersJson',
  answerkeyjson: 'answersJson',
  answer_key_json: 'answersJson',
});

export function parseAnswerSpec(text, problems) {
  if (Array.isArray(text)) return text.slice(0, problems);
  const value = String(text ?? '').trim();
  if (!value) return new Array(problems).fill('');
  let answers;
  if (value.startsWith('[')) {
    let parsed;
    try {
      parsed = JSON.parse(value);
    } catch (error) {
      throw new Error('정답 JSON 배열 형식이 올바르지 않습니다', { cause: error });
    }
    if (!Array.isArray(parsed) || parsed.some(item => item === null || (typeof item !== 'string' && typeof item !== 'number'))) {
      throw new Error('정답 JSON 배열은 문자열 또는 숫자 토큰만 포함해야 합니다');
    }
    answers = parsed.map(item => String(item));
  } else if (/[\s,]/.test(value)) {
    answers = value.split(/[\s,]+/).map(item => item.trim()).filter(Boolean);
  } else {
    answers = [value];
  }
  if (answers.length > problems) answers = answers.slice(0, problems);
  if (answers.length < problems) {
    answers = answers.concat(new Array(problems - answers.length).fill(''));
  }
  return answers;
}

export function parseAnswerSpec3(text, problems) {
  const lines = String(text ?? '').replace(/\r\n/g, '\n').split('\n').slice(0, 3);
  if (lines.length <= 1) {
    const base = parseAnswerSpec(lines[0] || '', problems);
    return { '1': base, '2': base.slice(), '3': base.slice() };
  }
  const one = parseAnswerSpec(lines[0] || '', problems);
  return {
    '1': one,
    '2': parseAnswerSpec(lines[1] || '', problems),
    '3': parseAnswerSpec(lines[2] || '', problems),
  };
}

export function answerKeyForTest(test) {
  const problems = Number(test?.problems || 0) || 0;
  const round = String(test?.round || '1').trim() || '1';
  if (test?.answerKeys && typeof test.answerKeys === 'object') {
    const exact = Array.isArray(test.answerKeys[round]) ? test.answerKeys[round] : null;
    if (exact) return parseAnswerSpec(exact, problems);
    const firstKey = Object.keys(test.answerKeys).find(key => Array.isArray(test.answerKeys[key]));
    if (firstKey) return parseAnswerSpec(test.answerKeys[firstKey], problems);
  }
  if (test?.answerKey != null) return parseAnswerSpec(test.answerKey, problems);
  return new Array(problems).fill('');
}

export function answerKeysToText(test) {
  const answers = answerKeyForTest(test);
  return answers.some(answer => /[\s,]/.test(String(answer || '')))
    ? JSON.stringify(answers)
    : answers.join(' ');
}

export function normalizeAnswerMode(value) {
  const mode = String(value || '').trim();
  return VALID_ANSWER_MODES.has(mode) ? mode : '';
}

export function answerModesForTest(test, problems, roundValue) {
  const total = Math.max(0, Number(problems ?? test?.problems ?? 0) || 0);
  const round = String(roundValue ?? test?.round ?? '1').trim() || '1';
  let raw = test?.answerModes ?? test?.answer_modes;
  if (raw && !Array.isArray(raw) && typeof raw === 'object') raw = raw[round];
  const modes = Array.isArray(raw) ? raw.slice(0, total).map(normalizeAnswerMode) : [];
  while (modes.length < total) modes.push('');
  return modes;
}

export function answerModeConsistencyIssue(answers, modes) {
  const total = Math.max(answers.length, modes.length);
  for (let index = 0; index < total; index += 1) {
    const answer = String(answers[index] || '').trim();
    const mode = normalizeAnswerMode(modes[index]);
    const questionNo = index + 1;
    if (!mode) return `${questionNo}번 문항 유형을 확인해주세요`;
    if (mode === 'choice_number' && !['1', '2', '3', '4', '5'].includes(answer)) {
      return `${questionNo}번 객관식 정답은 1~5여야 합니다`;
    }
    if (mode === 'answer_value' && !answer) {
      return `${questionNo}번 단답형 정답을 입력해주세요`;
    }
  }
  return '';
}

export function answerModeSummary(modes) {
  const counts = (Array.isArray(modes) ? modes : []).reduce((out, mode) => {
    out[mode || 'unverified'] = (out[mode || 'unverified'] || 0) + 1;
    return out;
  }, {});
  return {
    counts,
    text: [
      `객관식 ${counts.choice_number || 0}`,
      `단답형 ${counts.answer_value || 0}`,
      `수동 ${counts.manual_review || 0}`,
      `미확인 ${counts.unverified || 0}`,
    ].join(' · '),
  };
}

export function projectAnswerRound(test, options = {}) {
  const problems = Math.max(0, Number(options.problems ?? test?.problems ?? 0) || 0);
  const round = String(options.round ?? test?.round ?? '1').trim() || '1';
  const answerKey = parseAnswerSpec(options.answers, problems);
  const answerModes = answerModesForTest(
    { answerModes: Array.isArray(options.modes) ? options.modes : [] },
    problems,
    round,
  );
  const existingAnswerKeys = test?.answerKeys
    && !Array.isArray(test.answerKeys)
    && typeof test.answerKeys === 'object'
    ? test.answerKeys
    : {};
  const existingAnswerModes = test?.answerModes
    && !Array.isArray(test.answerModes)
    && typeof test.answerModes === 'object'
    ? test.answerModes
    : {};
  return {
    round,
    answerKey,
    answerKeys: { ...existingAnswerKeys, [round]: answerKey.slice() },
    answerModes: { ...existingAnswerModes, [round]: answerModes },
    issue: answerModeConsistencyIssue(answerKey, answerModes),
  };
}

export function csvCell(value) {
  const text = String(value ?? '');
  return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

export function buildTestCatalogCsvTemplate(ilsanGraphDifficulty = '그래프 포함') {
  const choiceAnswers = Array.from({ length: 20 }, (_, index) => String((index % 5) + 1)).join(' ');
  const choiceModes = new Array(20).fill('choice_number').join(' ');
  const mixedAnswers = Array.from({ length: 20 }, (_, index) => index % 2 ? '1/2' : '3').join(' ');
  const mixedModes = Array.from(
    { length: 20 },
    (_, index) => index % 2 ? 'answer_value' : 'choice_number',
  ).join(' ');
  const rows = [
    ['분류', '과목', '난이도', '고사', '회차', '시험명', '문항수', '정답', '유형', '1회차정답', '1회차유형', '2회차정답', '2회차유형', '3회차정답', '3회차유형'],
    ['복습 테스트', '대수', '상', '', '1', '대수 복습 상 1회차', '20', choiceAnswers, choiceModes, '', '', '', '', '', ''],
    ['단원평가', '공수1', 'Lv.4', '', '1', '원의 방정식 Lv.4', '20', '', '', mixedAnswers, mixedModes, mixedAnswers, mixedModes, mixedAnswers, mixedModes],
    ['트레이닝팩', '미적분1', '트팩', '', '1', '함수의 극한1', '20', '', '', choiceAnswers, choiceModes, choiceAnswers, choiceModes, '', ''],
    ['학군지 기출', '공수1', '상', '중간고사', '1', '학군지 기출 공수1 중간고사 상 1회차', '20', choiceAnswers, choiceModes, '', '', '', '', '', ''],
    ['일산 기출', '대수', '중상', '기말고사', '1', '일산 기출 대수 기말고사 중상 1회차', '20', choiceAnswers, choiceModes, '', '', '', '', '', ''],
    ['일산 기출', '대수', ilsanGraphDifficulty, '기말고사', '2', '그래프 포함 일산 기출 대수 기말고사 2회차', '20', choiceAnswers, choiceModes, '', '', '', '', '', ''],
  ];
  return `\uFEFF${rows.map(row => row.map(csvCell).join(',')).join('\r\n')}`;
}

export function parseCsv(text) {
  const rows = [];
  let row = [];
  let cell = '';
  let quoted = false;
  const source = String(text ?? '');

  for (let index = 0; index < source.length; index += 1) {
    const character = source[index];
    const next = source[index + 1];
    if (quoted) {
      if (character === '"' && next === '"') {
        cell += '"';
        index += 1;
      } else if (character === '"') {
        quoted = false;
      } else {
        cell += character;
      }
      continue;
    }

    if (character === '"') {
      quoted = true;
    } else if (character === ',') {
      row.push(cell);
      cell = '';
    } else if (character === '\n') {
      row.push(cell);
      rows.push(row);
      row = [];
      cell = '';
    } else if (character !== '\r') {
      cell += character;
    }
  }

  row.push(cell);
  rows.push(row);
  return rows.filter(items => items.some(item => String(item || '').trim()));
}

export function headerKey(value) {
  const key = String(value || '')
    .replace(/^\uFEFF/, '')
    .trim()
    .toLowerCase()
    .replace(/\s+/g, '');
  return HEADER_ALIASES[key] || key;
}

export function rowObject(headers, cells) {
  const out = {};
  headers.forEach((header, index) => {
    if (!header) return;
    out[header] = String(cells[index] ?? '').trim();
  });
  return out;
}

export function csvAnswerRounds(row) {
  return ['1', '2', '3'].filter(round => String(row?.[`answers${round}`] || '').trim());
}

export function hasRoundAnswerColumns(row) {
  return csvAnswerRounds(row).length > 0;
}

function reportParseWarning(onWarning, message, error) {
  if (typeof onWarning === 'function') onWarning(message, error);
}

export function answerKeyFromCsvRow(row, round, problems, onWarning) {
  const direct = String(row?.[`answers${round}`] || '').trim();
  if (direct) return parseAnswerSpec(direct, problems);
  const jsonText = String(row?.answersJson || '').trim();
  if (jsonText) {
    try {
      const parsed = JSON.parse(jsonText);
      if (Array.isArray(parsed)) return parseAnswerSpec(parsed, problems);
    } catch (error) {
      reportParseWarning(onWarning, '[tests] answers_json parse failed', error);
    }
  }
  return parseAnswerSpec(row?.answers || '', problems);
}

export function normalizeCsvAnswerMode(value) {
  const compact = String(value || '').trim().toLowerCase().replace(/[\s_-]+/g, '');
  if (['choicenumber', 'choice', '객관식', '객관식번호'].includes(compact)) return 'choice_number';
  if (['answervalue', 'shortanswer', '주관식', '단답', '단답형'].includes(compact)) return 'answer_value';
  if (['manualreview', 'manual', '수동', '수동검토'].includes(compact)) return 'manual_review';
  return normalizeAnswerMode(value);
}

export function parseCsvAnswerModes(value, problems) {
  let raw = value;
  if (typeof raw === 'string') {
    const text = raw.trim();
    if (!text) return [];
    try {
      const parsed = JSON.parse(text);
      raw = Array.isArray(parsed) ? parsed : text.split(/[\s,]+/).filter(Boolean);
    } catch {
      raw = text.split(/[\s,]+/).filter(Boolean);
    }
  }
  if (!Array.isArray(raw) || raw.length !== problems) return [];
  return raw.map(normalizeCsvAnswerMode);
}

export function answerModesFromCsvRow(row, round, problems, onWarning) {
  const direct = String(row?.[`modes${round}`] || '').trim();
  if (direct) return parseCsvAnswerModes(direct, problems);
  const jsonText = String(row?.modesJson || '').trim();
  if (jsonText) {
    try {
      const parsed = JSON.parse(jsonText);
      const selected = Array.isArray(parsed) ? parsed : parsed?.[round];
      if (Array.isArray(selected)) return parseCsvAnswerModes(selected, problems);
    } catch (error) {
      reportParseWarning(onWarning, '[tests] modes_json parse failed', error);
    }
  }
  return parseCsvAnswerModes(row?.modes || '', problems);
}
