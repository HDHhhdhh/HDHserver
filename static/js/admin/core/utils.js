// 공통 유틸(토스트, 셀렉터, 에러훅 등)
export const $ = (id) => document.getElementById(id);
export const CT = { "Content-Type": "application/json" };
export const DEBUG = true;

export const toast = (msg) => {
  const d = document.createElement('div');
  d.textContent = msg;
  d.style.cssText = 'position:fixed;bottom:20px;left:50%;transform:translateX(-50%);' +
    'background:#333;color:#fff;padding:6px 12px;border-radius:4px;font-size:13px;z-index:9999';
  document.body.appendChild(d);
  setTimeout(() => d.remove(), 1500);
};

export async function postJSON(url, data, ctx = '') {
  const res = await fetch(url, { method: 'POST', headers: CT, body: JSON.stringify(data) });
  let bodyText = '';
  try { bodyText = await res.text(); } catch {}
  if (!res.ok) {
    const err = new Error(`POST ${url} failed ${res.status} ${res.statusText}`);
    err.status = res.status; err.body = bodyText; err.ctx = ctx;
    if (DEBUG) console.error('[POST ERROR]', { url, ctx, status: res.status, body: bodyText });
    throw err;
  }
  try { return bodyText ? JSON.parse(bodyText) : null; }
  catch { if (DEBUG) console.warn('[WARN] non‑JSON response from', url, bodyText); return bodyText; }
}

window.addEventListener('unhandledrejection', (e) => {
  if (DEBUG) console.error('[Promise rejection]', e.reason);
  alert(`처리 중 오류(비동기): ${e.reason?.message || e.reason}`);
});
window.addEventListener('error', (e) => {
  if (DEBUG) console.error('[Window error]', e.message, e.error);
});

// 날짜 키(로컬) 헬퍼
export function todayLocalKey() {
  const now = new Date();
  return new Date(now.getTime() - now.getTimezoneOffset() * 60000)
    .toISOString().slice(0, 10);
}
