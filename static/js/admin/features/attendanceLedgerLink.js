import { ensureOk, fetchJsonChecked, sendJson } from '../../shared/api.js';

const DEFAULT_ATTENDANCE_LEDGER_URL = 'https://docs.google.com/spreadsheets/d/1KeNedUJtZRTMsSPOQh__RMQF9vwzbzzEkjlAucn5Hfs/edit?gid=1803596204#gid=1803596204';
const ATTENDANCE_LEDGER_STORAGE_KEY = 'admin.attendanceLedgerUrl';
const RETIRED_ATTENDANCE_LEDGER_URLS = new Set([
  'https://docs.google.com/spreadsheets/d/10cpoU0OxFx7DwGO3VBAFhPJx68kHIX_ugRzOong9IGs/edit?gid=1803596204#gid=1803596204',
]);

function normalizeLedgerUrl(value) {
  const raw = String(value || '').trim();
  if (!raw) return DEFAULT_ATTENDANCE_LEDGER_URL;
  try {
    const url = new URL(raw);
    return (url.protocol === 'http:' || url.protocol === 'https:') ? url.href : '';
  } catch {
    return '';
  }
}

export function getAttendanceLedgerUrl() {
  const link = document.getElementById('attendanceLedgerLink');
  return normalizeLedgerUrl(link?.href || window.localStorage.getItem(ATTENDANCE_LEDGER_STORAGE_KEY));
}

export function initAttendanceLedgerLink() {
  const link = document.getElementById('attendanceLedgerLink');
  if (!link) return;
  const settingsButton = document.getElementById('attendanceLedgerSettings');

  const storedValue = window.localStorage.getItem(ATTENDANCE_LEDGER_STORAGE_KEY);
  const savedUrl = storedValue ? normalizeLedgerUrl(storedValue) : '';
  if (RETIRED_ATTENDANCE_LEDGER_URLS.has(savedUrl)) {
    window.localStorage.removeItem(ATTENDANCE_LEDGER_STORAGE_KEY);
  }
  link.href = savedUrl && !RETIRED_ATTENDANCE_LEDGER_URLS.has(savedUrl)
    ? savedUrl
    : DEFAULT_ATTENDANCE_LEDGER_URL;

  fetchJsonChecked(
    '/api/makeup-sheet-sync/config',
    '시트 설정 조회',
    { cache: 'no-store' },
  ).then((data) => {
    const configured = normalizeLedgerUrl(data?.sheetUrl);
    if (!configured) return;
    link.href = configured;
    window.localStorage.setItem(ATTENDANCE_LEDGER_STORAGE_KEY, configured);
  }).catch((error) => {
    console.warn('[attendance-ledger] config load failed', error);
  });

  const editLedgerUrl = async () => {
    const next = window.prompt('학원 출석부 링크를 입력하세요. 빈 값으로 저장하면 기본 링크로 돌아갑니다.', link.href);
    if (next == null) return;

    const normalized = normalizeLedgerUrl(next);
    if (!normalized) {
      window.alert('http 또는 https 링크만 저장할 수 있습니다.');
      return;
    }

    try {
      const response = await sendJson('/api/makeup-sheet-sync/config', { sheetUrl: normalized });
      await ensureOk(response, '시트 설정 저장');
      const data = await response.json();
      const configured = normalizeLedgerUrl(data?.sheetUrl);
      if (!configured) throw new Error('저장된 시트 링크가 올바르지 않습니다.');
      link.href = configured;
      window.localStorage.setItem(ATTENDANCE_LEDGER_STORAGE_KEY, configured);
    } catch (error) {
      console.error(error);
      window.alert('시트 링크를 서버에 저장하지 못했습니다.');
    }
  };

  link.addEventListener('contextmenu', (event) => {
    event.preventDefault();
    editLedgerUrl();
  });

  settingsButton?.addEventListener('click', editLedgerUrl);
}
