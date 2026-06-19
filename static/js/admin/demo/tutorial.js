const TUTORIAL_STORAGE_KEY = 'academy.adminDemo.tutorial.v1';
const STYLE_ID = 'adminDemoTutorialStyles';
const HIGHLIGHT_CLASS = 'admin-demo-tutorial-highlight';
const PRACTICED_CLASS = 'is-practiced';
const SPOTLIGHT_MARGIN = 12;

const PAGE_MISSIONS = {
  admin: {
    title: '관리자 운영',
    subtitle: '오늘 수업 운영 흐름을 더미 데이터로 연습합니다.',
    missions: [
      {
        id: 'admin-date',
        title: '운영 날짜 확인',
        body: '날짜를 바꾸면 오늘 목록과 로그 기준이 함께 바뀝니다. 먼저 기준일을 확인하세요.',
        target: ['#adminDateMount .adb-wrap', '#adb_date_display', '#adminDateMount', '#adminDate', '#selectedDate', 'input[type="date"]'],
      },
      {
        id: 'admin-today',
        title: '오늘 학생 목록 점검',
        body: '출석, 연락, 도착 시간, 보강 상태를 한 줄에서 처리하는 흐름을 익힙니다.',
        target: ['#todayTable', '#todayBody', '.today-list', '.today-table'],
      },
      {
        id: 'admin-log',
        title: '수업 기록과 숙제 저장',
        body: '학생 행의 기록 버튼을 열어 특이사항, 숙제, 진도 상태를 더미로 저장해 봅니다.',
        target: ['button[data-action*="log"]', '.log-btn', '.btn-log', '#logModal'],
      },
      {
        id: 'admin-video',
        title: '영상 배정 확인',
        body: '영상 배정 모달에서 자동/수동 배정과 시청 진도 표시를 확인합니다.',
        target: ['button[data-action*="video"]', '.video-btn', '.btn-video', '#videoModal'],
      },
      {
        id: 'admin-test',
        title: '테스트 배정 확인',
        body: '테스트 배정 모달에서 단원평가, 복습, 학교 기출 배정 상태를 확인합니다.',
        target: ['button[data-action*="test"]', '.test-btn', '.btn-test', '#testModal'],
      },
      {
        id: 'admin-chat',
        title: '관리자 챗봇 활용',
        body: '데모 챗봇은 합성 데이터만 기준으로 답합니다. 운영 질문 예시를 연습하세요.',
        target: ['#adminChatbot', '#adminChatPanel', '#adminChatToggle', '.admin-chatbot'],
      },
      {
        id: 'admin-nav',
        title: '연계 페이지 이동',
        body: '전체학생, 학교일정, 영상관리, 테스트관리도 같은 더미 데이터로 이어집니다.',
        target: ['.global-links', 'nav', 'header'],
      },
    ],
  },
  students: {
    title: '전체학생',
    subtitle: '학생 명단과 운영 데이터가 다른 데모 페이지와 연결되는 방식을 익힙니다.',
    missions: [
      {
        id: 'students-search',
        title: '명단 검색과 정렬',
        body: '이름, 학교, 과정 검색으로 원하는 더미 학생을 빠르게 찾습니다.',
        target: ['#allStudentSearchInput', '#searchInput', '#allSearch', 'input[type="search"]', '#studentSearch'],
      },
      {
        id: 'students-inline',
        title: '학생 정보 직접 수정',
        body: '학교, 학년, 요일, 교재 같은 셀을 수정하면 데모 세션에만 저장됩니다.',
        target: ['#studentsTable', '#allTable', 'table tbody tr', '.students-table'],
      },
      {
        id: 'students-add',
        title: '신규 학생 추가',
        body: '상단 추가 바에서 학생을 만들면 더미 명단에만 추가됩니다.',
        target: ['#newStuMount', '#ns_add', '.ns-wrap'],
      },
      {
        id: 'students-clone-delete',
        title: '복제와 삭제 연습',
        body: '복제/삭제 버튼은 실제 명단을 건드리지 않고 데모 store만 바꿉니다.',
        target: ['.btn-clone-stu', '.btn-delete-stu', '.btn-del-stu', 'table tbody tr'],
      },
      {
        id: 'students-progress',
        title: '누적 진도 확인',
        body: '학생별 진도 팝업에서 영상/테스트 진행 상태가 연결되는 방식을 확인합니다.',
        target: ['.progress-btn', '.btn-progress', '[data-progress]', '#progressModal'],
      },
      {
        id: 'students-export',
        title: '명단 요약 활용',
        body: '명단 내보내기와 요약 도구는 더미 학생만 대상으로 연습합니다.',
        target: ['#chatRosterExport', '#copyRoster', '.roster-export', 'header.topbar'],
      },
    ],
  },
  calendar: {
    title: '학교일정',
    subtitle: '학교, 학년, 시험 범위 정보를 더미 일정으로 편집합니다.',
    missions: [
      {
        id: 'calendar-page',
        title: '연도와 시험 페이지 선택',
        body: '연도, 학기, 중간/기말 페이지를 바꾸며 일정 묶음을 확인합니다.',
        target: ['#yearSelect', '#semesterSelect', '#examSelect', '.page-controls'],
      },
      {
        id: 'calendar-school',
        title: '학교 행 추가',
        body: '학교 행을 추가하고 학교명을 입력하는 흐름을 연습합니다.',
        target: ['#addSchool', '[data-action="add-school"]', '.school-row'],
      },
      {
        id: 'calendar-grade',
        title: '학년/범위 입력',
        body: '학년별 시험 범위와 진도 메모를 입력해 전체학생 데이터와 맞춥니다.',
        target: ['.grade-row', '.gr-grade', 'tbody'],
      },
      {
        id: 'calendar-save',
        title: '자동 저장 확인',
        body: '수정 후 저장 상태 문구가 바뀌는지 확인합니다. 실제 school_calendar.json은 쓰지 않습니다.',
        target: ['#saveCalendar', '#saveStatus', '.save-status'],
      },
    ],
  },
  videos: {
    title: '영상관리',
    subtitle: '더미 영상 카탈로그가 관리자 배정 화면과 연결되는 방식을 익힙니다.',
    missions: [
      {
        id: 'videos-filter',
        title: '과정별 영상 필터',
        body: '커리큘럼, 세부과정, 검색어로 필요한 더미 영상을 찾습니다.',
        target: ['#curriculumFilter', '#subCurriculumFilter', '#videoSearch'],
      },
      {
        id: 'videos-add',
        title: '영상 추가 흐름',
        body: '추가 폼으로 새 더미 영상을 만들고 목록에 반영되는지 확인합니다.',
        target: ['#addVid', '#vTitle', '#vUrl', '#videoSection'],
      },
      {
        id: 'videos-edit',
        title: '영상 메타데이터 수정',
        body: '챕터, 제목, URL 셀을 수정한 뒤 저장 버튼으로 데모 store에 저장합니다.',
        target: ['#vidTable', '#saveVid', 'td[contenteditable]'],
      },
      {
        id: 'videos-delete',
        title: '삭제와 복구 연습',
        body: '삭제 버튼을 눌러도 운영 영상 데이터는 바뀌지 않습니다. 필요하면 데모 초기화로 되돌립니다.',
        target: ['.delV', '#vidTable'],
      },
    ],
  },
  tests: {
    title: '테스트관리',
    subtitle: '더미 테스트 카탈로그와 배정 규칙, 통계를 연습합니다.',
    missions: [
      {
        id: 'tests-filter',
        title: '테스트 분류 탐색',
        body: '단원평가, 복습, 학교 기출, 일산 기출을 바꾸며 카탈로그 구조를 확인합니다.',
        target: ['#cfgType', '#cfgCur', '#testList'],
      },
      {
        id: 'tests-editor',
        title: '테스트 항목 편집',
        body: '시험명, 문항 수, 정답 링크 메타데이터를 수정하고 저장 흐름을 확인합니다.',
        target: ['#testEditor', '#testName', '#saveTest', '#cfgName'],
      },
      {
        id: 'tests-rules',
        title: '자동 배정 규칙 확인',
        body: '레벨과 난이도 매칭 규칙을 바꾸면 데모 테스트 배정 기준이 바뀝니다.',
        target: ['#rulesGrid', '.rule-grid', '#autoAssignRules'],
      },
      {
        id: 'tests-csv',
        title: 'CSV 가져오기 흐름',
        body: '템플릿 다운로드와 가져오기 UI를 확인합니다. 데모에서는 합성 카탈로그만 저장됩니다.',
        target: ['#csvImport', '#csvFile', '#downloadTemplate'],
      },
      {
        id: 'tests-stats',
        title: '테스트 통계 읽기',
        body: '응시 수, 평균, 상세 기록은 더미 통계로 표시됩니다.',
        target: ['#statsSummary', '#statsTable', '#statsDetail'],
      },
    ],
  },
};

