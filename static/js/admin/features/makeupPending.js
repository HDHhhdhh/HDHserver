const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
const WCHR = '일월화수목금토';
const ACTIVATION_STORAGE_KEY = 'adminMakeupPendingActivationDate';

function normDate(value) {
  const s = String(value || '').slice(0, 10);
  return DATE_RE.test(s) ? s : '';
}

export function nextLocalDateKey(offsetDays = 1) {
  const d = new Date();
  d.setDate(d.getDate() + Number(offsetDays || 0));
  return [
    d.getFullYear(),
    String(d.getMonth() + 1).padStart(2, '0'),
    String(d.getDate()).padStart(2, '0'),
  ].join('-');
}

export function makeupPendingActivationDate(anchorDate = '', pendingDates = []) {
  const anchor = normDate(anchorDate) || nextLocalDateKey(0);
  const stored = readStoredActivationDate();
  if (stored) return stored;

  const dates = (Array.isArray(pendingDates) ? pendingDates : [])
    .map(normDate)
    .filter(Boolean)
    .sort();
  let start = anchor;
  if (dates.length && !dates.some(date => date >= anchor)) {
    start = dates.filter(date => date <= anchor).pop() || anchor;
  }

  writeStoredActivationDate(start);
  return start;
}

function readStoredActivationDate() {
  try {
    if (typeof localStorage === 'undefined') return '';
    return normDate(localStorage.getItem(ACTIVATION_STORAGE_KEY));
  } catch {
    return '';
  }
}

function writeStoredActivationDate(date) {
  const value = normDate(date);
  if (!value) return;
  try {
    if (typeof localStorage !== 'undefined') {
      localStorage.setItem(ACTIVATION_STORAGE_KEY, value);
    }
  } catch {}
}

export function studentSchool(stu) {
  return String(
    stu?.school ||
    stu?.schoolName ||
    stu?.highSchool ||
    stu?.middleSchool ||
    stu?.high ||
    stu?.middle ||
    stu?.schoolHigh ||
    stu?.schoolMiddle ||
    stu?.['학교'] ||
    stu?.['고등학교'] ||
    stu?.['중학교'] ||
    ''
  ).trim();
}

export function studentCourse(stu) {
  return [stu?.curriculum || stu?.course || stu?.subject || stu?.className, stu?.subCurriculum]
    .map(v => String(v || '').trim())
    .filter(Boolean)
    .join(' ');
}

function schoolForExport(stu) {
  return studentSchool(stu)
    .replace(/고등학교$/u, '')
    .replace(/중학교$/u, '')
    .replace(/[고중]$/u, '');
}

function gradeNumberForExport(stu) {
  const raw = String(stu?.grade || stu?.gradeLevel || stu?.['학년'] || '').trim();
  const m = raw.match(/\d+/);
  return m ? m[0] : raw;
}

function baseNameForExport(stu, fallbackName = '') {
  return String(stu?.name || fallbackName || '')
    .trim()
    .replace(/\s*[\(\[][^()\[\]]+[\)\]]\s*$/u, '')
    .trim();
}

function chatNameForExport(stu, fallbackName = '') {
  const school = schoolForExport(stu);
  const grade = gradeNumberForExport(stu);
  const name = baseNameForExport(stu, fallbackName);
  return `A ${school}${grade}${school || grade ? ' ' : ''}${name}`.trim();
}

function studentKeyForExport(item) {
  const stu = item?.student || {};
  const school = schoolForExport(stu);
  const grade = gradeNumberForExport(stu);
  const name = baseNameForExport(stu, item?.name || item?.sid);
  return [school, grade, name].filter(Boolean).join('|') || String(item?.sid || '').trim();
}

function courseForExport(course) {
  const text = String(course || '').trim();
  if (!text) return '';
  return text.split(/\s+/)[0] || text;
}

