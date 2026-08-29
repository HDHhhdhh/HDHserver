import { $, toast } from '../core/utils.js';
import { getAdminDate } from '../core/adminDate.js';
import { sendJson } from '../../shared/api.js';
import { downloadTextFile } from '../../shared/download.js?v=20260828-1';
import {
  QUICK_PRINTER_TIME_GROUPS,
  QUICK_PRINTER_TIME_GROUP_VALUES,
  collectQuickPrinterStudents,
  filterQuickPrinterStudentIds,
  formatQuickPrinterExportIssues,
  summarizeQuickPrinterTimeGroups,
} from './quickPrinterExportContract.js?v=20260829-time-filter1';

const QUICK_PRINTER_EXPORT_URL = '/api/tests/quick-printer-export';
const TIME_GROUP_CONTROLS = [
  {
    key: QUICK_PRINTER_TIME_GROUPS.SLOT1,
    inputId: 'quickPrinterTimeSlot1',
    countId: 'quickPrinterTimeSlot1Count',
  },
  {
    key: QUICK_PRINTER_TIME_GROUPS.CONSECUTIVE,
    inputId: 'quickPrinterTimeConsecutive',
    countId: 'quickPrinterTimeConsecutiveCount',
  },
  {
    key: QUICK_PRINTER_TIME_GROUPS.SLOT2,
    inputId: 'quickPrinterTimeSlot2',
    countId: 'quickPrinterTimeSlot2Count',
  },
];

let initialized = false;

async function createQuickPrinterCsv({ dateStr, studentIds, signal }) {
  const response = await sendJson(
    QUICK_PRINTER_EXPORT_URL,
    { date: dateStr, studentIds },
    { cache: 'no-store', credentials: 'same-origin', signal },
  );
  const payload = await response.json().catch(() => ({}));
  if (!response.ok || payload?.ok !== true) {
    return {
      ok: false,
      payload,
      message: formatQuickPrinterExportIssues(payload),
    };
  }
  if (typeof payload.csv !== 'string' || !payload.csv.startsWith('\uFEFF') || !payload.filename) {
    throw new Error('서버가 올바른 UTF-8 BOM CSV를 반환하지 않았습니다.');
  }

  downloadTextFile(payload.filename, payload.csv, 'text/csv;charset=utf-8');
  return { ok: true, payload };
}

function showExportFailure(result) {
  const summary = String(result?.payload?.message || '테스트 인쇄 CSV 생성 실패');
  toast(summary);
  if (Array.isArray(result?.payload?.issues) && result.payload.issues.length) {
    window.alert(result.message);
  }
}

async function exportWithoutDialog(button) {
  const dateStr = String(getAdminDate() || '').trim();
  const students = collectQuickPrinterStudents(document, dateStr);
  const studentIds = filterQuickPrinterStudentIds(students, QUICK_PRINTER_TIME_GROUP_VALUES);
  if (!studentIds.length) {
    toast('현재 운영판에 내보낼 학생이 없습니다.');
    return;
  }

  const previousText = button.textContent;
  button.disabled = true;
  button.textContent = 'CSV 생성 중...';
  try {
    const result = await createQuickPrinterCsv({ dateStr, studentIds });
    if (!result.ok) {
      showExportFailure(result);
      return;
    }
    toast(`테스트 인쇄 CSV ${Number(result.payload.rowCount) || 0}행 내보내기 완료`);
  } catch (error) {
    console.error('[quickPrinterExport] failed:', error);
    toast('테스트 인쇄 CSV 생성 실패');
    window.alert(`테스트 인쇄 CSV를 만들지 못했습니다.\n${error?.message || error}`);
  } finally {
    button.disabled = false;
    button.textContent = previousText;
  }
}

