const KST_OFFSET_MS = 9 * 60 * 60 * 1000;
const DEFAULT_DEMO_NOW = '2026-06-17T00:00:00+09:00';
const DEMO_LEVELS = ['중', '중상', '상'];
const DEMO_SUBJECTS = ['공통수학1', '공통수학2', '대수', '미적분', '기하'];

const STUDENT_SEEDS = [
  ['김민준', '해솔고', '2학년', '공통수학1', '기본', '중', '개념원리 공통수학1', [['월1', '14:30'], ['수1', '14:30']]],
  ['이서연', '해솔고', '2학년', '공통수학1', '심화', '중상', '쎈 공통수학1', [['화2', '18:20'], ['목2', '18:20']]],
  ['박지호', '나래고', '1학년', '공통수학2', '기본', '중', '개념원리 공통수학2', [['월2', '18:10'], ['금2', '18:10']]],
  ['최하린', '나래고', '1학년', '공통수학2', '심화', '상', 'RPM 공통수학2', [['수2', '18:30'], ['토1', '13:10']]],
  ['정도윤', '하늘고', '3학년', '미적분', '정규', '중상', '마플 미적분', [['화1', '15:00'], ['목1', '15:00']]],
  ['한유나', '하늘고', '3학년', '미적분', '심화', '상', '블랙라벨 미적분', [['수1', '15:20'], ['금1', '15:20']]],
  ['오시우', '빛가람고', '2학년', '대수', '정규', '중', '개념원리 대수', [['월1', '14:00'], ['목1', '14:00']]],
  ['신가은', '빛가람고', '2학년', '대수', '심화', '중상', '쎈 대수', [['화2', '18:40'], ['금2', '18:40']]],
  ['문태오', '새봄고', '1학년', '공통수학1', '기본', '중', '풍산자 공통수학1', [['수2', '18:00'], ['토1', '13:30']]],
  ['장예린', '새봄고', '1학년', '공통수학2', '기본', '중', '풍산자 공통수학2', [['월2', '18:30'], ['목2', '18:30']]],
  ['서준호', '한빛중', '3학년', '기하', '정규', '중상', '개념원리 기하', [['화1', '15:30'], ['금1', '15:30']]],
  ['유다인', '한빛중', '3학년', '기하', '심화', '상', '쎈 기하', [['수1', '16:00'], ['토2', '16:00']]],
  ['강현우', '미래고', '2학년', '미적분', '정규', '중', '수력충전 미적분', [['월1', '14:50'], ['수1', '14:50']]],
  ['임채원', '미래고', '2학년', '대수', '정규', '중상', '마플 대수', [['화2', '19:00'], ['목2', '19:00']]],
  ['조민서', '푸른고', '1학년', '공통수학1', '심화', '상', '최상위 공통수학1', [['금1', '15:40'], ['토1', '13:40']]],
];

const VIDEO_GROUPS = [
  ['공통수학1', '기본', '일차방정식'],
  ['공통수학1', '심화', '이차함수 심화'],
  ['공통수학2', '기본', '집합과 명제'],
  ['공통수학2', '심화', '함수의 그래프'],
  ['대수', '정규', '수열의 합'],
  ['대수', '심화', '지수로그 활용'],
  ['미적분', '정규', '미분계수'],
  ['미적분', '심화', '적분 응용'],
  ['기하', '정규', '벡터 기본'],
  ['기하', '심화', '공간도형'],
];

const UNIT_TESTS = [
  ['demo-test-unit-001', '일차방정식 단원평가 1회', '공통수학1', 'Lv.3', '1'],
  ['demo-test-unit-002', '이차함수 단원평가 2회', '공통수학1', 'Lv.4', '2'],
  ['demo-test-unit-003', '집합과 명제 단원평가 1회', '공통수학2', 'Lv.3', '1'],
  ['demo-test-unit-004', '함수 그래프 단원평가 2회', '공통수학2', 'Lv.4', '2'],
  ['demo-test-unit-005', '수열 단원평가 1회', '대수', 'Lv.4', '1'],
  ['demo-test-unit-006', '미분 단원평가 1회', '미적분', 'Lv.5', '1'],
  ['demo-test-unit-007', '벡터 단원평가 1회', '기하', 'Lv.5', '1'],
];