export function formatMakeupDate(dateStr) {
  const date = normDate(dateStr);
  if (!date) return '';
  const d = new Date(date);
  const month = d.getMonth() + 1;
  const day = d.getDate();
  const yoil = WCHR[d.getDay()] || '';
  return `${month}/${day}(${yoil})`;
}

function parseSlotNumbers(raw) {
  const values = Array.isArray(raw) ? raw : [raw];
  const slots = values.flatMap(value => {
    const matches = String(value ?? '').match(/\d+/g) || [];
    return matches.map(n => parseInt(n, 10));
  }).filter(n => n === 1 || n === 2);
  return Array.from(new Set(slots)).sort((a, b) => a - b);
}

function dayValues(stu) {
  return Object.keys(stu || {})
    .filter(k => /^day\d+$/.test(k) && stu[k])
    .sort((a, b) => parseInt(a.slice(3), 10) - parseInt(b.slice(3), 10))
    .map(k => String(stu[k]));
}

function regularSlotsForStudent(stu, dateStr) {
  const date = normDate(dateStr);
  if (!date) return [];
  const w = WCHR[new Date(date).getDay()] || '';
  return parseSlotNumbers(dayValues(stu).filter(value => String(value).startsWith(w)));
}

function carriedRowValue(carryover, date, sid, slot) {
  const rows = (carryover?.by_absence || carryover || {})?.[date] || {};
  const legacy = rows[String(sid)];
  if (legacy) return legacy;
  if (slot) return rows[`${sid}|${slot}`];
  return null;
}

function isCarriedRow(row) {
  if (!row) return false;
  if (row === true) return true;
  if (typeof row === 'object') return row.state === 'carried' || row.carried === true;
  return false;
}

function isCarriedOver(carryover, date, sid, slot) {
  return isCarriedRow(carriedRowValue(carryover, date, sid, slot));
}

function pushDemand(out, seen, item) {
  const sid = String(item.sid || '').trim();
  const absenceDate = normDate(item.absenceDate);
  const dateOnly = item.dateOnly === true;
  const slot = dateOnly ? '' : (parseSlotNumbers(item.slot)[0] || 1);
  if (!sid || !absenceDate) return;
  const key = `${item.source || 'absence'}|${absenceDate}|${sid}|${dateOnly ? 'date' : slot}|${item.manualKey || ''}`;
  if (seen.has(key)) return;
  seen.add(key);
  out.push({ ...item, sid, absenceDate, slot, dateOnly });
}

function buildAbsenceDemandRows({ studentsBySid, absentByDate = {}, absentSlotsByDate = {} }) {
  const out = [];
  const seen = new Set();
  const add = (date, sid, slots) => {
    const stu = studentsBySid.get(String(sid)) || { id: sid, name: sid };
    const finalSlots = parseSlotNumbers(slots);
    (finalSlots.length ? finalSlots : [1]).forEach(slot => pushDemand(out, seen, {
      source: 'absence',
      sid,
      absenceDate: date,
      slot,
      student: stu,
      name: String(stu?.name || sid).trim(),
      school: studentSchool(stu),
      course: studentCourse(stu),
    }));
  };

  if (absentByDate && typeof absentByDate === 'object') {
    for (const [dateRaw, ids] of Object.entries(absentByDate)) {
      const date = normDate(dateRaw);
      if (!date || !Array.isArray(ids)) continue;
      ids.forEach(id => {
        const sid = String(id || '').trim();
        if (!sid) return;
        const stu = studentsBySid.get(sid) || { id: sid, name: sid };
        const slots = parseSlotNumbers(absentSlotsByDate?.[date]?.[sid]);
        add(date, sid, slots.length ? slots : regularSlotsForStudent(stu, date));
      });
    }
  }

  if (absentSlotsByDate && typeof absentSlotsByDate === 'object') {
    for (const [dateRaw, sidMap] of Object.entries(absentSlotsByDate)) {
      const date = normDate(dateRaw);
      if (!date || !sidMap || typeof sidMap !== 'object') continue;
      for (const [sidRaw, slotsRaw] of Object.entries(sidMap)) {
        const sid = String(sidRaw || '').trim();
        if (!sid) continue;
        add(date, sid, parseSlotNumbers(slotsRaw));
      }
    }
  }

  return out;
}

