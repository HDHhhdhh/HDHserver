const truthy = value => value === true || value === 1 || value === '1' || value === 'true';
const status = value => String(typeof value === 'object' ? value?.state || value?.status || '' : value || '').toLowerCase();

export function projectPendingWork({ rows, students, updates = {}, progress = {} }) {
  const people = new Map(students.map(student => [String(student.id), student]));
  const result = [], seen = new Set();
  for (const row of rows) {
    const student = people.get(row.sid);
    if (!student) continue;
    const add = (kind, label, rank, detail) => {
      const id = kind === 'review' ? `${kind}:${row.sid}` : `${kind}:${row.date}:${row.sid}`;
      if (seen.has(id)) return;
      seen.add(id);
      result.push({ id, sid: row.sid, date: row.date, name: student.name || row.sid,
        subject: student.curriculum || '', kind, label, rank, detail });
    };
    if (!row.done && !row.selfStudy && !row.hwChecked && (row.attended || row.hwRequested)) {
      add('homework', row.hwRequested ? '숙검 요청' : '숙검 대기', row.hwRequested ? 0 : 2, '출석 또는 숙검 요청 후 검사 미완료');
    }
    if (student.whiteReviewPending === true) add('review', '백지리뷰 검사', 1, '학생별 검사 대기 표시');
    if (!row.done && row.attended) {
      const assignment = updates?.[row.date]?.[row.sid];
      const mids = Array.isArray(assignment) ? assignment : assignment?.videos;
      // An absent progress document is unknown, not proof of unfinished work.
      if (Array.isArray(mids) && Object.hasOwn(progress?.[row.date] || {}, row.sid)) {
        const pending = [...new Set(mids.map(String))].filter(mid => ['assigned', 'interrupted', 'none'].includes(status(progress[row.date][row.sid]?.[mid])));
        if (pending.length) add('video', '영상 진도 확인', 3, `선택일 배정 중 미완료 진도 기록 ${pending.length}개 · 기록 없는 영상 제외`);
      }
    }
  }
  return result.sort((a, b) => a.rank - b.rank || a.name.localeCompare(b.name, 'ko') || a.date.localeCompare(b.date));
}

export function trailingDates(end, count = 7) {
  const date = new Date(`${end}T12:00:00Z`);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(end) || !Number.isFinite(date.getTime()) || date.toISOString().slice(0, 10) !== end) throw new Error('유효한 날짜가 필요합니다.');
  return Array.from({ length: count }, (_, index) => {
    const day = new Date(date); day.setUTCDate(day.getUTCDate() - count + index + 1);
    return day.toISOString().slice(0, 10);
  });
}

export function projectDailyMetrics({ date, attendance, logs, progress }) {
  const logEntries = Object.values(logs?.[date] || {});
  const homework = logEntries.filter(entry => entry && ['hwChecked', 'hwAssigned', 'hwCheckRequested'].some(key => truthy(entry[key])));
  const checked = homework.filter(entry => truthy(entry.hwChecked)).length;
  const videoStates = Object.values(progress?.[date] || {}).flatMap(entry => Object.entries(entry || {})
    .filter(([key]) => key !== 'tests' && !key.startsWith('__'))
    .map(([, value]) => status(value)).filter(value => ['done', 'assigned', 'interrupted', 'none'].includes(value)));
  const videosDone = videoStates.filter(value => value === 'done').length;
  return { date, attended: Object.values(attendance).filter(truthy).length,
    homeworkTotal: homework.length, homeworkChecked: checked,
    homeworkRate: homework.length ? Math.round(checked / homework.length * 100) : null,
    videoTotal: videoStates.length, videosDone,
    videoRate: videoStates.length ? Math.round(videosDone / videoStates.length * 100) : null };
}
