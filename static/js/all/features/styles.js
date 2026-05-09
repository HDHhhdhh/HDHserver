/* styles.js — 요일 입력/부교재/신규학생 바 스타일 */
(() => {
  const css = `
/* ───── 학생 목록 요일 입력칸 ───── */
#allWrap td > .dayInput {
  display:flex;
  gap:6px;
  justify-content:center;
}
#allWrap td > .dayInput > .dayInput {
  width:3.2rem;
  min-width:3.2rem;
  text-align:center;
  padding:0.3rem 0.5rem;
  box-sizing:border-box;
}

/* ───── 부교재 입력칸 ───── */
#allWrap .sbBox { display:flex; gap:8px; justify-content:center; }
#allWrap .subBookInput {
  height:36px; width:9rem; padding:0 14px; text-align:center;
  border:1px solid #cbd5e1; border-radius:14px; background:#f1f5f9;
}
body.dark #allWrap .subBookInput { background:#1e293b; color:#e2e8f0; }

/* ───── 신규 학생 입력 바(두 줄) ───── */
.ns-wrap {
  display:grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap:10px;
  padding:12px;
  margin:12px 0 16px;
  border-radius:14px;
  background:var(--card-light);
}
body.dark .ns-wrap { background:var(--card-dark); }

.ns-input {
  height:38px;
  padding:0 12px;
  border-radius:12px;
  border:1px solid #cbd5e1;
  background:#f1f5f9;
  color:#111827;
  font:14px/38px system-ui, "Noto Sans KR", sans-serif;
  box-sizing:border-box;
}
body.dark .ns-input {
  background:#1e293b; border-color:#334155; color:#e2e8f0;
}
.ns-input:focus {
  outline:none; border-color:var(--accent);
  box-shadow:0 0 0 3px rgba(59,130,246,.25);
}
body.dark .ns-input:focus {
  border-color:var(--accent-dark);
  box-shadow:0 0 0 3px rgba(96,165,250,.35);
}

/* 추가 버튼 */
.ns-btn {
  height:38px;
  padding:0 16px;
  border:none;
  border-radius:12px;
  background:#3b82f6;
  color:#fff;
  font-weight:600;
  cursor:pointer;
  grid-column: 1 / -1;   /* 버튼은 두 줄 전체 폭 차지 */
}
.ns-btn:hover { filter:brightness(.96); }
  `;
  const s = document.createElement('style');
  s.textContent = css;
  document.head.appendChild(s);
})();
