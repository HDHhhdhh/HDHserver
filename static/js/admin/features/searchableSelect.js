import { loadToolkitLibrary } from './toolkitLibraries.js';
import { matchesSearchText, SEARCH_HELP_TEXT } from '../../shared/search.js';

const pending = new WeakMap();

export function enhanceVideoSelect(select) {
  if (!select) return;
  if (!document.getElementById('adminSearchableSelectStyles')) {
    const style = document.createElement('link'); style.id = 'adminSearchableSelectStyles';
    style.rel = 'stylesheet'; style.href = '/css/admin-searchable-select.css'; document.head.append(style);
  }
  if (select.tomselect) {
    select.tomselect.sync();
    select.disabled ? select.tomselect.disable() : select.tomselect.enable();
    return;
  }
  if (pending.has(select)) return;
  const job = loadToolkitLibrary('tomSelect').then(TomSelect => {
    if (!select.isConnected || select.tomselect) return;
    new TomSelect(select, {
      create: false, maxItems: 1, maxOptions: 100,
      allowEmptyOption: false, placeholder: `영상 검색 · ${SEARCH_HELP_TEXT}`,
      score: query => item => matchesSearchText(item.text, query) ? 1 : 0,
      render: {
        no_results: () => '<div class="no-results">일치하는 영상이 없습니다.</div>',
      },
      onInitialize() {
        this.control_input.removeAttribute('aria-labelledby');
        this.control_input.setAttribute('aria-label', '공지 영상 검색');
        this.control_input.setAttribute('title', SEARCH_HELP_TEXT);
        this.dropdown_content.removeAttribute('aria-labelledby');
        this.dropdown_content.setAttribute('aria-label', '영상 검색 결과');
      },
    });
    if (select.disabled) select.tomselect.disable();
  }).catch(error => console.warn('[announcement] searchable select unavailable:', error.message))
    .finally(() => pending.delete(select));
  pending.set(select, job);
}
