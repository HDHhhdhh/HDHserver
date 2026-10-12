import { $ } from './utils.js';
export function initDarkmode() {
  const t = $('darkToggle');
  if (!t) return;
  try {
    if (localStorage.theme === 'dark') { document.body.classList.add('dark'); t.checked = true; }
  } catch {}
  t.addEventListener('change', () => {
    document.body.classList.toggle('dark', t.checked);
    try { localStorage.theme = t.checked ? 'dark' : 'light'; } catch {}
  });
}
