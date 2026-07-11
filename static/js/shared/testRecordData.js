import { fetchJsonOr } from './api.js';

const SAME_ORIGIN_NO_STORE = { credentials: 'same-origin', cache: 'no-store' };
const DETAILS_DAYS = '3650';

let recordsPromise = null;

export function escapeHtml(value = '') {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

export function escapeAttr(value = '') {
  return escapeHtml(value);
}

export function recordCreatedAt(record) {
  return String(record?.createdAt || record?.created_at || record?.date || '').trim();
}

export function recordTestId(record) {
  return String(record?.testId || record?.test_id || record?.sourceId || '').trim();
}

export function scoreText(record) {
  const score = String(record?.score || '').trim();
  if (score) return score;
  const correct = record?.correct ?? '';
  const total = record?.total ?? '';
  return correct !== '' && total !== '' ? `${correct}/${total}` : '-';
}

export function pctText(record) {
  const pct = Number(record?.pct);
  if (Number.isFinite(pct)) return `${Math.round(pct * 10) / 10}%`;
  const match = String(record?.score || '').trim().match(/^(\d+)\s*\/\s*(\d+)$/);
  if (!match) return '-';
  const correct = Number(match[1]);
  const total = Number(match[2]);
  return total > 0 ? `${Math.round((correct / total) * 1000) / 10}%` : '-';
}

export function wrongCount(record) {
  return Array.isArray(record?.wrong) ? record.wrong.length : 0;
}

export function recordTitle(record) {
  return String(
    record?.testName ||
    record?.unitName ||
    record?.name ||
    record?.testId ||
    '테스트 기록'
  ).trim();
}

export function recordSubtitle(record) {
  return [
    record?.curriculum,
    record?.testLevel || record?.difficulty,
    record?.round ? `${record.round}회차` : '',
  ].map(value => String(value || '').trim()).filter(Boolean).join(' · ');
}

export function isQaRecord(record) {
  const memo = String(record?.memo || '').toUpperCase();
  return memo.includes('QA') || memo.includes('로컬 QA') || memo.includes('FIXTURE');
}

function flattenTestsPayload(payload) {
  const rows = [];
  if (!payload || typeof payload !== 'object') return rows;
  Object.entries(payload).forEach(([date, sidMap]) => {
    if (!sidMap || typeof sidMap !== 'object') return;
    Object.entries(sidMap).forEach(([sid, records]) => {
      if (!Array.isArray(records)) return;
      records.forEach(record => {
        if (!record || typeof record !== 'object') return;
        rows.push({ ...record, sid: String(sid), date: String(date) });
      });
    });
  });
  return rows.sort((a, b) => recordCreatedAt(b).localeCompare(recordCreatedAt(a)));
}

export async function loadStudentTestRecords() {
  if (!recordsPromise) {
    recordsPromise = fetchJsonOr('/api/tests', {}, SAME_ORIGIN_NO_STORE).then(flattenTestsPayload);
  }
  return recordsPromise;
}

export function recordsForSid(records, sid) {
  const key = String(sid || '').trim();
  if (!key) return [];
  return records.filter(record => String(record.sid || '').trim() === key);
}

export async function loadRecordDetail(record) {
  const testId = recordTestId(record);
  if (!testId) return null;
  const params = new URLSearchParams({ test_id: testId, recent_days: DETAILS_DAYS });
  const payload = await fetchJsonOr(`/api/tests-records?${params.toString()}`, null, SAME_ORIGIN_NO_STORE);
  if (!payload || !Array.isArray(payload.records)) return null;
  const createdAt = recordCreatedAt(record);
  const sid = String(record.sid || '').trim();
  const detailRecord = payload.records.find(item =>
    String(item?.sid || '').trim() === sid &&
    String(item?.createdAt || '').trim() === createdAt
  ) || payload.records.find(item => String(item?.sid || '').trim() === sid);
  return { payload, detailRecord };
}