function buildManualDemandRows({ studentsBySid, manualMakeups = {} }) {
  const out = [];
  const seen = new Set();
  if (!manualMakeups || typeof manualMakeups !== 'object') return out;
  for (const [dateRaw, rows] of Object.entries(manualMakeups)) {
    const date = normDate(dateRaw);
    if (!date || !rows || typeof rows !== 'object') continue;
    for (const [manualKeyRaw, value] of Object.entries(rows)) {
      const manualKey = String(manualKeyRaw || '').trim();
      const row = value && typeof value === 'object' ? value : {};
      if (!manualKey || isCarriedRow(row)) continue;
      const sid = String(row.sid || '').trim();
      if (!sid) continue;
      const stu = studentsBySid.get(sid) || { id: sid, name: sid };
      const regularSlots = regularSlotsForStudent(stu, date);
      const slots = parseSlotNumbers(row.slots ?? row.slot);
      const dateOnly = row.dateOnly === true || row.date_only === true || row.slotless === true;
      if (dateOnly) {
        pushDemand(out, seen, {
          source: 'manual',
          manualKey,
          sid,
          absenceDate: date,
          dateOnly: true,
          student: stu,
          name: String(stu?.name || sid).trim(),
          school: studentSchool(stu),
          course: String(row.course || studentCourse(stu) || '').trim(),
        });
        continue;
      }
      (slots.length ? slots : regularSlots.length ? regularSlots : [1]).forEach(slot => pushDemand(out, seen, {
        source: 'manual',
        manualKey,
        sid,
        absenceDate: date,
        slot,
        student: stu,
        name: String(stu?.name || sid).trim(),
        school: studentSchool(stu),
        course: String(row.course || studentCourse(stu) || '').trim(),
      }));
    }
  }
  return out;
}

function scheduledSupplyCounts({ studentsBySid, extra = {}, weekendSlots = {} }) {
  const counts = new Map();
  if (!extra || typeof extra !== 'object') return counts;

  const add = (sid, amount = 1) => {
    counts.set(sid, (counts.get(sid) || 0) + amount);
  };

  Object.entries(extra).sort(([a], [b]) => String(a).localeCompare(String(b))).forEach(([dateRaw, ids]) => {
    const date = normDate(dateRaw);
    if (!date || !Array.isArray(ids)) return;
    ids.map(id => String(id || '').trim()).filter(Boolean).forEach(sid => {
      const stu = studentsBySid.get(sid) || { id: sid };
      const rawSlots = parseSlotNumbers(weekendSlots?.[date]?.[sid]);
      const regular = new Set(regularSlotsForStudent(stu, date));
      const makeupSlots = rawSlots.filter(slot => !regular.has(slot));
      add(sid, makeupSlots.length || rawSlots.length || 1);
    });
  });

  return counts;
}