const REVIEW_TESTS = [
  ['demo-test-review-001', '6월 복습 테스트 기본', '공통수학1', '중', '1'],
  ['demo-test-review-002', '6월 복습 테스트 심화', '공통수학2', '중상', '1'],
  ['demo-test-review-003', '대수 누적 복습', '대수', '중상', '2'],
  ['demo-test-review-004', '미적분 누적 복습', '미적분', '상', '2'],
];

const SCHOOL_PAST_TESTS = [
  ['demo-test-school-001', '해솔고 2025 기말 적중', '공통수학1', '중', '1', '기말고사'],
  ['demo-test-school-002', '나래고 2025 기말 적중', '공통수학2', '중상', '1', '기말고사'],
  ['demo-test-school-003', '하늘고 2025 기말 적중', '미적분', '상', '1', '기말고사'],
];

const ILSAN_PAST_TESTS = [
  ['demo-test-ilsan-001', '일산권 공통수학 대표기출', '공통수학1', '중', '1', '기말고사'],
  ['demo-test-ilsan-002', '일산권 미적분 그래프 특강', '미적분', '그래프 포함', '1', '기말고사'],
];

function coerceDate(value = DEFAULT_DEMO_NOW) {
  if (value instanceof Date && Number.isFinite(value.getTime())) return value;
  const parsed = new Date(value ?? DEFAULT_DEMO_NOW);
  if (Number.isFinite(parsed.getTime())) return parsed;
  return new Date(DEFAULT_DEMO_NOW);
}

function dateKey(value) {
  const kst = new Date(coerceDate(value).getTime() + KST_OFFSET_MS);
  const y = kst.getUTCFullYear();
  const m = String(kst.getUTCMonth() + 1).padStart(2, '0');
  const d = String(kst.getUTCDate()).padStart(2, '0');
  return `${y}-${m}-${d}`;
}

function addDays(key, delta) {
  const [y, m, d] = String(key).split('-').map(Number);
  const dt = new Date(Date.UTC(y, m - 1, d + delta));
  return `${dt.getUTCFullYear()}-${String(dt.getUTCMonth() + 1).padStart(2, '0')}-${String(dt.getUTCDate()).padStart(2, '0')}`;
}

function isoAt(key, hhmm) {
  return `${key}T${hhmm}:00+09:00`;
}

function nextSaturdayFrom(key) {
  const [y, m, d] = String(key).split('-').map(Number);
  const dt = new Date(Date.UTC(y, m - 1, d));
  const day = dt.getUTCDay();
  const delta = (6 - day + 7) % 7;
  return addDays(key, delta || 7);
}

function studentId(index) {
  return `demo-s${String(index + 1).padStart(3, '0')}`;
}

function createStudents() {
  return STUDENT_SEEDS.map((seed, index) => {
    const [name, school, grade, curriculum, subCurriculum, level, book, slots] = seed;
    const id = studentId(index);
    const student = {
      id,
      name,
      school,
      grade,
      curriculum,
      subCurriculum,
      level,
      phone: `010-0000-${String(index + 101).padStart(4, '0')}`,
      parentPhone: `010-1000-${String(index + 101).padStart(4, '0')}`,
      docUrl: `/demo/rh3123/demo-student-card/${id}`,
      autoVideoAssignCount: (index % 3) + 1,
      selfStudyDays: index % 4 === 0 ? ['금'] : [],
      book,
      currentBook: book,
      nextBook: index % 2 === 0 ? '오답 정리 노트' : '개념 확인 프린트',
      memo: '데모용 안전 학생 데이터',
    };
    slots.forEach(([day, time], slotIndex) => {
      student[`day${slotIndex + 1}`] = day;
      student[`visitTime${slotIndex + 1}`] = time;
    });
    return student;
  });
}