export function installDemoTutorial({ window: rootWindow = window, demo = {} } = {}) {
  const doc = rootWindow.document;
  if (!doc?.body || doc.body.dataset.adminDemoTutorialInstalled === '1') return;
  doc.body.dataset.adminDemoTutorialInstalled = '1';
  injectStyles(doc);

  const pageKey = resolvePageKey(rootWindow.location.pathname);
  const page = PAGE_MISSIONS[pageKey] || PAGE_MISSIONS.admin;
  const state = loadState(rootWindow);
  const api = createTutorialApi(rootWindow, demo, pageKey, page, state);
  rootWindow.__adminDemoTutorial = api;
  rootWindow.addEventListener('admin-demo:tutorial-open', () => api.open());
  rootWindow.addEventListener('keydown', event => {
    if (event.key === 'Escape') api.close();
  });
  doc.addEventListener('click', event => api.markPractice(event.target), true);
  doc.addEventListener('change', event => api.markPractice(event.target), true);
  doc.addEventListener('input', event => api.markPractice(event.target), true);
  api.mount();
  if (!state.seenPages[pageKey]) api.open({ firstRun: true });
}

function resolvePageKey(pathname) {
  const path = String(pathname || '').replace(/\/+$/, '') || '/';
  if (path === '/demo/rh3123/students') return 'students';
  if (path === '/demo/rh3123/school-cal') return 'calendar';
  if (path === '/demo/rh3123/video-manage') return 'videos';
  if (path === '/demo/rh3123/tests') return 'tests';
  return 'admin';
}