export function buildPendingMakeups({
  students = [],
  absentByDate = {},
  absentSlotsByDate = {},
  extra = {},
  weekendSlots = {},
  carryover = {},
  manualMakeups = {},
  minAbsenceDate = '',
} = {}) {
  const studentsBySid = new Map((students || []).map(stu => [String(stu?.id), stu]));
  const minDate = normDate(minAbsenceDate);
  const demandRows = [
    ...buildAbsenceDemandRows({ studentsBySid, absentByDate, absentSlotsByDate }),
    ...buildManualDemandRows({ studentsBySid, manualMakeups }),
  ].sort((a, b) =>
    String(a.absenceDate).localeCompare(String(b.absenceDate)) ||
    String(a.name).localeCompare(String(b.name), 'ko', { numeric: true }) ||
    String(a.sid).localeCompare(String(b.sid), 'ko', { numeric: true }) ||
    Number(a.slot || 0) - Number(b.slot || 0)
  );

  const supply = scheduledSupplyCounts({ studentsBySid, extra, weekendSlots });
  const pending = [];

  demandRows.forEach(item => {
    if (minDate && item.absenceDate < minDate) return;
    if (item.source !== 'manual' && isCarriedOver(carryover, item.absenceDate, item.sid, item.slot)) return;
    const sid = String(item.sid);
    const available = supply.get(sid) || 0;
    if (available > 0) {
      supply.set(sid, available - 1);
      return;
    }
    pending.push(item);
  });

  return pending;
}

export function buildCarryForwardPendingMakeups(input = {}) {
  return buildPendingMakeups({ ...input, minAbsenceDate: '' });
}

export function countPendingMakeupsBySid(input) {
  const counts = {};
  const rows = buildPendingMakeups({ ...input, minAbsenceDate: '' });
  rows.forEach(item => {
    counts[item.sid] = (counts[item.sid] || 0) + 1;
  });
  return counts;
}

function csvCell(value) {
  const s = String(value ?? '');
  if (/[",\r\n]/.test(s)) return `"${s.replace(/"/g, '""')}"`;
  return s;
}

function exportSlotLabel(slot) {
  const n = Number(slot);
  return n === 1 || n === 2 ? `${n}타임` : '';
}

export function buildMakeupExportRows(items = []) {
  const groups = new Map();
  (items || []).forEach(item => {
    const key = studentKeyForExport(item);
    if (!key) return;
    if (!groups.has(key)) {
      groups.set(key, {
        key,
        student: item.student || {},
        name: baseNameForExport(item.student || {}, item.name || item.sid),
        entries: [],
      });
    }
    groups.get(key).entries.push(item);
  });

  return Array.from(groups.values()).map(group => {
    const entries = group.entries
      .slice()
      .sort((a, b) =>
        String(a.absenceDate || '').localeCompare(String(b.absenceDate || '')) ||
        String(a.course || '').localeCompare(String(b.course || ''), 'ko', { numeric: true }) ||
        Number(a.slot || 0) - Number(b.slot || 0)
      );
    const duplicateCounts = new Map();
    entries.forEach(item => {
      const course = courseForExport(item.course);
      const key = `${item.absenceDate || ''}|${course}`;
      duplicateCounts.set(key, (duplicateCounts.get(key) || 0) + 1);
    });

    const seenDetails = new Set();
    const details = [];
    entries.forEach(item => {
      const date = formatMakeupDate(item.absenceDate);
      const course = courseForExport(item.course);
      const duplicateKey = `${item.absenceDate || ''}|${course}`;
      const needsSlot = !!item.slot && item.dateOnly !== true;
      const slot = needsSlot ? exportSlotLabel(item.slot) : '';
      const detail = [date, course, slot].filter(Boolean).join(' ').trim();
      const detailKey = `${duplicateKey}|${needsSlot ? item.slot || '' : ''}`;
      if (!detail || seenDetails.has(detailKey)) return;
      seenDetails.add(detailKey);
      details.push(detail);
    });

    return {
      time: '',
      chatName: chatNameForExport(group.student, group.name),
      text: `📢 보강 잡아주세요!\n\n${details.join(', ')} 결석분에 대한 보강 날짜 알려주세요~`,
    };
  });
}

export function makeupExportRowsToCsv(rows = []) {
  const columns = ['타임', '대화명', '텍스트'];
  const lines = [columns.map(csvCell).join(',')];
  (rows || []).forEach(row => {
    lines.push([
      row.time || '',
      row.chatName || '',
      row.text || '',
    ].map(csvCell).join(','));
  });
  return `\uFEFF${lines.join('\r\n')}\r\n`;
}