function createVideos() {
  const videos = [];
  let counter = 1;
  VIDEO_GROUPS.forEach(([curriculum, subCurriculum, unit]) => {
    for (let chapter = 1; chapter <= 3; chapter += 1) {
      const mid = `demo-v${String(counter).padStart(3, '0')}`;
      videos.push({
        id: mid,
        mid,
        title: `${unit} ${chapter}강`,
        curriculum,
        subCurriculum,
        chapter,
        durationSec: 1200 + chapter * 180,
        url: `/demo-assets/videos/${mid}.mp4`,
        thumbnailUrl: `/demo-assets/thumbs/${mid}.png`,
      });
      counter += 1;
    }
  });
  return videos;
}

function createMaterials() {
  return {
    'demo-mat-001': {
      id: 'demo-mat-001',
      title: '6월 개념 확인 프린트',
      curriculum: '공통수학1',
      url: '/demo-assets/materials/demo-mat-001.pdf',
    },
    'demo-mat-002': {
      id: 'demo-mat-002',
      title: '기말 대비 오답 노트',
      curriculum: '공통수학2',
      url: '/demo-assets/materials/demo-mat-002.pdf',
    },
    'demo-mat-003': {
      id: 'demo-mat-003',
      title: '미적분 그래프 특강지',
      curriculum: '미적분',
      url: '/demo-assets/materials/demo-mat-003.pdf',
    },
  };
}

function videosForStudent(videos, student) {
  const primary = videos.filter(v =>
    v.curriculum === student.curriculum && v.subCurriculum === student.subCurriculum
  );
  if (primary.length) return primary;
  return videos.filter(v => v.curriculum === student.curriculum);
}

function createUpdates(baseDate, nextDate, students, videos) {
  const updates = { [baseDate]: {}, [nextDate]: {} };
  students.forEach((student, index) => {
    const mids = videosForStudent(videos, student).slice(0, (index % 3) + 1).map(v => v.mid);
    updates[baseDate][student.id] = {
      videos: mids,
      source: index % 5 === 1 ? 'manual' : 'auto',
    };
    if (index % 4 === 0) {
      updates[nextDate][student.id] = {
        videos: videosForStudent(videos, student).slice(1, 3).map(v => v.mid),
        source: 'auto',
      };
    }
  });
  return updates;
}

function homeworkRows(student, index) {
  return [
    {
      book: student.currentBook,
      this: `${12 + index}쪽 ${index % 2 === 0 ? '홀수' : '짝수'}번`,
      pct: String(60 + (index % 5) * 10),
      comment: index % 3 === 0 ? '서술형 풀이 확인' : '오답 표시 후 재풀이',
      next: `${14 + index}쪽 개념 확인`,
    },
  ];
}

function applyReadableLogModalFixture(logs, baseDate, prevDate) {
  const sid = 'demo-s001';
  if (logs[prevDate]?.[sid]) {
    logs[prevDate][sid] = {
      ...logs[prevDate][sid],
      notes: '김민서 이전 수업: 지수법칙 개념을 복습하고 계산 실수를 확인했습니다.',
      homeworkTable: [
        {
          book: '개념원리 공통수학1',
          this: '12쪽 대표유형',
          pct: '60',
          comment: '풀이 과정 점검',
          next: '14쪽 개념 확인',
        },
      ],
    };
  }
  if (logs[baseDate]?.[sid]) {
    logs[baseDate][sid] = {
      ...logs[baseDate][sid],
      notes: '김민서 오늘 수업: 상담 메모와 과제 흐름을 확인했습니다.',
      homeworkTable: [
        {
          book: '개념원리 공통수학1',
          this: '13쪽 지수법칙',
          pct: '70',
          comment: '오답 표시 후 재풀이',
          next: '15쪽 대표유형',
        },
      ],
    };
  }
}

