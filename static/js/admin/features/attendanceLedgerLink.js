const DEFAULT_ATTENDANCE_LEDGER_URL = 'https://docs.google.com/spreadsheets/d/10cpoU0OxFx7DwGO3VBAFhPJx68kHIX_ugRzOong9IGs/edit?gid=1803596204#gid=1803596204';
const ATTENDANCE_LEDGER_STORAGE_KEY = 'admin.attendanceLedgerUrl';

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

  const savedUrl = normalizeLedgerUrl(window.localStorage.getItem(ATTENDANCE_LEDGER_STORAGE_KEY));
  link.href = savedUrl || DEFAULT_ATTENDANCE_LEDGER_URL;

  const editLedgerUrl = () => {
    const next = window.prompt('학원 출석부 링크를 입력하세요. 빈 값으로 저장하면 기본 링크로 돌아갑니다.', link.href);
    if (next == null) return;

    const normalized = normalizeLedgerUrl(next);
    if (!normalized) {
      window.alert('http 또는 https 링크만 저장할 수 있습니다.');
      return;
    }

    link.href = normalized;
    if (normalized === DEFAULT_ATTENDANCE_LEDGER_URL) {
      window.localStorage.removeItem(ATTENDANCE_LEDGER_STORAGE_KEY);
    } else {
      window.localStorage.setItem(ATTENDANCE_LEDGER_STORAGE_KEY, normalized);
    }
  };

  link.addEventListener('contextmenu', (event) => {
    event.preventDefault();
    editLedgerUrl();
  });

  settingsButton?.addEventListener('click', editLedgerUrl);
}