function defaultState() {
  return {
    version: 1,
    seenPages: {},
    indexByPage: {},
    completedByPage: {},
    practicedByPage: {},
    open: false,
  };
}

function loadState(rootWindow) {
  try {
    const raw = rootWindow.sessionStorage.getItem(TUTORIAL_STORAGE_KEY);
    if (!raw) return defaultState();
    const parsed = JSON.parse(raw);
    if (!parsed || parsed.version !== 1) return defaultState();
    return {
      ...defaultState(),
      ...parsed,
      seenPages: parsed.seenPages || {},
      indexByPage: parsed.indexByPage || {},
      completedByPage: parsed.completedByPage || {},
      practicedByPage: parsed.practicedByPage || {},
    };
  } catch {
    return defaultState();
  }
}

function saveState(rootWindow, state) {
  try {
    rootWindow.sessionStorage.setItem(TUTORIAL_STORAGE_KEY, JSON.stringify(state));
  } catch {
  }
}

function createTutorialApi(rootWindow, demo, pageKey, page, state) {
  const doc = rootWindow.document;
  let host = null;
  let targetEl = null;
  let spotlightEl = null;
  let spotlightFrameEl = null;
  let spotlightLabelEl = null;
  let retryTimer = null;
  let rafId = 0;

  function completedSet() {
    const ids = state.completedByPage[pageKey] || [];
    return new Set(ids);
  }

  function practicedSet() {
    const ids = state.practicedByPage[pageKey] || [];
    return new Set(ids);
  }

  function currentIndex() {
    const index = Number(state.indexByPage[pageKey] || 0);
    return Math.max(0, Math.min(page.missions.length - 1, index));
  }

  function currentMission() {
    return page.missions[currentIndex()];
  }

  function persist() {
    saveState(rootWindow, state);
  }

  function setOpen(open) {
    state.open = !!open;
    state.seenPages[pageKey] = true;
    persist();
    render();
    if (state.open) highlightCurrentTarget();
    else clearHighlight();
  }

  function goTo(index) {
    state.indexByPage[pageKey] = Math.max(0, Math.min(page.missions.length - 1, index));
    persist();
    render();
    highlightCurrentTarget();
  }

  function markMissionComplete(id) {
    const set = completedSet();
    set.add(id);
    state.completedByPage[pageKey] = [...set];
    persist();
    demo.showMessage?.('미션 완료. 다음 기능을 연습하세요.', { quiet: true });
  }

  function markMissionPracticed(id) {
    const set = practicedSet();
    if (set.has(id)) return;
    set.add(id);
    state.practicedByPage[pageKey] = [...set];
    persist();
    render();
  }

  function completeCurrent() {
    const mission = currentMission();
    if (!mission) return;
    markMissionComplete(mission.id);
    if (currentIndex() < page.missions.length - 1) goTo(currentIndex() + 1);
    else render();
  }

  function resetGuide() {
    state.completedByPage[pageKey] = [];
    state.practicedByPage[pageKey] = [];
    state.indexByPage[pageKey] = 0;
    state.open = true;
    persist();
    render();
    highlightCurrentTarget();
  }

  function mount() {
    host = doc.createElement('div');
    host.className = 'admin-demo-tutorial-root';
    doc.body.appendChild(host);
    render();
    highlightCurrentTarget();
  }

  function render() {
    if (!host) return;
    const completed = completedSet();
    const practiced = practicedSet();
    const total = page.missions.length;
    const completeCount = page.missions.filter(mission => completed.has(mission.id)).length;
    const percent = total ? Math.round((completeCount / total) * 100) : 0;
    const mission = currentMission();
    const missionPracticed = mission ? practiced.has(mission.id) : false;
    const minimized = !state.open;

    host.innerHTML = `
      <button type="button" class="admin-demo-guide-launcher" ${minimized ? '' : 'hidden'} aria-label="데모 가이드 열기">
        데모 가이드
        <span>${completeCount}/${total}</span>
      </button>
      <section class="admin-demo-guide-panel" ${minimized ? 'hidden' : ''} role="dialog" aria-modal="false" aria-label="데모 훈련 가이드">
        <header class="admin-demo-guide-head">
          <div>
            <p class="admin-demo-guide-kicker">훈련 미션 · ${escapeHtml(page.title)}</p>
            <h2>${escapeHtml(page.subtitle)}</h2>
          </div>
          <button type="button" class="admin-demo-guide-close" aria-label="가이드 닫기">닫기</button>
        </header>
        <div class="admin-demo-guide-progress" aria-label="미션 진행률 ${percent}%">
          <span style="width:${percent}%"></span>
        </div>
        <div class="admin-demo-guide-score">
          <strong>${percent}%</strong>
          <span>${completeCount * 20} XP · ${completeCount}/${total} 완료</span>
        </div>
        <article class="admin-demo-guide-current ${missionPracticed ? PRACTICED_CLASS : ''}">
          <p class="admin-demo-guide-step">미션 ${currentIndex() + 1}</p>
          <h3>${escapeHtml(mission?.title || '')}</h3>
          <p>${escapeHtml(mission?.body || '')}</p>
          <div class="admin-demo-guide-status">${missionPracticed ? '실습 감지됨' : '대상 컨트롤을 눌러 보고 완료하세요.'}</div>
        </article>
        <nav class="admin-demo-guide-list" aria-label="미션 목록">
          ${page.missions.map((item, index) => `
            <button type="button" class="${index === currentIndex() ? 'is-current' : ''} ${completed.has(item.id) ? 'is-complete' : ''}" data-demo-mission-index="${index}">
              <span>${escapeHtml(String(index + 1))}</span>
              ${escapeHtml(item.title)}
            </button>
          `).join('')}
        </nav>
        <footer class="admin-demo-guide-actions">
          <button type="button" data-demo-guide-action="target">대상 찾기</button>
          <button type="button" data-demo-guide-action="prev">이전</button>
          <button type="button" data-demo-guide-action="complete">완료</button>
          <button type="button" data-demo-guide-action="skip">스킵</button>
          <button type="button" data-demo-guide-action="reset">재시작</button>
        </footer>
      </section>
    `;

    host.querySelector('.admin-demo-guide-launcher')?.addEventListener('click', () => setOpen(true));
    host.querySelector('.admin-demo-guide-close')?.addEventListener('click', () => setOpen(false));
    host.querySelectorAll('[data-demo-mission-index]').forEach(button => {
      button.addEventListener('click', () => goTo(Number(button.dataset.demoMissionIndex || 0)));
    });
    host.querySelector('[data-demo-guide-action="target"]')?.addEventListener('click', () => highlightCurrentTarget({ forceScroll: true }));
    host.querySelector('[data-demo-guide-action="prev"]')?.addEventListener('click', () => goTo(currentIndex() - 1));
    host.querySelector('[data-demo-guide-action="complete"]')?.addEventListener('click', completeCurrent);
    host.querySelector('[data-demo-guide-action="skip"]')?.addEventListener('click', () => {
      if (currentIndex() < page.missions.length - 1) goTo(currentIndex() + 1);
      else setOpen(false);
    });
    host.querySelector('[data-demo-guide-action="reset"]')?.addEventListener('click', resetGuide);
  }

  function findTarget(mission) {
    const selectors = Array.isArray(mission?.target) ? mission.target : [];
    for (const selector of selectors) {
      try {
        const candidates = doc.querySelectorAll(selector);
        for (const found of candidates) {
          if (isUsableTarget(found)) return found;
        }
      } catch {
      }
    }
    return doc.querySelector('main') || doc.body;
  }

  function isUsableTarget(element) {
    if (!element || !element.isConnected) return false;
    if (element.closest?.('.admin-demo-tutorial-root')) return false;
    const rect = element.getBoundingClientRect();
    const style = rootWindow.getComputedStyle(element);
    return rect.width > 0
      && rect.height > 0
      && style.display !== 'none'
      && style.visibility !== 'hidden'
      && style.opacity !== '0';
  }

  function clearHighlight() {
    if (retryTimer) {
      rootWindow.clearTimeout(retryTimer);
      retryTimer = null;
    }
    if (rafId) {
      rootWindow.cancelAnimationFrame(rafId);
      rafId = 0;
    }
    if (targetEl) {
      targetEl.classList.remove(HIGHLIGHT_CLASS);
      targetEl.removeAttribute('data-admin-demo-guide-target');
      targetEl = null;
    }
    if (spotlightEl) {
      spotlightEl.remove();
      spotlightEl = null;
      spotlightFrameEl = null;
      spotlightLabelEl = null;
    }
    rootWindow.removeEventListener('resize', scheduleSpotlightUpdate);
    rootWindow.removeEventListener('scroll', scheduleSpotlightUpdate, true);
  }

  function highlightCurrentTarget(options = {}) {
    clearHighlight();
    if (!state.open) return;
    const mission = currentMission();
    targetEl = findTarget(mission);
    if (!targetEl) return;
    targetEl.classList.add(HIGHLIGHT_CLASS);
    targetEl.setAttribute('data-admin-demo-guide-target', mission?.title || '미션 대상');
    ensureSpotlight(mission);
    updateSpotlight();
    rootWindow.addEventListener('resize', scheduleSpotlightUpdate, { passive: true });
    rootWindow.addEventListener('scroll', scheduleSpotlightUpdate, { passive: true, capture: true });
    if (options.forceScroll !== false) {
      try {
        targetEl.scrollIntoView({ block: 'center', inline: 'nearest', behavior: options.forceScroll ? 'smooth' : 'auto' });
        scheduleSpotlightUpdate();
        rootWindow.setTimeout(scheduleSpotlightUpdate, options.forceScroll ? 220 : 80);
      } catch {
      }
    }
    retryTimer = rootWindow.setTimeout(() => {
      const fresh = findTarget(currentMission());
      if (fresh && fresh !== targetEl) highlightCurrentTarget({ forceScroll: false });
      else scheduleSpotlightUpdate();
    }, 900);
  }

  function ensureSpotlight(mission) {
    spotlightEl = doc.createElement('div');
    spotlightEl.className = 'admin-demo-spotlight';
    spotlightEl.setAttribute('aria-hidden', 'true');
    spotlightEl.innerHTML = `
      <div class="admin-demo-spotlight-frame"></div>
      <span class="admin-demo-spotlight-label">여기를 눌러 보세요 · ${escapeHtml(mission?.title || '미션 대상')}</span>
    `;
    doc.body.appendChild(spotlightEl);
    spotlightFrameEl = spotlightEl.querySelector('.admin-demo-spotlight-frame');
    spotlightLabelEl = spotlightEl.querySelector('.admin-demo-spotlight-label');
  }

  function scheduleSpotlightUpdate() {
    if (rafId) return;
    rafId = rootWindow.requestAnimationFrame(() => {
      rafId = 0;
      updateSpotlight();
    });
  }

  function updateSpotlight() {
    if (!targetEl || !spotlightEl || !spotlightFrameEl) return;
    const rect = targetEl.getBoundingClientRect();
    const viewportWidth = rootWindow.innerWidth || doc.documentElement.clientWidth || 0;
    const viewportHeight = rootWindow.innerHeight || doc.documentElement.clientHeight || 0;
    const targetVisible = rect.width > 0
      && rect.height > 0
      && rect.bottom > 0
      && rect.right > 0
      && rect.top < viewportHeight
      && rect.left < viewportWidth;

    if (!targetVisible) {
      spotlightEl.hidden = true;
      return;
    }

    spotlightEl.hidden = false;
    const left = Math.max(8, rect.left - SPOTLIGHT_MARGIN);
    const top = Math.max(8, rect.top - SPOTLIGHT_MARGIN);
    const right = Math.min(viewportWidth - 8, rect.right + SPOTLIGHT_MARGIN);
    const bottom = Math.min(viewportHeight - 8, rect.bottom + SPOTLIGHT_MARGIN);
    const width = Math.max(44, right - left);
    const height = Math.max(36, bottom - top);
    const radius = Math.min(18, Math.max(8, Math.round(Math.min(width, height) / 8)));
    spotlightEl.style.setProperty('--spotlight-left', `${left}px`);
    spotlightEl.style.setProperty('--spotlight-top', `${top}px`);
    spotlightEl.style.setProperty('--spotlight-width', `${width}px`);
    spotlightEl.style.setProperty('--spotlight-height', `${height}px`);
    spotlightEl.style.setProperty('--spotlight-radius', `${radius}px`);
    positionSpotlightLabel({ left, top, width, height, viewportWidth, viewportHeight });
  }

  function positionSpotlightLabel({ left, top, width, height, viewportWidth, viewportHeight }) {
    if (!spotlightLabelEl) return;
    const guideActions = doc.querySelector('.admin-demo-guide-actions');
    const actionsRect = guideActions?.getBoundingClientRect?.();
    const labelHeight = 34;
    const lowerTop = top + height + 10;
    const upperTop = top - labelHeight - 10;
    const lowerOverlapsActions = actionsRect
      && lowerTop + labelHeight > actionsRect.top - 6
      && lowerTop < actionsRect.bottom + 6;
    const canUseLower = lowerTop + labelHeight <= viewportHeight - 10 && !lowerOverlapsActions;
    const labelTop = canUseLower
      ? lowerTop
      : Math.max(10, upperTop);
    const labelLeft = Math.min(
      Math.max(10, left + Math.min(width, 24)),
      Math.max(10, viewportWidth - 260)
    );
    spotlightLabelEl.style.left = `${labelLeft}px`;
    spotlightLabelEl.style.top = `${labelTop}px`;
  }

  function markPractice(target) {
    if (!state.open || !targetEl || !target) return;
    if (target === targetEl || targetEl.contains(target)) {
      const mission = currentMission();
      if (mission) markMissionPracticed(mission.id);
    }
  }

  return {
    mount,
    open: () => setOpen(true),
    close: () => setOpen(false),
    reset: resetGuide,
    markPractice,
  };
}

