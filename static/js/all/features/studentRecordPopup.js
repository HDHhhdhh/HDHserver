import { state as adminState } from '../../admin/core/state.js';
import { initLogModal } from '../../admin/features/logModal.js?v=20260914-homework-open-stable1&whiteRetest=20260928&hubSave=20261001&testSaveReady=20261002&uiPerf=20261002&dragScroll=20261007';
import { initHoverTooltip as initAdminHoverTooltip } from '../../admin/features/hoverTooltip.js?v=20260906-exam-pending-color1';
import { initVideoModal } from '../../admin/features/videoModal.js?v=20260912-watch-rearm1&youtube=20260913&hubSave=20261001&uiPerf=20261002&dragScroll=20261007';
import { initAssistantStudentNotes } from '../../admin/features/assistantStudentNotes.js?v=20260821-note-body-row2';

const ADMIN_POPUP_STYLESHEETS = [
  '/css/main.css?v=20260417a',
  '/css/admin.css?v=20260527chat',
  '/css/student-work-light.css?v=20260906-exam-pending-color1',
];
const ADMIN_POPUP_STYLESHEET_MARKER = 'data-all-students-admin-popup-style';

let initialized = false;
let initializationPromise = null;
let adminPopupStylesheetPromise = null;
let popupOpeningDepth = 0;
let popupCloseObserver = null;
let readOnlyAssignmentGuardInstalled = false;

function loadAdminPopupStylesheets() {
  if (adminPopupStylesheetPromise) return adminPopupStylesheetPromise;

  adminPopupStylesheetPromise = Promise.all(ADMIN_POPUP_STYLESHEETS.map((href) => new Promise((resolve, reject) => {
    const existing = document.head.querySelector(
      `link[${ADMIN_POPUP_STYLESHEET_MARKER}][href="${href}"]`,
    );
    if (existing?.sheet) {
      resolve(existing);
      return;
    }

    const link = existing || document.createElement('link');
    link.rel = 'stylesheet';
    link.href = href;
    link.setAttribute(ADMIN_POPUP_STYLESHEET_MARKER, '');
    link.addEventListener('load', () => resolve(link), { once: true });
    link.addEventListener('error', () => reject(new Error(`admin popup stylesheet failed: ${href}`)), { once: true });
    if (!existing) document.head.append(link);
  }))).catch((error) => {
    document.head.querySelectorAll(`link[${ADMIN_POPUP_STYLESHEET_MARKER}]`).forEach(link => link.remove());
    adminPopupStylesheetPromise = null;
    throw error;
  });

  return adminPopupStylesheetPromise;
}

async function activateAdminPopupSkin() {
  await loadAdminPopupStylesheets();
  document.head.querySelectorAll('link[rel="stylesheet"][href^="/css/style.css"]').forEach((link) => {
    link.disabled = true;
    link.dataset.allStudentsBaseStyleSuspended = '1';
  });
  if (document.body.classList.contains('all-page')) {
    document.body.classList.remove('all-page');
    document.body.dataset.allPageClassSuspended = '1';
  }
  document.body.classList.add('admin');
  document.body.dataset.adminPopupSkin = '1';
}

function hasOpenUnifiedStudentPopup() {
  return Boolean(document.querySelector(
    '#vidModal.student-work-layout,'
    + '#logModal.student-work-layout,'
    + '#testModal.student-work-layout,'
    + '#adminSchoolTip.student-work-layout',
  ));
}

function releaseAdminPopupSkin() {
  if (document.body.dataset.adminPopupSkin !== '1') return;
  document.body.classList.remove('admin');
  delete document.body.dataset.adminPopupSkin;
  if (document.body.dataset.allPageClassSuspended === '1') {
    document.body.classList.add('all-page');
    delete document.body.dataset.allPageClassSuspended;
  }
  document.head.querySelectorAll(`link[${ADMIN_POPUP_STYLESHEET_MARKER}]`).forEach(link => link.remove());
  document.head.querySelectorAll('link[data-all-students-base-style-suspended="1"]').forEach((link) => {
    link.disabled = false;
    delete link.dataset.allStudentsBaseStyleSuspended;
  });
  adminPopupStylesheetPromise = null;
}

