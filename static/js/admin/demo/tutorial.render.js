function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, ch => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
  }[ch]));
}

export function renderHelpCenter({ center, page, seen, onClose, onReset, onShowFeature }) {
  center.innerHTML = `
    <header class="admin-demo-help-head">
      <div>
        <p>기능 도움말</p>
        <h2>${escapeHtml(page.title)}</h2>
        <span>${escapeHtml(page.subtitle)}</span>
      </div>
      <button type="button" class="admin-demo-help-close" aria-label="도움말 닫기">닫기</button>
    </header>
    <div class="admin-demo-help-note">각 버튼이나 입력 영역을 처음 누르면 설명이 한 번만 표시됩니다.</div>
    <div class="admin-demo-help-list" role="list">
      ${page.features.map(feature => `
        <button type="button" data-demo-help-feature="${escapeHtml(feature.id)}" class="${seen.has(feature.id) ? 'is-seen' : ''}">
          <strong>${escapeHtml(feature.title)}</strong>
          <span>${escapeHtml(feature.body)}</span>
        </button>
      `).join('')}
    </div>
    <footer class="admin-demo-help-actions">
      <button type="button" data-demo-help-action="reset">처음 클릭 안내 다시 보기</button>
      <button type="button" data-demo-help-action="close">닫기</button>
    </footer>
  `;

  center.querySelector('.admin-demo-help-close')?.addEventListener('click', onClose);
  center.querySelector('[data-demo-help-action="close"]')?.addEventListener('click', onClose);
  center.querySelector('[data-demo-help-action="reset"]')?.addEventListener('click', onReset);
  center.querySelectorAll('[data-demo-help-feature]').forEach(button => {
    button.addEventListener('click', () => {
      const feature = page.features.find(item => item.id === button.dataset.demoHelpFeature);
      if (feature) onShowFeature(feature);
    });
  });
}

export function renderHelpPopover({ doc, feature, popoverClass, intentional, onClose }) {
  const popover = doc.createElement('section');
  popover.className = popoverClass;
  popover.setAttribute('role', 'dialog');
  popover.setAttribute('aria-modal', 'false');
  popover.setAttribute('aria-label', feature.title);
  popover.innerHTML = `
    <div class="admin-demo-help-popover-head">
      <p>${intentional ? '선택한 기능' : '처음 눌렀어요'}</p>
      <button type="button" class="admin-demo-help-close" aria-label="설명 닫기">닫기</button>
    </div>
    <h3>${escapeHtml(feature.title)}</h3>
    <p>${escapeHtml(feature.body)}</p>
    <footer>
      <button type="button" data-demo-help-action="ok">확인</button>
    </footer>
  `;
  popover.querySelector('.admin-demo-help-close')?.addEventListener('click', onClose);
  popover.querySelector('[data-demo-help-action="ok"]')?.addEventListener('click', onClose);
  return popover;
}