function injectStyles(doc) {
  if (doc.getElementById(STYLE_ID)) return;
  const style = doc.createElement('style');
  style.id = STYLE_ID;
  style.textContent = `
    .admin-demo-tutorial-root {
      color: #172033;
      font-family: Apple SD Gothic Neo, Noto Sans KR, Malgun Gothic, system-ui, sans-serif;
    }
    .admin-demo-guide-launcher {
      position: fixed;
      left: 18px;
      bottom: 18px;
      z-index: 10020;
      display: inline-flex;
      align-items: center;
      gap: 8px;
      min-height: 38px;
      padding: 0 12px;
      border: 1px solid #174ea6;
      border-radius: 8px;
      background: #ffffff;
      color: #174ea6;
      font-weight: 800;
      box-shadow: 0 8px 22px rgba(23, 32, 51, .18);
      cursor: pointer;
    }
    .admin-demo-guide-launcher span {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 36px;
      min-height: 24px;
      border-radius: 6px;
      background: #eaf2ff;
      color: #174ea6;
      font-size: 12px;
    }
    .admin-demo-guide-panel {
      position: fixed;
      left: 18px;
      bottom: 18px;
      z-index: 10020;
      width: min(440px, calc(100vw - 36px));
      max-height: min(720px, calc(100vh - 36px));
      overflow: auto;
      border: 1px solid rgba(23, 32, 51, .16);
      border-radius: 8px;
      background: #ffffff;
      box-shadow: 0 18px 45px rgba(23, 32, 51, .24);
    }
    .admin-demo-guide-head {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      padding: 14px 14px 10px;
      border-bottom: 1px solid #e7edf7;
    }
    .admin-demo-guide-kicker,
    .admin-demo-guide-step {
      margin: 0 0 4px;
      color: #4b647f;
      font-size: 12px;
      font-weight: 800;
    }
    .admin-demo-guide-head h2,
    .admin-demo-guide-current h3 {
      margin: 0;
      color: #172033;
      font-size: 16px;
      line-height: 1.35;
      letter-spacing: 0;
    }
    .admin-demo-guide-current h3 {
      font-size: 15px;
    }
    .admin-demo-guide-close,
    .admin-demo-guide-actions button,
    .admin-demo-guide-list button {
      min-height: 32px;
      border: 1px solid #d5dfec;
      border-radius: 6px;
      background: #ffffff;
      color: #172033;
      font: inherit;
      font-size: 13px;
      font-weight: 800;
      cursor: pointer;
    }
    .admin-demo-guide-close {
      min-width: 48px;
      align-self: flex-start;
    }
    .admin-demo-guide-progress {
      height: 8px;
      background: #e7edf7;
    }
    .admin-demo-guide-progress span {
      display: block;
      height: 100%;
      background: linear-gradient(90deg, #174ea6, #0f8b8d);
      transition: width .18s ease;
    }
    .admin-demo-guide-score {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 10px;
      padding: 10px 14px 0;
      color: #4b647f;
      font-size: 13px;
    }
    .admin-demo-guide-score strong {
      color: #174ea6;
      font-size: 18px;
    }
    .admin-demo-guide-current {
      margin: 12px 14px;
      padding: 12px;
      border: 1px solid #d9e5f5;
      border-radius: 8px;
      background: #f7fbff;
    }
    .admin-demo-guide-current p {
      margin: 6px 0 0;
      font-size: 13px;
      line-height: 1.55;
      color: #26364b;
    }
    .admin-demo-guide-status {
      margin-top: 10px;
      padding: 7px 8px;
      border-radius: 6px;
      background: #edf7ed;
      color: #17623a;
      font-size: 12px;
      font-weight: 800;
    }
    .admin-demo-guide-current:not(.is-practiced) .admin-demo-guide-status {
      background: #fff6dc;
      color: #7a4b00;
    }
    .admin-demo-guide-list {
      display: grid;
      gap: 6px;
      padding: 0 14px 12px;
    }
    .admin-demo-guide-list button {
      display: grid;
      grid-template-columns: 28px 1fr;
      align-items: center;
      gap: 8px;
      width: 100%;
      padding: 6px 8px;
      text-align: left;
      line-height: 1.35;
    }
    .admin-demo-guide-list button span {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 24px;
      border-radius: 6px;
      background: #eef3f9;
      color: #4b647f;
      font-size: 12px;
    }
    .admin-demo-guide-list button.is-current {
      border-color: #174ea6;
      background: #eef6ff;
    }
    .admin-demo-guide-list button.is-complete span {
      background: #17623a;
      color: #ffffff;
    }
    .admin-demo-guide-actions {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      padding: 12px 14px 14px;
      border-top: 1px solid #e7edf7;
      background: #fbfdff;
    }
    .admin-demo-guide-actions button {
      flex: 1 1 auto;
      padding: 0 10px;
    }
    .admin-demo-guide-actions [data-demo-guide-action="complete"] {
      border-color: #17623a;
      background: #17623a;
      color: #ffffff;
    }
    .admin-demo-tutorial-highlight {
      position: relative !important;
      z-index: 10032 !important;
      outline: 3px solid #0f8b8d !important;
      outline-offset: 3px !important;
      box-shadow: 0 0 0 7px rgba(15, 139, 141, .24), 0 12px 35px rgba(0, 0, 0, .28) !important;
      scroll-margin: 110px;
    }
    .admin-demo-spotlight {
      position: fixed;
      inset: 0;
      z-index: 10025;
      pointer-events: none;
      --spotlight-left: 50vw;
      --spotlight-top: 50vh;
      --spotlight-width: 120px;
      --spotlight-height: 64px;
      --spotlight-radius: 12px;
      overflow: hidden;
    }
    .admin-demo-spotlight-frame {
      position: absolute;
      left: var(--spotlight-left);
      top: var(--spotlight-top);
      width: var(--spotlight-width);
      height: var(--spotlight-height);
      border: 2px solid #5ee0d2;
      border-radius: var(--spotlight-radius);
      box-shadow:
        0 0 0 2px rgba(255, 255, 255, .92),
        0 0 0 9px rgba(94, 224, 210, .18),
        0 0 34px rgba(94, 224, 210, .58),
        0 0 0 9999px rgba(7, 12, 22, .64);
      animation: admin-demo-spotlight-pulse 1.45s ease-in-out infinite;
    }
    .admin-demo-spotlight-label {
      position: fixed;
      display: inline-flex;
      align-items: center;
      max-width: min(310px, calc(100vw - 20px));
      min-height: 30px;
      padding: 6px 10px;
      border: 1px solid rgba(94, 224, 210, .65);
      border-radius: 8px;
      background: #ffffff;
      color: #12363f;
      font-size: 13px;
      font-weight: 900;
      line-height: 1.35;
      box-shadow: 0 12px 32px rgba(7, 12, 22, .28);
      word-break: keep-all;
      overflow-wrap: anywhere;
    }
    .admin-demo-spotlight-label::before {
      content: '';
      width: 8px;
      height: 8px;
      margin-right: 7px;
      border-radius: 50%;
      background: #0f8b8d;
      box-shadow: 0 0 0 5px rgba(15, 139, 141, .16);
      flex: 0 0 auto;
    }
    @keyframes admin-demo-spotlight-pulse {
      0%, 100% {
        transform: scale(1);
      }
      50% {
        transform: scale(1.018);
      }
    }
    @media (max-width: 640px) {
      .admin-demo-guide-panel {
        left: 10px;
        right: 10px;
        bottom: 10px;
        width: auto;
        max-height: calc(100vh - 20px);
      }
      .admin-demo-guide-launcher {
        left: 10px;
        bottom: 10px;
      }
      .admin-demo-guide-head {
        align-items: flex-start;
      }
      .admin-demo-guide-actions button {
        flex-basis: calc(50% - 4px);
      }
      .admin-demo-spotlight-label {
        max-width: calc(100vw - 20px);
        font-size: 12px;
      }
    }
    @media (prefers-reduced-motion: reduce) {
      .admin-demo-spotlight-frame {
        animation: none;
      }
    }
  `;
  doc.head.appendChild(style);
}

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, ch => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
  }[ch]));
}
