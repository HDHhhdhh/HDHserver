function escapeAttr(value) {
  return String(value ?? '').replace(/[&<>"']/g, (ch) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
  }[ch]));
}

function studentLabel(name, sid) {
  return String(name || sid || '학생').trim() || '학생';
}

export function renderTodayActionButtons({ sid = '', name = '', date = '', includeDoneActions = false } = {}) {
  const safeSid = escapeAttr(String(sid || '').trim());
  const label = studentLabel(name, sid);
  const safeLabel = escapeAttr(label);
  const safeDate = escapeAttr(String(date || '').trim());
  const groupLabel = includeDoneActions && safeDate
    ? `${safeLabel} ${safeDate} 작업`
    : `${safeLabel} 작업`;
  const doneActions = includeDoneActions
    ? `
      <button type="button" class="undoDone" title="하원 취소" aria-label="${safeLabel} 하원 취소">취소</button>
      <button type="button" class="clearDone" title="기록 정리" aria-label="${safeLabel} 기록 정리">정리</button>`
    : '';

  return `<div class="today-actions" role="group" aria-label="${groupLabel}">
      <button type="button" class="openStudentPopups" title="상담 기록" aria-label="${safeLabel} 상담 기록">상담</button>
      <button type="button" class="studentTestRecordBtn" data-test-result-sid="${safeSid}" data-test-result-name="${safeLabel}" title="테스트 기록 보기" aria-label="${safeLabel} 테스트 기록 보기">기록</button>
      <button type="button" class="markAbsent" title="결석 처리" aria-label="${safeLabel} 결석 처리">결석</button>
      <button type="button" class="markLeave" title="하원 처리" aria-label="${safeLabel} 하원 처리">하원</button>${doneActions}
    </div>`;
}

export function renderTodayDocumentButton({ docUrl = '', name = '', sid = '' } = {}) {
  const label = escapeAttr(studentLabel(name, sid));
  return `<button type="button" class="btn-doc" data-doc-url="${escapeAttr(docUrl)}" title="문서 열기" aria-label="${label} 문서 열기">📄</button>`;
}