export function initQuickPrinterExport() {
  if (initialized) return;
  initialized = true;

  const button = $('exportQuickPrinterTests');
  if (!button) return;

  const modal = $('quickPrinterExportModal');
  const form = $('quickPrinterExportForm');
  const closeButton = $('quickPrinterExportClose');
  const cancelButton = $('quickPrinterExportCancel');
  const selectAllButton = $('quickPrinterExportSelectAll');
  const submitButton = $('quickPrinterExportSubmit');
  const dateLabel = $('quickPrinterExportDate');
  const status = $('quickPrinterExportStatus');
  const controls = TIME_GROUP_CONTROLS.map(meta => ({
    ...meta,
    input: $(meta.inputId),
    count: $(meta.countId),
  }));

  const dialogReady = !!(
    modal && form && closeButton && cancelButton && selectAllButton && submitButton &&
    dateLabel && status && controls.every(item => item.input && item.count)
  );
  if (!dialogReady) {
    button.addEventListener('click', () => exportWithoutDialog(button));
    return;
  }

  let activeDate = '';
  let activeStudents = [];
  let activeCounts = summarizeQuickPrinterTimeGroups([]);
  let currentGroups = new Set(QUICK_PRINTER_TIME_GROUP_VALUES);
  let exportInFlight = false;
  let activeController = null;
  let restoreFocus = null;

  function setStatus(message = '', kind = '') {
    status.textContent = message;
    status.classList.toggle('is-error', kind === 'error');
    status.classList.toggle('is-success', kind === 'success');
  }

  function readSelectedGroups() {
    return controls.filter(item => item.input.checked).map(item => item.key);
  }

  function selectedStudentIds() {
    return filterQuickPrinterStudentIds(activeStudents, readSelectedGroups());
  }

  function updateSelectionStatus() {
    const selectedCount = selectedStudentIds().length;
    setStatus(`${activeDate} · ${selectedCount}명 선택 / 전체 ${activeStudents.length}명`);
  }

  function setBusy(busy) {
    exportInFlight = busy;
    modal.setAttribute('aria-busy', busy ? 'true' : 'false');
    button.disabled = busy;
    selectAllButton.disabled = busy;
    submitButton.disabled = busy;
    submitButton.textContent = busy ? 'CSV 생성 중…' : '선택 타임 CSV 내보내기';
    controls.forEach(item => {
      item.input.disabled = busy || Number(activeCounts[item.key] || 0) === 0;
    });
  }

  function closeDialog() {
    if (exportInFlight) activeController?.abort();
    modal.style.display = 'none';
    modal.hidden = true;
    document.body.classList.remove('quick-printer-export-open');
    setStatus();
    const target = restoreFocus;
    restoreFocus = null;
    if (target?.focus) requestAnimationFrame(() => target.focus());
  }

  function openDialog() {
    if (exportInFlight) return;
    const dateStr = String(getAdminDate() || '').trim();
    const students = collectQuickPrinterStudents(document, dateStr);
    if (!students.length) {
      toast('현재 운영판에 내보낼 학생이 없습니다.');
      return;
    }

    restoreFocus = document.activeElement;
    activeDate = dateStr;
    activeStudents = students;
    activeCounts = summarizeQuickPrinterTimeGroups(activeStudents);
    dateLabel.textContent = activeDate;

    controls.forEach(item => {
      const count = Number(activeCounts[item.key] || 0);
      item.count.textContent = `${count}명`;
      item.input.disabled = count === 0;
      item.input.checked = count > 0 && currentGroups.has(item.key);
      item.input.closest('.quick-printer-time-option')?.classList.toggle('is-empty', count === 0);
    });
    if (!readSelectedGroups().length) {
      controls.forEach(item => {
        if (!item.input.disabled) item.input.checked = true;
      });
      currentGroups = new Set(readSelectedGroups());
    }

    updateSelectionStatus();
    modal.hidden = false;
    modal.style.display = 'flex';
    document.body.classList.add('quick-printer-export-open');
    requestAnimationFrame(() => {
      (controls.find(item => item.input.checked && !item.input.disabled)?.input || submitButton).focus();
    });
  }

  button.addEventListener('click', openDialog);
  closeButton.addEventListener('click', closeDialog);
  cancelButton.addEventListener('click', closeDialog);
  selectAllButton.addEventListener('click', () => {
    controls.forEach(item => {
      if (!item.input.disabled) item.input.checked = true;
    });
    currentGroups = new Set(readSelectedGroups());
    updateSelectionStatus();
  });
  controls.forEach(item => {
    item.input.addEventListener('change', () => {
      currentGroups = new Set(readSelectedGroups());
      updateSelectionStatus();
    });
  });
  modal.addEventListener('click', event => {
    if (event.target === modal) closeDialog();
  });
  modal.addEventListener('keydown', event => {
    if (event.key === 'Escape') {
      event.preventDefault();
      event.stopPropagation();
      closeDialog();
      return;
    }
    if (event.key !== 'Tab') return;
    const focusable = Array.from(
      modal.querySelectorAll('button:not([disabled]), input:not([disabled])'),
    ).filter(element => !element.hidden && element.offsetParent !== null);
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  });
  document.addEventListener('focusin', event => {
    if (modal.hidden || modal.contains(event.target)) return;
    submitButton.focus();
  });

  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (exportInFlight) return;

    const studentIds = selectedStudentIds();
    if (!studentIds.length) {
      setStatus('내보낼 타임을 하나 이상 선택해 주세요.', 'error');
      controls.find(item => !item.input.disabled)?.input.focus();
      return;
    }

    currentGroups = new Set(readSelectedGroups());
    const controller = new AbortController();
    activeController = controller;
    setBusy(true);
    setStatus(`${activeDate} 테스트 인쇄 CSV를 준비하고 있습니다.`);
    let closeAfterExport = false;
    try {
      const result = await createQuickPrinterCsv({
        dateStr: activeDate,
        studentIds,
        signal: controller.signal,
      });
      if (!result.ok) {
        showExportFailure(result);
        setStatus(String(result.payload?.message || '테스트 인쇄 CSV 생성 실패'), 'error');
        return;
      }

      const rowCount = Number(result.payload.rowCount) || 0;
      toast(`테스트 인쇄 CSV ${rowCount}행 내보내기 완료`);
      setStatus(`${studentIds.length}명 · ${rowCount}행 CSV를 내려받았습니다.`, 'success');
      closeAfterExport = true;
    } catch (error) {
      if (error?.name !== 'AbortError') {
        console.error('[quickPrinterExport] failed:', error);
        toast('테스트 인쇄 CSV 생성 실패');
        setStatus(error?.message || '테스트 인쇄 CSV 생성 실패', 'error');
        window.alert(`테스트 인쇄 CSV를 만들지 못했습니다.\n${error?.message || error}`);
      }
    } finally {
      if (activeController === controller) activeController = null;
      setBusy(false);
      if (closeAfterExport && !modal.hidden) closeDialog();
    }
  });
}
