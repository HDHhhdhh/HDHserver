import { $, toast } from '../core/utils.js';
import { getAdminDate } from '../core/adminDate.js';
import { sendJson } from '../../shared/api.js';
import { downloadTextFile } from '../../shared/download.js?v=20260828-1';
import {
  QUICK_PRINTER_TIME_GROUPS,
  QUICK_PRINTER_TIME_GROUP_VALUES,
  collectQuickPrinterStudents,
  filterQuickPrinterStudentIds,
  formatQuickPrinterAutomaticExclusion,
  formatQuickPrinterExportIssues,
  isQuickPrinterDownloadPayload,
  summarizeQuickPrinterTimeGroups,
} from './quickPrinterExportContract.js?v=20260830-carryover-history1';

const QUICK_PRINTER_EXPORT_URL = '/api/tests/quick-printer-export';
const QUICK_PRINTER_PREVIEW_URL = '/api/tests/quick-printer-export/preview';
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

async function requestQuickPrinter({ url, dateStr, studentIds, includeReprints = false, signal }) {
  const response = await sendJson(
    url,
    {
      date: dateStr,
      studentIds,
      includePreviouslyExportedCarryovers: includeReprints,
    },
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
  return { ok: true, payload };
}

async function previewQuickPrinterCsv({ dateStr, studentIds, includeReprints = false, signal }) {
  return requestQuickPrinter({
    url: QUICK_PRINTER_PREVIEW_URL,
    dateStr,
    studentIds,
    includeReprints,
    signal,
  });
}

async function createQuickPrinterCsv({ dateStr, studentIds, includeReprints = false, signal }) {
  const result = await requestQuickPrinter({
    url: QUICK_PRINTER_EXPORT_URL,
    dateStr,
    studentIds,
    includeReprints,
    signal,
  });
  if (!result.ok) return result;
  const { payload } = result;
  if (!isQuickPrinterDownloadPayload(payload)) {
    throw new Error('서버가 올바른 UTF-8 BOM CSV를 반환하지 않았습니다.');
  }

  downloadTextFile(payload.filename, payload.csv, 'text/csv;charset=utf-8');
  return result;
}

function showExportFailure(result) {
  const summary = String(result?.payload?.message || '테스트 인쇄 CSV 생성 실패');
  toast(summary);
  if (
    result?.payload?.code !== 'no_new_assignments_after_carryover_exclusion' &&
    Array.isArray(result?.payload?.issues) && result.payload.issues.length
  ) {
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
  const exclusionSummary = $('quickPrinterCarryoverExclusionSummary');
  const includeReprintsInput = $('quickPrinterIncludeReprints');
  const status = $('quickPrinterExportStatus');
  const controls = TIME_GROUP_CONTROLS.map(meta => ({
    ...meta,
    input: $(meta.inputId),
    count: $(meta.countId),
  }));

  const dialogReady = !!(
    modal && form && closeButton && cancelButton && selectAllButton && submitButton &&
    dateLabel && exclusionSummary && includeReprintsInput && status &&
    controls.every(item => item.input && item.count)
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
  let previewController = null;
  let previewSequence = 0;
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

  async function refreshPreview() {
    const studentIds = selectedStudentIds();
    const includeReprints = Boolean(includeReprintsInput.checked);
    const sequence = ++previewSequence;
    previewController?.abort();
    if (!studentIds.length) {
      exclusionSummary.textContent = formatQuickPrinterAutomaticExclusion({}, includeReprints);
      setStatus('내보낼 타임을 하나 이상 선택해 주세요.', 'error');
      return;
    }

    const controller = new AbortController();
    previewController = controller;
    exclusionSummary.textContent = '결석 이월 재배정 자동 제외: 확인 중…';
    try {
      const result = await previewQuickPrinterCsv({
        dateStr: activeDate,
        studentIds,
        includeReprints,
        signal: controller.signal,
      });
      if (sequence !== previewSequence || modal.hidden) return;
      if (!result.ok) {
        exclusionSummary.textContent = formatQuickPrinterAutomaticExclusion(result.payload, includeReprints);
        setStatus(String(result.payload?.message || '내보내기 대상을 확인할 수 없습니다.'), 'error');
        return;
      }
      exclusionSummary.textContent = formatQuickPrinterAutomaticExclusion(result.payload, includeReprints);
      const rowCount = Math.max(0, Number(result.payload?.rowCount) || 0);
      if (!rowCount) {
        setStatus(String(result.payload?.message || '내보낼 새 테스트가 없습니다.'), 'error');
        return;
      }
      setStatus(`${activeDate} · ${studentIds.length}명 선택 / 전체 ${activeStudents.length}명 · CSV ${rowCount}행`);
    } catch (error) {
      if (error?.name === 'AbortError' || sequence !== previewSequence) return;
      console.error('[quickPrinterExport] preview failed:', error);
      exclusionSummary.textContent = '결석 이월 재배정 자동 제외: 확인 실패';
      setStatus(error?.message || '내보내기 대상을 확인할 수 없습니다.', 'error');
    } finally {
      if (previewController === controller) previewController = null;
    }
  }

  function setBusy(busy) {
    exportInFlight = busy;
    modal.setAttribute('aria-busy', busy ? 'true' : 'false');
    button.disabled = busy;
    selectAllButton.disabled = busy;
    submitButton.disabled = busy;
    includeReprintsInput.disabled = busy;
    submitButton.textContent = busy ? 'CSV 생성 중…' : '선택 타임 CSV 내보내기';
    controls.forEach(item => {
      item.input.disabled = busy || Number(activeCounts[item.key] || 0) === 0;
    });
  }

  function closeDialog() {
    if (exportInFlight) activeController?.abort();
    previewController?.abort();
    previewController = null;
    previewSequence += 1;
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
    includeReprintsInput.checked = true;

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
    refreshPreview();
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
    refreshPreview();
  });
  controls.forEach(item => {
    item.input.addEventListener('change', () => {
      currentGroups = new Set(readSelectedGroups());
      updateSelectionStatus();
      refreshPreview();
    });
  });
  includeReprintsInput.addEventListener('change', refreshPreview);
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
        includeReprints: Boolean(includeReprintsInput.checked),
        signal: controller.signal,
      });
      if (!result.ok) {
        showExportFailure(result);
        setStatus(String(result.payload?.message || '테스트 인쇄 CSV 생성 실패'), 'error');
        return;
      }

      const rowCount = Number(result.payload.rowCount) || 0;
      exclusionSummary.textContent = formatQuickPrinterAutomaticExclusion(
        result.payload,
        Boolean(includeReprintsInput.checked),
      );
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