function createLogs(baseDate, prevDate, students) {
  const logs = { [prevDate]: {}, [baseDate]: {} };
  students.forEach((student, index) => {
    logs[prevDate][student.id] = {
      notes: `${student.name} 이전 수업: 핵심 개념 복습과 질문 정리 완료.`,
      homeworkTable: homeworkRows(student, index),
      hwAssigned: true,
      hwChecked: index % 2 === 0,
      done: true,
      leaveTime: index % 2 === 0 ? '20:40' : '17:10',
      updatedAt: isoAt(prevDate, '20:45'),
      tests: index % 5 === 0 ? [
        {
          id: 'demo-test-unit-001',
          name: '일차방정식 단원평가 1회',
          round: '1',
          score: 86 + index,
          wrong: ['4', '12'],
          memo: '계산 실수 확인',
        },
      ] : [],
    };
    logs[baseDate][student.id] = {
      notes: `${student.name} 오늘 수업: 데모 데이터로 상담 메모와 과제 흐름을 확인합니다.`,
      homeworkTable: homeworkRows(student, index + 1),
      hwAssigned: true,
      hwChecked: index % 3 === 0,
      selfStudy: index % 4 === 0,
      assignedTests: index % 4 === 0 ? [
        {
          id: 'demo-test-review-001',
          name: '6월 복습 테스트 기본',
          category: 'REVIEW',
          categoryLabel: '복습 테스트',
          curriculum: student.curriculum,
          difficulty: student.level,
          round: '1',
          label: `복습 테스트 / ${student.curriculum} / ${student.level} / 1회 / 6월 복습 테스트 기본`,
          status: 'assigned',
          statusLabel: '배정',
          answerUrl: '/demo-assets/answers/demo-test-review-001.html',
        },
      ] : [],
      updatedAt: isoAt(baseDate, '16:20'),
    };
  });
  applyReadableLogModalFixture(logs, baseDate, prevDate);
  return logs;
}

function createProgress(baseDate, prevDate, students, videos) {
  const progress = { [prevDate]: {}, [baseDate]: {} };
  students.forEach((student, index) => {
    const mids = videosForStudent(videos, student).slice(0, 3).map(v => v.mid);
    const prevEntry = {};
    const currentEntry = {};
    mids.forEach((mid, midIndex) => {
      prevEntry[mid] = midIndex === 0 ? 'done' : midIndex === 1 ? 'interrupted' : 'none';
      currentEntry[mid] = midIndex === 0 ? 'done' : midIndex === 1 && index % 3 === 0 ? 'skip' : 'none';
    });
    if (mids[2]) {
      currentEntry.__manualProgressMids = { [mids[2]]: true };
    }
    if (index % 4 === 0) {
      currentEntry.tests = {
        '복습 테스트 / 공통수학1 / 중 / 1회 / 6월 복습 테스트 기본': 'assigned',
      };
    }
    progress[prevDate][student.id] = prevEntry;
    progress[baseDate][student.id] = currentEntry;
  });
  return progress;
}

function answerUrl(id) {
  return `/demo-assets/answers/${id}.html`;
}

function testRow([id, name, curriculum, difficulty, round, term = '']) {
  return {
    id,
    name,
    curriculum,
    difficulty,
    round,
    term,
    problems: 20,
    answerUrl: answerUrl(id),
    sourceFiles: {
      answerUrl: answerUrl(id),
      solutionUrl: answerUrl(id),
    },
  };
}

function createTestsConfig() {
  return {
    categories: {
      UNIT: { label: '단원평가', tests: UNIT_TESTS.map(testRow) },
      REVIEW: { label: '복습 테스트', tests: REVIEW_TESTS.map(testRow) },
      SCHOOL_PAST: { label: '학교별 기출', tests: SCHOOL_PAST_TESTS.map(testRow) },
      ILSAN_PAST: { label: '일산 기출', tests: ILSAN_PAST_TESTS.map(testRow) },
    },
    autoAssignRules: Object.fromEntries(['UNIT', 'REVIEW', 'SCHOOL_PAST', 'ILSAN_PAST'].map(category => [
      category,
      Object.fromEntries(DEMO_SUBJECTS.map(subject => [
        subject,
        {
          'Lv.3': DEMO_LEVELS,
          'Lv.4': ['중', '중상', '상'],
          'Lv.5': ['중상', '상'],
          'Lv.6': ['상'],
          중: DEMO_LEVELS,
          중상: ['중상', '상'],
          상: ['상'],
          '그래프 포함': ['중상', '상'],
        },
      ])),
    ])),
  };
}

