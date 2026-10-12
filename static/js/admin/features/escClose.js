// /static/js/admin/features/escClose.js
export function initEscClose() {
  const ESC_TARGET_SELECTOR = '[id$="Modal"],[role="dialog"],.modal,.popup,.dialog,#schoolTip,#adminSchoolTip';
  const SEARCH_SELECTOR = 'input[type="search"],input[role="searchbox"]';
  const EDITABLE_SELECTOR = 'input:not([type="checkbox"]):not([type="radio"]),textarea,select,[contenteditable]:not([contenteditable="false"])';

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

  function clearSearch(input) {
    input.value = '';
    input.dispatchEvent(new Event('input', { bubbles: true }));
    try { input.focus({ preventScroll: true }); }
    catch { input.focus(); }
    try { input.select(); } catch {}
  }

  function focusTodaySearch(focusAtEscape) {
    if (document.activeElement !== focusAtEscape) return;
    if (hasOpenEscTarget() || document.activeElement?.matches?.(EDITABLE_SELECTOR)) return;
    const input = document.getElementById('todaySearchInput');
    if (!input) return;
    clearSearch(input);
    input.scrollIntoView({ behavior: 'smooth', block: 'center', inline: 'nearest' });
  }

  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape' || e.defaultPrevented) return;
    const input = e.target?.closest?.(SEARCH_SELECTOR) ||
      (document.activeElement?.matches?.(SEARCH_SELECTOR) ? document.activeElement : null);
    if (!input || input.disabled || input.readOnly || !isVisible(input)) return;
    e.stopImmediatePropagation();
    if (e.isComposing) return;
    e.preventDefault();
    clearSearch(input);
  }, true);

  function hide(el) {
    if (!el || getComputedStyle(el).display === 'none') return;
    const closeOwner = {
      extraModal: window.closeExtraAttendancePopup,
      attendModal: window.closeDateAttendancePopup,
      absentRegisterModal: window.closeAbsentRegistrationPopup,
      logModal: window.closeStudentWorkPopups,
      vidModal: window.closeVideoAssignmentPopup,
      testModal: window.closeTestAssignmentPopup,
    }[el.id];
    if (typeof closeOwner === 'function') {
      closeOwner();
      return;
    }
    el.style.display = 'none';
  }

  // 학생 툴팁(hoverTooltip.js) 강제 숨기기
  function hideStudentTipHard() {
    // 1) 전역 함수 있으면 상태까지 같이 리셋
    if (typeof window.hideStudentTooltip === 'function') {
      try {
        window.hideStudentTooltip();
      } catch (err) {
        console.warn('[escClose] hideStudentTooltip error', err);
      }
    }

    // 2) 혹시 모듈 내부 상태 문제로 인해 안 먹을 수도 있으니까
    //    DOM 기준으로 한 번 더 강제 숨김
    const tip = document.getElementById('adminSchoolTip');
    if (tip) {
      tip.style.display = 'none';
      tip.style.pointerEvents = 'none';
      tip.style.cursor = 'default';
    }
  }

  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape' || e.defaultPrevented || e.isComposing) return;
    if (window.isStudentPopupSavePending?.()) return;

    const hadOpenTarget = hasOpenEscTarget();

    if (typeof window.closeStudentWorkPopups === 'function') {
      const logModal = document.getElementById('logModal');
      const vidModal = document.getElementById('vidModal');
      const unifiedOpen =
        logModal?.classList?.contains('student-work-layout') ||
        vidModal?.classList?.contains('student-work-layout');
      if (unifiedOpen) {
        try {
          window.closeStudentWorkPopups();
          return;
        } catch (err) {
          console.warn('[escClose] closeStudentWorkPopups error', err);
        }
      }
    }

    if (!hadOpenTarget) {
      if (e.target?.closest?.(EDITABLE_SELECTOR) || document.activeElement?.matches?.(EDITABLE_SELECTOR)) return;
      const focusAtEscape = document.activeElement;
      requestAnimationFrame(() => focusTodaySearch(focusAtEscape));
      return;
    }

    // 학생 툴팁(로그 모달에서 띄운 고정 툴팁 포함) 먼저 닫기
    hideStudentTipHard();

    // 예전에 쓰던/다른 용도의 schoolTip도 같이 닫기 (기존 동작 유지)
    hide(document.getElementById('schoolTip'));

    // 모달/팝업 계열 전부 닫기
    document
      .querySelectorAll('[id$="Modal"],[role="dialog"],.modal,.popup,.dialog')
      .forEach((el) => {
        if (isVisible(el)) hide(el);
      });

    [
      'extraModal',
      'logModal',
      'vidModal',
      'stuModal',
      'attendModal',
      'selectionModal',
      'announceModal',
      'yoilModal',
      'progModal',
      'clinicModal',
      // schoolTip은 위에서 이미 처리
    ].forEach((id) => hide(document.getElementById(id)));
  });
}
