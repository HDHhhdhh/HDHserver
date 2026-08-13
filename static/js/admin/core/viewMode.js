import { $ } from './utils.js';

const VIEW_MODE_KEY = 'admin.viewMode';
const SIMPLE_MODE = 'simple';
const FULL_MODE = 'full';

function readViewMode() {
  try {
    return localStorage.getItem(VIEW_MODE_KEY) === SIMPLE_MODE ? SIMPLE_MODE : FULL_MODE;
  } catch {
    return FULL_MODE;
  }
}

function writeViewMode(mode) {
  try {
    localStorage.setItem(VIEW_MODE_KEY, mode);
  } catch {}
}

function applyViewMode(mode) {
  const simple = mode === SIMPLE_MODE;
  document.body.classList.toggle('admin-simple', simple);
  document.body.dataset.adminViewMode = simple ? SIMPLE_MODE : FULL_MODE;

  const button = $('simpleModeToggle');
  if (button) {
    button.textContent = simple ? 'Full' : 'Simple';
    button.setAttribute('aria-pressed', simple ? 'true' : 'false');
    button.title = simple ? '전체 운영판 보기' : '오늘 학생만 보기';
  }

  document.dispatchEvent(new CustomEvent('admin:viewModeChanged', {
    detail: { mode: simple ? SIMPLE_MODE : FULL_MODE },
  }));
}

export function initAdminViewMode() {
  const button = $('simpleModeToggle');
  if (!button) return;

  applyViewMode(readViewMode());
  button.addEventListener('click', () => {
    const nextMode = document.body.classList.contains('admin-simple') ? FULL_MODE : SIMPLE_MODE;
    writeViewMode(nextMode);
    applyViewMode(nextMode);
  });
}