function createTests(prevDate, baseDate) {
  return {
    [prevDate]: {
      'demo-s001': [{ id: 'demo-test-unit-001', name: '일차방정식 단원평가 1회', round: '1', score: 88, wrong: ['4', '12'], memo: '계산 실수' }],
      'demo-s005': [{ id: 'demo-test-unit-006', name: '미분 단원평가 1회', round: '1', score: 91, wrong: ['9'], memo: '그래프 해석 양호' }],
    },
    [baseDate]: {
      'demo-s002': [{ id: 'demo-test-review-001', name: '6월 복습 테스트 기본', round: '1', score: 84, wrong: ['3', '18'], memo: '부호 확인' }],
    },
  };
}

function createDayMaps(baseDate, nextDate, weekendDate, students) {
  const ids = students.map(student => student.id);
  const attendance = { [baseDate]: {}, [nextDate]: {} };
  const contact = { [baseDate]: {}, [nextDate]: {} };
  const arriveTime = { [baseDate]: {}, [nextDate]: {} };
  ids.forEach((id, index) => {
    if (index < 9) attendance[baseDate][id] = 1;
    if (index % 3 === 0) contact[baseDate][id] = 1;
    if (index % 5 === 0) arriveTime[baseDate][id] = index % 2 === 0 ? '14:20' : '18:05';
    if (index % 6 === 0) attendance[nextDate][id] = 1;
  });
  return {
    attendance,
    contact,
    arriveTime,
    extraAttend: {
      [baseDate]: ['demo-s014', 'demo-s015'],
      [nextDate]: ['demo-s005'],
    },
    weekendSlots: {
      [weekendDate]: {
        'demo-s004': [1],
        'demo-s012': [2],
        'demo-s015': [1],
      },
    },
    todayOrder: {
      [baseDate]: ids,
      [nextDate]: ids.slice().reverse(),
    },
    absent: {
      by_date: {
        [baseDate]: ['demo-s006'],
      },
      by_student: {
        'demo-s006': [baseDate],
      },
      by_slot: {
        [baseDate]: {
          'demo-s006': [1],
        },
      },
    },
    makeupCarryover: {
      [baseDate]: {
        'demo-s006': [{ from: addDays(baseDate, -2), reason: '학교 행사', slot: 1 }],
      },
    },
  };
}

function createSchoolCalendar(baseDate) {
  const year = String(baseDate).slice(0, 4);
  return {
    schemaVersion: 2,
    activeYear: year,
    activeExam: 'final',
    years: {
      [year]: {
        activeExam: 'final',
        schools: {
          해솔고: {
            common: { textbook: '공통수학 교과서', semesterStart: '3/4', finalMath: '6/30-7/2', finalRange: '이차함수까지', finalNote: '서술형 대비' },
            grades: { '2학년': { finalMath: '6/30-7/2', finalRange: '함수와 방정식' } },
          },
          나래고: {
            common: { textbook: '수학의 정석', semesterStart: '3/5', finalMath: '6/26-6/28', finalRange: '집합과 명제', finalNote: '프린트 포함' },
            grades: { '1학년': { finalMath: '6/26-6/28', finalRange: '명제 활용' } },
          },
          하늘고: {
            common: { textbook: '미적분 기본서', semesterStart: '3/6', finalMath: '7/1-7/3', finalRange: '도함수 활용', finalNote: '그래프 해석' },
            grades: { '3학년': { finalMath: '7/1-7/3', finalRange: '미분 전체' } },
          },
        },
      },
    },
  };
}