function releaseAdminPopupSkinWhenClosed() {
  if (popupOpeningDepth || hasOpenUnifiedStudentPopup()) return;
  releaseAdminPopupSkin();
}

function observeUnifiedPopupClose() {
  if (popupCloseObserver) return;
  popupCloseObserver = new MutationObserver(() => {
    queueMicrotask(releaseAdminPopupSkinWhenClosed);
  });
  popupCloseObserver.observe(document.body, {
    subtree: true,
    attributes: true,
    attributeFilter: ['class', 'style'],
  });
}

function installReadOnlyAssignmentGuard() {
  if (readOnlyAssignmentGuardInstalled) return;
  readOnlyAssignmentGuardInstalled = true;

  const mutationSelector = [
    '#vidModal.student-work-layout .vid-row',
    '#vidModal.student-work-layout .auto-count-btn',
    '#vidModal.student-work-layout .vid-exclude-high-btn',
    '#vidModal.student-work-layout #autoAssignCountRange',
    '#vidModal.student-work-layout .vid-extra-add',
    '#vidModal.student-work-layout .vid-extra-controls input',
    '#vidModal.student-work-layout .vid-extra-controls select',
    '#testModal.student-work-layout .test-save-btn',
    '#testModal.student-work-layout .test-row',
    '#testModal.student-work-layout .test-mini-actions button',
    '#testModal.student-work-layout .test-note-option input',
    '#logModal.student-work-layout .assistant-note-pin',
    '#logModal.student-work-layout .assistant-note-action-group',
    '#assistantStudentNotes[data-existing-read-only="true"] .assistant-note-pin',
    '#assistantStudentNotes[data-existing-read-only="true"] .assistant-note-action-group',
  ].join(',');
  const blockMutation = (event) => {
    const target = event.target?.closest?.(mutationSelector);
    if (!target) return;
    if (
      target.closest?.('#vidModal .vid-row')
      && (event.type === 'contextmenu' || (event.type === 'mousedown' && event.button === 2))
    ) return;
    event.preventDefault();
    event.stopImmediatePropagation();
  };
  ['click', 'input', 'change', 'mousedown', 'keydown', 'contextmenu'].forEach((type) => {
    document.addEventListener(type, blockMutation, true);
  });
}

async function initializeAllStudentsRecordPopup() {
  await activateAdminPopupSkin();
  try {
    initAdminHoverTooltip();
    initAssistantStudentNotes();
    initVideoModal();
    initLogModal();
    observeUnifiedPopupClose();
    installReadOnlyAssignmentGuard();

    const openAdminStudentPopups = window.openStudentPopupsForRow;
    window.openStudentPopupsForRow = async (...args) => {
      popupOpeningDepth += 1;
      try {
        await activateAdminPopupSkin();
        return await openAdminStudentPopups(...args);
      } finally {
        popupOpeningDepth -= 1;
        queueMicrotask(releaseAdminPopupSkinWhenClosed);
      }
    };
    initialized = true;
  } catch (error) {
    releaseAdminPopupSkin();
    throw error;
  }
}

export function initAllStudentsRecordPopup(allState) {
  adminState.students = allState.students;
  adminState.videos = allState.videos;
  adminState.progress = allState.progress;
  adminState.schoolCal = allState.schoolCal;
  adminState.homeworkBooksBySid = allState.homeworkBooksBySid;
  adminState.logs = adminState.logs || {};

  if (initialized) return Promise.resolve();
  if (!initializationPromise) {
    initializationPromise = initializeAllStudentsRecordPopup().catch((error) => {
      initializationPromise = null;
      throw error;
    });
  }
  return initializationPromise;
}
