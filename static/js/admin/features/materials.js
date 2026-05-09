/*
// 자료 업로드/삭제 + 표 렌더 (multi-file) — 커리큘럼 제거 버전
import { $, toast } from '../core/utils.js';
import { state } from '../core/state.js';

export function initMaterials(){
  // ▶ 파일 입력: 여러 개 선택 가능하도록 보장
  const fileInput = $('mFile');
  if (fileInput) fileInput.setAttribute('multiple', 'multiple');

  draw();

  $('upMat').onclick = async ()=>{
    const files = Array.from($('mFile').files || []);
    if (!files.length) return alert('업로드할 파일을 선택하세요.');

    const btn = $('upMat');
    btn.disabled = true;
    btn.textContent = '업로드 중...';

    let okCnt = 0, failCnt = 0;

    // 단일 파일 업로드 API(`/api/material-upload` -> field: 'file')를 순차 호출
    for (const file of files){
      const fd = new FormData();
      fd.append('file', file);
      // 서버 호환 위해 필드만 남기고 빈 값 전송 (서버가 옵션이면 무시됨)
      fd.append('curriculum', '');

      try {
        const res = await fetch('/api/material-upload', { method:'POST', body: fd });
        if (!res.ok) throw new Error(String(res.status));
        const m = await res.json();
        state.materials = m; // 서버가 최신 전체 맵을 돌려준다고 가정
        okCnt++;
      } catch(e){
        console.warn('upload failed:', file.name, e);
        failCnt++;
      }
    }

    draw();
    $('mFile').value = '';

    btn.disabled = false;
    btn.textContent = '업로드';

    if (okCnt && !failCnt) {
      toast(`${okCnt}개 업로드 완료`);
    } else if (okCnt && failCnt) {
      toast(`${okCnt}개 성공, ${failCnt}개 실패`);
      alert(`일부 파일 업로드 실패(${failCnt}개). 잠시 후 다시 시도해주세요.`);
    } else {
      toast('업로드 실패');
      alert('선택한 파일을 업로드하지 못했습니다.');
    }
  };

  $('matTable').addEventListener('click', (e)=>{
    if (!e.target.classList.contains('delMat')) return;
    const mid = e.target.closest('tr').dataset.mid;
    if (!confirm('이 자료를 삭제할까요?')) return;
    delete state.materials[mid];
    fetch('/api/materials', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify(state.materials)
    }).then(draw);
  });

  function draw(){
    // 커리 없이 제목 → id 순 정렬
    const rows = Object.entries(state.materials || {})
      .map(([mid,f])=>({ mid, ...f }))
      .sort((a,b)=> String(a.title||'').localeCompare(String(b.title||''), 'ko')
                    || (parseInt(a.id,10)||parseInt(a.mid,10)||0) - (parseInt(b.id,10)||parseInt(b.mid,10)||0))
      .map(f => `
        <tr data-mid="${f.id ?? f.mid}">
          <td><a href="${f.url}" target="_blank" rel="noopener">${f.title || ''}</a></td>
          <td style="white-space:nowrap">
            <button class="asBtn" title="학생 지정">👥</button>
            <button class="delMat" title="삭제">🗑</button>
          </td>
        </tr>`
      ).join('');

    $('matTable').innerHTML = `
      <thead><tr><th>파일</th><th>지정</th></tr></thead>
      <tbody>${rows}</tbody>`;
  }
}
*/