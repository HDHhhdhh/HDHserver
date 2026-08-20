const ESC_TARGET_SELECTOR = '[id$="Modal"],[role="dialog"],.modal,.popup,.dialog,#schoolTip,#adminSchoolTip';

function isVisible(el) {
  if (!el) return false;
  const style = getComputedStyle(el);
  if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
  const rect = el.getBoundingClientRect();
  return rect.width > 0 || rect.height > 0 || style.position === 'fixed';
}

function hasOpenEscTarget() {
  return Array.from(document.querySelectorAll(ESC_TARGET_SELECTOR)).some(isVisible);
}

function focusAllStudentSearch() {
  const input = document.getElementById('allStudentSearchInput');
  if (!input) return;
  input.value = '';
  input.dispatchEvent(new Event('input', { bubbles: true }));
  try { input.focus({ preventScroll: true }); }
  catch { input.focus(); }
  try { input.select(); } catch {}
}

document.addEventListener('keydown', (e) => {
  if (e.key !== 'Escape') return;

  const hadOpenTarget = hasOpenEscTarget();

  if (typeof window.closeStudentWorkPopups === 'function') {
    const logModal = document.getElementById('logModal');
    const vidModal = document.getElementById('vidModal');
    const unifiedOpen =
      logModal?.classList?.contains('student-work-layout') ||
      vidModal?.classList?.contains('student-work-layout');
    if (unifiedOpen) {
      window.closeStudentWorkPopups();
      return;
    }
  }

  if (!hadOpenTarget) {
    requestAnimationFrame(focusAllStudentSearch);
    return;
  }

  ['progModal', 'yoilModal', 'miniProgModal'].forEach((id) => {
    const modal = document.getElementById(id);
    if (!modal || modal.style.display === 'none') return;
    modal.style.display = 'none';
    if (id === 'miniProgModal') modal.dataset.sid = '';
  });
});
