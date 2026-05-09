// announcements.js — 공지 만들기 + 수정/삭제 + 현황 보드
// main.js:  import { initAnnouncements } from './features/announcements.js';

export function initAnnouncements() {
  const $  = (id) => document.getElementById(id);
  const CT = { 'Content-Type': 'application/json' };

  const btnNew   = $('newAnnBtn');
  const btnSave  = $('annSave');
  const btnClose = $('annClose');
  const btnRef   = $('annRefresh');
  const modal    = $('annModal');
  const board    = $('annBoard');

  if (!btnNew || !btnSave || !btnClose || !modal || !board) return;

  // 편집 상태
  let editingId = null;
  let annCache = []; // 최근 /api/announcements 결과 저장 (수정 프리필 용)

  // ───────── 모달 열/닫기
  btnNew.addEventListener('click', () => openModal(null));
  btnClose.addEventListener('click', closeModal);
  modal.addEventListener('click', (e) => { if (e.target === modal) closeModal(); });

  function openModal(ann) {
    // ann === null → 새로 만들기, ann = 공지 객체 → 수정
    editingId = ann?.id || null;

    setVal('annTitle',   ann?.title   || '');
    setVal('annContent', ann?.content || '');

    // poll
    const poll = ann?.poll || null;
    setVal('pollQ',       poll?.question || '');
    setVal('pollOpts',    Array.isArray(poll?.options) ? poll.options.join('\n') : '');
    setChk('pollMulti',   !!poll?.multiple);

    // survey (텍스트 라인 + * = required)
    let surveyLines = '';
    if (Array.isArray(ann?.survey)) {
      surveyLines = ann.survey.map(q => q.label + (q.required ? '*' : '')).join('\n');
    }
    setVal('surveyLines', surveyLines);

    setChk('annRequire', !!ann?.requireCompletion);

    modal.style.display = 'flex';
  }
  function closeModal(){ modal.style.display = 'none'; editingId = null; }

  function setVal(id, v){ const el=$(id); if(el) el.value=v; }
  function setChk(id, v){ const el=$(id); if(el) el.checked=v; }

  // ───────── 저장(신규=POST / 수정=PUT)
  btnSave.addEventListener('click', async () => {
    const title  = $('annTitle')?.value.trim()   || '';
    const content= $('annContent')?.value.trim() || '';
    const pollQ  = $('pollQ')?.value.trim()      || '';
    const pollOptsRaw = $('pollOpts')?.value || '';
    const pollMulti   = !!$('pollMulti')?.checked;
    const surveyLines = $('surveyLines')?.value || '';
    const requireCompletion = !!$('annRequire')?.checked;

    if (!title) { alert('제목을 입력하세요.'); return; }

    // poll
    let poll = null;
    const pollOptions = pollOptsRaw.split(/\r?\n/).map(s => s.trim()).filter(Boolean);
    if (pollQ || pollOptions.length) {
      poll = { question: pollQ || '투표', options: pollOptions, multiple: !!pollMulti };
    }

    // survey: 한 줄 = 문항, 끝의 * = 필수
    let survey = [];
    surveyLines.split(/\r?\n/).map(s => s.trim()).filter(Boolean).forEach((line, idx) => {
      const required = /\*$/.test(line);
      const label = line.replace(/\*$/, '').trim();
      if (label) survey.push({ id:`q${idx+1}`, type:'text', label, required });
    });
    if (!survey.length) survey = null;

    const payload = {
      title, content,
      requireCompletion,
      targets: 'all',
      poll, survey
    };

    try {
      if (editingId) {
        // 수정
        const res = await fetch(`/api/announcements/${encodeURIComponent(editingId)}`, {
          method: 'PUT',
          headers: CT,
          body: JSON.stringify(payload)
        });
        if (!res.ok) throw new Error(await res.text());
        toast('공지 수정 완료');
      } else {
        // 신규
        const res = await fetch('/api/announcements', {
          method: 'POST',
          headers: CT,
          body: JSON.stringify({
            ...payload,
            createdAt: new Date().toISOString()
          })
        });
        if (!res.ok) throw new Error(await res.text());
        toast('공지 저장 완료');
      }
      closeModal();
      await loadAndRender();
    } catch (e) {
      console.error(e);
      alert('저장 실패');
    }
  });

  // ───────── 현황 보드
  btnRef?.addEventListener('click', loadAndRender);
  loadAndRender(); // 초기 1회

  async function loadAndRender() {
    try {
      // 통계와 내용 병합 (편집 프리필 위해 anns 별도 보관)
      const [stats, anns] = await Promise.all([
        fetch('/api/announce-status', { cache:'no-store' }).then(r=>r.json()),
        fetch('/api/announcements',   { cache:'no-store' }).then(r=>r.json())
      ]);
      annCache = Array.isArray(anns) ? anns : [];

      const byId = {};
      annCache.forEach(a => { if (a?.id) byId[a.id]=a; });

      const html = (Array.isArray(stats) ? stats : []).map(s => {
        const a = byId[s.id] || {};
        const view = {
          id: s.id,
          title: a.title ?? s.title ?? '',
          content: a.content ?? '',
          createdAt: a.createdAt ?? s.createdAt ?? '',
          requireCompletion: !!a.requireCompletion,
          targetsCount: s.targetsCount ?? 0,
          ackCount: s.ackCount ?? 0,
          hasPoll: !!s.hasPoll,
          poll: s.poll || null,
          hasSurvey: !!s.hasSurvey
        };
        return renderCard(view);
      }).join('') || emptyCard();
      board.innerHTML = html;
    } catch (e) {
      console.error(e);
      board.innerHTML = emptyCard('불러오지 못했습니다');
    }
  }

  // 카드 액션 위임 (수정/삭제)
  board.addEventListener('click', async (e) => {
    const card = e.target.closest('.ann-card');
    if (!card) return;
    const id = card.dataset.id;

    if (e.target.classList.contains('btn-edit')) {
      const ann = annCache.find(a => String(a.id) === String(id));
      if (!ann) return alert('공지 정보를 찾을 수 없습니다.');
      openModal(ann);
      return;
    }
    if (e.target.classList.contains('btn-del')) {
      if (!confirm('이 공지를 삭제할까요? (상태도 함께 정리됩니다)')) return;
      try {
        const res = await fetch(`/api/announcements/${encodeURIComponent(id)}`, { method: 'DELETE' });
        if (!res.ok) throw new Error(await res.text());
        toast('삭제 완료');
        await loadAndRender();
      } catch (err) {
        console.error(err); alert('삭제 실패');
      }
    }
  });

  // ───────── 렌더/헬퍼
  function renderCard(s) {
    const created = formatDate(s.createdAt);
    const reqBadge = s.requireCompletion ? `<span class="badge">완료필요</span>` : '';
    const pollBadge= s.hasPoll ? `<span class="badge">투표</span>` : '';
    const survBadge= s.hasSurvey ? `<span class="badge">설문</span>` : '';

    // 투표 막대
    let pollRows = '';
    let total = 0;
    if (s.hasPoll && s.poll && Array.isArray(s.poll.options)) {
      const options = s.poll.options || [];
      const counts  = s.poll.counts  || [];
      total = counts.reduce((a,b)=>a+Number(b||0), 0);
      pollRows = options.map((label, i) => {
        const cnt = Number(counts[i] || 0);
        const pct = total ? Math.round(cnt*100/total) : 0;
        return `
          <div class="opt">
            <div style="min-width:60px">${escapeHtml(label)}</div>
            <div class="bar"><i style="width:${pct}%"></i></div>
            <span style="font-size:12px">${cnt}표 (${pct}%)</span>
          </div>`;
      }).join('');
    }

    return `
      <div class="ann-card" data-id="${escapeAttr(s.id)}">
        <div style="display:flex;justify-content:space-between;align-items:center;gap:.5rem">
          <h4 style="margin:0">${escapeHtml(s.title || '제목 없음')}</h4>
          <div class="actions" style="display:flex;gap:.35rem">
            <button class="btn-edit"  title="수정">✏️</button>
            <button class="btn-del"   title="삭제">🗑️</button>
          </div>
        </div>
        <div class="ann-meta">${created} ${reqBadge} ${pollBadge} ${survBadge}</div>
        <div style="margin:.35rem 0 .25rem; white-space:pre-wrap;">${escapeHtml(s.content || '')}</div>
        <div class="ann-row">
          <div class="badge">확인: ${s.ackCount}/${s.targetsCount || '-'}</div>
          ${s.hasPoll ? `<span style="font-size:12px">${total}표</span>` : '<span style="font-size:12px;color:var(--muted)">&nbsp;</span>'}
        </div>
        ${pollRows}
      </div>`;
  }

  function emptyCard(text='등록된 공지 없음') {
    return `<div class="ann-card"><div class="ann-meta">${escapeHtml(text)}</div></div>`;
  }
  function toast(msg) {
    const d = document.createElement('div');
    d.textContent = msg;
    d.style.cssText =
      'position:fixed;bottom:18px;left:50%;transform:translateX(-50%);'+
      'background:#333;color:#fff;padding:6px 12px;border-radius:6px;font-size:13px;z-index:99999';
    document.body.appendChild(d); setTimeout(()=>d.remove(), 1300);
  }
  function escapeHtml(s) {
    return String(s ?? '').replace(/[&<>"']/g, m => ({
      '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
    }[m]));
  }
  function escapeAttr(s) {
    return escapeHtml(s).replace(/`/g, '&#96;');
  }
  function formatDate(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    if (Number.isNaN(d)) return String(iso);
    const mm = String(d.getMonth()+1).padStart(2,'0');
    const dd = String(d.getDate()).padStart(2,'0');
    const hh = String(d.getHours()).padStart(2,'0');
    const mi = String(d.getMinutes()).padStart(2,'0');
    return `${mm}/${dd} ${hh}:${mi}`;
  }
}