function createAnnouncements(baseDate, students) {
  const allTargets = students.map(student => student.id);
  const snapshot = students.slice(0, 6).map(student => ({
    sid: student.id,
    name: student.name,
    curriculum: student.curriculum,
    grade: student.grade,
  }));
  return [
    {
      id: 'demo-ann-001',
      kind: 'announcement',
      title: '기말 대비 데모 공지',
      content: '이번 주는 오답 노트와 학교별 기출 확인을 함께 진행합니다.',
      targetSids: allTargets,
      targetSnapshot: snapshot,
      targetLabel: '전체 데모 학생',
      targetCount: allTargets.length,
      createdAt: isoAt(baseDate, '10:00'),
      expiresAt: isoAt(addDays(baseDate, 1), '22:00'),
      imageUrl: '/demo-assets/images/demo-announcement-001.png',
      replies: [
        { id: 'demo-reply-001', sid: 'demo-s001', name: '김민준', text: '확인했습니다.', createdAt: isoAt(baseDate, '10:30') },
      ],
    },
    {
      id: 'demo-survey-001',
      kind: 'survey',
      title: '보충 가능 시간 조사',
      content: '이번 주 보충 가능 시간을 선택해 주세요.',
      targetSids: allTargets.slice(0, 8),
      targetSnapshot: snapshot,
      targetLabel: '일부 데모 학생',
      targetCount: 8,
      createdAt: isoAt(baseDate, '11:20'),
      expiresAt: isoAt(addDays(baseDate, 2), '20:00'),
      survey: {
        status: 'public',
        anonymous: false,
        allowMultiple: false,
        questions: [
          {
            id: 'demo-q-001',
            type: 'single',
            text: '가능한 시간을 선택해 주세요.',
            required: true,
            options: [
              { id: 'demo-o-001', text: '금요일 18시' },
              { id: 'demo-o-002', text: '토요일 13시' },
            ],
          },
        ],
      },
      surveyResults: {
        responseCount: 3,
        questions: [
          {
            id: 'demo-q-001',
            responseCount: 3,
            options: [
              { id: 'demo-o-001', text: '금요일 18시', count: 2 },
              { id: 'demo-o-002', text: '토요일 13시', count: 1 },
            ],
          },
        ],
      },
    },
  ];
}

function createMatAssign(students) {
  return Object.fromEntries(students.map((student, index) => [
    student.id,
    index % 3 === 0 ? ['demo-mat-001', 'demo-mat-002'] : index % 3 === 1 ? ['demo-mat-002'] : ['demo-mat-003'],
  ]));
}

export function buildInitialDemoData(now = DEFAULT_DEMO_NOW, schemaVersion = 1) {
  const currentDate = dateKey(now);
  const previousDate = addDays(currentDate, -1);
  const nextDate = addDays(currentDate, 1);
  const weekendDate = nextSaturdayFrom(currentDate);
  const students = createStudents();
  const videos = createVideos();
  const dayMaps = createDayMaps(currentDate, nextDate, weekendDate, students);

  return {
    schemaVersion,
    generatedAt: isoAt(currentDate, '00:00'),
    demoDate: currentDate,
    dates: {
      previous: previousDate,
      current: currentDate,
      next: nextDate,
      weekend: weekendDate,
    },
    students,
    videos,
    materials: createMaterials(),
    matAssign: createMatAssign(students),
    updates: createUpdates(currentDate, nextDate, students, videos),
    logs: createLogs(currentDate, previousDate, students),
    progress: createProgress(currentDate, previousDate, students, videos),
    testsConfig: createTestsConfig(),
    tests: createTests(previousDate, currentDate),
    attendance: dayMaps.attendance,
    contact: dayMaps.contact,
    arriveTime: dayMaps.arriveTime,
    extraAttend: dayMaps.extraAttend,
    weekendSlots: dayMaps.weekendSlots,
    todayOrder: dayMaps.todayOrder,
    absent: dayMaps.absent,
    makeupCarryover: dayMaps.makeupCarryover,
    schoolCalendar: createSchoolCalendar(currentDate),
    announcements: createAnnouncements(currentDate, students),
    operationNotes: [
      {
        id: 2,
        content: '공지 답장 확인',
        created_at: isoAt(currentDate, '09:20'),
      },
      {
        id: 1,
        content: '보강 일정 다시 점검',
        created_at: isoAt(currentDate, '09:10'),
      },
    ],
    studentOperationLogs: [],
  };
}
