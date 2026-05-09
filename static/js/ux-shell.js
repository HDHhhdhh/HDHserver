// /js/ux-shell.js
// 모든 페이지 공통: 톤&헤더&버튼&다크토글 + 약간의 레이아웃 보정(관리자/전체학생 자동 인식)
// - 중복 헤더 방지: .topbar 있으면 아무 것도 안 함
// - style.css 유지, 필요한 건 이 파일이 <style>로 "추가"만 함

(function () {
  if (document.querySelector('.topbar')) return; // 이미 있으면 종료

  // =============== 공통 CSS(인라인 추가) ===============
  const css = `
  :root{
    --bg:#0b1220; --panel:#0f172a; --border:#1e293b;
    --fg:#e5e7eb; --muted:#9ca3af; --accent:#3b82f6; --accent2:#60a5fa;
    --radius:14px; --shadow:0 10px 30px rgba(0,0,0,.25);
  }
  html, body { width:100%; min-height:100%; }
  body { background:var(--bg); color:var(--fg); }

  /* ── 상단바 ── */
  .topbar{
    position:sticky; top:0; z-index:1000;
    display:flex; gap:10px; align-items:center; justify-content:space-between;
    padding:14px 24px; background:rgba(15,23,42,.85); border-bottom:1px solid var(--border);
    backdrop-filter:saturate(120%) blur(6px);
  }
  .topbar h1{ margin:0; font-size:18px; display:flex; align-items:center; gap:8px; }
  .topbar a{ color:var(--fg); opacity:.95; text-decoration:none; padding:.35rem .6rem; border-radius:10px; }
  .topbar a:hover{ background:rgba(30,41,59,.6); }

  /* ── 버튼 톤(전역적으로 통일) ── */
  .btn{ background:#3b82f6; color:#fff; border:none; border-radius:10px; padding:.45rem .7rem; cursor:pointer; font:inherit; }
  .btn:hover{ filter:brightness(.95); }
  .btn.secondary{ background:#1f2937; color:#e5e7eb; border:1px solid #22304a; }
  .btn.pill{ border-radius:999px; padding:.35rem .8rem; font-weight:600; border:1px solid #22304a; background:#122034; color:#c7d2fe; }

  /* ── 다크 토글(가상요소 필요) ── */
  .switch{ position:relative; width:50px; height:26px; flex:0 0 auto }
  .switch input{ opacity:0; width:0; height:0 }
  .switch .slider{ position:absolute; inset:0; border-radius:9999px; background:#475569; transition:.25s }
  .switch .slider:before{ content:""; position:absolute; left:4px; top:4px; width:18px; height:18px; border-radius:50%; background:#fff; transition:.25s }
  .switch input:checked + .slider{ background:#3b82f6 }
  .switch input:checked + .slider:before{ transform:translateX(24px) }

  /* ── 표 기본 톤 ── */
  table{ width:100%; border-collapse:separate; border-spacing:0; }
  thead th{
    background:rgba(15,23,42,.6); color:#cbd5e1; font-weight:600;
    padding:8px 10px; text-align:left; border-bottom:1px solid var(--border); position:sticky; top:0; z-index:1;
  }
  tbody td{ padding:8px 10px; border-top:1px solid rgba(30,41,59,.6); }
  tbody tr:nth-child(odd){ background:rgba(15,23,42,.35); }
  tbody tr:nth-child(even){ background:rgba(15,23,42,.2); }
  tbody tr:hover{ background:rgba(30,41,59,.45); }

  /* ── 카드 ── */
  .card{ background:linear-gradient(180deg, rgba(15,23,42,.9), rgba(11,18,32,.92)); border:1px solid var(--border);
         border-radius:var(--radius); box-shadow:var(--shadow); padding:14px; }
  .card h2,.card h3{ margin:0 0 .6rem 0; font-size:16px; }

  /* ── 관리자 페이지 레이아웃(.page 있으면 자동 적용) ── */
  .page{
    width:100%; max-width:100vw; box-sizing:border-box;
    padding:20px 32px 28px;
    display:grid; grid-template-columns:minmax(0,1fr) 800px; gap:24px; align-items:start;
  }
  @media (max-width:1200px){ .page{ grid-template-columns:1fr; } }

  /* ── 모달 공통 ── */
  .modal-backdrop{ position:fixed; inset:0; background:rgba(0,0,0,.5); display:none; justify-content:center; align-items:center; z-index:10000; }
  .modal-panel{ position:relative; background:#0f172a; border:1px solid var(--border); color:var(--fg);
    padding:16px; border-radius:10px; max-width:420px; width:90%; max-height:80%; overflow:auto; box-shadow:var(--shadow); }

  /* ── all.html 보정: 요일 칸 조금 넓게 ── */
  #allWrap .dayInput{ width:3.4rem; min-width:3.4rem; text-align:center; }

  /* ── 진도 그리드(공용) ── */
  .progress-grid{ display:grid; grid-template-columns:repeat(auto-fill,minmax(60px,1fr)); gap:6px; }
  .progress-cell{ padding:6px; text-align:center; border:1px solid #334155; border-radius:6px; user-select:none; }
  .progress-cell[data-state="done"]{ background:#22c55e; color:#fff; }
  .progress-cell[data-state="interrupted"]{ background:#eab308; color:#111; }
  .progress-cell[data-state="skip"]{ background:#dc2626; color:#fff; }
  `;

  const style = document.createElement('style');
  style.id = 'ux-shell-style';
  style.textContent = css;
  document.head.appendChild(style);

  // =============== 상단바 주입 ===============
  // 페이지 타입 자동 인식
  const isAdmin = !!document.querySelector('#todayWrap');
  const isAll = !!document.querySelector('#allWrap');
  const title = isAdmin ? '관리자 페이지'
              : isAll   ? '전체 학생'
              : (document.title || '페이지');

  const rightNavHTML = `
    <a href="/video-manage" class="btn secondary" style="margin-right:6px">영상관리</a>
    <a href="/students">전체학생</a>
    <a href="/school-cal">학사일정</a>
    <a href="/tests">테스트관리</a>
    <a href="/file-manage">파일</a>
  `;

  const pillId = isAll ? 'allCount' : 'todayCount';
  const topbar = document.createElement('header');
  topbar.className = 'topbar';
  topbar.innerHTML = `
    <div style="display:flex; align-items:center; gap:12px">
      <h1 style="display:flex;align-items:center;gap:8px;margin:0">
        ${title}
        <span id="${pillId}" class="btn pill" style="line-height:1;height:28px;display:inline-flex;align-items:center">0명</span>
      </h1>
      ${isAdmin ? `<button id="extraBtn" class="btn">+ 보강</button>
                   <button id="exportLogs" class="btn secondary">내보내기</button>
                   <button id="exportTodayCsv" class="btn secondary">오늘 명단 다운로드</button>` : ``}
    </div>
    <nav aria-label="주요 링크">${rightNavHTML}</nav>
    <label class="switch" title="다크모드">
      <input type="checkbox" id="darkToggle">
      <span class="slider"></span>
    </label>
  `;
  document.body.insertBefore(topbar, document.body.firstChild);

  // =============== 다크모드 상태 복원 ===============
  const toggle = document.getElementById('darkToggle');
  if (localStorage.theme === 'dark') {
    document.body.classList.add('dark');
    toggle.checked = true;
  }
  toggle.addEventListener('change', () => {
    document.body.classList.toggle('dark', toggle.checked);
    localStorage.theme = toggle.checked ? 'dark' : 'light';
  });

  // =============== 작은 어댑터 ===============
  // 기존 페이지에서 상단에 이미 타이틀/버튼이 있다면, 이 pill 값은 JS에서 알아서 갱신될 것.
  // 예: admin/main.js 가 todayCount / allCount 를 갱신.

})();
