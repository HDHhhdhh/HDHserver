import { applySearchPlaceholder, matchesSearchKey, searchKeyForText } from './shared/search.js';

const toast = msg => {
    const d = document.createElement('div');
    d.textContent = msg;
    d.style.cssText =
        'position:fixed;bottom:20px;left:50%;' +
        'transform:translateX(-50%);background:#333;color:#fff;' +
        'padding:6px 12px;border-radius:4px;font-size:13px;z-index:9999';
    document.body.appendChild(d);
    setTimeout(() => d.remove(), 1500);
};

const $ = id => document.getElementById(id);

(function setupDarkMode() {
    const b = $('darkToggle');
    if (!b) return;
    // 초기 상태 적용
    if (localStorage.theme === 'dark') {
        document.body.classList.add('dark');
        b.checked = true;
    }
    // 토글 이벤트
    b.addEventListener('change', () => {
        if (b.checked) {
            document.body.classList.add('dark');
            localStorage.theme = 'dark';
        } else {
            document.body.classList.remove('dark');
            localStorage.theme = 'light';
        }
    });
})();

(() => {
    const CUR = ['공수1', '공수2', '미적분1', '미적분2', '대수', '기하', '확통'];
    const SUB = {
        '공수1': ['A:Ble', 'APEX'], '공수2': ['A:Ble', 'APEX'],
        '미적분1': ['A:Ble', 'APEX'], '미적분2': ['A:Ble', 'APEX'],
        '대수': ['A:Ble', 'APEX'], '기하': ['A:Ble', 'APEX'],
        '확통': ['A:Ble', 'APEX']
    };

    let videos = [];
    const CT = { "Content-Type": "application/json" };
    const vidTable = $('vidTable');
    const saveVidBtn = $('saveVid');

    function extractKollusMid(url) {
        const raw = String(url || '').trim();
        if (!raw) return '';

        try {
            const u = new URL(raw, location.origin);
            if (!/kollus\.com$/i.test(u.hostname) && !/\.kollus\.com$/i.test(u.hostname)) return '';

            for (const key of ['mid', 'm', 'media_content_key', 'MEDIA_CONTENT_KEY', 'content_key']) {
                const cand = String(u.searchParams.get(key) || '').trim();
                if (/^[A-Za-z0-9_-]+$/.test(cand)) return cand;
            }

            const parts = u.pathname.split('/').filter(Boolean);
            for (let i = parts.length - 1; i >= 0; i--) {
                const cand = String(parts[i] || '').trim();
                if (/^[A-Za-z0-9_-]+$/.test(cand)) return cand;
            }
        } catch {
            const m = raw.match(/kollus\.com\/([^?#/]+)/i);
            if (m && /^[A-Za-z0-9_-]+$/.test(m[1])) return m[1];
        }

        return '';
    }

    function init() {
        // ── 공통 커리큘럼 셀렉터 ──
        const opts = `<option value="">전체</option>` +
            CUR.map(c => `<option value="${c}">${c}</option>`).join('');

        // Video-Manage 페이지에서는 vCur만 있으면 됨
        const vCur = $('vCur');
        if (vCur) vCur.innerHTML = opts;

        // (만약 student 페이지나 admin 페이지도 같은 스크립트 쓰신다면)
        const curSel = $('curSel');
        if (curSel) curSel.innerHTML = opts;

        const mCur = $('mCur');
        if (mCur) mCur.innerHTML = opts;

        // ── 세부과정 셀렉터 ──
        const subVidSel = $('subVidSel');
        if (subVidSel) {
            subVidSel.innerHTML = '<option value="">세부과정 선택</option>';
            if (vCur) {
                vCur.addEventListener('change', e => {
                    const subs = SUB[e.target.value] || [];
                    subVidSel.innerHTML =
                        '<option value="">선택</option>' +
                        subs.map(s => `<option value="${s}">${s}</option>`).join('');
                });
            }
        }

        // ── 학생용 세부 (student.html 전용) ──
        const subCurSel = $('subCurSel');
        if (subCurSel && curSel) {
            subCurSel.innerHTML = '<option value="">세부과정 선택</option>';
            curSel.addEventListener('change', e => {
                const subs = SUB[e.target.value] || [];
                subCurSel.innerHTML =
                    '<option value="">선택</option>' +
                    subs.map(s => `<option value="${s}">${s}</option>`).join('');
            });
        }

        // ── 접기/보기 토글 ──
        const toggleVidBtn = $('toggleVid');
        const videoSection = $('videoSection');
        if (toggleVidBtn && videoSection) {
            toggleVidBtn.addEventListener('click', () => {
                const isHidden = videoSection.style.display === 'none';
                videoSection.style.display = isHidden ? '' : 'none';
                toggleVidBtn.textContent = isHidden ? '접기' : '보기';
            });
        }

        // ── 나머지 로직 ──
        drawVid();
    }
    init();

    // 공통 초기 로드
    Promise.all([
        fetch('/api/videos').then(r => r.json())
    ]).then(([vids]) => {
        videos = vids;
        drawVid();
    });

    /***** ───── 영상 관리 테이블 ───── */
    function drawVid() {
        const curEl = document.getElementById('curriculumFilter');
        const subEl = document.getElementById('subCurriculumFilter');
        const searchEl = document.getElementById('videoSearch');
        const curSel = curEl ? curEl.value : '';
        const subSel = subEl ? subEl.value : '';
        const queryText = searchEl ? searchEl.value : '';
        if (!vidTable) return;

        // ② videos 배열에서 필터 적용 (빈 값이면 전체)
        const list = videos
            .filter(v =>
                (!curSel || v.curriculum === curSel) &&
                (!subSel || v.subCurriculum === subSel) &&
                matchesSearchKey(searchKeyForText([
                    v.id,
                    v.curriculum,
                    v.subCurriculum,
                    v.chapter,
                    v.title,
                    v.url,
                    v.mid,
                    JSON.stringify(v.exNum || {}),
                ].join(' ')), queryText)
            )
            // ③ 커리큘럼→세부과정→챕터 순으로 정렬
            .sort((a, b) => {
                const cmpCurr = a.curriculum.localeCompare(b.curriculum, 'ko');
                if (cmpCurr !== 0) return cmpCurr;
                const cmpSub = (a.subCurriculum || '')
                    .localeCompare(b.subCurriculum || '', 'ko');
                if (cmpSub !== 0) return cmpSub;
                return a.chapter - b.chapter;
            });

        // ④ 테이블 헤더 + 본문 렌더
        vidTable.innerHTML = `
    <tr>
      <th style="width:40px">ID</th>
      <th style="width:70px">커리큘럼</th>
      <th style="width:100px">세부과정</th>
      <th style="width:40px">챕</th>
      <th style="width:50px">상</th>
      <th style="width:50px">중</th>
      <th style="width:50px">하</th>
      <th>제목</th>
      <th style="min-width:260px">URL</th>
      <th style="width:40px">Del</th>
    </tr>
    ${list.map(v => {
            const idx = videos.findIndex(x => x.id === v.id);
            return `
        <tr data-idx="${idx}">
          <td>${v.id}</td>
          <td>${v.curriculum}</td>
          <td>${v.subCurriculum || ''}</td>
          <td contenteditable>${v.chapter}</td>
          <td contenteditable>${v.exNum?.['상'] || ''}</td>
          <td contenteditable>${v.exNum?.['중'] || ''}</td>
          <td contenteditable>${v.exNum?.['하'] || ''}</td>
          <td contenteditable>${v.title}</td>
          <td contenteditable>${v.url}</td>
          <td><button class="delV">×</button></td>
        </tr>
      `;
        }).join('')}
  `;

        // ⑤ 삭제 버튼 처리
        vidTable.querySelectorAll('.delV').forEach(btn => {
            btn.addEventListener('click', e => {
                const tr = e.target.closest('tr');
                const i = +tr.dataset.idx;
                videos.splice(i, 1);
                drawVid();    // 다시 렌더
            });
        });

        // ⑥ 편집 셀 blur 시 자동 저장 (서버 POST)
        vidTable.querySelectorAll('td[contenteditable]').forEach(td => {
            td.addEventListener('blur', () => {
                const tr = td.closest('tr');
                const i = +tr.dataset.idx;
                const cells = tr.children;
                // 값 읽고 반영
                videos[i].chapter = +cells[3].innerText.trim() || 1;
                const exS = cells[4].innerText.trim();
                const exM = cells[5].innerText.trim();
                const exH = cells[6].innerText.trim();
                if (exS || exM || exH) {
                    videos[i].exNum = {};
                    if (exS) videos[i].exNum['상'] = +exS;
                    if (exM) videos[i].exNum['중'] = +exM;
                    if (exH) videos[i].exNum['하'] = +exH;
                } else {
                    delete videos[i].exNum;
                }
                videos[i].title = cells[7].innerText.trim();
                videos[i].url = cells[8].innerText.trim();
                const nextMid = extractKollusMid(videos[i].url);
                if (nextMid) videos[i].mid = nextMid;
                // 서버에 저장
                /*fetch('/api/videos', {
                  method:  'POST',
                  headers: CT,
                  body:    JSON.stringify(videos)
                }).then(() => toast('저장 완료'))
                  .catch(() => toast('저장 실패'));*/
            });
        });
    }



    const videoSection = document.getElementById('videoSection');  // 영상 관리 섹션 :contentReference[oaicite:2]{index=2}
    const maincurricula = [
        '공수1',
        '공수2',
        '대수',
        '미적분1',
        '미적분2',
        '기하',
        '확통'
    ];
    const subCurricula = [
        'A:Ble',
        'APEX'
    ];
    const filterDiv = document.createElement('div');
    filterDiv.style.margin = '0.5rem 0';
    filterDiv.innerHTML = `
  <input id="videoSearch" type="search" autocomplete="off" placeholder="영상 검색" style="min-width:240px;margin-right:1rem;">
  <label style="margin-right:0.5rem;">커리큘럼:</label>
  <select id="curriculumFilter" style="margin-right:1rem;">
   <option value="">전체</option>
   ${maincurricula.map(m => `<option value="${m}">${m}</option>`).join('')}
  </select>

  <label style="margin-right:0.5rem;">세부:</label>
  <select id="subCurriculumFilter">
   <option value="">전체</option>
   ${subCurricula.map(s => `<option value="${s}">${s}</option>`).join('')}
  </select>
`;
    videoSection.prepend(filterDiv);
    const videoSearch = document.getElementById('videoSearch');
    applySearchPlaceholder(videoSearch, '영상 검색');
    videoSearch?.addEventListener('input', drawVid);
    videoSearch?.addEventListener('search', drawVid);
    videoSearch?.addEventListener('compositionend', drawVid);
    videoSearch?.addEventListener('keydown', (ev) => {
        if (ev.key !== 'Escape') return;
        videoSearch.value = '';
        drawVid();
    });

    // 드롭다운 변경 시 drawVid() 재실행
    document.getElementById('curriculumFilter')
        .addEventListener('change', () => drawVid());
    document.getElementById('subCurriculumFilter')
        .addEventListener('change', drawVid);


    ; (function () {
        const addVidBtn = document.getElementById('addVid');
        if (!addVidBtn) return;

        addVidBtn.addEventListener('click', () => {
            // 1) 필수 요소 가져오기
            const vCurEl = document.getElementById('vCur');
            const subVidEl = document.getElementById('subVidSel');
            const exHighEl = document.getElementById('exNumHigh');
            const exMidEl = document.getElementById('exNumMid');
            const exLowEl = document.getElementById('exNumLow');
            const vChapEl = document.getElementById('vChap');
            const vTitleEl = document.getElementById('vTitle');
            const vUrlEl = document.getElementById('vUrl');

            // 유효성 검사
            if (!vCurEl.value) return alert('커리큘럼을 선택하세요.');
            if (!subVidEl.value) return alert('세부과정을 선택하세요.');
            if (!vTitleEl.value.trim()) return alert('제목을 입력하세요.');
            const fullUrl = vUrlEl.value.trim();
            const mid = extractKollusMid(fullUrl);
            if (!mid) return alert('유효한 Kollus URL이 아닙니다.');

            // 값 파싱
            const curriculum = vCurEl.value;
            const subCurriculum = subVidEl.value;
            const chapter = parseInt(vChapEl.value, 10) || 1;
            const title = vTitleEl.value.trim();

            // 새 영상 객체 생성 (exNum 프로퍼티만 포함)
            const newVid = {
                id: videos.length ? Math.max(...videos.map(v => v.id || 0)) + 1 : 1,
                mid,
                curriculum,
                subCurriculum,
                chapter,
                title,
                url: fullUrl,
                exNum: {}
            };
            if (exHighEl.value) newVid.exNum['상'] = parseInt(exHighEl.value, 10);
            if (exMidEl.value) newVid.exNum['중'] = parseInt(exMidEl.value, 10);
            if (exLowEl.value) newVid.exNum['하'] = parseInt(exLowEl.value, 10);

            if (Object.keys(newVid.exNum).length === 0) {
                delete newVid.exNum;
            }

            // 배열에 추가 + 테이블 갱신
            videos.push(newVid);
            drawVid();
        });
    })();



    /* 영상 저장 */
    saveVidBtn.onclick = () => {
        // ① 테이블 행 순회
        document.querySelectorAll('#vidTable tr[data-idx]').forEach(tr => {
            const i = +tr.dataset.idx;
            const cells = tr.children;

            // ② 각 칸에서 텍스트 읽기
            const chap = +cells[3].innerText.trim() || 1;
            const exS = cells[4].innerText.trim();
            const exM = cells[5].innerText.trim();
            const exH = cells[6].innerText.trim();
            const title = cells[7].innerText.trim();
            const url = cells[8].innerText.trim();

            videos[i].curriculum = cells[1].innerText.trim();
            videos[i].subCurriculum = cells[2].innerText.trim();

            // ③ videos 배열에 반영
            videos[i].chapter = chap;

            // exNum 객체 생성 / 삭제
            if (exS || exM || exH) {
                videos[i].exNum = {};
                if (exS) videos[i].exNum['상'] = +exS;
                if (exM) videos[i].exNum['중'] = +exM;
                if (exH) videos[i].exNum['하'] = +exH;
            } else {
                delete videos[i].exNum;
            }

            videos[i].title = title;
            videos[i].url = url;
            const nextMid = extractKollusMid(url);
            if (nextMid) videos[i].mid = nextMid;
        });

        // ④ 서버에 저장
        fetch('/api/videos', {
            method: 'POST',
            headers: CT,
            body: JSON.stringify(videos)
        })
            .then(() => toast('영상 저장 완료'));
    };

})();
