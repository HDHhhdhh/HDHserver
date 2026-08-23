import { applySearchPlaceholder, matchesSearchKey, searchKeyForText } from './shared/search.js';
import { nextVideoId } from './shared/videoIds.js';
import { buildVideoCorrectionDraft, protectedVideoIdentityChanges, videoCorrectionSummary } from './shared/videoCatalogIdentity.js';

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
    const correctionModeBtn = $('videoCorrectionMode');
    const correctionDownloadBtn = $('videoCorrectionDownload');
    const correctionCancelBtn = $('videoCorrectionCancel');
    const correctionStatus = $('videoCorrectionStatus');
    let autoSaveTimer = null;
    let autoSaveClick = false;
    let lastSavedVideoBody = '';
    let saveInFlight = false;
    let queuedSaveMode = null;
    let correctionMode = false;
    let correctionBaseVideos = null;
    const VIDEO_IDENTITY_CHANGE_ERROR = 'video_catalog_identity_change_blocked';
    const VIDEO_SAFETY_DEFAULT_MESSAGE = '일반 모드 보호: 제목·챕터·같은 MID의 서명 URL 보정과 새 영상 추가는 가능하지만, 기존 영상의 MID 변경과 삭제는 저장되지 않습니다.';
    const VIDEO_CORRECTION_MESSAGE = '수정 모드: 지금 편집은 운영 서버에 저장되지 않습니다. 수정안 파일을 내려받은 뒤 점검·백업·서버 정지 절차로만 적용됩니다.';

    function setVideoSafetyNotice(message = VIDEO_SAFETY_DEFAULT_MESSAGE, state = 'normal') {
        const notice = $('videoSafetyNotice');
        if (!notice) return;
        const resolvedState = state === true ? 'blocked' : (state === false ? 'normal' : state);
        const blocked = resolvedState === 'blocked';
        notice.textContent = message;
        notice.dataset.state = resolvedState;
        notice.setAttribute('role', blocked ? 'alert' : 'status');
        notice.setAttribute('aria-live', blocked ? 'assertive' : 'polite');
        if (blocked) {
            notice.tabIndex = -1;
            notice.focus({ preventScroll: true });
        }
    }

    function restoreLastSavedVideos() {
        try {
            const saved = JSON.parse(lastSavedVideoBody || '[]');
            if (!Array.isArray(saved)) return false;
            videos = saved;
            drawVid();
            return true;
        } catch {
            return false;
        }
    }

    function cloneVideoRows(rows) {
        return JSON.parse(JSON.stringify(Array.isArray(rows) ? rows : []));
    }

    function parseLastSavedVideoRows() {
        const saved = JSON.parse(lastSavedVideoBody || '[]');
        if (!Array.isArray(saved)) throw new Error('saved video catalog is unavailable');
        return saved;
    }

    function syncVisibleVideoRowsFromTable() {
        document.querySelectorAll('#vidTable tr[data-idx]').forEach(tr => {
            const i = +tr.dataset.idx;
            const row = videos[i];
            const cells = tr.children;
            if (!row || cells.length < 9) return;

            row.curriculum = cells[1].innerText.trim();
            row.subCurriculum = cells[2].innerText.trim();
            row.chapter = +cells[3].innerText.trim() || 1;
            const exS = cells[4].innerText.trim();
            const exM = cells[5].innerText.trim();
            const exH = cells[6].innerText.trim();
            if (exS || exM || exH) {
                row.exNum = {};
                if (exS) row.exNum['상'] = +exS;
                if (exM) row.exNum['중'] = +exM;
                if (exH) row.exNum['하'] = +exH;
            } else {
                delete row.exNum;
            }
            row.title = cells[7].innerText.trim();
            row.url = cells[8].innerText.trim();
            const nextMid = extractKollusMid(row.url);
            if (nextMid) row.mid = nextMid;
        });
    }

    function hasCorrectionChanges(summary) {
        return Boolean(
            summary?.removedIds?.length ||
            summary?.midChanges?.length ||
            summary?.newIds?.length ||
            summary?.modifiedIds?.length
        );
    }

    function correctionSummaryText(summary) {
        const midChangedIds = new Set((summary.midChanges || []).map(change => change.id));
        const metadataCount = (summary.modifiedIds || []).filter(id => !midChangedIds.has(id)).length;
        const parts = [];
        if (summary.midChanges.length) parts.push(`MID 변경 ${summary.midChanges.length}건`);
        if (summary.removedIds.length) parts.push(`삭제 ${summary.removedIds.length}건`);
        if (summary.newIds.length) parts.push(`신규 ${summary.newIds.length}건`);
        if (metadataCount) parts.push(`기타 내용 변경 ${metadataCount}건`);
        return parts.length ? parts.join(' · ') : '아직 변경 없음';
    }

    function updateCorrectionControls() {
        if (correctionModeBtn) {
            correctionModeBtn.hidden = correctionMode;
            correctionModeBtn.disabled = !lastSavedVideoBody;
        }
        if (correctionDownloadBtn) correctionDownloadBtn.hidden = !correctionMode;
        if (correctionCancelBtn) correctionCancelBtn.hidden = !correctionMode;
        if (saveVidBtn) saveVidBtn.disabled = correctionMode;
        if (!correctionMode && correctionStatus) {
            correctionStatus.textContent = '수정 모드는 운영 데이터를 즉시 바꾸지 않고 별도 파일만 만듭니다.';
        }
    }

    function updateCorrectionStatus(suffix = '') {
        if (!correctionMode || !correctionBaseVideos) return;
        syncVisibleVideoRowsFromTable();
        const summary = videoCorrectionSummary(correctionBaseVideos, videos);
        if (correctionStatus) {
            correctionStatus.textContent = `서버 미반영 · ${correctionSummaryText(summary)}${suffix}`;
        }
    }

    function enterCorrectionMode() {
        if (saveInFlight) {
            alert('일반 저장이 끝난 뒤 다시 시도하세요.');
            return;
        }
        const confirmed = window.confirm(
            '수정 모드를 켜면 화면을 마지막 저장 상태로 되돌리고 시작합니다.\n' +
            '이후 편집은 서버에 저장되지 않으며, 수정안 파일로만 내려받습니다.'
        );
        if (!confirmed) return;
        let baseRows;
        try {
            baseRows = parseLastSavedVideoRows();
        } catch {
            alert('저장된 영상 목록을 아직 불러오지 못했습니다. 잠시 뒤 다시 시도하세요.');
            return;
        }
        if (autoSaveTimer) clearTimeout(autoSaveTimer);
        autoSaveTimer = null;
        autoSaveClick = false;
        correctionBaseVideos = cloneVideoRows(baseRows);
        videos = cloneVideoRows(baseRows);
        correctionMode = true;
        drawVid();
        updateCorrectionControls();
        setVideoSafetyNotice(VIDEO_CORRECTION_MESSAGE, 'correction');
        updateCorrectionStatus();
    }

    function cancelCorrectionMode() {
        syncVisibleVideoRowsFromTable();
        const summary = videoCorrectionSummary(correctionBaseVideos || [], videos);
        if (hasCorrectionChanges(summary) && !window.confirm('작성 중인 수정안을 버리고 일반 모드로 돌아갈까요?')) {
            return;
        }
        if (autoSaveTimer) clearTimeout(autoSaveTimer);
        autoSaveTimer = null;
        autoSaveClick = false;
        correctionMode = false;
        correctionBaseVideos = null;
        restoreLastSavedVideos();
        updateCorrectionControls();
        setVideoSafetyNotice();
        toast('수정안 취소됨 · 서버 데이터 변화 없음');
    }

    function downloadCorrectionDraft() {
        if (!correctionMode || !correctionBaseVideos) return;
        syncVisibleVideoRowsFromTable();
        const summary = videoCorrectionSummary(correctionBaseVideos, videos);
        if (!hasCorrectionChanges(summary)) {
            alert('변경한 내용이 없습니다.');
            return;
        }
        const draft = buildVideoCorrectionDraft(correctionBaseVideos, videos);
        const blob = new Blob([`${JSON.stringify(draft, null, 2)}\n`], { type: 'application/json;charset=utf-8' });
        const objectUrl = URL.createObjectURL(blob);
        const anchor = document.createElement('a');
        const stamp = new Date().toISOString().replace(/[-:]/g, '').replace(/\.\d{3}Z$/, 'Z');
        anchor.href = objectUrl;
        anchor.download = `video-correction-${stamp}.json`;
        document.body.appendChild(anchor);
        anchor.click();
        anchor.remove();
        setTimeout(() => URL.revokeObjectURL(objectUrl), 0);
        updateCorrectionStatus(' · 수정안 다운로드 완료(아직 서버 미반영)');
        toast('수정안 파일 다운로드 완료');
    }

    correctionModeBtn?.addEventListener('click', enterCorrectionMode);
    correctionDownloadBtn?.addEventListener('click', downloadCorrectionDraft);
    correctionCancelBtn?.addEventListener('click', cancelCorrectionMode);
    updateCorrectionControls();

    function showVideoIdentityBlocked(changes, serverMessage = '') {
        const midCount = Array.isArray(changes?.midChanges) ? changes.midChanges.length : 0;
        const removedCount = Array.isArray(changes?.removedIds) ? changes.removedIds.length : 0;
        const details = [];
        if (midCount) details.push(`기존 MID 변경 ${midCount}건`);
        if (removedCount) details.push(`기존 영상 삭제 ${removedCount}건`);
        const reason = details.length ? details.join(' · ') : '보호된 영상 식별자 변경';
        restoreLastSavedVideos();
        setVideoSafetyNotice(
            `${reason}이 차단되었습니다. ${serverMessage || '입력 화면을 마지막 저장 상태로 되돌렸습니다. 별도 수정 모드에서 처리해야 합니다.'}`,
            true,
        );
        toast('보호된 영상 변경 차단됨');
    }

    function scheduleVideoAutoSave(delay = 800) {
        if (!saveVidBtn) return;
        if (autoSaveTimer) clearTimeout(autoSaveTimer);
        autoSaveTimer = setTimeout(() => {
            autoSaveTimer = null;
            if (correctionMode) {
                updateCorrectionStatus();
                return;
            }
            autoSaveClick = true;
            saveVidBtn.click();
        }, correctionMode ? Math.min(delay, 200) : delay);
    }

    if (vidTable) {
        vidTable.addEventListener('blur', e => {
            if (e.target?.matches?.('td[contenteditable]')) scheduleVideoAutoSave();
        }, true);
        vidTable.addEventListener('click', e => {
            if (e.target?.closest?.('.delV')) scheduleVideoAutoSave();
        });
    }

    function extractKollusMid(url) {
        const raw = String(url || '').trim();
        if (!raw) return '';
        if (window.__adminDemo?.enabled) {
            const demoAsset = raw.match(/\/demo-assets\/videos\/([^/?#]+?)(?:\.[A-Za-z0-9]+)?(?:[?#].*)?$/i);
            if (demoAsset && /^[A-Za-z0-9_-]+$/.test(demoAsset[1])) return demoAsset[1];
            if (/^demo-[A-Za-z0-9_-]+$/.test(raw)) return raw;
        }

        try {
            const u = new URL(raw, location.origin);
            if (window.__adminDemo?.enabled && u.hostname === 'demo.invalid') {
                for (const key of ['mid', 'm', 'media_content_key', 'content_key']) {
                    const cand = String(u.searchParams.get(key) || '').trim();
                    if (/^[A-Za-z0-9_-]+$/.test(cand)) return cand;
                }
                const parts = u.pathname.split('/').filter(Boolean);
                const cand = String(parts[parts.length - 1] || '').replace(/\.[A-Za-z0-9]+$/, '');
                if (/^[A-Za-z0-9_-]+$/.test(cand)) return cand;
            }
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
        lastSavedVideoBody = JSON.stringify(videos);
        drawVid();
        updateCorrectionControls();
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

        // ⑥ 편집 셀 blur 시 현재 화면을 배열에 반영한다. 저장 여부는 모드가 결정한다.
        vidTable.querySelectorAll('td[contenteditable]').forEach(td => {
            td.addEventListener('blur', () => {
                syncVisibleVideoRowsFromTable();
                if (correctionMode) updateCorrectionStatus();
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
    filterDiv.className = 'video-filter-row';
    filterDiv.innerHTML = `
  <label class="video-filter-control">
    <span>커리큘럼 선택</span>
    <select id="curriculumFilter">
      <option value="">전체</option>
      ${maincurricula.map(m => `<option value="${m}">${m}</option>`).join('')}
    </select>
  </label>
  <label class="video-filter-control">
    <span>세부 선택</span>
    <select id="subCurriculumFilter">
      <option value="">전체</option>
      ${subCurricula.map(s => `<option value="${s}">${s}</option>`).join('')}
    </select>
  </label>
  <label class="video-filter-control video-search-control">
    <span>검색</span>
    <input id="videoSearch" type="search" autocomplete="off" placeholder="영상 검색 (초성/영타 검색 · 띄어쓰기=AND)">
  </label>
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
                id: nextVideoId(videos),
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
    document.getElementById('addVid')?.addEventListener('click', () => scheduleVideoAutoSave());



    /* 영상 저장 */
    saveVidBtn.onclick = () => {
        const isAutoSave = autoSaveClick;
        autoSaveClick = false;
        if (!isAutoSave && autoSaveTimer) {
            clearTimeout(autoSaveTimer);
            autoSaveTimer = null;
        }
        syncVisibleVideoRowsFromTable();
        if (correctionMode) {
            updateCorrectionStatus();
            toast('수정 모드에서는 서버 저장 안 됨');
            return;
        }

        // ④ 서버에 저장
        const body = JSON.stringify(videos);
        if (body === lastSavedVideoBody) {
            if (!isAutoSave) toast('변경사항 없음');
            return;
        }
        try {
            const previousVideos = JSON.parse(lastSavedVideoBody || '[]');
            const protectedChanges = protectedVideoIdentityChanges(previousVideos, videos);
            if (protectedChanges.removedIds.length || protectedChanges.midChanges.length) {
                showVideoIdentityBlocked(protectedChanges);
                return;
            }
        } catch {
            // The server remains authoritative if the local comparison snapshot is unavailable.
        }
        if (saveInFlight) {
            queuedSaveMode = isAutoSave ? (queuedSaveMode || 'auto') : 'manual';
            return;
        }

        saveInFlight = true;
        fetch('/api/videos', {
            method: 'POST',
            headers: CT,
            body
        })
            .then(async res => {
                if (!res.ok) {
                    const payload = await res.json().catch(() => ({}));
                    const error = new Error(payload?.message || `video save failed: ${res.status}`);
                    error.status = res.status;
                    error.payload = payload;
                    throw error;
                }
                lastSavedVideoBody = body;
                setVideoSafetyNotice();
                toast(isAutoSave ? '영상 자동 저장 완료' : '영상 저장 완료');
            })
            .catch(err => {
                if (err?.status === 409 && err?.payload?.error === VIDEO_IDENTITY_CHANGE_ERROR) {
                    showVideoIdentityBlocked(err.payload, err.payload.message);
                    return;
                }
                console.error('[video-manage] save failed', err);
                toast('영상 저장 실패');
            })
            .finally(() => {
                saveInFlight = false;
                if (!queuedSaveMode) return;
                const mode = queuedSaveMode;
                queuedSaveMode = null;
                autoSaveClick = mode === 'auto';
                saveVidBtn.click();
            });
    };

})();
