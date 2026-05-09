import { $ } from './utils.js';
export function initDarkmode() {
  const t = $('darkToggle');
  if (!t) return;
  if (localStorage.theme === 'dark') { document.body.classList.add('dark'); t.checked = true; }
  t.addEventListener('change', () => {
    document.body.classList.toggle('dark', t.checked);
    localStorage.theme = t.checked ? 'dark' : 'light';
  });
}
